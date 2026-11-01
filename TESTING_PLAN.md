# Testing plan (working notes, tracked)

Rule: one test per behavior that NOTES.md or a docstring promises. Real tmp lake
and recorded feeds, no mocking of internal modules, no Streamlit rendering
tests, no "cover every type" parametrization. One commit and one new file per
step; the suite stays green between steps.

Starting point (2026-10-30): 179 tests, green, ~10 s. Covered: gbfs, db, schema,
queries, collect, geofencing. Uncovered: settings, metrics, cli, dashboard helpers.

## Steps

- [x] **1. Settings** — `tests/test_settings.py` (12 tests) — commit 7af1d2f
- [x] **2. Shared seeded lake** — `tests/seed.py` + `seeded` fixture in conftest — 7cc7fb8
- [x] **3. Live Ops metrics** — `tests/test_metrics_live_ops.py` (17 tests, kept lean;
  metrics are due for a rewrite) — 93af319

- [x] **4. Trends metrics** — `tests/test_metrics_trends.py` (7 tests, lean)

- [x] **5. CLI** — `tests/test_cli.py` (9 tests)

- [x] **6. Dashboard pure helpers** — `tests/test_dashboard_helpers.py` (16 tests)

- [ ] **7. CI (optional)** — ruff + pytest on 3.11 / 3.12.

## Side fixes done along the way

- 2026-11-01: deleted `maps.availability_bucket` (duplicate of
  `station_status_bucket` with the low threshold hardcoded at 0.2); maps.py now
  imports the metrics one.
- 2026-11-01: deleted the repo-local `.env` (only held the retired
  `LASTMILE_DATABASE_URL`); `load_settings` now warns on unknown `LASTMILE_*`
  env vars instead of ignoring them; conftest runs tests from tmp so a local
  `.env` can no longer leak in.
- 2026-11-01: `coverage.py` moved off two deprecated shapely calls
  (`shapely.ops.transform` → `shapely.transform`, `resolution=` → `quad_segs=`).
