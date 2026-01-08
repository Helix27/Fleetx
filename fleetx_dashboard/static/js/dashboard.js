/**
 * FleetX Dashboard - Main JavaScript
 */

// ============== GLOBALS ==============
let map;
let vehicleMarkers = {};
let vehiclesData = [];
let geofenceLayers = {};
let routePolyline = null;
let routeMarker = null;
let routeData = [];
let playbackIndex = 0;
let playbackInterval = null;
let isPlaying = false;
let selectedVehicleId = null;
let callerMarker = null;
let callerMode = false;
let drawControl = null;
let drawnItems;

// ============== INITIALIZATION ==============
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    loadVehicles();
    loadGeofences();
    loadOverviewStats();
    setupEventListeners();

    // Refresh data periodically
    setInterval(() => {
        loadVehicles();
        if (selectedVehicleId) {
            loadDispatchRankings();
        }
    }, 30000);
});

function initMap() {
    // Initialize map centered on India (default)
    map = L.map('map', {
        zoomControl: false
    }).setView([20.5937, 78.9629], 5);

    // Add minimal tile layer
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19
    }).addTo(map);

    // Add zoom control to bottom right
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Initialize draw layer for geofences
    drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    // Map click handler for caller location
    map.on('click', (e) => {
        if (callerMode) {
            setCallerLocation(e.latlng.lat, e.latlng.lng);
            callerMode = false;
            document.getElementById('caller-mode-btn').classList.remove('bg-gray-900', 'text-white');
        }
    });

    // Draw event handlers - use string event name for compatibility
    map.on('draw:created', function(e) {
        const layer = e.layer;
        drawnItems.addLayer(layer);
        openGeofenceModal(layer);
    });
}

function setupEventListeners() {
    // Geofence form submit
    document.getElementById('geofence-form').addEventListener('submit', saveGeofence);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeAllPanels();
        }
        if (e.key === ' ' && routeData.length > 0) {
            e.preventDefault();
            playbackControl('toggle');
        }
    });
}

// ============== VEHICLES ==============
async function loadVehicles() {
    try {
        const response = await fetch('/api/vehicles');
        vehiclesData = await response.json();
        updateVehicleMarkers();
        renderVehicleList();
        updateStatusCounts();
        populateVehicleSelects();
    } catch (error) {
        console.error('Failed to load vehicles:', error);
    }
}

function updateVehicleMarkers() {
    vehiclesData.forEach(vehicle => {
        if (!vehicle.latitude || !vehicle.longitude) return;

        const statusColor = getStatusColor(vehicle.status);

        if (vehicleMarkers[vehicle.id]) {
            // Update existing marker
            vehicleMarkers[vehicle.id].setLatLng([vehicle.latitude, vehicle.longitude]);
            vehicleMarkers[vehicle.id].getElement()?.querySelector('.marker-dot')?.style.setProperty('background', statusColor);
        } else {
            // Create new marker
            const icon = L.divIcon({
                className: 'vehicle-marker',
                html: `
                    <div class="relative">
                        <div class="marker-dot w-4 h-4 rounded-full border-2 border-white shadow-md" style="background: ${statusColor}"></div>
                        ${vehicle.status === 'RUNNING' ? '<div class="absolute inset-0 w-4 h-4 rounded-full animate-ping opacity-50" style="background: ' + statusColor + '"></div>' : ''}
                    </div>
                `,
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            });

            vehicleMarkers[vehicle.id] = L.marker([vehicle.latitude, vehicle.longitude], { icon })
                .addTo(map)
                .on('click', () => showVehicleStats(vehicle.id));
        }
    });
}

function getStatusColor(status) {
    switch (status?.toUpperCase()) {
        case 'RUNNING': return '#22c55e';
        case 'IDLE': return '#eab308';
        case 'STOPPED': return '#ef4444';
        default: return '#9ca3af';
    }
}

