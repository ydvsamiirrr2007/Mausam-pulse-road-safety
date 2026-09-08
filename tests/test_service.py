from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.database import Database
from app.service import RoadSafetyService


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = RoadSafetyService(Database(str(Path(self.temp.name) / "test.db")))
        self.service.seed_demo()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def telemetry(self, **overrides):
        payload = {
            "vehicle_id": "veh_asha",
            "user_id": "usr_asha",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "latitude": 19.076,
            "longitude": 72.878,
            "speed_kph": 54,
            "visibility_m": 80,
            "weather_condition": "heavy_rain",
            "lead_vehicle_distance_m": 12,
            "lead_vehicle_speed_kph": 18,
            "traffic_light_state": "red",
            "distance_to_stop_line_m": 20,
        }
        payload.update(overrides)
        return self.service.ingest_telemetry(payload)

    def test_telemetry_returns_assessments_and_weather(self) -> None:
        result = self.telemetry()
        self.assertIn("collision", result["assessments"])
        self.assertIn("visibility", result["assessments"])
        self.assertGreaterEqual(len(result["assessments"]["weather_alerts"]), 1)

    def test_vehicle_ownership_is_enforced(self) -> None:
        with self.assertRaises(PermissionError):
            self.telemetry(user_id="usr_ravi")

    def test_public_identity_is_consent_filtered(self) -> None:
        self.telemetry()
        self.service.ingest_telemetry({
            "vehicle_id": "veh_ravi", "user_id": "usr_ravi",
            "latitude": 19.1, "longitude": 72.9, "speed_kph": 20,
            "visibility_m": 90, "weather_condition": "fog",
        })
        public = self.service.state()
        by_name = {item["user_name"]: item for item in public["vehicles"]}
        self.assertEqual(by_name["Asha"]["vehicle_name"], "Monsoon Rider")
        self.assertEqual(by_name["Private driver"]["vehicle_name"], "Private vehicle")
        self.assertIsNone(by_name["Private driver"]["registration_number"])
        self.assertEqual(by_name["Private driver"]["latitude"], round(19.1, 3))
        self.assertTrue(by_name["Private driver"]["id"].startswith("public_"))

    def test_owner_gets_precise_private_details(self) -> None:
        self.service.ingest_telemetry({
            "vehicle_id": "veh_ravi", "user_id": "usr_ravi",
            "latitude": 19.100123, "longitude": 72.900456, "speed_kph": 20,
            "visibility_m": 90, "weather_condition": "fog",
        })
        owner = self.service.state(viewer_user_id="usr_ravi")
        ravi = next(item for item in owner["vehicles"] if item["id"] == "veh_ravi")
        self.assertEqual(ravi["latitude"], 19.100123)
        self.assertEqual(ravi["registration_number"], "DEMO-RAVI")
        self.assertIn("emergency_contact", ravi)

    def test_live_vehicle_exposes_safety_inputs_for_dashboard(self) -> None:
        self.telemetry(
            speed_limit_kph=50,
            traffic_light_state="red",
            distance_to_stop_line_m=20,
            lead_vehicle_distance_m=12,
            lead_vehicle_speed_kph=18,
        )
        owner = self.service.state(viewer_user_id="usr_asha")
        vehicle = next(item for item in owner["vehicles"] if item["id"] == "veh_asha")
        self.assertEqual(vehicle["traffic_light_state"], "red")
        self.assertEqual(vehicle["distance_to_stop_line_m"], 20)
        self.assertEqual(vehicle["lead_vehicle_distance_m"], 12)

    def test_pothole_clusters_across_vehicles(self) -> None:
        first = self.service.create_pothole_report({
            "latitude": 19.076, "longitude": 72.878,
            "vehicle_id": "veh_asha", "user_id": "usr_asha",
            "signal_confidence": .7, "severity": "moderate",
        })
        second = self.service.create_pothole_report({
            "latitude": 19.07605, "longitude": 72.87804,
            "vehicle_id": "veh_ravi", "user_id": "usr_ravi",
            "signal_confidence": .7, "severity": "moderate",
        })
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "likely")

    def test_public_events_and_potholes_hide_internal_vehicle_ids(self) -> None:
        self.telemetry()
        self.service.create_pothole_report({
            "latitude": 19.076, "longitude": 72.878,
            "vehicle_id": "veh_asha", "user_id": "usr_asha",
            "signal_confidence": .7,
        })
        public = self.service.state()
        self.assertNotIn("vehicle_ids", public["potholes"][0])
        self.assertEqual(public["potholes"][0]["reporting_vehicle_count"], 1)
        self.assertIsNone(public["recent_events"][0]["vehicle_id"])
        self.assertNotIn("user_id", public["recent_events"][0])


if __name__ == "__main__":
    unittest.main()
