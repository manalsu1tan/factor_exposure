from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from factor_exposure.model.artifacts import ModelArtifacts
from factor_exposure.portfolio.analytics import portfolio_eod_analytics, reconcile_close_analytics
from factor_exposure.positions.schemas import PositionEvent


def _artifacts() -> ModelArtifacts:
    d = date(2025, 1, 2)
    return ModelArtifacts(
        as_of=d,
        factors=["f1"],
        exposures={(d, "AAPL"): np.array([1.0])},
        factor_returns={d: np.array([0.01])},
        factor_cov=np.array([[1.0]], dtype=float),
        specific_returns={},
        specific_returns_available=False,
        specific_var={(d, "AAPL"): 0.0},
    )


def _events() -> list[PositionEvent]:
    return [
        PositionEvent(
            event_id="e1",
            portfolio_id="book",
            event_time=datetime(2025, 1, 2, 10, 0),
            ticker="AAPL",
            event_type="TRADE",
            side="BUY",
            quantity=10.0,
            price=100.0,
        )
    ]


def test_eod_analytics_uses_exact_close_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factor_exposure.portfolio.analytics.load_events", lambda **_: _events())
    monkeypatch.setattr(
        "factor_exposure.portfolio.analytics.load_cached_prices_on_date",
        lambda **_: {"AAPL": {"date": date(2025, 1, 2), "price": 110.0}},
    )

    out = portfolio_eod_analytics(
        portfolio_id="book",
        artifacts=_artifacts(),
        as_of=date(2025, 1, 2),
        strict_close=True,
    )
    assert out["mode"] == "eod"
    assert out["positions"]["market_value"] == pytest.approx(1100.0)
    assert out["positions"]["unrealized_pnl"] == pytest.approx(100.0)
    assert out["strict_close"] is True


def test_reconcile_close_returns_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factor_exposure.portfolio.analytics.load_events", lambda **_: _events())
    monkeypatch.setattr(
        "factor_exposure.portfolio.analytics.load_latest_cached_prices",
        lambda **_: {"AAPL": {"date": date(2025, 1, 2), "price": 112.0}},
    )
    monkeypatch.setattr(
        "factor_exposure.portfolio.analytics.load_cached_prices_on_date",
        lambda **_: {"AAPL": {"date": date(2025, 1, 2), "price": 110.0}},
    )

    out = reconcile_close_analytics(portfolio_id="book", artifacts=_artifacts(), as_of=date(2025, 1, 2))
    assert out["deltas"]["market_value"] == pytest.approx(20.0)
    assert out["deltas"]["unrealized_pnl"] == pytest.approx(20.0)
    assert out["deltas"]["economic_total_pnl"] == pytest.approx(20.0)
