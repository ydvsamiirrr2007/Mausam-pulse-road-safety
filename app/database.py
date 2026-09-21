"""SQLite persistence for the standalone MVP."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .engine import aggregate_pothole_confidence, haversine_m


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, path: str):
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            full_name TEXT NOT NULL,
            emergency_contact TEXT,
            share_live_identity INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vehicles (
            id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL REFERENCES users(id),
            display_name TEXT NOT NULL,
            manufacturer TEXT,
            model TEXT,
            registration_number TEXT,
            color TEXT,
            share_live_identity INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry (
            id TEXT PRIMARY KEY,
            vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            observed_at TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            speed_kph REAL NOT NULL,
            heading_deg REAL,
            weather_condition TEXT NOT NULL,
            visibility_m REAL NOT NULL,
            raw_json TEXT NOT NULL,
            assessments_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS telemetry_vehicle_time
            ON telemetry(vehicle_id, observed_at DESC);
        CREATE TABLE IF NOT EXISTS weather_alerts (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_km REAL NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            source TEXT NOT NULL,
            instructions TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS weather_alert_time
            ON weather_alerts(starts_at, ends_at);
        CREATE TABLE IF NOT EXISTS potholes (
            id TEXT PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            severity TEXT NOT NULL,
            report_count INTEGER NOT NULL,
            vehicle_ids_json TEXT NOT NULL,
            strongest_signal REAL NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            first_reported_at TEXT NOT NULL,
            last_reported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pothole_reports (
            id TEXT PRIMARY KEY,
            pothole_id TEXT NOT NULL REFERENCES potholes(id),
            vehicle_id TEXT,
            user_id TEXT,
            signal_confidence REAL NOT NULL,
            camera_confirmed INTEGER NOT NULL,
            reported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS safety_events (
            id TEXT PRIMARY KEY,
            vehicle_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            level TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            details_json TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS safety_event_time
            ON safety_events(observed_at DESC);
        """
        with self._write_lock, self.connection() as conn:
            conn.executescript(schema)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": payload.get("id") or self._id("usr"),
            "display_name": payload["display_name"],
            "full_name": payload.get("full_name") or payload["display_name"],
            "emergency_contact": payload.get("emergency_contact"),
            "share_live_identity": bool(payload.get("share_live_identity", False)),
            "created_at": utc_now(),
        }
        with self._write_lock, self.connection() as conn:
            conn.execute(
                """INSERT INTO users
                   (id, display_name, full_name, emergency_contact,
                    share_live_identity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["display_name"], record["full_name"],
                    record["emergency_contact"], int(record["share_live_identity"]),
                    record["created_at"],
                ),
            )
        return record

    def create_vehicle(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": payload.get("id") or self._id("veh"),
            "owner_user_id": payload["owner_user_id"],
            "display_name": payload["display_name"],
            "manufacturer": payload.get("manufacturer"),
            "model": payload.get("model"),
            "registration_number": payload.get("registration_number"),
            "color": payload.get("color"),
            "share_live_identity": bool(payload.get("share_live_identity", False)),
            "created_at": utc_now(),
        }
        with self._write_lock, self.connection() as conn:
            conn.execute(
                """INSERT INTO vehicles
                   (id, owner_user_id, display_name, manufacturer, model,
                    registration_number, color, share_live_identity, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["owner_user_id"], record["display_name"],
                    record["manufacturer"], record["model"],
                    record["registration_number"], record["color"],
                    int(record["share_live_identity"]), record["created_at"],
                ),
            )
        return record

    def user_exists(self, user_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is not None

    def vehicle_for_user(self, vehicle_id: str, user_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute(
                "SELECT 1 FROM vehicles WHERE id = ? AND owner_user_id = ?",
                (vehicle_id, user_id),
            ).fetchone() is not None

    def latest_telemetry(self, vehicle_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM telemetry WHERE vehicle_id = ? ORDER BY observed_at DESC LIMIT 1",
                (vehicle_id,),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["raw"] = json.loads(value.pop("raw_json"))
        value["assessments"] = json.loads(value.pop("assessments_json"))
        return value

    def insert_telemetry(
        self, payload: dict[str, Any], assessments: dict[str, Any]
    ) -> dict[str, Any]:
        record_id = self._id("tel")
        created_at = utc_now()
        with self._write_lock, self.connection() as conn:
            conn.execute(
                """INSERT INTO telemetry
                   (id, vehicle_id, user_id, observed_at, latitude, longitude,
                    speed_kph, heading_deg, weather_condition, visibility_m,
                    raw_json, assessments_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id, payload["vehicle_id"], payload["user_id"],
                    payload["observed_at"], payload["latitude"], payload["longitude"],
                    payload["speed_kph"], payload.get("heading_deg"),
                    payload.get("weather_condition", "clear"), payload["visibility_m"],
                    json.dumps(payload, separators=(",", ":")),
                    json.dumps(assessments, separators=(",", ":")), created_at,
                ),
            )
        return {
            "id": record_id,
            "created_at": created_at,
            "telemetry": payload,
            "assessments": assessments,
        }

    def insert_safety_event(
        self,
        payload: dict[str, Any],
        event_type: str,
        level: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "id": self._id("evt"),
            "vehicle_id": payload["vehicle_id"],
            "user_id": payload["user_id"],
            "event_type": event_type,
            "level": level,
            "latitude": payload["latitude"],
            "longitude": payload["longitude"],
            "details": details,
            "observed_at": payload["observed_at"],
        }
        with self._write_lock, self.connection() as conn:
            conn.execute(
                """INSERT INTO safety_events
                   (id, vehicle_id, user_id, event_type, level, latitude,
                    longitude, details_json, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["vehicle_id"], record["user_id"],
                    record["event_type"], record["level"], record["latitude"],
                    record["longitude"], json.dumps(details), record["observed_at"],
                ),
            )
        return record

    def create_weather_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": payload.get("id") or self._id("wx"),
            "event_type": payload["event_type"],
            "severity": payload["severity"],
            "title": payload["title"],
            "description": payload["description"],
            "latitude": payload["latitude"],
            "longitude": payload["longitude"],
            "radius_km": payload.get("radius_km", 25.0),
            "starts_at": payload["starts_at"],
            "ends_at": payload["ends_at"],
            "source": payload.get("source", "manual"),
            "instructions": payload.get("instructions", "Monitor local official guidance."),
            "created_at": utc_now(),
        }
        with self._write_lock, self.connection() as conn:
            conn.execute(
                """INSERT INTO weather_alerts
                   (id, event_type, severity, title, description, latitude,
                    longitude, radius_km, starts_at, ends_at, source,
                    instructions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(record.values()),
            )
        return record

    def active_weather_alerts(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        now = now or utc_now()
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM weather_alerts
                   WHERE starts_at <= ? AND ends_at >= ?
                   ORDER BY severity DESC, starts_at DESC""",
                (now, now),
            ).fetchall()
        result = [dict(row) for row in rows]
        if latitude is None or longitude is None:
            return result
        nearby = []
        for alert in result:
            distance_km = haversine_m(
                latitude, longitude, alert["latitude"], alert["longitude"]
            ) / 1000
            if distance_km <= alert["radius_km"]:
                alert["distance_km"] = round(distance_km, 2)
                nearby.append(alert)
        return nearby

    def report_pothole(
        self,
        *,
        latitude: float,
        longitude: float,
        severity: str,
        signal_confidence: float,
        vehicle_id: str | None,
        user_id: str | None,
        camera_confirmed: bool,
        reported_at: str,
        cluster_radius_m: float = 25.0,
    ) -> dict[str, Any]:
        with self._write_lock, self.connection() as conn:
            candidates = conn.execute(
                "SELECT * FROM potholes ORDER BY last_reported_at DESC LIMIT 500"
            ).fetchall()
            selected = None
            for row in candidates:
                if haversine_m(latitude, longitude, row["latitude"], row["longitude"]) <= cluster_radius_m:
                    selected = dict(row)
                    break

            if selected:
                vehicles = set(json.loads(selected["vehicle_ids_json"]))
                if vehicle_id:
                    vehicles.add(vehicle_id)
                count = selected["report_count"] + 1
                strongest = max(float(selected["strongest_signal"]), signal_confidence)
                confidence, status = aggregate_pothole_confidence(count, len(vehicles), strongest)
                # Gradually average location to reduce single-device GPS noise.
                weight = min(selected["report_count"], 5)
                new_lat = (selected["latitude"] * weight + latitude) / (weight + 1)
                new_lon = (selected["longitude"] * weight + longitude) / (weight + 1)
                conn.execute(
                    """UPDATE potholes SET latitude=?, longitude=?, severity=?,
                       report_count=?, vehicle_ids_json=?, strongest_signal=?,
                       confidence=?, status=?, last_reported_at=? WHERE id=?""",
                    (
                        new_lat, new_lon, severity, count, json.dumps(sorted(vehicles)),
                        strongest, confidence, status, reported_at, selected["id"],
                    ),
                )
                pothole_id = selected["id"]
            else:
                pothole_id = self._id("pot")
                vehicles = {vehicle_id} if vehicle_id else set()
                confidence, status = aggregate_pothole_confidence(
                    1, len(vehicles), signal_confidence
                )
                conn.execute(
                    """INSERT INTO potholes
                       (id, latitude, longitude, severity, report_count,
                        vehicle_ids_json, strongest_signal, confidence, status,
                        first_reported_at, last_reported_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pothole_id, latitude, longitude, severity, 1,
                        json.dumps(sorted(vehicles)), signal_confidence, confidence,
                        status, reported_at, reported_at,
                    ),
                )
            conn.execute(
                """INSERT INTO pothole_reports
                   (id, pothole_id, vehicle_id, user_id, signal_confidence,
                    camera_confirmed, reported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._id("ptr"), pothole_id, vehicle_id, user_id,
                    signal_confidence, int(camera_confirmed), reported_at,
                ),
            )
            row = conn.execute("SELECT * FROM potholes WHERE id = ?", (pothole_id,)).fetchone()
        result = dict(row)
        result["vehicle_ids"] = json.loads(result.pop("vehicle_ids_json"))
        return result

    def nearby_potholes(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 25.0,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM potholes ORDER BY confidence DESC, last_reported_at DESC LIMIT 500"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["vehicle_ids"] = json.loads(item.pop("vehicle_ids_json"))
            if latitude is not None and longitude is not None:
                distance_km = haversine_m(
                    latitude, longitude, item["latitude"], item["longitude"]
                ) / 1000
                if distance_km > radius_km:
                    continue
                item["distance_km"] = round(distance_km, 2)
            result.append(item)
        return result

    def live_vehicles(self) -> list[dict[str, Any]]:
        query = """
        SELECT v.*, u.display_name AS user_display_name, u.full_name,
               u.emergency_contact, u.share_live_identity AS user_sharing,
               t.observed_at, t.latitude, t.longitude, t.speed_kph,
               t.heading_deg, t.weather_condition, t.visibility_m,
               t.assessments_json, t.raw_json AS telemetry_raw_json
        FROM vehicles v
        JOIN users u ON u.id = v.owner_user_id
        LEFT JOIN telemetry t ON t.id = (
            SELECT t2.id FROM telemetry t2
            WHERE t2.vehicle_id = v.id
            ORDER BY t2.observed_at DESC LIMIT 1
        )
        ORDER BY t.observed_at DESC
        """
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["assessments"] = json.loads(item.pop("assessments_json")) if item["assessments_json"] else None
            raw_json = item.pop("telemetry_raw_json")
            item["telemetry_raw"] = json.loads(raw_json) if raw_json else {}
            result.append(item)
        return result

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM safety_events ORDER BY observed_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        return result

def counts(self) -> dict[str, int]:
    """Return record counts for each table."""
    # Whitelist of allowed tables - prevents any injection
    allowed_tables = ("users", "vehicles", "telemetry", "weather_alerts", "potholes", "safety_events")
    
    with self.connection() as conn:
        result = {}
        for table in allowed_tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            result[table] = count
        return result

def clear_demo_data(self) -> None:
    """Clear all demonstration data from the database."""
    # Whitelist of allowed tables
    tables_to_clear = (
        "pothole_reports", "safety_events", "telemetry", "potholes",
        "weather_alerts", "vehicles", "users",
    )
    
    with self._write_lock, self.connection() as conn:
        for table in tables_to_clear:
            conn.execute(f"DELETE FROM {table}")