function renderVehicleList() {
    const container = document.getElementById('vehicle-list');
    container.innerHTML = vehiclesData.map(v => `
        <div class="vehicle-item p-4 border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors"
             onclick="showVehicleStats(${v.id})" data-name="${(v.name || v.number || '').toLowerCase()}">
            <div class="flex items-center justify-between mb-1">
                <span class="font-medium text-gray-900 text-sm">${v.number || v.name || 'Vehicle ' + v.id}</span>
                <span class="w-2 h-2 rounded-full" style="background: ${getStatusColor(v.status)}"></span>
            </div>
            <div class="text-xs text-gray-500">${v.driver || 'No driver'}</div>
            <div class="text-xs text-gray-400 mt-1 truncate">${v.address || 'Location unknown'}</div>
        </div>
    `).join('');
}

function filterVehicles(query) {
    const items = document.querySelectorAll('.vehicle-item');
    const q = query.toLowerCase();
    items.forEach(item => {
        const name = item.dataset.name || '';
        item.style.display = name.includes(q) ? 'block' : 'none';
    });
}

function updateStatusCounts() {
    const counts = { running: 0, idle: 0, stopped: 0 };
    vehiclesData.forEach(v => {
        const status = v.status?.toUpperCase();
        if (status === 'RUNNING') counts.running++;
        else if (status === 'IDLE') counts.idle++;
        else if (status === 'STOPPED') counts.stopped++;
    });
    document.getElementById('running-count').textContent = counts.running;
    document.getElementById('idle-count').textContent = counts.idle;
    document.getElementById('stopped-count').textContent = counts.stopped;
}

function populateVehicleSelects() {
    const options = vehiclesData.map(v =>
        `<option value="${v.id}">${v.number || v.name || 'Vehicle ' + v.id}</option>`
    ).join('');

    document.getElementById('geofence-vehicle').innerHTML = '<option value="">All Vehicles (Global)</option>' + options;
    document.getElementById('geofence-vehicle-filter').innerHTML = '<option value="">All Vehicles</option>' + options;
}

// ============== VEHICLE STATS ==============
async function showVehicleStats(vehicleId) {
    selectedVehicleId = vehicleId;

    // Close other panels and open stats
    closePanel('vehicles');
    closePanel('dispatch');
    closePanel('geofence');
    openPanel('stats');

    // Center map on vehicle
    const vehicle = vehiclesData.find(v => v.id === vehicleId);
    if (vehicle?.latitude && vehicle?.longitude) {
        map.flyTo([vehicle.latitude, vehicle.longitude], 14, { duration: 0.5 });
    }

    // Load stats
    try {
        const response = await fetch(`/api/vehicles/${vehicleId}/stats`);
        const stats = await response.json();
        renderVehicleStats(stats);

        // Load available dates for playback
        const datesResponse = await fetch(`/api/vehicles/${vehicleId}/route/dates`);
        const dates = await datesResponse.json();
        renderPlaybackDates(dates);
    } catch (error) {
        console.error('Failed to load vehicle stats:', error);
    }
}

