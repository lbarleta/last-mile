"""
Runtime configuration.

Three layers, each overriding the one before it:

1. The field defaults on :class:`Settings` — what the code does with no
   configuration at all.
2. ``lastmile.toml``, found at or above the working directory (or wherever
   ``LASTMILE_CONFIG`` points). This is where tunables live: search radii,
   thresholds, feed URLs.
3. Environment variables, including anything in a ``.env`` file. Use these for
   deployment-specific values you would rather not commit — above all the
   database URL.

Keys are flat: the TOML key and the ``Settings`` field share a name, and the
environment variable is that name uppercased with a ``LASTMILE_`` prefix, so
``database_url`` is ``LASTMILE_DATABASE_URL`` and ``coverage_radius_m`` is
``LASTMILE_COVERAGE_RADIUS_M``. Strings are coerced to the type of the default;
lists are comma-separated in the environment.

Nothing deployment-specific is stored in this file: installing the package never
means editing its source.
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
ENV_FILENAME = ".env"
ENV_PREFIX = "LASTMILE"


@dataclass(frozen=True)
class Settings:
    """Every tunable, plus the directory relative paths resolve against."""

    # The directory holding lastmile.toml (or the cwd when there is none).
    root: Path = Path(".")

    # --- database -----------------------------------------------------------
    # No useful default on purpose: put the URL in .env as
    # LASTMILE_DATABASE_URL rather than committing credentials to lastmile.toml.
    database_url: str = ""

    # --- GBFS feed ----------------------------------------------------------
    feeds_url: str = "https://gbfs.baywheels.com/gbfs/2.3/gbfs.json"
    feeds_lang: str = "en"
    timezone: str = "America/Los_Angeles"
    request_timeout_s: int = 30

    # --- metrics ------------------------------------------------------------
    # Ops "day" window for problematic-station scoring (local hour, inclusive).
    ops_day_hour_start: int = 7
    ops_day_hour_end: int = 20
    problematic_lookback_hours: int = 3
    # Nearest non-problematic alternative for rebalancing suggestions
    backup_station_radius_m: int = 900
    # Free-floating e-bikes at or below this remaining range count as low-range
    low_range_meters: int = 5000
    # A station holding bikes and docks but below this bike share counts as "low"
    low_station_bike_share: float = 0.2
    # Trailing window for the "typical for this hour" supply-balance baseline.
    supply_baseline_days: int = 28
    # Overnight hours used to estimate fleet size, when nearly all bikes are parked.
    fleet_baseline_hours: tuple[int, ...] = (0, 1, 2, 3, 4)

    # --- walk-shed coverage ---------------------------------------------------
    coverage_radius_m: int = 300
    # Relative paths resolve against the directory holding lastmile.toml.
    boundary_geojson: str = "assets/sf_county_boundary.geojson"
    # California State Plane Zone III (meters) — good for SF buffering
    projected_crs: str = "EPSG:3310"

    # --- weather (under development) -----------------------------------------
    # One grid point for the city; station-level variation is below ERA5 resolution.
    weather_lat: float = 37.7749
    weather_lon: float = -122.4194
    weather_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    weather_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    # ERA5 reanalysis lags real time by ~5 days; the forecast endpoint covers the gap.
    weather_archive_lag_days: int = 6
    weather_variables: tuple[str, ...] = (
        "temperature_2m",
        "precipitation",
        "wind_speed_10m",
        "relative_humidity_2m",
        "cloud_cover",
    )

    # --- stockout forecasting (under development) -----------------------------
    forecast_horizons: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    # Lags (hours) of a station's own occupancy used as model inputs
    forecast_lag_hours: tuple[int, ...] = (1, 2, 3, 6, 12, 24, 168)
    # Trailing window for the same-station / same-hour-of-day stockout rate
    forecast_climatology_days: int = 28
    # History loaded before a window so lag features are populated on its first hour
    forecast_warmup_days: int = 30
    # How much history to feed the trainer (0 = everything available)
    forecast_train_days: int = 180
    # Cap on training rows (station-hours x horizons) to keep fits in memory
    forecast_max_train_rows: int = 1_200_000
    forecast_model_path: str = "data/forecast_model.joblib"
    # Probability at or above which a station is flagged as at risk in the UI
    forecast_risk_threshold: float = 0.5

    # --- dashboard ------------------------------------------------------------
    dashboard_title: str = "Last Mile"
    # Optional Umami analytics; set LASTMILE_UMAMI_WEBSITE_ID in .env
    umami_website_id: str = ""

    def path(self, value: str) -> Path:
        """Resolve a configured path against the project root."""
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def boundary_geojson_path(self) -> Path:
        return self.path(self.boundary_geojson)

    @property
    def forecast_model_file(self) -> Path:
        return self.path(self.forecast_model_path)


# --- loading --------------------------------------------------------------


def load_dotenv(path: Path) -> None:
    """
    Load ``KEY=VALUE`` pairs from a .env file, never overriding real
    environment variables.

    Values may be quoted. Use single quotes for anything containing a ``$``,
    such as a database name on a shared host: this parser leaves it alone, but
    a shell that ``source``s the same file would expand it.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("'").strip('"'))


def find_config(start: Path | None = None) -> Path | None:
    """
    Locate ``lastmile.toml``: ``LASTMILE_CONFIG`` if set, else the nearest one
    at or above the working directory. Returns None when there is none, in which
    case the defaults on :class:`Settings` apply.
    """
    override = os.environ.get(f"{ENV_PREFIX}_CONFIG", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"{ENV_PREFIX}_CONFIG points at {path}, which does not exist"
            )
        return path
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _coerce(raw: Any, default: Any) -> Any:
    """Cast a TOML or environment value to the type of the field's default."""
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


def load_settings(path: str | Path | None = None) -> Settings:
    """Read configuration from disk. Prefer :func:`get_settings`."""
    config_path = Path(path).expanduser().resolve() if path else find_config()
    root = config_path.parent if config_path else Path.cwd().resolve()

    # Before any override is read, and cwd first so running from elsewhere in
    # the tree still picks up a local .env.
    load_dotenv(Path.cwd() / ENV_FILENAME)
    load_dotenv(root / ENV_FILENAME)

    data: Mapping[str, Any] = {}
    if config_path:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    known = {f.name: f.default for f in fields(Settings) if f.name != "root"}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(
            f"unknown key(s) in {config_path}: {', '.join(sorted(unknown))}"
        )

    values: dict[str, Any] = {"root": root}
    for name, default in known.items():
        env_value = os.environ.get(f"{ENV_PREFIX}_{name}".upper())
        raw = env_value.strip() if env_value is not None else data.get(name)
        if raw is None:
            continue
        try:
            values[name] = _coerce(raw, default)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad value for {name}: {raw!r} ({exc})") from exc
    return Settings(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, loaded once."""
    return load_settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read. For tests and the CLI's ``--config``."""
    get_settings.cache_clear()
    return get_settings()
