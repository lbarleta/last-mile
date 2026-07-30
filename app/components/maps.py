"""Map helpers for stations and free-floating bikes (Folium)."""

from __future__ import annotations

from typing import List, Optional

import folium
import pandas as pd
import streamlit as st
from branca.element import Element, MacroElement, Template
from folium.plugins import HeatMap
from streamlit_folium import st_folium


STATUS_COLORS = {
    "empty": "#b42828",
    "low": "#dc8c28",
    "healthy": "#288c5a",
    "full": "#285ab4",
}

FREE_BIKE_COLOR = "#783cc0"
FREE_BIKE_DISABLED_COLOR = "#5a5a5a"

# Empty weighs more than low so true shortages dominate the surface.
HOTSPOT_WEIGHT = {"empty": 2.0, "low": 1.0}
HOTSPOT_GRADIENT = {
    0.2: "#fff7e6",
    0.4: "#fdc978",
    0.65: "#f07c3a",
    0.85: "#d9481c",
    1.0: "#9b1c1c",
}


class SidePanel(MacroElement):
    """Single elegant panel: layer toggles on top, legend below."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        (function() {
            var map = {{ this._parent.get_name() }};
            var stationLayer = {{ this.station_layer }};
            var bikeLayer = {{ this.bike_layer }};
            var hotspotLayer = {{ this.hotspot_layer }};
            var coverageLayer = {{ this.coverage_layer }};

            var panel = L.control({position: 'topright'});
            panel.onAdd = function() {
                var div = L.DomUtil.create('div', 'lm-side-panel');
                div.innerHTML = `
                  <div class="lm-panel-section">
                    <div class="lm-panel-heading">Data layers</div>
                    <label class="lm-layer-row">
                      <input type="checkbox" id="lm-toggle-stations" checked>
                      <span>Stations</span>
                    </label>
                    <label class="lm-layer-row">
                      <input type="checkbox" id="lm-toggle-bikes" checked>
                      <span>Free-floating bikes</span>
                    </label>
                  </div>
                  <div class="lm-panel-spacer"></div>
                  <div class="lm-panel-section">
                    <div class="lm-panel-heading">Analysis layers</div>
                    <label class="lm-layer-row">
                      <input type="checkbox" id="lm-toggle-coverage" checked>
                      <span>3-min Coverage</span>
                    </label>
                    <label class="lm-layer-row">
                      <input type="checkbox" id="lm-toggle-hotspots" checked>
                      <span>Empty/low hotspots</span>
                    </label>
                  </div>
                  <div class="lm-panel-divider"></div>
                  <div class="lm-panel-section">
                    <div class="lm-panel-heading">Legend</div>
                    <div class="lm-legend-row"><span class="lm-dot" style="background:#b42828;"></span>Empty</div>
                    <div class="lm-legend-row"><span class="lm-dot" style="background:#dc8c28;"></span>Low</div>
                    <div class="lm-legend-row"><span class="lm-dot" style="background:#288c5a;"></span>Healthy</div>
                    <div class="lm-legend-row"><span class="lm-dot" style="background:#285ab4;"></span>Full</div>
                    <div class="lm-legend-spacer"></div>
                    <div class="lm-legend-row"><span class="lm-tri"></span>Free-floating bike</div>
                    <div class="lm-legend-spacer"></div>
                    <div class="lm-legend-row">
                      <span class="lm-cover"></span>
                      3-min Coverage
                    </div>
                    <div class="lm-legend-row">
                      <span class="lm-heat"></span>
                      Empty/low density
                    </div>
                  </div>
                `;
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                return div;
            };
            panel.addTo(map);

            function bindToggle(id, layer, enabled) {
                var el = document.getElementById(id);
                if (!el || !layer) {
                    if (el) {
                        el.disabled = true;
                        el.checked = false;
                    }
                    return;
                }
                el.checked = enabled;
                el.addEventListener('change', function() {
                    if (el.checked) {
                        map.addLayer(layer);
                    } else {
                        map.removeLayer(layer);
                    }
                });
            }

            bindToggle('lm-toggle-coverage', coverageLayer, {{ this.show_coverage|tojson }});
            bindToggle('lm-toggle-stations', stationLayer, {{ this.show_stations|tojson }});
            bindToggle('lm-toggle-bikes', bikeLayer, {{ this.show_bikes|tojson }});
            bindToggle('lm-toggle-hotspots', hotspotLayer, {{ this.show_hotspots|tojson }});
        })();
        {% endmacro %}
        """
    )

    def __init__(
        self,
        station_layer: Optional[folium.FeatureGroup],
        bike_layer: Optional[folium.FeatureGroup],
        hotspot_layer: Optional[HeatMap] = None,
        coverage_layer: Optional[folium.FeatureGroup] = None,
    ):
        super().__init__()
        self.station_layer = (
            station_layer.get_name() if station_layer is not None else "null"
        )
        self.bike_layer = bike_layer.get_name() if bike_layer is not None else "null"
        self.hotspot_layer = (
            hotspot_layer.get_name() if hotspot_layer is not None else "null"
        )
        self.coverage_layer = (
            coverage_layer.get_name() if coverage_layer is not None else "null"
        )
        self.show_stations = station_layer is not None
        self.show_bikes = bike_layer is not None
        self.show_hotspots = hotspot_layer is not None
        self.show_coverage = coverage_layer is not None


