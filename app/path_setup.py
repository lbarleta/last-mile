"""Make the project root and app/ importable when Streamlit runs from app/."""

from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
_ROOT = _APP_DIR.parent

for path in (_ROOT, _APP_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# Importing config is what loads .env; it has to happen after the path setup
# above, and before anything reads the environment.
import LastMile.config  # noqa: E402,F401
