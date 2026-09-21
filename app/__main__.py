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


def parse_port(value: str) -> int:"""Command-line entry point: ``python -m app``."""

from __future__ import annotations

import argparse
import os

from .api import Application


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_port(value: str) -> int:
    """Parse and validate port number from string."""
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Port must be an integer, got {value!r}"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"Port must be 1-65535, got {port}")
    return port


def parse_demo_interval(raw: str | None) -> float:
    """Return a positive float from the env var, falling back to 2.0.

    Bad or missing values must not crash startup, so this never raises.
    """
    if raw is None:
        return 2.0
    try:
        interval = float(raw)
    except ValueError:
        return 2.0
    if interval <= 0:
        return 2.0
    return interval


def main() -> None:
    parser = argparse.ArgumentParser(description="MausamPulse Road Safety MVP")
    parser.add_argument("--host", default=os.getenv("MAUSAM_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=parse_port,
        default=8080,
    )
    args = parser.parse_args()

    # Do NOT pass a hard-coded fallback for the API key here. Application
    # already prefers its explicit argument, then MAUSAM_API_KEY, and only
    # falls back to a clearly-labelled demo key when demo_mode is True.
    # Passing "demo-local-key" here would bypass that logic and quietly
    # re-introduce the default-key risk in production.
    app = Application(
        host=args.host,
        port=args.port,
        database_path=os.getenv("MAUSAM_DATABASE", "data/mausam-pulse.db"),
        api_key=os.getenv("MAUSAM_API_KEY"),
        cors_origin=os.getenv("MAUSAM_CORS_ORIGIN", "http://localhost:8080"),
        demo_mode=env_bool("MAUSAM_DEMO_MODE", True),
        demo_interval_s=parse_demo_interval(os.getenv("MAUSAM_DEMO_INTERVAL")),
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
    """Parse and validate port number from string."""
    try:
        port = int(value)
        if not 1 <= port <= 65535:
            raise argparse.ArgumentTypeError(f"Port must be 1-65535, got {port}")
        return port
    except ValueError:
        raise argparse.ArgumentTypeError(f"Port must be an integer, got '{value}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="MausamPulse Road Safety MVP")
    parser.add_argument("--host", default=os.getenv("MAUSAM_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=parse_port,
        default=8080
    )
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
