#!/usr/bin/env python3
"""
FleetX Vehicle Location Tracker (Optimized)
Uses Selenium only when needed to get token, then saves it for reuse
"""

import requests
import sqlite3
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fleetx_tracker.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class FleetXTracker:
    def __init__(self, config_path: str = 'config.json'):
        """Initialize the FleetX tracker with configuration"""
        self.config = self._load_config(config_path)
        self.session = requests.Session()
        self.access_token = None
        self.token_file = 'fleetx_token.json'
        self.db_conn = None
        self._setup_database()
        self._load_saved_token()
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from {config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def _load_saved_token(self):
        """Load saved token from file if it exists"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
                    self.access_token = token_data.get('access_token')
                    saved_time = token_data.get('saved_at', 0)
                    
                    # Check if token is recent (less than 12 hours old)
                    if time.time() - saved_time < 12 * 3600:
                        logger.info("Loaded saved access token")
                    else:
                        logger.info("Saved token is too old, will refresh")
                        self.access_token = None
        except Exception as e:
            logger.warning(f"Could not load saved token: {e}")
    
    def _save_token(self):
        """Save token to file for reuse"""
        try:
            token_data = {
                'access_token': self.access_token,
                'saved_at': time.time()
            }
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f)
            logger.info("Access token saved for future use")
        except Exception as e:
            logger.warning(f"Could not save token: {e}")
    
    def _setup_database(self):
        """Setup SQLite database and create tables if they don't exist"""
        try:
            db_path = self.config['database']['path']
            self.db_conn = sqlite3.connect(db_path, check_same_thread=False)
            cursor = self.db_conn.cursor()
            
            # Create main location history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vehicle_location_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetch_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    device_id TEXT,
                    account_id INTEGER,
                    vehicle_id INTEGER,
                    vehicle_number TEXT,
                    vehicle_name TEXT,
                    vehicle_make TEXT,
                    vehicle_model TEXT,
                    driver_name TEXT,
                    vehicle_year INTEGER,
                    group_id INTEGER,
                    driver_id INTEGER,
                    fuel_type TEXT,
                    type TEXT,
                    latitude REAL,
                    longitude REAL,
                    current_fuel_consumption REAL,
                    total_fuel_consumption REAL,
                    current_def_consumption REAL,
                    total_def_consumption REAL,
                    trip_ev_battery_consumed REAL,
                    trip_ev_battery_voltage_consumed REAL,
                    current_odometer REAL,
                    total_odometer REAL,
                    speed REAL,
                    timestamp TEXT,
                    create_date TEXT,
                    rpm TEXT,
                    status TEXT,
                    mileage REAL,
                    mileage_def REAL,
                    mileage_ev REAL,
                    mileage_ev_voltage REAL,
                    last_acc_on TEXT,
                    gear INTEGER,
                    rpm_slot INTEGER,
                    duration_engine_on INTEGER,
                    server_time BIGINT,
                    course REAL,
                    address TEXT,
                    other_attributes TEXT
                )
            ''')
            
            # Create index on vehicle_id and timestamp for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_vehicle_timestamp 
                ON vehicle_location_history(vehicle_id, timestamp)
            ''')
            
            self.db_conn.commit()
            logger.info(f"Database setup complete: {db_path}")
        except Exception as e:
            logger.error(f"Database setup failed: {e}")
            raise
    
    def login_with_selenium(self) -> bool:
        """Login to FleetX using Selenium and capture access token"""
        driver = None
        try:
            logger.info("Initializing Selenium WebDriver for login...")
            
            # Setup Chrome options for headless mode
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Initialize driver
            driver = webdriver.Chrome(options=chrome_options)
            
            logger.info("Navigating to login page...")
            login_url = self.config['api']['login_url']
            driver.get(login_url)
            
            # Wait for page to load
            wait = WebDriverWait(driver, 10)
            
            # Find and fill email field
            logger.info("Filling login form...")
            email_field = wait.until(
                EC.presence_of_element_located((By.NAME, "email"))
            )
            email_field.clear()
            email_field.send_keys(self.config['credentials']['email'])
            
            # Find and fill password field
            password_field = driver.find_element(By.NAME, "password")
            password_field.clear()
            password_field.send_keys(self.config['credentials']['password'])
            
            # Find and click submit button
            logger.info("Submitting login form...")
            submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()
            
            # Wait for redirect after login
            time.sleep(3)
            
            # Check if login was successful by checking URL
            current_url = driver.current_url
            logger.info(f"Current URL after login: {current_url}")
            
            if "login" in current_url.lower():
                logger.error("Login failed: Still on login page")
                return False
            
            # Extract access token from localStorage
            logger.info("Extracting access token from localStorage...")
            login_data = driver.execute_script(
                "return window.localStorage.getItem('reduxPersist:login');"
            )
            
            if login_data:
                login_obj = json.loads(login_data)
                self.access_token = login_obj.get('data', {}).get('access_token')
                
                if self.access_token:
                    logger.info(f"Successfully extracted access token: {self.access_token[:20]}...")
                    self._save_token()
                    return True
                else:
                    logger.error("Access token not found in localStorage")
                    return False
            else:
                logger.error("Could not retrieve login data from localStorage")
                return False
            
        except Exception as e:
            logger.error(f"Selenium login error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
        finally:
            # Close browser
            if driver:
                driver.quit()
    
    def fetch_vehicle_location(self, vehicle_id: int, timestamp: Optional[int] = None) -> Optional[Dict]:
        """Fetch vehicle location data from API"""
        try:
            if timestamp is None:
                timestamp = int(time.time() * 1000)  # Current timestamp in milliseconds
            
            url = f"{self.config['api']['base_url']}/api/v1/vehicles/history/location"
            params = {
                'vehicleId': vehicle_id,
                'time': timestamp
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            # Add access token to Authorization header
            if self.access_token:
                headers['Authorization'] = f'Bearer {self.access_token}'
            
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully fetched data for vehicle {vehicle_id}")
                return data
            elif response.status_code == 401 or response.status_code == 403:
                logger.warning(f"Authentication failed ({response.status_code}), token may be expired")
                # Clear saved token and try re-login
                self.access_token = None
                if os.path.exists(self.token_file):
                    os.remove(self.token_file)
                
                if self.login_with_selenium():
                    # Retry the request with new token
                    return self.fetch_vehicle_location(vehicle_id, timestamp)
                return None
            else:
                logger.error(f"Failed to fetch data for vehicle {vehicle_id}: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching vehicle location: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _get_last_record(self, vehicle_id: int) -> Optional[Dict]:
        """Get the last stored record for a vehicle"""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT device_id, account_id, vehicle_id, vehicle_number, vehicle_name,
                       vehicle_make, vehicle_model, driver_name, vehicle_year, group_id,
                       driver_id, fuel_type, type, latitude, longitude,
                       current_fuel_consumption, total_fuel_consumption,
                       current_def_consumption, total_def_consumption,
                       trip_ev_battery_consumed, trip_ev_battery_voltage_consumed,
                       current_odometer, total_odometer, speed, timestamp, create_date,
                       rpm, status, mileage, mileage_def, mileage_ev, mileage_ev_voltage,
                       last_acc_on, gear, rpm_slot, duration_engine_on,
                       server_time, course, address, other_attributes
                FROM vehicle_location_history
                WHERE vehicle_id = ?
                ORDER BY fetch_timestamp DESC
                LIMIT 1
            ''', (vehicle_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'deviceId': row[0],
                    'accountId': row[1],
                    'vehicleId': row[2],
                    'vehicleNumber': row[3],
                    'vehicleName': row[4],
                    'vehicleMake': row[5],
                    'vehicleModel': row[6],
                    'driverName': row[7],
                    'vehicleYear': row[8],
                    'groupId': row[9],
                    'driverId': row[10],
                    'fuelType': row[11],
                    'type': row[12],
                    'latitude': row[13],
                    'longitude': row[14],
                    'currentFuelConsumption': row[15],
                    'totalFuelConsumption': row[16],
                    'currentDEFConsumption': row[17],
                    'totalDEFConsumption': row[18],
                    'tripEVBatteryConsumed': row[19],
                    'tripEVBatteryVoltageConsumed': row[20],
                    'currentOdometer': row[21],
                    'totalOdometer': row[22],
                    'speed': row[23],
                    'timeStamp': row[24],
                    'createDate': row[25],
                    'rpm': row[26],
                    'status': row[27],
                    'mileage': row[28],
                    'mileageDEF': row[29],
                    'mileageEV': row[30],
                    'mileageEVVoltage': row[31],
                    'lastAccOn': row[32],
                    'gear': row[33],
                    'rpmSlot': row[34],
                    'durationEngineOn': row[35],
                    'serverTime': row[36],
                    'course': row[37],
                    'address': row[38],
                    'otherAttributes': json.loads(row[39]) if row[39] else {}
                }
            return None
        except Exception as e:
            logger.error(f"Error getting last record: {e}")
            return None
    
    def _has_data_changed(self, new_data: Dict, old_data: Optional[Dict]) -> bool:
        """Check if the new data is different from the old data"""
        if old_data is None:
            return True  # No previous data, so this is new
        
        # Compare key fields that indicate actual changes
        # Exclude timestamp fields as they always change
        compare_fields = [
            'latitude', 'longitude', 'speed', 'status', 'rpm',
            'currentFuelConsumption', 'totalFuelConsumption',
            'currentOdometer', 'totalOdometer', 'driverId',
            'course', 'address'
        ]
        
        for field in compare_fields:
            new_val = new_data.get(field)
            old_val = old_data.get(field)
            
            # Handle float comparison with small tolerance
            if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
                if abs(new_val - old_val) > 0.0001:
                    return True
            elif new_val != old_val:
                return True
        
        return False
    
    def store_location_data(self, data: Dict):
        """Store vehicle location data in SQLite database only if it has changed"""
        try:
            vehicle_id = data.get('vehicleId')
            
            # Get last stored record for this vehicle
            last_record = self._get_last_record(vehicle_id)
            
            # Check if data has changed
            if not self._has_data_changed(data, last_record):
                logger.info(f"No changes detected for vehicle {vehicle_id}, skipping storage")
                return
            
            cursor = self.db_conn.cursor()
            
            # Serialize other_attributes to JSON string
            other_attributes_json = json.dumps(data.get('otherAttributes', {}))
            
            cursor.execute('''
                INSERT INTO vehicle_location_history (
                    device_id, account_id, vehicle_id, vehicle_number, vehicle_name,
                    vehicle_make, vehicle_model, driver_name, vehicle_year, group_id,
                    driver_id, fuel_type, type, latitude, longitude,
                    current_fuel_consumption, total_fuel_consumption,
                    current_def_consumption, total_def_consumption,
                    trip_ev_battery_consumed, trip_ev_battery_voltage_consumed,
                    current_odometer, total_odometer, speed, timestamp, create_date,
                    rpm, status, mileage, mileage_def, mileage_ev, mileage_ev_voltage,
                    last_acc_on, gear, rpm_slot, duration_engine_on,
                    server_time, course, address, other_attributes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('deviceId'),
                data.get('accountId'),
                data.get('vehicleId'),
                data.get('vehicleNumber'),
                data.get('vehicleName'),
                data.get('vehicleMake'),
                data.get('vehicleModel'),
                data.get('driverName'),
                data.get('vehicleYear'),
                data.get('groupId'),
                data.get('driverId'),
                data.get('fuelType'),
                data.get('type'),
                data.get('latitude'),
                data.get('longitude'),
                data.get('currentFuelConsumption'),
                data.get('totalFuelConsumption'),
                data.get('currentDEFConsumption'),
                data.get('totalDEFConsumption'),
                data.get('tripEVBatteryConsumed'),
                data.get('tripEVBatteryVoltageConsumed'),
                data.get('currentOdometer'),
                data.get('totalOdometer'),
                data.get('speed'),
                data.get('timeStamp'),
                data.get('createDate'),
                data.get('rpm'),
                data.get('status'),
                data.get('mileage'),
                data.get('mileageDEF'),
                data.get('mileageEV'),
                data.get('mileageEVVoltage'),
                data.get('lastAccOn'),
                data.get('gear'),
                data.get('rpmSlot'),
                data.get('durationEngineOn'),
                data.get('serverTime'),
                data.get('course'),
                data.get('address'),
                other_attributes_json
            ))
            
            self.db_conn.commit()
            logger.info(f"Data stored for vehicle {data.get('vehicleId')} (changes detected)")
            
        except Exception as e:
            logger.error(f"Error storing data: {e}")
            self.db_conn.rollback()
    
    def run_periodic_fetch(self):
        """Run periodic fetching of vehicle location data"""
        logger.info("Starting FleetX Vehicle Location Tracker")
        
        # Check if we have a valid token, if not login
        if not self.access_token:
            logger.info("No saved token found, logging in...")
            if not self.login_with_selenium():
                logger.error("Initial login failed. Exiting.")
                return
        else:
            logger.info("Using saved access token")
        
        polling_interval = self.config.get('polling_interval_seconds', 300)
        vehicle_ids = self.config.get('vehicle_ids', [])
        
        logger.info(f"Monitoring {len(vehicle_ids)} vehicle(s)")
        logger.info(f"Polling interval: {polling_interval} seconds")
        
        try:
            while True:
                logger.info("--- Starting new fetch cycle ---")
                
                for vehicle_id in vehicle_ids:
                    logger.info(f"Fetching data for vehicle ID: {vehicle_id}")
                    data = self.fetch_vehicle_location(vehicle_id)
                    
                    if data:
                        self.store_location_data(data)
                    else:
                        logger.warning(f"No data retrieved for vehicle {vehicle_id}")
                    
                    # Small delay between vehicles
                    time.sleep(2)
                
                logger.info(f"Cycle complete. Waiting {polling_interval} seconds...")
                time.sleep(polling_interval)
                
        except KeyboardInterrupt:
            logger.info("Tracker stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        if self.db_conn:
            self.db_conn.close()
            logger.info("Database connection closed")


def main():
    """Main entry point"""
    tracker = FleetXTracker()
    tracker.run_periodic_fetch()


if __name__ == '__main__':
    main()