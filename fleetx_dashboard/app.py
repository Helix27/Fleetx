#!/usr/bin/env python3
"""
FleetX Dashboard - Flask Application
Vehicle route playback, geofencing, and decision-making stats
"""

from flask import Flask, render_template, jsonify, request
import sqlite3
import json
from datetime import datetime, timedelta
from functools import wraps
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fleetx-dashboard-secret'

# Database path - adjust if needed
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fleetx_data.db')
GEOFENCE_DB = os.path.join(os.path.dirname(__file__), 'geofences.db')


def get_db_connection():
    """Get connection to the main FleetX database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_geofence_db():
    """Get connection to geofence database"""
    conn = sqlite3.connect(GEOFENCE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_geofence_db():
    """Initialize geofence database"""
    conn = get_geofence_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS geofences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'polygon',
            coordinates TEXT NOT NULL,
            color TEXT DEFAULT '#3b82f6',
            alert_on_enter INTEGER DEFAULT 1,
            alert_on_exit INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


init_geofence_db()


# ============== PAGES ==============

@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')


# ============== VEHICLE API ==============

@app.route('/api/vehicles')
def get_vehicles():
    """Get list of all vehicles with latest position"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT vehicle_id, vehicle_number, vehicle_name,
               vehicle_make, vehicle_model, driver_name
        FROM vehicle_location_history
        GROUP BY vehicle_id
    ''')

    vehicles = []
    for row in cursor.fetchall():
        # Get latest position for each vehicle
        cursor.execute('''
            SELECT latitude, longitude, speed, status, address,
                   timestamp, total_odometer, current_odometer
            FROM vehicle_location_history
            WHERE vehicle_id = ?
            ORDER BY fetch_timestamp DESC
            LIMIT 1
        ''', (row['vehicle_id'],))

        latest = cursor.fetchone()
        vehicles.append({
            'id': row['vehicle_id'],
            'number': row['vehicle_number'],
            'name': row['vehicle_name'],
            'make': row['vehicle_make'],
            'model': row['vehicle_model'],
            'driver': row['driver_name'],
            'latitude': latest['latitude'] if latest else None,
            'longitude': latest['longitude'] if latest else None,
            'speed': latest['speed'] if latest else 0,
            'status': latest['status'] if latest else 'unknown',
            'address': latest['address'] if latest else '',
            'lastUpdate': latest['timestamp'] if latest else None,
            'totalOdometer': latest['total_odometer'] if latest else 0,
            'currentOdometer': latest['current_odometer'] if latest else 0
        })

    conn.close()
    return jsonify(vehicles)


@app.route('/api/vehicles/<int:vehicle_id>/stats')
def get_vehicle_stats(vehicle_id):
    """Get comprehensive stats for a vehicle"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Basic info
    cursor.execute('''
        SELECT vehicle_number, vehicle_name, vehicle_make, vehicle_model,
               driver_name, vehicle_year
        FROM vehicle_location_history
        WHERE vehicle_id = ?
        ORDER BY fetch_timestamp DESC
        LIMIT 1
    ''', (vehicle_id,))

    info = cursor.fetchone()
    if not info:
        conn.close()
        return jsonify({'error': 'Vehicle not found'}), 404

    # Speed statistics
    cursor.execute('''
        SELECT
            AVG(speed) as avg_speed,
            MAX(speed) as max_speed,
            MIN(CASE WHEN speed > 0 THEN speed END) as min_moving_speed
        FROM vehicle_location_history
        WHERE vehicle_id = ?
    ''', (vehicle_id,))
    speed_stats = cursor.fetchone()

    # Odometer range (distance traveled in tracked period)
    cursor.execute('''
        SELECT
            MIN(total_odometer) as start_odometer,
            MAX(total_odometer) as end_odometer
        FROM vehicle_location_history
        WHERE vehicle_id = ? AND total_odometer > 0
    ''', (vehicle_id,))
    odo_stats = cursor.fetchone()

    # Status distribution
    cursor.execute('''
        SELECT status, COUNT(*) as count
        FROM vehicle_location_history
        WHERE vehicle_id = ?
        GROUP BY status
    ''', (vehicle_id,))
    status_dist = {row['status']: row['count'] for row in cursor.fetchall()}

    # Activity by hour (for dispatch optimization)
    cursor.execute('''
        SELECT
            CAST(strftime('%H', fetch_timestamp) AS INTEGER) as hour,
            AVG(speed) as avg_speed,
            COUNT(*) as readings
        FROM vehicle_location_history
        WHERE vehicle_id = ?
        GROUP BY hour
        ORDER BY hour
    ''', (vehicle_id,))
    hourly_activity = [{'hour': row['hour'], 'avgSpeed': row['avg_speed'],
                        'readings': row['readings']} for row in cursor.fetchall()]

    # Recent trips count (based on status changes)
    cursor.execute('''
        SELECT COUNT(*) as trip_count
        FROM (
            SELECT status, LAG(status) OVER (ORDER BY fetch_timestamp) as prev_status
            FROM vehicle_location_history
            WHERE vehicle_id = ?
        )
        WHERE status = 'RUNNING' AND prev_status != 'RUNNING'
    ''', (vehicle_id,))
    trip_result = cursor.fetchone()

    # Total tracked time
    cursor.execute('''
        SELECT
            MIN(fetch_timestamp) as first_seen,
            MAX(fetch_timestamp) as last_seen,
            COUNT(*) as total_readings
        FROM vehicle_location_history
        WHERE vehicle_id = ?
    ''', (vehicle_id,))
    time_stats = cursor.fetchone()

    conn.close()

    distance_traveled = 0
    if odo_stats['end_odometer'] and odo_stats['start_odometer']:
        distance_traveled = odo_stats['end_odometer'] - odo_stats['start_odometer']

    return jsonify({
        'vehicle': {
            'id': vehicle_id,
            'number': info['vehicle_number'],
            'name': info['vehicle_name'],
            'make': info['vehicle_make'],
            'model': info['vehicle_model'],
            'driver': info['driver_name'],
            'year': info['vehicle_year']
        },
        'speed': {
            'average': round(speed_stats['avg_speed'] or 0, 1),
            'max': round(speed_stats['max_speed'] or 0, 1),
            'minMoving': round(speed_stats['min_moving_speed'] or 0, 1)
        },
        'distance': {
            'traveled': round(distance_traveled, 2),
            'currentOdometer': odo_stats['end_odometer'] or 0
        },
        'statusDistribution': status_dist,
        'hourlyActivity': hourly_activity,
        'tripCount': trip_result['trip_count'] if trip_result else 0,
        'tracking': {
            'firstSeen': time_stats['first_seen'],
            'lastSeen': time_stats['last_seen'],
            'totalReadings': time_stats['total_readings']
        }
    })


# ============== ROUTE PLAYBACK API ==============

@app.route('/api/vehicles/<int:vehicle_id>/route')
def get_vehicle_route(vehicle_id):
    """Get route history for playback"""
    start_time = request.args.get('start')
    end_time = request.args.get('end')
    limit = request.args.get('limit', 1000, type=int)

    conn = get_db_connection()
    cursor = conn.cursor()

    query = '''
        SELECT latitude, longitude, speed, status, address,
               timestamp, fetch_timestamp, course, total_odometer
        FROM vehicle_location_history
        WHERE vehicle_id = ?
    '''
    params = [vehicle_id]

    if start_time:
        query += ' AND fetch_timestamp >= ?'
        params.append(start_time)
    if end_time:
        query += ' AND fetch_timestamp <= ?'
        params.append(end_time)

    query += ' ORDER BY fetch_timestamp ASC LIMIT ?'
    params.append(limit)

    cursor.execute(query, params)

    route = []
    for row in cursor.fetchall():
        route.append({
            'lat': row['latitude'],
            'lng': row['longitude'],
            'speed': row['speed'],
            'status': row['status'],
            'address': row['address'],
            'timestamp': row['timestamp'],
            'fetchTime': row['fetch_timestamp'],
            'course': row['course'],
            'odometer': row['total_odometer']
        })

    conn.close()
    return jsonify(route)


@app.route('/api/vehicles/<int:vehicle_id>/route/dates')
def get_available_dates(vehicle_id):
    """Get available dates for route playback"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT DISTINCT DATE(fetch_timestamp) as date,
               COUNT(*) as points
        FROM vehicle_location_history
        WHERE vehicle_id = ?
        GROUP BY DATE(fetch_timestamp)
        ORDER BY date DESC
    ''', (vehicle_id,))

    dates = [{'date': row['date'], 'points': row['points']} for row in cursor.fetchall()]
    conn.close()
    return jsonify(dates)


