"""Station + free-floating bike map view."""

from __future__ import annotations

import streamlit as st

from components.maps import render_ops_map
from components.snapshot_picker import render_snapshot_picker
from LastMile import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    selected_ts = render_snapshot_picker(metrics_svc)
    if not selected_ts:
        return

    try:
        live = metrics_svc.get_live_ops_metrics(selected_ts)
        free_bikes = metrics_svc.get_free_bikes(selected_ts)
    except Exception as exc:
        st.error(f"Failed to load map data: {exc}")
        return

    if not live["timestamp"]:
        st.warning(f"No station data for snapshot `{selected_ts}`.")
        return

    render_ops_map(
        live["stations"],
        free_bikes=free_bikes,
        coverage_geojson=live.get("coverage_geojson"),
    )
