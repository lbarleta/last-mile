#!/usr/bin/env python3
"""Collect an hourly Bay Wheels GBFS snapshot into MySQL.

Usage:
    python scripts/collect.py
    python scripts/collect.py --db mysql://user:password@host/lastmile
    python scripts/collect.py --setup   # recreate stations table first
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from LastMile import (
    DEFAULT_FEEDS_URL,
    DEFAULT_LANG,
    DEFAULT_TIMEZONE,
    LastMileManager,
    LastMileSetup,
)
from LastMile.db import connect
from LastMile.engine import as_url, describe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LastMile hourly GBFS collector")
    parser.add_argument(
        "--db",
        default=None,
        help="MySQL URL (default: LASTMILE_DATABASE_URL)",
    )
    parser.add_argument("--feeds-url", default=DEFAULT_FEEDS_URL)
    parser.add_argument("--lang", default=DEFAULT_LANG)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create/refresh tables and station metadata before collecting",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = as_url(args.db)

    # A database with no stations table has never been set up, so the first run
    # against a fresh one bootstraps itself without needing --setup.
    needs_setup = args.setup
    if not needs_setup:
        conn = connect(target)
        try:
            needs_setup = not conn.has_table("stations")
        finally:
            conn.close()

    if needs_setup:
        print(f"Running setup against {describe(target)}…")
        with LastMileSetup(
            feeds_url=args.feeds_url, lang=args.lang, db_path=target
        ) as setup:
            setup.create_tables(overwrite=args.setup)
            if not setup.verify_setup():
                print("Setup verification failed")
                return 1

    print(f"Collecting snapshot into {describe(target)}…")
    with LastMileManager(
        feeds_url=args.feeds_url,
        lang=args.lang,
        db_path=target,
        timezone=args.timezone,
    ) as manager:
        manager.update_data()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