# ============== GEOFENCING API ==============

@app.route('/api/geofences', methods=['GET'])
def get_geofences():
    """Get all geofences or filter by vehicle"""
    vehicle_id = request.args.get('vehicle_id', type=int)

    conn = get_geofence_db()
    cursor = conn.cursor()

    if vehicle_id:
        cursor.execute('SELECT * FROM geofences WHERE vehicle_id = ? OR vehicle_id IS NULL',
                       (vehicle_id,))
    else:
        cursor.execute('SELECT * FROM geofences')

    geofences = []
    for row in cursor.fetchall():
        geofences.append({
            'id': row['id'],
            'vehicleId': row['vehicle_id'],
            'name': row['name'],
            'type': row['type'],
            'coordinates': json.loads(row['coordinates']),
            'color': row['color'],
            'alertOnEnter': bool(row['alert_on_enter']),
            'alertOnExit': bool(row['alert_on_exit']),
            'active': bool(row['active']),
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at']
        })

    conn.close()
    return jsonify(geofences)


@app.route('/api/geofences', methods=['POST'])
def create_geofence():
    """Create a new geofence"""
    data = request.json

    conn = get_geofence_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO geofences (vehicle_id, name, type, coordinates, color,
                              alert_on_enter, alert_on_exit, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('vehicleId'),
        data.get('name', 'Unnamed Geofence'),
        data.get('type', 'polygon'),
        json.dumps(data.get('coordinates', [])),
        data.get('color', '#3b82f6'),
        1 if data.get('alertOnEnter', True) else 0,
        1 if data.get('alertOnExit', True) else 0,
        1 if data.get('active', True) else 0
    ))

    geofence_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({'id': geofence_id, 'message': 'Geofence created'}), 201


