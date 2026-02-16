# Web Frontend (Minimal)

This is a minimal React + Vite dashboard for the factor exposure API.

## Prereqs

- Node 18+
- API running locally (default: `http://127.0.0.1:8000`)

## Run

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Current panels

- Holdings editor (weight mode or shares×price mode)
- CSV import for holdings (`ticker,weight,shares,price`)
- Ticker autocomplete + symbol validation (`/universe/tickers`)
- Add/remove rows directly in the holdings table
- Analytics (`/portfolio/analytics`)
- Coverage diagnostics + risk decomposition details
- Exposure context percentiles (`/portfolio/exposure-timeseries`)
- Scenario runner (`/portfolio/scenario`)
- Attribution quality (`/portfolio/attribution`) with explained vs realized chart
- LLM explainer (`/portfolio/explain`)

## UX/Reliability behavior

- Input state is persisted in `localStorage` (holdings, dates, API base, scenario settings).
- Requests use timeout + single retry for transient failures.
- API errors prefer backend `detail` messages for clearer troubleshooting.
- Attribution quality panel supports CSV export from the browser.
- Explainer supports `auto`, `heuristic`, and `llm` mode (backend `llm` needs `OPENAI_API_KEY`).
- Holdings section includes validation badges and concentration metrics (top-1/top-5/effective N).
- Unknown symbols are flagged when not present in model universe ticker reference.
- If autocomplete appears stale, use `Refresh Tickers` in holdings panel.
