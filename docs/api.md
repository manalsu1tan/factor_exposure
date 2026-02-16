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

## `POST /portfolio/exposure-timeseries`

Returns portfolio factor exposure time series for the provided holdings/date window.

### Request schema
```json
{
  "start_date": "YYYY-MM-DD (optional)",
  "end_date": "YYYY-MM-DD (optional)",
  "holdings": [
    {"ticker": "AAPL", "weight": 0.50},
    {"ticker": "MSFT", "weight": 0.50}
  ]
}
```

## `GET /universe/tickers`

Returns ticker symbols in the model universe for current artifact `as_of`.

### Response schema
```json
{
  "as_of": "YYYY-MM-DD",
  "count": 500,
  "tickers": ["AAPL", "MSFT", "NVDA"]
}
```

### Response schema
```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "rows": [
    {
      "date": "YYYY-MM-DD",
      "covered_holdings": 2,
      "requested_holdings": 2,
      "mom_12_1": 0.11,
      "mom_6_1": -0.03
    }
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

## `POST /positions/events`

Appends position lifecycle events to the parquet-backed event log.

### Request schema
```json
{
  "portfolio_id": "demo_book",
  "events": [
    {
      "event_id": "optional-idempotency-key",
      "event_time": "2025-01-02T14:30:00Z",
      "ticker": "AAPL",
      "event_type": "TRADE",
      "quantity": 100.0,
      "side": "BUY",
      "price": 180.5,
      "fees": 1.0,
      "split_ratio": null,
      "cash_amount_per_share": null,
      "source": "manual"
    }
  ]
}
```

Rules:
- `event_type` supports `TRADE`, `MANUAL_ADJUSTMENT` (`ADJUSTMENT` alias), `SPLIT`, `DIVIDEND` (`CASH_DIVIDEND` alias).

## `GET /positions/events`

Reads stored events for a portfolio.

Query params:
- `portfolio_id` (required)
- `ticker` (optional)
- `as_of` (optional ISO datetime filter)
- `limit` (optional; default `200`)

## `POST /positions/snapshot`

Builds a point-in-time snapshot by folding events in time order.

### Request schema
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31T21:00:00Z",
  "include_closed": false
}
```

### Response schema
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31T21:00:00+00:00",
  "event_count": 42,
  "totals": {
    "tickers": 3,
    "open_positions": 2,
    "long_positions": 1,
    "short_positions": 1,
    "realized_pnl": 2500.0,
    "dividends_pnl": 120.0,
    "total_pnl": 2620.0
  },
  "rows": [
    {
      "ticker": "AAPL",
      "quantity": 80.0,
      "avg_cost": 182.1,
      "market_price": 195.0,
      "price_as_of": "2025-12-30",
      "market_value": 15600.0,
      "realized_pnl": 350.0,
      "dividends_pnl": 40.0,
      "total_pnl": 390.0,
      "unrealized_pnl": 1032.0,
      "economic_total_pnl": 1422.0,
      "last_event_time": "2025-12-18T14:35:00+00:00"
    }
  ]
}
```

Notes:
- `market_price` comes from cached `data/cache/yfinance/prices/{TICKER}.parquet`.
- `price_as_of` is the latest cached date used (<= requested `as_of` date).
- `total_pnl` remains realized + dividends only.
- `economic_total_pnl` = realized + dividends + unrealized.
- `change_reasons` lists drivers seen for each ticker (`trade`, `manual_adjustment`, `split`, `dividend`).

## `POST /portfolio/realtime/analytics`

Builds analytics from latest event-sourced positions + latest cached prices, then feeds holdings into the existing factor risk engine.

### Request schema
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31"
}
```

## `POST /portfolio/eod/analytics`

Builds analytics from event-sourced positions using official close prices for `as_of`.

### Request schema
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31",
  "strict_close": true
}
```

Notes:
- `strict_close=true` requires exact `as_of` close in cached prices.
- If `strict_close=false`, the latest cached price on/before `as_of` is used.

## `POST /portfolio/reconcile/close`

Returns realtime-close vs eod-close deltas for PnL, exposures, and risk.

### Request schema
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31"
}
```

### Response schema (shape)
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31",
  "realtime": {"positions": {}, "analytics": {}},
  "eod": {"positions": {}, "analytics": {}},
  "deltas": {
    "market_value": 12.3,
    "unrealized_pnl": 12.3,
    "economic_total_pnl": 12.3,
    "annualized_vol": 0.001,
    "exposure_delta": {"mom_12_1": 0.02},
    "unpriced_tickers": {"realtime": [], "eod": []}
  }
}
```

### Response schema (shape)
```json
{
  "portfolio_id": "demo_book",
  "requested_as_of": "2025-12-31",
  "resolved_as_of": "2025-12-31",
  "positions": {
    "event_count": 42,
    "open_tickers": 5,
    "priced_tickers": 5,
    "unpriced_tickers": [],
    "market_value": 100000.0,
    "gross_market_value": 100000.0,
    "rows": [
      {"ticker": "AAPL", "quantity": 100, "avg_cost": 180.5, "change_reasons": ["trade"]}
    ]
  },
  "analytics": {
    "as_of": "2025-12-31",
    "factor_exposures": {"mom_12_1": 0.1},
    "risk": {"annualized_vol": 0.2}
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
