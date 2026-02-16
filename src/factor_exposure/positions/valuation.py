from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import polars as pl


def _price_cache_path(data_root: Path, ticker: str) -> Path:
    return data_root / "cache" / "yfinance" / "prices" / f"{ticker.upper().strip()}.parquet"


def load_latest_cached_prices(
    tickers: List[str],
    as_of: Optional[datetime] = None,
    data_root: Path | None = None,
) -> Dict[str, Dict[str, object]]:
    data_root = data_root or Path("data")
    cutoff: Optional[date] = as_of.date() if as_of is not None else None
    out: Dict[str, Dict[str, object]] = {}

    for ticker in sorted(set(t.upper().strip() for t in tickers if t.strip())):
        path = _price_cache_path(data_root, ticker)
        if not path.exists():
            continue

        df = pl.read_parquet(path)
        if "date" not in df.columns:
            continue
        price_col = "adj_close" if "adj_close" in df.columns else ("close" if "close" in df.columns else None)
        if price_col is None:
            continue

        slim = (
            df.select(pl.col("date").cast(pl.Date).alias("date"), pl.col(price_col).cast(pl.Float64).alias("price"))
            .drop_nulls(["date", "price"])
            .sort("date")
        )
        if cutoff is not None:
            slim = slim.filter(pl.col("date") <= pl.lit(cutoff))
        if slim.is_empty():
            continue

        last = slim.tail(1).to_dicts()[0]
        out[ticker] = {"date": last["date"], "price": float(last["price"])}

    return out


def load_cached_prices_on_date(
    tickers: List[str],
    as_of: date,
    data_root: Path | None = None,
    exact: bool = True,
) -> Dict[str, Dict[str, object]]:
    data_root = data_root or Path("data")
    out: Dict[str, Dict[str, object]] = {}

    for ticker in sorted(set(t.upper().strip() for t in tickers if t.strip())):
        path = _price_cache_path(data_root, ticker)
        if not path.exists():
            continue

        df = pl.read_parquet(path)
        if "date" not in df.columns:
            continue
        price_col = "adj_close" if "adj_close" in df.columns else ("close" if "close" in df.columns else None)
        if price_col is None:
            continue

        slim = (
            df.select(pl.col("date").cast(pl.Date).alias("date"), pl.col(price_col).cast(pl.Float64).alias("price"))
            .drop_nulls(["date", "price"])
            .sort("date")
        )
        if slim.is_empty():
            continue

        if exact:
            exact_row = slim.filter(pl.col("date") == pl.lit(as_of))
            if exact_row.is_empty():
                continue
            last = exact_row.tail(1).to_dicts()[0]
        else:
            upto = slim.filter(pl.col("date") <= pl.lit(as_of))
            if upto.is_empty():
                continue
            last = upto.tail(1).to_dicts()[0]

        out[ticker] = {"date": last["date"], "price": float(last["price"])}

    return out


def unrealized_pnl(quantity: float, avg_cost: float, market_price: float) -> float:
    return float((market_price - avg_cost) * quantity)
