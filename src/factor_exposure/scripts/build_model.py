from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List

import numpy as np
import polars as pl

from factor_exposure.data.yfinance_cache import load_prices_cached
from factor_exposure.model.factors import DEFAULT_FACTORS, compute_exposures_daily
from factor_exposure.model.fit import (
    ewma_factor_cov,
    ewma_specific_var,
    fit_cross_sectional_factor_returns,
)


def _read_universe(path: Path) -> List[str]:
    df = pl.read_csv(path)
    tickers = [str(t).strip().upper() for t in df.get_column("ticker").to_list()]
    invalid = {"", "NONE", "NAN", "NULL", "NA"}
    return [t for t in tickers if t not in invalid]


def _join_wide_on_date(frames: List[pl.DataFrame]) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame({"date": []})
    out = frames[0]
    for frame in frames[1:]:
        out = out.join(frame, on="date", how="full", coalesce=True)
    return out.sort("date")


def _ticker_quality(adj_close_df: pl.DataFrame, volume_df: pl.DataFrame, tickers: List[str]) -> pl.DataFrame:
    total_days = max(adj_close_df.height, 1)
    rows = []
    for ticker in tickers:
        px = adj_close_df.select("date", ticker).drop_nulls(subset=[ticker]).sort("date")
        vol = volume_df.select("date", ticker).drop_nulls(subset=[ticker]).sort("date")
        px_days = px.height
        vol_days = vol.height
        rows.append(
            {
                "ticker": ticker,
                "price_obs_days": px_days,
                "volume_obs_days": vol_days,
                "price_coverage_ratio": float(px_days / total_days),
                "volume_coverage_ratio": float(vol_days / total_days),
                "first_price_date": px.select(pl.col("date").min()).item() if px_days > 0 else None,
                "last_price_date": px.select(pl.col("date").max()).item() if px_days > 0 else None,
            }
        )
    return pl.DataFrame(rows).sort("ticker")


def _factor_return_stats(factor_returns: pl.DataFrame, factors: List[str]) -> dict:
    stats = {}
    n = factor_returns.height
    for f in factors:
        col = factor_returns.get_column(f).to_numpy().astype(float, copy=False)
        mean = float(np.nanmean(col)) if n else 0.0
        std = float(np.nanstd(col, ddof=1)) if n > 1 else 0.0
        tstat = float(mean / (std / np.sqrt(n))) if n > 1 and std > 0 else 0.0
        stats[f] = {"mean": mean, "std": std, "tstat": tstat}
    return stats


