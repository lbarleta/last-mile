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
                grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
                gap: 0.65rem;
                margin-bottom: 0.75rem;
            }
            .kpi-card {
                border: 1px solid #d5d9de;
                border-radius: 8px;
                background: #ffffff;
                padding: 0.75rem 0.85rem;
                min-height: 4.5rem;
            }
            .kpi-label {
                font-size: 0.75rem;
                font-weight: 500;
                color: #5c636b;
                margin-bottom: 0.35rem;
            }
            .kpi-hint {
                font-size: 0.68rem;
                font-weight: 400;
                color: #9aa1a9;
                margin: 0.3rem 0 0 0;
                line-height: 1.25;
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
                justify-content: center;
                margin: 0 0 1rem 0;
            }
            .kpi-hero-card {
                border: 1px solid #d5d9de;
                border-radius: 10px;
                background: #ffffff;
                padding: 1rem 1.75rem;
                min-width: min(100%, 320px);
                text-align: center;
            }
            .kpi-hero-label {
                font-size: 0.85rem;
                font-weight: 600;
                letter-spacing: 0.03em;
                text-transform: uppercase;
                color: #5c636b;
                margin-bottom: 0.35rem;
            }
            .kpi-hero-value {
                font-size: 2rem;
                font-weight: 700;
                color: #1c1f24;
                line-height: 1.2;
            }
            .kpi-hero-hint {
                font-size: 0.72rem;
                color: #9aa1a9;
                margin-top: 0.35rem;
            }
            .kpi-hero .kpi-value-row {
                justify-content: center;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_pct_with_count(pct: float, count: int) -> str:
    return f'{pct:.1f}% <span class="kpi-count">({count:,})</span>'


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
        hint_html = f'<div class="kpi-hint">{hint}</div>' if hint else ""
        delta_html = delta or ""
        items.append(
            f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value-row"><div class="kpi-value">{value}</div>'
            f"{delta_html}</div>"
            f"{hint_html}</div>"
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

    coverage_pct = float(metrics.get("pct_sf_coverage") or 0.0)
    coverage_delta = _fmt_delta(deltas.get("pct_sf_coverage"), as_pp=True)
    st.markdown(
        f"""
        <div class="kpi-hero">
          <div class="kpi-hero-card">
            <div class="kpi-hero-label">Coverage (San Francisco)</div>
            <div class="kpi-value-row">
              <div class="kpi-hero-value">{coverage_pct:.1f}%</div>
              {coverage_delta}
            </div>
            <div class="kpi-hero-hint">Area within 300 m (~3 min walk) of available bikes</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="kpi-section-label">Stations</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(station_cards), unsafe_allow_html=True)
    st.markdown('<div class="kpi-section-label">Bikes</div>', unsafe_allow_html=True)
    st.markdown(_kpi_row(bike_cards), unsafe_allow_html=True)
