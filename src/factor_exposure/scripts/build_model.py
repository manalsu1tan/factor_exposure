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

    out_root = data_root / "model" / "latest"
    out_root.mkdir(parents=True, exist_ok=True)

    exposures.write_parquet(out_root / "exposures.parquet")
    fit.factor_returns.write_parquet(out_root / "factor_returns.parquet")
    np.save(out_root / "factor_cov.npy", factor_cov)
    specific_var.write_parquet(out_root / "specific_var.parquet")

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
