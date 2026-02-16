# API

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
