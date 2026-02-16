from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from factor_exposure.explain.explainer import explain_portfolio_report
from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.positions.engine import build_snapshot
from factor_exposure.positions.schemas import PositionEvent, canonical_event_type
from factor_exposure.positions.store import append_events, load_events
from factor_exposure.positions.valuation import load_latest_cached_prices, unrealized_pnl
from factor_exposure.portfolio.analytics import (
    portfolio_analytics,
    portfolio_attribution,
    portfolio_eod_analytics,
    portfolio_realtime_analytics,
    reconcile_close_analytics,
    portfolio_scenario,
)
from factor_exposure.portfolio.scenarios import list_scenario_templates, resolve_factor_shocks
from factor_exposure.reporting.report import build_portfolio_report


app = FastAPI(title="factor_exposure", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Holding(BaseModel):
    ticker: str = Field(..., description="US equity ticker, e.g. AAPL")
    weight: float = Field(..., description="Portfolio weight (can be negative).")


class AnalyticsRequest(BaseModel):
    as_of: Optional[date] = Field(
        None, description="As-of date. Defaults to latest date in model artifacts."
    )
    holdings: List[Holding]


class AttributionRequest(BaseModel):
    start_date: Optional[date] = Field(
        None, description="Start date (inclusive). Defaults to earliest model date."
    )
    end_date: Optional[date] = Field(
        None, description="End date (inclusive). Defaults to latest model date."
    )
    include_daily: bool = Field(
        True, description="If false, returns only summary totals/coverage without daily rows."
    )
    limit: Optional[int] = Field(
        None, description="Optional max number of daily rows to return (used with include_daily=true)."
    )
    offset: int = Field(
        0, description="Optional start index for daily rows (used with include_daily=true)."
    )
    compact: bool = Field(
        False, description="If true, daily rows omit per-factor breakdown."
    )
    include_quality: bool = Field(
        True,
        description="If true and asset returns are available, include explained-vs-realized attribution quality checks.",
    )
    holdings: List[Holding]


class ScenarioRequest(BaseModel):
    as_of: Optional[date] = Field(
        None, description="As-of date. Defaults to latest date in model artifacts."
    )
    template: Optional[str] = Field(
        None,
        description=(
            "Optional predefined scenario template name "
            "(e.g. market_down_5, momentum_crash, liquidity_crunch, low_vol_unwind)."
        ),
    )
    factor_shocks: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "Optional factor shock overrides keyed by factor name, in return units (e.g., 0.01 = +1%). "
            "Can be used alone or merged on top of a template."
        ),
    )
    calibration_mode: str = Field(
        "none",
        description="Template calibration mode: none, sigma, or percentile.",
    )
    sigma_multiplier: float = Field(
        1.0,
        description="Used when calibration_mode=sigma. Shock = sign(template_shock) * sigma_multiplier * factor_std.",
    )
    percentile: float = Field(
        0.05,
        description=(
            "Used when calibration_mode=percentile. Negative template shocks map to this lower percentile; "
            "positive template shocks map to upper tail (1 - percentile)."
        ),
    )
    specific_shock: float = Field(
        0.0,
        description="Optional scalar shock applied to specific-risk proxy (0 by default).",
    )
    holdings: List[Holding]


class ExplainRequest(BaseModel):
    as_of: Optional[date] = Field(
        None, description="As-of date for snapshot sections. Defaults to latest model date."
    )
    start_date: Optional[date] = Field(
        None, description="Optional drift window start (inclusive)."
    )
    end_date: Optional[date] = Field(
        None, description="Optional drift window end (inclusive)."
    )
    top_n: int = Field(5, description="Top N factors used in views/risk/drift sections.")
    mode: str = Field(
        "auto",
        description="Explanation mode: auto (try llm then fallback), heuristic, or llm.",
    )
    llm_model: str = Field("gpt-4.1-mini", description="LLM model when mode=llm/auto.")
    holdings: List[Holding]


class ExposureTimeseriesRequest(BaseModel):
    start_date: Optional[date] = Field(
        None, description="Start date (inclusive). Defaults to earliest model date."
    )
    end_date: Optional[date] = Field(
        None, description="End date (inclusive). Defaults to latest model date."
    )
    holdings: List[Holding]


