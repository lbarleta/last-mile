"""Shared hourly snapshot date/hour picker for Live Ops and Map."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import streamlit as st

from LastMile import LastMileMetrics
from LastMile.config import TIMESTAMP_FORMAT

DATE_KEY = "snapshot_picker_date"
HOUR_KEY_PREFIX = "snapshot_picker_hour_"
FORCE_DAY_KEY = "snapshot_picker_force_day"


def _parse_snapshot_date(ts: str) -> date:
    return datetime.strptime(ts, TIMESTAMP_FORMAT).date()


def _build_timestamp(day: date, hour_label: str) -> str:
    return f"{day.isoformat()}-{hour_label}"


def _clamp_day(day: date, min_day: date, max_day: date) -> date:
    if day < min_day:
        return min_day
    if day > max_day:
        return max_day
    return day


def _hour_key(day_str: str) -> str:
    return f"{HOUR_KEY_PREFIX}{day_str}"


def _jump_to_latest(day: date, hour: str) -> None:
    """Button callback — runs before widgets are created on the next run."""
    st.session_state[DATE_KEY] = day
    st.session_state[_hour_key(day.isoformat())] = hour


def render_snapshot_picker(metrics_svc: LastMileMetrics) -> Optional[str]:
    """
    Render the shared date + hour picker.

    Returns the selected ``YYYY-MM-DD-HH:00`` timestamp, or None if unavailable.
    Selection is stored in session state so Live Ops and Map stay in sync.
    """
    latest_ts = metrics_svc.get_latest_timestamp()
    if not latest_ts:
        st.warning("No station_status rows found. Run `python scripts/collect.py` first.")
        return None

    dates = metrics_svc.list_snapshot_dates()
    if not dates:
        st.warning("No station_status rows found. Run `python scripts/collect.py` first.")
        return None

    available_days = set(dates)
    min_day = date.fromisoformat(dates[0])
    max_day = date.fromisoformat(dates[-1])
    latest_day = _parse_snapshot_date(latest_ts)
    latest_hour = latest_ts[11:16]  # HH:00

    force_day = st.session_state.pop(FORCE_DAY_KEY, None)
    if force_day:
        st.session_state[DATE_KEY] = date.fromisoformat(force_day)

    if DATE_KEY not in st.session_state:
        st.session_state[DATE_KEY] = latest_day
    else:
        stored = st.session_state[DATE_KEY]
        if isinstance(stored, date):
            st.session_state[DATE_KEY] = _clamp_day(stored, min_day, max_day)
        else:
            st.session_state[DATE_KEY] = latest_day

    c1, c2, c3, _ = st.columns([1.15, 0.7, 0.45, 1.7], vertical_alignment="bottom")
    with c1:
        selected_day = st.date_input(
            "Snapshot date",
            min_value=min_day,
            max_value=max_day,
            key=DATE_KEY,
        )
    selected_day = _clamp_day(selected_day, min_day, max_day)
    day_str = selected_day.isoformat()
    if day_str not in available_days:
        st.session_state[FORCE_DAY_KEY] = max_day.isoformat()
        st.rerun()

    hours = metrics_svc.list_snapshot_hours_for_date(day_str)
    if not hours:
        st.warning(f"No snapshots found for {day_str}.")
        return None

    default_hour = latest_hour if day_str == latest_day.isoformat() else hours[-1]
    if default_hour not in hours:
        default_hour = hours[-1]

    hour_key = _hour_key(day_str)
    if hour_key not in st.session_state or st.session_state[hour_key] not in hours:
        st.session_state[hour_key] = default_hour

    with c2:
        selected_hour = st.selectbox(
            "Hour",
            options=hours,
            key=hour_key,
        )
    with c3:
        st.markdown(
            """
            <style>
              div[data-testid="stHorizontalBlock"] > div:nth-child(3) button {
                padding: 0.2rem 0.55rem !important;
                min-height: 1.9rem !important;
                height: 1.9rem !important;
                font-size: 0.78rem !important;
                line-height: 1.2 !important;
              }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            "Latest Data",
            use_container_width=True,
            type="secondary",
            on_click=_jump_to_latest,
            args=(latest_day, latest_hour),
        )

    return _build_timestamp(selected_day, selected_hour)
