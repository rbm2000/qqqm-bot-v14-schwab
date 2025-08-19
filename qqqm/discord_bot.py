import os, asyncio
import discord
from discord.ext import commands
from .data.db import SessionLocal
from .data.models import Trade, Ledger, Position, SettingKV
from .config import load_config
from .scheduler import build_scheduler
from .brokers.paper import PaperBroker
from .util import discord as webhook_send

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

def fmt_money(x): return f"$ {x:,.2f}"

@bot.command()
async def ping(ctx): await ctx.reply("pong")

@bot.command()
async def status(ctx):
    s = SessionLocal()
    led = s.query(Ledger).order_by(Ledger.id.desc()).first()
    await ctx.reply(f"Cash {fmt_money(led.cash if led else 0)} | Equity {fmt_money(led.equity if led else 0)}")

@bot.command()
async def positions(ctx):
    s = SessionLocal()
    poss = s.query(Position).all()
    if not poss: 
        await ctx.reply("No positions")
        return
    lines = [f"{p.symbol}  qty={p.qty:.4f} avg={fmt_money(p.avg_price)} type={p.type}" for p in poss]
    await ctx.reply("\n".join(lines))

@bot.command()
async def pause(ctx):
    s = SessionLocal()
    kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
    if not kv: s.add(SettingKV(key='paused', value='1'))
    else: kv.value = '1'
    s.commit()
    await ctx.reply("⏸️ Trading paused")

@bot.command()
async def resume(ctx):
    s = SessionLocal()
    kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
    if not kv: s.add(SettingKV(key='paused', value='0'))
    else: kv.value = '0'
    s.commit()
    await ctx.reply("▶️ Trading resumed")

@bot.command()
async def killreset(ctx):
    s = SessionLocal()
    kv = s.query(SettingKV).filter(SettingKV.key=='kill_switch').first()
    if not kv: s.add(SettingKV(key='kill_switch', value='0'))
    else: kv.value = '0'
    s.commit()
    await ctx.reply("🔄 Kill‑Switch reset")

def run_bot():
    if not TOKEN: 
        return
    bot.run(TOKEN)

@bot.command()
async def report(ctx):
    s = SessionLocal()
    led = s.query(Ledger).order_by(Ledger.id.desc()).first()
    trades = s.query(Trade).order_by(Trade.id.desc()).limit(5).all()
    lines = [f"Cash ${getattr(led,'cash',0):.2f} | Equity ${getattr(led,'equity',0):.2f}"]
    for t in trades:
        lines.append(f"{t.ts} {t.action} {t.symbol} qty={t.qty} ${t.price:.2f} [{t.tag}]")
    await ctx.reply("\n".join(lines))

@bot.command()
async def config(ctx):
    cfg = load_config()
    await ctx.reply(f"Profile={cfg.profile} | Weekly DCA=${cfg.weekly_dca} | Buffer={cfg.cash_buffer_pct*100:.0f}% | VIX ceiling={cfg.risk.vix_ceiling}")

@bot.command()
async def closeall(ctx):
    try:
        from .config import load_config
        from .brokers.paper import PaperBroker
        b = PaperBroker()
        r = b.close_all_options()
        await ctx.reply(f"Closed {r.get('closed',0)} option positions.")
    except Exception as e:
        await ctx.reply(f"Error: {e}")


@bot.command()
async def portfolio(ctx):
    try:
        s = load_config()
        lines = ["**Portfolio**:"]
        for a in s.symbols:
            lines.append(f"- {a['ticker']} (opts: {a.get('options_ticker',a['ticker'])}) weight={a.get('weight',0):.2f} max_alloc_pct={a.get('max_alloc_pct',1.0):.2f} strategies={','.join(a.get('strategies',[]))}")
        await ctx.reply("\n".join(lines))
    except Exception as e:
        await ctx.reply(f"Error: {e}")

@bot.command()
async def enable(ctx, ticker: str, strategy: str):
    try:
        import json, os
        path = os.path.join(os.getcwd(), 'data', 'overrides.json')
        over = {}
        if os.path.exists(path):
            over = json.load(open(path,'r'))
        key = f"{ticker}.enable"
        lst = set(over.get(key, [])); lst.add(strategy); over[key] = list(lst)
        json.dump(over, open(path,'w'))
        await ctx.reply(f"Enabled {strategy} for {ticker}")
    except Exception as e:
        await ctx.reply(f"Error: {e}")

@bot.command()
async def disable(ctx, ticker: str, strategy: str):
    try:
        import json, os
        path = os.path.join(os.getcwd(), 'data', 'overrides.json')
        over = {}
        if os.path.exists(path):
            over = json.load(open(path,'r'))
        key = f"{ticker}.disable"
        lst = set(over.get(key, [])); lst.add(strategy); over[key] = list(lst)
        json.dump(over, open(path,'w'))
        await ctx.reply(f"Disabled {strategy} for {ticker}")
    except Exception as e:
        await ctx.reply(f"Error: {e}")
