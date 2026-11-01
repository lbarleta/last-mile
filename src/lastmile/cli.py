"""
The ``lastmile`` command.

    lastmile init-db               lay out the lake and load reference data
    lastmile collect               store one hourly snapshot (cron-friendly)
    lastmile status                what the warehouse currently holds
    lastmile dashboard             serve the Streamlit dashboard
    lastmile weather               not implemented
    lastmile forecast              not implemented

Global flags: ``--lake`` overrides the configured lake directory, ``--config``
points at an explicit lastmile.toml.
"""

from __future__ import annotations

import argparse
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
        if "captures" in counts:  # geofencing: documents, not rows
            note = " (new capture archived)" if counts["captured"] else ""
            print(
                f"  {name:<24} {counts['features']:>6,} zones, "
                f"{counts['captures']} capture(s){note}"
            )
            continue
        changes = ", ".join(
            f"{counts[kind]} {kind}"
            for kind in ("added", "changed", "removed")
            if counts[kind]
        )
        print(
            f"  {name:<24} {counts['total']:>6,} rows{f' ({changes})' if changes else ''}"
        )


def cmd_init_db(args: argparse.Namespace) -> int:
    from . import collect
    from .gbfs import GbfsClient

    print(f"Initializing {_describe(args)}…")
    conn = _connect(args)
    client = GbfsClient()
    info = client.system_information()
    results = collect.init_db(conn, client)
    print(
        f"Reading {info.get('name') or info.get('system_id') or 'system'} "
        f"on GBFS {client.version} ({collect.resolve_timezone(conn, client)})."
    )
    _report_reference(results)
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from . import collect

    conn = _connect(args)
    if not collect.is_initialized(conn):
        print(
            f"Lake {_describe(args)} is not initialized; run `lastmile init-db` first.",
            file=sys.stderr,
        )
        return 1

    result = collect.collect_snapshot(conn)
    written = ", ".join(f"{n:,} {name}" for name, n in result["rows"].items())
    print(f"{result['timestamp']}: {written} rows written to {_describe(args)}")
    if args.refresh_reference:
        from .gbfs import GbfsClient

        _report_reference(collect.refresh_reference_data(conn, GbfsClient()))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
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
            f"{info['timezone']}"
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
    import subprocess

    main_py = Path(__file__).resolve().parent / "dashboard" / "main.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(main_py)]
    if args.port:
        cmd += ["--server.port", str(args.port)]
    cmd += args.streamlit_args
    return subprocess.call(cmd)


def cmd_weather(args: argparse.Namespace) -> int:
    """Wiring only — see :mod:`lastmile.weather`, which is a stub."""
    from . import weather

    print(f"{weather.MESSAGE}.", file=sys.stderr)
    return 1


def cmd_forecast(args: argparse.Namespace) -> int:
    """Wiring only — see :mod:`lastmile.forecasting`, which is a stub."""
    from . import forecasting

    print(f"{forecasting.MESSAGE}.", file=sys.stderr)
    return 1


# --- parser -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
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

    p = sub.add_parser("collect", help="Store one hourly GBFS snapshot")
    _add_common(p)
    p.add_argument(
        "--refresh-reference",
        action="store_true",
        help="Also re-read the slow-changing feeds and log any changes",
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
