"""
GBFS collection: the hourly snapshot, the reference data, the geofencing zones.

:func:`collect` opens one feed client, reads the clock once and runs the
selected paths against both. Each path is also public, taking an explicit
client and instant, which is how the tests pin the clock.

Everything is stamped in UTC. Local time is applied by :mod:`lastmile.db` on
the way out, so this module never learns the system's zone and DST never
reaches it. Feeds arrive already normalized to GBFS 3.0 by :mod:`lastmile.gbfs`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from . import geofencing
from .db import Db, rows_from_frame
from .db.schema import table
from .gbfs import SYSTEM_INFORMATION_FIELDS, GbfsClient

# Tracked table <- the client accessor that fills it, in reporting order.
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
    Run the selected paths, all three by default; results keyed by path name.

    A path that raises does not stop the others: its exception is returned under
    ``errors`` (always present, empty on a clean run) instead of a result, so a
    flaky reference feed never costs the hourly snapshot. Opening the client is
    the one shared step, and a failed discovery request still raises.

    Order is immaterial to what is stored: every path writes UTC instants. It
    only affects the local label ``snapshot`` reports, which is rendered in the
    lake's zone as of the refresh — and that zone is already set on any
    initialized lake.
    """
    client = client or GbfsClient()
    observed_at = observed_at or datetime.now(UTC)
    paths = (
        ("reference", reference, refresh_reference_data),
        ("geofencing", geofencing, refresh_geofencing),
        ("snapshot", snapshot, collect_snapshot),
    )
    results: dict = {"errors": {}}
    for name, selected, run in paths:
        if not selected:
            continue
        try:
            results[name] = run(conn, client, observed_at)
        except Exception as exc:
            results["errors"][name] = exc
    return results


def snapshot_hour(instant: datetime) -> datetime:
    """The UTC hour an instant falls in; the ``ts`` of every row in a snapshot."""
    return instant.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


# --- hourly snapshot --------------------------------------------------------


def collect_snapshot(conn: Db, client: GbfsClient, observed_at: datetime) -> dict:
    """
    Store one snapshot of every status feed, stamped with the UTC hour.

    Returns the hour as the lake's local key and the rows newly written per
    table: all zero when the hour was already stored.
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
    """Stamp a frame with the snapshot hour and store it; skips empty ones."""
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
    Re-read the tracked feeds, logging only what changed. See :meth:`Db.sync`.

    Re-resolves the lake's display zone afterwards, since ``system_information``
    is where the system's timezone arrives.
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
    Archive the zone collection as a GeoJSON document when it changed.

    An absent feed is a no-op; an empty collection is a real version and is
    recorded. See :mod:`lastmile.geofencing`.
    """
    data = client.geofencing_zones()
    written = data is not None and geofencing.record(
        conn.root, geofencing.document(data), observed_at
    )
    return {**geofencing.summary(conn.root), "captured": written}
