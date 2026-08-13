#!/usr/bin/env python3
"""Train, evaluate, and run the station stockout forecast.

The dashboard never trains or scores — it reads the tables this script writes.

Usage:
    python scripts/forecast.py --all            # backtest, train, score
    python scripts/forecast.py --backtest       # evaluation only
    python scripts/forecast.py --train          # refit and save the model
    python scripts/forecast.py --score          # score the latest snapshot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from LastMile import forecast as fc
from LastMile.config import (
    FORECAST_MAX_TRAIN_ROWS,
    FORECAST_MODEL_PATH,
    FORECAST_TRAIN_DAYS,
)
from LastMile.db import connect
from LastMile.engine import as_url, describe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LastMile stockout forecast")
    parser.add_argument(
        "--db",
        default=None,
        help="MySQL URL (default: LASTMILE_DATABASE_URL)",
    )
    parser.add_argument("--model", default=FORECAST_MODEL_PATH, help="Model artifact path")
    parser.add_argument("--all", action="store_true", help="Backtest, train, then score")
    parser.add_argument("--backtest", action="store_true", help="Run rolling-origin evaluation")
    parser.add_argument("--train", action="store_true", help="Fit and save the model")
    parser.add_argument("--score", action="store_true", help="Score the latest snapshot")
    parser.add_argument("--train-days", type=int, default=FORECAST_TRAIN_DAYS)
    parser.add_argument("--max-rows", type=int, default=FORECAST_MAX_TRAIN_ROWS)
    parser.add_argument("--folds", type=int, default=4, help="Backtest folds")
    parser.add_argument("--fold-days", type=int, default=7, help="Days per backtest fold")
    parser.add_argument("--origin", help="Score a specific snapshot hour")
    return parser.parse_args()


def _print_headline(metrics: pd.DataFrame) -> None:
    overall = metrics[metrics["horizon"] == 0]
    if overall.empty:
        print("  no comparable folds")
        return
    summary = (
        overall.groupby(["target", "model"], as_index=False)
        .agg(
            brier=("brier", "mean"),
            avg_precision=("avg_precision", "mean"),
            roc_auc=("roc_auc", "mean"),
            base_rate=("base_rate", "mean"),
        )
        .sort_values(["target", "avg_precision"], ascending=[True, False])
    )
    for target in summary["target"].unique():
        rows = summary[summary["target"] == target]
        print(f"  {target} (base rate {rows['base_rate'].iloc[0]:.2%})")
        for row in rows.itertuples(index=False):
            print(
                f"    {row.model:<12} brier {row.brier:.4f}  "
                f"PR-AUC {row.avg_precision:.3f}  ROC-AUC {row.roc_auc:.3f}"
            )


def main() -> int:
    args = parse_args()
    url = as_url(args.db)

    do_backtest = args.backtest or args.all
    do_train = args.train or args.all
    do_score = args.score or args.all
    if not (do_backtest or do_train or do_score):
        print("Nothing to do; pass --all, --backtest, --train, or --score")
        return 1

    print(f"Using {describe(url)}")
    conn = connect(url)
    try:
        fc.ensure_forecast_tables(conn)
        bundle = None

        if do_train:
            print(f"Training on the last {args.train_days} days…")
            bundle = fc.train(
                conn,
                train_days=args.train_days,
                max_rows=args.max_rows,
                verbose=True,
            )
            path = fc.save_bundle(bundle, args.model)
            print(f"Saved model {bundle.version} → {path}")

        if do_backtest:
            print(f"Backtesting {args.folds} folds of {args.fold_days} days…")
            metrics, calibration = fc.backtest(
                conn,
                n_folds=args.folds,
                fold_days=args.fold_days,
                verbose=True,
            )
            if metrics.empty:
                print("  backtest produced no comparable folds")
            else:
                version = bundle.version if bundle else "backtest-only"
                fc.write_evaluation(conn, metrics, calibration, version)
                _print_headline(metrics)

        if do_score:
            if bundle is None:
                if not Path(args.model).exists():
                    print(f"No model at {args.model}; run with --train first")
                    return 1
                bundle = fc.load_bundle(args.model)
            scored = fc.score_origin(conn, bundle, origin_timestamp=args.origin)
            if scored.empty:
                print("Nothing to score")
                return 1
            written = fc.write_predictions(conn, scored, bundle.version)
            origin = scored["origin_timestamp"].iloc[0]
            at_risk = int(((scored["p_empty"] >= 0.5) | (scored["p_full"] >= 0.5)).sum())
            print(
                f"Scored {written:,} station-hours from {origin} "
                f"({at_risk} flagged at risk)"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
