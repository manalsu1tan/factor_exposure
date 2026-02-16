from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


EventType = Literal[
    "TRADE",
    "MANUAL_ADJUSTMENT",
    "SPLIT",
    "DIVIDEND",
    "ADJUSTMENT",
    "CASH_DIVIDEND",
]
Side = Literal["BUY", "SELL"]


EVENT_TYPE_ALIASES = {
    "TRADE": "TRADE",
    "MANUAL_ADJUSTMENT": "MANUAL_ADJUSTMENT",
    "ADJUSTMENT": "MANUAL_ADJUSTMENT",
    "SPLIT": "SPLIT",
    "DIVIDEND": "DIVIDEND",
    "CASH_DIVIDEND": "DIVIDEND",
}


def canonical_event_type(value: str) -> str:
    key = value.upper().strip()
    canonical = EVENT_TYPE_ALIASES.get(key)
    if canonical is None:
        raise ValueError(f"Unknown event_type: {value}")
    return canonical


@dataclass(frozen=True)
class PositionEvent:
    event_id: str
    portfolio_id: str
    event_time: datetime
    ticker: str
    event_type: EventType
    quantity: float = 0.0
    side: Optional[Side] = None
    price: Optional[float] = None
    fees: float = 0.0
    split_ratio: Optional[float] = None
    cash_amount_per_share: Optional[float] = None
    source: Optional[str] = None


@dataclass(frozen=True)
class PositionSnapshotRow:
    ticker: str
    quantity: float
    avg_cost: float
    realized_pnl: float
    dividends_pnl: float
    total_pnl: float
    last_event_time: datetime
    change_reasons: list[str]
