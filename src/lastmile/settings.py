"""
Runtime configuration: ``lastmile.toml``, found at or above the working
directory or wherever ``LASTMILE_CONFIG`` points. That variable is the only
thing read from the environment.

The file is tables all the way down::

    [general]            default_system, request_timeout_s, umami_website_id
    [systems.<name>]     one per GBFS system: its lake, its feed, its map
    [metrics]            thresholds and windows, shared by every system

The CLI's ``--system`` picks a system; ``default_system`` applies otherwise.
Whichever is active is resolved into the flat :class:`Settings`, so the rest
of the code never sees more than one. A system's table is self-contained:
``lake_path`` and ``feeds_url`` are required, and anything else it leaves out
takes the field default below. Those defaults are generic — a language, a
CRS, a blank timezone meaning "the system's own" — never a deployment's
values, so installing the package never means editing its source.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "lastmile.toml"
CONFIG_ENV = "LASTMILE_CONFIG"

# Which table each key lives in. Every field of Settings that is not internal
# appears here exactly once; ``default_system`` is the one key that is not a
# field, since it selects a system rather than describing one.
GENERAL_KEYS = ("default_system", "request_timeout_s", "umami_website_id")
SYSTEM_KEYS = (
    "lake_path",
    "feeds_url",
    "feeds_lang",
    "timezone",
    "dashboard_title",
    "boundary_geojson",
    "projected_crs",
)
REQUIRED_SYSTEM_KEYS = ("lake_path", "feeds_url")
METRICS_KEYS = (
    "ops_day_hour_start",
    "ops_day_hour_end",
    "problematic_lookback_hours",
    "backup_station_radius_m",
    "low_range_meters",
    "low_station_bike_share",
    "supply_baseline_days",
    "fleet_baseline_hours",
    "coverage_radius_m",
)
TABLES = {"general": GENERAL_KEYS, "systems": SYSTEM_KEYS, "metrics": METRICS_KEYS}
INTERNAL_FIELDS = ("root", "system", "systems")


@dataclass(frozen=True)
class Settings:
    """Every tunable, resolved for one system, plus where relative paths go."""

    # The directory holding lastmile.toml (or the cwd when there is none).
    root: Path = Path(".")
    # The active system's name, and every name the file configures.
    system: str = ""
    systems: tuple[str, ...] = ()

    # --- general --------------------------------------------------------------
    request_timeout_s: int = 30
    # Umami analytics id; blank disables.
    umami_website_id: str = ""

    # --- the active system ----------------------------------------------------
    # Both required in the system's table; blank only before one is loaded.
    lake_path: str = ""
    feeds_url: str = ""
    feeds_lang: str = "en"
    # Blank reads the system's own timezone from its system_information feed,
    # falling back to UTC. Display only: the lake itself stores instants.
    timezone: str = ""
    dashboard_title: str = "Last Mile"
    # City boundary for the coverage map; no default, since it is a city.
    boundary_geojson: str = ""
    projected_crs: str = "EPSG:4326"

    # --- metrics --------------------------------------------------------------
    # Ops "day" window for problematic-station scoring (local hour, inclusive).
    ops_day_hour_start: int = 7
    ops_day_hour_end: int = 20
    problematic_lookback_hours: int = 3
    backup_station_radius_m: int = 900
    low_range_meters: int = 5000
    low_station_bike_share: float = 0.2
    supply_baseline_days: int = 28
    fleet_baseline_hours: tuple[int, ...] = (0, 1, 2, 3, 4)
    coverage_radius_m: int = 300

    def path(self, value: str) -> Path:
        """Resolve a configured path against the project root."""
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def lake_dir(self) -> Path:
        if not self.lake_path:
            raise ValueError(_NO_SYSTEM)
        return self.path(self.lake_path)

    @property
    def boundary_geojson_path(self) -> Path:
        if not self.boundary_geojson:
            raise ValueError(
                f"boundary_geojson is not set for system {self.system!r} "
                f"in {CONFIG_FILENAME}"
            )
        return self.path(self.boundary_geojson)


_NO_SYSTEM = (
    f"no GBFS system is configured; {CONFIG_FILENAME} needs a "
    "[systems.<name>] table with lake_path and feeds_url"
)


# --- loading --------------------------------------------------------------


def find_config(start: Path | None = None) -> Path | None:
    """
    Locate ``lastmile.toml``: ``LASTMILE_CONFIG`` if set, else the nearest one
    at or above the working directory. Returns None when there is none, in which
    case the defaults on :class:`Settings` apply and no system is active.
    """
    override = os.environ.get(CONFIG_ENV, "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"{CONFIG_ENV} points at {path}, which does not exist"
            )
        return path
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _coerce(raw: Any, default: Any) -> Any:
    """Cast a TOML value to the type of the field's default."""
    if isinstance(default, tuple):
        items = raw.split(",") if isinstance(raw, str) else list(raw)
        sample = default[0] if default else ""
        return tuple(
            _coerce(item.strip() if isinstance(item, str) else item, sample)
            for item in items
            if not (isinstance(item, str) and not item.strip())
        )
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def _table(data: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    block = data.get(key) or {}
    if not isinstance(block, Mapping):
        raise ValueError(f"[{key}] in {where} must be a table")
    return block


def _reject_unknown(found: Mapping, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(found) - set(allowed))
    if unknown:
        raise ValueError(
            f"unknown key(s) in {where}: {', '.join(unknown)} "
            f"(allowed: {', '.join(allowed)})"
        )


def _systems(data: Mapping[str, Any], where: str) -> dict[str, dict]:
    """The ``[systems]`` table, validated: name -> its complete key set."""
    systems = {}
    for name, block in _table(data, "systems", where).items():
        if not isinstance(block, Mapping):
            raise ValueError(f"[systems.{name}] in {where} must be a table")
        _reject_unknown(block, SYSTEM_KEYS, f"[systems.{name}] of {where}")
        missing = [k for k in REQUIRED_SYSTEM_KEYS if not str(block.get(k, "")).strip()]
        if missing:
            raise ValueError(
                f"[systems.{name}] in {where} must set {', '.join(missing)}"
            )
        systems[name] = dict(block)
    return systems


def _select_system(
    systems: Mapping[str, Any], default: str, requested: str | None, where: str
) -> str:
    """Which system is active: the one asked for, else ``default_system``."""
    available = ", ".join(systems) or "none"
    if requested:
        if requested not in systems:
            raise ValueError(
                f"unknown system {requested!r}; configured in {where}: {available}"
            )
        return requested
    if not systems:
        return ""
    if default:
        if default not in systems:
            raise ValueError(
                f"default_system {default!r} in {where} is not configured; "
                f"available: {available}"
            )
        return default
    if len(systems) == 1:
        return next(iter(systems))
    raise ValueError(
        f"{where} configures several systems ({available}) but no "
        "default_system; set one under [general] or pass --system"
    )


def load_settings(
    path: str | Path | None = None, system: str | None = None
) -> Settings:
    """Read configuration from disk. Prefer :func:`get_settings`."""
    config_path = Path(path).expanduser().resolve() if path else find_config()
    root = config_path.parent if config_path else Path.cwd().resolve()
    where = str(config_path or CONFIG_FILENAME)

    data: Mapping[str, Any] = {}
    if config_path:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    stray = sorted(set(data) - set(TABLES))
    if stray:
        raise ValueError(
            f"unknown top-level key(s) in {where}: {', '.join(stray)}; every key "
            f"belongs in one of {', '.join(f'[{t}]' for t in TABLES)}"
        )

    general = dict(_table(data, "general", where))
    _reject_unknown(general, GENERAL_KEYS, f"[general] of {where}")
    metrics = _table(data, "metrics", where)
    _reject_unknown(metrics, METRICS_KEYS, f"[metrics] of {where}")
    systems = _systems(data, where)
    default = str(general.pop("default_system", "") or "").strip()
    system = _select_system(systems, default, system or _selected_system, where)

    configured = {**general, **metrics, **systems.get(system, {})}
    values: dict[str, Any] = {"root": root, "system": system, "systems": tuple(systems)}
    for field in fields(Settings):
        if field.name in INTERNAL_FIELDS or field.name not in configured:
            continue
        raw = configured[field.name]
        try:
            values[field.name] = _coerce(raw, field.default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad value for {field.name}: {raw!r} ({exc})") from exc
    return Settings(**values)


# The system the CLI asked for, if any. Module state rather than an argument
# so that get_settings() stays a plain cached call for the rest of the code.
_selected_system: str | None = None


def select_system(name: str | None) -> None:
    """Make later loads resolve this system instead of ``default_system``."""
    global _selected_system
    _selected_system = name or None
    get_settings.cache_clear()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, loaded once."""
    return load_settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read. For tests and the CLI."""
    get_settings.cache_clear()
    return get_settings()
