from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from factor_exposure.positions.engine import build_snapshot
from factor_exposure.positions.schemas import PositionEvent


def _t(i: int) -> datetime:
    return datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc) + timedelta(minutes=i)


def _trade(
    event_id: str,
    minute: int,
    side: str,
    quantity: float,
    price: float,
    ticker: str = "AAPL",
    fees: float = 0.0,
) -> PositionEvent:
    return PositionEvent(
        event_id=event_id,
        portfolio_id="book",
        event_time=_t(minute),
        ticker=ticker,
        event_type="TRADE",
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
    )


def test_snapshot_weighted_avg_cost_and_position() -> None:
    events = [
        _trade("e1", 0, "BUY", 10, 100.0),
        _trade("e2", 1, "BUY", 20, 110.0),
    ]
    out = build_snapshot(events)
    row = out["AAPL"]
    assert row.quantity == pytest.approx(30.0)
    assert row.avg_cost == pytest.approx((10 * 100 + 20 * 110) / 30.0)
    assert row.realized_pnl == pytest.approx(0.0)
    assert row.change_reasons == ["trade"]


def test_snapshot_partial_close_realized_pnl() -> None:
    events = [
        _trade("e1", 0, "BUY", 10, 100.0),
        _trade("e2", 1, "SELL", 4, 115.0),
    ]
    out = build_snapshot(events)
    row = out["AAPL"]
    assert row.quantity == pytest.approx(6.0)
    assert row.avg_cost == pytest.approx(100.0)
    assert row.realized_pnl == pytest.approx(60.0)


def test_snapshot_flip_long_to_short_resets_avg_cost() -> None:
    events = [
        _trade("e1", 0, "BUY", 10, 100.0),
        _trade("e2", 1, "SELL", 15, 90.0),
    ]
    out = build_snapshot(events)
    row = out["AAPL"]
    assert row.quantity == pytest.approx(-5.0)
    assert row.avg_cost == pytest.approx(90.0)
    assert row.realized_pnl == pytest.approx(-100.0)


def test_snapshot_split_and_dividend() -> None:
    events = [
        _trade("e1", 0, "BUY", 10, 100.0),
        PositionEvent(
            event_id="e2",
            portfolio_id="book",
            event_time=_t(1),
            ticker="AAPL",
            event_type="SPLIT",
            split_ratio=2.0,
        ),
        PositionEvent(
            event_id="e3",
            portfolio_id="book",
            event_time=_t(2),
            ticker="AAPL",
            event_type="DIVIDEND",
            cash_amount_per_share=0.5,
        ),
    ]
    out = build_snapshot(events)
    row = out["AAPL"]
    assert row.quantity == pytest.approx(20.0)
    assert row.avg_cost == pytest.approx(50.0)
    assert row.dividends_pnl == pytest.approx(10.0)
    assert row.total_pnl == pytest.approx(10.0)
    assert row.change_reasons == ["dividend", "split", "trade"]


def test_snapshot_accepts_adjustment_alias() -> None:
    events = [
        _trade("e1", 0, "BUY", 10, 100.0),
        PositionEvent(
            event_id="e2",
            portfolio_id="book",
            event_time=_t(1),
            ticker="AAPL",
            event_type="ADJUSTMENT",
            quantity=-2.0,
            price=110.0,
        ),
    ]
    out = build_snapshot(events)
    row = out["AAPL"]
    assert row.quantity == pytest.approx(8.0)
    assert row.realized_pnl == pytest.approx(20.0)
    assert row.change_reasons == ["manual_adjustment", "trade"]


def test_snapshot_as_of_filter_and_closed_toggle() -> None:
    events = [
        _trade("e1", 0, "BUY", 5, 100.0, ticker="MSFT"),
        _trade("e2", 1, "SELL", 5, 110.0, ticker="MSFT"),
        _trade("e3", 2, "BUY", 2, 90.0, ticker="AAPL"),
    ]

    as_of = _t(1)
    out_default = build_snapshot(events, as_of=as_of, include_closed=False)
    assert "MSFT" not in out_default
    assert "AAPL" not in out_default

    out_with_closed = build_snapshot(events, as_of=as_of, include_closed=True)
    assert "MSFT" in out_with_closed
    assert out_with_closed["MSFT"].quantity == pytest.approx(0.0)
