from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from factor_exposure.model.artifacts import ModelArtifacts
from factor_exposure.portfolio.analytics import (
    portfolio_analytics,
    portfolio_attribution,
    portfolio_scenario,
)


def _mock_artifacts() -> ModelArtifacts:
    d1 = date(2025, 1, 2)
    d2 = date(2025, 1, 3)
    factors = ["f1", "f2"]
    exposures = {
        (d1, "A"): np.array([1.0, 2.0]),
        (d1, "B"): np.array([3.0, 4.0]),
        (d2, "A"): np.array([1.0, 2.0]),
        (d2, "B"): np.array([3.0, 4.0]),
    }
    factor_returns = {
        d1: np.array([0.01, -0.02]),
        d2: np.array([0.02, 0.01]),
    }
    factor_cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    specific_returns = {
        (d1, "A"): 0.01,
        (d1, "B"): -0.02,
        (d2, "A"): 0.0,
        (d2, "B"): 0.02,
    }
    asset_returns = {
        (d1, "A"): -0.019,
        (d1, "B"): -0.065,
        (d2, "A"): 0.041,
        (d2, "B"): 0.118,
    }
    specific_var = {
        (d1, "A"): 0.01,
        (d1, "B"): 0.04,
        (d2, "A"): 0.01,
        (d2, "B"): 0.04,
    }
    return ModelArtifacts(
        as_of=d1,
        factors=factors,
        exposures=exposures,
        factor_returns=factor_returns,
        factor_cov=factor_cov,
        specific_returns=specific_returns,
        specific_returns_available=True,
        specific_var=specific_var,
        asset_returns=asset_returns,
        asset_returns_available=True,
    )


def test_portfolio_analytics_core_math() -> None:
    artifacts = _mock_artifacts()
    out = portfolio_analytics([("A", 0.5), ("B", 0.5)], artifacts, as_of=date(2025, 1, 2))

    assert out["coverage"]["covered"] == 2
    assert out["factor_exposures"]["f1"] == 2.0
    assert out["factor_exposures"]["f2"] == 3.0
    assert out["risk"]["variance"]["factor"] == pytest.approx(0.97)
    assert out["risk"]["variance"]["specific"] == pytest.approx(0.0125)
    assert out["risk"]["variance"]["total"] == pytest.approx(0.9825)


def test_portfolio_scenario_core_math() -> None:
    artifacts = _mock_artifacts()
    out = portfolio_scenario(
        [("A", 0.5), ("B", 0.5)],
        artifacts,
        factor_shocks={"f1": 0.1},
        as_of=date(2025, 1, 2),
        specific_shock=1.0,
    )

    assert out["pnl"]["factor"] == pytest.approx(0.2)
    assert out["pnl"]["factor_contrib"]["f1"] == pytest.approx(0.2)
    assert out["pnl"]["factor_contrib"]["f2"] == pytest.approx(0.0)
    assert out["pnl"]["specific"] == pytest.approx(0.15)
    assert out["pnl"]["total"] == pytest.approx(0.35)


def test_portfolio_attribution_totals_and_modes() -> None:
    artifacts = _mock_artifacts()

    summary = portfolio_attribution(
        [("A", 0.5), ("B", 0.5)],
        artifacts,
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 3),
        include_daily=False,
    )
    assert "daily" not in summary
    assert summary["totals"]["factor_return"] == pytest.approx(0.03)
    assert summary["totals"]["specific_return"] == pytest.approx(0.005)
    assert summary["totals"]["total_return"] == pytest.approx(0.035)
    assert summary["quality"]["available"] is True
    assert summary["quality"]["days_compared"] == 2
    assert summary["quality"]["mean_residual"] == pytest.approx(0.00125)
    assert summary["quality"]["mae_residual"] == pytest.approx(0.00175)

    paged = portfolio_attribution(
        [("A", 0.5), ("B", 0.5)],
        artifacts,
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 3),
        include_daily=True,
        limit=1,
        offset=1,
        compact=True,
    )
    assert paged["daily_page"]["returned"] == 1
    assert paged["daily"][0]["date"] == "2025-01-03"
    assert "factor_contrib" not in paged["daily"][0]
    assert "quality" in paged["daily"][0]
    assert paged["daily"][0]["quality"]["residual_return"] == pytest.approx(-0.0005)


def test_portfolio_attribution_quality_toggle() -> None:
    artifacts = _mock_artifacts()
    out = portfolio_attribution(
        [("A", 0.5), ("B", 0.5)],
        artifacts,
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 3),
        include_daily=True,
        include_quality=False,
    )
    assert out["quality"]["available"] is False
    assert out["quality"]["days_compared"] == 0
    assert "quality" not in out["daily"][0]
