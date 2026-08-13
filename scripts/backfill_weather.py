#!/usr/bin/env python3
"""Populate the local weather cache used by the stockout forecast.

Usage:
    python scripts/backfill_weather.py                 # full snapshot span
    python scripts/backfill_weather.py --refresh       # recent + future only
    python scripts/backfill_weather.py --start 2025-10-25 --end 2026-07-28
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from LastMile import weather as weather_mod
from LastMile.db import connect, get_timestamp_bounds
from LastMile.engine import as_url, describe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LastMile weather backfill")
    parser.add_argument(
        "--db",
        default=None,
        help="MySQL URL (default: LASTMILE_DATABASE_URL)",
    )
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Only pull the recent past and forecast window (hourly cron use)",
    )
    parser.add_argument(
        "--past-days",
        type=int,
        default=7,
        help="Days of recent history to refresh (with --refresh)",
    )
    parser.add_argument(
        "--forecast-days",
        type=int,
        default=3,
        help="Days of forecast to store (with --refresh)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = as_url(args.db)

    print(f"Using {describe(url)}")
    conn = connect(url)
    try:
        weather_mod.ensure_weather_table(conn)

        if args.refresh:
            df = weather_mod.fetch_forecast(
                past_days=args.past_days, forecast_days=args.forecast_days
            )
            written = weather_mod.upsert_weather(
                conn, df, weather_mod.SOURCE_FORECAST
            )
            print(f"Refreshed {written} hours from the forecast endpoint")
        else:
            start, end = args.start, args.end
            if start is None or end is None:
                first, last = get_timestamp_bounds(conn)
                if first is None or last is None:
                    print("No snapshots in the database; nothing to align to")
                    return 1
                start = start or first[:10]
                end = end or last[:10]
            print(f"Backfilling weather for {start} → {end}…")
            written = weather_mod.backfill(conn, start, end, verbose=True)
            print(f"Wrote {written} hours")

        summary = weather_mod.coverage_summary(conn)
        print(
            f"Cache: {summary['hours']:,} hours "
            f"({summary['archive_hours']:,} from archive) "
            f"{summary['min_timestamp']} → {summary['max_timestamp']}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
