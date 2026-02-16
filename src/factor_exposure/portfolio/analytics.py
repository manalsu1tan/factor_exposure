from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from factor_exposure.model.artifacts import ModelArtifacts
from factor_exposure.positions.engine import build_snapshot
from factor_exposure.positions.store import load_events
from factor_exposure.positions.valuation import (
    load_cached_prices_on_date,
    load_latest_cached_prices,
    unrealized_pnl,
)


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


def portfolio_scenario(
    holdings: List[Tuple[str, float]],
    artifacts: ModelArtifacts,
    factor_shocks: Dict[str, float],
    as_of: Optional[date] = None,
    specific_shock: float = 0.0,
    template: Optional[str] = None,
) -> Dict[str, object]:
    holdings = [(t.upper().strip(), float(w)) for t, w in holdings]
    holdings = _normalize_weights(holdings)
    as_of = as_of or artifacts.as_of
    factors = artifacts.factors

    unknown = sorted(set(factor_shocks.keys()) - set(factors))
    if unknown:
        raise ValueError(f"Unknown factors in shocks: {', '.join(unknown)}")

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

    w = np.array([r[1] for r in rows], dtype=float)
    X = np.stack([r[2] for r in rows], axis=0)
    spec_var = np.array([r[3] for r in rows], dtype=float)

    exposures = (w[:, None] * X).sum(axis=0)
    shock_vec = np.array([float(factor_shocks.get(f, 0.0)) for f in factors], dtype=float)
    factor_contrib = {f: float(exposures[i] * shock_vec[i]) for i, f in enumerate(factors)}
    factor_pnl = float(sum(factor_contrib.values()))

    specific_vol = np.sqrt(np.maximum(spec_var, 0.0))
    specific_pnl = float(np.sum(w * specific_vol) * float(specific_shock))
    total_pnl = factor_pnl + specific_pnl

    return {
        "as_of": as_of.isoformat(),
        "coverage": {
            "requested": len(holdings),
            "covered": len(rows),
            "missing": missing,
        },
        "scenario": {
            "template": template,
            "factor_shocks": {k: float(v) for k, v in factor_shocks.items()},
            "specific_shock": float(specific_shock),
        },
        "exposures": {f: float(v) for f, v in zip(factors, exposures.tolist())},
        "pnl": {
            "factor": factor_pnl,
            "specific": specific_pnl,
            "total": total_pnl,
            "factor_contrib": factor_contrib,
        },
    }