@app.route('/api/geofences/<int:geofence_id>', methods=['PUT'])
def update_geofence(geofence_id):
    """Update a geofence"""
    data = request.json

    conn = get_geofence_db()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE geofences SET
            vehicle_id = ?,
            name = ?,
            type = ?,
            coordinates = ?,
            color = ?,
            alert_on_enter = ?,
            alert_on_exit = ?,
            active = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (
        data.get('vehicleId'),
        data.get('name'),
        data.get('type'),
        json.dumps(data.get('coordinates', [])),
        data.get('color'),
        1 if data.get('alertOnEnter', True) else 0,
        1 if data.get('alertOnExit', True) else 0,
        1 if data.get('active', True) else 0,
        geofence_id
    ))

    conn.commit()
    conn.close()

    return jsonify({'message': 'Geofence updated'})


@app.route('/api/geofences/<int:geofence_id>', methods=['DELETE'])
def delete_geofence(geofence_id):
    """Delete a geofence"""
    conn = get_geofence_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM geofences WHERE id = ?', (geofence_id,))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Geofence deleted'})


# ============== DISPATCH DECISION API ==============

@app.route('/api/dispatch/rankings')
def get_dispatch_rankings():
    """Get vehicle rankings for dispatch decisions"""
    caller_lat = request.args.get('lat', type=float)
    caller_lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all vehicles with their latest positions
    cursor.execute('''
        SELECT v.vehicle_id, v.vehicle_number, v.vehicle_name, v.driver_name,
               v.latitude, v.longitude, v.speed, v.status, v.address
        FROM vehicle_location_history v
        INNER JOIN (
            SELECT vehicle_id, MAX(fetch_timestamp) as max_time
            FROM vehicle_location_history
            GROUP BY vehicle_id
        ) latest ON v.vehicle_id = latest.vehicle_id
                 AND v.fetch_timestamp = latest.max_time
    ''')

    vehicles = []
    for row in cursor.fetchall():
        vehicle = {
            'id': row['vehicle_id'],
            'number': row['vehicle_number'],
            'name': row['vehicle_name'],
            'driver': row['driver_name'],
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'speed': row['speed'],
            'status': row['status'],
            'address': row['address'],
            'distance': None,
            'score': 100  # Base score
        }

        # Calculate distance if caller location provided
        if caller_lat and caller_lng and row['latitude'] and row['longitude']:
            # Haversine formula approximation (km)
            import math
            lat1, lon1 = math.radians(caller_lat), math.radians(caller_lng)
            lat2, lon2 = math.radians(row['latitude']), math.radians(row['longitude'])

            dlat = lat2 - lat1
            dlon = lon2 - lon1

            a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            vehicle['distance'] = round(6371 * c, 2)  # Earth radius in km

            # Adjust score based on distance (closer = higher score)
            vehicle['score'] -= min(vehicle['distance'] * 2, 50)

        # Adjust score based on status
        if row['status'] == 'IDLE':
            vehicle['score'] += 20  # Prefer idle vehicles
        elif row['status'] == 'RUNNING':
            vehicle['score'] -= 10  # Slightly lower for running
        elif row['status'] == 'STOPPED':
            vehicle['score'] += 10

        # Get utilization stats for this vehicle
        cursor.execute('''
            SELECT
                COUNT(*) as total_readings,
                SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) as running_count
            FROM vehicle_location_history
            WHERE vehicle_id = ?
            AND fetch_timestamp > datetime('now', '-24 hours')
        ''', (row['vehicle_id'],))

        util = cursor.fetchone()
        if util and util['total_readings'] > 0:
            utilization = (util['running_count'] / util['total_readings']) * 100
            vehicle['utilization24h'] = round(utilization, 1)
            # Prefer less utilized vehicles
            vehicle['score'] -= utilization * 0.3
        else:
            vehicle['utilization24h'] = 0

        vehicle['score'] = round(max(0, vehicle['score']), 1)
        vehicles.append(vehicle)

    # Sort by score descending
    vehicles.sort(key=lambda x: x['score'], reverse=True)

    conn.close()
    return jsonify(vehicles)