function renderVehicleStats(stats) {
    document.getElementById('stats-vehicle-name').textContent =
        stats.vehicle.number || stats.vehicle.name || 'Vehicle ' + stats.vehicle.id;

    const container = document.getElementById('stats-content');
    container.innerHTML = `
        <!-- Vehicle Info -->
        <div class="space-y-2">
            <div class="flex justify-between text-sm">
                <span class="text-gray-500">Driver</span>
                <span class="text-gray-900 font-medium">${stats.vehicle.driver || 'Unassigned'}</span>
            </div>
            <div class="flex justify-between text-sm">
                <span class="text-gray-500">Make/Model</span>
                <span class="text-gray-900">${stats.vehicle.make || '-'} ${stats.vehicle.model || ''}</span>
            </div>
            <div class="flex justify-between text-sm">
                <span class="text-gray-500">Year</span>
                <span class="text-gray-900">${stats.vehicle.year || '-'}</span>
            </div>
        </div>

        <!-- Speed Stats -->
        <div>
            <h3 class="text-xs uppercase tracking-wider text-gray-400 mb-3">Speed Metrics</h3>
            <div class="grid grid-cols-3 gap-3">
                <div class="text-center p-3 bg-gray-50 rounded-lg">
                    <div class="text-xl font-light text-gray-900">${stats.speed.average}</div>
                    <div class="text-xs text-gray-500">Avg km/h</div>
                </div>
                <div class="text-center p-3 bg-gray-50 rounded-lg">
                    <div class="text-xl font-light text-gray-900">${stats.speed.max}</div>
                    <div class="text-xs text-gray-500">Max km/h</div>
                </div>
                <div class="text-center p-3 bg-gray-50 rounded-lg">
                    <div class="text-xl font-light text-gray-900">${stats.tripCount}</div>
                    <div class="text-xs text-gray-500">Trips</div>
                </div>
            </div>
        </div>

        <!-- Distance -->
        <div>
            <h3 class="text-xs uppercase tracking-wider text-gray-400 mb-3">Distance</h3>
            <div class="flex items-end gap-4">
                <div>
                    <div class="text-3xl font-light text-gray-900">${stats.distance.traveled.toLocaleString()}</div>
                    <div class="text-xs text-gray-500">km tracked</div>
                </div>
                <div class="text-sm text-gray-400 pb-1">
                    Odometer: ${stats.distance.currentOdometer?.toLocaleString() || 0} km
                </div>
            </div>
        </div>

        <!-- Status Distribution -->
        <div>
            <h3 class="text-xs uppercase tracking-wider text-gray-400 mb-3">Status Distribution</h3>
            <div class="space-y-2">
                ${renderStatusBars(stats.statusDistribution)}
            </div>
        </div>

        <!-- Hourly Activity Chart -->
        <div>
            <h3 class="text-xs uppercase tracking-wider text-gray-400 mb-3">Activity by Hour</h3>
            <canvas id="hourly-chart" height="120"></canvas>
        </div>

        <!-- Tracking Info -->
        <div class="text-xs text-gray-400 space-y-1">
            <div>First tracked: ${stats.tracking.firstSeen || '-'}</div>
            <div>Last update: ${stats.tracking.lastSeen || '-'}</div>
            <div>Total readings: ${stats.tracking.totalReadings?.toLocaleString() || 0}</div>
        </div>
    `;

    // Render hourly chart
    if (stats.hourlyActivity?.length > 0) {
        renderHourlyChart(stats.hourlyActivity);
    }

    // Show playback controls
    document.getElementById('playback-controls').classList.remove('hidden');
}

function renderStatusBars(distribution) {
    const total = Object.values(distribution).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(distribution).map(([status, count]) => {
        const percent = ((count / total) * 100).toFixed(1);
        return `
            <div class="flex items-center gap-2">
                <span class="w-16 text-xs text-gray-500">${status}</span>
                <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all" style="width: ${percent}%; background: ${getStatusColor(status)}"></div>
                </div>
                <span class="w-12 text-xs text-gray-500 text-right">${percent}%</span>
            </div>
        `;
    }).join('');
}

function renderHourlyChart(data) {
    const ctx = document.getElementById('hourly-chart')?.getContext('2d');
    if (!ctx) return;

    // Fill in missing hours
    const hourData = Array(24).fill(0);
    data.forEach(d => { hourData[d.hour] = d.avgSpeed || 0; });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: Array.from({ length: 24 }, (_, i) => i.toString().padStart(2, '0')),
            datasets: [{
                data: hourData,
                backgroundColor: '#e5e7eb',
                hoverBackgroundColor: '#111827',
                borderRadius: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 9 }, color: '#9ca3af' }
                },
                y: {
                    grid: { color: '#f3f4f6' },
                    ticks: { font: { size: 9 }, color: '#9ca3af' }
                }
            }
        }
    });
}

function renderPlaybackDates(dates) {
    const select = document.getElementById('playback-date');
    select.innerHTML = '<option value="">Select date</option>' +
        dates.map(d => `<option value="${d.date}">${d.date} (${d.points} points)</option>`).join('');
}

function closeStatsPanel() {
    closePanel('stats');
    clearRoute();
    selectedVehicleId = null;
}

