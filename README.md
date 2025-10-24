# LastMile

A Python library for managing GBFS (General Bikeshare Feed Specification) data from bike share systems and other micro-mobility services.

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Data Ingestion**: Fetch real-time data from GBFS API endpoints
- **Station Management**: Handle station information and status updates
- **Bike Tracking**: Monitor bike locations and availability
- **Metrics Calculation**: Compute system-wide statistics and KPIs
- **Database Integration**: Store historical data in SQLite

## Quick Start

```python
from LastMile import LastMileSetup, LastMileManager, LastMileMetrics

# Setup
with LastMileSetup(feeds_url='https://gbfs.baywheels.com/gbfs/2.3/gbfs.json', 
                   lang='en', 
                   db_path='lastmile-sf.db') as setup:
    setup.create_tables()

# Data collection
with LastMileManager(feeds_url='https://gbfs.baywheels.com/gbfs/2.3/gbfs.json',
                    lang='en',
                    db_path='lastmile-sf.db') as manager:
    manager.update_data()

# Metrics
metrics = LastMileMetrics(feeds_url='https://gbfs.baywheels.com/gbfs/2.3/gbfs.json',
                         lang='en',
                         db_path='lastmile-sf.db')
print(metrics.get_system_metrics())
```

## Installation

```bash
git clone https://github.com/yourusername/last-mile.git
cd last-mile
```

## Usage

Run the quick start script to test the library:

```bash
python quick_start.py
```

## Data Structure

The library works with the following data types:

- **Stations**: Station information with location and capacity
- **Station Status**: Real-time availability of bikes and docks
- **Bike Status**: Individual bike locations and status
- **Metrics**: System-wide statistics and KPIs

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [General Bikeshare Feed Specification (GBFS)](https://github.com/NABSA/gbfs) for the data standard
- [Bay Wheels](https://www.lyft.com/bikes/bay-wheels) for providing open data