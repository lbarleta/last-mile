# Metrics and design choices

Definitions behind the dashboard metrics and why particular visualizations were
chosen. Companion to the [project README](README.md).

## Station states

Mutually exclusive; empty wins if both bikes and docks are zero:

| State | Rule |
| --- | --- |
| Empty | `bikes == 0` |
| Full | `bikes > 0` and `docks == 0` |
| Low | has both, bike share `< 20%` of (bikes+docks) |
| Healthy | has both, bike share `≥ 20%` |

Free-floating bikes: no region in GBFS → attributed to **San Francisco**.

Timestamps: local `America/Los_Angeles`, key `YYYY-MM-DD-HH:00`.

---

## Live Ops

### Bikes per 10 docks (headline, first)

- Formula: `(docked + free-floating) / open_docks × 10`
- Why not a raw ratio: 0.66 is hard to read; “6.6 bikes per 10 docks” is the same number rescaled
- Why not prior-hour delta: the series barely moves hour-to-hour (~0.5 pts) but has a **daily cycle** (bike-heavy overnight, leanest late afternoon). Prior-hour looks like noise
- Baseline: same clock hour over trailing **28 days** (`SUPPLY_BASELINE_DAYS`). Holds hour fixed so the rhythm cancels
- Measures **fleet posture**, not local service — 40/60 system-wide can coexist with dozens of empty stations

### Coverage (headline, second)

- Share of SF land area within **300 m** (~3 min walk) of an available bike (docked or free-floating)
- Buffer in projected CRS (`EPSG:3310`), SF county boundary from `assets/`
- Delta: vs prior hour (unlike supply balance)

### Problematic stations

- Flag if empty **or** full in any of the trailing **3 daytime** hours (7am–8pm)
- Night hours in the lookback are ignored — ops window, not “empty for 3 hours straight”
- Backup column: nearest non-problematic station within **900 m**

### Region status chart

- Snapshot mix of Empty / Low / Healthy / Full by region
- Tooltip is region-level: `12.3% (42)` per status, not bar-specific

---

## Trends

### Bike and dock availability

- Stacked: docked classic (bikes − e-bikes), docked e-bikes, free-floating
- Separate dashed line: available docks (not stacked — different meaning)
- Classic is net of e-bikes because GBFS puts e-bikes inside `num_bikes_available`
- X-axis: hour always; date only under the first tick of each day

### Status over time

- Four states stacked to 100% (normalize)
- Critical states (Empty / Full) on the outer edges in saturated color; Healthy muted in the middle

### Problematic stations by hour

- Same **3h daytime** rule as Live Ops, averaged by clock hour
- Overnight ≈ 0 by construction (lookback has no ops-day hours)
- Not instantaneous empty/full — that was the earlier version and understated persistence

### Recurrent failures (scatter)

- One point per station: `% hours empty` vs `% hours full` over the selected window
- **Square chart on purpose** — same unit/domain on both axes; a stretched plot makes one failure mode look worse at identical values
- Dot size = **dock capacity** (not failure rate — that would restate distance from origin)
- Color: Reliable / Runs empty / Runs full / Mixed (3× skew rule)
- Dashed line: 25% of hours in failure mode (`pct_empty + pct_full`)
- Zoom bound to both scales

### Bike utilization (system-wide)

- Idea: parked count = fleet − bikes away. Away = riding + service + vans
- Baseline: each calendar day’s max parked count in **midnight–4am**; days without overnight → median of daily baselines
- `bikes_in_use = baseline − parked` at each snapshot
- **Always system-wide**, even when region filter is on — a region is not a closed fleet (bikes ride/van across borders → negatives). Title says so; no apology banner
- Measures simultaneous occupancy, not trip count
- Replaces the old “avg bikes available by hour” charts, which were flat (~7% swing) because fleet-wide parked stock is nearly conserved

---

## Choices that look like bugs but aren’t

| Observation | Why |
| --- | --- |
| Utilization overnight ≈ 0 on the problematic-by-hour chart | Ops-day lookback empty at night |
| Region filter doesn’t change Bike Utilization | Closed-fleet assumption only holds system-wide |
| 10am empty peak vs 3am full peak (instantaneous) | Commute drains stations by mid-morning; overnight parks fill docks — opposite ends of the day |
| Supply balance “always a bit below typical” for a stretch | Sustained bike-light posture vs 28d hour-matched baseline — real signal, not a bug |

---

## What each view answers

| View | Question |
| --- | --- |
| Live Ops | Is the system balanced *right now*, and which stations need a van? |
| Map | Where are the bikes and the holes geographically? |
| Trends | How does the fleet and station health move through the day / week? |

Coverage and bikes/10 docks are complementary: one is rider access, one is inventory posture. Neither replaces the problematic table.
