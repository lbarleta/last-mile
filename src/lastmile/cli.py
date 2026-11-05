"""
The ``lastmile`` command.

    lastmile init-db               lay out the lake and load reference data
    lastmile collect               collect every feed (cron-friendly)
        --snapshot                   only the hourly status feeds
        --reference                  only the tracked reference feeds
        --geofencing                 only the geofencing zones
    lastmile status                what the warehouse currently holds
    lastmile dashboard             serve the Streamlit dashboard
    lastmile weather               not implemented
    lastmile forecast              not implemented

Every command takes ``--lake`` and ``--config``. This module only prints;
collection is :mod:`lastmile.collect`'s and the lake layout :mod:`lastmile.db.schema`'s.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .settings import reload_settings


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lake",
        default=None,
        help="Parquet lake directory (default: LASTMILE_LAKE_PATH)",
    )
    parser.add_argument(
        "--config", default=None, help="Path to lastmile.toml (default: auto-discover)"
    )


def _connect(args: argparse.Namespace):
    from . import db

    return db.connect(args.lake)


def _describe(args: argparse.Namespace) -> str:
    from . import db

    return db.describe(db.as_path(args.lake))


# --- commands ---------------------------------------------------------------


def _report_reference(results: dict) -> None:
    """One line per reference feed, naming only what actually changed."""
    for name, counts in results.items():
        changes = ", ".join(
            f"{counts[kind]} {kind}"
            for kind in ("added", "changed", "removed")
            if counts[kind]
        )
        print(
            f"  {name:<24} {counts['total']:>6,} rows{f' ({changes})' if changes else ''}"
        )


def _report_geofencing(counts: dict) -> None:
    """Geofencing is documents, not rows: zones in the newest capture."""
    note = " (new capture archived)" if counts["captured"] else ""
    print(
        f"  {'geofencing_zones':<24} {counts['features']:>6,} zones, "
        f"{counts['captures']} capture(s){note}"
    )


def cmd_init_db(args: argparse.Namespace) -> int:
    """Lay out the lake and load everything but a snapshot. Safe to re-run."""
    from . import collect
    from .db import queries, schema

    conn = _connect(args)
    print(f"Initializing {_describe(args)}…")
    schema.create_all(conn)
    results = collect.collect(conn, snapshot=False)
    system = queries.get_system_info(conn) or {}
    print(
        f"Reading {system.get('name') or system.get('system_id') or 'system'} "
        f"on GBFS {system.get('gbfs_version')} ({conn.timezone})."
    )
    _report_reference(results["reference"])
    _report_geofencing(results["geofencing"])
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Run the selected collection paths, or all of them when none is named."""
    from . import collect

    conn = _connect(args)
    if not conn.is_initialized():
        print(
            f"Lake {_describe(args)} is not initialized; run `lastmile init-db` first.",
            file=sys.stderr,
        )
        return 1

    every = not (args.snapshot or args.reference or args.geofencing)
    results = collect.collect(
        conn,
        snapshot=args.snapshot or every,
        reference=args.reference or every,
        geofencing=args.geofencing or every,
    )
    if "reference" in results:
        _report_reference(results["reference"])
    if "geofencing" in results:
        _report_geofencing(results["geofencing"])
    if "snapshot" in results:
        result = results["snapshot"]
        written = ", ".join(f"{n:,} {name}" for name, n in result["rows"].items())
        print(f"{result['timestamp']}: {written} rows written to {_describe(args)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print what the lake holds, table by table."""
    from .db import queries, schema

    conn = _connect(args)
    print(f"Lake: {_describe(args)}")
    missing = schema.missing_tables(conn)
    if missing:
        print(f"Missing datasets: {', '.join(missing)} — run `lastmile init-db`")
        return 1
    info = queries.get_system_info(conn)
    if info:
        print(
            f"System: {info['name'] or info['system_id']} "
            f"({info['system_id']}) · GBFS {info['gbfs_version']} · "
            f"{info['timezone'] or 'no timezone declared'} "
            f"(hours shown in {conn.timezone})"
        )
    first, last = queries.get_timestamp_bounds(conn)
    print(f"Snapshots: {first} → {last}")
    groups = (
        ("hourly", schema.HOURLY_TABLES, None),
        ("tracked", schema.TRACKED_TABLES, (schema.LOG_SUFFIX, "logged")),
    )
    for group, names, companion in groups:
        print(f"{group}:")
        for table in names:
            suffix = ""
            if companion:
                extra, label = companion
                suffix = f" (+{conn.count(table + extra):,} {label})"
            print(f"  {table:<34} {conn.count(table):>12,} rows{suffix}")

    from . import geofencing

    zones = geofencing.summary(conn.root)
    print("documents:")
    print(
        f"  {'geofencing_zones':<34} {zones['features']:>12,} zones "
        f"({zones['captures']} capture(s))"
    )
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Hand off to ``streamlit run``; its exit code is ours."""
    import subprocess

    main_py = Path(__file__).resolve().parent / "dashboard" / "main.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(main_py)]
    if args.port:
        cmd += ["--server.port", str(args.port)]
    cmd += args.streamlit_args
    return subprocess.call(cmd)


def cmd_weather(args: argparse.Namespace) -> int:
    """Not implemented; :mod:`lastmile.weather` is a stub."""
    from . import weather

    print(f"{weather.MESSAGE}.", file=sys.stderr)
    return 1


def cmd_forecast(args: argparse.Namespace) -> int:
    """Not implemented; :mod:`lastmile.forecasting` is a stub."""
    from . import forecasting

    print(f"{forecasting.MESSAGE}.", file=sys.stderr)
    return 1


# --- parser -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """The argument parser; each subcommand sets ``func`` to its handler."""
    parser = argparse.ArgumentParser(
        prog="lastmile", description="GBFS collection and bike-share ops dashboard"
    )
    parser.add_argument(
        "--version", action="version", version=f"lastmile {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="Lay out the lake and load reference data")
    _add_common(p)
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser(
        "collect",
        help="Collect from the GBFS feeds",
        description="Collect from the GBFS feeds. With no flags, run every "
        "collection path; otherwise run exactly the paths named.",
    )
    _add_common(p)
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="Store one hourly snapshot of the status feeds",
    )
    p.add_argument(
        "--reference",
        action="store_true",
        help="Re-read the slow-changing feeds and log any changes",
    )
    p.add_argument(
        "--geofencing",
        action="store_true",
        help="Archive the geofencing zones if they changed",
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

    p = sub.add_parser("weather", help="Populate the weather cache (not implemented)")
    _add_common(p)
    p.set_defaults(func=cmd_weather)

    p = sub.add_parser("forecast", help="Stockout forecasting (not implemented)")
    _add_common(p)
    p.set_defaults(func=cmd_forecast)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Warnings from lower layers reach stderr through ``logging``."""
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    if getattr(args, "config", None):
        os.environ["LASTMILE_CONFIG"] = args.config
        reload_settings()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
