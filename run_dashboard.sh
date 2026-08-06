#!/bin/bash
# PythonAnywhere website entrypoint. Cwd must be the project root so
# .streamlit/config.toml (light theme) is picked up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export LASTMILE_DB="${LASTMILE_DB:-$ROOT/data/lastmile-sf.db}"
# Optional: project .env (gitignored) may set UMAMI_WEBSITE_ID=...
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
exec "$ROOT/.venv/bin/streamlit" run "$ROOT/app/main.py" \
  --server.address "unix://${DOMAIN_SOCKET}" \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --server.enableWebsocketCompression false \
  --theme.base light \
  --theme.primaryColor "#1f6f54" \
  --theme.backgroundColor "#f5f6f8" \
  --theme.secondaryBackgroundColor "#ffffff" \
  --theme.textColor "#1c1f24"