// ============== ROUTE PLAYBACK ==============
async function loadRoute() {
    const date = document.getElementById('playback-date').value;
    if (!selectedVehicleId || !date) return;

    try {
        const response = await fetch(`/api/vehicles/${selectedVehicleId}/route?start=${date}&end=${date}T23:59:59`);
        let rawData = await response.json();

        if (rawData.length === 0) {
            document.getElementById('playback-info').textContent = 'No route data for this date';
            return;
        }

        // Clear previous route
        clearRoute();

        // Filter out invalid coordinates
        routeData = rawData.filter(p =>
            p.lat !== null && p.lng !== null &&
            p.lat !== undefined && p.lng !== undefined &&
            !isNaN(p.lat) && !isNaN(p.lng) &&
            Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180
        );

        if (routeData.length === 0) {
            document.getElementById('playback-info').textContent = 'No valid coordinates in route data';
            return;
        }

        // Draw route polyline
        const latlngs = routeData.map(p => [p.lat, p.lng]);
        routePolyline = L.polyline(latlngs, {
            color: '#111827',
            weight: 2,
            opacity: 0.6,
            dashArray: '5, 10'
        }).addTo(map);

        // Fit map to route only if bounds are valid
        const bounds = routePolyline.getBounds();
        if (bounds && bounds.isValid()) {
            map.fitBounds(bounds, { padding: [50, 50] });
        } else if (latlngs.length > 0) {
            // Fallback: center on first point
            map.setView(latlngs[0], 14);
        }

        // Create playback marker
        routeMarker = L.circleMarker(latlngs[0], {
            radius: 8,
            fillColor: '#111827',
            fillOpacity: 1,
            color: '#fff',
            weight: 2
        }).addTo(map);

        playbackIndex = 0;
        updatePlaybackUI();

        document.getElementById('playback-slider').max = routeData.length - 1;
        document.getElementById('playback-info').textContent = `${routeData.length} valid points loaded`;

    } catch (error) {
        console.error('Failed to load route:', error);
        document.getElementById('playback-info').textContent = 'Error loading route';
    }
}

function clearRoute() {
    if (routePolyline) {
        map.removeLayer(routePolyline);
        routePolyline = null;
    }
    if (routeMarker) {
        map.removeLayer(routeMarker);
        routeMarker = null;
    }
    routeData = [];
    playbackIndex = 0;
    stopPlayback();
}

function playbackControl(action) {
    switch (action) {
        case 'toggle':
            isPlaying ? stopPlayback() : startPlayback();
            break;
        case 'next':
            if (playbackIndex < routeData.length - 1) {
                playbackIndex++;
                updatePlaybackPosition();
            }
            break;
        case 'prev':
            if (playbackIndex > 0) {
                playbackIndex--;
                updatePlaybackPosition();
            }
            break;
    }
}

function startPlayback() {
    if (routeData.length === 0) return;
    isPlaying = true;
    updatePlayButton();

    playbackInterval = setInterval(() => {
        if (playbackIndex < routeData.length - 1) {
            playbackIndex++;
            updatePlaybackPosition();
        } else {
            stopPlayback();
        }
    }, 200);
}

function stopPlayback() {
    isPlaying = false;
    updatePlayButton();
    if (playbackInterval) {
        clearInterval(playbackInterval);
        playbackInterval = null;
    }
}

function updatePlayButton() {
    const btn = document.getElementById('play-btn');
    btn.innerHTML = isPlaying
        ? '<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/></svg>'
        : '<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
}

function seekPlayback(value) {
    playbackIndex = parseInt(value);
    updatePlaybackPosition();
}

function updatePlaybackPosition() {
    if (!routeMarker || !routeData[playbackIndex]) return;

    const point = routeData[playbackIndex];
    routeMarker.setLatLng([point.lat, point.lng]);
    updatePlaybackUI();
}

function updatePlaybackUI() {
    if (!routeData[playbackIndex]) return;

    const point = routeData[playbackIndex];
    document.getElementById('playback-slider').value = playbackIndex;

    const time = point.timestamp ? new Date(point.timestamp).toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit'
    }) : '--:--';
    document.getElementById('playback-time').textContent = time;

    document.getElementById('playback-info').innerHTML = `
        <span class="inline-block w-2 h-2 rounded-full mr-1" style="background: ${getStatusColor(point.status)}"></span>
        ${point.speed || 0} km/h · ${point.address || 'Unknown location'}
    `;
}

