"""Shared Streamlit helpers for LastMile dashboard pages."""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st

from LastMile import DEFAULT_DB_PATH, LastMileMetrics
from LastMile.config import TIMESTAMP_FORMAT


def format_snapshot_date(timestamp: str) -> str:
    """Format YYYY-MM-DD-HH:00 as a readable calendar date."""
    try:
        return datetime.strptime(timestamp, TIMESTAMP_FORMAT).strftime("%B %d, %Y")
    except ValueError:
        return timestamp[:10]


def resolve_db_path() -> str:
    """DB path from LASTMILE_DB env or project default (not shown in UI)."""
    return os.environ.get("LASTMILE_DB", DEFAULT_DB_PATH)


def apply_layout_styles() -> None:
    """Hide sidebar/chrome and tighten header spacing."""
    st.markdown(
        """
        <style>
            /* Hide sidebar */
            [data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"],
            [data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }

            /* Collapse Streamlit top chrome that creates empty space */
            header[data-testid="stHeader"] {
                background: transparent !important;
                height: 0 !important;
                min-height: 0 !important;
            }
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            .stAppDeployButton {
                display: none !important;
            }

            .block-container {
                padding-top: 0.75rem !important;
                padding-bottom: 2rem !important;
            }

            /* Compact title + subtitle hierarchy */
            .lm-header {
                margin: 0 0 0.25rem 0;
            }
            .lm-header .lm-title {
                font-size: 2.15rem !important;
                font-weight: 700 !important;
                line-height: 1.15 !important;
                margin: 0 !important;
                padding: 0 !important;
                color: #1c1f24 !important;
                letter-spacing: -0.02em;
            }
            .lm-header .lm-subtitle {
                font-size: 1.1rem !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                margin: 0.2rem 0 0.7rem 0 !important;
                padding: 0 !important;
                color: #4a5058 !important;
            }
            .lm-header .lm-blurb {
                margin: 0 0 0.85rem 0 !important;
                line-height: 1.45 !important;
                font-size: 1rem !important;
                font-weight: 400 !important;
                color: #1c1f24 !important;
            }
            .lm-header a {
                color: #1f6f54 !important;
            }

            /* Keep page content close under the view switcher */
            div[data-testid="stSegmentedControl"] {
                margin-bottom: 0.15rem !important;
            }
            div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stSegmentedControl"]) {
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }
            .stCaptionContainer,
            [data-testid="stCaptionContainer"] {
                margin-top: 0.15rem !important;
                margin-bottom: 0.35rem !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_metrics(db_path: str) -> LastMileMetrics:
    return LastMileMetrics(db_path=db_path)


def clear_caches() -> None:
    get_metrics.clear()
