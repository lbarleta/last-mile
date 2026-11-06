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
from datetime import datetime
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


# --- reporting --------------------------------------------------------------

# Collection paths in the order a report lists them.
PATHS = ("snapshot", "reference", "geofencing")


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _snapshot_summary(result: dict) -> str:
    """The hour stored and the rows that were new, naming only non-empty tables."""
    written = ", ".join(f"{n:,} {name}" for name, n in result["rows"].items() if n)
    return f"{result['timestamp']}: {written or 'no new rows'}"


def _reference_summary(results: dict) -> str:
    """Only the feeds that changed, with their counts; else ``no changes``."""
    changed = []
    for name, counts in results.items():
        parts = ", ".join(
            f"{counts[kind]} {kind}"
            for kind in ("added", "changed", "removed")
            if counts[kind]
        )
        if parts:
            changed.append(f"{name} {parts}")
    return "; ".join(changed) or "no changes"


def _geofencing_summary(counts: dict) -> str:
    """Geofencing is documents, not rows: whether this run archived a new one."""
    if not counts["captures"]:
        return "feed not published"
    state = "new capture" if counts["captured"] else "unchanged"
    return f"{state}: {counts['features']:,} zones, {counts['captures']} capture(s)"


SUMMARIES = {
    "snapshot": _snapshot_summary,
    "reference": _reference_summary,
    "geofencing": _geofencing_summary,
}


def _report_paths(results: dict) -> None:
    """One line per path that ran: its summary, or ``FAILED`` and the cause."""
    for name in PATHS:
        if name in results["errors"]:
            print(f"  {name:<11} FAILED {_error(results['errors'][name])}")
        elif name in results:
            print(f"  {name:<11} {SUMMARIES[name](results[name])}")


def _report_reference_totals(results: dict) -> None:
    """One line per reference feed with its row count; for init-db."""
    for name, counts in results.items():
        changes = ", ".join(
            f"{counts[kind]} {kind}"
            for kind in ("added", "changed", "removed")
            if counts[kind]
        )
        print(
            f"  {name:<24} {counts['total']:>6,} rows{f' ({changes})' if changes else ''}"
        )


def _confirm(question: str) -> bool:
    """Ask on stdin. Anything but an explicit yes, including no stdin, is no."""
    try:
        answer = input(f"{question} [y/N] ")
    except (EOFError, OSError):
        answer = ""
    if not sys.stdin.isatty():
        print()  # nothing echoed the answer, so end the prompt line ourselves
    return answer.strip().lower() in ("y", "yes")


def _lake_state(lake: Path) -> str:
    """What is at the lake path now, for the init-db prompt."""
    if not lake.exists():
        return "does not exist yet"
    if lake.is_dir() and not any(lake.iterdir()):
        return "empty"
    return "exists but is not initialized"


# --- commands ---------------------------------------------------------------


def cmd_init_db(args: argparse.Namespace) -> int:
    """Create the lake and load reference data."""
    from . import collect, db, settings
    from .db import queries, schema

    conn = _connect(args)
    lake = db.as_path(args.lake)
    if conn.is_initialized():
        info = queries.get_system_info(conn) or {}
        _, last = queries.get_timestamp_bounds(conn)
        system = info.get("name") or info.get("system_id") or "unknown system"
        snapshots = f"last snapshot {last}" if last else "no snapshots yet"
        print(
            f"Lake {lake} is already initialized ({system}, {snapshots}); ",
            file=sys.stderr,
        )
        return 1

    print(f"Lake:    {lake} ({_lake_state(lake)})")
    print(f"Config:  {settings.find_config() or 'none found; built-in defaults apply'}")
    print(f"Feeds:   {settings.get_settings().feeds_url}")
    if not _confirm("Create the lake and load reference data?"):
        print("Aborted; nothing was written.")
        return 1

    schema.create_all(conn)
    results = collect.collect(conn, snapshot=False)
    if "reference" in results:
        system = queries.get_system_info(conn) or {}
        print(
            f"Reading {system.get('name') or system.get('system_id') or 'system'} "
            f"on GBFS {system.get('gbfs_version')} ({conn.timezone})."
        )
        _report_reference_totals(results["reference"])
    if "geofencing" in results:
        print(
            f"  {'geofencing_zones':<24} {_geofencing_summary(results['geofencing'])}"
        )
    for name, exc in results["errors"].items():
        print(f"  {name:<24} FAILED {_error(exc)}")
    return 1 if results["errors"] else 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Run the selected collection paths, or all when none is named."""
    from . import collect

    conn = _connect(args)
    lake = _describe(args)
    if not conn.is_initialized():
        print(
            f"Lake {lake} is not initialized; run `lastmile init-db` first.",
            file=sys.stderr,
        )
        return 1

    every = not (args.snapshot or args.reference or args.geofencing)
    started = datetime.now(conn.tzinfo).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"{started} collect {lake}")
    try:
        results = collect.collect(
            conn,
            snapshot=args.snapshot or every,
            reference=args.reference or every,
            geofencing=args.geofencing or every,
        )
    except Exception as exc:
        print(f"  FAILED {_error(exc)}")
        return 1
    _report_paths(results)
    return 1 if results["errors"] else 0


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
