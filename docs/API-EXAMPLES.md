# API examples

Set a convenience variable for a local shell:

```bash
MAUSAM_KEY=demo-local-key
```

## Register a user and vehicle

```bash
curl -X POST http://localhost:8080/api/users \
  -H "Authorization: Bearer $MAUSAM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"display_name":"Neha","full_name":"Neha Sharma","share_live_identity":false}'
```

Use the returned user ID:

```bash
curl -X POST http://localhost:8080/api/vehicles \
  -H "Authorization: Bearer $MAUSAM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "owner_user_id":"USER_ID",
    "display_name":"Blue Hatchback",
    "manufacturer":"Example",
    "model":"City EV",
    "registration_number":"PRIVATE",
    "share_live_identity":false
  }'
```

## Create a fog alert

```bash
curl -X POST http://localhost:8080/api/weather-alerts \
  -H "Authorization: Bearer $MAUSAM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "event_type":"fog",
    "severity":"warning",
    "title":"Dense fog",
    "description":"Visibility below 100 metres on the eastern corridor.",
    "latitude":28.6139,
    "longitude":77.2090,
    "radius_km":30,
    "starts_at":"2026-08-28T01:00:00Z",
    "ends_at":"2026-08-28T06:00:00Z",
    "source":"authorized operator",
    "instructions":"Use low-beam lamps, reduce speed, and increase spacing."
  }'
```

## Submit pothole evidence

```bash
curl -X POST http://localhost:8080/api/potholes \
  -H "Authorization: Bearer $MAUSAM_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "latitude":19.0762,
    "longitude":72.8779,
    "severity":"severe",
    "signal_confidence":0.82,
    "vehicle_id":"veh_asha",
    "user_id":"usr_asha",
    "camera_confirmed":true
  }'
```

## Authorized owner state

```bash
curl http://localhost:8080/api/state \
  -H "Authorization: Bearer $MAUSAM_KEY" \
  -H 'X-Viewer-User-Id: usr_asha'
```

The current demo uses the authenticated viewer header for clarity. Production must derive viewer identity from verified login claims, not a client-selected header.
