# LastMile

Python library for ingesting GBFS bike-share feeds into SQLite and computing ops metrics.

```text
LastMile/
  config.py     defaults (DB path, timestamps, coverage radius, …)
  utils.py      GBFS feed client + shared SQLite connection (LastMileUtils)
  setup.py      one-time stations table / schema (LastMileSetup)
  manager.py    hourly station + free-bike collection (LastMileManager)
  db.py         read-only SQL helpers and indexes
  metrics.py    live-ops + historical KPIs (LastMileMetrics)
  coverage.py   San Francisco 3-min walk-shed geometry
  weather.py    Open-Meteo hourly weather cache (archive + forecast)
  features.py   station panel + feature engineering for forecasting
  forecast.py   stockout model: train, backtest, score, store (under development)
```


Public imports:

```python
from LastMile import (
    LastMileSetup,
    LastMileManager,
    LastMileMetrics,
    LastMileUtils,
    DEFAULT_DB_PATH,
)
```

The Streamlit dashboard lives in [`app/`](../app/) (`streamlit run app/main.py`).  
Hourly collection: [`scripts/collect.py`](../scripts/collect.py).
