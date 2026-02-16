from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import polars as pl

from factor_exposure.model.artifacts import ModelArtifacts
from factor_exposure.portfolio.analytics import portfolio_analytics


def _normalize_weights(holdings: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    clean = [(t.upper().strip(), float(w)) for t, w in holdings]
    denom = sum(abs(w) for _, w in clean)
    if denom <= 0:
        raise ValueError("Sum of absolute weights must be > 0")
    return [(t, w / denom) for t, w in clean]


def _exposure_timeseries(
    holdings: List[Tuple[str, float]],
    artifacts: ModelArtifacts,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pl.DataFrame:
    factors = artifacts.factors
    holdings = _normalize_weights(holdings)

    all_dates = sorted(artifacts.factor_returns.keys())
    if not all_dates:
        return pl.DataFrame({"date": []})
    start = start_date or all_dates[0]
    end = end_date or all_dates[-1]

    rows: List[Dict[str, object]] = []
    for d in all_dates:
        if d < start or d > end:
            continue

        covered = []
        for ticker, w in holdings:
            x = artifacts.exposures.get((d, ticker))
            if x is not None:
                covered.append((ticker, w, x))
        if not covered:
            continue

        denom = sum(abs(w) for _, w, _ in covered)
        if denom <= 0:
            continue

        weights = np.array([w / denom for _, w, _ in covered], dtype=float)
        X = np.stack([x for _, _, x in covered], axis=0)
        b = (weights[:, None] * X).sum(axis=0)

        row = {"date": d, "covered_holdings": len(covered), "requested_holdings": len(holdings)}
        row.update({f: float(v) for f, v in zip(factors, b.tolist())})
        rows.append(row)

    if not rows:
        return pl.DataFrame({"date": []})
    return pl.DataFrame(rows).sort("date")


def build_portfolio_report(
    holdings: List[Tuple[str, float]],
    artifacts: ModelArtifacts,
    as_of: Optional[date] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    top_n: int = 5,
) -> Dict[str, object]:
    as_of = as_of or artifacts.as_of
    analytics = portfolio_analytics(holdings=holdings, artifacts=artifacts, as_of=as_of)
    factors = artifacts.factors
    top_n = max(1, int(top_n))

    views = sorted(
        analytics["factor_exposures"].items(),
        key=lambda kv: abs(float(kv[1])),
        reverse=True,
    )[:top_n]
    risk_top = sorted(
        analytics["risk"]["factor_variance_contrib"].items(),
        key=lambda kv: abs(float(kv[1])),
        reverse=True,
    )[:top_n]

    exp_ts = _exposure_timeseries(holdings, artifacts, start_date=start_date, end_date=end_date)
    drift_rows: List[Dict[str, object]] = []
    if exp_ts.height > 1:
        first = exp_ts.row(0, named=True)
        last = exp_ts.row(exp_ts.height - 1, named=True)
        for f in factors:
            start_val = float(first[f])
            end_val = float(last[f])
            drift_rows.append(
                {
                    "factor": f,
                    "start_exposure": start_val,
                    "end_exposure": end_val,
                    "delta": end_val - start_val,
                    "abs_delta": abs(end_val - start_val),
                }
            )
        drift_rows = sorted(drift_rows, key=lambda r: r["abs_delta"], reverse=True)[:top_n]

    return {
        "as_of": as_of.isoformat(),
        "views_expressed": [{"factor": k, "exposure": float(v)} for k, v in views],
        "top_risk_contributors": [{"factor": k, "variance_contrib": float(v)} for k, v in risk_top],
        "drift_window": {
            "start_date": exp_ts.select(pl.col("date").min()).item().isoformat() if exp_ts.height > 0 else None,
            "end_date": exp_ts.select(pl.col("date").max()).item().isoformat() if exp_ts.height > 0 else None,
            "rows": int(exp_ts.height),
        },
        "drift_top_factors": drift_rows,
        "exposure_timeseries": exp_ts,
        "analytics_snapshot": analytics,
    }
