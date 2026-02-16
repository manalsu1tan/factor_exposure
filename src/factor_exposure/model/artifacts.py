from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import polars as pl


@dataclass(frozen=True)
class ModelArtifacts:
    as_of: date
    factors: List[str]
    exposures: Dict[Tuple[date, str], np.ndarray]  # keyed by (date, ticker), values in factor order
    factor_returns: Dict[date, np.ndarray]  # keyed by date, values in factor order
    factor_cov: np.ndarray  # shape (K, K)
    specific_returns: Dict[Tuple[date, str], float]  # keyed by (date, ticker)
    specific_returns_available: bool
    specific_var: Dict[Tuple[date, str], float]  # keyed by (date, ticker)
    asset_returns: Dict[Tuple[date, str], float] = field(default_factory=dict)  # keyed by (date, ticker)
    asset_returns_available: bool = False


def _model_root(data_root: Path) -> Path:
    return data_root / "model" / "latest"


def load_latest_artifacts(data_root: Path | None = None) -> ModelArtifacts:
    data_root = data_root or Path("data")
    root = _model_root(data_root)
    meta_path = root / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            "Model artifacts not found. Run: "
            "python -m factor_exposure.scripts.build_model --universe data/universe.csv --asof YYYY-MM-DD"
        )

    meta = json.loads(meta_path.read_text())
    factors = list(meta["factors"])
    as_of = date.fromisoformat(meta["as_of"])

    exposures_df = (
        pl.read_parquet(root / "exposures.parquet")
        .select("date", "ticker", *factors)
        .with_columns(pl.col("date").cast(pl.Date), pl.col("ticker").str.to_uppercase())
    )
    exposures: Dict[Tuple[date, str], np.ndarray] = {}
    for row in exposures_df.iter_rows(named=True):
        exposures[(row["date"], row["ticker"])] = np.array([float(row[f]) for f in factors], dtype=float)

    factor_returns_df = (
        pl.read_parquet(root / "factor_returns.parquet")
        .select("date", *factors)
        .with_columns(pl.col("date").cast(pl.Date))
    )
    factor_returns: Dict[date, np.ndarray] = {}
    for row in factor_returns_df.iter_rows(named=True):
        factor_returns[row["date"]] = np.array([float(row[f]) for f in factors], dtype=float)

    specific_returns: Dict[Tuple[date, str], float] = {}
    specific_returns_path = root / "specific_returns.parquet"
    specific_returns_available = specific_returns_path.exists()
    if specific_returns_available:
        specific_returns_df = (
            pl.read_parquet(specific_returns_path)
            .select("date", "ticker", "residual")
            .with_columns(pl.col("date").cast(pl.Date), pl.col("ticker").str.to_uppercase())
        )
        for row in specific_returns_df.iter_rows(named=True):
            specific_returns[(row["date"], row["ticker"])] = float(row["residual"])

    asset_returns: Dict[Tuple[date, str], float] = {}
    asset_returns_path = root / "asset_returns.parquet"
    asset_returns_available = asset_returns_path.exists()
    if asset_returns_available:
        asset_returns_df = (
            pl.read_parquet(asset_returns_path)
            .select("date", "ticker", "ret")
            .with_columns(pl.col("date").cast(pl.Date), pl.col("ticker").str.to_uppercase())
        )
        for row in asset_returns_df.iter_rows(named=True):
            asset_returns[(row["date"], row["ticker"])] = float(row["ret"])

    specific_var_df = (
        pl.read_parquet(root / "specific_var.parquet")
        .select("date", "ticker", "specific_var")
        .with_columns(pl.col("date").cast(pl.Date), pl.col("ticker").str.to_uppercase())
    )
    specific_var: Dict[Tuple[date, str], float] = {}
    for row in specific_var_df.iter_rows(named=True):
        specific_var[(row["date"], row["ticker"])] = float(row["specific_var"])

    factor_cov = np.load(root / "factor_cov.npy")

    return ModelArtifacts(
        as_of=as_of,
        factors=factors,
        exposures=exposures,
        factor_returns=factor_returns,
        factor_cov=factor_cov,
        specific_returns=specific_returns,
        specific_returns_available=specific_returns_available,
        asset_returns=asset_returns,
        asset_returns_available=asset_returns_available,
        specific_var=specific_var,
    )