class PositionEventIn(BaseModel):
    event_id: Optional[str] = Field(
        None, description="Optional idempotency key. Auto-generated if omitted."
    )
    event_time: datetime = Field(..., description="Event timestamp in ISO-8601.")
    ticker: str = Field(..., description="US equity ticker.")
    event_type: str = Field(
        ...,
        description=(
            "One of: TRADE, MANUAL_ADJUSTMENT (or ADJUSTMENT), "
            "SPLIT, DIVIDEND (or CASH_DIVIDEND)."
        ),
    )
    quantity: float = Field(0.0, description="Quantity. TRADE expects positive quantity.")
    side: Optional[str] = Field(None, description="TRADE side: BUY or SELL.")
    price: Optional[float] = Field(None, description="Execution price (TRADE/optional ADJUSTMENT).")
    fees: float = Field(0.0, description="Execution fees.")
    split_ratio: Optional[float] = Field(None, description="Required for SPLIT events.")
    cash_amount_per_share: Optional[float] = Field(
        None, description="Required for CASH_DIVIDEND events."
    )
    source: Optional[str] = Field(None, description="Optional source/system label.")


class PositionEventsRequest(BaseModel):
    portfolio_id: str = Field(..., description="Portfolio id namespace for event stream.")
    events: List[PositionEventIn] = Field(..., description="One or more position events.")


class PositionSnapshotRequest(BaseModel):
    portfolio_id: str = Field(..., description="Portfolio id namespace for event stream.")
    as_of: Optional[datetime] = Field(
        None, description="Optional snapshot cutoff time. Defaults to now/all events."
    )
    include_closed: bool = Field(
        False, description="If true, include closed tickers with zero position."
    )


class RealtimeAnalyticsRequest(BaseModel):
    portfolio_id: str = Field(..., description="Portfolio id namespace for event stream.")
    as_of: Optional[date] = Field(
        None, description="Optional as-of date for positions/prices/model exposure lookup."
    )


class EodAnalyticsRequest(BaseModel):
    portfolio_id: str = Field(..., description="Portfolio id namespace for event stream.")
    as_of: Optional[date] = Field(None, description="Official close date.")
    strict_close: bool = Field(
        True, description="If true, require exact close date price for each ticker."
    )


class ReconcileCloseRequest(BaseModel):
    portfolio_id: str = Field(..., description="Portfolio id namespace for event stream.")
    as_of: Optional[date] = Field(None, description="Close date to reconcile.")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/health/mode")
def health_mode() -> Dict[str, object]:
    try:
        artifacts = load_latest_artifacts()
        return {
            "status": "ok",
            "as_of": artifacts.as_of.isoformat(),
            "factor_count": len(artifacts.factors),
            "exposure_rows": len(artifacts.exposures),
            "factor_return_days": len(artifacts.factor_returns),
            "specific_var_rows": len(artifacts.specific_var),
            "specific_returns_available": artifacts.specific_returns_available,
        }
    except FileNotFoundError:
        return {
            "status": "missing_artifacts",
            "message": (
                "Model artifacts not found. Run: "
                "python -m factor_exposure.scripts.build_model --universe data/universe.csv --asof YYYY-MM-DD"
            ),
        }


@app.get("/universe/tickers")
def universe_tickers() -> Dict[str, object]:
    artifacts = load_latest_artifacts()
    exposure_dates = sorted({d for d, _ in artifacts.exposures.keys()})
    if not exposure_dates:
        return {
            "as_of": artifacts.as_of.isoformat(),
            "effective_date": None,
            "count": 0,
            "tickers": [],
        }

    effective_date = max((d for d in exposure_dates if d <= artifacts.as_of), default=exposure_dates[-1])
    tickers = sorted({ticker for d, ticker in artifacts.exposures.keys() if d == effective_date})
    return {
        "as_of": artifacts.as_of.isoformat(),
        "effective_date": effective_date.isoformat(),
        "count": len(tickers),
        "tickers": tickers,
    }


@app.get("/portfolio/scenario/templates")
def scenario_templates() -> Dict[str, object]:
    try:
        templates = {
            name: {factor: float(shock) for factor, shock in shocks.items()}
            for name, shocks in list_scenario_templates().items()
        }
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load scenario templates: {e}") from e


