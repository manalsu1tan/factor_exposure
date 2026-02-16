from __future__ import annotations

from typing import Dict

import numpy as np


def _daily_returns(prices: np.ndarray) -> np.ndarray:
    out = np.full(prices.shape[0], np.nan, dtype=float)
    out[1:] = (prices[1:] / prices[:-1]) - 1.0
    return out


def compute_raw_factor_point(
    prices: np.ndarray,
    volumes: np.ndarray,
    spy_prices: np.ndarray,
    idx: int,
) -> Dict[str, float]:
    if not (prices.shape == volumes.shape == spy_prices.shape):
        raise ValueError("prices, volumes, and spy_prices must have identical shape")
    if idx < 0 or idx >= prices.shape[0]:
        raise ValueError("idx out of bounds")

    out: Dict[str, float] = {
        "mom_12_1": float("nan"),
        "mom_6_1": float("nan"),
        "rev_1m": float("nan"),
        "beta_spy_252": float("nan"),
        "vol_63": float("nan"),
        "liq_dollarvol_21": float("nan"),
    }

    if idx >= 273 and np.isfinite(prices[idx - 21]) and np.isfinite(prices[idx - 273]):
        out["mom_12_1"] = float(prices[idx - 21] / prices[idx - 273] - 1.0)

    if idx >= 147 and np.isfinite(prices[idx - 21]) and np.isfinite(prices[idx - 147]):
        out["mom_6_1"] = float(prices[idx - 21] / prices[idx - 147] - 1.0)

    if idx >= 21 and np.isfinite(prices[idx]) and np.isfinite(prices[idx - 21]):
        out["rev_1m"] = float(-(prices[idx] / prices[idx - 21] - 1.0))

    rets = _daily_returns(prices)
    spy_rets = _daily_returns(spy_prices)

    if idx >= 62:
        window = rets[idx - 62 : idx + 1]
        if np.isfinite(window).all():
            out["vol_63"] = float(np.std(window, ddof=0))

    if idx >= 20:
        dv = prices[idx - 20 : idx + 1] * volumes[idx - 20 : idx + 1]
        if np.isfinite(dv).all():
            dv_mean = float(np.mean(dv))
            if dv_mean > 0:
                out["liq_dollarvol_21"] = float(np.log(dv_mean))

    if idx >= 251:
        x = rets[idx - 251 : idx + 1]
        y = spy_rets[idx - 251 : idx + 1]
        if np.isfinite(x).all() and np.isfinite(y).all():
            y_var = float(np.var(y, ddof=0))
            if y_var > 0:
                cov = float(np.mean((x - np.mean(x)) * (y - np.mean(y))))
                out["beta_spy_252"] = cov / y_var

    return out
