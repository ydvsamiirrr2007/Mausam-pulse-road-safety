"""Small dependency-free input validation layer."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .database import utc_now


WEATHER_EVENTS = {
    "rain", "heavy_rain", "fog", "thunderstorm", "lightning", "flooding",
    "heatwave", "cold_wave", "dust_storm", "strong_winds", "hail", "snow",
    "cyclone", "ice", "other",
}
WEATHER_CONDITIONS = {
    "clear", "cloudy", "fog", "light_rain", "rain", "heavy_rain",
    "flooding", "snow", "ice", "dust_storm",
}
SEVERITIES = {"info", "advisory", "watch", "warning", "emergency"}
POTHOLE_SEVERITIES = {"minor", "moderate", "severe"}
TRAFFIC_LIGHT_STATES = {"red", "amber", "green", "unknown"}


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _sanitize_text(value: Any, *, max_length: int | None = None) -> str:
    """Trim, HTML-escape, and optionally truncate a free-text value.

    Escaping at the validation boundary means no value written to the
    database can be interpreted as markup, even if the dashboard ever
    renders it via ``innerHTML``. Values are preserved as-is when the
    frontend uses ``textContent``; only dangerous metacharacters are
    converted to entities.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if max_length is not None and len(text) > max_length:
        text = text[:max_length]
    return html.escape(text, quote=True)


def _required(payload: dict[str, Any], names: Iterable[str], errors: list[str]) -> None:
    for name in names:
        if payload.get(name) is None or payload.get(name) == "":
            errors.append(f"{name} is required")