// ============== DISPATCH RANKINGS ==============
async function loadDispatchRankings(lat, lng) {
    try {
        let url = '/api/dispatch/rankings';
        if (lat && lng) {
            url += `?lat=${lat}&lng=${lng}`;
        }

        const response = await fetch(url);
        const rankings = await response.json();
        renderDispatchList(rankings);
    } catch (error) {
        console.error('Failed to load dispatch rankings:', error);
    }
}

function renderDispatchList(rankings) {
    const container = document.getElementById('dispatch-list');
    container.innerHTML = rankings.map((v, i) => `
        <div class="p-4 border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors"
             onclick="focusVehicle(${v.id})">
            <div class="flex items-start justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="w-6 h-6 flex items-center justify-center text-xs font-medium rounded-full ${i === 0 ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}">${i + 1}</span>
                    <div>
                        <div class="font-medium text-gray-900 text-sm">${v.number || v.name || 'Vehicle ' + v.id}</div>
                        <div class="text-xs text-gray-500">${v.driver || 'No driver'}</div>
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-lg font-light text-gray-900">${v.score}</div>
                    <div class="text-xs text-gray-400">score</div>
                </div>
            </div>
            <div class="flex items-center gap-4 text-xs text-gray-500">
                <span class="flex items-center gap-1">
                    <span class="w-2 h-2 rounded-full" style="background: ${getStatusColor(v.status)}"></span>
                    ${v.status || 'Unknown'}
                </span>
                ${v.distance !== null ? `<span>${v.distance} km away</span>` : ''}
                <span>${v.utilization24h}% util</span>
            </div>
        </div>
    `).join('');
}

function setCallerMode() {
    callerMode = !callerMode;
    const btn = document.getElementById('caller-mode-btn');
    if (callerMode) {
        btn.classList.add('bg-gray-900', 'text-white');
    } else {
        btn.classList.remove('bg-gray-900', 'text-white');
    }
}

function setCallerLocation(lat, lng) {
    // Remove existing marker
    if (callerMarker) {
        map.removeLayer(callerMarker);
    }

    // Add caller marker
    callerMarker = L.marker([lat, lng], {
        icon: L.divIcon({
            className: 'caller-marker',
            html: `
                <div class="relative">
                    <div class="w-8 h-8 rounded-full bg-blue-500 border-4 border-white shadow-lg flex items-center justify-center">
                        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
                        </svg>
                    </div>
                    <div class="absolute inset-0 w-8 h-8 rounded-full bg-blue-500 animate-ping opacity-30"></div>
                </div>
            `,
            iconSize: [32, 32],
            iconAnchor: [16, 16]
        })
    }).addTo(map);

    document.getElementById('caller-location').value = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;

    // Reload rankings with caller location
    loadDispatchRankings(lat, lng);
}

function focusVehicle(vehicleId) {
    const vehicle = vehiclesData.find(v => v.id === vehicleId);
    if (vehicle?.latitude && vehicle?.longitude) {
        map.flyTo([vehicle.latitude, vehicle.longitude], 15, { duration: 0.5 });
    }
}

// ============== GEOFENCING ==============
async function loadGeofences() {
    try {
        const response = await fetch('/api/geofences');
        const geofences = await response.json();
        renderGeofenceList(geofences);
        drawGeofencesOnMap(geofences);
    } catch (error) {
        console.error('Failed to load geofences:', error);
    }
}

function drawGeofencesOnMap(geofences) {
    // Clear existing
    Object.values(geofenceLayers).forEach(layer => map.removeLayer(layer));
    geofenceLayers = {};

    geofences.forEach(gf => {
        if (!gf.active) return;

        const layer = L.polygon(gf.coordinates, {
            color: gf.color,
            fillColor: gf.color,
            fillOpacity: 0.1,
            weight: 2
        }).addTo(map);

        layer.bindTooltip(gf.name, { permanent: false });
        geofenceLayers[gf.id] = layer;
    });
}

