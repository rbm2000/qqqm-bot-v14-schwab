from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from functools import wraps
from ..config import load_config
from ..data.db import init_db, SessionLocal
from ..data.models import Trade, Ledger, Position, SettingKV, OptionPosition
import json, os, yaml
from ..factory import make_broker

def create_app():
    from ..config import Settings

    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY','dev-key')
    cfg = load_config()
    init_db(cfg.db_url)

    def require_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            pwd = os.getenv("DASHBOARD_PASSWORD")
            if not pwd:
                return f(*args, **kwargs)
            if session.get("auth_ok"):
                return f(*args, **kwargs)
            return redirect(url_for('login'))
        return decorated

    @app.route('/login', methods=['GET','POST'])
    def login():
        pwd = os.getenv("DASHBOARD_PASSWORD")
        if not pwd:
            return redirect(url_for('index'))
        if request.method == 'POST':
            if request.form.get('password') == pwd:
                session['auth_ok'] = True
                return redirect(url_for('index'))
        return render_template('login.html')

    @app.get('/')
    @require_auth
    def index():
        from datetime import datetime, timedelta
        now = datetime.utcnow(); week_ago = now - timedelta(days=7)
        sdb = SessionLocal()
        closed = sdb.query(OptionPosition).filter(OptionPosition.status=='closed', OptionPosition.closed!=None, OptionPosition.closed>=week_ago).all()
        wins = 0; pnl = 0.0
        for op in closed:
            sym = sdb.query(Trade).filter(Trade.ts>=week_ago, Trade.symbol.like(f"%{op.kind}%{op.expiry}%")).all()
            credits = sum(t.price for t in sym if t.action=='OPEN')
            debits = -sum(t.price for t in sym if t.action=='CLOSE')
            p = credits - debits
            pnl += p
            if p > 0: wins += 1
        trades = sdb.query(Trade).order_by(Trade.id.desc()).limit(200).all()
        led = sdb.query(Ledger).order_by(Ledger.id.desc()).first()
        poss = sdb.query(Position).all()
        stats = {'closed_trades': len(closed), 'wins': wins, 'pnl': pnl}
        return render_template('index.html', trades=trades, ledger=led, positions=poss, cfg=cfg, stats=stats)

    @app.get('/config')
    @require_auth
    def get_config():
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config', 'config.yaml')
        with open(path, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}

    @app.post('/config')
    @require_auth
    def save_config():
        txt = request.get_data(as_text=True)
        try:
            data = yaml.safe_load(txt)
            from ..config import Settings
            Settings(**data)
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config', 'config.yaml')
        with open(path, 'w') as f:
            f.write(txt)
        return jsonify({'ok': True})

    @app.post('/pause')
    @require_auth
    def pause():
        s = SessionLocal()
        kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
        if not kv:
            kv = SettingKV(key='paused', value='1')
            s.add(kv)
        else:
            kv.value = '1'
        s.commit()
        return jsonify({'ok':True})

    @app.post('/resume')
    @require_auth
    def resume():
        s = SessionLocal()
        kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
        if not kv:
            kv = SettingKV(key='paused', value='0')
            s.add(kv)
        else:
            kv.value = '0'
        s.commit()
        return jsonify({'ok':True})

    @app.post('/reset-kill')
    @require_auth
    def reset_kill():
        s = SessionLocal()
        kv = s.query(SettingKV).filter(SettingKV.key=='kill_switch').first()
        if not kv:
            kv = SettingKV(key='kill_switch', value='0')
            s.add(kv)
        else:
            kv.value = '0'
        s.commit()
        return jsonify({'ok':True})

    @app.get('/api/status')
    @require_auth
    def api_status():
        s = SessionLocal()
        led = s.query(Ledger).order_by(Ledger.id.desc()).first()
        poss = s.query(Position).all()
        return jsonify({'cash': float(getattr(led,'cash',0) or 0), 'equity': float(getattr(led,'equity',0) or 0),
                        'positions': [{'symbol':p.symbol,'qty':p.qty,'avg':p.avg_price,'type':p.type} for p in poss]})

    @app.get('/api/ledger')
    @require_auth
    def api_ledger():
        s = SessionLocal()
        recs = s.query(Ledger).order_by(Ledger.id.asc()).limit(1000).all()
        return jsonify([{'ts': str(r.ts), 'cash': r.cash, 'equity': r.equity} for r in recs])

    @app.get('/download/journal')
    @require_auth
    def dl_journal():
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'journal.jsonl')
        if not os.path.exists(path): return ('',204)
        with open(path,'rb') as f: data = f.read()
        return data, 200, {'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename=journal.jsonl'}

    @app.post('/action')
    @require_auth
    def action():
        act = request.args.get('do')
        s = SessionLocal()
        if act=='pause':
            kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
            if not kv: s.add(SettingKV(key='paused', value='1'))
            else: kv.value='1'
        elif act=='resume':
            kv = s.query(SettingKV).filter(SettingKV.key=='paused').first()
            if not kv: s.add(SettingKV(key='paused', value='0'))
            else: kv.value='0'
        elif act=='reset-kill':
            kv = s.query(SettingKV).filter(SettingKV.key=='kill_switch').first()
            if not kv: s.add(SettingKV(key='kill_switch', value='0'))
            else: kv.value='0'
        s.commit()
        return jsonify({'ok':True})

    @app.get('/api/options')
    @require_auth
    def api_options():
        s = SessionLocal()
        from ..data.models import OptionPosition
        ops = s.query(OptionPosition).all()
        return jsonify([{'id':op.id,'kind':op.kind,'direction':op.direction,'entry_credit':op.entry_credit,'expiry':op.expiry,'status':op.status} for op in ops])

    @app.post('/api/close')
    @require_auth
    def api_close():
        try:
            op_id = int(request.args.get('id','0'))
        except ValueError:
            return jsonify({'ok':False,'error':'invalid id'}), 400
        if not op_id: return jsonify({'ok':False,'error':'id required'}), 400
        from ..data.models import OptionPosition
        op = SessionLocal().query(OptionPosition).filter(OptionPosition.id==op_id, OptionPosition.status=='open').first()
        if not op: return jsonify({'ok':False,'error':'not found or already closed'}), 404
        sym = load_config().options_symbol
        b = make_broker(cfg.broker)
        r = b.close_option_by_calculated_debit(op_id, sym, reason="manual")
        return jsonify({'ok':True,'result':r})

    @app.post('/force-rebalance')
    @require_auth
    def force_rebalance():
        from ..scheduler import build_scheduler
        cfg = load_config()
        b = make_broker(cfg.broker)
        acct = b.account(); cash = float(acct.get('cash',0) or 0); eq = float(acct.get('equity',0) or 0)
        if eq<=0: eq=cash
        target = eq * cfg.cash_buffer_pct
        excess = cash - target
        if excess > 5:
            px = b.price(cfg.symbol); qty = round(excess / px, 4)
            b.buy_equity(cfg.symbol, qty, tag='SWEEP', note='manual rebalance to buffer')
            return jsonify({'ok':True,'bought_qty':qty})
        return jsonify({'ok':True,'bought_qty':0})

    @app.get('/api/health')
    @require_auth
    def api_health():
        from ..bot import broker_healthcheck
        b = make_broker(cfg.broker)
        ok, issues = broker_healthcheck(b)
        return jsonify({'ok': ok, 'issues': issues})

    @app.post('/api/close_all')
    @require_auth
    def api_close_all():
        b = make_broker(cfg.broker)
        res = b.close_all_options()
        return jsonify(res or {'closed':0})

    @app.get('/oauth/status')
    @require_auth
    def oauth_status():
        from ..util import OAuthStore
        t = OAuthStore.load()
        has = bool(t.get('access_token'))
        exp = t.get('expires_in')
        return jsonify({"connected": has, "expires_in": exp})

    @app.post('/oauth/restart')
    @require_auth
    def oauth_restart():
        from ..util import OAuthStore
        try:
            OAuthStore.save({})
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return app

@app.get('/api/portfolio')
def api_portfolio():
    from ..config import Settings
    s = Settings.load()
    return jsonify({"symbols": s.symbols, "weekly_dca_total": getattr(s, "weekly_dca_total", 100)})
