import os
from ..util import http_request, get_limiter
from .base import Broker
from typing import Dict, Any, List
from ..config import load_config

class AlpacaBroker(Broker):
    def __init__(self):
        self.base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.key = os.getenv("ALPACA_KEY_ID","")
        self.secret = os.getenv("ALPACA_SECRET_KEY","")
        self.h = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}
        self.settings = load_config()

    def _get(self, path):
        r = get_limiter('data', capacity=self.settings.limits.data_capacity_per_min, refill=self.settings.limits.data_capacity_per_min, per_seconds=60).wait(); http_request('GET', self.base+path, headers=self.h)
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload):
        r = get_limiter('trade', capacity=self.settings.limits.trade_capacity_per_sec, refill=self.settings.limits.trade_capacity_per_sec, per_seconds=1).wait(); http_request('POST', self.base+path, headers=self.h, json_body=payload)
        r.raise_for_status()
        return r.json()

    # Minimal implementations; expand per Alpaca docs for options trading
    def account(self) -> Dict[str, Any]:
        return self._get("/v2/account")

    def price(self, symbol: str) -> float:
        # Use data API v2 or external data provider; placeholder
        raise NotImplementedError("Implement Alpaca data fetch")

    def options_chain(self, symbol: str, expiry: str | None = None) -> List[dict]:
        raise NotImplementedError("Implement options chain via Alpaca Data API")

    def buy_equity(self, symbol: str, qty: float, tag: str, note: str = ""):
        return self._post("/v2/orders", {"symbol": symbol, "qty": qty, "side":"buy","type":"market","time_in_force":"day"})

    def sell_equity(self, symbol: str, qty: float, tag: str, note: str = ""):
        return self._post("/v2/orders", {"symbol": symbol, "qty": qty, "side":"sell","type":"market","time_in_force":"day"})

    def sell_covered_call(self, *args, **kwargs):
        raise NotImplementedError("Implement options order placement per Alpaca Options API")

    def sell_cash_secured_put(self, *args, **kwargs):
        raise NotImplementedError()

    def open_vertical_spread(self, *args, **kwargs):
        raise NotImplementedError()

    def open_iron_condor(self, *args, **kwargs):
        raise NotImplementedError()

    def positions(self) -> list:
        return self._get("/v2/positions")

    def ledger(self) -> dict:
        return self.account()


    def close_all_options(self, symbol: str = None, expiry: str = None):
        """Close all open option positions. 
        NOTE: This demo uses per-position closes; to wire true multi-leg, use broker-native multi-leg order endpoints.
        """
        try:
            poss = self.positions() or []
            n = 0
            for pos in poss:
                sym = pos.get('symbol') or pos.get('symbol_id') or ''
                if ' ' in sym or ':' in sym or pos.get('asset_class','').lower()=='option':
                    # attempt broker-native close; adapters should implement a real close for options
                    cr = self.close_position(sym)
                    n += 1 if cr is not None else 0
            return {'closed': n}
        except Exception as e:
            discord(f'{self.__class__.__name__} close_all_options error: {e}')
            return {'closed': 0, 'error': str(e)}
