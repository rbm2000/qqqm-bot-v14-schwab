from typing import Optional
import os

from .brokers.paper import PaperBroker
from .brokers.alpaca import AlpacaBroker
from .brokers.tradier import TradierBroker
from .brokers.schwab import SchwabBroker

def make_broker(name: str):
    """
    Central broker constructor used by both web/app and bot modules
    to avoid circular imports.
    """
    name = (name or "paper").lower()
    if name == "paper":
        start = float(os.getenv("STARTING_CASH", "1000"))
        return PaperBroker(starting_cash=start)
    if name == "alpaca":
        return AlpacaBroker()
    if name == "tradier":
        return TradierBroker()
    if name == "schwab":
        return SchwabBroker()
    raise ValueError(f"Unknown broker: {name}")
