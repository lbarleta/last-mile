"""KPI metric row helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


def _inject_kpi_styles() -> None:
    st.markdown(
        """
        <style>
            .kpi-row {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 0.75rem;
                margin-bottom: 0.75rem;
            }
            .kpi-card {
                border: 1px solid #d5d9de;
                border-radius: 8px;
                background: #ffffff;
                padding: 0.85rem 1rem;
                min-height: 5.25rem;
            }
            .kpi-label {
                font-size: 0.8rem;
                font-weight: 500;
                color: #5c636b;
                margin-bottom: 0.35rem;
            }
            .kpi-value {
                font-size: 1.35rem;
                font-weight: 700;
                color: #1c1f24;
                line-height: 1.25;
            }
            .kpi-delta {
                font-size: 0.78rem;
                font-weight: 500;
                margin-top: 0.35rem;
            }
            .kpi-delta-up { color: #1f6f54; }
            .kpi-delta-down { color: #b42318; }
            .kpi-delta-flat { color: #7a828a; }
            .kpi-section-label {
                font-size: 0.75rem;
                font-weight: 600;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #7a828a;
                margin: 0.15rem 0 0.4rem 0;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_pct_with_count(pct: float, count: int) -> str:
    return f"{pct:.1f}% ({count:,})"


def _fmt_ratio(ebikes: int, classic: int, ratio: Optional[float]) -> str:
    if ratio is None:
        return f"{ebikes:,} : {classic:,}"
    return f"{ratio:.2f} : 1 ({ebikes:,}:{classic:,})"


def _fmt_delta(
    delta: Optional[float],
    *,
    as_pp: bool = False,
    as_count: bool = False,
) -> str:
    if delta is None:
        return '<div class="kpi-delta kpi-delta-flat">vs prior hour: n/a</div>'

    if abs(delta) < 1e-9:
        text = "0" if as_count else ("0.0 pp" if as_pp else "0.0")
        return f'<div class="kpi-delta kpi-delta-flat">vs prior hour: {text}</div>'

    arrow = "▲" if delta > 0 else "▼"
    css = "kpi-delta-up" if delta > 0 else "kpi-delta-down"
    if as_pp:
        text = f"{arrow} {abs(delta):.1f} pp"
    elif as_count:
        text = f"{arrow} {abs(delta):,.0f}"
    else:
        text = f"{arrow} {abs(delta):.2f}"
    return f'<div class="kpi-delta {css}">vs prior hour: {text}</div>'


def _kpi_row(cards: List[Tuple[str, str, str]]) -> str:
    items = "".join(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{delta}</div>'
        for label, value, delta in cards
    )
    return f'<div class="kpi-row">{items}</div>'


def render_live_kpis(metrics: Dict[str, Any]) -> None:
    _inject_kpi_styles()
    deltas = metrics.get("deltas") or {}

    station_cards = [
        (
            "Total stations",
            f"{metrics['total_stations']:,}",
            _fmt_delta(deltas.get("total_stations"), as_count=True),
        ),
        (
            "% Full",
            _fmt_pct_with_count(metrics["pct_full"], metrics["full_stations"]),
            _fmt_delta(deltas.get("pct_full"), as_pp=True),
        ),
        (
            "% Empty",
            _fmt_pct_with_count(metrics["pct_empty"], metrics["empty_stations"]),
            _fmt_delta(deltas.get("pct_empty"), as_pp=True),
        ),
        (
            "% Dock availability",
            _fmt_pct_with_count(
                metrics["pct_dock_availability"], metrics["docks_available"]
            ),
            _fmt_delta(deltas.get("pct_dock_availability"), as_pp=True),
        ),
    ]
    bike_cards = [
        (
            "Total bikes",
            f"{metrics['total_bikes']:,}",
            _fmt_delta(deltas.get("total_bikes"), as_count=True),
        ),
        (
            "E-bike : classic",
            _fmt_ratio(
                metrics["ebikes_available"],
                metrics["classic_available"],
                metrics.get("ebike_classic_ratio"),
            ),
            _fmt_delta(deltas.get("ebike_classic_ratio")),
        ),
        (
            "% E-bike availability",
            _fmt_pct_with_count(
                metrics["pct_ebike_availability"], metrics["ebikes_available"]
            ),
            _fmt_delta(deltas.get("pct_ebike_availability"), as_pp=True),
        ),
        (
            "% Classic availability",
            _fmt_pct_with_count(
                metrics["pct_classic_availability"], metrics["classic_available"]
            ),
            _fmt_delta(deltas.get("pct_classic_availability"), as_pp=True),
        ),
    ]

    st.markdown('<div class="kpi-section-label">Stations</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(station_cards), unsafe_allow_html=True)
    st.markdown('<div class="kpi-section-label">Bikes</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(bike_cards), unsafe_allow_html=True)
