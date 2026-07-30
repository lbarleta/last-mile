"""KPI metric row helpers."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


def _inject_kpi_styles() -> None:
    st.markdown(
        """
        <style>
            .kpi-card {
                position: relative;
                border: 1px solid #d5d9de;
                border-radius: 8px;
                background: #ffffff;
                padding: 0.75rem 0.85rem;
                min-height: 4.5rem;
                overflow: visible;
            }
            .kpi-row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
                gap: 0.65rem;
                margin-bottom: 0.75rem;
                overflow: visible;
            }
            .kpi-label {
                font-size: 0.75rem;
                font-weight: 500;
                color: #5c636b;
                margin-bottom: 0.35rem;
                padding-right: 1.1rem;
            }
            .kpi-help {
                position: absolute;
                top: 0.4rem;
                right: 0.45rem;
                width: 1rem;
                height: 1rem;
                border-radius: 50%;
                border: 1px solid #c5ccd3;
                color: #7a828a;
                font-size: 0.68rem;
                font-weight: 600;
                line-height: 1rem;
                text-align: center;
                cursor: help;
                background: #f7f8fa;
                z-index: 5;
            }
            .kpi-help:hover {
                color: #1c1f24;
                border-color: #9aa1a9;
            }
            .kpi-tip {
                display: none;
                position: absolute;
                top: calc(100% + 0.35rem);
                right: 0;
                min-width: 140px;
                max-width: 200px;
                padding: 0.4rem 0.55rem;
                border-radius: 6px;
                border: 1px solid #d5d9de;
                background: #1c1f24;
                color: #ffffff;
                font-size: 0.68rem;
                font-weight: 400;
                line-height: 1.35;
                text-align: left;
                white-space: normal;
                box-shadow: 0 4px 12px rgba(28, 31, 36, 0.18);
                z-index: 20;
                pointer-events: none;
            }
            .kpi-help:hover .kpi-tip,
            .kpi-help:focus .kpi-tip {
                display: block;
            }
            .kpi-value-row {
                display: flex;
                align-items: baseline;
                flex-wrap: wrap;
                gap: 0.4rem;
            }
            .kpi-value {
                font-size: 1.25rem;
                font-weight: 700;
                color: #1c1f24;
                line-height: 1.25;
            }
            .kpi-count {
                font-size: 0.8rem;
                font-weight: 400;
                color: #6b7280;
            }
            .kpi-delta {
                font-size: 0.8rem;
                font-weight: 600;
                white-space: nowrap;
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
            .kpi-hero {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 0.65rem;
                margin: 0 0 1rem 0;
            }
            .kpi-hero-card {
                position: relative;
                border: 1px solid #d5d9de;
                border-radius: 10px;
                background: #ffffff;
                padding: 1rem 1.75rem;
                flex: 1 1 300px;
                max-width: 420px;
                text-align: center;
                overflow: visible;
            }
            .kpi-hero-note {
                font-size: 0.75rem;
                color: #7a828a;
                margin-top: 0.3rem;
            }
            .kpi-hero-label {
                font-size: 0.85rem;
                font-weight: 600;
                letter-spacing: 0.03em;
                text-transform: uppercase;
                color: #5c636b;
                margin-bottom: 0.35rem;
                padding-right: 1.1rem;
            }
            .kpi-hero-value {
                font-size: 2rem;
                font-weight: 700;
                color: #1c1f24;
                line-height: 1.2;
            }
            .kpi-hero .kpi-value-row {
                justify-content: center;
            }
            .kpi-hero-card .kpi-help {
                top: 0.55rem;
                right: 0.6rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _help_icon(hint: str) -> str:
    if not hint:
        return ""
    return (
        '<span class="kpi-help" tabindex="0" aria-label="More info">'
        "?"
        f'<span class="kpi-tip">{escape(hint)}</span>'
        "</span>"
    )


def _fmt_pct_with_count(pct: float, count: int) -> str:
    return f'{pct:.1f}% <span class="kpi-count">({count:,})</span>'


def _hour_label(timestamp: Optional[str]) -> str:
    """Snapshot hour as a plain clock label, e.g. "4 pm"."""
    try:
        hour = int(str(timestamp)[11:13])
    except (TypeError, ValueError):
        return "this hour"
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12} {suffix}"


def _fmt_vs_typical(
    delta: Optional[float], timestamp: Optional[str], samples: int
) -> str:
    if delta is None or samples == 0:
        return "no baseline for this hour yet"
    hour = _hour_label(timestamp)
    if abs(delta) < 0.05:
        return f"typical for {hour}"
    direction = "above" if delta > 0 else "below"
    return f"{abs(delta):.1f} {direction} typical for {hour}"


def _fmt_distance_m(meters: Optional[float]) -> str:
    if meters is None:
        return "n/a"
    if meters >= 1000:
        return f"{meters / 1000.0:.2f} km"
    return f"{meters:.0f} m"


def _fmt_delta(
    delta: Optional[float],
    *,
    as_pp: bool = False,
    as_count: bool = False,
    as_meters: bool = False,
) -> str:
    if delta is None:
        return '<span class="kpi-delta kpi-delta-flat">n/a</span>'

    # Treat values that round to zero at display precision as unchanged,
    # so tiny float noise doesn't show as a red/green "0.0".
    if as_meters:
        display_mag = round(abs(delta))
        zero_text = "0 m"
    elif as_count:
        display_mag = round(abs(delta))
        zero_text = "0"
    elif as_pp:
        display_mag = round(abs(delta), 1)
        zero_text = "0.0 pp"
    else:
        display_mag = round(abs(delta), 2)
        zero_text = "0.0"

    if display_mag == 0:
        return f'<span class="kpi-delta kpi-delta-flat">{zero_text}</span>'

    arrow = "▲" if delta > 0 else "▼"
    css = "kpi-delta-up" if delta > 0 else "kpi-delta-down"
    if as_meters:
        text = f"{arrow} {display_mag:.0f} m"
    elif as_pp:
        text = f"{arrow} {display_mag:.1f} pp"
    elif as_count:
        text = f"{arrow} {display_mag:,.0f}"
    else:
        text = f"{arrow} {display_mag:.2f}"
    return f'<span class="kpi-delta {css}">{text}</span>'


def _kpi_row(cards: List[Tuple[str, str, str, str]]) -> str:
    items = []
    for label, hint, value, delta in cards:
        delta_html = delta or ""
        items.append(
            f'<div class="kpi-card">{_help_icon(hint)}'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value-row"><div class="kpi-value">{value}</div>'
            f"{delta_html}</div></div>"
        )
    return f'<div class="kpi-row">{"".join(items)}</div>'


def render_live_kpis(metrics: Dict[str, Any]) -> None:
    _inject_kpi_styles()
    deltas = metrics.get("deltas") or {}

    station_cards = [
        (
            "Total stations",
            "",
            f"{metrics['total_stations']:,}",
            "",
        ),
        (
            "Full stations",
            "",
            _fmt_pct_with_count(metrics["pct_full"], metrics["full_stations"]),
            _fmt_delta(deltas.get("pct_full"), as_pp=True),
        ),
        (
            "Empty stations",
            "",
            _fmt_pct_with_count(metrics["pct_empty"], metrics["empty_stations"]),
            _fmt_delta(deltas.get("pct_empty"), as_pp=True),
        ),
        (
            "Healthy stations",
            "Has bikes and docks; bike share ≥20%",
            _fmt_pct_with_count(metrics["pct_healthy"], metrics["healthy_stations"]),
            _fmt_delta(deltas.get("pct_healthy"), as_pp=True),
        ),
        (
            "Low stations",
            "Has bikes and docks; bike share <20%",
            _fmt_pct_with_count(metrics["pct_low"], metrics["low_stations"]),
            _fmt_delta(deltas.get("pct_low"), as_pp=True),
        ),
        (
            "Available docks",
            "",
            _fmt_pct_with_count(
                metrics["pct_dock_availability"], metrics["docks_available"]
            ),
            _fmt_delta(deltas.get("pct_dock_availability"), as_pp=True),
        ),
        (
            "Disabled docks",
            "",
            _fmt_pct_with_count(
                metrics["pct_docks_disabled"], metrics["docks_disabled"]
            ),
            _fmt_delta(deltas.get("pct_docks_disabled"), as_pp=True),
        ),
    ]
    bike_cards = [
        (
            "Available",
            "",
            f"{metrics['available_bikes']:,}",
            _fmt_delta(deltas.get("available_bikes"), as_count=True),
        ),
        (
            "Docked Classic",
            "",
            _fmt_pct_with_count(
                metrics["pct_docked_classic"], metrics["classic_available"]
            ),
            _fmt_delta(deltas.get("pct_docked_classic"), as_pp=True),
        ),
        (
            "Docked E-bikes",
            "",
            _fmt_pct_with_count(
                metrics["pct_docked_ebike"], metrics["ebikes_available"]
            ),
            _fmt_delta(deltas.get("pct_docked_ebike"), as_pp=True),
        ),
        (
            "Free-floating",
            "",
            _fmt_pct_with_count(
                metrics["pct_free_range"], metrics["free_bikes_total"]
            ),
            _fmt_delta(deltas.get("pct_free_range"), as_pp=True),
        ),
        (
            "Low-range bikes",
            "Free-floating with ≤5 km left",
            _fmt_pct_with_count(
                metrics["pct_low_range"], metrics["low_range_bikes"]
            ),
            _fmt_delta(deltas.get("pct_low_range"), as_pp=True),
        ),
        (
            "Avg. distance to station",
            "Free-floating → nearest station",
            _fmt_distance_m(metrics.get("avg_dist_to_station_m")),
            _fmt_delta(deltas.get("avg_dist_to_station_m"), as_meters=True),
        ),
        (
            "Disabled bikes",
            "Docked + free-floating",
            _fmt_pct_with_count(
                metrics["pct_disabled_bikes"], metrics["disabled_bikes_total"]
            ),
            _fmt_delta(deltas.get("pct_disabled_bikes"), as_pp=True),
        ),
    ]

    balance = metrics.get("bikes_per_10_docks")
    balance_note = _fmt_vs_typical(
        metrics.get("bikes_per_10_docks_vs_typical"),
        metrics.get("timestamp"),
        int(metrics.get("bikes_per_10_docks_samples") or 0),
    )
    coverage_pct = float(metrics.get("pct_sf_coverage") or 0.0)
    coverage_delta = _fmt_delta(deltas.get("pct_sf_coverage"), as_pp=True)
    coverage_note = "vs prior hour" if coverage_delta else "no prior hour"
    st.markdown(
        f"""
        <div class="kpi-hero">
          <div class="kpi-hero-card">
            {_help_icon(
                "Rideable bikes (docked + free-floating) for every 10 open docks. "
                "Compared with the same hour over the past 4 weeks."
            )}
            <div class="kpi-hero-label">Bikes per 10 docks</div>
            <div class="kpi-value-row">
              <div class="kpi-hero-value">
                {f"{balance:.1f}" if balance is not None else "n/a"}
              </div>
            </div>
            <div class="kpi-hero-note">{balance_note}</div>
          </div>
          <div class="kpi-hero-card">
            {_help_icon("Area within 300 m (~3 min walk) of available bikes")}
            <div class="kpi-hero-label">Coverage (San Francisco)</div>
            <div class="kpi-value-row">
              <div class="kpi-hero-value">{coverage_pct:.1f}%</div>
              {coverage_delta}
            </div>
            <div class="kpi-hero-note">{coverage_note}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="kpi-section-label">Stations</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(station_cards), unsafe_allow_html=True)
    st.markdown('<div class="kpi-section-label">Bikes</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(bike_cards), unsafe_allow_html=True)