def portfolio_attribution(
    holdings: List[Tuple[str, float]],
    artifacts: ModelArtifacts,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_daily: bool = True,
    limit: Optional[int] = None,
    offset: int = 0,
    compact: bool = False,
    include_quality: bool = True,
) -> Dict[str, object]:
    if not artifacts.specific_returns_available:
        raise ValueError(
            "specific_returns.parquet is missing. Rebuild artifacts with "
            "python -m factor_exposure.scripts.build_model --universe data/universe.csv --asof YYYY-MM-DD"
        )

    holdings = [(t.upper().strip(), float(w)) for t, w in holdings]
    holdings = _normalize_weights(holdings)
    factors = artifacts.factors

    available_dates = sorted(artifacts.factor_returns.keys())
    if not available_dates:
        raise ValueError("No factor return history available for attribution")

    effective_start = start_date or available_dates[0]
    effective_end = end_date or available_dates[-1]
    if effective_start > effective_end:
        raise ValueError("start_date must be <= end_date")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be > 0 when provided")

    selected_dates = [d for d in available_dates if effective_start <= d <= effective_end]
    if not selected_dates:
        raise ValueError("No factor return dates in requested range")

    requested_tickers = [t for t, _ in holdings]
    available_any_date = set()
    for d in selected_dates:
        for t in requested_tickers:
            if (d, t) in artifacts.exposures:
                available_any_date.add(t)
    missing = sorted(set(requested_tickers) - available_any_date)

    daily_rows_all: List[Dict[str, object]] = []
    total_factor_by_name = {f: 0.0 for f in factors}
    total_specific = 0.0
    total_return = 0.0
    covered_days = 0
    quality_enabled = bool(include_quality and artifacts.asset_returns_available)
    quality_explained: List[float] = []
    quality_realized: List[float] = []
    quality_residuals: List[float] = []

    for d in selected_dates:
        f_ret = artifacts.factor_returns.get(d)
        if f_ret is None:
            continue

        active_rows = []
        for ticker, w in holdings:
            x = artifacts.exposures.get((d, ticker))
            if x is None:
                continue
            s = float(artifacts.specific_returns.get((d, ticker), 0.0))
            r = artifacts.asset_returns.get((d, ticker)) if quality_enabled else None
            active_rows.append((ticker, w, x, s, r))

        if not active_rows:
            continue

        active_weight_denom = sum(abs(w) for _, w, _, _, _ in active_rows)
        if active_weight_denom <= 0:
            continue

        weights = np.array([w / active_weight_denom for _, w, _, _, _ in active_rows], dtype=float)
        exposures = np.stack([x for _, _, x, _, _ in active_rows], axis=0)
        specific = np.array([s for _, _, _, s, _ in active_rows], dtype=float)

        factor_by_name = {}
        factor_total = 0.0
        for idx, name in enumerate(factors):
            contrib = float(np.sum(weights * exposures[:, idx]) * float(f_ret[idx]))
            factor_by_name[name] = contrib
            total_factor_by_name[name] += contrib
            factor_total += contrib

        specific_total = float(np.sum(weights * specific))
        total_day = factor_total + specific_total
        total_specific += specific_total
        total_return += total_day
        covered_days += 1

        row = {
            "date": d.isoformat(),
            "factor_return": factor_total,
            "specific_return": specific_total,
            "total_return": total_day,
            "coverage": {
                "active_holdings": len(active_rows),
                "requested_holdings": len(holdings),
            },
        }
        if quality_enabled:
            comparable = [
                (w, x, s, float(r))
                for _, w, x, s, r in active_rows
                if r is not None and np.isfinite(r)
            ]
            if comparable:
                q_denom = sum(abs(w) for w, _, _, _ in comparable)
                if q_denom > 0:
                    q_weights = np.array([w / q_denom for w, _, _, _ in comparable], dtype=float)
                    q_exp = np.stack([x for _, x, _, _ in comparable], axis=0)
                    q_spec = np.array([s for _, _, s, _ in comparable], dtype=float)
                    q_realized = np.array([r for _, _, _, r in comparable], dtype=float)
                    explained = float(np.sum(q_weights * (q_exp @ f_ret + q_spec)))
                    realized = float(np.sum(q_weights * q_realized))
                    residual = float(realized - explained)
                    quality_explained.append(explained)
                    quality_realized.append(realized)
                    quality_residuals.append(residual)
                    row["quality"] = {
                        "explained_return": explained,
                        "realized_return": realized,
                        "residual_return": residual,
                        "comparable_holdings": len(comparable),
                    }
        if not compact:
            row["factor_contrib"] = factor_by_name
        daily_rows_all.append(row)

    if covered_days == 0:
        raise ValueError("No overlapping exposure and return data in requested range")

    response = {
        "start_date": selected_dates[0].isoformat(),
        "end_date": selected_dates[-1].isoformat(),
        "coverage": {
            "requested_holdings": len(holdings),
            "holdings_with_any_data": len(set(requested_tickers) - set(missing)),
            "missing": missing,
            "days_requested": len(selected_dates),
            "days_with_data": covered_days,
        },
        "totals": {
            "factor_return": float(sum(total_factor_by_name.values())),
            "specific_return": total_specific,
            "total_return": total_return,
            "factor_contrib": total_factor_by_name,
        },
    }

    quality_summary: Dict[str, object] = {
        "available": quality_enabled,
        "days_compared": len(quality_residuals),
    }
    if quality_enabled and quality_residuals:
        res = np.array(quality_residuals, dtype=float)
        exp = np.array(quality_explained, dtype=float)
        real = np.array(quality_realized, dtype=float)
        rmse = float(np.sqrt(np.mean(res * res)))
        mae = float(np.mean(np.abs(res)))
        mean_res = float(np.mean(res))
        std_res = float(np.std(res, ddof=1)) if len(res) > 1 else 0.0
        tstat = float(mean_res / (std_res / np.sqrt(len(res)))) if len(res) > 1 and std_res > 0 else 0.0
        corr = float(np.corrcoef(exp, real)[0, 1]) if len(res) > 1 and np.std(exp) > 0 and np.std(real) > 0 else 0.0
        ss_res = float(np.sum((real - exp) ** 2))
        ss_tot = float(np.sum((real - np.mean(real)) ** 2))
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        quality_summary.update(
            {
                "mean_residual": mean_res,
                "mae_residual": mae,
                "rmse_residual": rmse,
                "residual_tstat": tstat,
                "corr_explained_vs_realized": corr,
                "r2_explained_vs_realized": r2,
                "sum_explained": float(np.sum(exp)),
                "sum_realized": float(np.sum(real)),
            }
        )
    response["quality"] = quality_summary

    if include_daily:
        start_idx = min(offset, len(daily_rows_all))
        end_idx = len(daily_rows_all) if limit is None else min(start_idx + limit, len(daily_rows_all))
        response["daily"] = daily_rows_all[start_idx:end_idx]
        response["daily_page"] = {
            "offset": offset,
            "limit": limit,
            "returned": len(response["daily"]),
            "total_available": len(daily_rows_all),
        }

    return response


