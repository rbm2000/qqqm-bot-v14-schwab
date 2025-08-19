from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple
import yfinance as yf

from .util import discord
from .data.db import SessionLocal
from .data.models import Trade, Ledger, RiskItem, SettingKV

def _today_bounds():
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return start, end

def _week_start():
    now = datetime.utcnow()
    start = now - timedelta(days=now.weekday())  # Monday
    return datetime(start.year, start.month, start.day)

@dataclass
class GuardResult:
    ok: bool
    reason: str | None = None

class RiskGuard:
    def __init__(self, settings):
        self.s = settings
        self.db = SessionLocal()

    def _vix(self) -> float:
        try:
            return float(yf.Ticker("^VIX").history(period="1d")["Close"][-1])
        except Exception:
            return 20.0

    def _equity_cash(self) -> Tuple[float,float]:
        led = self.db.query(Ledger).order_by(Ledger.id.desc()).first()
        if not led:
            return 0.0, 0.0
        return float(led.equity or 0), float(led.cash or 0)

    def _pnl_day(self) -> float:
        start, end = _today_bounds()
        first = self.db.query(Ledger).filter(Ledger.ts >= start, Ledger.ts < end).order_by(Ledger.id.asc()).first()
        last = self.db.query(Ledger).filter(Ledger.ts >= start, Ledger.ts < end).order_by(Ledger.id.desc()).first()
        if not first or not last:
            return 0.0
        return (last.equity or 0) - (first.equity or 0)

    def _pnl_week_pct(self) -> float:
        ws = _week_start()
        first = self.db.query(Ledger).filter(Ledger.ts >= ws).order_by(Ledger.id.asc()).first()
        last = self.db.query(Ledger).filter(Ledger.ts >= ws).order_by(Ledger.id.desc()).first()
        if not first or not last or (first.equity or 0) == 0:
            return 0.0
        return ((last.equity or 0) - (first.equity or 0)) / (first.equity or 1)

    def _open_spread_risk(self) -> Tuple[float,int,int]:
        # Sum RiskItem where closed is null. Also compute bull vs bear counts
        open_items = self.db.query(RiskItem).filter(RiskItem.closed == None).all()
        risk_sum = sum(r.risk_amount or 0 for r in open_items)
        bulls = sum(1 for r in open_items if (r.direction or "").lower() == "bull")
        bears = sum(1 for r in open_items if (r.direction or "").lower() == "bear")
        return risk_sum, bulls, bears

    def _trades_today(self) -> int:
        start, end = _today_bounds()
        return self.db.query(Trade).filter(Trade.ts >= start, Trade.ts < end).count()

    def _paused_or_killed(self) -> Tuple[bool,bool]:
        get = lambda k: self.db.query(SettingKV).filter(SettingKV.key==k).first()
        paused = (get("paused").value == "1") if get("paused") else False
        killed = (get("kill_switch").value == "1") if get("kill_switch") else False
        return paused, killed

    def set_flag(self, key: str, val: bool):
        kv = self.db.query(SettingKV).filter(SettingKV.key==key).first()
        if not kv:
            kv = SettingKV(key=key, value="1" if val else "0")
            self.db.add(kv)
        else:
            kv.value = "1" if val else "0"
        self.db.commit()

    def note_trade(self):
        # record last_trade_ts
        kv = self.db.query(SettingKV).filter(SettingKV.key=="last_trade_ts").first()
        now = datetime.utcnow().isoformat()
        if not kv:
            self.db.add(SettingKV(key="last_trade_ts", value=now))
        else:
            kv.value = now
        self.db.commit()

    def cooldown_ok(self) -> bool:
        kv = self.db.query(SettingKV).filter(SettingKV.key=="last_trade_ts").first()
        if not kv: return True
        try:
            ts = datetime.fromisoformat(kv.value)
            return (datetime.utcnow() - ts) >= timedelta(minutes=self.s.risk.trade_cooldown_min)
        except Exception:
            return True

    def checks(self) -> GuardResult:
        paused, killed = self._paused_or_killed()
        if killed:
            return GuardResult(False, "Kill-switch active")
        if paused:
            return GuardResult(False, "Paused")

        equity, cash = self._equity_cash()
        # VIX
        vix = self._vix()
        if vix > self.s.risk.vix_ceiling:
            return GuardResult(False, f"VIX {vix:.1f} > ceiling {self.s.risk.vix_ceiling}")

        # Daily/Weekly stops
        if -self._pnl_day() > self.s.risk.day_abs_loss_stop:
            # flip kill switch for the day
            self.set_flag("kill_switch", True)
            discord(f"🛑 Kill-switch: daily loss exceeded ${self.s.risk.day_abs_loss_stop:.0f}")
            return GuardResult(False, "Daily loss stop")
        if -self._pnl_week_pct() > self.s.risk.week_loss_pct_stop:
            self.set_flag("kill_switch", True)
            discord(f"🛑 Kill-switch: weekly loss exceeded {self.s.risk.week_loss_pct_stop*100:.0f}%")
            return GuardResult(False, "Weekly loss stop")

        # Open risk % cap
        risk_sum, bulls, bears = self._open_spread_risk()
        if equity > 0 and (risk_sum / equity) > self.s.risk.max_open_risk_pct:
            return GuardResult(False, "Max open risk cap reached")

        # Direction cap (avoid >2:1 tilt)
        if bears > 0 and bulls / max(bears,1) > self.s.risk.direction_cap_ratio:
            return GuardResult(False, "Direction cap (too bullish)")
        if bulls > 0 and bears / max(bulls,1) > self.s.risk.direction_cap_ratio:
            return GuardResult(False, "Direction cap (too bearish)")

        # Trades/day cap
        if self._trades_today() >= self.s.risk.max_trades_per_day:
            return GuardResult(False, "Max trades/day reached")

        # Cooldown
        if not self.cooldown_ok():
            return GuardResult(False, "Cooldown active")

        return GuardResult(True, None)
