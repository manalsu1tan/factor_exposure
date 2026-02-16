from __future__ import annotations

import numpy as np
import pytest

from factor_exposure.model.sanity import compute_raw_factor_point
from factor_exposure.scripts.factor_sanity import _parse_compare_tickers


def test_compute_raw_factor_point_basic() -> None:
    n = 400
    t = np.arange(n, dtype=float)
    prices = 100.0 + t
    volumes = 1_000_000.0 + 1000.0 * t
    spy_prices = 200.0 + 0.5 * t
    idx = n - 1

    out = compute_raw_factor_point(prices=prices, volumes=volumes, spy_prices=spy_prices, idx=idx)

    expected_mom12 = prices[idx - 21] / prices[idx - 273] - 1.0
    expected_mom6 = prices[idx - 21] / prices[idx - 147] - 1.0
    expected_rev = -(prices[idx] / prices[idx - 21] - 1.0)
    expected_liq = np.log(np.mean(prices[idx - 20 : idx + 1] * volumes[idx - 20 : idx + 1]))

    rets = np.full(n, np.nan, dtype=float)
    spy_rets = np.full(n, np.nan, dtype=float)
    rets[1:] = prices[1:] / prices[:-1] - 1.0
    spy_rets[1:] = spy_prices[1:] / spy_prices[:-1] - 1.0
    expected_vol = np.std(rets[idx - 62 : idx + 1], ddof=0)
    x = rets[idx - 251 : idx + 1]
    y = spy_rets[idx - 251 : idx + 1]
    expected_beta = np.mean((x - np.mean(x)) * (y - np.mean(y))) / np.var(y, ddof=0)

    assert out["mom_12_1"] == pytest.approx(expected_mom12)
    assert out["mom_6_1"] == pytest.approx(expected_mom6)
    assert out["rev_1m"] == pytest.approx(expected_rev)
    assert out["liq_dollarvol_21"] == pytest.approx(expected_liq)
    assert out["vol_63"] == pytest.approx(expected_vol)
    assert out["beta_spy_252"] == pytest.approx(expected_beta)


def test_compute_raw_factor_point_insufficient_history() -> None:
    n = 50
    prices = np.linspace(100.0, 150.0, n)
    volumes = np.linspace(1_000_000.0, 1_100_000.0, n)
    spy_prices = np.linspace(200.0, 220.0, n)

    out = compute_raw_factor_point(prices=prices, volumes=volumes, spy_prices=spy_prices, idx=n - 1)
    assert np.isnan(out["mom_12_1"])
    assert np.isnan(out["mom_6_1"])
    assert np.isnan(out["beta_spy_252"])
    assert np.isfinite(out["rev_1m"])
    assert np.isfinite(out["liq_dollarvol_21"])


def test_parse_compare_tickers() -> None:
    parsed = _parse_compare_tickers("aapl, MSFT, aapl, nvda")
    assert parsed == ["AAPL", "MSFT", "NVDA"]


def test_parse_compare_tickers_empty_errors() -> None:
    with pytest.raises(ValueError, match="compare list is empty"):
        _parse_compare_tickers(" , , ")
