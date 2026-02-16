# Schemas

This project separates:
- **Raw market data cache** (per ticker, from yfinance)
- **Daily factor exposures** (per ticker, per date)
- **Model artifacts** (factor returns, specific returns, factor covariance, specific variance)
- **Diagnostics artifacts** (data quality + model diagnostics)

For exact factor formulas/sign conventions, see:
- `docs/factors.md`

## 1) Universe file
Path:
- `data/universe.csv`

CSV columns:
- `ticker` (string)

## 2) Cached price history (per ticker)
Path pattern:
- `data/cache/yfinance/prices/{TICKER}.parquet`

Parquet columns:
- `date` (date)
- `open` (float)
- `high` (float)
- `low` (float)
- `close` (float)
- `adj_close` (float)
- `volume` (float)

Notes:
- We request adjusted prices; `adj_close` drives returns.

## 3) Daily exposures
Path:
- `data/model/latest/exposures.parquet`

Parquet columns:
- `date` (date)
- `ticker` (string)
- `mom_12_1` (float, cross-sectional z-score)
- `mom_6_1` (float, cross-sectional z-score)
- `rev_1m` (float, cross-sectional z-score)
- `beta_spy_252` (float, cross-sectional z-score)
- `vol_63` (float, cross-sectional z-score)
- `liq_dollarvol_21` (float, cross-sectional z-score)

## 4) Factor returns
Path:
- `data/model/latest/factor_returns.parquet`

Parquet columns:
- `date` (date)
- one column per factor (float, daily factor return)

## 5) Factor covariance
Path:
- `data/model/latest/factor_cov.npy`

Numpy array:
- shape: (K, K), aligned to `data/model/latest/metadata.json` `factors` order

## 6) Specific returns
Path:
- `data/model/latest/specific_returns.parquet`

Parquet columns:
- `date` (date)
- `ticker` (string)
- `residual` (float, daily specific return from cross-sectional fit)

## 7) Asset returns (for attribution quality checks)
Path:
- `data/model/latest/asset_returns.parquet`

Parquet columns:
- `date` (date)
- `ticker` (string)
- `ret` (float, realized close-to-close return used in model fit window)

## 8) Specific variance
Path:
- `data/model/latest/specific_var.parquet`

Parquet columns:
- `date` (date)
- `ticker` (string)
- `specific_var` (float, daily variance)

## 9) Metadata
Path:
- `data/model/latest/metadata.json`

Keys:
- `as_of` (YYYY-MM-DD)
- `factors` (list of factor names, order used for covariance)
- `universe_size` (int)
- `lookbacks` (object)

## 10) Ticker quality
Path:
- `data/model/latest/ticker_quality.parquet`

Parquet columns:
- `ticker` (string)
- `price_obs_days` (int)
- `volume_obs_days` (int)
- `price_coverage_ratio` (float)
- `volume_coverage_ratio` (float)
- `first_price_date` (date)
- `last_price_date` (date)

## 11) Data quality summary
Path:
- `data/model/latest/data_quality.json`

Keys (subset):
- `as_of` (YYYY-MM-DD)
- `universe_requested` (int)
- `universe_loaded` (int)
- `skipped_tickers` (list[string])
- `model_days` (int)
- `avg_price_coverage_ratio` (float)
- `avg_volume_coverage_ratio` (float)

## 12) Model diagnostics summary
Path:
- `data/model/latest/model_diagnostics.json`

Keys (subset):
- `as_of` (YYYY-MM-DD)
- `factor_count` (int)
- `covariance_condition_number` (float)
- `fit` (object: fit dates, cross-sectional size stats, R² stats)
- `factor_return_stats` (object keyed by factor with mean/std/tstat)

## 13) Universe validation outputs
Paths (optional outputs from `validate_universe`):
- `data/model/universe_validation.csv`
- `data/model/universe_validation_summary.json`

Validation CSV columns:
- `ticker` (string)
- `status` (`ok` | `insufficient_history` | `no_data`)
- `obs_days` (int)
- `coverage_ratio_vs_spy` (float)
- `meets_history` (bool)
- `meets_coverage` (bool)
- `first_date` (date)
- `last_date` (date)
- `reason` (string)

## 14) Position events log
Path:
- `data/positions/events.parquet`

Parquet columns:
- `event_id` (string)
- `portfolio_id` (string)
- `event_time` (datetime)
- `ticker` (string)
- `event_type` (`TRADE` | `ADJUSTMENT` | `SPLIT` | `CASH_DIVIDEND`)
- canonicalized to (`TRADE` | `MANUAL_ADJUSTMENT` | `SPLIT` | `DIVIDEND`)
- `quantity` (float)
- `side` (string, nullable)
- `price` (float, nullable)
- `fees` (float)
- `split_ratio` (float, nullable)
- `cash_amount_per_share` (float, nullable)
- `source` (string, nullable)

## 15) Position snapshot response schema (API object)
Produced by:
- `POST /positions/snapshot`

Per-row fields:
- `ticker` (string)
- `quantity` (float)
- `avg_cost` (float)
- `market_price` (float, nullable)
- `price_as_of` (date, nullable)
- `market_value` (float, nullable)
- `realized_pnl` (float)
- `dividends_pnl` (float)
- `total_pnl` (float)
- `unrealized_pnl` (float, nullable)
- `economic_total_pnl` (float, nullable)
- `last_event_time` (datetime)
- `change_reasons` (list[string], subset of `trade|manual_adjustment|split|dividend`)
