from ..util import discord, human_money

def run(broker, settings):
    # buy dollars -> shares
    px = broker.price(settings.symbol)
    shares = round(settings.weekly_dca / px, 4)
    if shares < 0.01:
        discord("DCA skipped: amount too small for a share fraction.")
        return
    res = broker.buy_equity(settings.symbol, shares, tag="DCA", note=f"${settings.weekly_dca} weekly DCA")
    discord(f"🧊 DCA: bought {shares} {settings.symbol} @ ~{human_money(px)}")


def _load_map():
    try:
        pend = _load_pending()
    except Exception:
        pend = {}
    if isinstance(pend, dict) and 'status' in pend and 'amount' in pend:
        return {}
    return pend if isinstance(pend, dict) else {}

def request_discord_confirmation(amount: float, ticker: str = 'QQQM'):
    pend = _load_map()
    now = int(time.time())
    pend[ticker] = {"amount": amount, "requested_at": now, "status": "pending"}
    _save_pending(pend)
    discord(f"⚠️ DCA pending for **{ticker}**: confirm ${amount:.2f}. Reply `!dca_yes {ticker}` to confirm or `!dca_no {ticker}` to skip (48h timeout).")

def dca_should_execute(ticker: str = 'QQQM') -> float:
    pend = _load_map()
    t = pend.get(ticker) or {}
    if not t or t.get('status') in (None, 'pending'):
        return 0.0
    if t.get('status') == 'approved':
        amt = float(t.get('amount', 0.0) or 0.0)
        pend[ticker] = {"status":"consumed","amount":amt,"consumed_at":int(time.time())}
        _save_pending(pend)
        return amt
    return 0.0

def dca_timeout_check(timeout_hours: int = 48):
    pend = _load_map()
    changed = False
    for tk, t in list(pend.items()):
        if t.get('status') == 'pending':
            ts = int(t.get('requested_at', 0) or 0)
            if ts and (time.time() - ts) > timeout_hours*3600:
                t['status'] = 'expired'
                pend[tk] = t
                changed = True
    if changed:
        _save_pending(pend)
        discord("⏱️ DCA request expired for one or more tickers (48h). Use `!dca_yes <ticker>` next time to confirm.")

def execute_confirmed_for_asset(broker, settings, ticker: str, amount: float):
    pend = _load_map()
    if not pend.get(ticker) or pend.get(ticker,{}).get('status') in (None, 'expired', 'declined', 'consumed'):
        request_discord_confirmation(amount, ticker=ticker)
        return {"status":"awaiting_confirmation","ticker":ticker}
    dca_timeout_check(getattr(settings, 'confirm_timeout_hours', 48))
    amt = dca_should_execute(ticker=ticker)
    if amt > 0:
        price = broker.price(ticker) or 0.0
        qty = int(amt // max(price, 1e-9)) if price > 0 else 0
        if qty <= 0:
            return {"status":"skipped","ticker":ticker,"reason":"not enough for 1 share"}
        code, resp = broker.place_equity_order(None, ticker, qty, 'BUY', orderType='MARKET')
        return {"status":"bought","ticker":ticker,"qty":qty,"entry":code}
    return {"status":"pending","ticker":ticker}
