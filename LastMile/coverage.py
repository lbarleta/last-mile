"""Walk-shed coverage of San Francisco from available bikes."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

from .config import (
    COVERAGE_RADIUS_M,
    SF_BOUNDARY_GEOJSON_URL,
    SF_PROJECTED_CRS,
)

LatLon = Tuple[float, float]

# Degrees of padding around SF bounds (~radius + margin) before projecting.
_BBOX_PAD_DEG = 0.01


@lru_cache(maxsize=1)
def load_sf_boundary() -> Any:
    """Load San Francisco city boundary as a shapely geometry (WGS84)."""
    resp = requests.get(SF_BOUNDARY_GEOJSON_URL, timeout=30)
    resp.raise_for_status()
    collection = resp.json()
    geoms = [shape(feat["geometry"]) for feat in collection["features"]]
    if not geoms:
        raise ValueError("SF boundary GeoJSON has no features")
    return unary_union(geoms)


@lru_cache(maxsize=1)
def _transformers() -> Tuple[Transformer, Transformer]:
    to_proj = Transformer.from_crs("EPSG:4326", SF_PROJECTED_CRS, always_xy=True)
    to_wgs = Transformer.from_crs(SF_PROJECTED_CRS, "EPSG:4326", always_xy=True)
    return to_proj, to_wgs


def _to_projected(geom: Any) -> Any:
    to_proj, _ = _transformers()
    return transform(lambda x, y, z=None: to_proj.transform(x, y), geom)


def _to_wgs84(geom: Any) -> Any:
    _, to_wgs = _transformers()
    return transform(lambda x, y, z=None: to_wgs.transform(x, y), geom)


def _collect_points(
    stations: pd.DataFrame,
    free_bikes: Optional[pd.DataFrame],
    bbox: Tuple[float, float, float, float],
) -> List[LatLon]:
    minx, miny, maxx, maxy = bbox
    points: List[LatLon] = []

    if stations is not None and not stations.empty:
        with_bikes = stations[stations["num_bikes_available"] > 0].copy()
        with_bikes["lat"] = pd.to_numeric(with_bikes["lat"], errors="coerce")
        with_bikes["lon"] = pd.to_numeric(with_bikes["lon"], errors="coerce")
        with_bikes = with_bikes.dropna(subset=["lat", "lon"])
        with_bikes = with_bikes[
            (with_bikes["lon"] >= minx)
            & (with_bikes["lon"] <= maxx)
            & (with_bikes["lat"] >= miny)
            & (with_bikes["lat"] <= maxy)
        ]
        points.extend(
            (float(r.lat), float(r.lon)) for r in with_bikes.itertuples(index=False)
        )

    if free_bikes is not None and not free_bikes.empty:
        bikes = free_bikes.copy()
        bikes["lat"] = pd.to_numeric(bikes["lat"], errors="coerce")
        bikes["lon"] = pd.to_numeric(bikes["lon"], errors="coerce")
        if "is_disabled" in bikes.columns:
            bikes = bikes[bikes["is_disabled"].fillna(0).astype(int) == 0]
        bikes = bikes.dropna(subset=["lat", "lon"])
        bikes = bikes[
            (bikes["lon"] >= minx)
            & (bikes["lon"] <= maxx)
            & (bikes["lat"] >= miny)
            & (bikes["lat"] <= maxy)
        ]
        points.extend(
            (float(r.lat), float(r.lon)) for r in bikes.itertuples(index=False)
        )
    return points


def compute_sf_coverage(
    stations: pd.DataFrame,
    free_bikes: Optional[pd.DataFrame] = None,
    *,
    radius_m: float = COVERAGE_RADIUS_M,
) -> Dict[str, Any]:
    """
    Share of San Francisco land within ``radius_m`` of an available bike.

    Sources: docked stations with bikes available, plus non-disabled free-floating bikes.
    """
    sf_wgs = load_sf_boundary()
    sf_proj = _to_projected(sf_wgs)
    sf_area = float(sf_proj.area)
    empty = {
        "pct_coverage": 0.0,
        "covered_area_m2": 0.0,
        "sf_area_m2": sf_area,
        "n_sources": 0,
        "coverage_geojson": None,
    }
    if sf_area <= 0:
        return empty

    minx, miny, maxx, maxy = sf_wgs.bounds
    bbox = (
        minx - _BBOX_PAD_DEG,
        miny - _BBOX_PAD_DEG,
        maxx + _BBOX_PAD_DEG,
        maxy + _BBOX_PAD_DEG,
    )
    points = _collect_points(stations, free_bikes, bbox)
    if not points:
        return empty

    to_proj, _ = _transformers()
    buffers = []
    for lat, lon in points:
        x, y = to_proj.transform(lon, lat)
        buffers.append(Point(x, y).buffer(radius_m, resolution=8))

    covered = unary_union(buffers).intersection(sf_proj)
    covered_area = float(covered.area) if not covered.is_empty else 0.0
    pct = covered_area / sf_area * 100.0

    coverage_geojson = None
    if covered_area > 0 and not covered.is_empty:
        coverage_geojson = {
            "type": "Feature",
            "properties": {
                "pct_coverage": round(pct, 2),
                "radius_m": radius_m,
            },
            "geometry": mapping(_to_wgs84(covered)),
        }

    return {
        "pct_coverage": pct,
        "covered_area_m2": covered_area,
        "sf_area_m2": sf_area,
        "n_sources": len(points),
        "coverage_geojson": coverage_geojson,
    }
