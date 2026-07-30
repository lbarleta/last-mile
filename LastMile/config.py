"""Default configuration for LastMile."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(PROJECT_ROOT / "data" / "lastmile-sf.db")
DEFAULT_FEEDS_URL = "https://gbfs.baywheels.com/gbfs/2.3/gbfs.json"
DEFAULT_LANG = "en"
DEFAULT_TIMEZONE = "America/Los_Angeles"

# Hourly snapshot format used in station_status / bike_status
TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"

# Ops "day" window for problematic-station scoring (local hour, inclusive).
# Hours outside this range (9pm–6am) are ignored.
OPS_DAY_HOUR_START = 7   # 7:00
OPS_DAY_HOUR_END = 20    # 20:00 (through 8pm); 21:00+ excluded
PROBLEMATIC_LOOKBACK_HOURS = 3
# Nearest non-problematic alternative for rebalancing suggestions
BACKUP_STATION_RADIUS_M = 900

# Free-floating e-bikes at or below this remaining range count as low-range
LOW_RANGE_METERS = 5000

# Walk-shed coverage: ~3-minute walk around available bikes
COVERAGE_RADIUS_M = 300

SF_BOUNDARY_GEOJSON_PATH = PROJECT_ROOT / "assets" / "sf_county_boundary.geojson"
# Source (kept for reference; app reads the local copy only):
# https://data.sfgov.org/resource/wamw-vt4s.geojson?county=San%20Francisco
# California State Plane Zone III (meters) — good for SF buffering
SF_PROJECTED_CRS = "EPSG:3310"


## UNDER DEVELOPMENT -------------------------------------------------------
# Weather (Open-Meteo) -------------------------------------------------
# One grid point for the city; Bay Wheels' SF footprint is ~10 km across, so
# station-level weather variation is well below ERA5/HRRR resolution.
SF_WEATHER_LAT = 37.7749
SF_WEATHER_LON = -122.4194
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# ERA5 reanalysis lags real time by ~5 days; the forecast endpoint covers the
# gap (past_days) and the future hours we score against.
OPEN_METEO_ARCHIVE_LAG_DAYS = 6
WEATHER_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "relative_humidity_2m",
    "cloud_cover",
)

# --- Stockout forecasting -------------------------------------------------
FORECAST_HORIZONS = (1, 2, 3, 4, 5, 6)
# Lags (hours) of a station's own occupancy used as model inputs
FORECAST_LAG_HOURS = (1, 2, 3, 6, 12, 24, 168)
# Trailing window for the same-station / same-hour-of-day stockout rate, which
# doubles as the climatology baseline in backtests
FORECAST_CLIMATOLOGY_DAYS = 28
# History loaded before a training/scoring window so lag and climatology
# features are fully populated on its first hour
FORECAST_WARMUP_DAYS = 30
# How much history to feed the trainer (None = everything available)
FORECAST_TRAIN_DAYS = 180
# Cap on training rows (station-hours x horizons) to keep fits in memory
FORECAST_MAX_TRAIN_ROWS = 1_200_000
FORECAST_MODEL_PATH = str(PROJECT_ROOT / "data" / "forecast_model.joblib")
# Probability at or above which a station is flagged as at risk in the UI
FORECAST_RISK_THRESHOLD = 0.5