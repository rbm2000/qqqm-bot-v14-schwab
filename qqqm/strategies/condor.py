# qqqm/strategies/condor.py
from datetime import datetime
import yfinance as yf
from ..util import discord, vol_factor
from ..data.db import SessionLocal
from ..data.models import RiskItem
from ..margin_guard import MarginGuard

def _pick_expiry(symbol: str, dte_min: int, dte_max: int) -> str | None:
    tk = yf.Ticker(symbol)
    today = datetime.utcnow().date()
    best = None
    for e in (tk.options or []):
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            dte = (d - today).days
            if dte_min <= dte <= dte_max:
                if best is None or d < best:
                    best = d
        except Exception:
            pass
    return best.isoformat() if best else None

def run(broker, settings):
    # volatility sizing
    try:
        vix = float(yf.Ticker('^VIX').history(period='1d')['Close'][-1])
    except Exception:
        vix = settings.vol_sizing.vix_target
    factor = vol_factor(
        vix,
        settings.vol_sizing.vix_floor,
        settings.vol_sizing.vix_target,
        settings.vol_sizing.vix_ceiling,
        settings.vol_sizing.min_factor,
        settings.vol_sizing.max_factor,
    )
    if factor < 0.6:
        return  # too spicy

    sym = getattr(settings, 'options_symbol', settings.symbol)
    expiry = _pick_expiry(sym, settings.dte_window.min, settings.dte_window.max)
    if not expiry:
        return

    px = broker.price(sym)
    chain = broker.options_chain(sym, expiry)
    if not chain:
        return

    calls = [o for o in chain if o.get("type") == "call"]
    puts  = [o for o in chain if o.get("type") == "put"]
    if not calls or not puts:
        return

    # ~5%/7% wings around spot
    up1 = min((c for c in calls if c["strike"] >= px * 1.05), key=lambda x: x["strike"], default=None)
    up2 = min((c for c in calls if c["strike"] >= px * 1.07), key=lambda x: x["strike"], default=None)
    dn1 = max((p for p in puts  if p["strike"] <= px * 0.95), key=lambda x: x["strike"], default=None)
    dn2 = max((p for p in puts  if p["strike"] <= px * 0.93), key=lambda x: x["strike"], default=None)
    if not (up1 and up2 and dn1 and dn2):
        return

    mg = MarginGuard(settings)
    width = max(up2["strike"] - up1["strike"], dn1["strike"] - dn2["strike"]) * 100
    if not mg.can_afford_credit_spread(width):
        return

    broker.open_iron_condor(
        sym,
        lower_put=dn2["strike"],
        upper_put=dn1["strike"],
        lower_call=up1["strike"],
        upper_call=up2["strike"],
        expiry=expiry,
        tag="CONDOR",
    )

    # track risk
    risk_amt = max(dn1["strike"] - dn2["strike"], up2["strike"] - up1["strike"]) * 100
    s = SessionLocal()
    s.add(RiskItem(kind="condor", risk_amount=risk_amt, direction="neutral"))
    s.commit()
    discord(f"🪙 Opened iron condor {sym} {expiry} | wings {dn2['strike']}-{dn1['strike']} & {up1['strike']}-{up2['strike']}")