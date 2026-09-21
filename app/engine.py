"""Deterministic road-safety calculations.

The functions in this module deliberately distinguish measurements from
estimates.  They are useful for warnings and demonstrations, but are not a
certified Advanced Driver Assistance System (ADAS).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Any


GRAVITY_MPS2 = 9.80665
EARTH_RADIUS_M = 6_371_000.0

FRICTION_BY_CONDITION = {
    "clear": 0.70,
    "cloudy": 0.70,
    "fog": 0.60,
    "light_rain": 0.50,
    "rain": 0.45,
    "heavy_rain": 0.35,
    "flooding": 0.25,
    "snow": 0.25,
    "ice": 0.15,
    "dust_storm": 0.45,
}


@dataclass(frozen=True)
class CollisionAssessment:
    level: str
    time_to_collision_s: float | None
    reason: str
    recommended_action: str


@dataclass(frozen=True)
class BrakeAssessment:
    source: str
    brake_pressure_pct: float | None
    estimated_deceleration_mps2: float | None
    required_deceleration_mps2: float | None
    stop_line_status: str
    explanation: str
    stopping_distance_m: float
    stop_margin_m: float | None


@dataclass(frozen=True)
class VisibilityAssessment:
    level: str
    safe_speed_kph: float
    current_speed_kph: float
    visibility_m: float
    is_speed_above_guidance: bool
    guidance: str


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance between two WGS84 points in metres."""
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def destination_point(
    latitude: float, longitude: float, distance_m: float, bearing_deg: float
) -> tuple[float, float]:
    """Move a point along a great-circle bearing."""
    angular = distance_m / EARTH_RADIUS_M
    bearing = radians(bearing_deg)
    lat1 = radians(latitude)
    lon1 = radians(longitude)
    lat2 = asin(
        sin(lat1) * cos(angular)
        + cos(lat1) * sin(angular) * cos(bearing)
    )
    lon2 = lon1 + atan2(
        sin(bearing) * sin(angular) * cos(lat1),
        cos(angular) - sin(lat1) * sin(lat2),
    )
    return degrees(lat2), ((degrees(lon2) + 540) % 360) - 180


def estimate_deceleration_mps2(
    previous_speed_kph: float | None,
    current_speed_kph: float,
    previous_time: str | datetime | None,
    current_time: str | datetime,
) -> float | None:
    """Estimate positive braking deceleration from consecutive speeds.

    Returns 0 for constant/accelerating motion and ``None`` when there is no
    usable previous sample.
    """
    if previous_speed_kph is None or previous_time is None:
        return None
    seconds = (parse_time(current_time) - parse_time(previous_time)).total_seconds()
    if seconds <= 0 or seconds > 30:
        return None
    delta_mps = (previous_speed_kph - current_speed_kph) / 3.6
    return round(max(0.0, delta_mps / seconds), 3)


def braking_distance_m(
    speed_kph: float,
    condition: str = "clear",
    reaction_time_s: float = 1.5,
) -> float:
    speed_mps = max(0.0, speed_kph) / 3.6
    friction = FRICTION_BY_CONDITION.get(condition, FRICTION_BY_CONDITION["clear"])
    reaction = speed_mps * max(0.0, reaction_time_s)
    physical = speed_mps**2 / (2 * friction * GRAVITY_MPS2)
    return round(reaction + physical, 1)


def required_deceleration_mps2(speed_kph: float, available_distance_m: float) -> float | None:
    if available_distance_m <= 0:
        return None
    speed_mps = max(0.0, speed_kph) / 3.6
    return round(speed_mps**2 / (2 * available_distance_m), 3)


