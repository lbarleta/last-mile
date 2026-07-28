"""Default configuration for LastMile."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(PROJECT_ROOT / "data" / "lastmile-sf.db")
DEFAULT_FEEDS_URL = "https://gbfs.baywheels.com/gbfs/2.3/gbfs.json"
DEFAULT_LANG = "en"
DEFAULT_TIMEZONE = "America/Los_Angeles"

# Hourly snapshot format used in station_status / bike_status
TIMESTAMP_FORMAT = "%Y-%m-%d-%H:00"
