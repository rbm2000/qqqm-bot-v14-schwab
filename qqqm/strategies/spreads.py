from ..util import discord, vol_factor
from ..data.db import SessionLocal
from ..data.models import RiskItem
from ..riskguard import RiskGuard
from ..margin_guard import MarginGuard
import yfinance as yf
from datetime import datetime

def run(broker, settings):
    # Risk open % cap enforced by Guard; here we persist risk item when we open
    # Volatility-adjusted sizing factor (reduce in high VIX)
    try:
        vix = float(yf.Ticker('^VIX').history(period='1d')['Close'][-1])
    except Exception:
        vix = settings.vol_sizing.vix_target
    factor = vol_factor(vix, settings.vol_sizing.vix_floor, settings.vol_sizing.vix_target, settings.vol_sizing.vix_ceiling, settings.vol_sizing.min_factor, settings.vol_sizing.max_factor)
    # Tiny defined-risk spread example (placeholder): open 1-lot bull put spread a few % OTM
    sym = getattr(settings, 'options_symbol', settings.symbol)
    px = broker.price(sym)
    expiry = _pick_expiry(sym, settings.dte_window.min, settings.dte_window.max)
    expiry_chain = broker.options_chain(sym, expiry) if expiry else broker.options_chain(sym)
    # filter out bad quotes
    expiry_chain = [o for o in expiry_chain if o.get('bid',0)>0 or o.get('ask',0)>0]
    puts = sorted([o for o in expiry_chain if o["type"]=="put"], key=lambda x: x["strike"])
    if not puts:
        return
    short = max([p for p in puts if p["strike"] <= px*0.95], key=lambda x: x["strike"], default=None)
    if not short:
        return
    long = next((p for p in puts if p["strike"] < short["strike"]-1), None)
    if not long:
        return
    # Apply factor by optionally skipping if too low
    if factor < 0.5:
        return
    # cash-only preflight: require width*100 on hand (conservative)
    mg = MarginGuard(settings)
    width = abs(short['strike']-long['strike'])*100
    if not mg.can_afford_credit_spread(width):
        return
    broker.open_vertical_spread(sym, "bull_put", short["strike"], long["strike"], short["expiry"], tag="SPREAD")
    # record max loss risk = width*100
    risk_amt = (short['strike'] - long['strike']) * 100
    s = SessionLocal()
    s.add(RiskItem(kind='spread', risk_amount=risk_amt, direction='bull'))
    s.commit()
    discord(f"🔧 Opened bull put spread {sym} {long['strike']}/{short['strike']} {short['expiry']}")


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