def assess_collision(
    speed_kph: float,
    lead_vehicle_distance_m: float | None,
    lead_vehicle_speed_kph: float | None,
) -> CollisionAssessment:
    """Assess rear-end collision risk using time-to-collision (TTC).

    Own speed alone is insufficient. A finite TTC is produced only when lead
    distance and lead speed are both supplied and the gap is closing.
    """
    if lead_vehicle_distance_m is None or lead_vehicle_speed_kph is None:
        return CollisionAssessment(
            "unknown",
            None,
            "Relative distance and lead-vehicle speed are unavailable.",
            "Use a camera, radar, lidar, or V2X source for collision warnings.",
        )
    if lead_vehicle_distance_m <= 0:
        return CollisionAssessment(
            "critical", 0.0, "The reported separation is zero.", "Brake immediately."
        )
    closing_speed_mps = (speed_kph - lead_vehicle_speed_kph) / 3.6
    if closing_speed_mps <= 0:
        return CollisionAssessment(
            "low",
            None,
            "The distance to the lead vehicle is not currently closing.",
            "Maintain a safe following distance.",
        )
    ttc = round(lead_vehicle_distance_m / closing_speed_mps, 2)
    if ttc < 2.0:
        return CollisionAssessment("critical", ttc, "TTC is below 2 seconds.", "Brake immediately.")
    if ttc < 4.0:
        return CollisionAssessment("high", ttc, "TTC is below 4 seconds.", "Slow down now and increase the gap.")
    if ttc < 7.0:
        return CollisionAssessment("moderate", ttc, "The closing gap needs attention.", "Ease off the accelerator and increase the gap.")
    return CollisionAssessment("low", ttc, "The current TTC is above 7 seconds.", "Continue monitoring the road.")


def safe_speed_for_visibility_kph(
    visibility_m: float,
    condition: str = "clear",
    reaction_time_s: float = 1.5,
    safety_margin: float = 0.75,
    speed_limit_kph: float | None = None,
) -> float:
    """Solve for a speed whose estimated stopping distance fits visibility."""
    usable_distance = max(1.0, visibility_m * clamp(safety_margin, 0.2, 1.0))
    friction = FRICTION_BY_CONDITION.get(condition, FRICTION_BY_CONDITION["clear"])
    a = 1.0 / (2 * friction * GRAVITY_MPS2)
    b = max(0.1, reaction_time_s)
    speed_mps = (-b + sqrt(b * b + 4 * a * usable_distance)) / (2 * a)
    speed_kph = max(5.0, speed_mps * 3.6)
    if speed_limit_kph is not None:
        speed_kph = min(speed_kph, max(5.0, speed_limit_kph))
    return round(speed_kph, 1)


def assess_visibility(
    visibility_m: float,
    speed_kph: float,
    condition: str,
    speed_limit_kph: float | None = None,
) -> VisibilityAssessment:
    safe_speed = safe_speed_for_visibility_kph(
        visibility_m, condition, speed_limit_kph=speed_limit_kph
    )
    if visibility_m < 50:
        level = "critical"
        base = "Extremely poor visibility. Avoid travel or stop at a safe place."
    elif visibility_m < 100:
        level = "high"
        base = "Severely reduced visibility. Use low-beam lamps and increase spacing."
    elif visibility_m < 250:
        level = "moderate"
        base = "Reduced visibility. Slow down and avoid sudden manoeuvres."
    else:
        level = "low"
        base = "Visibility is currently acceptable; continue monitoring conditions."
    above = speed_kph > safe_speed + 1.0
    guidance = base
    if above:
        guidance += f" Reduce speed toward {safe_speed:.0f} km/h or lower."
    return VisibilityAssessment(
        level,
        safe_speed,
        round(speed_kph, 1),
        round(visibility_m, 1),
        above,
        guidance,
    )


