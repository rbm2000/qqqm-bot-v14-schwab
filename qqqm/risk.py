from dataclasses import dataclass
from typing import Optional
import yfinance as yf
from .util import discord

@dataclass
class RiskContext:
    equity: float
    cash: float
    drawdown: float
    vix: float

class RiskManager:
    def __init__(self, settings):
        self.s = settings

    def _vix(self) -> float:
        try:
            return float(yf.Ticker("^VIX").history(period="1d")["Close"][-1])
        except:
            return 20.0

    def gate(self, broker) -> Optional[RiskContext]:
        acct = broker.account()
        equity = float(acct.get("equity", 0) or 0)
        cash = float(acct.get("cash", 0) or 0)
        # naive peak/equity drawdown approximation using ledger last-equity vs peak seen in memory
        # (for simplicity we don't maintain a peak table; this can be upgraded)
        drawdown = 0.0
        vix = self._vix()
        ctx = RiskContext(equity=equity, cash=cash, drawdown=drawdown, vix=vix)
        # VIX guard
        if vix > self.s.vix_max:
            discord(f"⛔ Skipping trades: VIX {vix:.1f} > {self.s.vix_max}")
            return None
        # Cash buffer guard
        if cash / max(equity, 1e-9) < self.s.cash_buffer_pct:
            discord(f"⛔ Skipping trades: cash buffer below {self.s.cash_buffer_pct*100:.0f}%")
            return None
        return ctx
