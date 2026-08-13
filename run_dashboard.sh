#!/bin/bash
# PythonAnywhere website entrypoint. Cwd must be the project root so
# .streamlit/config.toml (light theme) is picked up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# .env (gitignored, supplying LASTMILE_DATABASE_URL and optionally
# UMAMI_WEBSITE_ID) is read by LastMile.config at import. Deliberately not
# sourced here: a PythonAnywhere database name contains a '$', which the shell
# would expand away, silently pointing the app at the wrong database.
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
