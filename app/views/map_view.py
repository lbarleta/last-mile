"""Station + free-floating bike map view."""

from __future__ import annotations

import streamlit as st

from components.maps import render_ops_map
from LastMile.lastmile_metrics import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    try:
        live = metrics_svc.get_live_ops_metrics()
        free_bikes = metrics_svc.get_free_bikes(live["timestamp"])
    except Exception as exc:
        st.error(f"Failed to load map data: {exc}")
        return

    if not live["timestamp"]:
        st.warning("No station_status rows found. Run `python scripts/collect.py` first.")
        return

    st.caption(f"Latest snapshot · {live['timestamp']}")
    render_ops_map(
        live["stations"],
        free_bikes=free_bikes,
        coverage_geojson=live.get("coverage_geojson"),
    )
