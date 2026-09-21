import os

class Application:
    def __init__(self, db, service, simulator=None, api_key=None, cors_origin=None):
        self.db = db
        self.service = service
        self.simulator = simulator
        self.api_key = api_key or os.environ.get("MAUSAM_API_KEY")
        if not self.api_key:
            raise ValueError("MAUSAM_API_KEY environment variable must be set")
        self.cors_origin = cors_origin or "http://localhost:8080"
        # ... rest of init
