"""Command-line entry point: ``python -m app``."""

from __future__ import annotations

import argparse
import os

from .api import Application


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    parser = argparse.ArgumentParser(description="MausamPulse Road Safety MVP")
    parser.add_argument("--host", default=os.getenv("MAUSAM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MAUSAM_PORT", "8080")))
    args = parser.parse_args()
    app = Application(
        host=args.host,
        port=args.port,
        database_path=os.getenv("MAUSAM_DATABASE", "data/mausam-pulse.db"),
        api_key=os.getenv("MAUSAM_API_KEY", "demo-local-key"),
        cors_origin=os.getenv("MAUSAM_CORS_ORIGIN", "http://localhost:8080"),
        demo_mode=env_bool("MAUSAM_DEMO_MODE", True),
        demo_interval_s=float(os.getenv("MAUSAM_DEMO_INTERVAL", "2")),
    )
    host, port = app.address
    print(f"MausamPulse running at http://{host}:{port}")
    print("Safety note: decision-support demo; not a certified ADAS or emergency service.")
    try:
        app.start()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
