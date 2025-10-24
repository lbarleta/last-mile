import pandas as pd
import requests
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import os


class LastMileUtils:
    """
    A utility class for common operations in the LastMile system.
    """
    
    def __init__(self, feeds_url: str, lang: str = 'en', db_path: str = 'lastmile.db'):
        """
        Initialize the LastMileUtils.
        
        Args:
            feeds_url (str): URL to the GBFS feed.
            lang (str): Language code (e.g., 'en', 'es', 'fr').
            db_path (str): Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = self.connect()
        self.feeds_url = feeds_url
        self.lang = lang
        self.feeds = self.get_system_feeds()

    def __del__(self):
        """Destructor to close the database connection."""
        self.disconnect()
        self.conn = None

    def get_system_feeds(self) -> Dict[str, Any]:
        """
        Get the main GBFS feeds configuration.
        
        Returns:
            Dict containing the feeds configuration
        """
        try:
            sources = requests.get(self.feeds_url).json()
            return sources['data'][self.lang]['feeds']
        except Exception as e:
            print(f"Error fetching system feeds: {e}")
            raise

    def get_feed_url(self, name: str) -> str:
        """
        Get the URL for a given feed.
        
        Args:
            name (str): name of the feed to get the URL for.
        """
        
        try:
            for feed in self.feeds:
                if feed['name'] == name:
                    return feed['url']
            raise KeyError(f"Feed '{name}' not found in available feeds.")
        except Exception as e:
            print(f"Error getting feed URL: {e}")
            raise


    def load_feed_data(self, name: str, key: str) -> pd.DataFrame:
        """
        Fetches JSON data from a given URL, extracts a specified section,
        and returns it as a pandas DataFrame.

        Args:
            feed (str): name of the feed to load.
            key (str): Name of the key to retrieve under the feed section (e.g., 'stations').

        Returns:
            pd.DataFrame: DataFrame containing the extracted data.
        """

        feed_url = self.get_feed_url(name)
        try:
            sources = requests.get(feed_url).json()
            return pd.DataFrame(sources['data'][key])
        except requests.RequestException as e:
            print(f"Error fetching data from {feed_url}: {e}")
            raise
        except KeyError as e:
            print(f"Error parsing JSON data: {e}")
            raise
    
    
    def connect(self):
        """Establish database connection."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            print(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            raise
        return self.conn

    
    def disconnect(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            print("Database connection closed")
        self.conn = None
    
        # def get_table_info(self, table_name: str) -> Dict[str, Any]:
    #     """
    #     Get information about a database table.
        
    #     Args:
    #         table_name (str): Name of the table
            
    #     Returns:
    #         Dict containing table information
    #     """
    #     try:
            
    #         # Get table schema
    #         cursor = self.conn.cursor()
    #         cursor.execute(f"PRAGMA table_info({table_name})")
    #         columns = cursor.fetchall()
            
    #         # Get row count
    #         cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    #         row_count = cursor.fetchone()[0]
            
    #         # Get sample data
    #         sample_data = self.execute_query(f"SELECT * FROM {table_name} LIMIT 5")
            
    #         return {
    #             'table_name': table_name,
    #             'columns': [col[1] for col in columns],  # Column names
    #             'row_count': row_count,
    #             'sample_data': sample_data
    #         }
    #     except Exception as e:
    #         print(f"Error getting table info for {table_name}: {e}")
    #         raise
    
    # def get_all_tables(self) -> List[str]:
    #     """
    #     Get list of all tables in the database.
        
    #     Returns:
    #         List of table names
    #     """
    #     try:
            
    #         cursor = self.conn.cursor()
    #         cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    #         tables = [row[0] for row in cursor.fetchall()]
    #         return tables
    #     except Exception as e:
    #         print(f"Error getting table list: {e}")
    #         raise
    
    # def clear_table(self, table_name: str):
    #     """
    #     Clear all data from a table.
        
    #     Args:
    #         table_name (str): Name of the table to clear
    #     """
    #     try:
            
    #         cursor = self.conn.cursor()
    #         cursor.execute(f"DELETE FROM {table_name}")
    #         self.conn.commit()
    #         print(f"Table {table_name} cleared successfully")
    #     except Exception as e:
    #         print(f"Error clearing table {table_name}: {e}")
    #         raise
    
    # def get_historical_data(self, table_name: str, hours: int = 24, 
    #                       start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    #     """
    #     Get historical data from a table.
        
    #     Args:
    #         table_name (str): Name of the table
    #         hours (int): Number of hours of historical data
    #         start_date (str, optional): Start date in 'YYYY-MM-DD' format
    #         end_date (str, optional): End date in 'YYYY-MM-DD' format
            
    #     Returns:
    #         pd.DataFrame: Historical data
    #     """
    #     try:
            
    #         if start_date and end_date:
    #             query = f"""
    #             SELECT * FROM {table_name} 
    #             WHERE date(timestamp) BETWEEN '{start_date}' AND '{end_date}'
    #             ORDER BY timestamp DESC
    #             """
    #         else:
    #             query = f"""
    #             SELECT * FROM {table_name} 
    #             WHERE datetime(timestamp) >= datetime('now', '-{hours} hours')
    #             ORDER BY timestamp DESC
    #             """
            
    #         return self.execute_query(query)
    #     except Exception as e:
    #         print(f"Error getting historical data: {e}")
    #         raise
    
    # def get_latest_data(self, table_name: str, limit: int = 100) -> pd.DataFrame:
    #     """
    #     Get the latest data from a table.
        
    #     Args:
    #         table_name (str): Name of the table
    #         limit (int): Maximum number of records to return
            
    #     Returns:
    #         pd.DataFrame: Latest data
    #     """
    #     try:
    #         query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT {limit}"
    #         return self.execute_query(query)
    #     except Exception as e:
    #         print(f"Error getting latest data: {e}")
    #         raise
    
    # def backup_database(self, backup_path: Optional[str] = None) -> str:
    #     """
    #     Create a backup of the database.
        
    #     Args:
    #         backup_path (str, optional): Path for backup file
            
    #     Returns:
    #         str: Path to backup file
    #     """
    #     try:
    #         if not backup_path:
    #             timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    #             backup_path = f"lastmile_backup_{timestamp}.db"
            
    #         # Copy database file
    #         import shutil
    #         shutil.copy2(self.db_path, backup_path)
    #         print(f"Database backed up to: {backup_path}")
    #         return backup_path
    #     except Exception as e:
    #         print(f"Error creating backup: {e}")
    #         raise
    
    # def get_database_stats(self) -> Dict[str, Any]:
    #     """
    #     Get database statistics.
        
    #     Returns:
    #         Dict containing database statistics
    #     """
    #     try:
            
    #         tables = self.get_all_tables()
    #         stats = {
    #             'database_path': self.db_path,
    #             'database_size_mb': os.path.getsize(self.db_path) / (1024 * 1024),
    #             'tables': {},
    #             'total_records': 0
    #         }
            
    #         for table in tables:
    #             table_info = self.get_table_info(table)
    #             stats['tables'][table] = {
    #                 'row_count': table_info['row_count'],
    #                 'columns': table_info['columns']
    #             }
    #             stats['total_records'] += table_info['row_count']
            
    #         return stats
    #     except Exception as e:
    #         print(f"Error getting database stats: {e}")
    #         raise
    
    # def optimize_database(self):
    #     """
    #     Optimize the database by running VACUUM and ANALYZE.
    #     """
    #     try:
            
    #         cursor = self.conn.cursor()
    #         cursor.execute("VACUUM")
    #         cursor.execute("ANALYZE")
    #         self.conn.commit()
    #         print("Database optimized successfully")
    #     except Exception as e:
    #         print(f"Error optimizing database: {e}")
    #         raise
    
    # def get_system_info(self) -> Dict[str, Any]:
    #     """
    #     Get system information and configuration.
        
    #     Returns:
    #         Dict containing system information
    #     """
    #     try:
    #         feeds = self.get_system_feeds()
    #         pricing = requests.get("https://gbfs.lyft.com/gbfs/2.3/bay/en/system_pricing_plans.json").json()
            
    #         system_info = {
    #             'feeds': feeds,
    #             'pricing_plans': pricing['data']['plans'],
    #             'database_path': self.db_path,
    #             'setup_timestamp': datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
    #         }
            
    #         return system_info
    #     except Exception as e:
    #         print(f"Error getting system info: {e}")
    #         raise


# # Example usage
# if __name__ == "__main__":
#     # feeds url and language
#     url = 'https://gbfs.lyft.com/gbfs/2.3/bay/en/system_feeds.json'
#     lang = 'en'
    
#     # Utilities example
#     with LastMileUtils() as utils:
#         # Get system feeds
#         feeds = utils.get_system_feeds(url, lang)
#         print(f"System feeds: {len(feeds)} available")
        
#         # Get database stats
#         stats = utils.get_database_stats()
#         print(f"Database has {stats['total_records']} total records")
