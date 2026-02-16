from __future__ import annotations

import json
import os
from typing import Dict, List, Optional


FACTOR_INTERPRETATION = {
    "liq_dollarvol_21": {
        "positive": "tilt toward higher-liquidity names",
        "negative": "tilt toward less-liquid names",
    },
    "vol_63": {
        "positive": "tilt toward higher-volatility names",
        "negative": "tilt toward lower-volatility names",
    },
    "rev_1m": {
        "positive": "short-term reversal tilt (buy recent laggards / fade recent winners)",
        "negative": "short-term momentum continuation tilt",
    },
    "beta_spy_252": {
        "positive": "pro-cyclical beta tilt (more market-sensitive)",
        "negative": "defensive beta tilt (less market-sensitive)",
    },
    "mom_12_1": {
        "positive": "medium-term momentum tilt",
        "negative": "contrarian tilt versus medium-term momentum",
    },
    "mom_6_1": {
        "positive": "intermediate momentum tilt",
        "negative": "contrarian tilt versus intermediate momentum",
    },
}


def _factor_definition_map() -> Dict[str, Dict[str, str]]:
    return {
        "liq_dollarvol_21": {
            "description": "21-day average log dollar-volume liquidity factor.",
            "positive_exposure_means": "tilt toward higher-liquidity names",
            "negative_exposure_means": "tilt toward less-liquid names",
        },
        "vol_63": {
            "description": "63-day realized volatility factor.",
            "positive_exposure_means": "tilt toward higher-volatility names",
            "negative_exposure_means": "tilt toward lower-volatility names",
        },
        "rev_1m": {
            "description": "1-month short-term reversal factor (NOT revenue revision).",
            "positive_exposure_means": "reversal tilt (buy recent laggards / fade recent winners)",
            "negative_exposure_means": "short-term continuation tilt",
        },
        "beta_spy_252": {
            "description": "252-day beta vs SPY factor.",
            "positive_exposure_means": "more market-sensitive / pro-cyclical tilt",
            "negative_exposure_means": "less market-sensitive / defensive tilt",
        },
        "mom_12_1": {
            "description": "12-1 month momentum factor.",
            "positive_exposure_means": "medium-term momentum tilt",
            "negative_exposure_means": "contrarian tilt versus medium-term momentum",
        },
        "mom_6_1": {
            "description": "6-1 month momentum factor.",
            "positive_exposure_means": "intermediate momentum tilt",
            "negative_exposure_means": "contrarian tilt versus intermediate momentum",
        },
    }


def _validate_explanation_contract(payload: Dict[str, object]) -> Dict[str, object]:
    required_non_empty_list = [
        "key_views",
        "risk_watchouts",
        "drift_story",
        "scenario_implications",
        "limitations",
    ]
    if not isinstance(payload.get("overview"), str) or not payload["overview"].strip():
        raise ValueError("Invalid explanation: overview must be a non-empty string")
    for key in required_non_empty_list:
        value = payload.get(key)
        if not isinstance(value, list) or len(value) == 0:
            raise ValueError(f"Invalid explanation: {key} must be a non-empty list")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"Invalid explanation: {key} entries must be non-empty strings")
    return payload


def _extract_json_object(text: str) -> Dict[str, object]:
    raw = text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM response did not contain valid JSON")
        return json.loads(raw[start : end + 1])


