# Factor Definitions

This document is the canonical definition for factor construction in this repo.
Source of truth in code: `src/factor_exposure/model/factors.py`.

## Conventions

- Universe: US equities in your `data/universe.csv`.
- Frequency: daily.
- Inputs:
  - `P_{i,t}` = adjusted close for ticker `i` on date `t`
  - `V_{i,t}` = share volume for ticker `i` on date `t`
  - `P^{SPY}_t` = SPY adjusted close on date `t`
- Daily return:
  - `r_{i,t} = P_{i,t} / P_{i,t-1} - 1`
  - `r^{SPY}_t = P^{SPY}_t / P^{SPY}_{t-1} - 1`

## Raw factor formulas (before cross-sectional normalization)

1) `mom_12_1` (12-1 momentum)
- Implemented as `roll(pct_change(P, 252), 21)`.
- Equivalent:
  - `mom_12_1(i,t) = P_{i,t-21} / P_{i,t-273} - 1`
- Intuition: medium-term trend, skipping the most recent month.

2) `mom_6_1` (6-1 momentum)
- Implemented as `roll(pct_change(P, 126), 21)`.
- Equivalent:
  - `mom_6_1(i,t) = P_{i,t-21} / P_{i,t-147} - 1`
- Intuition: intermediate trend, skipping the most recent month.

3) `rev_1m` (1-month short-term reversal)
- Implemented as `-pct_change(P, 21)`.
- Formula:
  - `rev_1m(i,t) = -(P_{i,t} / P_{i,t-21} - 1)`
- Intuition:
  - Positive `rev_1m` means the stock underperformed over the last month (laggard).
  - Negative `rev_1m` means the stock outperformed over the last month (winner).
  - This is **reversal**, not revenue revision.

4) `beta_spy_252` (252-day market beta)
- Rolling 252-day beta to SPY:
  - `beta_spy_252(i,t) = Cov_{252}(r_{i}, r^{SPY}) / Var_{252}(r^{SPY})`
- Uses population moments (`ddof=0`) and rolling window ending at `t`.

5) `vol_63` (63-day realized volatility)
- Formula:
  - `vol_63(i,t) = Std_{63}(r_{i})`
- Uses population standard deviation (`ddof=0`) over last 63 daily returns.

6) `liq_dollarvol_21` (21-day log dollar-volume liquidity)
- Dollar volume per day:
  - `DV_{i,t} = P_{i,t} * V_{i,t}`
- 21-day average dollar volume:
  - `\overline{DV}_{i,t} = mean(DV_{i,t-k}), k=0..20`
- Factor:
  - `liq_dollarvol_21(i,t) = log(\overline{DV}_{i,t})`
- Intuition: higher value = more traded names, typically easier to execute.

## Cross-sectional normalization (what exposures store)

For each factor and date `t`, across all tickers in the universe:

1. Winsorize each row at `mean ± 5 * std`.
2. Z-score each row:
   - `z_{i,t} = (x_{i,t} - mean_t(x)) / std_t(x)`
3. Missing values are set to `0.0` after normalization.

So the stored exposures in `data/model/latest/exposures.parquet` are **cross-sectional z-scores**, not raw units.

## Sign interpretation for portfolio exposure

- `mom_12_1` positive: tilt to medium-term winners; negative: contrarian vs medium-term momentum.
- `mom_6_1` positive: tilt to intermediate winners; negative: contrarian vs intermediate momentum.
- `rev_1m` positive: reversal tilt (recent laggards); negative: short-term continuation tilt (recent winners).
- `beta_spy_252` positive: more market-sensitive/pro-cyclical; negative: more defensive.
- `vol_63` positive: tilt to higher-volatility stocks; negative: tilt to lower-volatility stocks.
- `liq_dollarvol_21` positive: tilt to higher-liquidity stocks; negative: tilt to lower-liquidity stocks.

## Practical note

Because exposures are z-scored each day, magnitudes are relative to the cross-section on that date. A `+1.0` is roughly one cross-sectional standard deviation above the universe mean for that factor on that date.
