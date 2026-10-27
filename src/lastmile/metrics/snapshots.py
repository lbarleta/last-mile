"""What snapshots exist: the pickers' view of the warehouse."""

from __future__ import annotations

from ..db import queries
from .base import BaseMetric


class SnapshotMetrics(BaseMetric):
    """Snapshot and region listings used by the dashboard's pickers."""

    def list_snapshot_dates(self) -> list[str]:
        return queries.list_snapshot_dates(self.conn)

    def list_snapshot_hours_for_date(self, date_str: str) -> list[str]:
        return queries.list_snapshot_hours_for_date(self.conn, date_str)

    def list_regions(self) -> list[str]:
        """Station regions available for filtering."""
        return queries.list_regions(self.conn)
