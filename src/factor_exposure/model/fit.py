from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import polars as pl


@dataclass(frozen=True)
class FitResult:
    factor_returns: pl.DataFrame  # columns: date + factors
    residuals: pl.DataFrame  # columns: date, ticker, residual


def fit_cross_sectional_factor_returns(
    exposures: pl.DataFrame,  # columns: date, ticker, factors...
    returns: pl.DataFrame,  # columns: date, ticker, ret
    factors: List[str],
    ridge: float = 1e-3,
) -> FitResult:
    """
    Per-date ridge regression:
      r = X f + e
    """
    merged = exposures.join(returns, on=["date", "ticker"], how="inner")
    merged = merged.drop_nulls(subset=[*factors, "ret"]).sort("date")

    factor_returns_rows: List[Tuple] = []
    residual_rows: List[Tuple] = []

    for g in merged.partition_by("date", as_dict=False, maintain_order=True):
        d = g.get_column("date")[0]
        X = g.select(factors).to_numpy().astype(float, copy=False)
        y = g.get_column("ret").to_numpy().astype(float, copy=False)

        min_obs = max(6, X.shape[1] + 1)
        if X.shape[0] < min_obs:
            continue

        XtX = X.T @ X
        XtX = XtX + ridge * np.eye(X.shape[1])
        Xty = X.T @ y
        f = np.linalg.solve(XtX, Xty)

        yhat = X @ f
        e = y - yhat

        factor_returns_rows.append((d, *f.tolist()))
        residual_rows.extend((d, t, float(r)) for t, r in zip(g.get_column("ticker").to_list(), e))

    factor_returns = pl.DataFrame(factor_returns_rows, schema=["date", *factors], orient="row")
    residuals = pl.DataFrame(residual_rows, schema=["date", "ticker", "residual"], orient="row")
    return FitResult(factor_returns=factor_returns, residuals=residuals)


def ewma_factor_cov(factor_returns: pl.DataFrame, factors: List[str], halflife: int = 60) -> np.ndarray:
    """
    EWMA covariance of factor returns, returned as (K, K) numpy array.
    """
    f = factor_returns.select(factors).to_numpy().astype(float, copy=False)
    if f.shape[0] == 0:
        raise ValueError("No factor return history available to estimate covariance")

    alpha = 1.0 - np.exp(np.log(0.5) / halflife)
    k = f.shape[1]
    cov = np.zeros((k, k), dtype=float)
    for i in range(f.shape[0]):
        x = f[i : i + 1].T
        cov = (1 - alpha) * cov + alpha * (x @ x.T)
    return cov


def ewma_specific_var(residuals: pl.DataFrame, halflife: int = 60) -> pl.DataFrame:
    """
    EWMA variance of residuals per ticker.
    Returns columns: date, ticker, specific_var (daily).
    """
    alpha = 1.0 - np.exp(np.log(0.5) / halflife)
    residuals = residuals.sort(["ticker", "date"])
    out_rows: List[Tuple] = []
    for g in residuals.partition_by("ticker", as_dict=False, maintain_order=True):
        ticker = g.get_column("ticker")[0]
        dates = g.get_column("date").to_list()
        eps = g.get_column("residual").to_numpy().astype(float, copy=False)
        v = 0.0
        initialized = False
        for d, e in zip(dates, eps):
            if not initialized:
                v = float(e * e)
                initialized = True
            else:
                v = (1 - alpha) * v + alpha * float(e * e)
            out_rows.append((d, ticker, v))
    return pl.DataFrame(out_rows, schema=["date", "ticker", "specific_var"], orient="row")
