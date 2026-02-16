from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List

import polars as pl

from factor_exposure.data.yfinance_cache import load_prices_cached


def _read_universe(path: Path) -> List[str]:
    df = pl.read_csv(path)
    tickers = [str(t).strip().upper() for t in df.get_column("ticker").to_list()]
    invalid = {"", "NONE", "NAN", "NULL", "NA"}
    clean = [t for t in tickers if t not in invalid]
    # preserve order but dedupe
    return list(dict.fromkeys(clean))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=str, required=True, help="CSV with column 'ticker'")
    parser.add_argument("--asof", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--lookback_years", type=int, default=10)
    parser.add_argument("--min_history_days", type=int, default=504)
    parser.add_argument("--min_coverage_ratio", type=float, default=0.8)
    parser.add_argument("--data_root", type=str, default="data")
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional CSV output path for validation report",
    )
    parser.add_argument(
        "--summary_out",
        type=str,
        default=None,
        help="Optional JSON output path for validation summary",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.asof)
    start = as_of - timedelta(days=int(args.lookback_years * 365.25))
    data_root = Path(args.data_root)

    tickers = _read_universe(Path(args.universe))
    spy_pf = load_prices_cached(data_root=data_root, ticker="SPY", start=start, end=as_of)
    spy_days = max(spy_pf.df.height, 1)

    rows = []
    for ticker in tickers:
        try:
            pf = load_prices_cached(data_root=data_root, ticker=ticker, start=start, end=as_of)
            frame = pf.df.sort("date")
            n_obs = frame.height
            first_date = frame.select(pl.col("date").min()).item()
            last_date = frame.select(pl.col("date").max()).item()
            coverage_ratio = float(n_obs / spy_days)
            meets_history = bool(n_obs >= args.min_history_days)
            meets_coverage = bool(coverage_ratio >= args.min_coverage_ratio)
            status = "ok" if (meets_history and meets_coverage) else "insufficient_history"
            reason = ""
        except ValueError as exc:
            n_obs = 0
            first_date = None
            last_date = None
            coverage_ratio = 0.0
            meets_history = False
            meets_coverage = False
            status = "no_data"
            reason = str(exc)

        rows.append(
            {
                "ticker": ticker,
                "status": status,
                "obs_days": n_obs,
                "coverage_ratio_vs_spy": coverage_ratio,
                "meets_history": meets_history,
                "meets_coverage": meets_coverage,
                "first_date": first_date,
                "last_date": last_date,
                "reason": reason,
            }
        )

    report = pl.DataFrame(rows).sort(["status", "ticker"])
    ok_count = report.filter(pl.col("status") == "ok").height
    short_count = report.filter(pl.col("status") == "insufficient_history").height
    no_data_count = report.filter(pl.col("status") == "no_data").height

    print(
        f"Universe validation: total={report.height} ok={ok_count} "
        f"short_history={short_count} no_data={no_data_count}"
    )
    if short_count > 0:
        short_names = report.filter(pl.col("status") == "insufficient_history").get_column("ticker").to_list()
        print(f"Short history tickers: {', '.join(short_names)}")
    if no_data_count > 0:
        none_names = report.filter(pl.col("status") == "no_data").get_column("ticker").to_list()
        print(f"No data tickers: {', '.join(none_names)}")

    summary = {
        "as_of": as_of.isoformat(),
        "lookback_years": args.lookback_years,
        "min_history_days": args.min_history_days,
        "min_coverage_ratio": args.min_coverage_ratio,
        "spy_obs_days": spy_days,
        "total": int(report.height),
        "ok": int(ok_count),
        "insufficient_history": int(short_count),
        "no_data": int(no_data_count),
    }
    print(
        "Validation summary: "
        f"ok={summary['ok']}/{summary['total']} "
        f"insufficient_history={summary['insufficient_history']} "
        f"no_data={summary['no_data']}"
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report.write_csv(out_path)
        print(f"Wrote validation report: {out_path}")

    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        print(f"Wrote validation summary: {summary_path}")


if __name__ == "__main__":
    main()
