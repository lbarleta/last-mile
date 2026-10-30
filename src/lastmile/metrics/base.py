"""The connection handling and timestamp helpers every metric group shares."""

from __future__ import annotations

from pathlib import Path

from .. import db
from ..db import queries


class BaseMetric:
    """Connection handling and timestamp helpers shared by all metric groups."""

    def __init__(self, lake: str | Path | None = None, conn: db.Db | None = None):
        self._owns_conn = conn is None
        self.conn = conn if conn is not None else db.connect(lake)

    @property
    def timezone(self) -> str:
        """The zone stored hours are in, as recorded when the lake was built."""
        from ..collect import resolve_timezone

        return resolve_timezone(self.conn)

    def close(self) -> None:
        if self._owns_conn and self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_latest_timestamp(self) -> str | None:
        return queries.get_latest_timestamp(self.conn)

    def _since_from_hours(self, hours: int | None) -> str | None:
        """Window start for a trailing-hours range, anchored on the last snapshot."""
        latest = self.get_latest_timestamp()
        if latest is None:
            return None
        return queries.cutoff_timestamp(hours, self.timezone, latest)

