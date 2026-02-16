from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.portfolio.analytics import portfolio_analytics


app = FastAPI(title="factor_exposure", version="0.1.0")


class Holding(BaseModel):
    ticker: str = Field(..., description="US equity ticker, e.g. AAPL")
    weight: float = Field(..., description="Portfolio weight (can be negative).")


class AnalyticsRequest(BaseModel):
    as_of: Optional[date] = Field(
        None, description="As-of date. Defaults to latest date in model artifacts."
    )
    holdings: List[Holding]


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


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
