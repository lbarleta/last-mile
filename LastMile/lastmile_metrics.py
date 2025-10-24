import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List, Tuple, Union
from .lastmile_utils import LastMileUtils

class LastMileMetrics:
    """
    A comprehensive utility class for calculating and analyzing metrics 
    in the LastMile bike share system.
    """
    
    def __init__(self, feeds_url: str, lang: str = 'en', db_path: str = 'lastmile.db', timezone: str = "America/Los_Angeles"):
        """
        Initialize the LastMileMetrics.
        
        Args:
            db_path (str): Path to the SQLite database file
        """
        self.utils = LastMileUtils(feeds_url=feeds_url, lang=lang, db_path=db_path)
        self.timezone = ZoneInfo(timezone)
        self.timestamp = datetime.now(self.timezone).strftime("%Y-%m-%d-%H:00")


    def get_system_metrics(self, timestamp: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate comprehensive system metrics.
        
        Args:
            timestamp (str): Timestamp to calculate metrics for
            
        Returns:
            Dict containing calculated metrics
        """
        try:
            if timestamp is None:
                timestamp = self.timestamp

            station_data = self.utils.load_feed_data('station_status', 'stations')
            bike_data = self.utils.load_feed_data('free_bike_status', 'bikes')

            basic_metrics = self._calculate_basic_metrics(station_data, bike_data)

            metrics = {
                **basic_metrics,
                'timestamp': timestamp,
            }

            return metrics
        except Exception as e:
            print(f"Error calculating system metrics: {e}")
            raise

        # try:
        #     # Validate input data
        #     station_required = ['station_id', 'num_bikes_available', 'num_docks_available', 
        #                       'num_ebikes_available', 'num_bikes_disabled', 'num_docks_disabled']
        #     bike_required = ['bike_id', 'is_reserved', 'is_disabled']
            
        #     self._validate_data(station_data, station_required, "Station data")
        #     self._validate_data(bike_data, bike_required, "Bike data")
            
        #     # Calculate basic metrics
        #     basic_metrics = self._calculate_basic_metrics(station_data, bike_data)
            
        #     # Calculate availability metrics
        #     availability_metrics = self._calculate_availability_metrics(station_data, bike_data)
            
        #     # Calculate utilization metrics
        #     utilization_metrics = self._calculate_utilization_metrics(station_data)
            
        #     # Calculate performance metrics
        #     performance_metrics = self._calculate_performance_metrics(station_data, bike_data)
            
        #     # Calculate geographic metrics
        #     geographic_metrics = self._calculate_geographic_metrics(station_data, bike_data)
            
        #     # Combine all metrics
        #     metrics = {
        #         **basic_metrics,
        #         **availability_metrics,
        #         **utilization_metrics,
        #         **performance_metrics,
        #         **geographic_metrics,
        #         'calculation_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #         'data_quality_score': self._calculate_data_quality_score(station_data, bike_data)
        #     }
            
        #     return metrics
            
        # except Exception as e:
        #     print(f"Error calculating system metrics: {e}")
        #     raise
    
    def _calculate_basic_metrics(self, station_data: pd.DataFrame, 
                                bike_data: pd.DataFrame) -> Dict[str, Any]:
        """Calculate basic system metrics."""
        return {
            'total_stations': len(station_data),
            'total_bikes': len(bike_data),
            'active_stations': len(station_data[station_data['num_bikes_available'] > 0]),
            'active_bikes': len(bike_data[(bike_data['is_reserved'] == 0) & 
                                       (bike_data['is_disabled'] == 0)])
        }
    
    # def _calculate_availability_metrics(self, station_data: pd.DataFrame, 
    #                                   bike_data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate availability metrics."""
    #     return {
    #         'bikes_available': int(station_data['num_bikes_available'].sum()),
    #         'ebikes_available': int(station_data['num_ebikes_available'].sum()),
    #         'docks_available': int(station_data['num_docks_available'].sum()),
    #         'bikes_disabled': int(station_data['num_bikes_disabled'].sum()),
    #         'docks_disabled': int(station_data['num_docks_disabled'].sum()),
    #         'bikes_reserved': int(bike_data['is_reserved'].sum()),
    #         'bikes_inactive': int(bike_data['is_disabled'].sum()),
    #         'availability_rate': self._calculate_availability_rate(station_data),
    #         'ebike_ratio': self._calculate_ebike_ratio(station_data)
    #     }
    
    # def _calculate_utilization_metrics(self, station_data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate utilization metrics."""
    #     total_capacity = station_data['num_bikes_available'] + station_data['num_docks_available']
    #     total_used = station_data['num_bikes_available']
        
    #     # Avoid division by zero
    #     utilization_rates = np.where(total_capacity > 0, total_used / total_capacity, 0)
        
    #     return {
    #         'overall_utilization': float(np.mean(utilization_rates)),
    #         'utilization_std': float(np.std(utilization_rates)),
    #         'utilization_median': float(np.median(utilization_rates)),
    #         'high_utilization_stations': int(np.sum(utilization_rates > 0.8)),
    #         'low_utilization_stations': int(np.sum(utilization_rates < 0.2)),
    #         'balanced_stations': int(np.sum((utilization_rates >= 0.2) & (utilization_rates <= 0.8)))
    #     }
    
    # def _calculate_performance_metrics(self, station_data: pd.DataFrame, 
    #                                 bike_data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate performance metrics."""
    #     return {
    #         'avg_bikes_per_station': float(station_data['num_bikes_available'].mean()),
    #         'max_bikes_per_station': int(station_data['num_bikes_available'].max()),
    #         'min_bikes_per_station': int(station_data['num_bikes_available'].min()),
    #         'stations_with_bikes': int((station_data['num_bikes_available'] > 0).sum()),
    #         'stations_with_docks': int((station_data['num_docks_available'] > 0).sum()),
    #         'stations_empty': int((station_data['num_bikes_available'] == 0).sum()),
    #         'stations_full': int((station_data['num_docks_available'] == 0).sum()),
    #         'system_efficiency': self._calculate_system_efficiency(station_data)
    #     }
    
    # def _calculate_geographic_metrics(self, station_data: pd.DataFrame, 
    #                                 bike_data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate geographic distribution metrics."""
    #     metrics = {
    #         'station_coverage': self._calculate_station_coverage(station_data),
    #         'bike_distribution': self._calculate_bike_distribution(bike_data)
    #     }
        
    #     # Add geographic spread if coordinates are available
    #     if 'lat' in station_data.columns and 'lon' in station_data.columns:
    #         metrics['geographic_spread'] = self._calculate_geographic_spread(station_data)
        
    #     return metrics
    
    # def _calculate_availability_rate(self, station_data: pd.DataFrame) -> float:
    #     """Calculate overall system availability rate."""
    #     total_capacity = station_data['num_bikes_available'] + station_data['num_docks_available']
    #     if total_capacity.sum() == 0:
    #         return 0.0
    #     return float((station_data['num_bikes_available'].sum() / total_capacity.sum()))
    
    # def _calculate_ebike_ratio(self, station_data: pd.DataFrame) -> float:
    #     """Calculate e-bike to regular bike ratio."""
    #     total_bikes = station_data['num_bikes_available'].sum()
    #     total_ebikes = station_data['num_ebikes_available'].sum()
    #     if total_bikes == 0:
    #         return 0.0
    #     return float(total_ebikes / total_bikes)
    
    # def _calculate_system_efficiency(self, station_data: pd.DataFrame) -> float:
    #     """Calculate overall system efficiency."""
    #     total_capacity = station_data['num_bikes_available'] + station_data['num_docks_available']
    #     total_used = station_data['num_bikes_available']
        
    #     if total_capacity.sum() == 0:
    #         return 0.0
        
    #     # Calculate efficiency as the ratio of used capacity to total capacity
    #     efficiency = total_used.sum() / total_capacity.sum()
    #     return float(efficiency)
    
    # def _calculate_station_coverage(self, station_data: pd.DataFrame) -> Dict[str, int]:
    #     """Calculate station coverage metrics."""
    #     return {
    #         'stations_with_bikes': int((station_data['num_bikes_available'] > 0).sum()),
    #         'stations_with_docks': int((station_data['num_docks_available'] > 0).sum()),
    #         'stations_empty': int((station_data['num_bikes_available'] == 0).sum()),
    #         'stations_full': int((station_data['num_docks_available'] == 0).sum()),
    #         'stations_operational': int(len(station_data))
    #     }
    
    # def _calculate_bike_distribution(self, bike_data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate bike distribution metrics."""
    #     if bike_data.empty:
    #         return {
    #             'bikes_reserved': 0,
    #             'bikes_disabled': 0,
    #             'bikes_active': 0,
    #             'avg_range_meters': 0.0
    #         }
        
    #     active_bikes = bike_data[(bike_data['is_reserved'] == 0) & (bike_data['is_disabled'] == 0)]
        
    #     metrics = {
    #         'bikes_reserved': int(bike_data['is_reserved'].sum()),
    #         'bikes_disabled': int(bike_data['is_disabled'].sum()),
    #         'bikes_active': len(active_bikes)
    #     }
        
    #     # Add range metrics if available
    #     if 'current_range_meters' in bike_data.columns:
    #         metrics['avg_range_meters'] = float(bike_data['current_range_meters'].mean())
    #         metrics['max_range_meters'] = float(bike_data['current_range_meters'].max())
    #         metrics['min_range_meters'] = float(bike_data['current_range_meters'].min())
    #     else:
    #         metrics['avg_range_meters'] = 0.0
        
    #     return metrics
    
    # def _calculate_geographic_spread(self, station_data: pd.DataFrame) -> Dict[str, float]:
    #     """Calculate geographic spread metrics."""
    #     if 'lat' not in station_data.columns or 'lon' not in station_data.columns:
    #         return {}
        
    #     lat_std = float(station_data['lat'].std())
    #     lon_std = float(station_data['lon'].std())
        
    #     return {
    #         'latitude_std': lat_std,
    #         'longitude_std': lon_std,
    #         'geographic_spread': float(np.sqrt(lat_std**2 + lon_std**2))
    #     }
    
    # def _calculate_data_quality_score(self, station_data: pd.DataFrame, 
    #                                 bike_data: pd.DataFrame) -> float:
    #     """Calculate data quality score (0-1)."""
    #     score = 1.0
        
    #     # Check for missing values
    #     station_missing = station_data.isnull().sum().sum() / (len(station_data) * len(station_data.columns))
    #     bike_missing = bike_data.isnull().sum().sum() / (len(bike_data) * len(bike_data.columns))
        
    #     score -= (station_missing + bike_missing) * 0.5
        
    #     # Check for negative values in numeric columns
    #     numeric_cols = station_data.select_dtypes(include=[np.number]).columns
    #     negative_values = (station_data[numeric_cols] < 0).sum().sum()
    #     if negative_values > 0:
    #         score -= 0.2
        
    #     return max(0.0, min(1.0, score))
    
    # def calculate_usage_patterns(self, historical_data: pd.DataFrame, 
    #                            time_column: str = 'timestamp') -> Dict[str, Any]:
    #     """
    #     Calculate usage patterns from historical data.
        
    #     Args:
    #         historical_data (pd.DataFrame): Historical station status data
    #         time_column (str): Name of the timestamp column
            
    #     Returns:
    #         Dict containing usage patterns
    #     """
    #     try:
    #         if historical_data.empty:
    #             return {}
            
    #         # Validate required columns
    #         required_cols = [time_column, 'num_bikes_available']
    #         self._validate_data(historical_data, required_cols, "Historical data")
            
    #         # Convert timestamp to datetime
    #         data = historical_data.copy()
    #         data['datetime'] = pd.to_datetime(data[time_column])
    #         data['hour'] = data['datetime'].dt.hour
    #         data['day_of_week'] = data['datetime'].dt.day_name()
    #         data['date'] = data['datetime'].dt.date
            
    #         patterns = {
    #             'hourly_usage': self._calculate_hourly_usage(data),
    #             'daily_usage': self._calculate_daily_usage(data),
    #             'weekly_usage': self._calculate_weekly_usage(data),
    #             'peak_hours': self._find_peak_hours(data),
    #             'peak_days': self._find_peak_days(data),
    #             'usage_trends': self._calculate_usage_trends(data),
    #             'seasonal_patterns': self._calculate_seasonal_patterns(data)
    #         }
            
    #         return patterns
            
    #     except Exception as e:
    #         print(f"Error calculating usage patterns: {e}")
    #         raise
    
    # def _calculate_hourly_usage(self, data: pd.DataFrame) -> pd.DataFrame:
    #     """Calculate average usage by hour."""
    #     hourly_stats = data.groupby('hour')['num_bikes_available'].agg([
    #         'mean', 'std', 'min', 'max', 'count'
    #     ]).reset_index()
    #     hourly_stats.columns = ['hour', 'avg_bikes', 'std_bikes', 'min_bikes', 'max_bikes', 'data_points']
    #     return hourly_stats.fillna(0)
    
    # def _calculate_daily_usage(self, data: pd.DataFrame) -> pd.DataFrame:
    #     """Calculate average usage by day of week."""
    #     daily_stats = data.groupby('day_of_week')['num_bikes_available'].agg([
    #         'mean', 'std', 'min', 'max', 'count'
    #     ]).reset_index()
    #     daily_stats.columns = ['day_of_week', 'avg_bikes', 'std_bikes', 'min_bikes', 'max_bikes', 'data_points']
    #     return daily_stats.fillna(0)
    
    # def _calculate_weekly_usage(self, data: pd.DataFrame) -> pd.DataFrame:
    #     """Calculate weekly usage patterns."""
    #     data['week'] = data['datetime'].dt.isocalendar().week
    #     weekly_stats = data.groupby('week')['num_bikes_available'].agg([
    #         'mean', 'std', 'min', 'max', 'count'
    #     ]).reset_index()
    #     weekly_stats.columns = ['week', 'avg_bikes', 'std_bikes', 'min_bikes', 'max_bikes', 'data_points']
    #     return weekly_stats.fillna(0)
    
    # def _find_peak_hours(self, data: pd.DataFrame, top_n: int = 3) -> List[int]:
    #     """Find peak usage hours."""
    #     hourly_avg = data.groupby('hour')['num_bikes_available'].mean()
    #     return hourly_avg.nlargest(top_n).index.tolist()
    
    # def _find_peak_days(self, data: pd.DataFrame, top_n: int = 3) -> List[str]:
    #     """Find peak usage days."""
    #     daily_avg = data.groupby('day_of_week')['num_bikes_available'].mean()
    #     return daily_avg.nlargest(top_n).index.tolist()
    
    # def _calculate_usage_trends(self, data: pd.DataFrame) -> Dict[str, float]:
    #     """Calculate usage trends over time."""
    #     data_sorted = data.sort_values('datetime')
    #     if len(data_sorted) < 2:
    #         return {'trend_slope': 0.0, 'trend_direction': 'insufficient_data'}
        
    #     # Calculate trend using linear regression
    #     x = np.arange(len(data_sorted))
    #     y = data_sorted['num_bikes_available'].values
        
    #     # Remove NaN values
    #     mask = ~np.isnan(y)
    #     if np.sum(mask) < 2:
    #         return {'trend_slope': 0.0, 'trend_direction': 'insufficient_data'}
        
    #     x_clean = x[mask]
    #     y_clean = y[mask]
        
    #     # Simple linear regression
    #     slope = np.polyfit(x_clean, y_clean, 1)[0]
        
    #     return {
    #         'trend_slope': float(slope),
    #         'trend_direction': 'increasing' if slope > 0.1 else 'decreasing' if slope < -0.1 else 'stable'
    #     }
    
    # def _calculate_seasonal_patterns(self, data: pd.DataFrame) -> Dict[str, Any]:
    #     """Calculate seasonal usage patterns."""
    #     if 'datetime' not in data.columns:
    #         return {}
        
    #     data['month'] = data['datetime'].dt.month
    #     data['season'] = data['month'].map({
    #         12: 'Winter', 1: 'Winter', 2: 'Winter',
    #         3: 'Spring', 4: 'Spring', 5: 'Spring',
    #         6: 'Summer', 7: 'Summer', 8: 'Summer',
    #         9: 'Fall', 10: 'Fall', 11: 'Fall'
    #     })
        
    #     seasonal_stats = data.groupby('season')['num_bikes_available'].agg([
    #         'mean', 'std', 'count'
    #     ]).reset_index()
    #     seasonal_stats.columns = ['season', 'avg_bikes', 'std_bikes', 'data_points']
        
    #     return seasonal_stats.to_dict('records')
    
    # def get_station_rankings(self, station_data: pd.DataFrame, 
    #                        metric: str = 'num_bikes_available', 
    #                        top_n: int = 10) -> pd.DataFrame:
    #     """
    #     Get station rankings by a specific metric.
        
    #     Args:
    #         station_data (pd.DataFrame): Station data
    #         metric (str): Metric to rank by
    #         top_n (int): Number of top stations to return
            
    #     Returns:
    #         pd.DataFrame: Ranked stations
    #     """
    #     try:
    #         if metric not in station_data.columns:
    #             raise ValueError(f"Metric '{metric}' not found in station data")
            
    #         # Get top N stations
    #         rankings = station_data.nlargest(top_n, metric)[['station_id', metric]].copy()
    #         rankings['rank'] = range(1, len(rankings) + 1)
    #         rankings['percentile'] = rankings[metric].rank(pct=True) * 100
            
    #         return rankings
            
    #     except Exception as e:
    #         print(f"Error getting station rankings: {e}")
    #         raise
    
    # def calculate_efficiency_metrics(self, station_data: pd.DataFrame) -> Dict[str, Any]:
    #     """
    #     Calculate system efficiency metrics.
        
    #     Args:
    #         station_data (pd.DataFrame): Station status data
            
    #     Returns:
    #         Dict containing efficiency metrics
    #     """
    #     try:
    #         total_capacity = station_data['num_bikes_available'] + station_data['num_docks_available']
    #         total_used = station_data['num_bikes_available']
            
    #         # Avoid division by zero
    #         efficiency_rates = np.where(total_capacity > 0, total_used / total_capacity, 0)
            
    #         efficiency_metrics = {
    #             'overall_efficiency': float(np.mean(efficiency_rates)),
    #             'efficiency_std': float(np.std(efficiency_rates)),
    #             'efficiency_median': float(np.median(efficiency_rates)),
    #             'stations_above_80_percent': int(np.sum(efficiency_rates > 0.8)),
    #             'stations_below_20_percent': int(np.sum(efficiency_rates < 0.2)),
    #             'balanced_stations': int(np.sum((efficiency_rates >= 0.2) & (efficiency_rates <= 0.8))),
    #             'efficiency_gini': self._calculate_gini_coefficient(efficiency_rates)
    #         }
            
    #         return efficiency_metrics
            
    #     except Exception as e:
    #         print(f"Error calculating efficiency metrics: {e}")
    #         raise


# Example usage and testing
if __name__ == "__main__":
    print("🚀 LastMile Metrics Module")
    print("-" * 30)

    # Parameters
    url = 'https://gbfs.baywheels.com/gbfs/2.3/gbfs.json'
    lang = 'en'
    db_path = 'lastmile-sf.db'

    # Initialize metrics
    metrics = LastMileMetrics(feeds_url=url, lang=lang, db_path=db_path)
    print(metrics.get_system_metrics())