def portfolio_realtime_analytics(
    portfolio_id: str,
    artifacts: ModelArtifacts,
    as_of: Optional[date] = None,
    data_root: Path | None = None,
) -> Dict[str, object]:
    portfolio_id = portfolio_id.strip()
    if not portfolio_id:
        raise ValueError("portfolio_id must be non-empty")

    as_of_date = as_of or artifacts.as_of
    cutoff_dt = datetime.combine(as_of_date, time.max)

    events = load_events(portfolio_id=portfolio_id, as_of=cutoff_dt, data_root=data_root)
    if not events:
        raise ValueError("No position events found for portfolio_id")

    snapshot = build_snapshot(events=events, as_of=cutoff_dt, include_closed=False)
    if not snapshot:
        raise ValueError("No open positions after applying events")

    rows = sorted(snapshot.values(), key=lambda r: r.ticker)
    price_map = load_latest_cached_prices(tickers=[r.ticker for r in rows], as_of=cutoff_dt, data_root=data_root)
    return _positions_analytics_result(
        mode="realtime",
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        rows=rows,
        price_map=price_map,
        artifacts=artifacts,
        event_count=len(events),
    )


def portfolio_eod_analytics(
    portfolio_id: str,
    artifacts: ModelArtifacts,
    as_of: Optional[date] = None,
    data_root: Path | None = None,
    strict_close: bool = True,
) -> Dict[str, object]:
    portfolio_id = portfolio_id.strip()
    if not portfolio_id:
        raise ValueError("portfolio_id must be non-empty")

    as_of_date = as_of or artifacts.as_of
    cutoff_dt = datetime.combine(as_of_date, time.max)

    events = load_events(portfolio_id=portfolio_id, as_of=cutoff_dt, data_root=data_root)
    if not events:
        raise ValueError("No position events found for portfolio_id")

    snapshot = build_snapshot(events=events, as_of=cutoff_dt, include_closed=False)
    if not snapshot:
        raise ValueError("No open positions after applying events")

    rows = sorted(snapshot.values(), key=lambda r: r.ticker)
    price_map = load_cached_prices_on_date(
        tickers=[r.ticker for r in rows],
        as_of=as_of_date,
        data_root=data_root,
        exact=strict_close,
    )
    return _positions_analytics_result(
        mode="eod",
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        rows=rows,
        price_map=price_map,
        artifacts=artifacts,
        strict_close=strict_close,
        event_count=len(events),
    )


def reconcile_close_analytics(
    portfolio_id: str,
    artifacts: ModelArtifacts,
    as_of: Optional[date] = None,
    data_root: Path | None = None,
) -> Dict[str, object]:
    as_of_date = as_of or artifacts.as_of
    realtime = portfolio_realtime_analytics(
        portfolio_id=portfolio_id,
        artifacts=artifacts,
        as_of=as_of_date,
        data_root=data_root,
    )
    eod = portfolio_eod_analytics(
        portfolio_id=portfolio_id,
        artifacts=artifacts,
        as_of=as_of_date,
        data_root=data_root,
        strict_close=True,
    )

    rt_analytics = realtime["analytics"]
    eod_analytics = eod["analytics"]
    factors = sorted(set(rt_analytics["factor_exposures"]) | set(eod_analytics["factor_exposures"]))
    exposure_delta = {
        f: float(rt_analytics["factor_exposures"].get(f, 0.0) - eod_analytics["factor_exposures"].get(f, 0.0))
        for f in factors
    }
    return {
        "portfolio_id": portfolio_id.strip(),
        "as_of": as_of_date.isoformat(),
        "realtime": realtime,
        "eod": eod,
        "deltas": {
            "market_value": float(realtime["positions"]["market_value"] - eod["positions"]["market_value"]),
            "unrealized_pnl": float(realtime["positions"]["unrealized_pnl"] - eod["positions"]["unrealized_pnl"]),
            "economic_total_pnl": float(
                realtime["positions"]["economic_total_pnl"] - eod["positions"]["economic_total_pnl"]
            ),
            "annualized_vol": float(
                rt_analytics["risk"]["annualized_vol"] - eod_analytics["risk"]["annualized_vol"]
            ),
            "exposure_delta": exposure_delta,
            "unpriced_tickers": {
                "realtime": realtime["positions"]["unpriced_tickers"],
                "eod": eod["positions"]["unpriced_tickers"],
            },
        },
    }


