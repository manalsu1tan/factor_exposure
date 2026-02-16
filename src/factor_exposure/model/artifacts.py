from __future__ import annotations

import json
from dataclasses import dataclass
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
    factor_cov: np.ndarray  # shape (K, K)
    specific_var: Dict[Tuple[date, str], float]  # keyed by (date, ticker)


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
        factor_cov=factor_cov,
        specific_var=specific_var,
    )
