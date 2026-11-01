"""
The warehouse schema, declared once as data.

Tables are named for the GBFS 3.0 feeds they hold, and columns for the fields
in them. Where 2.3 and 3.0 disagree the 3.0 spelling wins; the feed client
translates. Columns that are not in the spec are marked where they appear.

Every table is a directory of Parquet files under the lake root, read through a
DuckDB view. There is no server and no catalog file: the lake *is* the database.

    <lake>/station_status/_schema.parquet   zero rows, fixes the column types
    <lake>/station_status/2026-10-29.parquet
    <lake>/station_information/data.parquet
    <lake>/station_information_log/data.parquet

Two kinds of feed, two shapes:

* **Snapshotted** — the live status feeds (``station_status``,
  ``vehicle_status`` and the two per-vehicle-type breakdowns). Appended once per
  collection run, partitioned one file per local calendar day, so a run only
  rewrites today's file.
* **Tracked** — the slow feeds whose entities carry stable ids: stations,
  vehicle types, pricing plans, regions, alerts. Storing a copy per run would
  be almost entirely duplicate rows, so each keeps its *current* state in one
  file plus a companion ``<name>_log`` holding one row each time an entity is
  added, changed or removed. The log tables are generated from the ``tracked``
  flag below, not declared by hand.

Two things live in the lake but not in a table. ``geofencing_zones`` — the one
slow feed whose entities have no ids — is archived as standalone GeoJSON
documents, one file per version of the whole collection; see
:mod:`lastmile.geofencing`. And ``weather`` below is a declared placeholder for
a module that is not implemented; nothing writes to it.

``key`` is the logical primary key. Parquet enforces nothing, so
:class:`lastmile.db.Db` applies it on write: ``insert_ignore`` drops incoming
rows whose key is already stored, ``upsert`` replaces them, ``sync`` does the
tracked-table comparison. Collection is idempotent because of that, including
the repeated hour at the DST fall-back.

The ``_schema.parquet`` seed matters more than it looks. Globbing an empty
directory is an error in DuckDB, and the column types of a view over Parquet
come from the files it reads, so a table with no data yet would otherwise have
neither. The seed carries the full typed header in zero rows; every data file is
written with these same columns, in this order, missing ones cast to NULL.

Types are DuckDB's. ``ts`` columns are real TIMESTAMPs — naive, holding local
time for the system being collected. Identifiers are VARCHAR: they are opaque
strings in GBFS, and publishers use both short counters and UUIDs. GBFS arrays
of scalars (``rental_methods``, ``pricing_plan_ids``) are stored comma-joined,
and arrays of objects with no useful flattening (``per_min_pricing``) as JSON
text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle, types only
    from . import Db

# Appended to a tracked table's name to make its change log.
LOG_SUFFIX = "_log"
# Values of the log's ``change`` column.
ADDED, CHANGED, REMOVED = "added", "changed", "removed"


@dataclass(frozen=True)
class Table:
    """One Parquet dataset: its columns, logical key, and how it keeps history."""

    name: str
    columns: tuple[tuple[str, str], ...]
    key: tuple[str, ...] = ()
    # Timestamp column whose calendar date names the file. None keeps the table
    # in a single data.parquet.
    partition_by: str | None = None
    # Keep a companion <name>_log recording every add, change and removal.
    tracked: bool = False

    def __post_init__(self) -> None:
        declared = self.types
        for column in (*self.key, *filter(None, [self.partition_by])):
            if column not in declared:
                raise ValueError(f"{self.name} has no column {column!r}")
        if self.partition_by and self.key and self.partition_by not in self.key:
            # Keys are applied one file at a time. If a row could change file
            # by having its partition column updated, the old copy would stay
            # behind in the file the merge never opened.
            raise ValueError(
                f"{self.name} is partitioned on {self.partition_by}, which must "
                "be part of its key"
            )
        if self.tracked and not self.key:
            raise ValueError(f"{self.name} cannot be tracked without a key")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.columns)

    @property
    def types(self) -> dict[str, str]:
        return dict(self.columns)

    @property
    def value_columns(self) -> tuple[str, ...]:
        """Columns outside the key — the ones a change is detected on."""
        return tuple(name for name in self.column_names if name not in self.key)

    @property
    def log_name(self) -> str:
        return f"{self.name}{LOG_SUFFIX}"


def log_table(spec: Table) -> Table:
    """
    The change log companion for a tracked table.

    Same columns, plus when the change was seen and what kind it was. An
    ``added`` or ``changed`` row holds the new values; a ``removed`` row holds
    the last values seen before the entity left the feed, so the log can be
    read without the current-state file.
    """
    return Table(
        f"{spec.name}{LOG_SUFFIX}",
        (
            *spec.columns,
            ("observed_at", "TIMESTAMP"),
            ("change", "VARCHAR"),
        ),
        key=(*spec.key, "observed_at"),
    )


# --- declarations ----------------------------------------------------------

_DECLARED: tuple[Table, ...] = (
    # --- system ------------------------------------------------------------
    # gbfs_version and feeds_url are not spec fields: they record which feed
    # this lake was filled from, which nothing else would tell you afterwards.
    Table(
        "system_information",
        (
            ("system_id", "VARCHAR"),
            ("name", "VARCHAR"),
            ("short_name", "VARCHAR"),
            ("operator", "VARCHAR"),
            ("opening_hours", "VARCHAR"),
            ("start_date", "VARCHAR"),
            ("termination_date", "VARCHAR"),
            ("url", "VARCHAR"),
            ("purchase_url", "VARCHAR"),
            ("phone_number", "VARCHAR"),
            ("email", "VARCHAR"),
            ("feed_contact_email", "VARCHAR"),
            ("timezone", "VARCHAR"),
            ("languages", "VARCHAR"),
            ("license_id", "VARCHAR"),
            ("license_url", "VARCHAR"),
            ("attribution_organization_name", "VARCHAR"),
            ("attribution_url", "VARCHAR"),
            ("terms_url", "VARCHAR"),
            ("terms_last_updated", "VARCHAR"),
            ("privacy_url", "VARCHAR"),
            ("privacy_last_updated", "VARCHAR"),
            ("gbfs_version", "VARCHAR"),
            ("feeds_url", "VARCHAR"),
        ),
        key=("system_id",),
        tracked=True,
    ),
    Table(
        "gbfs_versions",
        (("version", "VARCHAR"), ("url", "VARCHAR")),
        key=("version",),
        tracked=True,
    ),
    Table(
        "system_regions",
        (("region_id", "VARCHAR"), ("name", "VARCHAR")),
        key=("region_id",),
        tracked=True,
    ),
    Table(
        "system_pricing_plans",
        (
            ("plan_id", "VARCHAR"),
            ("name", "VARCHAR"),
            ("currency", "VARCHAR"),
            ("price", "DOUBLE"),
            ("is_taxable", "TINYINT"),
            ("description", "VARCHAR"),
            ("url", "VARCHAR"),
            ("surge_pricing", "TINYINT"),
            # Arrays of {start, rate, interval, end}; kept as published.
            ("per_km_pricing", "VARCHAR"),
            ("per_min_pricing", "VARCHAR"),
        ),
        key=("plan_id",),
        tracked=True,
    ),
    Table(
        "system_alerts",
        (
            ("alert_id", "VARCHAR"),
            ("type", "VARCHAR"),
            ("summary", "VARCHAR"),
            ("description", "VARCHAR"),
            ("url", "VARCHAR"),
            ("station_ids", "VARCHAR"),
            ("region_ids", "VARCHAR"),
            # Array of {start, end} windows the alert applies to.
            ("times", "VARCHAR"),
            ("last_updated", "BIGINT"),
        ),
        key=("alert_id",),
        tracked=True,
    ),
    Table(
        "vehicle_types",
        (
            ("vehicle_type_id", "VARCHAR"),
            ("form_factor", "VARCHAR"),
            ("propulsion_type", "VARCHAR"),
            ("name", "VARCHAR"),
            ("description", "VARCHAR"),
            ("make", "VARCHAR"),
            ("model", "VARCHAR"),
            ("color", "VARCHAR"),
            ("wheel_count", "INTEGER"),
            ("max_permitted_speed", "INTEGER"),
            ("rated_power", "INTEGER"),
            ("max_range_meters", "DOUBLE"),
            ("rider_capacity", "INTEGER"),
            ("cargo_volume_capacity", "INTEGER"),
            ("cargo_load_capacity", "INTEGER"),
            ("default_reserve_time", "INTEGER"),
            ("return_constraint", "VARCHAR"),
            ("g_co2_km", "INTEGER"),
            ("default_pricing_plan_id", "VARCHAR"),
            ("pricing_plan_ids", "VARCHAR"),
        ),
        key=("vehicle_type_id",),
        tracked=True,
    ),
    # --- stations ----------------------------------------------------------
    Table(
        "station_information",
        (
            ("station_id", "VARCHAR"),
            ("name", "VARCHAR"),
            ("short_name", "VARCHAR"),
            ("lat", "DOUBLE"),
            ("lon", "DOUBLE"),
            ("address", "VARCHAR"),
            ("cross_street", "VARCHAR"),
            ("post_code", "VARCHAR"),
            ("region_id", "VARCHAR"),
            ("capacity", "INTEGER"),
            ("is_virtual_station", "TINYINT"),
            ("is_valet_station", "TINYINT"),
            ("is_charging_station", "TINYINT"),
            ("parking_type", "VARCHAR"),
            ("parking_hoop", "TINYINT"),
            ("contact_phone", "VARCHAR"),
            ("station_opening_hours", "VARCHAR"),
            ("rental_methods", "VARCHAR"),
            ("rental_uris_android", "VARCHAR"),
            ("rental_uris_ios", "VARCHAR"),
            ("rental_uris_web", "VARCHAR"),
            # GeoJSON MultiPolygon for a virtual station, as published.
            ("station_area", "VARCHAR"),
        ),
        key=("station_id",),
        tracked=True,
    ),
    Table(
        "station_status",
        (
            ("station_id", "VARCHAR"),
            ("ts", "TIMESTAMP"),
            ("num_vehicles_available", "INTEGER"),
            ("num_vehicles_disabled", "INTEGER"),
            ("num_docks_available", "INTEGER"),
            ("num_docks_disabled", "INTEGER"),
            ("is_installed", "TINYINT"),
            ("is_renting", "TINYINT"),
            ("is_returning", "TINYINT"),
            # Epoch seconds. GBFS 3 publishes RFC 3339; the client normalizes.
            ("last_reported", "BIGINT"),
        ),
        key=("station_id", "ts"),
        partition_by="ts",
    ),
    # station_status.vehicle_types_available, one row per type instead of a
    # nested array. This is where an electric-vehicle count comes from: join it
    # to vehicle_types.propulsion_type.
    Table(
        "station_vehicle_types_available",
        (
            ("station_id", "VARCHAR"),
            ("ts", "TIMESTAMP"),
            ("vehicle_type_id", "VARCHAR"),
            ("count", "INTEGER"),
        ),
        key=("station_id", "ts", "vehicle_type_id"),
        partition_by="ts",
    ),
    # station_status.vehicle_docks_available. Each entry is a count of docks
    # accepting a *set* of types, so the set is the key: its ids sorted and
    # comma-joined, which keeps it stable between snapshots.
    Table(
        "station_vehicle_docks_available",
        (
            ("station_id", "VARCHAR"),
            ("ts", "TIMESTAMP"),
            ("vehicle_type_ids", "VARCHAR"),
            ("count", "INTEGER"),
        ),
        key=("station_id", "ts", "vehicle_type_ids"),
        partition_by="ts",
    ),
    # --- free-floating vehicles --------------------------------------------
    Table(
        "vehicle_status",
        (
            ("vehicle_id", "VARCHAR"),
            ("ts", "TIMESTAMP"),
            ("lat", "DOUBLE"),
            ("lon", "DOUBLE"),
            ("is_reserved", "TINYINT"),
            ("is_disabled", "TINYINT"),
            ("vehicle_type_id", "VARCHAR"),
            ("current_range_meters", "DOUBLE"),
            ("current_fuel_percent", "DOUBLE"),
            ("station_id", "VARCHAR"),
            ("home_station_id", "VARCHAR"),
            ("pricing_plan_id", "VARCHAR"),
            ("vehicle_equipment", "VARCHAR"),
            ("available_until", "VARCHAR"),
            ("last_reported", "BIGINT"),
        ),
        key=("vehicle_id", "ts"),
        partition_by="ts",
    ),
    # --- not GBFS ----------------------------------------------------------
    # Placeholder for the weather cache, which is not implemented. The table is
    # declared so the shape is settled; nothing writes to it.
    Table(
        "weather",
        (
            ("ts", "TIMESTAMP"),
            ("temp_c", "DOUBLE"),
            ("precip_mm", "DOUBLE"),
            ("wind_kph", "DOUBLE"),
            ("humidity_pct", "DOUBLE"),
            ("cloud_pct", "DOUBLE"),
            ("source", "VARCHAR"),
            ("fetched_at", "VARCHAR"),
        ),
        key=("ts",),
    ),
)


def _expand(declared: tuple[Table, ...]) -> tuple[Table, ...]:
    """Each declaration, followed by its change log where it has one."""
    tables: list[Table] = []
    for spec in declared:
        tables.append(spec)
        if spec.tracked:
            tables.append(log_table(spec))
    return tuple(tables)


TABLES: tuple[Table, ...] = _expand(_DECLARED)
BY_NAME: dict[str, Table] = {t.name: t for t in TABLES}
TABLE_NAMES: tuple[str, ...] = tuple(BY_NAME)

#: Tables fed by a GBFS feed that changes slowly, each with a ``_log``.
TRACKED_TABLES: tuple[str, ...] = tuple(t.name for t in _DECLARED if t.tracked)
#: Tables holding one row per entity per snapshot hour.
HOURLY_TABLES: tuple[str, ...] = tuple(
    t.name for t in _DECLARED if t.partition_by is not None
)


def table(name: str) -> Table:
    """The declaration for a table, or raise naming the ones that exist."""
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown table {name!r}; declared tables are {', '.join(TABLE_NAMES)}"
        ) from None


def create_all(db: Db, names: tuple[str, ...] = TABLE_NAMES) -> None:
    """Lay out the dataset directories and their typed seeds. Idempotent."""
    for name in names:
        db.ensure_table(name)


def missing_tables(db: Db) -> list[str]:
    """Tables the schema declares that the lake does not hold yet."""
    return [name for name in TABLE_NAMES if not db.has_table(name)]
