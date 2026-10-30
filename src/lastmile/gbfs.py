"""
GBFS feed client, speaking 3.0 and reading 2.3.

The spec is the thing that changes, not the publisher. GBFS 3.0 renamed feeds
and fields, dropped the language envelope, localized free text and moved every
timestamp to RFC 3339. This module absorbs all of that and hands the rest of the
package the 3.0 shape, under 3.0 names:

* **Discovery.** 2.x nests feeds under a language (``data.en.feeds``); 3.x has a
  single ``data.feeds``. The version is read from the document when present and
  inferred from that shape when it is not — Austin's 2.3 ``gbfs.json`` omits it.
* **Feed names.** ``free_bike_status`` became ``vehicle_status``; a 2.x feed is
  found under its old name automatically.
* **Field names.** ``num_bikes_available`` became ``num_vehicles_available``,
  ``bike_id`` became ``vehicle_id``, and so on. Each field is read as "the first
  of these names the feed has", which works on either version without
  branching, and is written out under the 3.0 name.
* **Localized text.** 3.x publishes ``name`` and ``description`` as
  ``[{text, language}]`` arrays; 2.x publishes plain strings. Both collapse to
  one string in the configured language.
* **Timestamps.** ``last_reported`` is POSIX seconds in 2.x and RFC 3339 in 3.x.
  Both are returned as POSIX seconds.
* **Booleans.** Flags arrive as integers from some publishers and as real
  booleans from others; both become 0/1.

Each feed is described once in a table of :class:`Field` declarations below,
which is also the list of what gets stored — adding a column to the warehouse
is adding a line there and a line in :mod:`lastmile.db.schema`.

GBFS arrays are flattened rather than dropped: arrays of scalars
(``rental_methods``) are comma-joined, arrays of objects that key cleanly
(``vehicle_types_available``) come back as their own long frames, and the rest
(``per_min_pricing``) are kept as JSON text.

``geofencing_zones`` is the exception to all of the above: its payload is a
GeoJSON FeatureCollection with no entity ids, archived wholesale as documents,
so it is passed through exactly as published — see
:meth:`GbfsClient.geofencing_zones` and :mod:`lastmile.geofencing`.

Not read: per-vehicle ``rental_uris`` (deep links, no analytic value).

This talks to the network only. Storing what it returns is
:mod:`lastmile.collect`'s job.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

import pandas as pd
import requests

from .settings import get_settings


@dataclass(frozen=True)
class Feed:
    """One GBFS feed under both the names and data keys it has had."""

    name: str
    key: str | None
    # GBFS 2.x spellings, when they differ from the 3.0 ones above.
    legacy_name: str | None = None
    legacy_key: str | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, self.legacy_name) if self.legacy_name else (self.name,)

    @property
    def keys(self) -> tuple[str, ...]:
        if self.key is None:
            return ()
        return (self.key, self.legacy_key) if self.legacy_key else (self.key,)


FEEDS: dict[str, Feed] = {
    # system_information's payload is an object, not an array under a key.
    "system_information": Feed("system_information", None),
    "gbfs_versions": Feed("gbfs_versions", "versions"),
    "station_information": Feed("station_information", "stations"),
    "station_status": Feed("station_status", "stations"),
    "vehicle_types": Feed("vehicle_types", "vehicle_types"),
    "system_regions": Feed("system_regions", "regions"),
    "system_pricing_plans": Feed("system_pricing_plans", "plans"),
    "system_alerts": Feed("system_alerts", "alerts"),
    "vehicle_status": Feed(
        "vehicle_status", "vehicles",
        legacy_name="free_bike_status", legacy_key="bikes",
    ),
    # The payload is a GeoJSON FeatureCollection, not an array of records; it
    # has a dedicated accessor rather than a Field table.
    "geofencing_zones": Feed("geofencing_zones", None),
}


# --- value normalization ---------------------------------------------------


def as_int_flag(value: Any) -> int | None:
    """GBFS publishers use both 0/1 and true/false for these flags."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def as_epoch(value: Any) -> int | None:
    """
    A GBFS timestamp as POSIX seconds.

    2.x publishes an integer already; 3.x publishes RFC 3339
    (``2026-10-29T17:20:12.64Z``), which always carries an offset, so this never
    has to guess a zone.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else int(value)
    moment = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(moment) else int(moment.timestamp())


def localized(value: Any, lang: str | None = None) -> str | None:
    """
    One string out of a GBFS name, whichever version published it.

    3.x localizes free text as ``[{"text": ..., "language": ...}]``; 2.x
    publishes the string itself. An unmatched language falls back to the first
    translation rather than nothing: the English name of a French-only system is
    still more useful than a blank.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return value.get("text")
    if isinstance(value, (list, tuple)):
        entries = [entry for entry in value if isinstance(entry, Mapping)]
        if not entries:
            return None
        if lang:
            for entry in entries:
                if entry.get("language") == lang:
                    return entry.get("text")
        return entries[0].get("text")
    return None


