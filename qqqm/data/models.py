from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from .db import Base
from datetime import datetime

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    qty = Column(Float, default=0)
    avg_price = Column(Float, default=0)
    type = Column(String, default="equity")  # equity | option

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.utcnow)
    action = Column(String)       # BUY/SELL/SHORT/COVER/OPEN/CLOSE
    symbol = Column(String)
    qty = Column(Float)
    price = Column(Float)
    order_type = Column(String)   # market/limit
    tag = Column(String)          # DCA/CC/CSP/SPREAD/CONDOR
    details = Column(Text)

class Ledger(Base):
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.utcnow)
    cash = Column(Float)
    equity = Column(Float)
    note = Column(String)

class SettingKV(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text)


class RiskItem(Base):
    __tablename__ = "risk_items"
    id = Column(Integer, primary_key=True)
    kind = Column(String)          # spread/condor
    risk_amount = Column(Float)    # max loss in dollars
    opened = Column(DateTime, default=datetime.utcnow)
    closed = Column(DateTime, nullable=True)
    direction = Column(String)     # bull/bear/neutral


class OptionPosition(Base):
    __tablename__ = "option_positions"
    id = Column(Integer, primary_key=True)
    kind = Column(String)            # spread | condor | cc | csp
    direction = Column(String)       # bull | bear | neutral
    entry_credit = Column(Float)     # total credit received
    expiry = Column(String)          # YYYY-MM-DD
    legs = Column(Text)              # JSON encoded legs [{'type':'call/put','strike':x,'side':'short/long'}]
    status = Column(String, default="open")
    opened = Column(DateTime, default=datetime.utcnow)
    closed = Column(DateTime, nullable=True)
