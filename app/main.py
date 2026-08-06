"""LastMile dashboard — shared header with Live Ops / Trends switcher."""

from __future__ import annotations

from pathlib import Path

import path_setup  # noqa: F401

import streamlit as st

from components import (
    apply_layout_styles,
    format_snapshot_date,
    get_metrics,
    inject_umami,
    resolve_db_path,
)
from views import forecast, live_ops, map_view, trends

st.set_page_config(
    page_title="Last Mile",
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_umami()
apply_layout_styles()

db_path = resolve_db_path()
if not Path(db_path).exists():
    st.error(
        "Database not found. Place the warehouse at `data/lastmile-sf.db` "
        "or set `LASTMILE_DB`."
    )
    st.stop()

metrics_svc = get_metrics(db_path)
latest_ts = metrics_svc.get_latest_timestamp()
latest_date = format_snapshot_date(latest_ts) if latest_ts else "unknown"

st.markdown(
    f"""
<div class="lm-header">
  <div class="lm-title">Last Mile</div>
  <div class="lm-subtitle">Bay Wheels · San Francisco Bay Area</div>
  <div class="lm-blurb">
    An ops dashboard for Bay Wheels (Lyft) that collects hourly
    <a href="https://github.com/NABSA/gbfs">GBFS</a> snapshots of station and
    free-bike status into a local database.<br/>
    Collection currently spans from October 25, 2025 to {latest_date}.
    Metric definitions and design choices are in
    <a href="https://github.com/lbarleta/last-mile/blob/main/NOTES.md">NOTES.md</a>.
    By <a href="https://github.com/lbarleta/last-mile">Leo Barleta</a>.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# "Forecast" is under development and stays out of the options list; the
# dispatch branch below keeps it one edit away from being re-enabled.
view = st.segmented_control(
    "View",
    options=["Live Ops", "Map", "Trends"],
    default="Live Ops",
    label_visibility="collapsed",
)

if view == "Map":
    map_view.render(metrics_svc)
elif view == "Forecast":
    forecast.render(metrics_svc)
elif view == "Trends":
    trends.render(metrics_svc)
else:
    live_ops.render(metrics_svc)
