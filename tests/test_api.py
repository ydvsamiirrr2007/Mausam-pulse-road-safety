from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path

from app.api import Application


class APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(
            host="127.0.0.1",
            port=0,
            database_path=str(Path(self.temp.name) / "api.db"),
            api_key="test-key",
            demo_mode=False,
        )
        self.app.start(background=True)
        self.host, self.port = self.app.address

    def tearDown(self) -> None:
        self.app.stop()
        self.temp.cleanup()

    def request(self, method: str, path: str, body=None, authenticated=False):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        headers = {}
        encoded = None
        if body is not None:
            encoded = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers["Authorization"] = "Bearer test-key"
        conn.request(method, path, body=encoded, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        status = response.status
        conn.close()
        return status, payload

    def test_health_is_public(self) -> None:
        status, payload = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")

    def test_write_requires_bearer_key(self) -> None:
        status, _ = self.request("POST", "/api/demo/seed", {})
        self.assertEqual(status, 401)

    def test_demo_seed_and_step(self) -> None:
        status, seeded = self.request("POST", "/api/demo/seed", {}, True)
        self.assertEqual(status, 200)
        self.assertTrue(seeded["seeded"])
        status, update = self.request("POST", "/api/demo/step", {}, True)
        self.assertEqual(status, 200)
        self.assertEqual(len(update["updates"]), 2)
        status, dashboard = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(dashboard["vehicles"]), 2)

    def test_invalid_telemetry_is_rejected(self) -> None:
        status, _ = self.request("POST", "/api/demo/seed", {}, True)
        self.assertEqual(status, 200)
        status, payload = self.request(
            "POST", "/api/telemetry", {"vehicle_id": "veh_asha"}, True
        )
        self.assertEqual(status, 400)
        self.assertIn("details", payload)


if __name__ == "__main__":
    unittest.main()
