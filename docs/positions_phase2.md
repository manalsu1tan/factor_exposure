# Phase 2: Position Events + Snapshot Engine

This phase introduces an event-sourced position state layer that can feed both:
- intraday/streaming updates
- end-of-day reproducible snapshots

## Target folders

```text
src/factor_exposure/
  positions/
    __init__.py
    schemas.py        # canonical event + snapshot row models
    store.py          # parquet-backed event log IO
    engine.py         # event fold -> point-in-time snapshot

data/
  positions/
    events.parquet    # append-only event log per portfolio_id
```

## Event schema (canonical)

`PositionEvent` fields:
- `event_id` (string, idempotency key)
- `portfolio_id` (string)
- `event_time` (datetime)
- `ticker` (string, uppercased)
- `event_type` (`TRADE` | `MANUAL_ADJUSTMENT` | `SPLIT` | `DIVIDEND`)
- `quantity` (float; signed for `ADJUSTMENT`, positive for `TRADE`)
- `side` (`BUY` | `SELL`, required for `TRADE`)
- `price` (float, required for `TRADE`)
- `fees` (float, default `0.0`)
- `split_ratio` (float, required for `SPLIT`)
- `cash_amount_per_share` (float, required for `CASH_DIVIDEND`)
- `source` (optional string)

Aliases accepted:
- `ADJUSTMENT` -> `MANUAL_ADJUSTMENT`
- `CASH_DIVIDEND` -> `DIVIDEND`

## Snapshot schema

`PositionSnapshotRow` fields:
- `ticker`
- `quantity`
- `avg_cost`
- `realized_pnl`
- `dividends_pnl`
- `total_pnl`
- `last_event_time`
- `change_reasons` (`trade`, `manual_adjustment`, `split`, `dividend`)

## Endpoint contracts

### `POST /positions/events`
Append one or more events for a portfolio.

Request:
```json
{
  "portfolio_id": "demo_book",
  "events": [
    {
      "event_time": "2025-01-02T14:30:00Z",
      "ticker": "AAPL",
      "event_type": "TRADE",
      "side": "BUY",
      "quantity": 100,
      "price": 180.5,
      "fees": 1.0
    }
  ]
}
```

### `GET /positions/events`
Read stored events with filters.

Query params:
- `portfolio_id` (required)
- `ticker` (optional)
- `as_of` (optional datetime)
- `limit` (optional, default 200)

### `POST /positions/snapshot`
Fold events to a position snapshot at a cutoff.

Request:
```json
{
  "portfolio_id": "demo_book",
  "as_of": "2025-12-31T21:00:00Z",
  "include_closed": false
}
```

Response includes:
- portfolio-level totals (`realized_pnl`, `dividends_pnl`, counts)
- per-ticker rows with quantity/cost/PnL

## Math behavior

- `TRADE`: updates quantity, weighted average cost, and realized PnL on closes/flips.
- `ADJUSTMENT`: synthetic signed quantity update; uses provided `price` or current `avg_cost`.
- `SPLIT`: scales quantity by ratio and inversely scales average cost.
- `CASH_DIVIDEND`: books `quantity * cash_amount_per_share` into `dividends_pnl`.

## Next extensions

- Add market-price join for unrealized PnL + market value.
- Add reconciliation endpoint for batch close vs stream state.
- Add explainability decomposition (`trade`, `price`, `corporate_action` deltas).
