from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np
import polars as pl


DEFAULT_FACTORS: List[str] = [
    "mom_12_1",
    "mom_6_1",
    "rev_1m",
    "beta_spy_252",
    "vol_63",
    "liq_dollarvol_21",
]


def _wide_to_matrix(df: pl.DataFrame, tickers: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    ordered = df.select(["date", *tickers]).sort("date")
    dates = ordered.get_column("date").to_numpy()
    mat = ordered.select(tickers).to_numpy().astype(float, copy=False)
    return dates, mat


def _pct_change(mat: np.ndarray, periods: int = 1) -> np.ndarray:
    out = np.full_like(mat, np.nan, dtype=float)
    out[periods:, :] = (mat[periods:, :] / mat[:-periods, :]) - 1.0
    return out


def _rolling_std(mat: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(mat, np.nan, dtype=float)
    if mat.shape[0] < window:
        return out
    for i in range(window - 1, mat.shape[0]):
        slice_ = mat[i - window + 1 : i + 1, :]
        out[i, :] = np.nanstd(slice_, axis=0, ddof=0)
    return out


def _rolling_beta(asset_ret: np.ndarray, spy_ret: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(asset_ret, np.nan, dtype=float)
    if asset_ret.shape[0] < window:
        return out
    for i in range(window - 1, asset_ret.shape[0]):
        x = asset_ret[i - window + 1 : i + 1, :]
        y = spy_ret[i - window + 1 : i + 1]
        y_var = np.nanvar(y, ddof=0)
        if not np.isfinite(y_var) or y_var <= 0:
            continue
        x_mean = np.nanmean(x, axis=0)
        y_mean = np.nanmean(y)
        cov = np.nanmean((x - x_mean) * (y[:, None] - y_mean), axis=0)
        out[i, :] = cov / y_var
    return out


def _winsorize_rows(arr: np.ndarray, z: float = 5.0) -> np.ndarray:
    out = arr.copy()
    for i in range(out.shape[0]):
        row = out[i, :]
        valid = np.isfinite(row)
        if not valid.any():
            continue
        mu = np.nanmean(row)
        sd = np.nanstd(row, ddof=0)
        if not np.isfinite(sd) or sd <= 0:
            continue
        lo = mu - z * sd
        hi = mu + z * sd
        row[valid] = np.clip(row[valid], lo, hi)
        out[i, :] = row
    return out


def _zscore_rows(arr: np.ndarray) -> np.ndarray:
    out = np.full_like(arr, np.nan, dtype=float)
    for i in range(arr.shape[0]):
        row = arr[i, :]
        valid = np.isfinite(row)
        if not valid.any():
            continue
        mu = np.nanmean(row[valid])
        sd = np.nanstd(row[valid], ddof=0)
        if not np.isfinite(sd) or sd <= 0:
            out[i, valid] = 0.0
            continue
        out[i, valid] = (row[valid] - mu) / sd
    return np.nan_to_num(out, nan=0.0)


def _factor_long_frame(dates: np.ndarray, tickers: List[str], factor_mats: Dict[str, np.ndarray]) -> pl.DataFrame:
    rows = len(dates) * len(tickers)
    date_col = np.repeat(dates, len(tickers))
    ticker_col = np.tile(np.array(tickers, dtype=object), len(dates))
    cols: Dict[str, np.ndarray] = {"date": date_col, "ticker": ticker_col}
    for name in DEFAULT_FACTORS:
        cols[name] = factor_mats[name].reshape(rows)
    out = pl.DataFrame(cols)
    valid_expr = pl.any_horizontal([pl.col(name).is_not_null() for name in DEFAULT_FACTORS])
    return out.filter(valid_expr)


def compute_exposures_daily(
    tickers: Iterable[str],
    adj_close: pl.DataFrame,  # columns: date + tickers
    volume: pl.DataFrame,  # columns: date + tickers
    spy_adj_close: pl.DataFrame,  # columns: date, adj_close
) -> pl.DataFrame:
    """
    Returns long-form exposures:
      columns: date, ticker, factors...
    Each factor is cross-sectionally z-scored per date.
    """
    tickers = list(tickers)
    dates, prices = _wide_to_matrix(adj_close, tickers)
    _, vols = _wide_to_matrix(volume, tickers)

    spy = spy_adj_close.sort("date").get_column("adj_close").to_numpy().astype(float, copy=False)
    if spy.shape[0] != prices.shape[0]:
        spy_by_date = spy_adj_close.rename({"adj_close": "spy"}).join(
            pl.DataFrame({"date": dates}),
            on="date",
            how="right",
        ).sort("date")
        spy = spy_by_date.get_column("spy").to_numpy().astype(float, copy=False)

    rets = _pct_change(prices, 1)
    spy_ret = _pct_change(spy.reshape(-1, 1), 1).reshape(-1)

    mom_12_1 = np.roll(_pct_change(prices, 252), 21, axis=0)
    mom_12_1[:21, :] = np.nan
    mom_6_1 = np.roll(_pct_change(prices, 126), 21, axis=0)
    mom_6_1[:21, :] = np.nan
    rev_1m = -_pct_change(prices, 21)
    vol_63 = _rolling_std(rets, 63)

    dollar_vol = prices * vols
    liq_dollarvol_21 = np.full_like(dollar_vol, np.nan, dtype=float)
    for i in range(21 - 1, dollar_vol.shape[0]):
        liq_dollarvol_21[i, :] = np.nanmean(dollar_vol[i - 21 + 1 : i + 1, :], axis=0)
    liq_dollarvol_21 = np.log(np.where(liq_dollarvol_21 > 0, liq_dollarvol_21, np.nan))

    beta_spy_252 = _rolling_beta(rets, spy_ret, 252)

    factor_wide = {
        "mom_12_1": mom_12_1,
        "mom_6_1": mom_6_1,
        "rev_1m": rev_1m,
        "beta_spy_252": beta_spy_252,
        "vol_63": vol_63,
        "liq_dollarvol_21": liq_dollarvol_21,
    }

    zscored: Dict[str, np.ndarray] = {}
    for name, mat in factor_wide.items():
        clean = np.where(np.isfinite(mat), mat, np.nan)
        wins = _winsorize_rows(clean)
        zscored[name] = _zscore_rows(wins)

    return _factor_long_frame(dates=dates, tickers=tickers, factor_mats=zscored)
