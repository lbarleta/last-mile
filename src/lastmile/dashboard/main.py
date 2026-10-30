"""LastMile dashboard — shared header with Live Ops / Trends switcher."""

from __future__ import annotations

import streamlit as st

from lastmile.dashboard.components import (
    apply_layout_styles,
    format_snapshot_date,
    get_metrics,
    inject_umami,
    resolve_lake_path,
)
from lastmile.dashboard.views import live_ops, map_view, trends
from lastmile.settings import get_settings

st.set_page_config(
    page_title=get_settings().dashboard_title,
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_umami()
apply_layout_styles()

lake_path = resolve_lake_path()
if lake_path is None:
    st.error(
        "No warehouse found. Run `lastmile init-db` to create one, or point "
        "`LASTMILE_LAKE_PATH` at an existing lake directory."
    )
    st.stop()

metrics_svc = get_metrics(lake_path)
first_ts, latest_ts = metrics_svc.get_timestamp_bounds()
latest_date = format_snapshot_date(latest_ts) if latest_ts else "unknown"
first_date = format_snapshot_date(first_ts) if first_ts else "unknown"

# Whose system this is comes from the feed's own system_information, collected
# alongside the snapshots — nothing here is specific to one operator or city.
system = metrics_svc.get_system_info() or {}
system_name = system.get("name") or system.get("system_id") or "a GBFS system"
spec_version = system.get("gbfs_version") or "GBFS"

st.markdown(
    f"""
<div class="lm-header">
  <div class="lm-title">{get_settings().dashboard_title}</div>
  <div class="lm-subtitle">{system_name}</div>
  <div class="lm-blurb">
    An ops dashboard that collects hourly
    <a href="https://github.com/MobilityData/gbfs">GBFS</a> {spec_version}
    snapshots of station and vehicle status into a local Parquet warehouse.<br/>
    Collection currently spans from {first_date} to {latest_date}.
    Metric definitions and design choices are in
    <a href="https://github.com/lbarleta/last-mile/blob/main/NOTES.md">NOTES.md</a>.
    By <a href="https://github.com/lbarleta/last-mile">Leo Barleta</a>.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

view = st.segmented_control(
    "View",
    options=["Live Ops", "Map", "Trends"],
    default="Live Ops",
    label_visibility="collapsed",
)

if view == "Map":
    map_view.render(metrics_svc)
elif view == "Trends":
    trends.render(metrics_svc)
else:
    live_ops.render(metrics_svc)
