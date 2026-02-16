from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import polars as pl

from factor_exposure.positions.schemas import PositionEvent, canonical_event_type


EVENT_COLUMNS = [
    "event_id",
    "portfolio_id",
    "event_time",
    "ticker",
    "event_type",
    "quantity",
    "side",
    "price",
    "fees",
    "split_ratio",
    "cash_amount_per_share",
    "source",
]


def _events_path(data_root: Path) -> Path:
    return data_root / "positions" / "events.parquet"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _event_to_row(event: PositionEvent) -> dict:
    return {
        "event_id": event.event_id,
        "portfolio_id": event.portfolio_id,
        "event_time": event.event_time,
        "ticker": event.ticker.upper().strip(),
        "event_type": canonical_event_type(event.event_type),
        "quantity": float(event.quantity),
        "side": event.side,
        "price": None if event.price is None else float(event.price),
        "fees": float(event.fees),
        "split_ratio": None if event.split_ratio is None else float(event.split_ratio),
        "cash_amount_per_share": (
            None if event.cash_amount_per_share is None else float(event.cash_amount_per_share)
        ),
        "source": event.source,
    }


def _row_to_event(row: dict) -> PositionEvent:
    return PositionEvent(
        event_id=str(row["event_id"]),
        portfolio_id=str(row["portfolio_id"]),
        event_time=row["event_time"],
        ticker=str(row["ticker"]).upper(),
        event_type=canonical_event_type(str(row["event_type"])),
        quantity=float(row["quantity"]),
        side=row["side"],
        price=None if row["price"] is None else float(row["price"]),
        fees=float(row["fees"]),
        split_ratio=None if row["split_ratio"] is None else float(row["split_ratio"]),
        cash_amount_per_share=(
            None
            if row["cash_amount_per_share"] is None
            else float(row["cash_amount_per_share"])
        ),
        source=row["source"],
    )


def append_events(events: List[PositionEvent], data_root: Path | None = None) -> int:
    if not events:
        return 0

    data_root = data_root or Path("data")
    path = _events_path(data_root)
    _ensure_parent(path)

    prepared = []
    for event in events:
        event_id = event.event_id.strip() if event.event_id else str(uuid.uuid4())
        prepared.append(PositionEvent(**{**event.__dict__, "event_id": event_id}))

    append_df = (
        pl.DataFrame([_event_to_row(e) for e in prepared])
        .with_columns(
            pl.col("event_time").cast(pl.Datetime(time_unit="us")),
            pl.col("ticker").str.to_uppercase(),
            pl.col("portfolio_id").str.strip_chars(),
        )
        .select(EVENT_COLUMNS)
    )

    if path.exists():
        existing = pl.read_parquet(path).select(EVENT_COLUMNS)
        existing_ids = set(existing["event_id"].to_list())
        new_ids = append_df["event_id"].to_list()
        dup = sorted(set(new_ids) & existing_ids)
        if dup:
            raise ValueError(f"Duplicate event_id(s): {', '.join(dup[:5])}")
        full = (
            pl.concat([existing, append_df], how="vertical")
            .sort(["event_time", "event_id"])
            .select(EVENT_COLUMNS)
        )
    else:
        full = append_df.sort(["event_time", "event_id"]).select(EVENT_COLUMNS)

    full.write_parquet(path)
    return append_df.height


def load_events(
    portfolio_id: str,
    data_root: Path | None = None,
    ticker: Optional[str] = None,
    as_of: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> List[PositionEvent]:
    data_root = data_root or Path("data")
    path = _events_path(data_root)
    if not path.exists():
        return []

    df = pl.read_parquet(path).select(EVENT_COLUMNS)
    df = df.filter(pl.col("portfolio_id") == portfolio_id.strip())
    if ticker:
        df = df.filter(pl.col("ticker") == ticker.upper().strip())
    if as_of is not None:
        df = df.filter(pl.col("event_time") <= as_of)

    df = df.sort(["event_time", "event_id"])
    if limit is not None and limit > 0:
        df = df.tail(limit)

    return [_row_to_event(row) for row in df.iter_rows(named=True)]
