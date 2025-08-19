from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time as dtime
from .strategies import dca, wheel, spreads, condor
from .risk import RiskManager
from .riskguard import RiskGuard
from .data.db import SessionLocal
from .data.models import OptionPosition
from .util import legs_mid_credit
from .sync import LiveSync
from .util import discord
from .util import discord

def build_scheduler(broker, settings):
    live = LiveSync(broker, settings)
    sdb = SessionLocal()

    def rebalance_to_buffer():
        acct = broker.account(); cash = float(acct.get('cash',0) or 0); eq = float(acct.get('equity',0) or 0)
        if eq<=0: eq=cash
        target = eq * settings.cash_buffer_pct
        excess = cash - target
        if excess > 5:
            px = broker.price(settings.symbol)
            qty = round(excess / px, 4)
            broker.buy_equity(settings.symbol, qty, tag='SWEEP', note='rebalance to buffer')
            discord(f"🧹 Rebalanced: invested ${excess:.2f} into {settings.symbol}")

    def daily_report():
        # simple daily text report via Discord
        acct = broker.account(); msg = f"Daily: Cash ${acct.get('cash',0):.2f} | Equity ${acct.get('equity',0):.2f}"
        discord(msg)

    risk = RiskManager(settings)
    guard = RiskGuard(settings)
    sched = BackgroundScheduler(timezone="US/Eastern")

    def manage_exits():
        # scan open options and close at TP/SL
        open_ops = sdb.query(OptionPosition).filter(OptionPosition.status=='open').all()
        for op in open_ops:
            sym = settings.options_symbol
            chain = broker.options_chain(sym, op.expiry)
            chain = [o for o in chain if o.get('bid',0)>0 or o.get('ask',0)>0]
            if not chain: 
                continue
            credit_now = legs_mid_credit(chain, json.loads(op.legs))
            if credit_now is None:
                continue
            # PnL on short credit: entry_credit - current_credit
            pnl = (op.entry_credit or 0) - max(0.0, credit_now)
            # compute thresholds
            if op.kind == 'spread':
                tp = settings.exits.spread_take_profit_pct * (op.entry_credit or 0)
                sl = -settings.exits.spread_stop_loss_pct * (op.entry_credit or 0)
            else:
                tp = settings.exits.condor_take_profit_pct * (op.entry_credit or 0)
                sl = -settings.exits.condor_stop_loss_pct * (op.entry_credit or 0)
            if pnl >= tp:
                broker.close_option_by_calculated_debit(op.id, sym, reason="TP")
            elif pnl <= sl:
                broker.close_option_by_calculated_debit(op.id, sym, reason="SL")
    

    def guarded(fn):
        # wraps strategy with RiskGuard + journaling of deny reasons
        def wrapper():
            # Guard v6 checks
            g = guard.checks()
            if not g.ok:
                from .util import discord
                discord(f"⛔ Guard block: {g.reason}")
                return
            ctx = risk.gate(broker)
            if not ctx:
                return
            try:
                fn(broker, settings)
            except Exception as e:
                discord(f"⚠️ Strategy error: {e}")
        return wrapper

    # Weekly DCA: Monday 10:00 ET
    sched.add_job(guarded(dca.run), "cron", day_of_week="mon", hour=10, minute=0, id="dca" )

    # Wheel roll: Monday 10:05 ET
    sched.add_job(guarded(wheel.run), "cron", day_of_week="mon", hour=10, minute=5, id="wheel" )

    # Enhanced-only extras on Monday 10:10 ET
    if settings.profile == "enhanced":
        sched.add_job(guarded(spreads.run), "cron", day_of_week="mon", hour=10, minute=10, id="spreads")
        sched.add_job(guarded(condor.run), "cron", day_of_week="mon", hour=10, minute=15, id="condor")

    # manage exits every 10 minutes
    sched.add_job(manage_exits, "cron", minute="*/10", id="exits")
    # Live account sync (cash/equity/positions)
    sched.add_job(live.snapshot, 'cron', minute='*/3', id='live_snapshot')
    # Rebalance to buffer daily
    sched.add_job(rebalance_to_buffer, 'cron', day_of_week='mon-fri', hour=10, minute=20, id='rebalance')
    # Daily report
    sched.add_job(daily_report, 'cron', day_of_week='mon-fri', hour=17, minute=30, id='daily_report')
    sched.start()
    return sched


def schedule_portfolio_jobs(sched, broker, settings):
    from .portfolio.engine import PortfolioEngine
    from .riskguard import RiskGuard
    pe = PortfolioEngine(broker, settings, RiskGuard(broker, settings))
    def entries_job():
        try:
            pe.run_entries(snapshot=None)
        except Exception as e:
            from .util import get_logger
            get_logger(__name__).error(f"portfolio entries error: {e}")
    sched.add_job(entries_job, 'cron', day_of_week='mon-fri', hour=14, minute=35, id='portfolio_entries')
