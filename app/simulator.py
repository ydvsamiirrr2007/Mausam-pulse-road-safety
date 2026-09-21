import threading
import time
from app.models import ValidationError  # if needed

class DemoSimulator:
    def __init__(self, service, interval=2.0):
        self.service = service
        self.interval = interval
        self._tick = 0
        self._positions = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self.running = False

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self.running = False
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            self.step()
            self._stop_event.wait(self.interval)

    def step(self):
        """Advance the simulation by one tick. Thread‑safe."""
        with self._lock:
            self._tick += 1
            # --- your original simulation logic here ---
            # Example: update positions, send telemetry via self.service
            # for vehicle_id in self._positions:
            #     ...
            # self.service.ingest_telemetry(...)
            pass
