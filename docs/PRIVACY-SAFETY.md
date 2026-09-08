# Privacy and safety controls

## Identity views

The bundled dashboard demonstrates three disclosure levels:

| Viewer | Identity | Location | Sensitive vehicle data |
|---|---|---|---|
| Public/unauthenticated | Consented display names only | Rounded to about 100 m | Hidden |
| Authenticated owner | Full own name | Precise reported coordinate | Registration and emergency contact |
| Future fleet/emergency role | Explicitly authorized scope only | Purpose- and time-limited | Policy-controlled and audited |

Both the user and vehicle must opt in before a public display identity appears. A registration number and emergency contact never appear in the public response.

The demo owner header is intentionally simple. Replace it with verified OIDC identity and server-side authorization before sharing the service.

## Browser route tracking

The dashboard starts location tracking only after the user presses **Track me** and grants browser permission. The coordinate is sent as a query to the current MausamPulse server so it can return weather alerts and potholes within 25 km; the tracking feature does not insert that coordinate into the database. Stopping tracking clears the active browser watch. A production deployment should avoid logging precise query strings, use short-lived proximity tokens or server-side geofencing where appropriate, and provide a clear retention and deletion policy.

## Required production controls

- Separate authentication for people, vehicles, sensors, and service accounts.
- Short-lived credentials, signed device messages, nonce/counter replay protection, and key rotation.
- Encryption in transit and at rest; field-level protection for identity and precise location.
- Purpose limitation, explicit consent, minimal retention, deletion/correction, and access logs.
- Coarse public maps, delayed public telemetry, and anti-stalking/anti-enumeration protections.
- Rate limits, anomaly detection, device revocation, incident response, and regular access reviews.
- Documented legal basis and local-law review for every geography and user group.

## Driver-interface safety

The mobile experience should default to audio/haptic warnings while moving, prevent complex interaction by the driver, suppress low-value alerts, and prioritize critical messages. Alert wording must be short, actionable, localized, and tested for false alarms and alarm fatigue.

The service must fail safely: stale, missing, contradictory, or low-confidence data should be shown as unknown rather than converted into false precision.

## Pothole protection

Raw camera evidence can reveal faces, license plates, homes, and travel history. Prefer on-device feature extraction; blur incidental identifiers before upload; retain only evidence needed for confirmation; and expire road hazards that are repaired or no longer corroborated.

## Operational boundary

This MVP does not contact emergency services, issue official weather warnings, control vehicle systems, or guarantee collision prevention. Those capabilities require explicit operating authority, certified components, formal hazard analysis, validation, monitored service levels, and human accountability.
