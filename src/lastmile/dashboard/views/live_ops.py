"""Live ops view — hourly snapshot KPIs and region charts."""

from __future__ import annotations

import streamlit as st

from lastmile.dashboard.components.charts import render_region_status_pct
from lastmile.dashboard.components.kpis import render_live_kpis
from lastmile.dashboard.components.snapshot_picker import render_snapshot_picker
from lastmile.dashboard.components.tables import render_problematic_stations
from lastmile.metrics import Metrics


def render(metrics_svc: Metrics) -> None:
    selected_ts = render_snapshot_picker(metrics_svc)
    if not selected_ts:
        return

    try:
        live = metrics_svc.get_live_ops_metrics(selected_ts)
        problematic = metrics_svc.get_problematic_stations(selected_ts)
    except Exception as exc:
        st.error(f"Failed to load live metrics: {exc}")
        return

    if not live["timestamp"]:
        st.warning(f"No station data for snapshot `{selected_ts}`.")
        return

    render_live_kpis(live)

    left, right = st.columns(2, gap="medium", vertical_alignment="top")
    with left:
        render_problematic_stations(problematic)
    with right:
        render_region_status_pct(
            metrics_svc.get_station_status_by_region(selected_ts)
        )
