"""Dependency-free HTTP and Server-Sent Events API."""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import queue
import sqlite3
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .database import Database
from .models import ValidationError
from .service import RoadSafetyService
from .simulator import DemoSimulator


STATIC_DIR = Path(__file__).parent / "static"


API_SCHEMA = {
    "name": "MausamPulse Road Safety MVP",
    "version": "0.1.0",
    "warning": "Decision-support demonstration; not a certified ADAS or emergency service.",
    "authentication": "Mutating endpoints require Authorization: Bearer <MAUSAM_API_KEY>.",
    "endpoints": {
        "GET /api/health": "Service health and record counts",
        "GET /api/state": "Alerts, consent-filtered vehicles, potholes, and recent events",
        "GET /api/weather-alerts": "Active weather alerts; optional lat/lon filter",
        "GET /api/potholes": "Potholes; optional lat/lon/radius_km filter",
        "GET /api/events": "Server-Sent Events stream",
        "POST /api/users": "Create a user",
        "POST /api/vehicles": "Register a vehicle",
        "POST /api/telemetry": "Submit phone/vehicle telemetry and receive assessments",
        "POST /api/weather-alerts": "Create a geofenced weather alert",
        "POST /api/potholes": "Submit a manual or computer-vision pothole report",
        "POST /api/demo/seed": "Seed demonstration identities and weather alerts",
        "POST /api/demo/step": "Generate one synthetic telemetry update",
    },
}


def _as_float(values: dict[str, list[str]], name: str, default: float | None = None) -> float | None:
    if name not in values:
        return default
    return float(values[name][0])


class RoadSafetyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        service: RoadSafetyService,
        api_key: str,
        cors_origin: str,
    ):
        super().__init__(address, RoadSafetyHandler)
        self.service = service
        self.api_key = api_key
        self.cors_origin = cors_origin
        self.simulator: DemoSimulator | None = None