def joined(value: Any) -> str | None:
    """A GBFS array of scalars as one comma-separated string."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value if item is not None]
        return ", ".join(items) if items else None
    return str(value)


def key_of(value: Any) -> str | None:
    """
    A GBFS array of ids as a stable key: sorted, comma-joined.

    ``vehicle_docks_available`` counts docks accepting a *set* of vehicle
    types, and publishers do not promise a stable order within that set. Sorting
    is what keeps the same set of docks looking like the same row from one hour
    to the next.
    """
    if not isinstance(value, (list, tuple)):
        return None if value is None else str(value)
    return ", ".join(sorted(str(item) for item in value if item is not None))


def as_json(value: Any) -> str | None:
    """A nested GBFS object kept verbatim, for fields with no flat shape."""
    if value is None or value == [] or value == {}:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


READERS = {
    "id": lambda v, lang: None if v is None else str(v),
    "text": lambda v, lang: None if v is None else str(v),
    "localized": localized,
    "number": lambda v, lang: as_number(v),
    "flag": lambda v, lang: as_int_flag(v),
    "epoch": lambda v, lang: as_epoch(v),
    "join": lambda v, lang: joined(v),
    "json": lambda v, lang: as_json(v),
}


@dataclass(frozen=True)
class Field:
    """One warehouse column and the feed fields that can carry it."""

    name: str
    kind: str
    # Field names in the feed, 3.0 spelling first. Dotted paths reach into
    # nested objects, as in rental_uris.android.
    sources: tuple[str, ...]

    def read(self, record: Mapping[str, Any], lang: str | None) -> Any:
        for source in self.sources:
            value = _lookup(record, source)
            if value is not None:
                return READERS[self.kind](value, lang)
        return None


def _lookup(record: Mapping[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def F(name: str, kind: str = "text", *sources: str) -> Field:
    """A field declaration, defaulting its source to its own name."""
    return Field(name, kind, sources or (name,))


# --- feed field tables -----------------------------------------------------

SYSTEM_INFORMATION_FIELDS = (
    F("system_id", "id"),
    F("name", "localized"),
    F("short_name", "localized"),
    F("operator", "localized"),
    F("opening_hours"),
    F("start_date"),
    F("termination_date"),
    F("url"),
    F("purchase_url"),
    F("phone_number"),
    F("email"),
    F("feed_contact_email"),
    F("timezone"),
    # 2.x publishes a single `language`, 3.x a `languages` list.
    F("languages", "join", "languages", "language"),
    F("license_id"),
    F("license_url"),
    F("attribution_organization_name"),
    F("attribution_url"),
    F("terms_url"),
    F("terms_last_updated"),
    F("privacy_url"),
    F("privacy_last_updated"),
)

GBFS_VERSIONS_FIELDS = (F("version", "id"), F("url"))

SYSTEM_REGIONS_FIELDS = (F("region_id", "id"), F("name", "localized"))

SYSTEM_PRICING_PLANS_FIELDS = (
    F("plan_id", "id"),
    F("name", "localized"),
    F("currency"),
    F("price", "number"),
    F("is_taxable", "flag"),
    F("description", "localized"),
    F("url"),
    F("surge_pricing", "flag"),
    F("per_km_pricing", "json"),
    F("per_min_pricing", "json"),
)

SYSTEM_ALERTS_FIELDS = (
    F("alert_id", "id"),
    F("type"),
    F("summary", "localized"),
    F("description", "localized"),
    F("url"),
    F("station_ids", "join"),
    F("region_ids", "join"),
    F("times", "json"),
    F("last_updated", "epoch"),
)

VEHICLE_TYPES_FIELDS = (
    F("vehicle_type_id", "id"),
    F("form_factor"),
    F("propulsion_type"),
    F("name", "localized"),
    F("description", "localized"),
    F("make", "localized"),
    F("model", "localized"),
    F("color"),
    F("wheel_count", "number"),
    F("max_permitted_speed", "number"),
    F("rated_power", "number"),
    F("max_range_meters", "number"),
    F("rider_capacity", "number"),
    F("cargo_volume_capacity", "number"),
    F("cargo_load_capacity", "number"),
    F("default_reserve_time", "number"),
    F("return_constraint"),
    F("g_co2_km", "number", "g_CO2_km", "g_co2_km"),
    F("default_pricing_plan_id"),
    F("pricing_plan_ids", "join"),
)

STATION_INFORMATION_FIELDS = (
    F("station_id", "id"),
    F("name", "localized"),
    F("short_name", "localized"),
    F("lat", "number"),
    F("lon", "number"),
    F("address"),
    F("cross_street"),
    F("post_code"),
    F("region_id"),
    F("capacity", "number"),
    F("is_virtual_station", "flag"),
    F("is_valet_station", "flag"),
    F("is_charging_station", "flag"),
    F("parking_type"),
    F("parking_hoop", "flag"),
    F("contact_phone"),
    F("station_opening_hours"),
    F("rental_methods", "join"),
    F("rental_uris_android", "text", "rental_uris.android"),
    F("rental_uris_ios", "text", "rental_uris.ios"),
    F("rental_uris_web", "text", "rental_uris.web"),
    F("station_area", "json"),
)

STATION_STATUS_FIELDS = (
    F("station_id", "id"),
    F("num_vehicles_available", "number",
      "num_vehicles_available", "num_bikes_available"),
    F("num_vehicles_disabled", "number",
      "num_vehicles_disabled", "num_bikes_disabled"),
    F("num_docks_available", "number"),
    F("num_docks_disabled", "number"),
    F("is_installed", "flag"),
    F("is_renting", "flag"),
    F("is_returning", "flag"),
    F("last_reported", "epoch"),
)

VEHICLE_STATUS_FIELDS = (
    F("vehicle_id", "id", "vehicle_id", "bike_id"),
    F("lat", "number"),
    F("lon", "number"),
    F("is_reserved", "flag"),
    F("is_disabled", "flag"),
    F("vehicle_type_id"),
    F("current_range_meters", "number"),
    F("current_fuel_percent", "number"),
    F("station_id"),
    F("home_station_id"),
    F("pricing_plan_id"),
    F("vehicle_equipment", "join"),
    F("available_until"),
    F("last_reported", "epoch"),
)

# Coordinates are rounded to five decimals — about a metre, well inside GPS
# error for a parked vehicle, and it keeps publishers' 15-digit floats from
# making every snapshot look different.
COORDINATE_DECIMALS = 5


class StationStatus(NamedTuple):
    """
    One ``station_status`` fetch, with its two nested arrays flattened out.

    They travel together because they come from one response, and splitting the
    accessor would mean fetching the feed three times per snapshot.
    """

    stations: pd.DataFrame
    vehicle_types_available: pd.DataFrame
    vehicle_docks_available: pd.DataFrame


def _frame(
    records: Sequence[Mapping[str, Any]],
    fields: Sequence[Field],
    lang: str | None,
) -> pd.DataFrame:
    """Feed records to a DataFrame with one column per declared field."""
    columns = [field.name for field in fields]
    if not records:
        return pd.DataFrame(columns=columns)
    rows = [
        {field.name: field.read(record, lang) for field in fields}
        for record in records
        if isinstance(record, Mapping)
    ]
    frame = pd.DataFrame(rows, columns=columns)
    for column in ("lat", "lon"):
        if column in frame.columns:
            frame[column] = frame[column].round(COORDINATE_DECIMALS)
    return frame


# --- client ----------------------------------------------------------------


class GbfsClient:
    """
    Reads a system's discovery document and the feeds it advertises.

    Every accessor returns the normalized GBFS 3.0 shape, whichever spec version
    the system actually publishes.
    """

    def __init__(
        self,
        feeds_url: str | None = None,
        lang: str | None = None,
        timeout: int | None = None,
    ):
        """
        Args:
            feeds_url: URL of the GBFS discovery document (``gbfs.json``) for
                any system on spec 2.x or 3.x. Defaults to the configured
                ``feeds_url``.
            lang: Language to pick out of localized text, and the language
                block to read on a 2.x discovery document.
            timeout: Per-request timeout in seconds.
        """
        settings = get_settings()
        self.feeds_url = feeds_url or settings.feeds_url
        self.lang = lang or settings.feeds_lang
        self.timeout = timeout if timeout is not None else settings.request_timeout_s
        self.version, self.feeds = self._discover()
        self._system_information: dict[str, Any] | None = None

    # --- discovery --------------------------------------------------------

    def _get(self, url: str) -> dict[str, Any]:
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _discover(self) -> tuple[str, dict[str, str]]:
        """
        The advertised feeds, as ``{name: url}``, plus the spec version.

        2.x nests feeds under a language key, 3.x does not, and that difference
        is a reliable version signal on its own: Austin's 2.3 document omits the
        ``version`` field the spec asks for.
        """
        payload = self._get(self.feeds_url)
        data = payload.get("data") or {}
        declared = str(payload.get("version") or "").strip()
        if "feeds" in data:
            entries = data["feeds"]
            version = declared or "3.0"
        else:
            block = data.get(self.lang) or next(iter(data.values()), {})
            entries = block.get("feeds", [])
            version = declared or "2.3"
        feeds = {
            entry["name"]: entry["url"]
            for entry in entries
            if entry.get("name") and entry.get("url")
        }
        return version, feeds

    # --- feed access ------------------------------------------------------

    def get_feed_url(self, name: str) -> str:
        """The URL for a feed, found under either spec version's name."""
        for candidate in FEEDS.get(name, Feed(name, None)).names:
            if candidate in self.feeds:
                return self.feeds[candidate]
        raise KeyError(
            f"Feed '{name}' not found in {self.feeds_url}; "
            f"available: {', '.join(sorted(self.feeds)) or 'none'}"
        )

    def has_feed(self, name: str) -> bool:
        return any(
            candidate in self.feeds
            for candidate in FEEDS.get(name, Feed(name, None)).names
        )

    def load_feed_data(self, name: str) -> list[Mapping[str, Any]]:
        """A feed's records, raw, under whichever data key its version uses."""
        if not self.has_feed(name):
            return []
        data = self._get(self.get_feed_url(name)).get("data") or {}
        for candidate in FEEDS[name].keys:
            if candidate in data:
                return list(data[candidate] or [])
        return []

    def _read(self, name: str, fields: Sequence[Field]) -> pd.DataFrame:
        """A feed, normalized against its field table."""
        return _frame(self.load_feed_data(name), fields, self.lang)

    # --- normalized views -------------------------------------------------

    def system_information(self) -> dict[str, Any]:
        """
        What the system says about itself, as one flat record.

        ``timezone`` is the field that matters most: it is what the hourly
        snapshot key is bucketed in, and reading it here is the difference
        between a GBFS client and a one-city client.
        """
        if self._system_information is not None:
            return self._system_information
        data: dict[str, Any] = {}
        if self.has_feed("system_information"):
            data = self._get(self.get_feed_url("system_information")).get("data") or {}
        record = {
            field.name: field.read(data, self.lang)
            for field in SYSTEM_INFORMATION_FIELDS
        }
        # Not spec: which feed this lake was filled from.
        record["gbfs_version"] = self.version
        record["feeds_url"] = self.feeds_url
        self._system_information = record
        return record

    @property
    def timezone(self) -> str | None:
        """The system's own timezone, or None when it publishes none."""
        return self.system_information().get("timezone")

    def gbfs_versions(self) -> pd.DataFrame:
        return self._read("gbfs_versions", GBFS_VERSIONS_FIELDS)

    def system_regions(self) -> pd.DataFrame:
        return self._read("system_regions", SYSTEM_REGIONS_FIELDS)

    def system_pricing_plans(self) -> pd.DataFrame:
        return self._read("system_pricing_plans", SYSTEM_PRICING_PLANS_FIELDS)

    def system_alerts(self) -> pd.DataFrame:
        return self._read("system_alerts", SYSTEM_ALERTS_FIELDS)

    def vehicle_types(self) -> pd.DataFrame:
        return self._read("vehicle_types", VEHICLE_TYPES_FIELDS)

    def station_information(self) -> pd.DataFrame:
        """
        Station metadata, with localized names collapsed to one string.

        Systems that are entirely free-floating publish an empty
        ``station_information`` feed, or omit it — both valid GBFS, neither an
        error.
        """
        frame = self._read("station_information", STATION_INFORMATION_FIELDS)
        return frame.drop_duplicates(subset=["station_id"])

    def station_status(self) -> StationStatus:
        """
        Current station status, with its nested availability arrays flattened.

        A system with no docks publishes no ``station_status`` at all, so an
        absent feed is three empty frames rather than an error.
        """
        records = self.load_feed_data("station_status")
        stations = _frame(records, STATION_STATUS_FIELDS, self.lang)
        return StationStatus(
            stations=stations.drop_duplicates(subset=["station_id"]),
            vehicle_types_available=_explode(
                records,
                "vehicle_types_available",
                ("vehicle_type_id", lambda entry: _text(entry.get("vehicle_type_id"))),
            ),
            vehicle_docks_available=_explode(
                records,
                "vehicle_docks_available",
                ("vehicle_type_ids", lambda entry: key_of(entry.get("vehicle_type_ids"))),
            ),
        )

    def geofencing_zones(self) -> dict[str, Any] | None:
        """
        The geofencing payload exactly as published, or None if unadvertised.

        Deliberately not normalized: the payload is a GeoJSON FeatureCollection
        archived wholesale as documents (see :mod:`lastmile.geofencing`), and
        the rules dialect differs between 2.3 and 3.0 (``ride_allowed`` vs the
        start/end split) in ways that do not map losslessly — the archive
        should record what the publisher said, not a paraphrase.
        """
        if not self.has_feed("geofencing_zones"):
            return None
        return self._get(self.get_feed_url("geofencing_zones")).get("data") or {}

    def vehicle_status(self) -> pd.DataFrame:
        """
        Free-floating vehicles, from ``vehicle_status`` or 2.x's
        ``free_bike_status``.

        GBFS asks publishers to rotate the vehicle id between trips for privacy,
        so these identifiers cannot be used to follow a vehicle over time.
        """
        frame = self._read("vehicle_status", VEHICLE_STATUS_FIELDS)
        return frame.drop_duplicates(subset=["vehicle_id"])


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _explode(
    records: Sequence[Mapping[str, Any]],
    array: str,
    label: tuple[str, Any],
) -> pd.DataFrame:
    """
    One row per entry of a nested per-station array.

    Both ``vehicle_types_available`` and ``vehicle_docks_available`` are arrays
    of ``{<some id>, count}``; only how the entry is labelled differs.
    """
    name, read_label = label
    columns = ["station_id", name, "count"]
    rows = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        station_id = _text(record.get("station_id"))
        for entry in record.get(array) or []:
            if not isinstance(entry, Mapping):
                continue
            value = read_label(entry)
            if value is None:
                continue
            rows.append(
                {
                    "station_id": station_id,
                    name: value,
                    "count": as_number(entry.get("count")),
                }
            )
    frame = pd.DataFrame(rows, columns=columns)
    return frame.drop_duplicates(subset=["station_id", name])
