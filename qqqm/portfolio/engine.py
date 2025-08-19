from dataclasses import dataclass
from typing import List, Dict, Any
from ..util import get_logger
log = get_logger(__name__)

@dataclass
class AssetCfg:
    ticker: str
    options_ticker: str
    weight: float
    strategies: List[str]
    max_alloc_pct: float = 1.0
    min_spread_risk: float = 10.0
    cc_otm_pct: float = 0.05

class PortfolioEngine:
    def __init__(self, broker, settings, riskguard):
        self.broker = broker
        self.s = settings
        self.rg = riskguard
        self.assets: List[AssetCfg] = []
        for a in getattr(self.s, 'symbols', []):
            self.assets.append(AssetCfg(
                ticker=a.get('ticker'),
                options_ticker=a.get('options_ticker', a.get('ticker')),
                weight=float(a.get('weight', 0)),
                strategies=a.get('strategies', []),
                max_alloc_pct=float(a.get('max_alloc_pct', 1.0)),
                min_spread_risk=float(a.get('min_spread_risk', 10)),
                cc_otm_pct=float(a.get('cc_otm_pct', 0.05)),
            ))

    def dca_budget_split(self, total_usd: float) -> Dict[str, float]:
        wsum = sum(a.weight for a in self.assets) or 1.0
        return {a.ticker: total_usd * (a.weight / wsum) for a in self.assets}

    def run_entries(self, snapshot: Any = None):
        if not self.rg.ok_to_trade():
            log.info("RiskGuard blocking new entries."); return
        for a in self.assets:
            try:
                if not self._asset_within_caps(a): 
                    continue
                self._maybe_dca(a, snapshot)
                self._maybe_wheel(a, snapshot)
                self._maybe_spreads(a, snapshot)
                self._maybe_condor(a, snapshot)
            except Exception as e:
                log.error(f"[{a.ticker}] entry error: {e}")

    def _maybe_dca(self, a: AssetCfg, snapshot):
        if 'dca' not in a.strategies: 
            return
        total = float(getattr(self.s, 'weekly_dca_total', 100) or 0)
        per = self.dca_budget_split(total).get(a.ticker, 0.0)
        if per <= 0: 
            return
        try:
            from ..strategies import dca as dca_mod
            res = dca_mod.execute_confirmed_for_asset(self.broker, self.s, a.ticker, per)
            if res and res.get('status') == 'bought':
                log.info(f"DCA bought {res.get('qty')} {a.ticker}")
        except Exception as e:
            log.error(f"DCA error {a.ticker}: {e}")

    def _maybe_wheel(self, a: AssetCfg, snapshot):
        if 'wheel' not in a.strategies: 
            return
        try:
            from ..strategies import wheel as wheel_mod
        except Exception:
            return
        try:
            wheel_mod.run(self.broker, self.s, a.ticker, a.options_ticker)
        except Exception as e:
            log.error(f"Wheel error {a.ticker}: {e}")

    def _maybe_spreads(self, a: AssetCfg, snapshot):
        if 'credit_spreads' not in a.strategies and 'defined_risk_spreads' not in a.strategies:
            return
        try:
            from ..strategies import spreads as sp_mod
        except Exception:
            return
        try:
            sp_mod.run(self.broker, self.s, a.ticker, a.options_ticker, a.min_spread_risk)
        except Exception as e:
            log.error(f"Spreads error {a.ticker}: {e}")

    def _maybe_condor(self, a: AssetCfg, snapshot):
        if 'iron_condor' not in a.strategies: 
            return
        try:
            from ..strategies import condor as condor_mod
        except Exception:
            return
        try:
            condor_mod.run(self.broker, self.s, a.ticker, a.options_ticker)
        except Exception as e:
            log.error(f"Condor error {a.ticker}: {e}")

    def _asset_within_caps(self, a: AssetCfg) -> bool:
        try:
            eq = float(self.broker.equity() or 0)
            if eq <= 0:
                return False
            total_value = 0.0
            for pos in (self.broker.positions() or []):
                ins = pos.get('instrument',{}) if isinstance(pos, dict) else {}
                if ins.get('symbol','').upper() == a.ticker.upper():
                    qty = float(pos.get('longQuantity') or 0) - float(pos.get('shortQuantity') or 0)
                    price = float(self.broker.price(a.ticker) or 0.0)
                    total_value += max(0.0, qty) * price
            alloc = total_value / eq if eq > 0 else 0.0
            return alloc <= a.max_alloc_pct + 1e-6
        except Exception:
            return True
