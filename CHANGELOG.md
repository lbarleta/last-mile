# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0alpha] - 2024-01-XX

### Added
- Initial release of LastMile library
- Core functionality for GBFS data management
- Support for multiple GBFS feeds (Bay Wheels, Citi Bike, etc.)
- SQLite database integration
- Real-time data collection capabilities
- Basic metrics calculation
- Quick start script for testing

### Features
- **LastMileSetup**: Initial setup and configuration management
- **LastMileManager**: Data collection and management
- **LastMileUtils**: Utility functions for data loading
- **LastMileMetrics**: Basic system metrics calculation

### Technical Details
- Python 3.7+ support
- SQLite database storage
- Real-time GBFS data ingestion
- Context manager support for resource cleanup
- Timezone-aware timestamp handling

### Dependencies
- pandas >= 1.5.0
- numpy >= 1.21.0
- requests >= 2.28.0