class RoadSafetyHandler(BaseHTTPRequestHandler):
    server: RoadSafetyHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        if os.getenv("MAUSAM_QUIET", "false").lower() not in {"1", "true", "yes"}:
            super().log_message(format, *args)

    def _cors_origin(self) -> str | None:
        request_origin = self.headers.get("Origin")
        allowed = self.server.cors_origin
        if allowed == "*":
            return "*"
        if request_origin and request_origin in {part.strip() for part in allowed.split(",")}:
            return request_origin
        return None

    def _base_headers(self) -> None:
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._base_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, details: Any = None) -> None:
        payload: dict[str, Any] = {"error": HTTPStatus(status).phrase, "message": message}
        if details is not None:
            payload["details"] = details
        self._json(status, payload)

    def _authenticated(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.api_key}"
        return hmac.compare_digest(supplied, expected)

    def _require_auth(self) -> bool:
        if self._authenticated():
            return True
        # Do not leave an unread request body on a persistent connection.
        self.close_connection = True
        self._error(HTTPStatus.UNAUTHORIZED, "A valid Bearer API key is required.")
        return False

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError(["Content-Length is invalid"]) from exc
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ValidationError(["request body exceeds 1 MB"])
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(["request body must be valid UTF-8 JSON"]) from exc
        if not isinstance(value, dict):
            raise ValidationError(["request body must be a JSON object"])
        return value

    def _serve_static(self, filename: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Resource not found")
            return
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._base_headers()
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") or "javascript" in mime else mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._base_headers()
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Viewer-User-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                return self._serve_static("index.html")
            if parsed.path == "/app.js":
                return self._serve_static("app.js")
            if parsed.path == "/styles.css":
                return self._serve_static("styles.css")
            if parsed.path == "/api/schema":
                return self._json(HTTPStatus.OK, API_SCHEMA)
            if parsed.path == "/api/health":
                return self._json(HTTPStatus.OK, {
                    "status": "ready",
                    "counts": self.server.service.db.counts(),
                    "demo_running": bool(self.server.simulator and self.server.simulator.running),
                })
            if parsed.path == "/api/state":
                viewer = self.headers.get("X-Viewer-User-Id") if self._authenticated() else None
                return self._json(HTTPStatus.OK, self.server.service.state(
                    latitude=_as_float(query, "lat"),
                    longitude=_as_float(query, "lon"),
                    radius_km=_as_float(query, "radius_km", 25.0) or 25.0,
                    viewer_user_id=viewer,
                ))
            if parsed.path == "/api/weather-alerts":
                alerts = self.server.service.db.active_weather_alerts(
                    _as_float(query, "lat"), _as_float(query, "lon")
                )
                return self._json(HTTPStatus.OK, {"alerts": alerts})
            if parsed.path == "/api/potholes":
                items = self.server.service.public_potholes(
                    _as_float(query, "lat"), _as_float(query, "lon"),
                    _as_float(query, "radius_km", 25.0) or 25.0,
                )
                return self._json(HTTPStatus.OK, {"potholes": items})
            if parsed.path == "/api/events":
                return self._serve_events()
            self._error(HTTPStatus.NOT_FOUND, "Resource not found")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "Invalid query parameter", str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected server error", str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._require_auth():
            return
        try:
            payload = self._read_json()
            routes = {
                "/api/users": self.server.service.create_user,
                "/api/vehicles": self.server.service.create_vehicle,
                "/api/telemetry": self.server.service.ingest_telemetry,
                "/api/weather-alerts": self.server.service.create_weather_alert,
                "/api/potholes": self.server.service.create_pothole_report,
            }
            if parsed.path in routes:
                result = routes[parsed.path](payload)
                return self._json(HTTPStatus.CREATED, result)
            if parsed.path == "/api/demo/seed":
                result = self.server.service.seed_demo(bool(payload.get("reset", False)))
                return self._json(HTTPStatus.OK, result)
            if parsed.path == "/api/demo/step":
                if self.server.simulator is None:
                    self.server.simulator = DemoSimulator(self.server.service)
                    self.server.service.seed_demo()
                result = self.server.simulator.step()
                return self._json(HTTPStatus.OK, {"updates": result})
            self._error(HTTPStatus.NOT_FOUND, "Resource not found")
        except ValidationError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "Input validation failed", exc.errors)
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except LookupError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except sqlite3.IntegrityError as exc:
            self._error(HTTPStatus.CONFLICT, "Record conflicts with existing data", str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected server error", str(exc))

    def _serve_events(self) -> None:
        target = self.server.service.events.subscribe()
        self.send_response(HTTPStatus.OK)
        self._base_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            hello = json.dumps({"type": "connected"}, separators=(",", ":"))
            self.wfile.write(f"event: connected\ndata: {hello}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    item = target.get(timeout=15)
                    event_name = str(item["type"]).replace("\n", "")
                    body = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    message = f"event: {event_name}\ndata: {body}\n\n"
                except queue.Empty:
                    message = ": heartbeat\n\n"
                self.wfile.write(message.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.service.events.unsubscribe(target)


class Application:
    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        database_path: str = "data/mausam-pulse.db",
        api_key: str = "demo-local-key",
        cors_origin: str = "http://localhost:8080",
        demo_mode: bool = True,
        demo_interval_s: float = 2.0,
    ):
        self.db = Database(database_path)
        self.service = RoadSafetyService(self.db)
        self.server = RoadSafetyHTTPServer((host, port), self.service, api_key, cors_origin)
        self.simulator = DemoSimulator(self.service, demo_interval_s)
        self.server.simulator = self.simulator
        self.demo_mode = demo_mode
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address

    def start(self, background: bool = False) -> None:
        if self.demo_mode:
            self.simulator.start()
        if background:
            self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self._thread.start()
        else:
            self.server.serve_forever()

    def stop(self) -> None:
        self.simulator.stop()
        self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=3)
