from __future__ import annotations

from datetime import date

import pytest

from factor_exposure.api.main import (
    EodAnalyticsRequest,
    RealtimeAnalyticsRequest,
    ReconcileCloseRequest,
    eod_analytics,
    realtime_analytics,
    reconcile_close,
)


def test_realtime_endpoint_calls_portfolio_realtime_analytics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factor_exposure.api.main.load_latest_artifacts", lambda: object())
    monkeypatch.setattr(
        "factor_exposure.api.main.portfolio_realtime_analytics",
        lambda **_: {"ok": True, "portfolio_id": "book"},
    )

    out = realtime_analytics(RealtimeAnalyticsRequest(portfolio_id="book", as_of=date(2025, 1, 2)))
    assert out["ok"] is True
    assert out["portfolio_id"] == "book"


def test_eod_endpoint_calls_portfolio_eod_analytics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factor_exposure.api.main.load_latest_artifacts", lambda: object())
    monkeypatch.setattr(
        "factor_exposure.api.main.portfolio_eod_analytics",
        lambda **_: {"ok": True, "mode": "eod"},
    )
    out = eod_analytics(EodAnalyticsRequest(portfolio_id="book", as_of=date(2025, 1, 2), strict_close=True))
    assert out["ok"] is True
    assert out["mode"] == "eod"


def test_reconcile_endpoint_calls_reconcile_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factor_exposure.api.main.load_latest_artifacts", lambda: object())
    monkeypatch.setattr(
        "factor_exposure.api.main.reconcile_close_analytics",
        lambda **_: {"ok": True, "deltas": {}},
    )
    out = reconcile_close(ReconcileCloseRequest(portfolio_id="book", as_of=date(2025, 1, 2)))
    assert out["ok"] is True