@app.route('/api/stats/overview')
def get_overview_stats():
    """Get fleet overview statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Total vehicles
    cursor.execute('SELECT COUNT(DISTINCT vehicle_id) as count FROM vehicle_location_history')
    total_vehicles = cursor.fetchone()['count']

    # Current status distribution
    cursor.execute('''
        SELECT v.status, COUNT(*) as count
        FROM vehicle_location_history v
        INNER JOIN (
            SELECT vehicle_id, MAX(fetch_timestamp) as max_time
            FROM vehicle_location_history
            GROUP BY vehicle_id
        ) latest ON v.vehicle_id = latest.vehicle_id
                 AND v.fetch_timestamp = latest.max_time
        GROUP BY v.status
    ''')
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

    # Average speed of moving vehicles
    cursor.execute('''
        SELECT AVG(v.speed) as avg_speed
        FROM vehicle_location_history v
        INNER JOIN (
            SELECT vehicle_id, MAX(fetch_timestamp) as max_time
            FROM vehicle_location_history
            GROUP BY vehicle_id
        ) latest ON v.vehicle_id = latest.vehicle_id
                 AND v.fetch_timestamp = latest.max_time
        WHERE v.speed > 0
    ''')
    avg_speed = cursor.fetchone()['avg_speed'] or 0

    # Total distance tracked today
    cursor.execute('''
        SELECT SUM(max_odo - min_odo) as total_distance
        FROM (
            SELECT vehicle_id,
                   MAX(total_odometer) as max_odo,
                   MIN(total_odometer) as min_odo
            FROM vehicle_location_history
            WHERE DATE(fetch_timestamp) = DATE('now')
            AND total_odometer > 0
            GROUP BY vehicle_id
        )
    ''')
    total_distance = cursor.fetchone()['total_distance'] or 0

    conn.close()

    return jsonify({
        'totalVehicles': total_vehicles,
        'statusCounts': status_counts,
        'averageSpeed': round(avg_speed, 1),
        'totalDistanceToday': round(total_distance, 2)
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
