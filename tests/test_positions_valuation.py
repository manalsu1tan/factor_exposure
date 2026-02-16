from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from factor_exposure.positions.valuation import load_latest_cached_prices, unrealized_pnl


def _write_price_cache(
    root: Path,
    ticker: str,
    rows: list[dict],
) -> None:
    path = root / "cache" / "yfinance" / "prices" / f"{ticker}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


def test_load_latest_cached_prices_uses_cutoff_date(tmp_path: Path) -> None:
    _write_price_cache(
        tmp_path,
        "AAPL",
        [
            {"date": "2025-01-01", "adj_close": 100.0},
            {"date": "2025-01-02", "adj_close": 101.5},
            {"date": "2025-01-03", "adj_close": 103.0},
        ],
    )
    px = load_latest_cached_prices(
        tickers=["AAPL"],
        as_of=datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc),
        data_root=tmp_path,
    )
    assert "AAPL" in px
    assert px["AAPL"]["price"] == pytest.approx(101.5)
    assert px["AAPL"]["date"].isoformat() == "2025-01-02"


def test_load_latest_cached_prices_falls_back_to_close(tmp_path: Path) -> None:
    _write_price_cache(
        tmp_path,
        "MSFT",
        [
            {"date": "2025-01-01", "close": 200.0},
            {"date": "2025-01-02", "close": 210.0},
        ],
    )
    px = load_latest_cached_prices(tickers=["MSFT"], data_root=tmp_path)
    assert px["MSFT"]["price"] == pytest.approx(210.0)


def test_unrealized_pnl_long_and_short() -> None:
    assert unrealized_pnl(quantity=10.0, avg_cost=100.0, market_price=105.0) == pytest.approx(50.0)
    assert unrealized_pnl(quantity=-5.0, avg_cost=100.0, market_price=90.0) == pytest.approx(50.0)
