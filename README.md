# MausamPulse Live Road Safety

MausamPulse is a runnable proof of concept for real-time road-weather safety. It combines weather alerts, consent-aware vehicle tracking, braking and collision-risk analysis, low-visibility guidance, and crowdsourced pothole detection in one live dashboard.

This version is intentionally dependency-free: Python's standard library supplies the HTTP API, Server-Sent Events stream, SQLite database, dashboard server, and automated tests.

> **Safety boundary:** This is decision-support software, not a certified Advanced Driver Assistance System (ADAS), emergency service, or autonomous braking controller. It must not control a vehicle or encourage a driver to look at a screen while driving.

## What works

| Requirement | MVP implementation | Important boundary |
|---|---|---|
| Rain, fog, and other weather alerts | Geofenced alerts for rain, heavy rain, fog, storms, lightning, flooding, heat/cold, wind, dust, hail, snow, cyclone, and ice | The demo uses synthetic alerts; connect approved official feeds for deployment |
| Collision calculation | Time-to-collision from lead distance, own speed, and lead speed | Own speed alone cannot calculate collision risk |
| Braking at a traffic light | Stop-line status, required deceleration, phone-derived braking estimate, and optional OBD/CAN pressure input | Exact pedal/pressure data requires a supported vehicle signal; phone GPS provides only an estimate |
| Vehicle and user names | Authorized owners see full registered details; public views show only consented display identity | Names, registration numbers, contacts, and precise positions are never universally public |
| Rain/fog visibility assistance | Safe-speed guidance based on stopping distance, visibility, road condition, and speed limit | GPS cannot detect nearby obstacles; safety-grade detection needs radar/camera/V2X |
| Pothole locations | Manual, camera, or phone-IMU reports clustered within 25 m and promoted through corroboration | One signal remains unverified; repeated independent vehicles increase confidence |
| Familiar live map | Interactive road and satellite maps with drag, zoom, hazard layers, live markers, focus controls, and an offline visual fallback | Online tiles use OpenStreetMap and Esri with visible attribution; no Google API key is required |
| Personal route tracking | Browser GPS filters weather alerts and potholes within 25 km and highlights nearby rain/fog guidance | With permission, position is sent to the current app server for proximity filtering but is not stored by this tracker |
| App-style UI | Responsive light/dark interface using white, black, blue, green, yellow, and red safety states | Designed for pre-trip use or a passenger; drivers must not operate the screen while moving |

## Start in under a minute

Requires Python 3.11 or newer. No packages need to be installed.

```bash
python3 -m app
```

Open `http://localhost:8080`. The default demo starts two synthetic vehicles, heavy-rain and fog alerts, traffic-light braking, changing collision risk, and occasional pothole signals.

For the presentation, open the dashboard and use **Map / Satellite**, toggle the three live layers, select a vehicle marker, and choose **Asha owner view** in the presentation controls to show precise owner-authorized identity and telemetry. **Track me** uses browser location permission to follow local rain, fog, and nearby potholes.

The road and satellite imagery needs an internet connection. If tiles are unavailable, the live vehicle, weather, and pothole overlays continue to work on the built-in fallback map.

The local demonstration API key is `demo-local-key`. Change it before any shared deployment.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

The Compose configuration binds the service to `127.0.0.1` by default so development data is not exposed across the network.

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers collision calculations, wet-weather stopping distance, visibility guidance, exact-versus-estimated braking labels, pothole corroboration, identity privacy, ownership enforcement, authentication, and live API flows.

## Telemetry example

```bash
curl -X POST http://localhost:8080/api/telemetry \
  -H 'Authorization: Bearer demo-local-key' \
  -H 'Content-Type: application/json' \
  -d '{
    "vehicle_id": "veh_asha",
    "user_id": "usr_asha",
    "latitude": 19.0760,
    "longitude": 72.8777,
    "speed_kph": 46,
    "visibility_m": 75,
    "weather_condition": "heavy_rain",
    "speed_limit_kph": 50,
    "traffic_light_state": "red",
    "distance_to_stop_line_m": 22,
    "lead_vehicle_distance_m": 18,
    "lead_vehicle_speed_kph": 25,
    "brake_pressure_pct": 54,
    "brake_sensor_source": "obd_can",
    "vertical_acceleration_g": 0.12
  }'
```

The response contains separate `collision`, `braking`, `visibility`, and nearby `weather_alerts` assessments. If `brake_pressure_pct` is omitted, the service may estimate deceleration from consecutive speeds, but it never invents a pedal-pressure percentage.

## Main API routes

| Method and route | Purpose |
|---|---|
| `GET /api/state` | Dashboard snapshot with consent-filtered identities |
| `GET /api/events` | Live Server-Sent Events stream |
| `GET /api/weather-alerts` | Active alerts, optionally filtered by `lat` and `lon` |
| `GET /api/potholes` | Road defects, optionally filtered by location and radius |
| `POST /api/users` | Register a user and sharing choice |
| `POST /api/vehicles` | Register a vehicle to an existing user |
| `POST /api/telemetry` | Submit a sensor sample and receive safety assessments |
| `POST /api/weather-alerts` | Ingest an official or operator alert |
| `POST /api/potholes` | Submit a manual/camera pothole report |
| `POST /api/demo/seed` | Create or reset demo records |
| `POST /api/demo/step` | Generate one synthetic update |

`GET /api/schema` provides an online route summary. Mutating routes require `Authorization: Bearer <MAUSAM_API_KEY>`.

## Project structure

```text
app/
  api.py          HTTP, SSE, static dashboard, and authentication
  database.py     SQLite schema, queries, pothole clustering, and privacy data
  engine.py       Collision, braking, visibility, distance, and confidence math
  models.py       Input validation and accepted event types
  service.py      Business workflow and consent-filtered state
  simulator.py    Synthetic rain, fog, braking, TTC, and pothole telemetry
  static/         Responsive real-time dashboard
tests/            Standard-library unit and API integration tests
docs/             Architecture, hardware, privacy, and API guidance
```

## Relationship to the original MausamPulse data plane

This is a self-contained MVP built because the supplied project contained only a README and Docker Compose file, not the referenced services. The original Kafka/PostGIS/ClickHouse/OpenSearch/Flink architecture remains suitable for large-scale deployment.

The recommended integration path is:

1. Publish device input to `vehicle.telemetry.raw` in Kafka.
2. Run these deterministic calculations as a partitioned consumer keyed by `vehicle_id`.
3. Publish warnings to `road.safety.alerts` and pothole evidence to `road.hazards`.
4. Store canonical live state in PostGIS and high-volume telemetry in ClickHouse.
5. Use the existing weather processor to populate the alert/geofence input.
6. Replace the demo bearer key with OIDC/SSO, per-device credentials, and role-based access.

## Before real-road deployment

- Validate every supported vehicle signal against its manufacturer documentation. Generic OBD-II does not guarantee brake-pressure or pedal-position availability.
- Use a certified hardware/ADAS partner for radar, camera, V2X, or automatic braking functions.
- Add signed device identities, replay protection, encryption, data minimization, retention/deletion workflows, and auditable consent.
- Integrate authoritative weather and traffic-signal sources under their permitted terms.
- Conduct sensor calibration, false-alert, latency, load, cybersecurity, privacy, and road-safety testing.
- Arrange legal, regulatory, insurance, emergency-response, and 24×7 operational ownership before public use.

See [hardware integration](docs/HARDWARE-INTEGRATION.md), [privacy and safety](docs/PRIVACY-SAFETY.md), and [architecture](docs/ARCHITECTURE.md) for the next implementation phase.
