"""Walk-shed coverage of the city from available bikes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

from ..settings import get_settings

LatLon = tuple[float, float]

# Degrees of padding around the boundary bounds (~radius + margin) before projecting.
_BBOX_PAD_DEG = 0.01


@lru_cache(maxsize=4)
def _load_boundary(path_str: str) -> Any:
    """Load the configured city boundary GeoJSON (WGS84) as one geometry."""
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Boundary GeoJSON not found at {path}. "
            "Check boundary_geojson in lastmile.toml."
        )
    collection = json.loads(path.read_text(encoding="utf-8"))
    geoms = [shape(feat["geometry"]) for feat in collection.get("features", [])]
    if not geoms:
        raise ValueError(f"Boundary GeoJSON at {path} has no features")
    return unary_union(geoms)


def load_boundary() -> Any:
    return _load_boundary(str(get_settings().boundary_geojson_path))


@lru_cache(maxsize=4)
def _transformers(projected_crs: str) -> tuple[Transformer, Transformer]:
    to_proj = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    to_wgs = Transformer.from_crs(projected_crs, "EPSG:4326", always_xy=True)
    return to_proj, to_wgs


def _to_projected(geom: Any) -> Any:
    to_proj, _ = _transformers(get_settings().projected_crs)
    return transform(lambda x, y, z=None: to_proj.transform(x, y), geom)


def _to_wgs84(geom: Any) -> Any:
    _, to_wgs = _transformers(get_settings().projected_crs)
    return transform(lambda x, y, z=None: to_wgs.transform(x, y), geom)


def _collect_points(
    stations: pd.DataFrame,
    free_bikes: pd.DataFrame | None,
    bbox: tuple[float, float, float, float],
) -> list[LatLon]:
    minx, miny, maxx, maxy = bbox
    points: list[LatLon] = []

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


def compute_coverage(
    stations: pd.DataFrame,
    free_bikes: pd.DataFrame | None = None,
    *,
    radius_m: float | None = None,
) -> dict[str, Any]:
    """
    Share of the city's land within ``radius_m`` of an available bike.

    Sources: docked stations with bikes available, plus non-disabled
    free-floating bikes. ``radius_m`` defaults to the configured
    ``coverage_radius_m``.
    """
    if radius_m is None:
        radius_m = get_settings().coverage_radius_m
    boundary_wgs = load_boundary()
    boundary_proj = _to_projected(boundary_wgs)
    boundary_area = float(boundary_proj.area)
    empty = {
        "pct_coverage": 0.0,
        "covered_area_m2": 0.0,
        "boundary_area_m2": boundary_area,
        "n_sources": 0,
        "coverage_geojson": None,
    }
    if boundary_area <= 0:
        return empty

    minx, miny, maxx, maxy = boundary_wgs.bounds
    bbox = (
        minx - _BBOX_PAD_DEG,
        miny - _BBOX_PAD_DEG,
        maxx + _BBOX_PAD_DEG,
        maxy + _BBOX_PAD_DEG,
    )
    points = _collect_points(stations, free_bikes, bbox)
    if not points:
        return empty

    to_proj, _ = _transformers(get_settings().projected_crs)
    buffers = []
    for lat, lon in points:
        x, y = to_proj.transform(lon, lat)
        buffers.append(Point(x, y).buffer(radius_m, resolution=8))

    covered = unary_union(buffers).intersection(boundary_proj)
    covered_area = float(covered.area) if not covered.is_empty else 0.0
    pct = covered_area / boundary_area * 100.0

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
        "boundary_area_m2": boundary_area,
        "n_sources": len(points),
        "coverage_geojson": coverage_geojson,
    }
