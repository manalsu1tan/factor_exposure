from __future__ import annotations

import pytest

from factor_exposure.explain.explainer import explain_portfolio_report


def _report() -> dict:
    return {
        "as_of": "2025-12-31",
        "views_expressed": [
            {"factor": "liq_dollarvol_21", "exposure": 0.5},
            {"factor": "vol_63", "exposure": -0.4},
            {"factor": "rev_1m", "exposure": 0.3},
        ],
        "top_risk_contributors": [
            {"factor": "vol_63", "variance_contrib": 0.001},
            {"factor": "liq_dollarvol_21", "variance_contrib": 0.0008},
        ],
        "drift_window": {"start_date": "2025-01-01", "end_date": "2025-12-31", "rows": 250},
        "drift_top_factors": [
            {"factor": "rev_1m", "delta": 0.4},
            {"factor": "vol_63", "delta": -0.2},
        ],
    }


def test_heuristic_mode_returns_structured_output() -> None:
    out = explain_portfolio_report(_report(), mode="heuristic")
    assert out["mode"] == "heuristic"
    assert isinstance(out["overview"], str) and out["overview"]
    assert len(out["key_views"]) > 0
    assert len(out["risk_watchouts"]) > 0
    assert len(out["drift_story"]) > 0
    assert len(out["scenario_implications"]) > 0
    assert len(out["limitations"]) > 0


def test_auto_mode_falls_back_to_heuristic_without_api_key() -> None:
    out = explain_portfolio_report(_report(), mode="auto")
    assert out["mode"] == "heuristic"


def test_invalid_mode_errors() -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        explain_portfolio_report(_report(), mode="invalid")
