# API

Factor definitions and sign conventions:
- `docs/factors.md`

## `POST /portfolio/analytics`

Computes factor exposures and predicted risk decomposition for a portfolio using the latest fitted
model artifacts in `data/model/latest/`.

To run the API without installing the package:
```bash
uvicorn --app-dir src factor_exposure.api.main:app --reload
```

### Request schema
```json
{
  "as_of": "YYYY-MM-DD (optional)",
  "holdings": [
    {"ticker": "AAPL", "weight": 0.10},
    {"ticker": "MSFT", "weight": 0.90}
  ]
}
```

## `POST /portfolio/attribution`

Computes model-implied daily and total return attribution over a date range:
- Factor return contribution by factor
- Specific (residual) return contribution

### Request schema
```json
{
  "start_date": "YYYY-MM-DD (optional)",
  "end_date": "YYYY-MM-DD (optional)",
  "include_daily": true,
  "limit": 50,
  "offset": 0,
  "compact": false,
  "include_quality": true,
  "holdings": [
    {"ticker": "AAPL", "weight": 0.50},
    {"ticker": "MSFT", "weight": 0.50}
  ]
}
```

## `POST /portfolio/scenario`

Computes shocked portfolio PnL using current factor exposures and user-provided factor shocks.

### Request schema
```json
{
  "as_of": "YYYY-MM-DD (optional)",
  "template": "market_down_5",
  "calibration_mode": "none",
  "sigma_multiplier": 1.0,
  "percentile": 0.05,
  "factor_shocks": {
    "beta_spy_252": -0.03
  },
  "specific_shock": 0.0,
  "holdings": [
    {"ticker": "AAPL", "weight": 0.50},
    {"ticker": "MSFT", "weight": 0.50}
  ]
}
```

