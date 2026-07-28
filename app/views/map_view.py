"""Station map view — latest hourly snapshot."""

from __future__ import annotations

import streamlit as st

from components.maps import render_station_map
from LastMile.lastmile_metrics import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    st.header("Map")

    try:
        live = metrics_svc.get_live_ops_metrics()
    except Exception as exc:
        st.error(f"Failed to load station data: {exc}")
        return

    if not live["timestamp"]:
        st.warning("No station_status rows found. Run `python scripts/collect.py` first.")
        return

    st.caption(f"Latest snapshot · {live['timestamp']}")
    render_station_map(live["stations"])
