"""
The ``lastmile`` command.

    lastmile init-db               create the schema and load reference data
    lastmile collect               store one hourly snapshot (cron-friendly)
    lastmile status                what the warehouse currently holds
    lastmile dashboard             serve the Streamlit dashboard
    lastmile weather ...           populate the weather cache (under development)
    lastmile forecast ...          train/score the stockout forecast (needs [forecast])

Global flags: ``--db`` overrides the configured database URL, ``--config``
points at an explicit lastmile.toml.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .settings import get_settings, reload_settings


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db", default=None, help="Database URL (default: LASTMILE_DATABASE_URL)"
    )
    parser.add_argument(
        "--config", default=None, help="Path to lastmile.toml (default: auto-discover)"
    )


def _connect(args: argparse.Namespace):
    from . import db

    return db.connect(args.db)


def _describe(args: argparse.Namespace) -> str:
    from . import db

    return db.describe(db.as_url(args.db))


# --- commands ---------------------------------------------------------------


def cmd_init_db(args: argparse.Namespace) -> int:
    from . import collect

    print(f"Initializing {_describe(args)}…")
    conn = _connect(args)
    counts = collect.init_db(conn)
    print(
        f"Schema ready; {counts['stations']} stations and "
        f"{counts['vehicle_types']} vehicle types loaded."
    )
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from . import collect

    conn = _connect(args)
    if not collect.is_initialized(conn):
        print(
            f"Database {_describe(args)} is not initialized; "
            "run `lastmile init-db` first.",
            file=sys.stderr,
        )
        return 1

    result = collect.collect_snapshot(conn)
    print(
        f"{result['timestamp']}: {result['station_rows']} station rows, "
        f"{result['bike_rows']} bike rows written to {_describe(args)}"
    )
    if args.refresh_stations:
        from .gbfs import GbfsClient

        client = GbfsClient()
        n = collect.refresh_stations(conn, client)
        t = collect.refresh_vehicle_types(conn, client)
        print(f"Reference data refreshed: {n} stations, {t} vehicle types")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .db import queries, schema

    conn = _connect(args)
    print(f"Database: {_describe(args)}")
    missing = schema.missing_tables(conn)
    if missing:
        print(f"Missing tables: {', '.join(missing)} — run `lastmile init-db`")
        return 1
    latest = queries.get_latest_timestamp(conn)
    first, last = queries.get_timestamp_bounds(conn)
    print(f"Snapshots: {first} → {last} (latest: {latest})")
    for table in ("stations", "station_status", "bike_status", "weather", "forecast_stockout"):
        print(f"  {table:<18} {conn.count(table):>12,} rows")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    import subprocess

    main_py = Path(__file__).resolve().parent / "dashboard" / "main.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(main_py)]
    if args.port:
        cmd += ["--server.port", str(args.port)]
    cmd += args.streamlit_args
    return subprocess.call(cmd)


def cmd_weather(args: argparse.Namespace) -> int:
    from . import weather
    from .db import queries

    conn = _connect(args)
    weather.ensure_weather_table(conn)
    if args.refresh:
        df = weather.fetch_forecast(
            past_days=args.past_days, forecast_days=args.forecast_days
        )
        written = weather.upsert_weather(conn, df, weather.SOURCE_FORECAST)
        print(f"Refreshed {written} hours from the forecast endpoint")
    else:
        start, end = args.start, args.end
        if start is None or end is None:
            first, last = queries.get_timestamp_bounds(conn)
            if first is None or last is None:
                print("No snapshots in the database; nothing to align to")
                return 1
            start = start or first[:10]
            end = end or last[:10]
        print(f"Backfilling weather for {start} → {end}…")
        written = weather.backfill(conn, start, end, verbose=True)
        print(f"Wrote {written} hours")

    summary = weather.coverage_summary(conn)
    print(
        f"Cache: {summary['hours']:,} hours "
        f"({summary['archive_hours']:,} from archive) "
        f"{summary['min_timestamp']} → {summary['max_timestamp']}"
    )
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    try:
        from .forecasting import model as fc
    except ImportError as exc:
        print(f'The forecast extra is not installed ({exc}).')
        print('Install it with: pip install -e ".[forecast]"')
        return 1
    from .forecasting.metrics import ensure_forecast_tables

    do_backtest = args.backtest or args.all
    do_train = args.train or args.all
    do_score = args.score or args.all
    if not (do_backtest or do_train or do_score):
        print("Nothing to do; pass --all, --backtest, --train, or --score")
        return 1

    model_path = args.model or str(get_settings().forecast_model_file)
    conn = _connect(args)
    print(f"Using {_describe(args)}")
    ensure_forecast_tables(conn)
    bundle = None

    if do_train:
        print(f"Training on the last {args.train_days} days…")
        bundle = fc.train(
            conn, train_days=args.train_days, max_rows=args.max_rows, verbose=True
        )
        path = fc.save_bundle(bundle, model_path)
        print(f"Saved model {bundle.version} → {path}")

    if do_backtest:
        print(f"Backtesting {args.folds} folds of {args.fold_days} days…")
        metrics, calibration = fc.backtest(
            conn, n_folds=args.folds, fold_days=args.fold_days, verbose=True
        )
        if metrics.empty:
            print("  backtest produced no comparable folds")
        else:
            version = bundle.version if bundle else "backtest-only"
            fc.write_evaluation(conn, metrics, calibration, version)

    if do_score:
        if bundle is None:
            if not Path(model_path).exists():
                print(f"No model at {model_path}; run with --train first")
                return 1
            bundle = fc.load_bundle(model_path)
        scored = fc.score_origin(conn, bundle, origin_timestamp=args.origin)
        if scored.empty:
            print("Nothing to score")
            return 1
        written = fc.write_predictions(conn, scored, bundle.version)
        origin = scored["origin_timestamp"].iloc[0]
        threshold = get_settings().forecast_risk_threshold
        at_risk = int(
            ((scored["p_empty"] >= threshold) | (scored["p_full"] >= threshold)).sum()
        )
        print(
            f"Scored {written:,} station-hours from {origin} "
            f"({at_risk} flagged at risk)"
        )
    return 0


# --- parser -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lastmile", description="Bay Wheels collection and dashboard"
    )
    parser.add_argument("--version", action="version", version=f"lastmile {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="Create the schema and load reference data")
    _add_common(p)
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("collect", help="Store one hourly GBFS snapshot")
    _add_common(p)
    p.add_argument(
        "--refresh-stations",
        action="store_true",
        help="Also refresh station metadata and vehicle types",
    )
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("status", help="Show what the warehouse holds")
    _add_common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("dashboard", help="Serve the Streamlit dashboard")
    _add_common(p)
    p.add_argument("--port", type=int, default=None)
    p.add_argument(
        "streamlit_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments for `streamlit run`, after `--` "
        "(e.g. lastmile dashboard -- --server.headless true)",
    )
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("weather", help="Populate the weather cache (under development)")
    _add_common(p)
    p.add_argument("--refresh", action="store_true", help="Recent past + forecast only")
    p.add_argument("--past-days", type=int, default=7)
    p.add_argument("--forecast-days", type=int, default=3)
    p.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", help="End date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_weather)

    p = sub.add_parser(
        "forecast", help="Train/score the stockout forecast (needs the forecast extra)"
    )
    _add_common(p)
    p.add_argument("--model", default=None, help="Model artifact path")
    p.add_argument("--all", action="store_true", help="Backtest, train, then score")
    p.add_argument("--backtest", action="store_true")
    p.add_argument("--train", action="store_true")
    p.add_argument("--score", action="store_true")
    p.add_argument("--train-days", type=int, default=None)
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--folds", type=int, default=4, help="Backtest folds")
    p.add_argument("--fold-days", type=int, default=7, help="Days per backtest fold")
    p.add_argument("--origin", help="Score a specific snapshot hour")
    p.set_defaults(func=cmd_forecast)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "config", None):
        os.environ["LASTMILE_CONFIG"] = args.config
        reload_settings()
    if getattr(args, "command", "") == "forecast":
        settings = get_settings()
        if args.train_days is None:
            args.train_days = settings.forecast_train_days
        if args.max_rows is None:
            args.max_rows = settings.forecast_max_train_rows
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