### Percentile calibration example
```bash
curl -X POST http://127.0.0.1:8000/portfolio/scenario \
  -H "Content-Type: application/json" \
  -d '{"as_of":"2025-12-31","template":"momentum_crash","calibration_mode":"percentile","percentile":0.1,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

## `POST /portfolio/explain`

Builds a compact portfolio report and returns plain-English interpretation.

### Request schema
```json
{
  "as_of": "YYYY-MM-DD (optional)",
  "start_date": "YYYY-MM-DD (optional)",
  "end_date": "YYYY-MM-DD (optional)",
  "top_n": 5,
  "mode": "auto",
  "llm_model": "gpt-4.1-mini",
  "holdings": [
    {"ticker": "AAPL", "weight": 0.50},
    {"ticker": "MSFT", "weight": 0.50}
  ]
}
```

Rules:
- `mode` can be `auto`, `heuristic`, or `llm`.
- `auto` tries LLM and falls back to heuristic if unavailable.
- `llm` requires `OPENAI_API_KEY` and the `openai` package.

### Response shape
```json
{
  "report": {
    "as_of": "YYYY-MM-DD",
    "views_expressed": [{"factor": "vol_63", "exposure": -0.49}],
    "top_risk_contributors": [{"factor": "vol_63", "variance_contrib": 0.00005}],
    "drift_window": {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "rows": 250},
    "drift_top_factors": [{"factor": "rev_1m", "delta": 0.44}]
  },
  "explanation": {
    "mode": "heuristic",
    "overview": "...",
    "key_views": ["..."],
    "key_risks": ["..."],
    "drift_summary": ["..."],
    "watchouts": ["..."]
  }
}
```

Rules:
- Provide `template`, `factor_shocks`, or both.
- If both are provided, `factor_shocks` overrides template values.
- `factor_shocks` keys must match model factor names.
- Shock units are return units (`0.01` = `+1%`).
- `specific_shock` is optional and defaults to `0.0`.
- `calibration_mode` can be `none`, `sigma`, or `percentile`.
- `sigma` mode maps each template shock to `sign(template_shock) * sigma_multiplier * std(factor_return)`.
- `percentile` mode maps negative template shocks to lower-tail `percentile`, positive shocks to upper-tail `1 - percentile`.
- Calibration applies only to template shocks; explicit `factor_shocks` still override those values.

### `GET /portfolio/scenario/templates`

Lists predefined template shocks:
- `market_down_5`
- `momentum_crash`
- `liquidity_crunch`
- `low_vol_unwind`

### Response schema
```json
{
  "as_of": "YYYY-MM-DD",
  "coverage": {
    "requested": 2,
    "covered": 2,
    "missing": []
  },
  "scenario": {
    "factor_shocks": {
      "mom_12_1": -0.01
    },
    "specific_shock": 0.0,
    "calibration": {
      "mode": "none",
      "sigma_multiplier": 1.0,
      "percentile": 0.05
    }
  },
  "exposures": {
    "mom_12_1": 0.12
  },
  "pnl": {
    "factor": -0.0012,
    "specific": 0.0,
    "total": -0.0012,
    "factor_contrib": {
      "mom_12_1": -0.0012
    }
  }
}
```

Rules:
- `start_date` defaults to earliest factor-return date in artifacts.
- `end_date` defaults to latest factor-return date in artifacts.
- Weights are normalized by sum of absolute weights.
- `include_daily=false` returns summary totals only (no `daily` payload).
- `limit`/`offset` paginate daily rows when `include_daily=true`.
- `compact=true` removes per-day `factor_contrib` to reduce response size.
- `include_quality=true` adds explained-vs-realized checks when `asset_returns.parquet` is available.

### Response schema
```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "coverage": {
    "requested_holdings": 2,
    "holdings_with_any_data": 2,
    "missing": [],
    "days_requested": 252,
    "days_with_data": 250
  },
  "totals": {
    "factor_return": 0.11,
    "specific_return": 0.02,
    "total_return": 0.13,
    "factor_contrib": {
      "mom_12_1": 0.03
    }
  },
  "quality": {
    "available": true,
    "days_compared": 250,
    "mean_residual": 0.00001,
    "mae_residual": 0.00120,
    "rmse_residual": 0.00160,
    "corr_explained_vs_realized": 0.93,
    "r2_explained_vs_realized": 0.85
  },
  "daily": [
    {
      "date": "YYYY-MM-DD",
      "factor_return": 0.001,
      "specific_return": -0.0003,
      "total_return": 0.0007,
      "factor_contrib": {
        "mom_12_1": 0.0002
      },
      "coverage": {
        "active_holdings": 2,
        "requested_holdings": 2
      },
      "quality": {
        "explained_return": 0.0007,
        "realized_return": 0.0008,
        "residual_return": 0.0001,
        "comparable_holdings": 2
      }
    }
  ],
  "daily_page": {
    "offset": 0,
    "limit": 50,
    "returned": 50,
    "total_available": 250
  }
}
```

### Small response example (summary only)
```json
{
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "include_daily": false,
  "holdings": [
    {"ticker": "AAPL", "weight": 0.50},
    {"ticker": "MSFT", "weight": 0.50}
  ]
}
```

Rules:
- `weight` is a portfolio weight (can be negative).
- If weights do not sum to 1, the API normalizes by the sum of absolute weights.
- `as_of` defaults to the latest date available in model artifacts.

### Response schema
```json
{
  "as_of": "YYYY-MM-DD",
  "coverage": {
    "requested": 2,
    "covered": 2,
    "missing": []
  },
  "factor_exposures": {
    "mom_12_1": 0.15,
    "mom_6_1": 0.08,
    "rev_1m": -0.02,
    "beta_spy_252": 1.01,
    "vol_63": -0.11,
    "liq_dollarvol_21": 0.25
  },
  "risk": {
    "annualized_vol": 0.18,
    "daily_vol": 0.011,
    "variance": {
      "total": 0.00012,
      "factor": 0.00009,
      "specific": 0.00003
    },
    "factor_variance_contrib": {
      "mom_12_1": 0.00001
    }
  }
}
```
