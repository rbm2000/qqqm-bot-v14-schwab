from abc import ABC, abstractmethod
from typing import Dict, Any, List

class Broker(ABC):
    @abstractmethod
    def account(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def price(self, symbol: str) -> float:
        ...

    # returns list of dicts: {'strike': float, 'expiry': 'YYYY-MM-DD', 'type': 'call/put', 'bid': float, 'ask': float}
    @abstractmethod
    def options_chain(self, symbol: str, expiry: str | None = None) -> List[dict]:
        ...

    @abstractmethod
    def buy_equity(self, symbol: str, qty: float, tag: str, note: str = "") -> Dict[str, Any]:
        ...

    @abstractmethod
    def sell_equity(self, symbol: str, qty: float, tag: str, note: str = "") -> Dict[str, Any]:
        ...

    @abstractmethod
    def sell_covered_call(self, symbol: str, shares: int, strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def sell_cash_secured_put(self, symbol: str, cash: float, strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def open_vertical_spread(self, symbol: str, kind: str, short_strike: float, long_strike: float, expiry: str, tag: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def open_iron_condor(self, symbol: str, lower_put: float, upper_put: float, lower_call: float, upper_call: float, expiry: str, tag: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def positions(self) -> list:
        ...

    @abstractmethod
    def ledger(self) -> dict:
        ...
