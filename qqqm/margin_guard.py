from dataclasses import dataclass
from .data.db import SessionLocal
from .data.models import Ledger, RiskItem
from typing import Optional, Tuple

@dataclass
class MarginStatus:
    margin_enabled: bool
    reason: str = ""

class MarginGuard:
    def __init__(self, settings):
        self.s = settings
        self.db = SessionLocal()

    def account_margin_enabled(self, acct_info: dict) -> MarginStatus:
        # Try to detect margin flags in broker account json; fall back to env/config
        text = json.dumps(acct_info or {})
        enabled = any(k in text.lower() for k in ['margin', 'pattern_day_trader', 'sma', 'daytrading_buying_power'])
        return MarginStatus(enabled)

    def available_cash_after_buffer(self) -> float:
        led = self.db.query(Ledger).order_by(Ledger.id.desc()).first()
        if not led: return 0.0
        eq = float(led.equity or 0)
        cash = float(led.cash or 0)
        return cash - (eq * self.s.cash_buffer_pct)

    def can_afford_equity_buy(self, dollars: float) -> bool:
        return self.available_cash_after_buffer() >= dollars

    def can_afford_credit_spread(self, max_loss: float) -> bool:
        # enforce holding full max loss in cash to avoid any margin use
        return self.available_cash_after_buffer() >= max_loss