def _heuristic_explain(report: Dict[str, object]) -> Dict[str, object]:
    views = report.get("views_expressed", [])
    risks = report.get("top_risk_contributors", [])
    drift = report.get("drift_top_factors", [])
    as_of = report.get("as_of")

    key_views: List[str] = []
    for row in views:
        factor = str(row["factor"])
        val = float(row["exposure"])
        direction = "positive" if val >= 0 else "negative"
        meaning = FACTOR_INTERPRETATION.get(factor, {}).get(direction, f"{direction} exposure to {factor}")
        key_views.append(f"{factor} ({val:+.4f}): {meaning}")

    risk_watchouts: List[str] = []
    for row in risks:
        factor = str(row["factor"])
        val = float(row["variance_contrib"])
        risk_watchouts.append(f"{factor} is a top variance contributor ({val:+.8f})")

    drift_story: List[str] = []
    for row in drift:
        factor = str(row["factor"])
        delta = float(row["delta"])
        drift_story.append(f"{factor} drifted by {delta:+.4f} over the selected window")

    overview = (
        f"As of {as_of}, the book is primarily expressing "
        + (", ".join([v.split(":")[0] for v in key_views[:3]]) if key_views else "no strong factor tilts")
        + "."
    )

    payload = {
        "mode": "heuristic",
        "overview": overview,
        "key_views": key_views,
        "risk_watchouts": risk_watchouts or ["Top risk contributors are concentrated in a few factors."],
        "drift_story": drift_story or ["Exposure drift was limited in the selected window."],
        "scenario_implications": [
            "A negative shock to top positive exposures is likely to hurt near-term returns.",
            "A vol shock has elevated impact when volatility-related risk contributions are high.",
            "Liquidity shocks can be amplified when liquidity exposure and risk contribution are both large.",
        ],
        "limitations": [
            "Recent drift may indicate implicit strategy change even if holdings changed modestly.",
            "Interpretation depends on factor definitions and cross-sectional z-scoring choices.",
            "This summary is model-implied and does not include transaction costs or execution effects.",
        ],
    }
    return _validate_explanation_contract(payload)


def _llm_explain_openai(
    report: Dict[str, object],
    model: str = "gpt-4.1-mini",
    api_key_env: str = "OPENAI_API_KEY",
) -> Dict[str, object]:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ValueError(f"{api_key_env} is not set")

    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise ValueError("openai package is not installed. Install with: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    factor_definitions = _factor_definition_map()
    output_contract = {
        "overview": "string, non-empty",
        "key_views": ["3-5 non-empty strings, <=25 words each, 1 sentence each"],
        "risk_watchouts": ["3-5 non-empty strings, <=25 words each, 1 sentence each"],
        "drift_story": ["3-5 non-empty strings, <=25 words each, 1 sentence each"],
        "scenario_implications": ["3-5 non-empty strings, <=25 words each, 1 sentence each"],
        "limitations": ["2-3 non-empty strings, <=25 words each, 1 sentence each"],
    }
    prompt = (
        "You are a portfolio risk interpreter. Use ONLY provided JSON and factor definitions.\n"
        "Critical rule: rev_1m is a short-term reversal factor, not revenue revision.\n"
        "Use cautious language (e.g., may/could), not deterministic forecasts.\n"
        "Do not infer sector, market-cap, country, or security concentration unless explicitly provided.\n"
        "If a factor variance contribution is negative, describe it as an offset/hedge-like contribution.\n"
        "Do not invent numbers or factor meanings.\n"
        "Return STRICT JSON ONLY. No markdown, no prose outside JSON.\n"
        "Every required section must be non-empty.\n\n"
        f"FACTOR_DEFINITIONS:\n{json.dumps(factor_definitions, indent=2)}\n\n"
        f"OUTPUT_CONTRACT:\n{json.dumps(output_contract, indent=2)}\n\n"
        f"INPUT_REPORT:\n{json.dumps(report, default=str, indent=2)}"
    )
    response = client.responses.create(model=model, input=prompt)
    parsed = _extract_json_object(response.output_text)
    checked = _validate_explanation_contract(parsed)
    return {
        "mode": "llm",
        "model": model,
        **checked,
    }


def explain_portfolio_report(
    report: Dict[str, object],
    mode: str = "auto",
    llm_model: str = "gpt-4.1-mini",
) -> Dict[str, object]:
    normalized_mode = mode.lower().strip()
    if normalized_mode not in {"auto", "heuristic", "llm"}:
        raise ValueError("mode must be one of: auto, heuristic, llm")

    if normalized_mode == "heuristic":
        return _heuristic_explain(report)

    if normalized_mode == "llm":
        return _llm_explain_openai(report=report, model=llm_model)

    try:
        return _llm_explain_openai(report=report, model=llm_model)
    except Exception:
        return _heuristic_explain(report)
