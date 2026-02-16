from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import numpy as np


SCENARIO_TEMPLATES: Dict[str, Dict[str, float]] = {
    "market_down_5": {
        "beta_spy_252": -0.05,
    },
    "momentum_crash": {
        "mom_12_1": -0.03,
        "mom_6_1": -0.02,
        "rev_1m": 0.01,
    },
    "liquidity_crunch": {
        "liq_dollarvol_21": -0.03,
        "vol_63": 0.02,
        "beta_spy_252": -0.02,
    },
    "low_vol_unwind": {
        "vol_63": 0.03,
        "beta_spy_252": -0.01,
    },
}


def list_scenario_templates() -> Dict[str, Dict[str, float]]:
    return {k: dict(v) for k, v in SCENARIO_TEMPLATES.items()}


def resolve_factor_shocks(
    factors: List[str],
    template: Optional[str],
    factor_shocks: Optional[Dict[str, float]],
    factor_returns: Optional[Dict[date, np.ndarray]] = None,
    calibration_mode: str = "none",
    sigma_multiplier: float = 1.0,
    percentile: float = 0.05,
) -> Dict[str, float]:
    if template is None and factor_shocks is None:
        raise ValueError("Provide either template or factor_shocks")

    if template is not None and template not in SCENARIO_TEMPLATES:
        valid = ", ".join(sorted(SCENARIO_TEMPLATES.keys()))
        raise ValueError(f"Unknown scenario template '{template}'. Available: {valid}")

    shocks: Dict[str, float] = {}
    if template is not None:
        shocks.update(SCENARIO_TEMPLATES[template])

    mode = calibration_mode.lower().strip()
    if mode not in {"none", "sigma", "percentile"}:
        raise ValueError("calibration_mode must be one of: none, sigma, percentile")
    if mode == "sigma" and sigma_multiplier <= 0:
        raise ValueError("sigma_multiplier must be > 0")
    if mode == "percentile" and not (0.0 < percentile <= 0.5):
        raise ValueError("percentile must be in (0, 0.5]")

    if shocks and mode != "none":
        if not factor_returns:
            raise ValueError("factor_returns history is required for calibrated templates")
        if len(factor_returns) < 20:
            raise ValueError("at least 20 factor-return observations are required for calibration")

        by_factor = {}
        ordered = sorted(factor_returns.items(), key=lambda kv: kv[0])
        for idx, f in enumerate(factors):
            by_factor[f] = np.array([float(row[idx]) for _, row in ordered], dtype=float)

        calibrated: Dict[str, float] = {}
        for f, base_shock in shocks.items():
            sign = 1.0 if float(base_shock) >= 0 else -1.0
            series = by_factor[f]
            if mode == "sigma":
                shock = sign * sigma_multiplier * float(np.std(series, ddof=1))
            else:
                q = (1.0 - percentile) if sign >= 0 else percentile
                shock = float(np.quantile(series, q))
            calibrated[f] = shock
        shocks = calibrated

    if factor_shocks:
        shocks.update({k: float(v) for k, v in factor_shocks.items()})

    unknown = sorted(set(shocks.keys()) - set(factors))
    if unknown:
        raise ValueError(f"Unknown factors in shocks: {', '.join(unknown)}")

    return shocks
