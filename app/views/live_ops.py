"""Live ops view — latest hourly snapshot KPIs and station tables."""

from __future__ import annotations

import streamlit as st

from components.kpis import render_live_kpis
from LastMile.lastmile_metrics import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    st.header("Live Ops")

    try:
        live = metrics_svc.get_live_ops_metrics()
    except Exception as exc:
        st.error(f"Failed to load live metrics: {exc}")
        return

    if not live["timestamp"]:
        st.warning("No station_status rows found. Run `python scripts/collect.py` first.")
        return

    st.caption(f"Latest snapshot · {live['timestamp']}")
    render_live_kpis(live)

    left, right = st.columns(2)
    with left:
        st.subheader("Top empty stations")
        empty = metrics_svc.get_top_empty_stations(10)
        st.dataframe(empty, width="stretch", hide_index=True)
    with right:
        st.subheader("Top full stations")
        full = metrics_svc.get_top_full_stations(10)
        st.dataframe(full, width="stretch", hide_index=True)
