import os
from ..util import http_request, get_limiter
from .base import Broker
from typing import Dict, Any, List
from ..config import load_config

class TradierBroker(Broker):
    def __init__(self):
        self.base = os.getenv("TRADIER_BASE_URL","https://api.tradier.com/v1")
        self.tok = os.getenv("TRADIER_ACCESS_TOKEN","")
        self.h = {"Authorization": f"Bearer {self.tok}", "Accept": "application/json"}
        self.settings = load_config()

    def _get(self, path, params=None):
        r = get_limiter('data', capacity=self.settings.limits.data_capacity_per_min, refill=self.settings.limits.data_capacity_per_min, per_seconds=60).wait(); http_request('GET', self.base+path, headers=self.h, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload):
        r = get_limiter('trade', capacity=self.settings.limits.trade_capacity_per_sec, refill=self.settings.limits.trade_capacity_per_sec, per_seconds=1).wait(); http_request('POST', self.base+path, headers=self.h, data=payload)
        r.raise_for_status()
        return r.json()

    def account(self) -> Dict[str, Any]:
        # requires account id in path for production; left as placeholder
        return {"note":"connect account and implement endpoints"}

    def price(self, symbol: str) -> float:
        j = self._get("/markets/quotes", params={"symbols":symbol})
        q = j.get("quotes",{}).get("quote",{})
        return float(q.get("last",0))

    def options_chain(self, symbol: str, expiry: str | None = None) -> List[dict]:
        if not expiry:
            # grab nearest expiry list and pick first
            j = self._get("/markets/options/expirations", params={"symbol":symbol,"includeAll":"false"})
            expiry = j["expirations"]["date"][0]
        ch = self._get("/markets/options/chains", params={"symbol":symbol, "expiration":expiry})
        out = []
        for o in ch.get("options",{}).get("option",[]):
            out.append({"strike": float(o["strike"]), "expiry": expiry, "type": o["option_type"], "bid": float(o.get("bid",0) or 0), "ask": float(o.get("ask",0) or 0)})
        return out

    def buy_equity(self, symbol: str, qty: float, tag: str, note: str = ""):
        raise NotImplementedError("Implement /accounts/{id}/orders payload with market buy")

    def sell_equity(self, symbol: str, qty: float, tag: str, note: str = ""):
        raise NotImplementedError("Implement /accounts/{id}/orders payload with market sell")

    def sell_covered_call(self, *args, **kwargs):
        raise NotImplementedError("Implement complex option order per Tradier docs")

    def sell_cash_secured_put(self, *args, **kwargs):
        raise NotImplementedError()

    def open_vertical_spread(self, *args, **kwargs):
        raise NotImplementedError()

    def open_iron_condor(self, *args, **kwargs):
        raise NotImplementedError()

    def positions(self) -> list:
        return []

    def ledger(self) -> dict:
        return {}


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