def _number(
    payload: dict[str, Any],
    name: str,
    errors: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    required: bool = False,
) -> float | None:
    value = payload.get(name)
    if value is None:
        if required:
            errors.append(f"{name} is required")
        return None
    if isinstance(value, bool):
        errors.append(f"{name} must be a number")
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a number")
        return None
    if minimum is not None and result < minimum:
        errors.append(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        errors.append(f"{name} must be at most {maximum}")
    return result


def _choice(payload: dict[str, Any], name: str, choices: set[str], errors: list[str], default: str | None = None) -> str | None:
    value = payload.get(name, default)
    if value is None:
        return None
    value = str(value).strip().lower()
    if value not in choices:
        errors.append(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


def _timestamp(value: Any, name: str, errors: list[str], default: str | None = None) -> str | None:
    value = value or default
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        errors.append(f"{name} must be an ISO-8601 timestamp")
        return None


def validate_user(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _required(payload, ["display_name"], errors)
    raw_name = str(payload.get("display_name", "")).strip()
    if len(raw_name) > 80:
        errors.append("display_name must be 80 characters or fewer")
    if errors:
        raise ValidationError(errors)
    display_name = _sanitize_text(raw_name, max_length=80)
    raw_full = str(payload.get("full_name") or "").strip()
    if not raw_full:
        raw_full = raw_name
    full_name = _sanitize_text(raw_full, max_length=120)
    emergency_contact = _sanitize_text(payload.get("emergency_contact"), max_length=80) or None
    return {
        "id": payload.get("id"),
        "display_name": display_name,
        "full_name": full_name,
        "emergency_contact": emergency_contact,
        "share_live_identity": bool(payload.get("share_live_identity", False)),
    }


def validate_vehicle(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _required(payload, ["owner_user_id", "display_name"], errors)
    if errors:
        raise ValidationError(errors)
    return {
        "id": payload.get("id"),
        "owner_user_id": str(payload["owner_user_id"]),
        "display_name": _sanitize_text(payload["display_name"], max_length=120),
        "manufacturer": _sanitize_text(payload.get("manufacturer"), max_length=80) or None,
        "model": _sanitize_text(payload.get("model"), max_length=80) or None,
        "registration_number": _sanitize_text(payload.get("registration_number"), max_length=40) or None,
        "color": _sanitize_text(payload.get("color"), max_length=40) or None,
        "share_live_identity": bool(payload.get("share_live_identity", False)),
    }


def validate_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _required(payload, ["vehicle_id", "user_id"], errors)
    latitude = _number(payload, "latitude", errors, minimum=-90, maximum=90, required=True)
    longitude = _number(payload, "longitude", errors, minimum=-180, maximum=180, required=True)
    speed = _number(payload, "speed_kph", errors, minimum=0, maximum=350, required=True)
    visibility = _number(payload, "visibility_m", errors, minimum=1, maximum=100_000, required=True)
    heading = _number(payload, "heading_deg", errors, minimum=0, maximum=360)
    brake = _number(payload, "brake_pressure_pct", errors, minimum=0, maximum=100)
    vertical = _number(payload, "vertical_acceleration_g", errors, minimum=-10, maximum=10)
    lead_distance = _number(payload, "lead_vehicle_distance_m", errors, minimum=0, maximum=10_000)
    lead_speed = _number(payload, "lead_vehicle_speed_kph", errors, minimum=0, maximum=350)
    stop_distance = _number(payload, "distance_to_stop_line_m", errors, minimum=-100, maximum=5_000)
    speed_limit = _number(payload, "speed_limit_kph", errors, minimum=5, maximum=200)
    condition = _choice(payload, "weather_condition", WEATHER_CONDITIONS, errors, "clear")
    light = _choice(payload, "traffic_light_state", TRAFFIC_LIGHT_STATES, errors, "unknown")
    observed = _timestamp(payload.get("observed_at"), "observed_at", errors, utc_now())
    brake_source = payload.get("brake_sensor_source")
    if brake is not None and brake_source not in {"obd_can", "simulated_obd_can"}:
        errors.append("brake_pressure_pct requires brake_sensor_source=obd_can or simulated_obd_can")
    if (lead_distance is None) != (lead_speed is None):
        errors.append("lead_vehicle_distance_m and lead_vehicle_speed_kph must be supplied together")
    if errors:
        raise ValidationError(errors)
    return {
        "vehicle_id": str(payload["vehicle_id"]),
        "user_id": str(payload["user_id"]),
        "observed_at": observed,
        "latitude": latitude,
        "longitude": longitude,
        "speed_kph": speed,
        "heading_deg": heading,
        "weather_condition": condition,
        "visibility_m": visibility,
        "speed_limit_kph": speed_limit,
        "brake_pressure_pct": brake,
        "brake_sensor_source": brake_source,
        "traffic_light_state": light,
        "distance_to_stop_line_m": stop_distance,
        "lead_vehicle_distance_m": lead_distance,
        "lead_vehicle_speed_kph": lead_speed,
        "vertical_acceleration_g": vertical,
        "camera_pothole_confirmed": bool(payload.get("camera_pothole_confirmed", False)),
    }


def validate_weather_alert(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _required(payload, ["event_type", "severity", "title", "description"], errors)
    event = _choice(payload, "event_type", WEATHER_EVENTS, errors)
    severity = _choice(payload, "severity", SEVERITIES, errors)
    latitude = _number(payload, "latitude", errors, minimum=-90, maximum=90, required=True)
    longitude = _number(payload, "longitude", errors, minimum=-180, maximum=180, required=True)
    radius = _number(payload, "radius_km", errors, minimum=0.1, maximum=1_000) or 25.0
    starts = _timestamp(payload.get("starts_at"), "starts_at", errors, utc_now())
    default_end = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    ends = _timestamp(payload.get("ends_at"), "ends_at", errors, default_end)
    if starts and ends and starts >= ends:
        errors.append("ends_at must be after starts_at")
    if errors:
        raise ValidationError(errors)
    return {
        "id": payload.get("id"),
        "event_type": event,
        "severity": severity,
        "title": _sanitize_text(payload["title"], max_length=200),
        "description": _sanitize_text(payload["description"], max_length=2000),
        "latitude": latitude,
        "longitude": longitude,
        "radius_km": radius,
        "starts_at": starts,
        "ends_at": ends,
        "source": _sanitize_text(payload.get("source", "manual"), max_length=200) or "manual",
        "instructions": _sanitize_text(
            payload.get("instructions", "Monitor local official guidance."),
            max_length=2000,
        ),
    }


def validate_pothole_report(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    latitude = _number(payload, "latitude", errors, minimum=-90, maximum=90, required=True)
    longitude = _number(payload, "longitude", errors, minimum=-180, maximum=180, required=True)
    severity = _choice(payload, "severity", POTHOLE_SEVERITIES, errors, "moderate")
    signal = _number(payload, "signal_confidence", errors, minimum=0, maximum=1) or 0.45
    reported = _timestamp(payload.get("reported_at"), "reported_at", errors, utc_now())
    if errors:
        raise ValidationError(errors)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "severity": severity,
        "signal_confidence": signal,
        "vehicle_id": payload.get("vehicle_id"),
        "user_id": payload.get("user_id"),
        "camera_confirmed": bool(payload.get("camera_confirmed", False)),
        "reported_at": reported,
    }
