import yfinance as yf
from .base import Broker
from typing import Dict, Any, List
import math, os, json
from datetime import datetime, timedelta
from ..data.models import Trade, Ledger, Position, OptionPosition
from sqlalchemy.orm import Session
from ..util import journal
from ..util import legs_mid_credit

class PaperBroker(Broker):
    def __init__(self, starting_cash: float = 1000.0):
        super().__init__()
        try:
            from ..config import load_config
            self.settings = load_config()
        except Exception:
            self.settings = None

        from ..data.db import SessionLocal
        self.session: Session = SessionLocal()

        if not self.session.query(Ledger).count():
            self.session.add(Ledger(cash=starting_cash, equity=starting_cash, note="init"))
            self.session.commit()

    def _add_option_position(self, kind, direction, legs, expiry, credit):
        op = OptionPosition(kind=kind, direction=direction, legs=json.dumps(legs), expiry=expiry, entry_credit=credit, status='open')
        self.session.add(op)
        self.session.commit()
        return op

    def _update_equity(self):
        cash = self._cash()
        eq_val = cash
        for p in self.session.query(Position).all():
            px = self.price(p.symbol) if p.type == "equity" else 0
            eq_val += p.qty * px
        try:
            from ..data.models import OptionPosition
            opens = self.session.query(OptionPosition).filter(OptionPosition.status=='open').all()
            for op in opens:
                chain = self.options_chain('QQQ' if 'QQQM' not in op.legs else 'QQQM', op.expiry)
                chain = [o for o in chain if o.get('bid',0)>0 or o.get('ask',0)>0]
                cur = legs_mid_credit(chain, json.loads(op.legs)) or 0.0
                if cur > 0:
                    eq_val -= cur
        except Exception:
            pass
        self.session.add(Ledger(cash=cash, equity=eq_val, note="mark"))
        self.session.commit()

    def _cash(self) -> float:
        last = self.session.query(Ledger).order_by(Ledger.id.desc()).first()
        return last.cash if last else 0.0

    def account(self) -> Dict[str, Any]:
        self._update_equity()
        last = self.session.query(Ledger).order_by(Ledger.id.desc()).first()
        return {"cash": last.cash, "equity": last.equity}

    def price(self, symbol: str) -> float:
        return float(yf.Ticker(symbol).history(period="1d")["Close"][-1])

    def options_chain(self, symbol: str, expiry: str | None = None) -> List[dict]:
        tk = yf.Ticker(symbol)
        exps = tk.options
        if not exps:
            return []
        if not expiry:
            now = datetime.utcnow().date()
            candidates = []
            for e in exps:
                try:
                    d = datetime.strptime(e, "%Y-%m-%d").date()
                    if (d - now).days >= 5:
                        candidates.append(d)
                except:
                    pass
            expiry = min(candidates).isoformat() if candidates else exps[0]
        ch = []
        calls = tk.option_chain(expiry).calls
        puts = tk.option_chain(expiry).puts
        for _, row in calls.iterrows():
            ch.append({"strike": float(row["strike"]), "expiry": expiry, "type": "call", "bid": float(row["bid"]), "ask": float(row["ask"])})
        for _, row in puts.iterrows():
            ch.append({"strike": float(row["strike"]), "expiry": expiry, "type": "put", "bid": float(row["bid"]), "ask": float(row["ask"])})
        return ch

    def _record_trade(self, action, symbol, qty, price, tag, details=""):
        self.session.add(Trade(action=action, symbol=symbol, qty=qty, price=price, order_type="market", tag=tag, details=details))
        journal({"event":"trade","action":action,"symbol":symbol,"qty":qty,"price":price,"tag":tag,"details":details})
        cash = self._cash()
        if action in ("BUY","OPEN") and qty>0:
            cash -= qty * price
            pos = self.session.query(Position).filter_by(symbol=symbol, type="equity").first()
            if not pos:
                pos = Position(symbol=symbol, qty=0, avg_price=0, type="equity")
                self.session.add(pos)
                self.session.flush()
            total_cost = pos.avg_price * pos.qty + qty * price
            pos.qty += qty
            pos.avg_price = total_cost / max(pos.qty,1e-9)
        elif action in ("SELL","CLOSE") and qty>0:
            cash += qty * price
            pos = self.session.query(Position).filter_by(symbol=symbol, type="equity").first()
            if pos:
                pos.qty = max(0, pos.qty - qty)
        self.session.add(Ledger(cash=cash, equity=0, note=f"{action} {symbol}"))
        self.session.commit()
        return {"status":"ok","price":price}

    def buy_equity(self, symbol: str, qty: float, tag: str, note: str = "") -> Dict[str, Any]:
        px = self.price(symbol)
        return self._record_trade("BUY", symbol, qty, px, tag, details=note)

    def sell_equity(self, symbol: str, qty: float, tag: str, note: str = "") -> Dict[str, Any]:
        px = self.price(symbol)
        return self._record_trade("SELL", symbol, qty, px, tag, details=note)

    def sell_covered_call(self, symbol: str, shares: int, strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        chain = self.options_chain(symbol, expiry)
        candidates = [c for c in chain if c["type"]=="call" and abs(c["strike"]-strike)<1e-6]
        mid = 0.0
        if candidates:
            b = candidates[0].get('bid',0) or 0
            a = candidates[0].get('ask',0) or 0
            if a>0 or b>0:
                mid = (a if b==0 else b if a==0 else (a+b)/2)
        prem = max(0.0, mid) * (shares//100) * 100
        cash = self._cash() + prem
        self.session.add(Trade(action="OPEN", symbol=f"{symbol}_CC_{strike}_{expiry}", qty=shares, price=prem, order_type="market", tag=tag, details="paper CC"))
        self.session.add(Ledger(cash=cash, equity=0, note="open CC"))
        self.session.commit()
        return {"status":"ok","premium":prem}

    def sell_cash_secured_put(self, symbol: str, cash: float, strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        chain = self.options_chain(symbol, expiry)
        candidates = [p for p in chain if p["type"]=="put" and abs(p["strike"]-strike)<1e-6]
        mid = 0.0
        if candidates:
            b = candidates[0].get('bid',0) or 0
            a = candidates[0].get('ask',0) or 0
            if a>0 or b>0:
                mid = (a if b==0 else b if a==0 else (a+b)/2)
        contracts = int(cash // (strike*100))
        if contracts < 1:
            return {"status":"skipped","reason":"insufficient cash for CSP"}
        prem = max(0.0, mid) * contracts * 100
        new_cash = self._cash() + prem - (strike*100*contracts)
        self.session.add(Trade(action="OPEN", symbol=f"{symbol}_P_{strike}_{expiry}", qty=contracts*100, price=prem, order_type="market", tag=tag, details="paper CSP"))
        self.session.add(Ledger(cash=new_cash, equity=0, note="open CSP reserve"))
        self.session.commit()
        return {"status":"ok","premium":prem,"contracts":contracts}

    def open_vertical_spread(self, symbol: str, kind: str, short_strike: float, long_strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        prem = 10.0
        cash = self._cash() + prem
        self.session.add(Trade(action="OPEN", symbol=f"{symbol}_{kind.upper()}_SPREAD_{expiry}", qty=1, price=prem, order_type="market", tag=tag, details="paper spread"))
        self.session.add(Ledger(cash=cash, equity=0, note="open spread"))
        self.session.commit()
        return {"status":"ok","premium":prem}

    def open_iron_condor(self, symbol: str, lower_put: float, upper_put: float, lower_call: float, upper_call: float, expiry: str, tag: str) -> Dict[str, Any]:
        chain = self.options_chain(symbol, expiry)
        chain = [o for o in chain if o.get('bid',0)>0 or o.get('ask',0)>0]
        legs = [
            {'type':'put','strike':upper_put,'side':'short'},
            {'type':'put','strike':lower_put,'side':'long'},
            {'type':'call','strike':lower_call,'side':'short'},
            {'type':'call','strike':upper_call,'side':'long'}
        ]
        credit = legs_mid_credit(chain, legs) or 12.0
        put_w = abs(upper_put - lower_put) * 100
        call_w = abs(upper_call - lower_call) * 100
        width = max(put_w, call_w)
        max_loss = max(0.0, width - credit)
        cash = self._cash() + credit - max_loss
        if cash < 0:
            return {"status":"skipped","reason":"insufficient cash for condor collateral"}
        self.session.add(Trade(action="OPEN", symbol=f"{symbol}_IC_{expiry}", qty=1, price=credit, order_type="market", tag=tag, details=f"max_loss={max_loss}"))
        self.session.add(Ledger(cash=cash, equity=0, note="open condor reserve"))
        self._add_option_position('condor','neutral', legs, expiry, credit)
        self.session.commit()
        return {"status":"ok","premium":credit,"max_loss":max_loss}

    def positions(self) -> list:
        return [{"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price, "type": p.type} for p in self.session.query(Position).all()]

    def ledger(self) -> dict:
        last = self.session.query(Ledger).order_by(Ledger.id.desc()).first()
        return {"cash": last.cash, "equity": last.equity}

    def close_option_positions(self, symbol: str):
        pass

    def close_option_by_calculated_debit(self, op_id: int, symbol: str, reason: str = "exit"):
        op = self.session.query(OptionPosition).filter(OptionPosition.id==op_id, OptionPosition.status=='open').first()
        if not op: 
            return {"status":"skip"}
        chain = self.options_chain(symbol, op.expiry)
        chain = [o for o in chain if o.get('bid',0)>0 or o.get('ask',0)>0]
        
        from ..util import legs_mid_credit
        credit_now = legs_mid_credit(chain, json.loads(op.legs))
        if credit_now is None:
            return {"status":"skip","reason":"no quotes"}
        debit = max(0.0, credit_now)
        cash = self._cash() - debit
        self.session.add(Trade(action="CLOSE", symbol=f"{symbol}_{op.kind}_{op.expiry}", qty=1, price=-debit, order_type="market", tag=reason, details=reason))
        self.session.add(Ledger(cash=cash, equity=0, note="close option"))
        op.status = 'closed'
        op.closed = datetime.utcnow()
        self.session.commit()
        return {"status":"ok","debit":debit}

    def close_all_options(self, symbol: str = None, expiry: str = None):
        from ..data.models import OptionPosition
        ops = self.session.query(OptionPosition).filter(OptionPosition.status=='open').all()
        n = 0
        for op in ops:
            sym = getattr(self, 'settings', None).options_symbol if getattr(self, 'settings', None) else symbol or 'QQQ'
            r = self.close_option_by_calculated_debit(op.id, sym, reason='CLOSEALL')
            if r.get('status')=='ok': n += 1
        return {'closed': n}
