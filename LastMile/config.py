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
