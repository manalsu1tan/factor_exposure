from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import List, Tuple

import polars as pl

from factor_exposure.model.artifacts import load_latest_artifacts
from factor_exposure.portfolio.analytics import portfolio_attribution


def _parse_holdings(path: Path) -> List[Tuple[str, float]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("Holdings JSON must be a list of {'ticker','weight'} objects")
    return [(str(row["ticker"]).upper().strip(), float(row["weight"])) for row in payload]


def _to_markdown(result: dict) -> str:
    q = result.get("quality", {})
    lines: List[str] = []
    lines.append(f"# Attribution Quality Report ({result['start_date']} to {result['end_date']})")
    lines.append("")
    lines.append("## Coverage")
    cov = result["coverage"]
    lines.append(
        f"- Holdings with data: {cov['holdings_with_any_data']}/{cov['requested_holdings']}, "
        f"days with data: {cov['days_with_data']}/{cov['days_requested']}"
    )
    lines.append("")
    lines.append("## Explained vs Realized")
    if not q.get("available", False):
        lines.append("- Asset returns not available; rebuild model artifacts to generate `asset_returns.parquet`.")
    else:
        lines.append(f"- Days compared: {q.get('days_compared', 0)}")
        lines.append(f"- Mean residual: {q.get('mean_residual', 0.0):+.8f}")
        lines.append(f"- MAE residual: {q.get('mae_residual', 0.0):.8f}")
        lines.append(f"- RMSE residual: {q.get('rmse_residual', 0.0):.8f}")
        lines.append(f"- Residual t-stat: {q.get('residual_tstat', 0.0):+.4f}")
        lines.append(f"- Corr(explained, realized): {q.get('corr_explained_vs_realized', 0.0):+.4f}")
        lines.append(f"- R²(explained->realized): {q.get('r2_explained_vs_realized', 0.0):+.4f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdings", type=str, required=True, help="Path to JSON list of holdings")
    parser.add_argument("--start_date", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--out", type=str, default=None, help="Optional markdown output path")
    parser.add_argument(
        "--daily_csv_out",
        type=str,
        default=None,
        help="Optional CSV path for daily explained/realized residual rows",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else None
    holdings = _parse_holdings(Path(args.holdings))
    artifacts = load_latest_artifacts()

    result = portfolio_attribution(
        holdings=holdings,
        artifacts=artifacts,
        start_date=start,
        end_date=end,
        include_daily=True,
        compact=False,
        include_quality=True,
    )
    markdown = _to_markdown(result)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        print(f"Wrote report: {out_path}")
    else:
        print(markdown)

    if args.daily_csv_out:
        rows = []
        for row in result.get("daily", []):
            quality = row.get("quality")
            if not quality:
                continue
            rows.append(
                {
                    "date": row["date"],
                    "explained_return": quality["explained_return"],
                    "realized_return": quality["realized_return"],
                    "residual_return": quality["residual_return"],
                    "factor_return": row["factor_return"],
                    "specific_return": row["specific_return"],
                    "total_return": row["total_return"],
                }
            )
        csv_path = Path(args.daily_csv_out)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows).write_csv(csv_path)
        print(f"Wrote daily quality CSV: {csv_path}")


if __name__ == "__main__":
    main()
