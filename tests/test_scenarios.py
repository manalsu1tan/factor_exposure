from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from factor_exposure.portfolio.scenarios import resolve_factor_shocks


FACTORS = [
    "mom_12_1",
    "mom_6_1",
    "rev_1m",
    "beta_spy_252",
    "vol_63",
    "liq_dollarvol_21",
]


def test_resolve_template_only() -> None:
    shocks = resolve_factor_shocks(FACTORS, template="market_down_5", factor_shocks=None)
    assert shocks == {"beta_spy_252": -0.05}


def test_resolve_template_with_overrides() -> None:
    shocks = resolve_factor_shocks(
        FACTORS,
        template="market_down_5",
        factor_shocks={"beta_spy_252": -0.03, "mom_12_1": 0.01},
    )
    assert shocks["beta_spy_252"] == -0.03
    assert shocks["mom_12_1"] == 0.01


def test_resolve_requires_template_or_shocks() -> None:
    with pytest.raises(ValueError, match="Provide either template or factor_shocks"):
        resolve_factor_shocks(FACTORS, template=None, factor_shocks=None)


def test_resolve_unknown_template_errors() -> None:
    with pytest.raises(ValueError, match="Unknown scenario template"):
        resolve_factor_shocks(FACTORS, template="does_not_exist", factor_shocks=None)


def test_resolve_unknown_factor_errors() -> None:
    with pytest.raises(ValueError, match="Unknown factors in shocks"):
        resolve_factor_shocks(FACTORS, template=None, factor_shocks={"not_a_factor": 0.1})


def _factor_history(n: int = 30) -> dict:
    base = date(2025, 1, 1)
    history = {}
    for i in range(n):
        history[base + timedelta(days=i)] = np.array(
            [
                -0.02 + i * 0.001,   # mom_12_1
                -0.01 + i * 0.0008,  # mom_6_1
                -0.03 + i * 0.0015,  # rev_1m
                -0.04 + i * 0.002,   # beta_spy_252
                -0.015 + i * 0.001,  # vol_63
                -0.025 + i * 0.0012, # liq_dollarvol_21
            ],
            dtype=float,
        )
    return history


def test_sigma_calibration_for_template() -> None:
    history = _factor_history(40)
    shocks = resolve_factor_shocks(
        FACTORS,
        template="market_down_5",
        factor_shocks=None,
        factor_returns=history,
        calibration_mode="sigma",
        sigma_multiplier=2.0,
    )
    beta_series = np.array([row[3] for _, row in sorted(history.items(), key=lambda kv: kv[0])], dtype=float)
    expected = -2.0 * float(np.std(beta_series, ddof=1))
    assert shocks["beta_spy_252"] == pytest.approx(expected)


def test_percentile_calibration_for_template_sign() -> None:
    history = _factor_history(40)
    shocks = resolve_factor_shocks(
        FACTORS,
        template="momentum_crash",
        factor_shocks=None,
        factor_returns=history,
        calibration_mode="percentile",
        percentile=0.1,
    )
    ordered = [row for _, row in sorted(history.items(), key=lambda kv: kv[0])]
    mom_12 = np.array([row[0] for row in ordered], dtype=float)
    mom_6 = np.array([row[1] for row in ordered], dtype=float)
    rev = np.array([row[2] for row in ordered], dtype=float)
    assert shocks["mom_12_1"] == pytest.approx(float(np.quantile(mom_12, 0.1)))
    assert shocks["mom_6_1"] == pytest.approx(float(np.quantile(mom_6, 0.1)))
    assert shocks["rev_1m"] == pytest.approx(float(np.quantile(rev, 0.9)))


def test_calibration_validation_errors() -> None:
    history = _factor_history(10)
    with pytest.raises(ValueError, match="at least 20 factor-return observations"):
        resolve_factor_shocks(
            FACTORS,
            template="market_down_5",
            factor_shocks=None,
            factor_returns=history,
            calibration_mode="sigma",
        )
    with pytest.raises(ValueError, match="percentile must be in"):
        resolve_factor_shocks(
            FACTORS,
            template="market_down_5",
            factor_shocks=None,
            factor_returns=_factor_history(30),
            calibration_mode="percentile",
            percentile=0.0,
        )
