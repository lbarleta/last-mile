"""Live ops view — hourly snapshot KPIs and region charts."""

from __future__ import annotations

import streamlit as st

from components.charts import render_region_status_pct
from components.kpis import render_live_kpis
from components.snapshot_picker import render_snapshot_picker
from LastMile.lastmile_metrics import LastMileMetrics


def render(metrics_svc: LastMileMetrics) -> None:
    selected_ts = render_snapshot_picker(metrics_svc)
    if not selected_ts:
        return

    try:
        live = metrics_svc.get_live_ops_metrics(selected_ts)
    except Exception as exc:
        st.error(f"Failed to load live metrics: {exc}")
        return

    if not live["timestamp"]:
        st.warning(f"No station data for snapshot `{selected_ts}`.")
        return

    render_live_kpis(live)
    render_region_status_pct(metrics_svc.get_station_status_by_region(selected_ts))
