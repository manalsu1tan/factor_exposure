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

Artifacts are written under:
- `data/model/latest/`

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

## Schemas
- Data + artifact schemas: `docs/schemas.md`
- API request/response: `docs/api.md`
z
