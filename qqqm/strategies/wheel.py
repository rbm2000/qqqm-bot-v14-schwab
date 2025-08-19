from ..util import discord
from datetime import datetime, timedelta
from ..margin_guard import MarginGuard
import yfinance as yf

def _nearest_weekly_expiry():
    # aim for next Friday at least 5 days out
    d = datetime.utcnow().date()
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    if (d - datetime.utcnow().date()).days < 5:
        d += timedelta(days=7)
    return d.isoformat()

def run(broker, settings):
    sym = settings.symbol
    opt_sym = getattr(settings, 'options_symbol', settings.symbol)
    acct = broker.account()
    px = broker.price(sym)

    # Fetch positions to see share count
    shares = 0
    for p in broker.positions():
        if p["symbol"] == sym and p.get("type","equity") == "equity":
            shares = p["qty"]
            break

    mg = MarginGuard(settings)
    expiry = _pick_expiry(opt_sym, settings.dte_window.min, settings.dte_window.max) or _nearest_weekly_expiry()
    chain = broker.options_chain(opt_sym, expiry)
    chain = [o for o in chain if o.get('bid',0)>0 or o.get('ask',0)>0]

    if shares >= 100:
        # Covered call
        target_strike = round(px * (1 + settings.call_pct_otm), 2)
        # pick nearest >= target
        strikes = sorted({c["strike"] for c in chain if c["type"]=="call"})
        strike = min([s for s in strikes if s >= target_strike], default=target_strike)
        broker.sell_covered_call(sym, int(shares//100*100), strike, expiry, tag="CC")
        discord(f"💸 Sold covered call {sym} {strike} {expiry} against {int(shares//100*100)} shares" )
    else:
        # Cash-secured put sized by available cash
        cash = acct.get("cash",0)
        target_strike = round(px * (1 - settings.put_pct_otm), 2)
        strikes = sorted({p["strike"] for p in chain if p["type"]=="put"})
        strike = max([s for s in strikes if s <= target_strike], default=target_strike)
        # Enforce cash-only: require full strike*100 collateral
        contracts = int((cash) // (strike*100))
        if contracts<1 or not mg.can_afford_credit_spread(strike*100*contracts):
            return
        broker.sell_cash_secured_put(sym, cash*0.9, strike, expiry, tag="CSP")
        discord(f"🛡️ Sold cash‑secured put {sym} {strike} {expiry}")


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