PANEL_CSS = """
<style>
  .lm-side-panel {
    background: #ffffff;
    border: 1px solid #d8dde3;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(28, 31, 36, 0.08);
    padding: 12px 14px;
    min-width: 188px;
    max-width: 220px;
    color: #1c1f24;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 12.5px;
    line-height: 1.35;
    overflow: hidden;
  }
  .lm-panel-heading {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #6b7280;
    margin-bottom: 8px;
  }
  .lm-panel-section { margin: 0; }
  .lm-panel-spacer { height: 10px; }
  .lm-panel-divider {
    height: 1px;
    background: #e6eaee;
    margin: 10px 0;
  }
  .lm-layer-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 6px 0;
    cursor: pointer;
    font-weight: 500;
  }
  .lm-layer-row:last-child { margin-bottom: 0; }
  .lm-layer-row input {
    margin: 0;
    accent-color: #1f6f54;
  }
  .lm-legend-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 5px 0;
  }
  .lm-legend-row:last-child { margin-bottom: 0; }
  .lm-legend-spacer { height: 8px; }
  .lm-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
    flex: 0 0 10px;
  }
  .lm-tri {
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 11px solid #783cc0;
    display: inline-block;
    flex: 0 0 12px;
  }
  .lm-heat {
    width: 12px;
    height: 10px;
    border-radius: 2px;
    display: inline-block;
    flex: 0 0 12px;
    background: linear-gradient(90deg, #fdc978 0%, #f07c3a 50%, #9b1c1c 100%);
  }
  .lm-cover {
    width: 12px;
    height: 10px;
    border-radius: 2px;
    display: inline-block;
    flex: 0 0 12px;
    background: rgba(31, 111, 84, 0.45);
    border: 1px solid #1f6f54;
  }
  /* Hide default Leaflet attribution clutter in the iframe a bit less critical */
  .leaflet-control-layers { display: none !important; }
</style>
"""


def availability_bucket(row: pd.Series) -> str:
    if row["num_bikes_available"] == 0:
        return "empty"
    if row["num_docks_available"] == 0:
        return "full"
    capacity = row["num_bikes_available"] + row["num_docks_available"]
    if capacity > 0 and row["num_bikes_available"] / capacity < 0.2:
        return "low"
    return "healthy"


def _popup_html(tip_type: str, tip_status: str, tip_info: str) -> str:
    return f"<b>{tip_type}</b><br/>{tip_status}<br/>{tip_info}"


def _add_stations(layer: folium.FeatureGroup, stations: pd.DataFrame) -> None:
    df = stations.copy()
    df["status"] = df.apply(availability_bucket, axis=1)
    for _, row in df.iterrows():
        status = str(row["status"])
        tip_info = (
            f"{row.get('name', '')} · {row.get('region') or 'Unknown'} · "
            f"Bikes {int(row['num_bikes_available'])} · "
            f"Docks {int(row['num_docks_available'])} · "
            f"E-bikes {int(row['num_ebikes_available'])}"
        )
        folium.CircleMarker(
            location=[float(row["lat"]), float(row["lon"])],
            radius=6,
            color=STATUS_COLORS[status],
            fill=True,
            fill_color=STATUS_COLORS[status],
            fill_opacity=0.85,
            weight=1,
            popup=folium.Popup(
                _popup_html("Station", status.title(), tip_info),
                max_width=280,
            ),
            tooltip=f"Station · {status.title()}",
        ).add_to(layer)


def _hotspot_points(stations: pd.DataFrame) -> List[List[float]]:
    """Weighted [lat, lon, weight] points for empty/low stations."""
    points: List[List[float]] = []
    df = stations.copy()
    df["status"] = df.apply(availability_bucket, axis=1)
    for _, row in df.iterrows():
        status = str(row["status"])
        weight = HOTSPOT_WEIGHT.get(status)
        if weight is None:
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue
        points.append([lat, lon, weight])
    return points