function renderGeofenceList(geofences) {
    const container = document.getElementById('geofence-list');
    container.innerHTML = geofences.map(gf => `
        <div class="p-4 border-b border-gray-50 hover:bg-gray-50">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="w-3 h-3 rounded" style="background: ${gf.color}"></span>
                    <span class="font-medium text-gray-900 text-sm">${gf.name}</span>
                </div>
                <div class="flex items-center gap-1">
                    <button onclick="editGeofence(${gf.id})" class="p-1 hover:bg-gray-200 rounded transition-colors">
                        <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/>
                        </svg>
                    </button>
                    <button onclick="deleteGeofence(${gf.id})" class="p-1 hover:bg-gray-200 rounded transition-colors">
                        <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="text-xs text-gray-500">
                ${gf.vehicleId ? 'Vehicle #' + gf.vehicleId : 'All vehicles'}
                · ${gf.alertOnEnter ? 'Enter' : ''} ${gf.alertOnExit ? 'Exit' : ''} alerts
            </div>
        </div>
    `).join('') || '<div class="p-4 text-sm text-gray-500">No geofences configured</div>';
}

function toggleGeofenceDraw() {
    if (drawControl) {
        map.removeControl(drawControl);
        drawControl = null;
        document.getElementById('draw-geofence-btn').textContent = '+ Draw';
        document.getElementById('draw-geofence-btn').classList.remove('bg-red-500');
        document.getElementById('draw-geofence-btn').classList.add('bg-gray-900');
    } else {
        drawControl = new L.Control.Draw({
            position: 'bottomleft',
            draw: {
                polygon: {
                    allowIntersection: false,
                    showArea: true,
                    shapeOptions: { color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.1, weight: 2 }
                },
                rectangle: {
                    showArea: true,
                    shapeOptions: { color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.1, weight: 2 }
                },
                circle: {
                    shapeOptions: { color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.1, weight: 2 }
                },
                polyline: false,
                marker: false,
                circlemarker: false
            },
            edit: { featureGroup: drawnItems }
        });
        map.addControl(drawControl);
        document.getElementById('draw-geofence-btn').textContent = 'Cancel';
        document.getElementById('draw-geofence-btn').classList.add('bg-red-500');
        document.getElementById('draw-geofence-btn').classList.remove('bg-gray-900');
    }
}

function openGeofenceModal(layer) {
    let coords = [];

    // Handle different layer types
    if (layer instanceof L.Circle) {
        // For circles, create a polygon approximation
        const center = layer.getLatLng();
        const radius = layer.getRadius();
        const points = 32;
        for (let i = 0; i < points; i++) {
            const angle = (i / points) * 2 * Math.PI;
            const lat = center.lat + (radius / 111320) * Math.cos(angle);
            const lng = center.lng + (radius / (111320 * Math.cos(center.lat * Math.PI / 180))) * Math.sin(angle);
            coords.push([lat, lng]);
        }
    } else if (layer.getLatLngs) {
        // For polygons and rectangles
        const latLngs = layer.getLatLngs();
        // Handle nested array structure
        const points = Array.isArray(latLngs[0]) ? latLngs[0] : latLngs;
        coords = points.map(ll => [ll.lat, ll.lng]);
    }

    document.getElementById('geofence-id').value = '';
    document.getElementById('geofence-coords').value = JSON.stringify(coords);
    document.getElementById('geofence-name').value = '';
    document.getElementById('geofence-vehicle').value = '';
    document.getElementById('geofence-color').value = '#3b82f6';
    document.getElementById('geofence-alert-enter').checked = true;
    document.getElementById('geofence-alert-exit').checked = true;
    document.getElementById('geofence-modal-title').textContent = 'New Geofence';

    document.getElementById('geofence-modal').classList.remove('hidden');

    // Remove draw control
    if (drawControl) {
        toggleGeofenceDraw();
    }
}

function closeGeofenceModal() {
    document.getElementById('geofence-modal').classList.add('hidden');
    drawnItems.clearLayers();
}

