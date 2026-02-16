# factor_exposure

Daily US equities factor exposure + risk decomposition (equities-only MVP).

Given a portfolio of holdings, this project returns:
- Factor exposures ("views")
- Predicted risk decomposition (factor vs specific)

This repo is intentionally scaffolded for extension (industries, fundamentals, options later).

## Quickstart

### 1) Set up env
Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

If you already had the env before this migration, rerun:
```bash
pip install -e ".[dev]"
```

### 2) Create a universe
Put tickers (one per line) at:
- `data/universe.csv`

You can start from the sample:
```bash
cp data/universe.sample.csv data/universe.csv
```

### 3) Build model artifacts (cached locally)
```bash
python -m factor_exposure.scripts.build_model --universe data/universe.csv --asof 2026-02-14
```

Optional preflight validation:
```bash
python -m factor_exposure.scripts.validate_universe --universe data/universe.csv --asof 2026-02-14 --out data/model/universe_validation.csv
```
With summary JSON + stricter coverage:
```bash
python -m factor_exposure.scripts.validate_universe --universe data/universe.csv --asof 2026-02-14 --min_history_days 756 --min_coverage_ratio 0.9 --out data/model/universe_validation.csv --summary_out data/model/universe_validation_summary.json
```

Artifacts are written under:
- `data/model/latest/`
- Includes diagnostics files:
  - `data/model/latest/data_quality.json`
  - `data/model/latest/model_diagnostics.json`
  - `data/model/latest/ticker_quality.parquet`

Note:
- If you built artifacts before the attribution endpoint existed, rerun `build_model` once to generate `specific_returns.parquet`.

### 4) Run the API
If you installed the package (`pip install -e ".[dev]"`), you can run:
```bash
uvicorn factor_exposure.api.main:app --reload
```

If you did *not* install the package, run with `--app-dir src`:
```bash
uvicorn --app-dir src factor_exposure.api.main:app --reload
```

Troubleshooting:
- If `pip install -e ".[dev]"` fails (for example due to restricted network/build dependencies),
  this repo includes a local import shim, so running from repo root with:
  `uvicorn factor_exposure.api.main:app --reload`
  should still work.
- If you see `ModuleNotFoundError: No module named 'polars'`, activate your project venv and rerun
  `pip install -e ".[dev]"`.

Then POST:
- `http://127.0.0.1:8000/portfolio/analytics`
- `http://127.0.0.1:8000/portfolio/attribution`
- `http://127.0.0.1:8000/portfolio/scenario`
- `http://127.0.0.1:8000/portfolio/scenario/templates`
- `http://127.0.0.1:8000/portfolio/explain`

Example request body:
```json
{
  "as_of": "2026-02-14",
  "holdings": [
    {"ticker": "AAPL", "weight": 0.25},
    {"ticker": "MSFT", "weight": 0.25},
    {"ticker": "SPY", "weight": 0.50}
  ]
}
```

Attribution summary-only example (smaller payload):
```bash
curl -X POST http://127.0.0.1:8000/portfolio/attribution \
  -H "Content-Type: application/json" \
  -d '{"start_date":"2025-01-01","end_date":"2025-12-31","include_daily":false,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

Attribution paged daily example:
```bash
curl -X POST http://127.0.0.1:8000/portfolio/attribution \
  -H "Content-Type: application/json" \
  -d '{"start_date":"2025-01-01","end_date":"2025-12-31","include_daily":true,"limit":20,"offset":0,"compact":true,"include_quality":true,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

Scenario example:
```bash
curl -X POST http://127.0.0.1:8000/portfolio/scenario \
  -H "Content-Type: application/json" \
  -d '{"as_of":"2025-12-31","factor_shocks":{"mom_12_1":-0.01,"beta_spy_252":-0.02},"specific_shock":0.0,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

Scenario template example:
```bash
curl -X POST http://127.0.0.1:8000/portfolio/scenario \
  -H "Content-Type: application/json" \
  -d '{"as_of":"2025-12-31","template":"market_down_5","factor_shocks":{"beta_spy_252":-0.03},"specific_shock":0.0,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

Scenario template with sigma calibration example:
```bash
curl -X POST http://127.0.0.1:8000/portfolio/scenario \
  -H "Content-Type: application/json" \
  -d '{"as_of":"2025-12-31","template":"momentum_crash","calibration_mode":"sigma","sigma_multiplier":1.5,"specific_shock":0.0,"holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

Explain example:
```bash
curl -X POST http://127.0.0.1:8000/portfolio/explain \
  -H "Content-Type: application/json" \
  -d '{"as_of":"2025-12-31","start_date":"2025-01-01","end_date":"2025-12-31","top_n":5,"mode":"auto","holdings":[{"ticker":"AAPL","weight":0.5},{"ticker":"MSFT","weight":0.5}]}'
```

## Schemas
- Data + artifact schemas: `docs/schemas.md`
- API request/response: `docs/api.md`
- Factor formulas, signs, intuition: `docs/factors.md`

## Lightweight Report

Generate a markdown report with:
- views expressed
- top risk contributors
- factor exposure drift over time

Example holdings file:
```json
[
  {"ticker": "AAPL", "weight": 0.5},
  {"ticker": "MSFT", "weight": 0.5}
]
```

Run:
```bash
python -m factor_exposure.scripts.portfolio_report --holdings holdings.json --asof 2025-12-31 --start_date 2025-01-01 --end_date 2025-12-31 --out reports/portfolio_report.md --timeseries_out reports/exposure_timeseries.csv
```

Notebook:
- Open `notebooks/portfolio_report.ipynb` for interactive tables.

## Factor Sanity Check

Print raw factor values (pre-zscore) and stored z-score exposures for a ticker/date:

```bash
python -m factor_exposure.scripts.factor_sanity --ticker AAPL --asof 2025-12-31
```

Compare multiple tickers side-by-side:

```bash
python -m factor_exposure.scripts.factor_sanity --compare AAPL,MSFT,NVDA,SPY --asof 2025-12-31
```

## Attribution Quality Report

Generate explained-vs-realized attribution diagnostics and optional per-day residual CSV:

```bash
python -m factor_exposure.scripts.attribution_quality_report --holdings holdings.json --start_date 2025-01-01 --end_date 2025-12-31 --out reports/attribution_quality_report.md --daily_csv_out reports/attribution_quality_daily.csv
```
