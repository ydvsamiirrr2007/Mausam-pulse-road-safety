# Vehicle and sensor integration

## Smartphone-only mode

A phone can usually supply GNSS position, GNSS-derived speed, accelerometer/gyroscope samples, network connectivity, and optionally camera evidence. This supports weather geofencing, approximate braking detection, visibility advisories, and pothole evidence.

It does **not** provide exact brake-pedal position or hydraulic pressure. Phone placement, sampling frequency, GNSS multipath, vibration, and sensor calibration all affect the result. The MVP therefore labels phone braking as `phone_estimate` and never assigns it a pressure percentage.

## OBD-II and CAN mode

Generic OBD-II guarantees emissions-related diagnostics, not every chassis signal. Brake-pedal state, master-cylinder pressure, individual wheel speed, ABS activity, wiper state, and stability-control data may require manufacturer-specific PIDs, a CAN database, a supported telematics gateway, or an OEM agreement.

For each vehicle model:

1. Identify the authoritative signal definition and physical units.
2. Confirm update rate, scale, offset, invalid values, counters, and checksums.
3. Use read-only access during early development.
4. Sign and timestamp gateway envelopes and reject replays.
5. Record signal age and quality alongside every measurement.
6. Validate against calibrated reference equipment.

The current API accepts `brake_pressure_pct` only with `brake_sensor_source=obd_can` (or `simulated_obd_can` for the bundled demo). In production, the server must derive this source from authenticated device configuration rather than trusting a client-provided string.

## Collision measurements

Time-to-collision requires the distance to an object and the relative closing speed. Suitable sources include radar, stereo/monocular vision with a validated distance model, lidar, or V2X messages. GNSS positions from two ordinary phones are not sufficiently reliable for close-range emergency collision avoidance.

The MVP formula is:

\[
TTC = \frac{d}{v_{own} - v_{lead}}
\]

It is calculated only while the gap is closing. Real implementations must account for lane association, cut-ins, curvature, measurement covariance, object classification, sensor age, and braking capability.

## Traffic lights and stop lines

Possible sources, in descending order of operational authority, are authenticated infrastructure SPaT/MAP feeds, surveyed HD-map stop lines, validated on-device vision, and approximate public-map geometry. Every output should carry source and confidence.

Signal recognition must never assume that a map record represents the current lamp phase. The MVP accepts `traffic_light_state` and `distance_to_stop_line_m` as already-resolved inputs so the perception/source layer can be replaced independently.

## Visibility

Visibility may come from a weather station, roadside sensor, camera model, official nowcast, or operator report. Store the measurement method and uncertainty. Rain affects both visibility and road friction; fog primarily affects visibility, though condensation and local surface conditions can change grip.

Safety-grade nearby-object detection requires local sensors. Cloud-based user tracking can support shared awareness and fleet operations, but not emergency obstacle avoidance.
