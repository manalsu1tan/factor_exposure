**Goal**
Build a daily US equities “views + risks” engine: given holdings, output (1) factor exposures, (2) risk decomposition (factor vs specific), (3) realized return attribution, (4) simple stress scenarios—beyond FF5 via richer style + industry factors and a proper covariance/specific-risk model.

**Data (free)**
- Prices/volume/corp actions: `yfinance` (cache to Parquet; treat as research-grade, not survivorship-safe).
- Optional fundamentals later: SEC EDGAR (adds complexity; not required for v1).

**Factor set (equities-only, daily, MVP)**
- **Industry**: sector/industry one-hot (start with sector if you want minimal).
- **Style (10–12)** (all computed from price/volume so you can ship fast):
  - Size (log mkt cap proxy if you have shares; otherwise use price*shares if available; or skip size in v1)
  - Beta (to SPY)
  - Residual/Idio vol (from market model)
  - Momentum (12-1, 6-1)
  - Short-term reversal (1w/1m)
  - Low vol (trailing vol)
  - Liquidity (dollar volume, Amihud proxy)
  - Trend (time-series momentum)
  - Dividend yield/value/quality require fundamentals—keep these “v2”.

**Model (Barra-like)**
1) **Exposure computation** per stock per day: standardized (z-score), winsorized, optionally industry-neutralized.
2) **Cross-sectional regression** each day:
   - \( r_{t} = X_{t} f_{t} + \epsilon_{t} \)
   - Robust/WLS (weights by sqrt(mkt cap) or liquidity).
   - Outputs daily factor returns \(f_t\) and residuals.
3) **Risk model**
   - Factor covariance: EWMA + shrinkage (stable with daily data).
   - Specific risk: EWMA of residual variance (with floors/caps).
4) **Portfolio analytics**
   - Exposures: \( b = X^\top w \)
   - Predicted vol: \( b^\top \Sigma_f b + \sum w_i^2 \sigma^2_{\epsilon,i} \)
   - Risk contributions by factor, by name.
   - Return attribution over a period: sum of \(b_t \cdot f_t\) + specific.

**Project deliverables (what you’ll show recruiters)**
- A callable API: `POST /portfolio/analytics` → exposures, risk decomposition, attribution, stress.
- A demo report/dashboard: “Top expressed views”, “Top risk drivers”, “Factor P&L last 1m/3m/1y”.
- Diagnostics notebook: factor t-stats, turnover, exposure distributions, residual correlation, stability plots.

**Repo scope (suggested structure)**
- `/Users/Manal/factor_exposure/`
  - `src/factor_exposure/`
    - `data/` (yfinance pull, caching, universe)
    - `features/` (factor definitions)
    - `model/` (cross-sec regression, cov, specific risk)
    - `portfolio/` (exposure/risk/attribution)
    - `api/` (FastAPI)
  - `pipelines/` (daily jobs: ingest → features → fit → store artifacts)
  - `notebooks/` (research + diagnostics)
  - `data/` (Parquet cache + model artifacts; gitignored)

**Milestones (tight MVP)**
1) Universe + cached daily OHLCV (10y) + clean returns.
2) Compute 8–10 price/vol/liquidity factors daily; store exposures.
3) Daily cross-sectional fit → factor returns + residuals; store.
4) Covariance + specific risk; portfolio risk decomposition.
5) FastAPI endpoint + Streamlit demo page.

**Key limitations to be explicit about**
- Yahoo/`yfinance` is not survivorship-safe; delistings and ticker history gaps can bias backtests.
- Without fundamentals, “value/quality/profitability” are approximations; v1 focuses on price/volume-derived factors.

If you want, I can scaffold this in `/Users/Manal/factor_exposure` with a working end-to-end path (download → build exposures → fit model → run a sample portfolio analytics call).