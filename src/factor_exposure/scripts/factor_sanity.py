from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np
import polars as pl

from factor_exposure.data.yfinance_cache import load_prices_cached
from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.model.factors import DEFAULT_FACTORS
from factor_exposure.model.sanity import compute_raw_factor_point


def _parse_compare_tickers(value: str) -> List[str]:
    tickers = []
    seen = set()
    for part in value.split(","):
        t = part.strip().upper()
        if not t:
            continue
        if t not in seen:
            tickers.append(t)
            seen.add(t)
    if not tickers:
        raise ValueError("compare list is empty; provide comma-separated tickers, e.g. AAPL,MSFT,NVDA")
    return tickers


def _aligned_series(data_root: Path, ticker: str, as_of: date) -> pl.DataFrame:
    start = as_of - timedelta(days=int(6 * 365.25))
    ticker_df = load_prices_cached(data_root=data_root, ticker=ticker, start=start, end=as_of).df
    spy_df = load_prices_cached(data_root=data_root, ticker="SPY", start=start, end=as_of).df

    aligned = (
        ticker_df.select(
            "date",
            pl.col("adj_close").alias("price"),
            pl.col("volume").alias("volume"),
        )
        .join(
            spy_df.select(
                "date",
                pl.col("adj_close").alias("spy_price"),
            ),
            on="date",
            how="inner",
        )
        .drop_nulls(subset=["price", "volume", "spy_price"])
        .sort("date")
    )
    if aligned.is_empty():
        raise ValueError(f"No aligned price history for {ticker} and SPY up to {as_of.isoformat()}")
    return aligned


def _asof_index(aligned: pl.DataFrame, as_of: date) -> int:
    dates = aligned.get_column("date").to_list()
    candidates = [i for i, d in enumerate(dates) if d <= as_of]
    if not candidates:
        raise ValueError(f"No trading date <= {as_of.isoformat()} in aligned history")
    return candidates[-1]


def _single_ticker_payload(
    ticker: str,
    as_of: date,
    data_root: Path,
    artifacts,
) -> Dict[str, object]:
    aligned = _aligned_series(data_root=data_root, ticker=ticker, as_of=as_of)
    idx = _asof_index(aligned, as_of=as_of)
    used_date = aligned.get_column("date")[idx]

    prices = aligned.get_column("price").to_numpy().astype(float, copy=False)
    volumes = aligned.get_column("volume").to_numpy().astype(float, copy=False)
    spy_prices = aligned.get_column("spy_price").to_numpy().astype(float, copy=False)
    raw = compute_raw_factor_point(prices=prices, volumes=volumes, spy_prices=spy_prices, idx=idx)

    z = artifacts.exposures.get((used_date, ticker))
    z_map = {f: float("nan") for f in DEFAULT_FACTORS} if z is None else {
        f: float(v) for f, v in zip(artifacts.factors, z)
    }

    return {
        "ticker": ticker,
        "requested_as_of": as_of.isoformat(),
        "used_as_of": used_date.isoformat(),
        "factors": {
            f: {
                "raw": None if not np.isfinite(raw[f]) else float(raw[f]),
                "zscore_exposure": None if not np.isfinite(z_map.get(f, np.nan)) else float(z_map[f]),
            }
            for f in DEFAULT_FACTORS
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ticker", type=str, help="Single ticker mode")
    mode.add_argument(
        "--compare",
        type=str,
        help="Comma-separated compare mode, e.g. AAPL,MSFT,NVDA",
    )
    parser.add_argument("--asof", type=str, required=False, help="YYYY-MM-DD; defaults to model as_of")
    parser.add_argument("--data_root", type=str, default="data")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    artifacts = load_latest_artifacts(data_root=data_root)
    as_of = date.fromisoformat(args.asof) if args.asof else artifacts.as_of
    notes = [
        "Raw factors are pre-winsor/pre-zscore units.",
        "Exposure factors are cross-sectional z-scores from model artifacts.",
        "rev_1m is short-term reversal: positive means recent laggard.",
    ]

    if args.ticker:
        ticker = args.ticker.strip().upper()
        single = _single_ticker_payload(ticker=ticker, as_of=as_of, data_root=data_root, artifacts=artifacts)
        result = {
            **single,
            "notes": notes,
        }
    else:
        tickers = _parse_compare_tickers(args.compare)
        rows = [
            _single_ticker_payload(ticker=t, as_of=as_of, data_root=data_root, artifacts=artifacts)
            for t in tickers
        ]
        factor_views = {}
        for f in DEFAULT_FACTORS:
            entries = [
                {
                    "ticker": row["ticker"],
                    "used_as_of": row["used_as_of"],
                    "raw": row["factors"][f]["raw"],
                    "zscore_exposure": row["factors"][f]["zscore_exposure"],
                }
                for row in rows
            ]
            entries.sort(
                key=lambda e: -abs(e["zscore_exposure"]) if e["zscore_exposure"] is not None else -1.0
            )
            factor_views[f] = entries
        result = {
            "mode": "compare",
            "requested_as_of": as_of.isoformat(),
            "tickers": tickers,
            "notes": notes,
            "rows": rows,
            "factor_views": factor_views,
        }

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
