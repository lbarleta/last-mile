"""
Quick Start Guide for LastMile Library

Demonstrates setup, collection, and metrics against the local warehouse.
"""

from LastMile import (
    DEFAULT_DB_PATH,
    LastMileSetup,
    LastMileManager,
    LastMileUtils,
    LastMileMetrics,
)


def test_utils(url, lang, db_path):
    utils = LastMileUtils(feeds_url=url, lang=lang, db_path=db_path)
    feeds = utils.feeds
    print(f"System feeds: {len(feeds)} available")
    feed_name = "station_information"
    print(utils.get_feed_url(feed_name))
    stations = utils.load_feed_data(feed_name, "stations")
    print(stations.sample(3))
    utils.disconnect()


def quick_setup(url, lang, db_path):
    with LastMileSetup(feeds_url=url, lang=lang, db_path=db_path) as setup:
        setup.create_tables(overwrite=False)
        if setup.verify_setup():
            print("LastMile setup completed successfully!")
        else:
            print("Setup verification failed!")


def quick_data_update(url, lang, db_path, timezone):
    with LastMileManager(
        feeds_url=url, lang=lang, db_path=db_path, timezone=timezone
    ) as manager:
        station_data = manager.get_station_status()
        print(station_data.sample(3))
        bike_data = manager.get_bike_status()
        print(bike_data.sample(3))
        manager.update_data()


def quick_metrics(db_path):
    with LastMileMetrics(db_path=db_path) as metrics:
        print(metrics.get_system_metrics())


def main():
    print("LastMile Quick Start")
    print("-" * 30)

    url = "https://gbfs.baywheels.com/gbfs/2.3/gbfs.json"
    lang = "en"
    db_path = DEFAULT_DB_PATH
    timezone = "America/Los_Angeles"

    test_utils(url, lang, db_path)
    quick_setup(url, lang, db_path)
    quick_data_update(url, lang, db_path, timezone)
    quick_metrics(db_path)
    return True


if __name__ == "__main__":
    main()
