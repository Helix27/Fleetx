#!/usr/bin/env python3
"""
FleetX Data Query Utility
Query and analyze stored vehicle location data
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict
import sys


class FleetXDataQuery:
    def __init__(self, db_path: str = 'fleetx_data.db'):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
    
    def get_latest_locations(self, limit: int = 10) -> List[Dict]:
        """Get latest location records"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM vehicle_location_history
            ORDER BY fetch_timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        results = []
        for row in cursor.fetchall():
            results.append(dict(row))
        return results
    
    def get_vehicle_history(self, vehicle_id: int, hours: int = 24) -> List[Dict]:
        """Get location history for a specific vehicle"""
        cursor = self.conn.cursor()
        time_threshold = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT * FROM vehicle_location_history
            WHERE vehicle_id = ?
            AND fetch_timestamp >= ?
            ORDER BY fetch_timestamp DESC
        ''', (vehicle_id, time_threshold.isoformat()))
        
        results = []
        for row in cursor.fetchall():
            results.append(dict(row))
        return results
    
    def get_vehicle_summary(self, vehicle_id: int) -> Dict:
        """Get summary statistics for a vehicle"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(*) as record_count,
                MIN(fetch_timestamp) as first_record,
                MAX(fetch_timestamp) as last_record,
                vehicle_number,
                vehicle_name,
                vehicle_make,
                vehicle_model
            FROM vehicle_location_history
            WHERE vehicle_id = ?
            GROUP BY vehicle_id
        ''', (vehicle_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
    
    def get_all_vehicles(self) -> List[int]:
        """Get list of all vehicle IDs in database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT vehicle_id 
            FROM vehicle_location_history
            ORDER BY vehicle_id
        ''')
        return [row[0] for row in cursor.fetchall()]
    
    def get_records_count(self) -> int:
        """Get total number of records in database"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM vehicle_location_history')
        return cursor.fetchone()[0]
    
    def export_to_json(self, output_file: str, vehicle_id: int = None, limit: int = None):
        """Export data to JSON file"""
        if vehicle_id:
            data = self.get_vehicle_history(vehicle_id, hours=24*365)  # All records
        else:
            cursor = self.conn.cursor()
            query = 'SELECT * FROM vehicle_location_history ORDER BY fetch_timestamp DESC'
            if limit:
                query += f' LIMIT {limit}'
            cursor.execute(query)
            data = [dict(row) for row in cursor.fetchall()]
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"Exported {len(data)} records to {output_file}")
    
    def close(self):
        """Close database connection"""
        self.conn.close()


def main():
    """Main entry point for query utility"""
    query = FleetXDataQuery()
    
    print("=" * 60)
    print("FleetX Data Query Utility")
    print("=" * 60)
    
    # Show summary
    total_records = query.get_records_count()
    print(f"\nTotal records in database: {total_records}")
    
    vehicles = query.get_all_vehicles()
    print(f"Vehicles tracked: {len(vehicles)}")
    
    if vehicles:
        print("\nVehicle IDs:", ", ".join(map(str, vehicles)))
        
        print("\n" + "=" * 60)
        print("Vehicle Summaries")
        print("=" * 60)
        
        for vehicle_id in vehicles:
            summary = query.get_vehicle_summary(vehicle_id)
            if summary:
                print(f"\nVehicle ID: {vehicle_id}")
                print(f"  Number: {summary.get('vehicle_number')}")
                print(f"  Name: {summary.get('vehicle_name')}")
                print(f"  Make/Model: {summary.get('vehicle_make')} {summary.get('vehicle_model')}")
                print(f"  Records: {summary.get('record_count')}")
                print(f"  First Record: {summary.get('first_record')}")
                print(f"  Last Record: {summary.get('last_record')}")
        
        # Show latest records
        print("\n" + "=" * 60)
        print("Latest 5 Records")
        print("=" * 60)
        
        latest = query.get_latest_locations(5)
        for i, record in enumerate(latest, 1):
            print(f"\n{i}. Vehicle {record['vehicle_number']} ({record['vehicle_id']})")
            print(f"   Status: {record['status']}")
            print(f"   Location: {record['latitude']}, {record['longitude']}")
            print(f"   Speed: {record['speed']} km/h")
            print(f"   Time: {record['timestamp']}")
            print(f"   Address: {record['address']}")
    
    query.close()


if __name__ == '__main__':
    main()
