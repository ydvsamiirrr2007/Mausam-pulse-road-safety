"""Application services that connect validation, calculations, and storage."""

from __future__ import annotations

import queue
import threading
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database, utc_now
from .engine import (
    assess_braking,
    assess_collision,
    assess_visibility,
    assessment_to_dict,
    pothole_signal_confidence,
)
from .models import (
    validate_pothole_report,
    validate_telemetry,
    validate_user,
    validate_vehicle,
    validate_weather_alert,
)


class EventBus:
    """In-process fan-out used by the Server-Sent Events endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        target: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(target)
        return target

    def unsubscribe(self, target: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(target)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "at": utc_now(), "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for target in subscribers:
            try:
                target.put_nowait(event)
            except queue.Full:
                try:
                    target.get_nowait()
                    target.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass


class RoadSafetyService:
    def __init__(self, database: Database, event_bus: EventBus | None = None):
        self.db = database
        self.events = event_bus or EventBus()

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.db.create_user(validate_user(payload))
        self.events.publish("user.created", {"refresh": True})
        return record

    def create_vehicle(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = validate_vehicle(payload)
        if not self.db.user_exists(data["owner_user_id"]):
            raise LookupError("owner_user_id does not exist")
        record = self.db.create_vehicle(data)
        self.events.publish("vehicle.created", {"refresh": True})
        return record

    def create_weather_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.db.create_weather_alert(validate_weather_alert(payload))
        self.events.publish("weather.alert", record)
        return record

    def create_pothole_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = validate_pothole_report(payload)
        record = self.db.report_pothole(**data)
        self.events.publish("pothole.updated", self._pothole_view(record))
        return record

    def ingest_telemetry(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = validate_telemetry(payload)
        if not self.db.vehicle_for_user(data["vehicle_id"], data["user_id"]):
            raise PermissionError("vehicle_id does not belong to user_id")
        previous = self.db.latest_telemetry(data["vehicle_id"])
        previous_speed = previous["speed_kph"] if previous else None
        previous_time = previous["observed_at"] if previous else None

        collision = assess_collision(
            data["speed_kph"],
            data["lead_vehicle_distance_m"],
            data["lead_vehicle_speed_kph"],
        )
        braking = assess_braking(
            speed_kph=data["speed_kph"],
            previous_speed_kph=previous_speed,
            previous_time=previous_time,
            current_time=data["observed_at"],
            brake_pressure_pct=data["brake_pressure_pct"],
            brake_sensor_source=data["brake_sensor_source"],
            traffic_light_state=data["traffic_light_state"],
            distance_to_stop_line_m=data["distance_to_stop_line_m"],
            weather_condition=data["weather_condition"],
        )
        visibility = assess_visibility(
            data["visibility_m"],
            data["speed_kph"],
            data["weather_condition"],
            data["speed_limit_kph"],
        )
        nearby_alerts = self.db.active_weather_alerts(
            data["latitude"], data["longitude"], data["observed_at"]
        )
        assessments = {
            "collision": assessment_to_dict(collision),
            "braking": assessment_to_dict(braking),
            "visibility": assessment_to_dict(visibility),
            "weather_alerts": nearby_alerts,
            "measurement_notes": {
                "position": "GNSS position; accuracy depends on the reporting device.",
                "braking": (
                    "Vehicle-provided brake input."
                    if data["brake_pressure_pct"] is not None
                    else "Estimated from consecutive speed samples; pedal pressure unavailable."
                ),
                "collision": "TTC requires a measured lead-vehicle distance and speed.",
            },
        }
        record = self.db.insert_telemetry(data, assessments)

        if collision.level in {"critical", "high", "moderate"}:
            event = self.db.insert_safety_event(
                data, "collision_risk", collision.level, assessments["collision"]
            )
            self.events.publish("safety.collision", self._event_view(event, None))
        if visibility.level in {"critical", "high"} or visibility.is_speed_above_guidance:
            event = self.db.insert_safety_event(
                data, "visibility_risk", visibility.level, assessments["visibility"]
            )
            self.events.publish("safety.visibility", self._event_view(event, None))
        if braking.stop_line_status in {"hard_braking_required", "stop_line_crossed"}:
            level = "critical" if braking.stop_line_status == "stop_line_crossed" else "high"
            event = self.db.insert_safety_event(
                data, "traffic_signal_risk", level, assessments["braking"]
            )
            self.events.publish("safety.traffic_signal", self._event_view(event, None))

        pothole_score = pothole_signal_confidence(
            data["vertical_acceleration_g"],
            data["speed_kph"],
            data["camera_pothole_confirmed"],
        )
        pothole = None
        if pothole_score >= 0.30:
            severity = "severe" if pothole_score >= 0.75 else "moderate"
            pothole = self.db.report_pothole(
                latitude=data["latitude"],
                longitude=data["longitude"],
                severity=severity,
                signal_confidence=pothole_score,
                vehicle_id=data["vehicle_id"],
                user_id=data["user_id"],
                camera_confirmed=data["camera_pothole_confirmed"],
                reported_at=data["observed_at"],
            )
            self.events.publish("pothole.detected", self._pothole_view(pothole))

        self.events.publish(
            "telemetry.updated",
            {
                "vehicle_id": data["vehicle_id"],
                "observed_at": data["observed_at"],
                "collision_level": collision.level,
                "visibility_level": visibility.level,
            },
        )
        record["pothole_detection"] = pothole
        return record

    @staticmethod
    def _public_reference(value: str) -> str:
        return "public_" + hashlib.sha256(("mausam-public:" + value).encode()).hexdigest()[:10]

    @staticmethod
    def _vehicle_view(item: dict[str, Any], viewer_user_id: str | None) -> dict[str, Any]:
        owner = viewer_user_id and viewer_user_id == item["owner_user_id"]
        shared = bool(item["share_live_identity"] and item["user_sharing"])
        precise = bool(owner)
        raw = item.get("telemetry_raw") or {}
        result = {
            "id": item["id"] if owner else RoadSafetyService._public_reference(item["id"]),
            "vehicle_name": item["display_name"] if owner or shared else "Private vehicle",
            "user_name": item["full_name"] if owner else (
                item["user_display_name"] if shared else "Private driver"
            ),
            "manufacturer": item["manufacturer"] if owner or shared else None,
            "model": item["model"] if owner or shared else None,
            "color": item["color"] if owner or shared else None,
            "registration_number": item["registration_number"] if owner else None,
            "observed_at": item["observed_at"],
            "latitude": item["latitude"] if precise or item["latitude"] is None else round(item["latitude"], 3),
            "longitude": item["longitude"] if precise or item["longitude"] is None else round(item["longitude"], 3),
            "location_precision": "precise_owner_view" if precise else "approximately_100m_public_view",
            "speed_kph": item["speed_kph"],
            "heading_deg": item["heading_deg"],
            "weather_condition": item["weather_condition"],
            "visibility_m": item["visibility_m"],
            "speed_limit_kph": raw.get("speed_limit_kph"),
            "traffic_light_state": raw.get("traffic_light_state", "unknown"),
            "distance_to_stop_line_m": raw.get("distance_to_stop_line_m"),
            "lead_vehicle_distance_m": raw.get("lead_vehicle_distance_m"),
            "lead_vehicle_speed_kph": raw.get("lead_vehicle_speed_kph"),
            "assessments": item["assessments"],
            "identity_shared_by_consent": shared,
        }
        if owner:
            result["emergency_contact"] = item["emergency_contact"]
        return result

    @staticmethod
    def _pothole_view(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        vehicle_ids = result.pop("vehicle_ids", [])
        result["reporting_vehicle_count"] = len(vehicle_ids)
        return result

    @staticmethod
    def _event_view(item: dict[str, Any], viewer_user_id: str | None) -> dict[str, Any]:
        owner = bool(viewer_user_id and viewer_user_id == item["user_id"])
        result = {
            "id": item["id"] if owner else RoadSafetyService._public_reference(item["id"]),
            "vehicle_id": item["vehicle_id"] if owner else None,
            "event_type": item["event_type"],
            "level": item["level"],
            "latitude": item["latitude"] if owner else round(item["latitude"], 3),
            "longitude": item["longitude"] if owner else round(item["longitude"], 3),
            "location_precision": "precise_owner_view" if owner else "approximately_100m_public_view",
            "details": item["details"],
            "observed_at": item["observed_at"],
        }
        if owner:
            result["user_id"] = item["user_id"]
        return result

    def state(
        self,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 25.0,
        viewer_user_id: str | None = None,
    ) -> dict[str, Any]:
        vehicles = [self._vehicle_view(item, viewer_user_id) for item in self.db.live_vehicles()]
        potholes = [
            self._pothole_view(item)
            for item in self.db.nearby_potholes(latitude, longitude, radius_km)
        ]
        events = [
            self._event_view(item, viewer_user_id)
            for item in self.db.recent_events(40)
        ]
        return {
            "generated_at": utc_now(),
            "system_mode": "decision-support MVP; not certified ADAS",
            "weather_alerts": self.db.active_weather_alerts(latitude, longitude),
            "vehicles": vehicles,
            "potholes": potholes,
            "recent_events": events,
            "counts": self.db.counts(),
        }

    def public_potholes(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 25.0,
    ) -> list[dict[str, Any]]:
        return [
            self._pothole_view(item)
            for item in self.db.nearby_potholes(latitude, longitude, radius_km)
        ]

    def seed_demo(self, reset: bool = False) -> dict[str, Any]:
        if reset:
            self.db.clear_demo_data()
        counts = self.db.counts()
        if counts["users"]:
            return {"seeded": False, "reason": "database already contains users", "counts": counts}
        self.create_user({
            "id": "usr_asha", "display_name": "Asha", "full_name": "Asha Mehta",
            "emergency_contact": "+91-DEMO-100", "share_live_identity": True,
        })
        self.create_user({
            "id": "usr_ravi", "display_name": "Ravi", "full_name": "Ravi Kumar",
            "emergency_contact": "+91-DEMO-200", "share_live_identity": False,
        })
        self.create_vehicle({
            "id": "veh_asha", "owner_user_id": "usr_asha", "display_name": "Monsoon Rider",
            "manufacturer": "Demo Motors", "model": "Nimbus EV", "color": "Blue",
            "registration_number": "DEMO-ASHA", "share_live_identity": True,
        })
        self.create_vehicle({
            "id": "veh_ravi", "owner_user_id": "usr_ravi", "display_name": "Fog Runner",
            "manufacturer": "Demo Motors", "model": "Drizzle", "color": "Silver",
            "registration_number": "DEMO-RAVI", "share_live_identity": False,
        })
        now = datetime.now(timezone.utc)
        self.create_weather_alert({
            "id": "wx_demo_rain",
            "event_type": "heavy_rain",
            "severity": "warning",
            "title": "Heavy rain and waterlogging risk",
            "description": "Demo alert for intense rainfall near central Mumbai.",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "radius_km": 35,
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(hours=4)).isoformat(),
            "source": "MausamPulse demo",
            "instructions": "Reduce speed, increase following distance, and avoid flooded underpasses.",
        })
        self.create_weather_alert({
            "id": "wx_demo_fog",
            "event_type": "fog",
            "severity": "advisory",
            "title": "Patches of dense fog",
            "description": "Demo low-visibility advisory on the northern route.",
            "latitude": 19.125,
            "longitude": 72.900,
            "radius_km": 18,
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
            "source": "MausamPulse demo",
            "instructions": "Use low-beam lamps and avoid abrupt lane changes.",
        })
        return {"seeded": True, "counts": self.db.counts()}
