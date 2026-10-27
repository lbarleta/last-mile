"""
Metrics derived from stored LastMile snapshots, grouped by dashboard view.

Each submodule holds one metric group as a small class on top of
:class:`BaseMetric`, which owns the connection and the shared timestamp
helpers. :class:`Metrics` composes them back into the single object the
dashboard instantiates.
"""

from __future__ import annotations

from .base import BaseMetric
from .live_ops import LiveOpsMetrics
from .snapshots import SnapshotMetrics
from .trends import TrendsMetrics


class Metrics(LiveOpsMetrics, TrendsMetrics, SnapshotMetrics):
    """Every metric group behind one handle, for the dashboard and the CLI."""


__all__ = [
    "BaseMetric",
    "Metrics",
    "LiveOpsMetrics",
    "SnapshotMetrics",
    "TrendsMetrics",
]
