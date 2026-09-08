"""Synthetic telemetry generator for the credential-free demo."""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any

from .engine import destination_point
from .service import RoadSafetyService


class DemoSimulator:
    def __init__(self, service: RoadSafetyService, interval_s: float = 2.0):
        self.service = service
        self.interval_s = max(0.5, interval_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick = 0
        self._positions = {
            "veh_asha": (19.0718, 72.8700),
            "veh_ravi": (19.1110, 72.8940),
        }

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self.service.seed_demo()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mausam-demo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception as exc:  # Demo must not terminate the API.
                self.service.events.publish("demo.error", {"message": str(exc)})
            self._stop.wait(self.interval_s)

    def step(self) -> list[dict[str, Any]]:
        self._tick += 1
        at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        results = []

        # Vehicle 1 approaches a red light and exposes simulated OBD brake input.
        phase = self._tick % 24
        if phase < 10:
            asha_speed = 42.0
            distance_to_line = 95.0 - phase * 7.0
            brake = 0.0
            light = "red"
        elif phase < 16:
            asha_speed = max(0.0, 42.0 - (phase - 9) * 7.0)
            distance_to_line = max(5.0, 32.0 - (phase - 9) * 4.5)
            brake = min(78.0, 20.0 + (phase - 9) * 10.0)
            light = "red"
        elif phase < 19:
            asha_speed = 0.0
            distance_to_line = 5.0
            brake = 42.0
            light = "red"
        else:
            asha_speed = 30.0
            distance_to_line = None
            brake = 0.0
            light = "green"
        asha_lat, asha_lon = self._positions["veh_asha"]
        if asha_speed > 0:
            asha_lat, asha_lon = destination_point(
                asha_lat, asha_lon, asha_speed / 3.6 * self.interval_s, 65
            )
            self._positions["veh_asha"] = (asha_lat, asha_lon)
        asha_vertical = 2.3 if self._tick % 36 == 9 else 0.08
        results.append(self.service.ingest_telemetry({
            "vehicle_id": "veh_asha",
            "user_id": "usr_asha",
            "observed_at": at,
            "latitude": asha_lat,
            "longitude": asha_lon,
            "speed_kph": asha_speed,
            "heading_deg": 65,
            "weather_condition": "heavy_rain",
            "visibility_m": 115,
            "speed_limit_kph": 50,
            "brake_pressure_pct": brake,
            "brake_sensor_source": "simulated_obd_can",
            "traffic_light_state": light,
            "distance_to_stop_line_m": distance_to_line,
            "lead_vehicle_distance_m": 35,
            "lead_vehicle_speed_kph": max(0.0, asha_speed - 4),
            "vertical_acceleration_g": asha_vertical,
            "camera_pothole_confirmed": asha_vertical > 2,
        }))

        # Vehicle 2 demonstrates fog guidance and a periodically closing gap.
        wave = (math.sin(self._tick / 4) + 1) / 2
        ravi_speed = 34 + 22 * wave
        lead_speed = 26 + 6 * wave
        lead_distance = max(8.0, 42.0 - (self._tick % 18) * 1.9)
        ravi_lat, ravi_lon = self._positions["veh_ravi"]
        ravi_lat, ravi_lon = destination_point(
            ravi_lat, ravi_lon, ravi_speed / 3.6 * self.interval_s, 210
        )
        self._positions["veh_ravi"] = (ravi_lat, ravi_lon)
        ravi_vertical = 1.95 if self._tick % 36 == 11 else 0.06
        results.append(self.service.ingest_telemetry({
            "vehicle_id": "veh_ravi",
            "user_id": "usr_ravi",
            "observed_at": at,
            "latitude": ravi_lat,
            "longitude": ravi_lon,
            "speed_kph": round(ravi_speed, 1),
            "heading_deg": 210,
            "weather_condition": "fog",
            "visibility_m": 72,
            "speed_limit_kph": 60,
            "traffic_light_state": "unknown",
            "lead_vehicle_distance_m": lead_distance,
            "lead_vehicle_speed_kph": round(lead_speed, 1),
            "vertical_acceleration_g": ravi_vertical,
            "camera_pothole_confirmed": False,
        }))
        return results