def _fit_diagnostics(exposures: pl.DataFrame, returns: pl.DataFrame, factor_returns: pl.DataFrame, factors: List[str]) -> dict:
    merged = exposures.join(returns, on=["date", "ticker"], how="inner").drop_nulls(subset=[*factors, "ret"])
    fr_rows = {
        r["date"]: np.array([float(r[f]) for f in factors], dtype=float)
        for r in factor_returns.iter_rows(named=True)
    }

    rows = []
    for g in merged.partition_by("date", as_dict=False, maintain_order=True):
        d = g.get_column("date")[0]
        if d not in fr_rows:
            continue
        X = g.select(factors).to_numpy().astype(float, copy=False)
        y = g.get_column("ret").to_numpy().astype(float, copy=False)
        yhat = X @ fr_rows[d]
        resid = y - yhat
        sse = float(np.sum(resid * resid))
        y_mean = float(np.mean(y))
        sst = float(np.sum((y - y_mean) ** 2))
        r2 = float(1.0 - sse / sst) if sst > 0 else 0.0
        rows.append(
            {
                "date": d,
                "n_assets": int(X.shape[0]),
                "r2": r2,
                "residual_std": float(np.std(resid, ddof=0)),
            }
        )

    if not rows:
        return {
            "fit_dates": 0,
            "n_assets_mean": 0.0,
            "n_assets_min": 0,
            "n_assets_max": 0,
            "r2_mean": 0.0,
            "r2_median": 0.0,
            "r2_positive_ratio": 0.0,
            "residual_std_mean": 0.0,
        }

    diag = pl.DataFrame(rows)
    r2_vals = diag.get_column("r2").to_numpy().astype(float, copy=False)
    n_vals = diag.get_column("n_assets").to_numpy().astype(float, copy=False)
    resid_vals = diag.get_column("residual_std").to_numpy().astype(float, copy=False)
    return {
        "fit_dates": int(diag.height),
        "n_assets_mean": float(np.mean(n_vals)),
        "n_assets_min": int(np.min(n_vals)),
        "n_assets_max": int(np.max(n_vals)),
        "r2_mean": float(np.mean(r2_vals)),
        "r2_median": float(np.median(r2_vals)),
        "r2_positive_ratio": float(np.mean(r2_vals > 0.0)),
        "residual_std_mean": float(np.mean(resid_vals)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=str, required=True, help="CSV with column 'ticker'")
    parser.add_argument("--asof", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--lookback_years", type=int, default=10)
    parser.add_argument("--data_root", type=str, default="data")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.asof)
    start = as_of - timedelta(days=int(args.lookback_years * 365.25))
    data_root = Path(args.data_root)

    tickers = _read_universe(Path(args.universe))
    if "SPY" not in tickers:
        tickers = ["SPY", *tickers]

    # Download/cache prices; skip invalid/unavailable symbols except SPY.
    adj_close_frames: List[pl.DataFrame] = []
    volume_frames: List[pl.DataFrame] = []
    loaded_tickers: List[str] = []
    skipped_tickers: List[str] = []
    for t in tickers:
        try:
            pf = load_prices_cached(data_root=data_root, ticker=t, start=start, end=as_of)
        except ValueError:
            if t == "SPY":
                raise
            skipped_tickers.append(t)
            continue
        adj_close_frames.append(pf.df.select("date", pl.col("adj_close").alias(t)))
        volume_frames.append(pf.df.select("date", pl.col("volume").alias(t)))
        loaded_tickers.append(t)

    if skipped_tickers:
        print(f"Skipped tickers with no data: {', '.join(skipped_tickers)}")

    adj_close_df = _join_wide_on_date(adj_close_frames)
    volume_df = _join_wide_on_date(volume_frames)

    if "SPY" not in adj_close_df.columns:
        raise ValueError("SPY is required for beta factor")

    spy_adj_close = (
        adj_close_df.select("date", "SPY")
        .rename({"SPY": "adj_close"})
        .drop_nulls(subset=["adj_close"])
        .sort("date")
    )
    universe_tickers = [t for t in loaded_tickers if t != "SPY"]
    if not universe_tickers:
        raise ValueError("No valid non-SPY tickers available after filtering/downloading.")

    exposures = compute_exposures_daily(
        tickers=universe_tickers,
        adj_close=adj_close_df,
        volume=volume_df,
        spy_adj_close=spy_adj_close,
    )

    # Daily returns (next-day returns aligned to exposure date; simplest: same-day close-to-close)
    rets = adj_close_df.select(
        "date", *[pl.col(t).pct_change().alias(t) for t in universe_tickers]
    )
    returns = (
        rets.unpivot(
            index=["date"],
            on=universe_tickers,
            variable_name="ticker",
            value_name="ret",
        )
        .drop_nulls(subset=["ret"])
        .with_columns(pl.col("ticker").str.to_uppercase())
    )

    fit = fit_cross_sectional_factor_returns(
        exposures=exposures,
        returns=returns,
        factors=DEFAULT_FACTORS,
        ridge=1e-3,
    )

    factor_cov = ewma_factor_cov(fit.factor_returns, factors=DEFAULT_FACTORS, halflife=60)
    specific_var = ewma_specific_var(fit.residuals, halflife=60)

    ticker_quality = _ticker_quality(adj_close_df=adj_close_df, volume_df=volume_df, tickers=universe_tickers)
    fit_diag = _fit_diagnostics(
        exposures=exposures,
        returns=returns,
        factor_returns=fit.factor_returns,
        factors=DEFAULT_FACTORS,
    )
    factor_stats = _factor_return_stats(factor_returns=fit.factor_returns, factors=DEFAULT_FACTORS)

    data_quality = {
        "as_of": as_of.isoformat(),
        "calendar_start": start.isoformat(),
        "universe_requested": len(tickers) - 1,
        "universe_loaded": len(universe_tickers),
        "skipped_tickers": sorted(skipped_tickers),
        "model_days": int(adj_close_df.height),
        "returns_rows": int(returns.height),
        "exposures_rows": int(exposures.height),
        "factor_return_rows": int(fit.factor_returns.height),
        "specific_return_rows": int(fit.residuals.height),
        "avg_price_coverage_ratio": float(
            ticker_quality.select(pl.col("price_coverage_ratio").mean()).item() if ticker_quality.height > 0 else 0.0
        ),
        "avg_volume_coverage_ratio": float(
            ticker_quality.select(pl.col("volume_coverage_ratio").mean()).item() if ticker_quality.height > 0 else 0.0
        ),
    }

    model_diagnostics = {
        "as_of": as_of.isoformat(),
        "factor_count": len(DEFAULT_FACTORS),
        "covariance_condition_number": float(np.linalg.cond(factor_cov)),
        "fit": fit_diag,
        "factor_return_stats": factor_stats,
    }

    out_root = data_root / "model" / "latest"
    out_root.mkdir(parents=True, exist_ok=True)

    exposures.write_parquet(out_root / "exposures.parquet")
    fit.factor_returns.write_parquet(out_root / "factor_returns.parquet")
    fit.residuals.write_parquet(out_root / "specific_returns.parquet")
    returns.write_parquet(out_root / "asset_returns.parquet")
    np.save(out_root / "factor_cov.npy", factor_cov)
    specific_var.write_parquet(out_root / "specific_var.parquet")
    ticker_quality.write_parquet(out_root / "ticker_quality.parquet")
    (out_root / "data_quality.json").write_text(json.dumps(data_quality, indent=2, sort_keys=True))
    (out_root / "model_diagnostics.json").write_text(json.dumps(model_diagnostics, indent=2, sort_keys=True))

    metadata = {
        "as_of": as_of.isoformat(),
        "factors": DEFAULT_FACTORS,
        "universe_size": len(universe_tickers),
        "lookbacks": {
            "mom_12_1": 252,
            "mom_6_1": 126,
            "rev_1m": 21,
            "beta_spy_252": 252,
            "vol_63": 63,
            "liq_dollarvol_21": 21,
            "ewma_halflife_days": 60,
        },
    }
    (out_root / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))

    print(f"Wrote model artifacts to {out_root}")


if __name__ == "__main__":
    main()
