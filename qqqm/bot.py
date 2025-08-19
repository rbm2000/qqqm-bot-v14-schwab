import os, threading, time, logging

from .config import load_config
from .scheduler import build_scheduler
from .data.db import init_db
from .util import discord
from .web.app import create_app
from .discord_bot import run_bot
from .factory import make_broker

# --- logging (built-in; no util dependency)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("qqqm.bot")

def run_dashboard():
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5005")))

def initial_deploy(broker, cfg):
    """Invest excess cash above the buffer into cfg.symbol on first run."""
    try:
        if not getattr(cfg, "deploy_full_cash_on_start", False):
            return
        acct = broker.account() or {}
        cash = float(acct.get("cash", 0) or 0)
        eq = float(acct.get("equity", 0) or 0)
        if eq <= 0: eq = cash
        target_cash = eq * float(getattr(cfg, "cash_buffer_pct", 0.15) or 0)
        buyable = max(0.0, cash - target_cash)
        if buyable < 5:  # need at least a few dollars for fractional
            return
        px = float(broker.price(cfg.symbol) or 0)
        if px <= 0: return
        qty = round(buyable / px, 4)
        broker.buy_equity(cfg.symbol, qty, tag="INIT", note="initial deploy to buffer")
        discord(f"🚀 Initial deploy: bought {qty} {cfg.symbol} using ${buyable:.2f} (buffer ${target_cash:.2f}).")
    except Exception as e:
        log.error(f"initial_deploy error: {e}")

def broker_healthcheck(broker):
    ok = True; issues = []
    try:
        a = broker.account()
        if not a: ok=False; issues.append("account() returned empty")
    except Exception as e:
        ok=False; issues.append(f"account() ex: {e}")
    try:
        _ = broker.positions()
    except Exception as e:
        issues.append(f"positions() ex: {e}")
    return ok, issues

def main():
    cfg = load_config()

    # Optional DB init
    try:
        if getattr(cfg, "db_url", None):
            init_db(cfg.db_url)
    except Exception as e:
        log.warning(f"DB init skipped: {e}")

    broker = make_broker(cfg.broker)

    ok, issues = broker_healthcheck(broker)
    if not ok:
        discord(f"⚠️ Broker healthcheck issues: {issues}")

    initial_deploy(broker, cfg)

    # Scheduler
    try:
        sched = build_scheduler(broker, cfg)
        sched.start()
        log.info("Scheduler started.")
    except Exception as e:
        log.error(f"Scheduler failed to start: {e}")

    # Web dashboard
    t_web = threading.Thread(target=run_dashboard, daemon=True)
    t_web.start(); log.info("Web dashboard thread started.")

    # Discord bot
    t_discord = threading.Thread(target=run_bot, daemon=True)
    t_discord.start(); log.info("Discord bot thread started.")

    # Keep process alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down...")

if __name__ == "__main__":
    main()
