from __future__ import annotations

from datetime import datetime, timezone

import pytest

from factor_exposure.api.main import PositionSnapshotRequest, position_snapshot
from factor_exposure.positions.schemas import PositionEvent


def test_position_snapshot_includes_market_value_and_unrealized(monkeypatch: pytest.MonkeyPatch) -> None:
    event = PositionEvent(
        event_id="e1",
        portfolio_id="book",
        event_time=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
        ticker="AAPL",
        event_type="TRADE",
        side="BUY",
        quantity=10.0,
        price=100.0,
    )

    monkeypatch.setattr("factor_exposure.api.main.load_events", lambda **_: [event])
    monkeypatch.setattr(
        "factor_exposure.api.main.load_latest_cached_prices",
        lambda **_: {"AAPL": {"date": datetime(2025, 1, 2).date(), "price": 110.0}},
    )

    out = position_snapshot(
        PositionSnapshotRequest(
            portfolio_id="book",
            as_of=datetime(2025, 1, 3, 0, 0, tzinfo=timezone.utc),
            include_closed=False,
        )
    )

    assert out["totals"]["market_value"] == pytest.approx(1100.0)
    assert out["totals"]["unrealized_pnl"] == pytest.approx(100.0)
    assert out["totals"]["economic_total_pnl"] == pytest.approx(100.0)
    assert out["rows"][0]["market_price"] == pytest.approx(110.0)
    assert out["rows"][0]["unrealized_pnl"] == pytest.approx(100.0)
