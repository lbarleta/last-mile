"""
Geofencing zones, archived as standalone GeoJSON documents.

Zones carry no ids in GBFS and their shapes drift, so there is nothing to track
entity by entity, and nothing reads this data live — it exists for later
analysis. So it is not a table at all: each capture is one ``.geojson`` file in
the lake, named for when it was taken, openable directly in QGIS or
``geopandas.read_file`` without this package.

    <lake>/geofencing_zones/20260101T080000.geojson
    <lake>/geofencing_zones/20260304T090000.geojson   <- newest file is current

A refresh writes a new file only when the feed's content differs from the
newest capture; an unchanged feed writes nothing, so the directory holds one
file per actual version. Geometry is kept exactly as published. The one
normalization is that features are sorted by their serialized form before
writing, so a publisher reshuffling the array — feature order carries no
meaning in GeoJSON — does not fake a new version.

Each file is the published FeatureCollection. GBFS 3.0's ``global_rules`` (the
rules applying outside every zone) ride along as a top-level ``global_rules``
member, which the GeoJSON spec permits as a foreign member and GIS tools
ignore.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

DIRECTORY = "geofencing_zones"
SUFFIX = ".geojson"
# Lexicographic order on the names is chronological order on the captures.
STAMP_FORMAT = "%Y%m%dT%H%M%S"


def capture_dir(root: str | Path) -> Path:
    return Path(root) / DIRECTORY


def captures(root: str | Path) -> list[Path]:
    """Every stored capture, oldest first; the last one is current."""
    directory = capture_dir(root)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{SUFFIX}"))


def latest(root: str | Path) -> Path | None:
    stored = captures(root)
    return stored[-1] if stored else None


def observed_at(path: Path) -> datetime:
    """When a capture was taken, read back from its filename."""
    return datetime.strptime(path.name.removesuffix(SUFFIX), STAMP_FORMAT)


def document(data: dict[str, Any]) -> dict[str, Any]:
    """
    The GeoJSON document to store, from a feed's published ``data`` payload.

    The FeatureCollection as published, its features sorted by serialized form,
    with any non-empty ``global_rules`` attached as a foreign member.
    """
    collection = dict(data.get("geofencing_zones") or {})
    collection.setdefault("type", "FeatureCollection")
    features = collection.get("features") or []
    collection["features"] = sorted(features, key=_canonical)
    if data.get("global_rules"):
        collection["global_rules"] = data["global_rules"]
    return collection


def record(root: str | Path, doc: dict[str, Any], when: datetime) -> bool:
    """
    Store a capture if its content differs from the current one.

    Returns whether a file was written. An empty collection is a capture like
    any other — including the first one. It is what lets the archive say "this
    system had no zones then" rather than "nobody looked", and what keeps an
    emptied collection from reading as if its old zones were still active. It
    stays a single file for as long as the feed stays empty, because identical
    content is never rewritten.
    """
    current = latest(root)
    content = _canonical(doc)
    if current is not None:
        if _canonical(json.loads(current.read_text(encoding="utf-8"))) == content:
            return False

    directory = capture_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{when.strftime(STAMP_FORMAT)}{SUFFIX}"
    temporary = path.with_name(path.name + ".tmp")
    # Compact on purpose: a big system's collection runs to megabytes, and
    # these files are for tools, which do not care about whitespace.
    temporary.write_text(content + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return True


def summary(root: str | Path) -> dict[str, Any]:
    """What the archive holds, for the CLI."""
    stored = captures(root)
    if not stored:
        return {"captures": 0, "features": 0, "observed_at": None}
    current = json.loads(stored[-1].read_text(encoding="utf-8"))
    return {
        "captures": len(stored),
        "features": len(current.get("features") or []),
        "observed_at": observed_at(stored[-1]),
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
