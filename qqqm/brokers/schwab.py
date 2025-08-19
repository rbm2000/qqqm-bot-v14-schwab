import os, time, json, threading, base64, urllib.parse, websocket, ssl, uuid
from datetime import datetime, timedelta
from ..config import load_config
from ..util import http_request, OAuthStore, discord, get_limiter
from .base import Broker

class SchwabBroker(Broker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cfg = load_config()
        self.oauth = self.cfg.schwab_oauth
        self.end = self.cfg.schwab_endpoints
        self._access = None
        self._access_exp = 0
        self._refresh = None
        self._lock = threading.Lock()
        self._stream = None
        self._stream_thread = None
        self._stream_connected = False
        self.account_hashes = {}

        tokens = OAuthStore.load()
        self._access = tokens.get("access_token")
        self._refresh = tokens.get("refresh_token")
        try:
            self._access_exp = time.time() + float(tokens.get("expires_in", 0))
        except Exception:
            self._access_exp = 0

    # ---------- OAuth Flow ----------
    def auth_url(self) -> str:
        params = {
            "client_id": self.oauth.client_id,
            "redirect_uri": self.oauth.redirect_uri,
        }
        return self.oauth.auth_url + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str):
        data = { "grant_type": "authorization_code", "code": code, "redirect_uri": self.oauth.redirect_uri }
        auth = (self.oauth.client_id, self.oauth.client_secret)
        r = http_request("POST", self.oauth.token_url, headers={}, data=data, auth=auth, timeout=20)
        j = r.json()
        self._set_tokens(j)

    def refresh_token(self):
        if not self._refresh:
            raise RuntimeError("No refresh token on file; restart OAuth authorization")
        data = { "grant_type": "refresh_token", "refresh_token": self._refresh }
        auth = (self.oauth.client_id, self.oauth.client_secret)
        r = http_request("POST", self.oauth.token_url, headers={}, data=data, auth=auth, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"Refresh failed: {r.status_code} {r.text[:200]}")
        j = r.json()
        self._set_tokens(j)

    def _set_tokens(self, j):
        self._access = j.get("access_token")
        self._refresh = j.get("refresh_token", self._refresh)
        try:
            self._access_exp = time.time() + float(j.get("expires_in", 1800))
        except Exception:
            self._access_exp = time.time() + 1800
        OAuthStore.save({ "access_token": self._access, "refresh_token": self._refresh, "expires_in": j.get("expires_in", 1800) })

    def _bearer(self):
        with self._lock:
            if not self._access or time.time() > (self._access_exp - 60):
                try:
                    self.refresh_token()
                except Exception as e:
                    discord(f"⚠️ Schwab refresh failed; need full OAuth restart: {e}")
                    raise
            return { "Authorization": f"Bearer {self._access}" }

    def _get_account_hashes(self):
        if self.account_hashes:
            return
        h = self._bearer()
        url = f"{self.end.trading_base}/accounts/accountNumbers"
        r = http_request("GET", url, headers=h, timeout=15)
        for acc in r.json():
            self.account_hashes[acc.get("accountNumber")] = acc.get("hashValue")

    # ---------- Accounts & Positions ----------
    def account(self):
        self._get_account_hashes()
        h = self._bearer()
        all_accounts_info = []
        for account_hash in self.account_hashes.values():
            url = f"{self.end.trading_base}/accounts/{account_hash}"
            r = http_request("GET", url, headers=h, timeout=15)
            all_accounts_info.append(r.json())

        cash = 0.0; equity = 0.0
        for a in all_accounts_info:
            acc = a.get('securitiesAccount', {})
            try:
                c = float(acc.get("currentBalances", {}).get("cashAvailableForTrading", 0) or 0)
                e = float(acc.get("currentBalances", {}).get("equity", 0) or 0)
            except Exception:
                c = 0; e = 0
            cash += c; equity += e
        return { "cash": cash, "equity": equity, "raw": all_accounts_info }

    def positions(self):
        self._get_account_hashes()
        h = self._bearer()
        all_positions = []
        for account_hash in self.account_hashes.values():
            url = f"{self.end.trading_base}/accounts/{account_hash}?fields=positions"
            r = http_request("GET", url, headers=h, timeout=20)
            acc_positions = r.json().get('securitiesAccount', {}).get('positions', [])
            if acc_positions:
                for p in acc_positions:
                    p['accountHash'] = account_hash
                all_positions.extend(acc_positions)
        return all_positions

    # ---------- Market Data ----------
    def quote(self, symbol: str):
        h = self._bearer()
        url = f"{self.end.market_base}/quotes"
        params = { "symbols": symbol }
        r = http_request("GET", url, headers=h, params=params, timeout=10)
        return r.json()

    def options_chain(self, symbol: str, **params):
        h = self._bearer()
        url = f"{self.end.market_base}/chains"
        pr = {"symbol": symbol}
        pr.update({k:v for k,v in params.items() if v is not None})
        r = http_request("GET", url, headers=h, params=pr, timeout=20)
        return r.json()

    def price_history(self, symbol: str, **params):
        h = self._bearer()
        url = f"{self.end.market_base}/pricehistory"
        pr = {"symbol": symbol}
        pr.update({k:v for k,v in params.items() if v is not None})
        r = http_request("GET", url, headers=h, params=pr, timeout=20)
        return r.json()

    def price(self, symbol: str) -> float:
        try:
            q = self.quote(symbol)
            if isinstance(q, dict) and symbol in q:
                quote_data = q[symbol].get('quote', {})
                if 'lastPrice' in quote_data:
                    return float(quote_data['lastPrice'])
                elif 'mark' in quote_data:
                    return float(quote_data['mark'])
            return 0.0
        except Exception as e:
            discord(f"Schwab price error: {e}")
            return 0.0

    # ---------- Orders ----------
    def _orders_url(self, accountNumberHash=None):
        if accountNumberHash:
            return f"{self.end.trading_base}/accounts/{accountNumberHash}/orders"
        return f"{self.end.trading_base}/orders"

    def list_orders(self, accountNumberHash=None, **filters):
        h = self._bearer()
        url = self._orders_url(accountNumberHash)
        r = http_request("GET", url, headers=h, params=filters, timeout=20)
        return r.json()

    def place_equity_order(self, accountNumber: str, symbol: str, qty: int, side: str, orderType="MARKET", limitPrice=None, duration="DAY"):
        accountNumberHash = self.account_hashes.get(accountNumber)
        if not accountNumberHash:
            self._get_account_hashes()
            accountNumberHash = self.account_hashes.get(accountNumber)
            if not accountNumberHash:
                raise ValueError(f"Account {accountNumber} not found.")

        h = self._bearer()
        url = self._orders_url(accountNumberHash)
        order = {
          "session": "NORMAL",
          "duration": duration,
          "orderType": orderType,
          "orderStrategyType": "SINGLE",
          "orderLegCollection": [{
              "instruction": "BUY" if side.upper()=="BUY" else "SELL",
              "quantity": qty,
              "instrument": {"symbol": symbol, "assetType": "EQUITY"}
          }]
        }
        if orderType == "LIMIT" and limitPrice is not None:
            order["price"] = float(limitPrice)
        get_limiter('trade', self.cfg.limits.orders_per_min, self.cfg.limits.orders_per_min, 60).wait()
        r = http_request("POST", url, headers={**h, "Content-Type":"application/json"}, json_body=order, timeout=20)
        return r.status_code, r.text

    def place_multi_leg_option(self, accountNumber: str, legs: list, price=None, duration="DAY", order_type="NET_CREDIT"):
        accountNumberHash = self.account_hashes.get(accountNumber)
        if not accountNumberHash:
            self._get_account_hashes()
            accountNumberHash = self.account_hashes.get(accountNumber)
            if not accountNumberHash:
                raise ValueError(f"Account {accountNumber} not found.")

        h = self._bearer()
        url = self._orders_url(accountNumberHash)
        olc = []
        for leg in legs:
            sym = leg['symbol']
            olc.append({
                "instruction": leg['instruction'],
                "quantity": int(leg.get('quantity',1)),
                "instrument": {"symbol": sym, "assetType": "OPTION"}
            })

        complex_order_strategy_type = "NONE"
        if len(legs) == 2:
            complex_order_strategy_type = "VERTICAL"
        elif len(legs) == 4:
            complex_order_strategy_type = "IRON_CONDOR"

        order = {
            "session": "NORMAL",
            "duration": duration,
            "orderType": "LIMIT" if price is not None else "MARKET",
            "price": price,
            "complexOrderStrategyType": complex_order_strategy_type,
            "orderStrategyType": "SINGLE",
            "orderLegCollection": olc
        }

        if price is not None:
            order["orderType"] = "NET_CREDIT" if order_type == "NET_CREDIT" else "NET_DEBIT"


        get_limiter('trade', self.cfg.limits.orders_per_min, self.cfg.limits.orders_per_min, 60).wait()
        r = http_request("POST", url, headers={**h, "Content-Type":"application/json"}, json_body=order, timeout=25)
        return r.status_code, r.text

    def close_position(self, symbol_or_id: str):
        discord("Schwab close_position called; implement per-asset close as needed.")
        return {"status":"not_implemented"}

    def close_all_options(self, symbol: str = None, expiry: str = None):
        try:
            poss = self.positions() or []
            closed = 0
            for pos in poss:
                ins = pos.get('instrument',{}) if isinstance(pos, dict) else {}
                if str(ins.get('assetType','')).lower() == 'option':
                    acct_hash = pos.get('accountHash')
                    o = ins.get('symbol')
                    qty = abs(int(pos.get('longQuantity') or pos.get('shortQuantity') or 0))
                    side = 'BUY_TO_CLOSE' if (pos.get('shortQuantity') or 0)>0 else 'SELL_TO_CLOSE'
                    if qty>0 and o:
                        self.place_multi_leg_option(acct_hash, [{'instruction': side, 'quantity': qty, 'symbol': o}], price=None)
                        closed += 1
            return {"closed": closed}
        except Exception as e:
            discord(f"Schwab close_all_options error: {e}")
            return {"closed": 0, "error": str(e)}

    # ---------- Streamer (WebSocket) scaffold ----------
    def _get_stream_prefs(self):
        h = self._bearer()
        url = self.end.preferences
        r = http_request("GET", url, headers=h, timeout=15)
        return r.json()

    def start_stream(self, symbols_equity=None, symbols_option=None):
        if self._stream_connected:
            return
        
        prefs_data = self._get_stream_prefs()
        prefs = prefs_data.get('streamerInfo', [{}])[0]
        if not prefs:
            discord("⚠️ Schwab streamer info not found in user preferences.")
            return

        wsurl = prefs.get('streamerSocketUrl')
        scid = prefs.get('schwabClientCustomerId')
        correl = prefs.get('schwabClientCorrelId')
        channel = prefs.get('schwabClientChannel')
        token = self._bearer().get('Authorization').split(' ',1)[1]

        def on_message(ws, message):
            """
            This function will be called for each message from the streamer.
            A complete implementation would parse these messages and update
            a real-time market data cache.
            """
            # Placeholder for real-time data handling
            print("Streamer message:", message)

        def on_error(ws, error):
            discord(f"Schwab streamer error: {error}")
            self._stream_connected = False

        def on_close(ws, close_status_code, close_msg):
            discord("Schwab streamer connection closed.")
            self._stream_connected = False
            # Optional: implement reconnection logic here

        def on_open(ws):
            login_req = {
                "requests": [{
                    "requestid": "1",
                    "service": "ADMIN",
                    "command": "LOGIN",
                    "SchwabClientCustomerId": scid,
                    "SchwabClientCorrelId": correl,
                    "parameters": {
                        "Authorization": token,
                        "SchwabClientChannel": channel,
                        "SchwabClientFunctionId": "APIAPP"
                    }
                }]
            }
            ws.send(json.dumps(login_req))

            if symbols_equity:
                equity_sub_req = {
                    "requests": [{
                        "requestid": "2",
                        "service": "LEVELONE_EQUITIES",
                        "command": "SUBS",
                        "SchwabClientCustomerId": scid,
                        "SchwabClientCorrelId": correl,
                        "parameters": {
                            "keys": ",".join(symbols_equity),
                            "fields": "0,1,2,3,4,5,8,10"
                        }
                    }]
                }
                ws.send(json.dumps(equity_sub_req))

            if symbols_option:
                option_sub_req = {
                    "requests": [{
                        "requestid": "3",
                        "service": "LEVELONE_OPTIONS",
                        "command": "SUBS",
                        "SchwabClientCustomerId": scid,
                        "SchwabClientCorrelId": correl,
                        "parameters": {
                            "keys": ",".join(symbols_option),
                            "fields": "0,2,3,13,14,15,16,17,18,19"
                        }
                    }]
                }
                ws.send(json.dumps(option_sub_req))
            
            self._stream_connected = True

        self._stream = websocket.WebSocketApp(wsurl,
                                              on_open=on_open,
                                              on_message=on_message,
                                              on_error=on_error,
                                              on_close=on_close)
        
        self._stream_thread = threading.Thread(target=self._stream.run_forever, daemon=True)
        self._stream_thread.start()