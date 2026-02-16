from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from factor_exposure.explain.explainer import explain_portfolio_report
from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.portfolio.analytics import (
    portfolio_analytics,
    portfolio_attribution,
    portfolio_scenario,
)
from factor_exposure.portfolio.scenarios import list_scenario_templates, resolve_factor_shocks
from factor_exposure.reporting.report import build_portfolio_report


app = FastAPI(title="factor_exposure", version="0.1.0")


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
