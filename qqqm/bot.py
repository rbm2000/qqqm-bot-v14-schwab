import os, threading, time
from .config import load_config
from .scheduler import build_scheduler
from .data.db import init_db
from .util import discord
from .brokers.paper import PaperBroker
from .brokers.alpaca import AlpacaBroker
from .brokers.tradier import TradierBroker
from .brokers.schwab import SchwabBroker
from .web.app import create_app
from .util import discord
import os, threading
from .discord_bot import run_bot
from .util import discord

def make_broker(name: str):
    if name == "paper":
        # start with 1000 unless overridden by env STARTING_CASH
        start = float(os.getenv("STARTING_CASH", "1000"))
        return PaperBroker(starting_cash=start)
    if name == "alpaca":
        return AlpacaBroker()
    if name == "tradier":
        return TradierBroker()
    if name == "schwab":
        return SchwabBroker()
    raise ValueError("Unknown broker")

def run_dashboard():
    app = create_app()
    app.run(host="0.0.0.0", port=5005)

def initial_deploy(broker, cfg):
    # invest all excess cash above buffer into ETF now
    acct = broker.account()
    cash = float(acct.get('cash',0) or 0)
    eq = float(acct.get('equity',0) or 0)
    if eq <= 0: eq = cash
    target_cash = eq * cfg.cash_buffer_pct
    buyable = max(0.0, cash - target_cash)
    if not cfg.deploy_full_cash_on_start or buyable < 5:  # need at least $5 for fractional
        return
    px = broker.price(cfg.symbol)
    qty = round(buyable / px, 4)
    broker.buy_equity(cfg.symbol, qty, tag='INIT', note='initial deploy to buffer')
    discord(f"🚀 Initial deploy: bought {qty} {cfg.symbol} with ${buyable:.2f}, keeping {target_cash:.2f} buffer.")

def broker_healthcheck(broker):
    ok = True; issues = []
    try:
        a = broker.account()
        if not a: ok=False; issues.append('account() failed')
    except Exception as e:
        ok=False; issues.append(f'account ex: {e}')
    try:
        _ = broker.positions()
    except Exception as e:
        issues.append(f'positions ex: {e}')
    return ok, issues

def main():
    cfg = load_config()
    init_db(cfg.db_url)
    broker = make_broker(cfg.broker)
    ok, issues = broker_healthcheck(broker)
    if not ok:
        discord(f"⚠️ Broker healthcheck: {issues}")
    initial_deploy(broker, cfg)
    sched = build_scheduler(broker, cfg)

    # run web UI in thread
    t = threading.Thread(target=run_dashboard, daemon=True); t.start()
    # run discord bot (optional)
    if os.getenv('DISCORD_BOT_TOKEN'):
        td = threading.Thread(target=run_bot, daemon=True); td.start()

    discord("🟢 QQQM bot started.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        discord("🟡 QQQM bot stopped.")

if __name__ == "__main__":
    main()
