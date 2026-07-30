import pandas as pd
import requests
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any
from .utils import LastMileUtils


class LastMileManager:
    """
    A class to manage ongoing data collection and updates for the LastMile system.
    """
    
    def __init__(self, feeds_url: str, lang: str = 'en', db_path: str = 'lastmile.db', timezone: str = "America/Los_Angeles"):
        """
        Initialize the LastMileManager.
        
        Args:
            feeds_url (str): URL to the GBFS feed.
            lang (str): Language code (e.g., 'en', 'es', 'fr').
            db_path (str): Path to the SQLite database file
        """
        self.db_path = db_path
        self.utils = LastMileUtils(feeds_url=feeds_url, lang=lang, db_path=db_path)
        self.timezone = ZoneInfo(timezone)
        self.timestamp = datetime.now(self.timezone).strftime("%Y-%m-%d-%H:00")
        
    # def set_timestamp(self, timestamp: Optional[str] = None):
    #     """
    #     Set the current timestamp for data collection. The system use hourly timestamps.
    #     If no timestamp is provided, the system will use the current time.

    #     Args:
    #         timestamp (str, optional): Custom timestamp. If None, uses current time.
    #         The format should be YYYY-MM-DD-HH:00.
    #     """
    #     if timestamp is None:
    #         self.current_timestamp = datetime.now(self.timezone).strftime("%Y-%m-%d-%H:00")
    #     else:
    #         self.current_timestamp = timestamp
    #     print(f"Timestamp set to: {self.current_timestamp}")
    
    def get_station_status(self, timestamp: Optional[str] = None) -> pd.DataFrame:
        """
        Get current station status data.
        
        Args:
            timestamp (str, optional): Custom timestamp. Uses instance timestamp if None.
            
        Returns:
            pd.DataFrame: Station status data
        """
        if timestamp is None:
            timestamp = self.timestamp
        
        try:
            st_status = self.utils.load_feed_data('station_status', 'stations')
            st_status = st_status[[
                'station_id', 'num_bikes_available', 'num_docks_available', 
                'num_ebikes_available', 'num_docks_disabled', 'num_bikes_disabled'
            ]]
            st_status['timestamp'] = timestamp
            return st_status
        except Exception as e:
            print(f"Error getting station status: {e}")
            raise
    
    def get_bike_status(self, timestamp: Optional[str] = None) -> pd.DataFrame:
        """
        Get current bike status data.
        
        Args:
            timestamp (str, optional): Custom timestamp. Uses instance timestamp if None.
            
        Returns:
            pd.DataFrame: Bike status data
        """
        if timestamp is None:
            timestamp = self.timestamp
        
        try:
            bk_status = self.utils.load_feed_data('free_bike_status', 'bikes')
            bk_status = bk_status[[
                'bike_id', 'lat', 'lon', 'is_reserved', 'is_disabled', 
                'vehicle_type_id', 'current_range_meters'
            ]]
            # Round lat and lon to 5 decimal places
            bk_status['lat'] = bk_status['lat'].round(5)
            bk_status['lon'] = bk_status['lon'].round(5)
            bk_status['timestamp'] = timestamp
            return bk_status
        except Exception as e:
            print(f"Error getting bike status: {e}")
            raise
    
    def update_station_status(self, st_status: Optional[pd.DataFrame] = None):
        """
        Update the station_status table with new data.
        
        Args:
            st_status (pd.DataFrame, optional): Station status data. Fetches if None.
        """
        if st_status is None:
            st_status = self.get_station_status()
        
        try:            
            # Insert new data
            st_status.to_sql('station_status', self.utils.conn, if_exists='append', index=False)
            print("Station status table updated successfully")
            
        except sqlite3.Error as e:
            print(f"Error updating station status: {e}")
            raise
    
    def update_bike_status(self, bk_status: Optional[pd.DataFrame] = None):
        """
        Update the bike_status table with new data.
        
        Args:
            bk_status (pd.DataFrame, optional): Bike status data. Fetches if None.
        """
        if bk_status is None:
            bk_status = self.get_bike_status()
        
        try:
            # Insert new data
            bk_status.to_sql('bike_status', self.utils.conn, if_exists='append', index=False)
            print("Bike status table updated successfully")
            
        except sqlite3.Error as e:
            print(f"Error updating bike status: {e}")
            raise
    
  
    # def calculate_metrics(self, st_status: Optional[pd.DataFrame] = None, bk_status: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    #     """
    #     Calculate system metrics from station and bike status data.
        
    #     Args:
    #         st_status (pd.DataFrame, optional): Station status data
    #         bk_status (pd.DataFrame, optional): Bike status data
            
    #     Returns:
    #         Dict containing calculated metrics
    #     """
    #     if st_status is None:
    #         st_status = self.get_station_status()
    #     if bk_status is None:
    #         bk_status = self.get_bike_status()
        
    #     metrics = {
    #         'n_bikes_available': st_status['num_bikes_available'].sum(),
    #         'n_ebikes_available': st_status['num_ebikes_available'].sum(),
    #         'n_docks_available': st_status['num_docks_available'].sum(),
    #         'n_total_bikes': len(bk_status),
    #         'timestamp': self.current_timestamp
    #     }
        
    #     print(f"Metrics calculated: {metrics}")
    #     return metrics
    
    def update_data(self):
        """
        Update both station and bike status data.
        """
        try:
            print("Updating data...")
                        
            # Update status tables
            self.update_station_status()
            self.update_bike_status()
            
            # # Calculate and display metrics
            # metrics = self.calculate_metrics()
            
            print("Data update completed successfully!")
            return True
            
        except Exception as e:
            print(f"Error during data update: {e}")
            raise
    
    # def get_historical_data(self, table: str, hours: int = 24) -> pd.DataFrame:
    #     """
    #     Get historical data from the database.
        
    #     Args:
    #         table (str): Table name ('station_status' or 'bike_status')
    #         hours (int): Number of hours of historical data to retrieve
            
    #     Returns:
    #         pd.DataFrame: Historical data
    #     """
    #     try:
    #         query = f"""
    #         SELECT * FROM {table} 
    #         WHERE datetime(timestamp) >= datetime('now', '-{hours} hours')
    #         ORDER BY timestamp DESC
    #         """
    #         return pd.read_sql_query(query, self.conn)
    #     except Exception as e:
    #         print(f"Error getting historical data: {e}")
    #         raise
    
    # def get_station_summary(self) -> pd.DataFrame:
    #     """
    #     Get a summary of all stations with their current status.
        
    #     Returns:
    #         pd.DataFrame: Station summary with current status
    #     """
    #     try:
    #         query = """
    #         SELECT s.*, st.num_bikes_available, st.num_docks_available, 
    #                st.num_ebikes_available, st.timestamp as last_update
    #         FROM stations s
    #         LEFT JOIN (
    #             SELECT station_id, num_bikes_available, num_docks_available, 
    #                    num_ebikes_available, timestamp,
    #                    ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY timestamp DESC) as rn
    #             FROM station_status
    #         ) st ON s.station_id = st.station_id AND st.rn = 1
    #         """
    #         return pd.read_sql_query(query, self.conn)
    #     except Exception as e:
    #         print(f"Error getting station summary: {e}")
    #         raise
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.utils.disconnect()


# Example usage
if __name__ == "__main__":
    # Using context manager (recommended)
    feeds_url = 'https://gbfs.lyft.com/gbfs/2.3/bay/en/system_feeds.json'
    with LastMileManager(feeds_url=feeds_url) as manager:
        # Update data
        metrics = manager.update_data()
        print(f"Final metrics: {metrics}")
    
    # Alternative usage without context manager
    # manager = LastMileManager(feeds_url=feeds_url)
    # try:
    #     metrics = manager.update_data()
    # finally:
    #     manager.close_connection()