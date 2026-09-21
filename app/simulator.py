"""Demo simulator that emits synthetic telemetry into the service."""

from __future__ import annotations

import threading
from typing import Any

from .service import RoadSafetyService


class DemoSimulator:
    """Background generator of synthetic telemetry for the live demo.

    Thread-safety contract:
      * `start()` / `stop()` are safe to call from any thread.
      * `step()` is atomic — it takes the internal lock, so a manual
        step from the HTTP API cannot interleave with the background
        loop. The API additionally refuses manual steps while `running`
        is True, which is the primary defence; the lock is a second
        layer in case a caller bypasses that check.
    """

    def __init__(self, service: RoadSafetyService, interval_s: float = 2.0) -> None:
        self.service = service
        self.interval_s = float(interval_s)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick = 0
        self._positions: dict[str, dict[str, float]] = {}
        self.running = False

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Start the background generation loop. Idempotent."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="demo-simulator", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Signal the loop to stop and wait for it to exit. Idempotent."""
        with self._lock:
            if not self.running:
                return
            self.running = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.step()
            except Exception:
                # Never let a single bad tick kill the demo loop.
                # Replace with logging if you have a logger wired up.
                pass
            # Interruptible sleep so stop() returns promptly.
            self._stop_event.wait(self.interval_s)

    # ------------------------------------------------------------------ tick
    def step(self) -> list[dict[str, Any]]:
        """Advance the simulation by one tick.

        Returns the list of telemetry records that were ingested, so the
        HTTP endpoint can report how many vehicles were updated.
        """
        with self._lock:
            self._tick += 1
            updates: list[dict[str, Any]] = []
            for vehicle_id, position in list(self._positions.items()):
                # TODO: replace this block with your actual synthetic
                # telemetry generation. The shape below matches what
                # `RoadSafetyService.ingest_telemetry` expects.
                payload: dict[str, Any] = {
                    "vehicle_id": vehicle_id,
                    "user_id": position.get("user_id"),
                    "latitude": position["lat"],
                    "longitude": position["lon"],
                    "speed_kph": position.get("speed_kph", 40.0),
                    "heading_deg": position.get("heading_deg", 0.0),
                    "weather_condition": position.get("weather_condition", "clear"),
                    "visibility_m": position.get("visibility_m", 5000.0),
                    "speed_limit_kph": position.get("speed_limit_kph", 60.0),
                    "brake_pressure_pct": None,
                    "brake_sensor_source": "phone_estimate",
                    "traffic_light_state": "unknown",
                    "distance_to_stop_line_m": None,
                    "lead_vehicle_distance_m": None,
                    "lead_vehicle_speed_kph": None,
                    "vertical_acceleration_g": 0.0,
                    "camera_pothole_confirmed": False,
                    # Use "now" in whatever ISO format your validators expect.
                    # If you already have a helper, call it here instead.
                    "observed_at": position.get("observed_at"),
                }
                self.service.ingest_telemetry(payload)
                updates.append(payload)
            return updates
