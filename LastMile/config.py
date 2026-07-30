"""Default configuration for LastMile."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(PROJECT_ROOT / "data" / "lastmile-sf.db")
DEFAULT_FEEDS_URL = "https://gbfs.baywheels.com/gbfs/2.3/gbfs.json"
DEFAULT_LANG = "en"
DEFAULT_TIMEZONE = "America/Los_Angeles"

# Hourly snapshot format used in station_status / bike_status
TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"

# Free-floating e-bikes at or below this remaining range count as low-range
LOW_RANGE_METERS = 5000

# Walk-shed coverage: ~3-minute walk around available bikes
COVERAGE_RADIUS_FT = 1000
COVERAGE_RADIUS_M = COVERAGE_RADIUS_FT * 0.3048
SF_BOUNDARY_GEOJSON_PATH = PROJECT_ROOT / "assets" / "sf_county_boundary.geojson"
# Source (kept for reference; app reads the local copy only):
# https://data.sfgov.org/resource/wamw-vt4s.geojson?county=San%20Francisco
# California State Plane Zone III (meters) — good for SF buffering
SF_PROJECTED_CRS = "EPSG:3310"
