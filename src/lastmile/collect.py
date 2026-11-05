"""
GBFS collection: the hourly snapshot, the reference data, the geofencing zones.

:func:`collect` is the entry point. It opens one feed client, reads the clock
once, and runs whichever of the three paths are selected against both, so a
run's paths share one discovery request and one ``observed_at``:

* :func:`collect_snapshot` — the status feeds, appended every hour, stamped
  with the current UTC hour and merged against the ``(entity, ts)`` key — so
  re-running the collector inside the same hour adds nothing rather than a
  duplicate.
* :func:`refresh_reference_data` — stations, vehicle types, pricing plans,
  regions, alerts. They change a few times a year, so each is stored as current
  state plus a log of changes rather than an hourly copy. See
  :meth:`lastmile.db.Db.sync`.
* :func:`refresh_geofencing` — the zone collection, archived as a GeoJSON
  document whenever it changed. See :mod:`lastmile.geofencing`.

The paths are public so they can be driven one at a time with an explicit
client and instant, which is how the tests pin the clock.

Nothing here knows what timezone the collected system is in, and that is the
point. GBFS publishes every timestamp as RFC 3339, an instant with an explicit
offset, and the lake does the same: ``ts`` is the instant the snapshot was
taken, truncated to the hour. Local time is a rendering concern, handled by
:mod:`lastmile.db` when a value is read. It also means DST never reaches this
module — UTC has none, so the hour that repeats or vanishes on the local clock
is just another hour here, and both fall-back readings are stored.

The feed's own shape is :mod:`lastmile.gbfs`'s problem; everything arriving here
is already normalized to GBFS 3.0. Functions return row counts and leave
printing to the CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from . import geofencing
from .db import Db, rows_from_frame
from .db.schema import table
from .gbfs import SYSTEM_INFORMATION_FIELDS, GbfsClient

# Tracked table <- the client accessor that fills it. Order matters only for
# how the CLI reports it.
REFERENCE_FEEDS = {
    "gbfs_versions": "gbfs_versions",
    "system_regions": "system_regions",
    "system_pricing_plans": "system_pricing_plans",
    "system_alerts": "system_alerts",
    "vehicle_types": "vehicle_types",
    "station_information": "station_information",
}


def collect(
    conn: Db,
    *,
    snapshot: bool = True,
    reference: bool = True,
    geofencing: bool = True,
    client: GbfsClient | None = None,
    observed_at: datetime | None = None,
) -> dict:
    """
    Run the selected collection paths; all three by default.

    Reference data goes first, so a timezone it brings is the one the snapshot
    hour is reported in. Returns each selected path's result under its own name
    — ``reference``, ``geofencing``, ``snapshot`` — and nothing for the others.
    ``client`` defaults to the configured feed and ``observed_at`` to now.
    """
    client = client or GbfsClient()
    observed_at = observed_at or datetime.now(UTC)
    results = {}
    if reference:
        results["reference"] = refresh_reference_data(conn, client, observed_at)
    if geofencing:
        results["geofencing"] = refresh_geofencing(conn, client, observed_at)
    if snapshot:
        results["snapshot"] = collect_snapshot(conn, client, observed_at)
    return results


def snapshot_hour(instant: datetime) -> datetime:
    """The UTC hour an instant falls in: the ``ts`` every row of one snapshot carries."""
    return instant.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


# --- hourly snapshot --------------------------------------------------------


def collect_snapshot(conn: Db, client: GbfsClient, observed_at: datetime) -> dict:
    """
    Fetch and store one snapshot of every status feed.

    Every row is stamped with :func:`snapshot_hour` of ``observed_at``. Returns
    that hour, as the lake's local ``YYYY-MM-DD-HH:00`` key, and the rows newly
    written per table — zero everywhere if the hour was already stored.
    """
    ts = snapshot_hour(observed_at)
    status = client.station_status()
    frames = {
        "station_status": status.stations,
        "station_vehicle_types_available": status.vehicle_types_available,
        "station_vehicle_docks_available": status.vehicle_docks_available,
        "vehicle_status": client.vehicle_status(),
    }
    written = {name: _append(conn, name, frame, ts) for name, frame in frames.items()}
    return {"timestamp": conn.to_key(ts), "rows": written}


def _append(conn: Db, name: str, frame: pd.DataFrame, ts: datetime) -> int:
    """Stamp a normalized frame with the snapshot hour and store it."""
    columns = table(name).column_names
    if frame.empty:
        return 0
    return conn.insert_ignore(
        name, columns, rows_from_frame(frame.assign(ts=ts), columns)
    )


# --- reference data ---------------------------------------------------------


def refresh_reference_data(
    conn: Db, client: GbfsClient, observed_at: datetime
) -> dict[str, dict[str, int]]:
    """
    Re-read the tracked feeds, logging whatever changed.

    Each tracked table keeps its current state and gains a log row only where
    something actually differs, so running this hourly costs nothing when
    nothing did. The lake's display zone is re-resolved afterwards, since this
    is where a system's timezone arrives.
    """
    system = client.system_information()
    fields = [field.name for field in SYSTEM_INFORMATION_FIELDS]
    results = {
        "system_information": conn.sync(
            "system_information",
            (*fields, "gbfs_version", "feeds_url"),
            [tuple(system.get(name) for name in (*fields, "gbfs_version", "feeds_url"))]
            if system.get("system_id")
            else [],
            observed_at,
        )
    }
    for name, accessor in REFERENCE_FEEDS.items():
        frame = getattr(client, accessor)()
        columns = table(name).column_names
        results[name] = conn.sync(
            name, columns, rows_from_frame(frame, columns), observed_at
        )
    conn.refresh_timezone()
    return results


# --- geofencing -------------------------------------------------------------


def refresh_geofencing(conn: Db, client: GbfsClient, observed_at: datetime) -> dict:
    """
    Archive the geofencing collection as a GeoJSON document when it changed.

    Zones have no ids in GBFS, so nothing is tracked entity by entity: each
    version of the whole collection is one standalone ``.geojson`` file in the
    lake, and the newest file is current. An absent feed is a no-op; a
    present-but-empty collection is authoritative — a system that deleted all
    its zones really has none, and recording that is a version like any other.
    """
    data = client.geofencing_zones()
    written = data is not None and geofencing.record(
        conn.root, geofencing.document(data), observed_at
    )
    return {**geofencing.summary(conn.root), "captured": written}
