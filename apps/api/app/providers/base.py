from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class InstrumentDraft:
    symbol: str
    ticker: str
    name: str
    instrument_type: str
    asset_class: str
    market: str
    currency: str
    lot_size: int = 1
    tick_size: float = 0.01
    theme: str | None = None
    provider: str = ""


@dataclass
class QuoteDTO:
    symbol: str
    price: float
    change: float | None
    change_pct: float | None
    prev_close: float | None
    as_of: datetime
    session: str  # regular|pre|post|closed|unknown
    stale: bool = False
    provider: str = ""


@dataclass
class BarDTO:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    finalized: bool = True


class MarketDataProvider(Protocol):
    name: str

    def search(self, keyword: str) -> list[InstrumentDraft]: ...

    def get_quote(self, symbol: str) -> QuoteDTO: ...

    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[BarDTO]: ...