async function saveGeofence(e) {
    e.preventDefault();

    const id = document.getElementById('geofence-id').value;
    const data = {
        name: document.getElementById('geofence-name').value,
        vehicleId: document.getElementById('geofence-vehicle').value || null,
        coordinates: JSON.parse(document.getElementById('geofence-coords').value),
        color: document.getElementById('geofence-color').value,
        alertOnEnter: document.getElementById('geofence-alert-enter').checked,
        alertOnExit: document.getElementById('geofence-alert-exit').checked,
        active: true
    };

    try {
        const url = id ? `/api/geofences/${id}` : '/api/geofences';
        const method = id ? 'PUT' : 'POST';

        await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        closeGeofenceModal();
        loadGeofences();
    } catch (error) {
        console.error('Failed to save geofence:', error);
    }
}

async function editGeofence(id) {
    try {
        const response = await fetch('/api/geofences');
        const geofences = await response.json();
        const gf = geofences.find(g => g.id === id);
        if (!gf) return;

        document.getElementById('geofence-id').value = gf.id;
        document.getElementById('geofence-coords').value = JSON.stringify(gf.coordinates);
        document.getElementById('geofence-name').value = gf.name;
        document.getElementById('geofence-vehicle').value = gf.vehicleId || '';
        document.getElementById('geofence-color').value = gf.color;
        document.getElementById('geofence-alert-enter').checked = gf.alertOnEnter;
        document.getElementById('geofence-alert-exit').checked = gf.alertOnExit;
        document.getElementById('geofence-modal-title').textContent = 'Edit Geofence';

        document.getElementById('geofence-modal').classList.remove('hidden');
    } catch (error) {
        console.error('Failed to edit geofence:', error);
    }
}

async function deleteGeofence(id) {
    if (!confirm('Delete this geofence?')) return;

    try {
        await fetch(`/api/geofences/${id}`, { method: 'DELETE' });
        loadGeofences();
    } catch (error) {
        console.error('Failed to delete geofence:', error);
    }
}

function filterGeofences() {
    const vehicleId = document.getElementById('geofence-vehicle-filter').value;
    // Reload with filter
    fetch(`/api/geofences${vehicleId ? '?vehicle_id=' + vehicleId : ''}`)
        .then(r => r.json())
        .then(geofences => {
            renderGeofenceList(geofences);
            drawGeofencesOnMap(geofences);
        });
}

// ============== OVERVIEW STATS ==============
async function loadOverviewStats() {
    try {
        const response = await fetch('/api/stats/overview');
        const stats = await response.json();

        document.getElementById('stat-total-vehicles').textContent = stats.totalVehicles;
        document.getElementById('stat-avg-speed').innerHTML = `${stats.averageSpeed} <span class="text-sm">km/h</span>`;
        document.getElementById('stat-distance').innerHTML = `${stats.totalDistanceToday.toLocaleString()} <span class="text-sm">km</span>`;

        const available = (stats.statusCounts['IDLE'] || 0) + (stats.statusCounts['STOPPED'] || 0);
        document.getElementById('stat-available').textContent = available;
    } catch (error) {
        console.error('Failed to load overview stats:', error);
    }
}

// ============== PANEL MANAGEMENT ==============
function togglePanel(name) {
    const panel = document.getElementById(`panel-${name}`);
    const isOpen = panel.classList.contains('open');

    // Close all panels first
    closeAllPanels();

    if (!isOpen) {
        openPanel(name);
    }
}

function openPanel(name) {
    const panel = document.getElementById(`panel-${name}`);
    if (panel) {
        panel.classList.add('open');

        // Load dispatch data when opening dispatch panel
        if (name === 'dispatch') {
            loadDispatchRankings();
            document.getElementById('fleet-stats').classList.remove('hidden');
        }
    }
}

function closePanel(name) {
    const panel = document.getElementById(`panel-${name}`);
    if (panel) {
        panel.classList.remove('open');
    }
    if (name === 'dispatch') {
        document.getElementById('fleet-stats').classList.add('hidden');
    }
}

function closeAllPanels() {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('open'));
    document.getElementById('fleet-stats').classList.add('hidden');
}
