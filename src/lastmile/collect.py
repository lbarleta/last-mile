"""
Hourly GBFS collection, plus the slow-changing reference data.

Two rhythms. The status feeds are snapshotted every hour and appended, bucketed
to the local hour of the *system being collected*, not the host's, and merged
against the ``(entity, ts)`` key — so re-running the collector inside the same
hour adds nothing rather than a duplicate. The hour repeats once a year when DST
falls back; the key means the second reading is skipped.

Everything else — stations, vehicle types, pricing plans, regions, alerts —
changes a few times a year, so it is stored as current state plus a log of
changes rather than an hourly copy. See :meth:`lastmile.db.Db.sync`.

The feed's own shape is :mod:`lastmile.gbfs`'s problem; everything arriving here
is already normalized to GBFS 3.0. Functions return row counts and leave
printing to the CLI.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import geofencing
from .constants import TIMESTAMP_FORMAT
from .db import Db, rows_from_frame
from .db.queries import stored_timezone
from .db.schema import HOURLY_TABLES, create_all, table
from .gbfs import SYSTEM_INFORMATION_FIELDS, GbfsClient
from .settings import get_settings

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

# Used only when neither the configuration nor the feed names a timezone, which
# would otherwise leave the snapshot hour undefined.
FALLBACK_TIMEZONE = "UTC"


def resolve_timezone(conn: Db | None = None, client: GbfsClient | None = None) -> str:
    """
    The zone snapshot hours are bucketed in.

    Configuration wins, because an operator may deliberately want a different
    one. Otherwise the system's own ``system_information.timezone`` is used,
    read from the warehouse when it has been collected and from the live feed
    when a client is at hand. Collecting Austin against a Los Angeles default
    would silently file every snapshot two hours early.
    """
    configured = get_settings().timezone.strip()
    if configured:
        return configured
    if client is not None and client.timezone:
        return client.timezone
    if conn is not None:
        stored = stored_timezone(conn)
        if stored:
            return stored
    return FALLBACK_TIMEZONE


def snapshot_hour(timezone: str) -> datetime:
    """The current local hour, naive, as stored in the ``ts`` columns."""
    now = datetime.now(ZoneInfo(timezone))
    return now.replace(minute=0, second=0, microsecond=0, tzinfo=None)


# --- hourly snapshot --------------------------------------------------------


def collect_snapshot(conn: Db, client: GbfsClient | None = None) -> dict:
    """
    Fetch and store one snapshot of every status feed.

    Returns the hour and the rows newly written per table — zero everywhere if
    the hour was already stored.
    """
    client = client or GbfsClient()
    ts = snapshot_hour(resolve_timezone(conn, client))
    status = client.station_status()
    frames = {
        "station_status": status.stations,
        "station_vehicle_types_available": status.vehicle_types_available,
        "station_vehicle_docks_available": status.vehicle_docks_available,
        "vehicle_status": client.vehicle_status(),
    }
    written = {name: _append(conn, name, frame, ts) for name, frame in frames.items()}
    return {"timestamp": ts.strftime(TIMESTAMP_FORMAT), "rows": written}


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
    conn: Db, client: GbfsClient, observed_at: datetime | None = None
) -> dict[str, dict[str, int]]:
    """
    Re-read everything that changes more slowly than the status feeds.

    Each tracked table keeps its current state and gains a log row only where
    something actually differs, and the geofencing collection only writes when
    its content changed — so running this hourly costs nothing when nothing did.
    """
    observed_at = observed_at or datetime.now()
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
    results["geofencing_zones"] = refresh_geofencing(conn, client, observed_at)
    return results


def refresh_geofencing(conn: Db, client: GbfsClient, observed_at: datetime) -> dict:
    """
    Archive the geofencing collection as a GeoJSON document when it changed.

    Zones have no ids in GBFS, so nothing is tracked entity by entity: each
    version of the whole collection is one standalone ``.geojson`` file in the
    lake, and the newest file is current. An absent feed is a no-op; a
    present-but-empty collection is authoritative — a system that deleted all
    its zones really has none, and recording that is a version like any other.
    See :mod:`lastmile.geofencing`.
    """
    data = client.geofencing_zones()
    written = data is not None and geofencing.record(
        conn.root, geofencing.document(data), observed_at
    )
    return {**geofencing.summary(conn.root), "captured": written}


def init_db(conn: Db, client: GbfsClient | None = None) -> dict:
    """Lay out the lake and load reference data. Safe to run repeatedly."""
    create_all(conn)
    client = client or GbfsClient()
    return refresh_reference_data(conn, client)


def is_initialized(conn: Db) -> bool:
    """
    True when the datasets exist and reference data has been loaded.

    ``system_information`` is the signal rather than the station tables, because
    an entirely free-floating system legitimately has none of those.
    """
    for name in ("system_information", *HOURLY_TABLES):
        if not conn.has_table(name):
            return False
    return conn.count("system_information") > 0