@app.post("/portfolio/analytics")
def analytics(req: AnalyticsRequest) -> Dict[str, object]:
    if not req.holdings:
        raise HTTPException(status_code=400, detail="holdings must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        return portfolio_analytics(
            holdings=[(h.ticker.upper().strip(), float(h.weight)) for h in req.holdings],
            artifacts=artifacts,
            as_of=req.as_of,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/attribution")
def attribution(req: AttributionRequest) -> Dict[str, object]:
    if not req.holdings:
        raise HTTPException(status_code=400, detail="holdings must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        return portfolio_attribution(
            holdings=[(h.ticker.upper().strip(), float(h.weight)) for h in req.holdings],
            artifacts=artifacts,
            start_date=req.start_date,
            end_date=req.end_date,
            include_daily=req.include_daily,
            limit=req.limit,
            offset=req.offset,
            compact=req.compact,
            include_quality=req.include_quality,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/scenario")
def scenario(req: ScenarioRequest) -> Dict[str, object]:
    if not req.holdings:
        raise HTTPException(status_code=400, detail="holdings must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        shocks = resolve_factor_shocks(
            factors=artifacts.factors,
            template=req.template,
            factor_shocks=req.factor_shocks,
            factor_returns=artifacts.factor_returns,
            calibration_mode=req.calibration_mode,
            sigma_multiplier=req.sigma_multiplier,
            percentile=req.percentile,
        )
        out = portfolio_scenario(
            holdings=[(h.ticker.upper().strip(), float(h.weight)) for h in req.holdings],
            artifacts=artifacts,
            factor_shocks=shocks,
            as_of=req.as_of,
            specific_shock=req.specific_shock,
            template=req.template,
        )
        out["scenario"]["calibration"] = {
            "mode": req.calibration_mode,
            "sigma_multiplier": float(req.sigma_multiplier),
            "percentile": float(req.percentile),
        }
        return out
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/explain")
def explain(req: ExplainRequest) -> Dict[str, object]:
    if not req.holdings:
        raise HTTPException(status_code=400, detail="holdings must be non-empty")
    if req.top_n <= 0:
        raise HTTPException(status_code=400, detail="top_n must be > 0")

    artifacts = load_latest_artifacts()
    try:
        report = build_portfolio_report(
            holdings=[(h.ticker.upper().strip(), float(h.weight)) for h in req.holdings],
            artifacts=artifacts,
            as_of=req.as_of,
            start_date=req.start_date,
            end_date=req.end_date,
            top_n=req.top_n,
        )
        report_summary = {
            "as_of": report["as_of"],
            "views_expressed": report["views_expressed"],
            "top_risk_contributors": report["top_risk_contributors"],
            "drift_window": report["drift_window"],
            "drift_top_factors": report["drift_top_factors"],
        }
        explanation = explain_portfolio_report(
            report=report_summary,
            mode=req.mode,
            llm_model=req.llm_model,
        )
        return {
            "report": report_summary,
            "explanation": explanation,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/exposure-timeseries")
def exposure_timeseries(req: ExposureTimeseriesRequest) -> Dict[str, object]:
    if not req.holdings:
        raise HTTPException(status_code=400, detail="holdings must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        as_of = req.end_date or artifacts.as_of
        report = build_portfolio_report(
            holdings=[(h.ticker.upper().strip(), float(h.weight)) for h in req.holdings],
            artifacts=artifacts,
            as_of=as_of,
            start_date=req.start_date,
            end_date=req.end_date,
            top_n=5,
        )
        ts = report["exposure_timeseries"]
        rows = []
        for row in ts.iter_rows(named=True):
            row_out = dict(row)
            row_out["date"] = row["date"].isoformat()
            rows.append(row_out)
        return {
            "start_date": report["drift_window"]["start_date"],
            "end_date": report["drift_window"]["end_date"],
            "rows": rows,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/realtime/analytics")
def realtime_analytics(req: RealtimeAnalyticsRequest) -> Dict[str, object]:
    portfolio_id = req.portfolio_id.strip()
    if not portfolio_id:
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        return portfolio_realtime_analytics(
            portfolio_id=portfolio_id,
            artifacts=artifacts,
            as_of=req.as_of,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/eod/analytics")
def eod_analytics(req: EodAnalyticsRequest) -> Dict[str, object]:
    portfolio_id = req.portfolio_id.strip()
    if not portfolio_id:
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        return portfolio_eod_analytics(
            portfolio_id=portfolio_id,
            artifacts=artifacts,
            as_of=req.as_of,
            strict_close=req.strict_close,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/portfolio/reconcile/close")
def reconcile_close(req: ReconcileCloseRequest) -> Dict[str, object]:
    portfolio_id = req.portfolio_id.strip()
    if not portfolio_id:
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")

    artifacts = load_latest_artifacts()
    try:
        return reconcile_close_analytics(
            portfolio_id=portfolio_id,
            artifacts=artifacts,
            as_of=req.as_of,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/positions/events")
def post_position_events(req: PositionEventsRequest) -> Dict[str, object]:
    portfolio_id = req.portfolio_id.strip()
    if not portfolio_id:
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")
    if not req.events:
        raise HTTPException(status_code=400, detail="events must be non-empty")

    events = [
        PositionEvent(
            event_id=e.event_id or "",
            portfolio_id=portfolio_id,
            event_time=e.event_time,
            ticker=e.ticker.upper().strip(),
            event_type=canonical_event_type(e.event_type),
            quantity=float(e.quantity),
            side=e.side.upper().strip() if e.side else None,
            price=None if e.price is None else float(e.price),
            fees=float(e.fees),
            split_ratio=None if e.split_ratio is None else float(e.split_ratio),
            cash_amount_per_share=(
                None if e.cash_amount_per_share is None else float(e.cash_amount_per_share)
            ),
            source=e.source,
        )
        for e in req.events
    ]
    try:
        appended = append_events(events)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"portfolio_id": portfolio_id, "appended": appended}


@app.get("/positions/events")
def get_position_events(
    portfolio_id: str = Query(..., description="Portfolio id."),
    ticker: Optional[str] = Query(None, description="Optional ticker filter."),
    as_of: Optional[datetime] = Query(None, description="Optional end timestamp filter."),
    limit: Optional[int] = Query(200, description="Optional limit (tail after sorting)."),
) -> Dict[str, object]:
    if not portfolio_id.strip():
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")
    try:
        events = load_events(
            portfolio_id=portfolio_id,
            ticker=ticker,
            as_of=as_of,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "portfolio_id": portfolio_id.strip(),
        "count": len(events),
        "events": [
            {
                "event_id": e.event_id,
                "portfolio_id": e.portfolio_id,
                "event_time": e.event_time.isoformat(),
                "ticker": e.ticker,
                "event_type": e.event_type,
                "quantity": e.quantity,
                "side": e.side,
                "price": e.price,
                "fees": e.fees,
                "split_ratio": e.split_ratio,
                "cash_amount_per_share": e.cash_amount_per_share,
                "source": e.source,
            }
            for e in events
        ],
    }


@app.post("/positions/snapshot")
def position_snapshot(req: PositionSnapshotRequest) -> Dict[str, object]:
    portfolio_id = req.portfolio_id.strip()
    if not portfolio_id:
        raise HTTPException(status_code=400, detail="portfolio_id must be non-empty")

    events = load_events(portfolio_id=portfolio_id, as_of=req.as_of)
    snapshot = build_snapshot(events=events, as_of=req.as_of, include_closed=req.include_closed)
    rows = sorted(snapshot.values(), key=lambda r: r.ticker)
    latest_prices = load_latest_cached_prices(
        tickers=[r.ticker for r in rows],
        as_of=req.as_of,
    )

    response_rows = []
    unpriced_tickers: List[str] = []
    for r in rows:
        px = latest_prices.get(r.ticker)
        market_price = float(px["price"]) if px is not None else None
        price_as_of = px["date"].isoformat() if px is not None else None
        market_value = float(r.quantity * market_price) if market_price is not None else None
        unrealized = (
            unrealized_pnl(quantity=r.quantity, avg_cost=r.avg_cost, market_price=market_price)
            if market_price is not None
            else None
        )
        economic_total = float(r.total_pnl + unrealized) if unrealized is not None else None
        if market_price is None:
            unpriced_tickers.append(r.ticker)

        response_rows.append(
            {
                "ticker": r.ticker,
                "quantity": r.quantity,
                "avg_cost": r.avg_cost,
                "market_price": market_price,
                "price_as_of": price_as_of,
                "market_value": market_value,
                "realized_pnl": r.realized_pnl,
                "dividends_pnl": r.dividends_pnl,
                "total_pnl": r.total_pnl,
                "unrealized_pnl": unrealized,
                "economic_total_pnl": economic_total,
                "last_event_time": r.last_event_time.isoformat(),
                "change_reasons": r.change_reasons,
            }
        )

    priced_rows = [row for row in response_rows if row["market_price"] is not None]
    total_market_value = float(sum(float(row["market_value"]) for row in priced_rows))
    total_unrealized = float(sum(float(row["unrealized_pnl"]) for row in priced_rows))
    total_realized_and_div = float(sum(r.total_pnl for r in rows))
    total_economic = float(total_realized_and_div + total_unrealized)

    return {
        "portfolio_id": portfolio_id,
        "as_of": req.as_of.isoformat() if req.as_of else None,
        "event_count": len(events),
        "totals": {
            "tickers": len(rows),
            "open_positions": sum(1 for r in rows if abs(r.quantity) > 1e-12),
            "long_positions": sum(1 for r in rows if r.quantity > 0),
            "short_positions": sum(1 for r in rows if r.quantity < 0),
            "priced_rows": len(priced_rows),
            "unpriced_tickers": unpriced_tickers,
            "market_value": total_market_value,
            "realized_pnl": float(sum(r.realized_pnl for r in rows)),
            "dividends_pnl": float(sum(r.dividends_pnl for r in rows)),
            "total_pnl": total_realized_and_div,
            "unrealized_pnl": total_unrealized,
            "economic_total_pnl": total_economic,
        },
        "rows": response_rows,
    }
