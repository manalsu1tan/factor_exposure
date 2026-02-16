from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from factor_exposure.model.artifacts import ModelArtifacts
from factor_exposure.portfolio.analytics import portfolio_realtime_analytics
from factor_exposure.positions.schemas import PositionEvent


def _artifacts() -> ModelArtifacts:
    d = date(2025, 1, 2)
    return ModelArtifacts(
        as_of=d,
        factors=["f1"],
        exposures={
            (d, "AAPL"): np.array([1.0]),
            (d, "MSFT"): np.array([2.0]),
        },
        factor_returns={d: np.array([0.01])},
        factor_cov=np.array([[1.0]], dtype=float),
        specific_returns={},
        specific_returns_available=False,
        specific_var={(d, "AAPL"): 0.0, (d, "MSFT"): 0.0},
    )


def test_realtime_analytics_uses_positions_and_latest_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        PositionEvent(
            event_id="e1",
            portfolio_id="book",
            event_time=datetime(2025, 1, 2, 10, 0),
            ticker="AAPL",
            event_type="TRADE",
            side="BUY",
            quantity=10,
            price=100.0,
        ),
        PositionEvent(
            event_id="e2",
            portfolio_id="book",
            event_time=datetime(2025, 1, 2, 10, 1),
            ticker="MSFT",
            event_type="TRADE",
            side="BUY",
            quantity=20,
            price=50.0,
        ),
    ]

    monkeypatch.setattr("factor_exposure.portfolio.analytics.load_events", lambda **_: events)
    monkeypatch.setattr(
        "factor_exposure.portfolio.analytics.load_latest_cached_prices",
        lambda **_: {
            "AAPL": {"date": date(2025, 1, 2), "price": 110.0},
            "MSFT": {"date": date(2025, 1, 2), "price": 40.0},
        },
    )

    out = portfolio_realtime_analytics(
        portfolio_id="book",
        artifacts=_artifacts(),
        as_of=date(2025, 1, 3),
    )

    assert out["resolved_as_of"] == "2025-01-02"
    assert out["positions"]["priced_tickers"] == 2
    assert out["positions"]["market_value"] == pytest.approx(1900.0)
    assert out["positions"]["gross_market_value"] == pytest.approx(1900.0)
    assert out["analytics"]["factor_exposures"]["f1"] == pytest.approx((1100 * 1 + 800 * 2) / 1900)