def _positions_analytics_result(
    mode: str,
    portfolio_id: str,
    as_of_date: date,
    rows: list,
    price_map: Dict[str, Dict[str, object]],
    artifacts: ModelArtifacts,
    strict_close: bool = False,
    event_count: Optional[int] = None,
) -> Dict[str, object]:
    
    holdings_mv: List[Tuple[str, float]] = []
    unpriced: List[str] = []
    position_rows = []
    total_realized = float(sum(r.realized_pnl for r in rows))
    total_dividends = float(sum(r.dividends_pnl for r in rows))
    total_realized_and_div = float(sum(r.total_pnl for r in rows))
    total_unrealized = 0.0
    for row in rows:
        px = price_map.get(row.ticker)
        if px is None:
            unpriced.append(row.ticker)
            position_rows.append(
                {
                    "ticker": row.ticker,
                    "quantity": row.quantity,
                    "avg_cost": row.avg_cost,
                    "market_price": None,
                    "price_as_of": None,
                    "market_value": None,
                    "realized_pnl": row.realized_pnl,
                    "dividends_pnl": row.dividends_pnl,
                    "total_pnl": row.total_pnl,
                    "unrealized_pnl": None,
                    "economic_total_pnl": None,
                    "change_reasons": row.change_reasons,
                }
            )
            continue
        market_price = float(px["price"])
        price_as_of = px["date"].isoformat()
        mv = float(row.quantity * market_price)
        unrealized = unrealized_pnl(quantity=row.quantity, avg_cost=row.avg_cost, market_price=market_price)
        total_unrealized += unrealized
        if abs(mv) > 1e-12:
            holdings_mv.append((row.ticker, mv))
        position_rows.append(
            {
                "ticker": row.ticker,
                "quantity": row.quantity,
                "avg_cost": row.avg_cost,
                "market_price": market_price,
                "price_as_of": price_as_of,
                "market_value": mv,
                "realized_pnl": row.realized_pnl,
                "dividends_pnl": row.dividends_pnl,
                "total_pnl": row.total_pnl,
                "unrealized_pnl": unrealized,
                "economic_total_pnl": float(row.total_pnl + unrealized),
                "change_reasons": row.change_reasons,
            }
        )

    if not holdings_mv:
        raise ValueError(f"No priced open positions available for {mode} analytics")

    exposure_dates = sorted({d for d, _ in artifacts.exposures.keys()})
    if not exposure_dates:
        raise ValueError("No exposure history in model artifacts")
    resolved_as_of = max((d for d in exposure_dates if d <= as_of_date), default=exposure_dates[-1])

    analytics = portfolio_analytics(holdings=holdings_mv, artifacts=artifacts, as_of=resolved_as_of)

    market_value = float(sum(v for _, v in holdings_mv))
    gross_market_value = float(sum(abs(v) for _, v in holdings_mv))
    economic_total = float(total_realized_and_div + total_unrealized)

    return {
        "mode": mode,
        "portfolio_id": portfolio_id,
        "requested_as_of": as_of_date.isoformat(),
        "resolved_as_of": resolved_as_of.isoformat(),
        "strict_close": bool(strict_close),
        "positions": {
            "event_count": event_count,
            "open_tickers": len(rows),
            "priced_tickers": len(holdings_mv),
            "unpriced_tickers": unpriced,
            "market_value": market_value,
            "gross_market_value": gross_market_value,
            "realized_pnl": total_realized,
            "dividends_pnl": total_dividends,
            "total_pnl": total_realized_and_div,
            "unrealized_pnl": total_unrealized,
            "economic_total_pnl": economic_total,
            "rows": position_rows,
        },
        "analytics": analytics,
    }
