import pandas as pd
import requests
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from .lastmile_utils import LastMileUtils


class LastMileSetup:
    """
    A class to handle initial setup and configuration of the LastMile data system.
    """
    
    def __init__(self, feeds_url: str, lang: str = 'en', db_path: str = 'lastmile.db'):
        """
        Initialize the LastMileSetup.

        Args:
            feeds_url (str): URL to the GBFS feed.
            lang (str): Language code (e.g., 'en', 'es', 'fr').
        """
        self.utils = LastMileUtils(feeds_url=feeds_url, lang=lang, db_path=db_path)
    
       
    def setup_stations_table(self):
        """
        Create and populate the stations table with station information and regions.
        This is a one-time setup operation.
        """
        try:
            print("Setting up stations table...")
                        
            # Get station information
            st_info = self.utils.load_feed_data(name='station_information', key='stations')
            st_info.drop(columns=['rental_uris'], inplace=True)
            st_info.drop_duplicates(inplace=True)

            # Get regions information
            regions = self.utils.load_feed_data(name='system_regions', key='regions')
            regions.drop_duplicates(inplace=True)

            # Merge station info with regions
            stations = pd.merge(
                st_info[['station_id', 'name', 'short_name', 'region_id', 'capacity', 'lat', 'lon']],
                regions,
                on='region_id',
                how='left'
            )
            
            # Round lat and lon to 5 decimal places
            stations['lat'] = stations['lat'].round(5)
            stations['lon'] = stations['lon'].round(5)
            
            stations.rename(columns={'name_y': 'region'}, inplace=True)
   
            # Save to database
            stations.to_sql('stations', self.utils.conn, if_exists='replace', index=False)
            print(f"Stations table created and populated successfully with {len(stations)} stations")
            
            return stations
            
        except Exception as e:
            print(f"Error setting up stations table: {e}")
            raise
    
    def create_tables(self, overwrite: bool = False):
        """
        Create all necessary database tables for the LastMile system.
        """
        try:
            print("Creating database tables...")

            if self.verify_setup() and not overwrite:
                print("All required tables already exist. Use overwrite=True to overwrite existing tables.")
                return
            
            # Create stations table
            self.setup_stations_table()
            
            # Create station_status table structure
            cursor = self.utils.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS station_status (
                    station_id TEXT,
                    num_bikes_available INTEGER,
                    num_docks_available INTEGER,
                    num_ebikes_available INTEGER,
                    num_docks_disabled INTEGER,
                    num_bikes_disabled INTEGER,
                    timestamp INTEGER
                )
            ''')
            
            # Create bike_status table structure
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bike_status (
                    bike_id TEXT,
                    lat REAL,
                    lon REAL,
                    is_reserved INTEGER,
                    is_disabled INTEGER,
                    vehicle_type_id INTEGER,
                    current_range_meters INTEGER,
                    timestamp INTEGER
                )
            ''')
            
            self.utils.conn.commit()
            print("All database tables created successfully")
            
        except sqlite3.Error as e:
            print(f"Error creating tables: {e}")
            raise
    
    def verify_setup(self) -> bool:
        """
        Verify that the setup is complete and all tables exist.
        
        Returns:
            bool: True if setup is complete, False otherwise
        """
        try:
            cursor = self.utils.conn.cursor()
            
            # Check if all required tables exist
            tables = ['stations', 'station_status', 'bike_status']
            for table in tables:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                if not cursor.fetchone():
                    print(f"Table {table} not found")
                    return False
            
            # Check if stations table has data
            cursor.execute("SELECT COUNT(*) FROM stations")
            station_count = cursor.fetchone()[0]
            print(f"Found {station_count} stations in database")
            
            print("Setup verification completed successfully")
            return True
            
        except Exception as e:
            print(f"Error verifying setup: {e}")
            return False


    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        return False


# Example usage
if __name__ == "__main__":
    # Setup the LastMile system
    with LastMileSetup() as setup:
        # Create all tables
        setup.create_tables()
        
        # Verify setup
        if setup.verify_setup():
            print("LastMile setup completed successfully!")
        else:
            print("Setup verification failed!")
