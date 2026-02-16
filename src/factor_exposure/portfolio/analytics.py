from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from factor_exposure.model.artifacts import ModelArtifacts


def _normalize_weights(holdings: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    denom = sum(abs(w) for _, w in holdings)
    if denom <= 0:
        raise ValueError("Sum of absolute weights must be > 0")
    return [(t, w / denom) for t, w in holdings]


def portfolio_analytics(
    holdings: List[Tuple[str, float]],
    artifacts: ModelArtifacts,
    as_of: Optional[date] = None,
) -> Dict[str, object]:
    holdings = [(t.upper().strip(), float(w)) for t, w in holdings]
    holdings = _normalize_weights(holdings)

    as_of = as_of or artifacts.as_of
    factors = artifacts.factors

    missing: List[str] = []
    rows = []
    for ticker, w in holdings:
        key = (as_of, ticker)
        x = artifacts.exposures.get(key)
        if x is None:
            missing.append(ticker)
            continue

        sv = float(artifacts.specific_var.get(key, 0.0))

        rows.append((ticker, w, x.astype(float, copy=False), sv))

    if not rows:
        raise ValueError("No holdings covered by model artifacts for requested as_of date")

    w = np.array([r[1] for r in rows], dtype=float)  # (N,)
    X = np.stack([r[2] for r in rows], axis=0)  # (N,K)
    spec_var = np.array([r[3] for r in rows], dtype=float)  # (N,)

    b = (w[:, None] * X).sum(axis=0)  # (K,)
    cov = artifacts.factor_cov.astype(float)

    factor_var = float(b.T @ cov @ b)
    specific_var = float(np.sum((w * w) * spec_var))
    total_var = factor_var + specific_var

    # Simple factor variance decomposition: component variances b_i * (Cov b)_i
    cov_b = cov @ b
    factor_contrib = {f: float(bi * ci) for f, bi, ci in zip(factors, b.tolist(), cov_b.tolist())}

    daily_vol = float(np.sqrt(max(total_var, 0.0)))
    annualized_vol = float(daily_vol * np.sqrt(252.0))

    return {
        "as_of": as_of.isoformat(),
        "coverage": {
            "requested": len(holdings),
            "covered": len(rows),
            "missing": missing,
        },
        "factor_exposures": {f: float(v) for f, v in zip(factors, b.tolist())},
        "risk": {
            "daily_vol": daily_vol,
            "annualized_vol": annualized_vol,
            "variance": {"total": total_var, "factor": factor_var, "specific": specific_var},
            "factor_variance_contrib": factor_contrib,
        },
    }
