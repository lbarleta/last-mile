"""
Weather cache — a stub.

Intended to hold hourly weather on the same local-hour grid as
``station_status``, so the two join without timezone handling. Nothing is
implemented: this module is the wiring that ``lastmile weather`` calls. The
``weather`` table is declared in :mod:`lastmile.db.schema` so its shape is
settled, but nothing writes to it.
"""

from __future__ import annotations

from .db import Db

MESSAGE = "the weather cache is not implemented"


def ensure_weather_table(conn: Db) -> None:
    """Create the weather dataset if it does not exist."""
    conn.ensure_table("weather")


def backfill(conn: Db, start_date: str, end_date: str, **kwargs) -> int:
    """Populate the cache for a date range. Not implemented."""
    raise NotImplementedError(MESSAGE)


def refresh(conn: Db, **kwargs) -> int:
    """Re-read the recent past and the forecast horizon. Not implemented."""
    raise NotImplementedError(MESSAGE)


__all__ = ["MESSAGE", "backfill", "ensure_weather_table", "refresh"]
