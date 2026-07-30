#!/usr/bin/env python3
"""Collect an hourly Bay Wheels GBFS snapshot into the local SQLite database.

Usage:
    python scripts/collect.py
    python scripts/collect.py --db data/lastmile-sf.db
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
    DEFAULT_DB_PATH,
    DEFAULT_FEEDS_URL,
    DEFAULT_LANG,
    DEFAULT_TIMEZONE,
    LastMileManager,
    LastMileSetup,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LastMile hourly GBFS collector")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
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
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.setup or not db_path.exists():
        print(f"Running setup against {db_path}…")
        with LastMileSetup(
            feeds_url=args.feeds_url, lang=args.lang, db_path=str(db_path)
        ) as setup:
            setup.create_tables(overwrite=args.setup)
            if not setup.verify_setup():
                print("Setup verification failed")
                return 1

    print(f"Collecting snapshot into {db_path}…")
    with LastMileManager(
        feeds_url=args.feeds_url,
        lang=args.lang,
        db_path=str(db_path),
        timezone=args.timezone,
    ) as manager:
        manager.update_data()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