def _add_hotspots(stations: pd.DataFrame) -> Optional[HeatMap]:
    points = _hotspot_points(stations)
    if not points:
        return None
    return HeatMap(
        points,
        name="Empty/low hotspots",
        min_opacity=0.25,
        radius=28,
        blur=22,
        max_zoom=14,
        gradient=HOTSPOT_GRADIENT,
    )


def _add_free_bikes(layer: folium.FeatureGroup, bikes: pd.DataFrame) -> None:
    df = bikes.copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])
    for _, row in df.iterrows():
        disabled = int(row.get("is_disabled") or 0)
        reserved = int(row.get("is_reserved") or 0)
        status = (
            "Disabled" if disabled else ("Reserved" if reserved else "Available")
        )
        color = FREE_BIKE_DISABLED_COLOR if disabled else FREE_BIKE_COLOR
        range_m = row.get("current_range_meters")
        range_txt = (
            f"{float(range_m) / 1000.0:.1f} km"
            if pd.notna(range_m)
            else "n/a"
        )
        tip_info = f"{row['bike_id']} · Range {range_txt}"
        folium.RegularPolygonMarker(
            location=[float(row["lat"]), float(row["lon"])],
            number_of_sides=3,
            rotation=30,
            radius=7,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            weight=1,
            popup=folium.Popup(
                _popup_html("Bike", status, tip_info),
                max_width=280,
            ),
            tooltip=f"Bike · {status}",
        ).add_to(layer)


def _add_coverage(
    layer: folium.FeatureGroup, coverage_geojson: dict
) -> None:
    folium.GeoJson(
        coverage_geojson,
        name="3-min Coverage",
        style_function=lambda _: {
            "fillColor": "#1f6f54",
            "color": "#1f6f54",
            "weight": 1,
            "fillOpacity": 0.28,
            "opacity": 0.65,
        },
        tooltip="Area within 300 m (~3 min walk) of an available bike",
    ).add_to(layer)


def render_ops_map(
    stations: pd.DataFrame,
    free_bikes: Optional[pd.DataFrame] = None,
    coverage_geojson: Optional[dict] = None,
) -> None:
    """Render stations and free-floating bikes with a combined side panel."""
    free_bikes = free_bikes if free_bikes is not None else pd.DataFrame()
    has_stations = not stations.empty
    has_bikes = not free_bikes.empty
    has_coverage = bool(coverage_geojson)

    if not has_stations and not has_bikes:
        st.info("No map data for this snapshot.")
        return

    if has_stations:
        mid_lat = float(stations["lat"].mean())
        mid_lon = float(stations["lon"].mean())
    else:
        mid_lat = float(pd.to_numeric(free_bikes["lat"], errors="coerce").mean())
        mid_lon = float(pd.to_numeric(free_bikes["lon"], errors="coerce").mean())

    fmap = folium.Map(
        location=[mid_lat, mid_lon],
        zoom_start=12,
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        "CartoDB positron",
        name="Basemap",
        control=False,
        attr="&copy; OpenStreetMap &copy; CartoDB",
    ).add_to(fmap)

    stations_layer = None
    bikes_layer = None
    hotspot_layer = None
    coverage_layer = None

    if has_coverage:
        coverage_layer = folium.FeatureGroup(name="3-min Coverage", show=True)
        _add_coverage(coverage_layer, coverage_geojson)
        coverage_layer.add_to(fmap)

    if has_stations:
        hotspot_layer = _add_hotspots(stations)
        if hotspot_layer is not None:
            hotspot_layer.add_to(fmap)

        stations_layer = folium.FeatureGroup(name="Stations", show=True)
        _add_stations(stations_layer, stations)
        stations_layer.add_to(fmap)

    if has_bikes:
        bikes_layer = folium.FeatureGroup(name="Free-floating bikes", show=True)
        _add_free_bikes(bikes_layer, free_bikes)
        bikes_layer.add_to(fmap)

    fmap.get_root().header.add_child(Element(PANEL_CSS))
    fmap.add_child(
        SidePanel(stations_layer, bikes_layer, hotspot_layer, coverage_layer)
    )

    st_folium(fmap, width="100%", height=560, returned_objects=[])


def render_station_map(stations: pd.DataFrame) -> None:
    """Backward-compatible wrapper."""
    render_ops_map(stations, free_bikes=None)