def assess_braking(
    *,
    speed_kph: float,
    previous_speed_kph: float | None,
    previous_time: str | datetime | None,
    current_time: str | datetime,
    brake_pressure_pct: float | None,
    brake_sensor_source: str | None,
    traffic_light_state: str | None,
    distance_to_stop_line_m: float | None,
    weather_condition: str = "clear",
) -> BrakeAssessment:
    estimated = estimate_deceleration_mps2(
        previous_speed_kph, speed_kph, previous_time, current_time
    )
    if brake_pressure_pct is not None:
        source = (
            "obd_can_exact_input"
            if brake_sensor_source == "obd_can"
            else "simulated_obd_can_input"
        )
        pressure = round(clamp(brake_pressure_pct, 0.0, 100.0), 1)
        explanation = "Brake pressure was supplied by the vehicle interface."
    elif estimated is not None and estimated >= 0.35:
        source = "phone_estimate"
        pressure = None
        explanation = "Braking was estimated from the change in speed; pedal pressure is unknown."
    else:
        source = "not_detected"
        pressure = None
        explanation = "No reliable braking input was detected."

    stopping_distance = braking_distance_m(speed_kph, weather_condition)
    required = None
    stop_margin = None
    status = "not_applicable"
    if traffic_light_state == "red" and distance_to_stop_line_m is not None:
        required = required_deceleration_mps2(speed_kph, distance_to_stop_line_m)
        stop_margin = round(distance_to_stop_line_m - stopping_distance, 1)
        if distance_to_stop_line_m <= 8 and speed_kph <= 2:
            status = "stopped_at_line"
        elif distance_to_stop_line_m <= 0 and speed_kph > 2:
            status = "stop_line_crossed"
        elif stop_margin < 0 or (required is not None and required > 4.5):
            status = "hard_braking_required"
        else:
            status = "approaching_red_signal"
    return BrakeAssessment(
        source,
        pressure,
        estimated,
        required,
        status,
        explanation,
        stopping_distance,
        stop_margin,
    )


def pothole_signal_confidence(
    vertical_acceleration_g: float | None,
    speed_kph: float,
    camera_confirmed: bool = False,
) -> float:
    """Score a possible pothole from an IMU impulse and optional camera signal."""
    score = 0.0
    if vertical_acceleration_g is not None and 5 <= speed_kph <= 100:
        impulse = abs(vertical_acceleration_g)
        if impulse >= 2.5:
            score = 0.72
        elif impulse >= 1.8:
            score = 0.55
        elif impulse >= 1.35:
            score = 0.32
    if camera_confirmed:
        score = max(score, 0.65) + 0.20
    return round(clamp(score, 0.0, 0.95), 2)


def aggregate_pothole_confidence(
    report_count: int,
    distinct_vehicles: int,
    strongest_signal: float,
) -> tuple[float, str]:
    """Calculate confidence score and status for pothole detection.

    Args:
        report_count: Total number of reports for this pothole.
        distinct_vehicles: Number of different vehicles that reported it.
        strongest_signal: Highest confidence signal from all reports.

    Returns:
        Tuple of (confidence_score, status_string).
    """
    if report_count < 1 or distinct_vehicles < 0:
        raise ValueError(
            f"Invalid counts: report_count={report_count}, distinct_vehicles={distinct_vehicles}"
        )
    # A caller cannot have more distinct vehicles than total reports.
    # Without this guard, a malicious or buggy caller could pass
    # distinct_vehicles=5, report_count=1 and inflate the confidence
    # score through the distinct-vehicle bonus below.
    if distinct_vehicles > report_count:
        raise ValueError(
            f"distinct_vehicles ({distinct_vehicles}) cannot exceed "
            f"report_count ({report_count})"
        )

    confidence = strongest_signal + min(0.28, max(0, distinct_vehicles - 1) * 0.14)
    confidence += min(0.08, max(0, report_count - distinct_vehicles) * 0.02)
    confidence = round(clamp(confidence, 0.0, 0.99), 2)

    if distinct_vehicles >= 3 and confidence >= 0.75:
        status = "verified"
    elif distinct_vehicles >= 2 and confidence >= 0.55:
        status = "likely"
    else:
        status = "unverified"

    return confidence, status


def assessment_to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
