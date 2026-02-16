from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import List, Tuple

import polars as pl

from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.reporting.report import build_portfolio_report


def _parse_holdings(path: Path) -> List[Tuple[str, float]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("Holdings JSON must be a list of {'ticker','weight'} objects")
    out: List[Tuple[str, float]] = []
    for row in payload:
        out.append((str(row["ticker"]).upper().strip(), float(row["weight"])))
    return out


def _to_markdown(report: dict) -> str:
    lines: List[str] = []
    lines.append(f"# Portfolio Report ({report['as_of']})")
    lines.append("")
    lines.append("## Views Expressed")
    for r in report["views_expressed"]:
        lines.append(f"- {r['factor']}: {r['exposure']:.6f}")
    lines.append("")
    lines.append("## Top Risk Contributors")
    for r in report["top_risk_contributors"]:
        lines.append(f"- {r['factor']}: {r['variance_contrib']:.8f}")
    lines.append("")
    lines.append("## Drift Over Time")
    window = report["drift_window"]
    lines.append(
        f"- Window: {window['start_date']} to {window['end_date']} "
        f"({window['rows']} observations)"
    )
    for r in report["drift_top_factors"]:
        lines.append(
            f"- {r['factor']}: start={r['start_exposure']:.6f}, "
            f"end={r['end_exposure']:.6f}, delta={r['delta']:.6f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdings", type=str, required=True, help="Path to JSON list of holdings")
    parser.add_argument("--asof", type=str, default=None, help="As-of date YYYY-MM-DD (default: model as_of)")
    parser.add_argument("--start_date", type=str, default=None, help="Drift window start YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=None, help="Drift window end YYYY-MM-DD")
    parser.add_argument("--top_n", type=int, default=5, help="Top N factors per section")
    parser.add_argument("--out", type=str, default=None, help="Optional output markdown path")
    parser.add_argument(
        "--timeseries_out",
        type=str,
        default=None,
        help="Optional CSV path for full factor exposure timeseries",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.asof) if args.asof else None
    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else None
    holdings = _parse_holdings(Path(args.holdings))
    artifacts = load_latest_artifacts()

    report = build_portfolio_report(
        holdings=holdings,
        artifacts=artifacts,
        as_of=as_of,
        start_date=start,
        end_date=end,
        top_n=args.top_n,
    )
    markdown = _to_markdown(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        print(f"Wrote report: {out_path}")
    else:
        print(markdown)

    if args.timeseries_out:
        ts_path = Path(args.timeseries_out)
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        report["exposure_timeseries"].write_csv(ts_path)
        print(f"Wrote timeseries: {ts_path}")


if __name__ == "__main__":
    main()
