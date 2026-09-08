from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.engine import (
    aggregate_pothole_confidence,
    assess_braking,
    assess_collision,
    assess_visibility,
    braking_distance_m,
    haversine_m,
    pothole_signal_confidence,
)


class EngineTests(unittest.TestCase):
    def test_haversine_returns_reasonable_city_distance(self) -> None:
        # Gateway of India to Mumbai Central is roughly 5–7 km by straight line.
        distance = haversine_m(18.9219, 72.8347, 18.9696, 72.8194)
        self.assertGreater(distance, 5_000)
        self.assertLess(distance, 7_000)

    def test_collision_requires_relative_measurements(self) -> None:
        result = assess_collision(80, None, None)
        self.assertEqual(result.level, "unknown")
        self.assertIsNone(result.time_to_collision_s)

    def test_collision_ttc_marks_critical_gap(self) -> None:
        result = assess_collision(72, 10, 36)
        self.assertEqual(result.level, "critical")
        self.assertAlmostEqual(result.time_to_collision_s, 1.0)

    def test_non_closing_gap_is_low_risk(self) -> None:
        result = assess_collision(40, 20, 50)
        self.assertEqual(result.level, "low")
        self.assertIsNone(result.time_to_collision_s)

    def test_rain_increases_stopping_distance(self) -> None:
        clear = braking_distance_m(60, "clear")
        wet = braking_distance_m(60, "heavy_rain")
        self.assertGreater(wet, clear)

    def test_visibility_guidance_flags_excess_speed(self) -> None:
        result = assess_visibility(55, 80, "fog", 80)
        self.assertIn(result.level, {"high", "critical"})
        self.assertTrue(result.is_speed_above_guidance)
        self.assertLess(result.safe_speed_kph, 80)

    def test_obd_brake_pressure_remains_measurement(self) -> None:
        now = datetime.now(timezone.utc)
        result = assess_braking(
            speed_kph=30,
            previous_speed_kph=40,
            previous_time=now - timedelta(seconds=2),
            current_time=now,
            brake_pressure_pct=55,
            brake_sensor_source="obd_can",
            traffic_light_state="red",
            distance_to_stop_line_m=15,
        )
        self.assertEqual(result.source, "obd_can_exact_input")
        self.assertEqual(result.brake_pressure_pct, 55)
        self.assertGreater(result.stopping_distance_m, 0)
        self.assertIsNotNone(result.stop_margin_m)

    def test_phone_braking_is_labeled_estimate(self) -> None:
        now = datetime.now(timezone.utc)
        result = assess_braking(
            speed_kph=20,
            previous_speed_kph=40,
            previous_time=now - timedelta(seconds=2),
            current_time=now,
            brake_pressure_pct=None,
            brake_sensor_source=None,
            traffic_light_state="red",
            distance_to_stop_line_m=12,
        )
        self.assertEqual(result.source, "phone_estimate")
        self.assertIsNone(result.brake_pressure_pct)
        self.assertGreater(result.estimated_deceleration_mps2, 2)

    def test_wet_stop_margin_flags_insufficient_distance(self) -> None:
        now = datetime.now(timezone.utc)
        result = assess_braking(
            speed_kph=50,
            previous_speed_kph=50,
            previous_time=now - timedelta(seconds=2),
            current_time=now,
            brake_pressure_pct=45,
            brake_sensor_source="obd_can",
            traffic_light_state="red",
            distance_to_stop_line_m=20,
            weather_condition="heavy_rain",
        )
        self.assertLess(result.stop_margin_m, 0)
        self.assertEqual(result.stop_line_status, "hard_braking_required")

    def test_pothole_needs_corroboration_for_verified_status(self) -> None:
        signal = pothole_signal_confidence(2.4, 35, True)
        confidence, status = aggregate_pothole_confidence(3, 3, signal)
        self.assertGreaterEqual(confidence, 0.75)
        self.assertEqual(status, "verified")


if __name__ == "__main__":
    unittest.main()
