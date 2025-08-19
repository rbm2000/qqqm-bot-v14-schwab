from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session

_engine = None
SessionLocal = None
Base = declarative_base()

def init_db(db_url: str):
    global _engine, SessionLocal
    _engine = create_engine(db_url, echo=False, future=True)
    session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    SessionLocal = scoped_session(session_factory)
    Base.metadata.create_all(_engine)
    return SessionLocal