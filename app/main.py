"""LastMile dashboard — shared header with Live Ops / Historical switcher."""

from __future__ import annotations

from pathlib import Path

import path_setup  # noqa: F401

import streamlit as st

from components import (
    apply_layout_styles,
    format_snapshot_date,
    get_metrics,
    resolve_db_path,
)
from LastMile.lastmile_queries import get_timestamp_bounds
from views import historical, live_ops, map_view

st.set_page_config(
    page_title="Last Mile",
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="collapsed",
)

apply_layout_styles()

db_path = resolve_db_path()
if not Path(db_path).exists():
    st.error(
        "Database not found. Place the warehouse at `data/lastmile-sf.db` "
        "or set `LASTMILE_DB`."
    )
    st.stop()

metrics_svc = get_metrics(db_path)
first_ts, last_ts = get_timestamp_bounds(metrics_svc.conn)
first_date = format_snapshot_date(first_ts) if first_ts else "unknown"
last_date = format_snapshot_date(last_ts) if last_ts else "unknown"

st.markdown(
    f"""
<div class="lm-header">
  <div class="lm-title">Last Mile</div>
  <div class="lm-subtitle">Bay Wheels, San Francisco</div>
  <div class="lm-blurb">
    A dashboard for Bay Wheels, a regional bike share system in the San Francisco
    Bay Area operated by Lyft. Data is based on hourly snapshots published in
    <a href="https://github.com/NABSA/gbfs">GBFS</a> format and ranges from
    <strong>{first_date}</strong> to <strong>{last_date}</strong>.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

view = st.segmented_control(
    "View",
    options=["Live Ops", "Map", "Historical"],
    default="Live Ops",
    label_visibility="collapsed",
)

st.divider()

if view == "Map":
    map_view.render(metrics_svc)
elif view == "Historical":
    historical.render(metrics_svc)
else:
    live_ops.render(metrics_svc)
