"""
Quick Start Guide for LastMile Library

This file demonstrates the most common usage patterns for the LastMile library.
"""

from LastMile import LastMileSetup, LastMileManager, LastMileUtils, LastMileMetrics

def test_utils(url, lang, db_path):
    # Test the utils class
    utils = LastMileUtils(feeds_url=url, lang=lang, db_path=db_path)

    feeds = utils.feeds
    print(f"System feeds: {len(feeds)} available")

    feed_name = 'station_information'
    print(utils.get_feed_url(feed_name))

    stations = utils.load_feed_data(feed_name, 'stations')
    print(stations.sample(3))


def quick_setup(url, lang, db_path):
    """One-time setup of the LastMile system."""
    with LastMileSetup(feeds_url=url, lang=lang, db_path=db_path) as setup:
        setup.create_tables(overwrite=True)
        
        # Verify setup
        if setup.verify_setup():
            print("LastMile setup completed successfully!")
        else:
            print("Setup verification failed!")


def quick_data_update(url, lang, db_path, timezone):
    with LastMileManager(feeds_url=url, lang=lang, db_path=db_path, timezone=timezone) as manager:
        station_data = manager.get_station_status()
        print(station_data.sample(3))
        
        bike_data = manager.get_bike_status()
        print(bike_data.sample(3))

        manager.update_data()


def quick_metrics(url, lang, db_path, timezone):
    metrics = LastMileMetrics(url, lang, db_path, timezone)
    print(metrics.get_system_metrics())
    

def main():
    """Main quick start function."""
    print("🚀 LastMile Quick Start")
    print("-" * 30)

    # Parameters
    url = 'https://gbfs.baywheels.com/gbfs/2.3/gbfs.json'
    lang = 'en'
    db_path = 'lastmile-sf.db'
    timezone = "America/Los_Angeles"

    # Test the utils class
    test_utils(url, lang, db_path)

    # One-time setup of the LastMile system
    quick_setup(url, lang, db_path)

    # Data collection
    quick_data_update(url, lang, db_path, timezone)

    # Metrics calculation
    quick_metrics(url, lang, db_path, timezone)

    return True


if __name__ == "__main__":
    main()
