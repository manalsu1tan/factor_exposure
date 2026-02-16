# Schemas

This project separates:
- **Raw market data cache** (per ticker, from yfinance)
- **Daily factor exposures** (per ticker, per date)
- **Model artifacts** (factor returns, factor covariance, specific variance)

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

## 6) Specific variance
Path:
- `data/model/latest/specific_var.parquet`

Parquet columns:
- `date` (date)
- `ticker` (string)
- `specific_var` (float, daily variance)

## 7) Metadata
Path:
- `data/model/latest/metadata.json`

Keys:
- `as_of` (YYYY-MM-DD)
- `factors` (list of factor names, order used for covariance)
- `universe_size` (int)
- `lookbacks` (object)

