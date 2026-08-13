"""Shared Streamlit helpers for LastMile dashboard pages."""

from __future__ import annotations

import os
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components

from LastMile import LastMileMetrics
from LastMile.config import TIMESTAMP_FORMAT
from LastMile.engine import resolve_database_url

UMAMI_SCRIPT_SRC = "https://cloud.umami.is/script.js"


def format_snapshot_date(timestamp: str) -> str:
    """Format YYYY-MM-DD-HH:00 as a readable calendar date."""
    try:
        return datetime.strptime(timestamp, TIMESTAMP_FORMAT).strftime("%B %d, %Y")
    except ValueError:
        return timestamp[:10]


def format_snapshot_datetime(timestamp: str) -> str:
    """Format YYYY-MM-DD-HH:00 as a readable date and hour."""
    try:
        dt = datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    except ValueError:
        return timestamp
    return dt.strftime("%B %-d, %Y at %-I %p").replace("AM", "am").replace("PM", "pm")


def format_hour(hour: int) -> str:
    """Clock hour as "3 pm", matching the lowercase meridiem used elsewhere."""
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12} {suffix}"


def resolve_db_path() -> str | None:
    """
    Database URL from the environment, or None when it is not configured.

    Anything beyond "is it set" is left to fail at connection time with the
    server's own message.
    """
    try:
        return resolve_database_url()
    except RuntimeError:
        return None


def inject_umami() -> None:
    """Load Umami when UMAMI_WEBSITE_ID is set (via .env or the environment)."""
    website_id = os.environ.get("UMAMI_WEBSITE_ID", "").strip()
    if not website_id:
        return
    components.html(
        f'<script defer src="{UMAMI_SCRIPT_SRC}" '
        f'data-website-id="{website_id}"></script>',
        height=0,
    )


def apply_layout_styles() -> None:
    """Hide sidebar/chrome and apply compact shared page styles."""
    st.markdown(
        """
        <style>
            /* Force light theme even if config.toml is not discovered
               (e.g. PythonAnywhere cwd is not the project root). */
            :root, html, body, [data-testid="stAppViewContainer"], .stApp {
                color-scheme: light !important;
                background-color: #f5f6f8 !important;
                color: #1c1f24 !important;
            }
            [data-testid="stHeader"] {
                background-color: #f5f6f8 !important;
            }
            [data-testid="stMain"],
            section.main,
            .main .block-container {
                background-color: #f5f6f8 !important;
            }

            /* Hide sidebar */
            [data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"],
            [data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }

            /* Collapse Streamlit top chrome that creates empty space */
            header[data-testid="stHeader"] {
                background: #f5f6f8 !important;
                height: 0 !important;
                min-height: 0 !important;
            }
            [data-testid="stToolbar"],
            [data-testid="stDecoration"],
            .stAppDeployButton {
                display: none !important;
            }

            .block-container {
                padding-top: 0.65rem !important;
                padding-bottom: 1.75rem !important;
            }

            /* App header: clearer separation from the view below */
            .lm-header {
                margin: 0 0 0.85rem 0;
                padding: 0.1rem 0 0.95rem 0;
                border-bottom: 1px solid #dde3ea;
            }
            .lm-header .lm-title {
                font-size: 2rem !important;
                font-weight: 700 !important;
                line-height: 1.1 !important;
                margin: 0 !important;
                padding: 0 !important;
                color: #1c1f24 !important;
                letter-spacing: -0.025em;
            }
            .lm-header .lm-subtitle {
                font-size: 0.95rem !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                margin: 0.2rem 0 0.55rem 0 !important;
                padding: 0 !important;
                color: #1f6f54 !important;
                letter-spacing: 0.01em;
            }
            .lm-header .lm-blurb {
                margin: 0 !important;
                max-width: 52rem;
                line-height: 1.45 !important;
                font-size: 0.92rem !important;
                font-weight: 400 !important;
                color: #3d4450 !important;
            }
            .lm-header a {
                color: #1f6f54 !important;
                text-decoration: underline;
                text-underline-offset: 2px;
            }

            /* View switcher sits just under the header rule */
            div[data-testid="stSegmentedControl"] {
                margin-top: 0.15rem !important;
                margin-bottom: 0.55rem !important;
            }
            div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stSegmentedControl"]) {
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }

            /* Shared section hierarchy — compact, same on Live Ops and Trends */
            .stMarkdown h2,
            [data-testid="stHeading"] h2 {
                font-size: 1.15rem !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                letter-spacing: -0.01em;
                color: #1c1f24 !important;
                margin: 0.95rem 0 0.15rem 0 !important;
                padding: 0 !important;
            }
            .stMarkdown h5,
            [data-testid="stHeading"] h5 {
                font-size: 0.9rem !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                color: #2a3038 !important;
                margin: 0.1rem 0 0 !important;
                padding: 0 !important;
            }
            .stCaptionContainer,
            [data-testid="stCaptionContainer"] {
                margin-top: 0.05rem !important;
                margin-bottom: 0.3rem !important;
            }
            .stCaptionContainer p,
            [data-testid="stCaptionContainer"] p {
                font-size: 0.82rem !important;
                line-height: 1.4 !important;
                color: #5c636b !important;
            }

            /* Pull successive Streamlit blocks a little closer */
            div[data-testid="stElementContainer"] {
                margin-bottom: 0.15rem !important;
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
