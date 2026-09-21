const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const TILE_SIZE = 256;
const state = {
  data: null,
  stream: null,
  lastToast: {},
  map: {
    latitude: 19.076,
    longitude: 72.8777,
    zoom: 13,
    mode: "road",
    layers: { vehicles: true, weather: true, potholes: true },
    fitted: false,
    tileKey: "",
    selected: null,
    drag: null,
  },
  tracking: {
    watchId: null,
    location: null,
    error: "",
    lastFetchAt: 0,
  },
};

function esc(value) {
  return String(value ?? "—").replace(
    /[&<>'"]/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;",
      })[character],
  );
}

function titleCase(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function numberOrDash(value, digits = 0) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

function badge(value) {
  return `<span class="badge ${esc(value)}">${esc(titleCase(value))}</span>`;
}

function timeAgo(value) {
  if (!value) return "No telemetry";
  const seconds = Math.max(
    0,
    Math.round((Date.now() - new Date(value).getTime()) / 1000),
  );
  if (seconds < 5) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function clockTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatUntil(value) {
  if (!value) return "Until further notice";
  return `Until ${new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function weatherGlyph(type) {
  if (String(type).includes("rain") || type === "flooding") return "☂";
  if (type === "fog" || type === "dust_storm") return "≋";
  if (["thunderstorm", "lightning"].includes(type)) return "ϟ";
  if (["snow", "ice", "hail"].includes(type)) return "✳";
  if (["strong_winds", "cyclone"].includes(type)) return "↝";
  return "!";
}

function renderMetrics(data) {
  const priority = data.recent_events.filter((event) =>
    ["critical", "high"].includes(event.level),
  ).length;
  const verified = data.potholes.filter(
    (pothole) => pothole.status === "verified",
  ).length;
  const liveVehicles = data.vehicles.filter(
    (vehicle) => vehicle.observed_at,
  ).length;
  const metrics = [
    {
      label: "Weather alerts",
      value: data.weather_alerts.length,
      note: "Rain, fog & severe weather",
      tone: "blue",
      icon: "☂",
    },
    {
      label: "Vehicles online",
      value: liveVehicles,
      note: "Streaming consented telemetry",
      tone: "green",
      icon: "▲",
    },
    {
      label: "Road hazards",
      value: data.potholes.length,
      note: `${verified} verified pothole${verified === 1 ? "" : "s"}`,
      tone: "yellow",
      icon: "!",
    },
    {
      label: "Priority warnings",
      value: priority,
      note: "High & critical recent events",
      tone: "red",
      icon: "↘",
    },
  ];
  $("#metrics").innerHTML = metrics
    .map(
      (metric) => `
    <article class="metric ${metric.tone}">
      <span class="metric-icon" aria-hidden="true">${metric.icon}</span>
      <span class="metric-copy"><small>${esc(metric.label)}</small><strong>${esc(metric.value)}</strong><span>${esc(metric.note)}</span></span>
    </article>`,
    )
    .join("");
}

function renderWeather(alerts) {
  $("#weather-count").textContent = alerts.length;
  $("#weather-alerts").innerHTML = alerts.length
    ? alerts
        .map(
          (alert) => `
    <article class="alert-card ${esc(alert.severity)}">
      <div class="alert-glyph ${esc(alert.event_type)}" aria-hidden="true">${weatherGlyph(alert.event_type)}</div>
      <div class="alert-body">
        <div class="row-head"><strong>${esc(alert.title)}</strong>${badge(alert.severity)}</div>
        <p>${esc(alert.instructions || alert.description)}</p>
        <div class="alert-meta">
          <span>${esc(titleCase(alert.event_type))}</span>
          ${alert.distance_km != null ? `<span>${numberOrDash(alert.distance_km, 1)} km away</span>` : ""}
          <span>${esc(formatUntil(alert.ends_at))}</span>
        </div>
        <button class="text-button" type="button" data-focus-lat="${Number(alert.latitude)}" data-focus-lon="${Number(alert.longitude)}" data-select-kind="weather" data-select-id="${esc(alert.id)}">Show on map</button>
      </div>
    </article>`,
        )
        .join("")
    : `<div class="empty-state"><span>✓</span><strong>No active weather warning nearby</strong><p>Live monitoring remains on.</p></div>`;
}

function eventAction(event) {
  return (
    event?.details?.recommended_action ||
    event?.details?.guidance ||
    event?.details?.explanation ||
    "Continue monitoring the road."
  );
}

function renderPriority(data) {
  const event = data.recent_events.find((item) =>
    ["critical", "high"].includes(item.level),
  );
  const weather = data.weather_alerts.find((item) =>
    ["emergency", "warning"].includes(item.severity),
  );
  const panel = $("#priority-panel");
  if (event) {
    panel.className = `surface priority-panel level-${event.level}`;
    panel.innerHTML = `
      <div class="priority-top"><span class="eyebrow">Priority guidance</span>${badge(event.level)}</div>
      <div class="priority-symbol" aria-hidden="true">${event.event_type.includes("collision") ? "↘" : event.event_type.includes("visibility") ? "◉" : "!"}</div>
      <h2>${esc(titleCase(event.event_type))}</h2>
      <p>${esc(eventAction(event))}</p>
      <div class="priority-meta"><span>${esc(timeAgo(event.observed_at))}</span><button type="button" class="text-button" data-focus-lat="${Number(event.latitude)}" data-focus-lon="${Number(event.longitude)}">Locate event</button></div>`;
    return;
  }
  if (weather) {
    panel.className = "surface priority-panel level-moderate";
    panel.innerHTML = `
      <div class="priority-top"><span class="eyebrow">Priority guidance</span>${badge(weather.severity)}</div>
      <div class="priority-symbol" aria-hidden="true">${weatherGlyph(weather.event_type)}</div>
      <h2>${esc(weather.title)}</h2><p>${esc(weather.instructions)}</p>
      <div class="priority-meta"><span>${esc(formatUntil(weather.ends_at))}</span></div>`;
    return;
  }
  panel.className = "surface priority-panel level-low";
  panel.innerHTML = `
    <div class="priority-top"><span class="eyebrow">Priority guidance</span>${badge("low")}</div>
    <div class="priority-symbol safe" aria-hidden="true">✓</div>
    <h2>No immediate high-risk event</h2><p>Conditions can change quickly. Keep live monitoring active.</p>`;
}

function brakeSourceLabel(source) {
  const labels = {
    obd_can_exact_input: "Exact vehicle sensor",
    simulated_obd_can_input: "Live demo sensor",
    phone_estimate: "Phone speed estimate",
    not_detected: "No braking signal",
    unknown: "Waiting for signal",
  };
  return labels[source] || titleCase(source);
}

function trafficLight(stateName) {
  const current = ["red", "amber", "green"].includes(stateName)
    ? stateName
    : "unknown";
  return `<span class="traffic-light" aria-label="Traffic light: ${esc(current)}">
    <i class="red ${current === "red" ? "active" : ""}"></i>
    <i class="amber ${current === "amber" ? "active" : ""}"></i>
    <i class="green ${current === "green" ? "active" : ""}"></i>
  </span>`;
}

function renderVehicles(vehicles) {
  $("#vehicles").innerHTML = vehicles.length
    ? vehicles
        .map((vehicle) => {
          const assessments = vehicle.assessments || {};
          const collision = assessments.collision || {};
          const visibility = assessments.visibility || {};
          const braking = assessments.braking || {};
          const collisionLevel = collision.level || "unknown";
          const ttc =
            collision.time_to_collision_s == null
              ? "Stable"
              : `${numberOrDash(collision.time_to_collision_s, 1)}s`;
          const ttcLabel =
            collision.time_to_collision_s == null
              ? "No closing risk"
              : "Time to collision";
          const pressure =
            braking.brake_pressure_pct == null
              ? "—"
              : `${numberOrDash(braking.brake_pressure_pct, 0)}%`;
          const deceleration =
            braking.estimated_deceleration_mps2 == null
              ? "—"
              : `${numberOrDash(braking.estimated_deceleration_mps2, 1)} m/s²`;
          const required =
            braking.required_deceleration_mps2 == null
              ? "—"
              : `${numberOrDash(braking.required_deceleration_mps2, 1)} m/s²`;
          const stopDistance =
            braking.stopping_distance_m == null
              ? "—"
              : `${numberOrDash(braking.stopping_distance_m, 0)} m`;
          const stopMargin =
            braking.stop_margin_m == null
              ? "—"
              : `${braking.stop_margin_m > 0 ? "+" : ""}${numberOrDash(braking.stop_margin_m, 0)} m`;
          const metadata =
            [vehicle.manufacturer, vehicle.model, vehicle.color]
              .filter(Boolean)
              .join(" · ") || "Identity protected";
          const registration = vehicle.registration_number
            ? ` · ${vehicle.registration_number}`
            : "";
          const exactSignal = braking.source === "obd_can_exact_input";
          const signalState = vehicle.traffic_light_state || "unknown";
          const riskWidth =
            collision.time_to_collision_s == null
              ? 12
              : Math.max(
                  10,
                  Math.min(
                    100,
                    ((7 - Number(collision.time_to_collision_s)) / 7) * 100,
                  ),
                );
          const safeSpeed =
            visibility.safe_speed_kph == null
              ? "—"
              : numberOrDash(visibility.safe_speed_kph, 0);
          return `<article class="vehicle-card level-${esc(collisionLevel)}">
      <header class="vehicle-head">
        <div class="vehicle-identity">
          <span class="vehicle-avatar" aria-hidden="true">${esc((vehicle.vehicle_name || "V").slice(0, 1).toUpperCase())}</span>
          <div><div class="identity-line"><h3>${esc(vehicle.vehicle_name)}</h3><span class="online-chip"><i></i>${esc(timeAgo(vehicle.observed_at))}</span></div>
          <p><strong>${esc(vehicle.user_name)}</strong> · ${esc(metadata)}${esc(registration)}</p></div>
        </div>
        ${vehicle.latitude != null ? `<button class="locate-mini" type="button" data-focus-lat="${Number(vehicle.latitude)}" data-focus-lon="${Number(vehicle.longitude)}" data-select-kind="vehicle" data-select-id="${esc(vehicle.id)}">Locate</button>` : ""}
      </header>

      <div class="safety-stat-grid">
        <div class="safety-stat speed-stat"><span>Current speed</span><strong>${numberOrDash(vehicle.speed_kph, 0)}<small> km/h</small></strong><em>Limit ${vehicle.speed_limit_kph == null ? "—" : numberOrDash(vehicle.speed_limit_kph, 0)}</em></div>
        <div class="safety-stat"><span>${esc(ttcLabel)}</span><strong class="risk-${esc(collisionLevel)}">${esc(ttc)}</strong><em>${esc(titleCase(collisionLevel))} risk</em></div>
        <div class="safety-stat"><span>Road visibility</span><strong>${numberOrDash(vehicle.visibility_m, 0)}<small> m</small></strong><em>${esc(titleCase(vehicle.weather_condition))}</em></div>
        <div class="safety-stat"><span>Safe speed guide</span><strong>${esc(safeSpeed)}<small> km/h</small></strong><em>${visibility.is_speed_above_guidance ? "Slow down" : "Within guide"}</em></div>
      </div>

      <div class="risk-meter" aria-label="Collision risk level"><span class="${esc(collisionLevel)}" style="width:${riskWidth}%"></span></div>
      <div class="live-guidance ${esc(collisionLevel)}"><span aria-hidden="true">${collisionLevel === "critical" ? "!" : "→"}</span><p>${esc(collision.recommended_action || visibility.guidance || "Waiting for telemetry")}</p></div>

      <section class="brake-console">
        <div class="brake-title">
          <div>${trafficLight(signalState)}<span><small>Traffic-light braking</small><strong>${esc(titleCase(braking.stop_line_status || "not applicable"))}</strong></span></div>
          <span class="sensor-chip ${exactSignal ? "exact" : ""}"><i></i>${esc(brakeSourceLabel(braking.source || "unknown"))}</span>
        </div>
        <div class="brake-grid">
          <div><span>Brake applied</span><strong>${esc(pressure)}</strong><small>${braking.brake_pressure_pct == null ? deceleration : "Pedal / pressure input"}</small></div>
          <div><span>Distance to light</span><strong>${vehicle.distance_to_stop_line_m == null ? "—" : `${numberOrDash(vehicle.distance_to_stop_line_m, 0)} m`}</strong><small>Measured stop line</small></div>
          <div><span>Calculated stop</span><strong>${esc(stopDistance)}</strong><small>Includes road condition</small></div>
          <div class="${Number(braking.stop_margin_m) < 0 ? "danger-value" : ""}"><span>Safety margin</span><strong>${esc(stopMargin)}</strong><small>Available minus required</small></div>
          <div><span>Required braking</span><strong>${esc(required)}</strong><small>To reach stop line</small></div>
          <div><span>Lead vehicle</span><strong>${vehicle.lead_vehicle_distance_m == null ? "—" : `${numberOrDash(vehicle.lead_vehicle_distance_m, 0)} m`}</strong><small>${vehicle.lead_vehicle_speed_kph == null ? "No relative sensor" : `${numberOrDash(vehicle.lead_vehicle_speed_kph, 0)} km/h ahead`}</small></div>
        </div>
      </section>
      <footer class="vehicle-footer"><span>Position: ${esc(titleCase(vehicle.location_precision))}</span>${vehicle.emergency_contact ? `<span>Emergency: ${esc(vehicle.emergency_contact)}</span>` : ""}</footer>
    </article>`;
        })
        .join("")
    : `<div class="empty-state wide"><span>○</span><strong>No vehicle telemetry yet</strong><p>Register a vehicle or start the demo stream.</p></div>`;
}

function renderPotholes(items) {
  $("#potholes").innerHTML = items.length
    ? items
        .map(
          (pothole) => `
    <article class="pothole-card">
      <div class="pothole-symbol" aria-hidden="true"><span>!</span></div>
      <div class="pothole-copy">
        <div class="row-head"><strong>${esc(titleCase(pothole.severity))} road defect</strong>${badge(pothole.status)}</div>
        <p>${esc(pothole.report_count)} report${pothole.report_count === 1 ? "" : "s"} from ${esc(pothole.reporting_vehicle_count)} independent vehicle${pothole.reporting_vehicle_count === 1 ? "" : "s"}.</p>
        <div class="confidence-row"><span><i style="width:${Math.round(pothole.confidence * 100)}%"></i></span><strong>${Math.round(pothole.confidence * 100)}%</strong></div>
        <div class="alert-meta"><span>${numberOrDash(pothole.latitude, 4)}, ${numberOrDash(pothole.longitude, 4)}</span><span>${esc(timeAgo(pothole.last_reported_at))}</span></div>
      </div>
      <button class="locate-mini" type="button" data-focus-lat="${Number(pothole.latitude)}" data-focus-lon="${Number(pothole.longitude)}" data-select-kind="pothole" data-select-id="${esc(pothole.id)}">Locate</button>
    </article>`,
        )
        .join("")
    : `<div class="empty-state"><span>✓</span><strong>No pothole reports nearby</strong><p>Camera, IMU and manual reports appear here.</p></div>`;
}

function eventIcon(type) {
  if (type.includes("collision")) return "↘";
  if (type.includes("visibility")) return "◉";
  if (type.includes("signal")) return "◇";
  return "!";
}

function renderEvents(events) {
  $("#events").innerHTML = events.length
    ? events
        .slice(0, 18)
        .map(
          (event) => `
    <article class="event-row level-${esc(event.level)}">
      <div class="event-icon" aria-hidden="true">${eventIcon(event.event_type)}</div>
      <div class="event-copy"><div class="row-head"><strong>${esc(titleCase(event.event_type))}</strong>${badge(event.level)}</div><p>${esc(eventAction(event))}</p><span>${esc(timeAgo(event.observed_at))}</span></div>
      <button class="locate-mini icon-only" type="button" aria-label="Locate event" data-focus-lat="${Number(event.latitude)}" data-focus-lon="${Number(event.longitude)}">⌖</button>
    </article>`,
        )
        .join("")
    : `<div class="empty-state"><span>✓</span><strong>No safety event recorded</strong><p>New live warnings appear here.</p></div>`;
}

function worldPoint(latitude, longitude, zoom) {
  const lat = Math.max(-85.05112878, Math.min(85.05112878, Number(latitude)));
  const scale = TILE_SIZE * 2 ** zoom;
  const sinLatitude = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((Number(longitude) + 180) / 360) * scale,
    y:
      (0.5 - Math.log((1 + sinLatitude) / (1 - sinLatitude)) / (4 * Math.PI)) *
      scale,
  };
}

function coordinatesFromWorld(x, y, zoom) {
  const scale = TILE_SIZE * 2 ** zoom;
  const longitude = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const latitude = (180 / Math.PI) * Math.atan(Math.sinh(n));
  return { latitude, longitude: ((longitude + 540) % 360) - 180 };
}

function mapPixel(latitude, longitude, rect) {
  const center = worldPoint(
    state.map.latitude,
    state.map.longitude,
    state.map.zoom,
  );
  const point = worldPoint(latitude, longitude, state.map.zoom);
  return {
    x: point.x - center.x + rect.width / 2,
    y: point.y - center.y + rect.height / 2,
  };
}

function tileUrl(zoom, x, y) {
  if (state.map.mode === "satellite") {
    return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${y}/${x}`;
  }
  // Switched to Esri Street Map to fix the 403 Access Blocked error
  return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/${zoom}/${y}/${x}`;
}

function renderTiles() {
  const map = $("#map");
  const tileLayer = $("#tile-layer");
  const rect = map.getBoundingClientRect();
  if (rect.width < 40 || rect.height < 40) return;
  const center = worldPoint(
    state.map.latitude,
    state.map.longitude,
    state.map.zoom,
  );
  const minWorldX = center.x - rect.width / 2;
  const minWorldY = center.y - rect.height / 2;
  const startX = Math.floor(minWorldX / TILE_SIZE);
  const endX = Math.floor((center.x + rect.width / 2) / TILE_SIZE);
  const startY = Math.floor(minWorldY / TILE_SIZE);
  const endY = Math.floor((center.y + rect.height / 2) / TILE_SIZE);
  const tileCount = 2 ** state.map.zoom;
  const tileKey = [
    state.map.mode,
    state.map.zoom,
    startX,
    endX,
    startY,
    endY,
  ].join(":");
  if (tileKey === state.map.tileKey) {
    [...tileLayer.children].forEach((image) => {
      image.style.left = `${Number(image.dataset.tileX) * TILE_SIZE - minWorldX}px`;
      image.style.top = `${Number(image.dataset.tileY) * TILE_SIZE - minWorldY}px`;
    });
    return;
  }
  state.map.tileKey = tileKey;
  tileLayer.innerHTML = "";
  for (let tileY = startY; tileY <= endY; tileY += 1) {
    if (tileY < 0 || tileY >= tileCount) continue;
    for (let tileX = startX; tileX <= endX; tileX += 1) {
      const wrappedX = ((tileX % tileCount) + tileCount) % tileCount;
      const image = document.createElement("img");
      image.className = "map-tile";
      image.alt = "";
      image.draggable = false;
      image.src = tileUrl(state.map.zoom, wrappedX, tileY);
      image.dataset.tileX = tileX;
      image.dataset.tileY = tileY;
      image.style.left = `${tileX * TILE_SIZE - minWorldX}px`;
      image.style.top = `${tileY * TILE_SIZE - minWorldY}px`;
      image.addEventListener("error", () => image.remove(), { once: true });
      tileLayer.append(image);
    }
  }
  $("#map-attribution").textContent =
    state.map.mode === "satellite"
      ? "Imagery © Esri · markers © MausamPulse"
      : "© OpenStreetMap contributors · markers © MausamPulse";
}

function renderMapSelection() {
  const panel = $("#map-selection");
  const selected = state.map.selected;
  if (!selected || !state.data) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  let title = "Live map item";
  let detail = "";
  let meta = "";
  if (selected.kind === "vehicle") {
    const vehicle = state.data.vehicles.find((item) => item.id === selected.id);
    if (!vehicle) return void (panel.hidden = true);
    title = vehicle.vehicle_name;
    detail = `${vehicle.user_name} · ${numberOrDash(vehicle.speed_kph, 0)} km/h`;
    meta = `${titleCase(vehicle.weather_condition)} · ${numberOrDash(vehicle.visibility_m, 0)} m visibility`;
  } else if (selected.kind === "pothole") {
    const pothole = state.data.potholes.find((item) => item.id === selected.id);
    if (!pothole) return void (panel.hidden = true);
    title = `${titleCase(pothole.severity)} pothole`;
    detail = `${Math.round(pothole.confidence * 100)}% confidence · ${titleCase(pothole.status)}`;
    meta = `${pothole.report_count} report${pothole.report_count === 1 ? "" : "s"}`;
  } else if (selected.kind === "weather") {
    const alert = state.data.weather_alerts.find(
      (item) => item.id === selected.id,
    );
    if (!alert) return void (panel.hidden = true);
    title = alert.title;
    detail = alert.instructions;
    meta = `${titleCase(alert.event_type)} · ${formatUntil(alert.ends_at)}`;
  } else if (selected.kind === "user" && state.tracking.location) {
    title = "Your live position";
    detail = `Accuracy ±${Math.round(state.tracking.location.accuracy)} m`;
    meta = `${numberOrDash(state.tracking.location.latitude, 4)}, ${numberOrDash(state.tracking.location.longitude, 4)}`;
  }
  panel.hidden = false;
  panel.innerHTML = `<button id="close-map-selection" type="button" aria-label="Close map detail">×</button><strong>${esc(title)}</strong><p>${esc(detail)}</p><span>${esc(meta)}</span>`;
}

function renderMapOverlays() {
  const map = $("#map");
  const rect = map.getBoundingClientRect();
  if (!state.data || rect.width < 40) return;
  const overlays = [];
  if (state.map.layers.weather) {
    state.data.weather_alerts.forEach((alert) => {
      const point = mapPixel(alert.latitude, alert.longitude, rect);
      const metresPerPixel =
        (156543.03392 * Math.cos((Number(alert.latitude) * Math.PI) / 180)) /
        2 ** state.map.zoom;
      const diameter = Math.max(
        72,
        Math.min(440, (Number(alert.radius_km || 10) * 2000) / metresPerPixel),
      );
      overlays.push(
        `<button class="weather-zone ${esc(alert.event_type)}" style="left:${point.x}px;top:${point.y}px;width:${diameter}px;height:${diameter}px" type="button" data-map-kind="weather" data-map-id="${esc(alert.id)}" aria-label="${esc(alert.title)}"><span>${weatherGlyph(alert.event_type)} ${esc(titleCase(alert.event_type))}</span></button>`,
      );
    });
  }
  if (state.map.layers.potholes) {
    state.data.potholes.forEach((pothole) => {
      const point = mapPixel(pothole.latitude, pothole.longitude, rect);
      overlays.push(
        `<button class="map-marker pothole-marker" style="left:${point.x}px;top:${point.y}px" type="button" data-map-kind="pothole" data-map-id="${esc(pothole.id)}" aria-label="${esc(titleCase(pothole.severity))} pothole, ${Math.round(pothole.confidence * 100)} percent confidence"><span class="pin">!</span><span class="marker-label">${esc(titleCase(pothole.status))} pothole</span></button>`,
      );
    });
  }
  if (state.map.layers.vehicles) {
    state.data.vehicles
      .filter((vehicle) => vehicle.latitude != null)
      .forEach((vehicle) => {
        const point = mapPixel(vehicle.latitude, vehicle.longitude, rect);
        const level = vehicle.assessments?.collision?.level || "low";
        overlays.push(
          `<button class="map-marker vehicle-marker level-${esc(level)}" style="left:${point.x}px;top:${point.y}px" type="button" data-map-kind="vehicle" data-map-id="${esc(vehicle.id)}" aria-label="${esc(vehicle.vehicle_name)}, ${numberOrDash(vehicle.speed_kph, 0)} kilometres per hour"><span class="pulse-ring"></span><span class="pin" style="--heading:${Number(vehicle.heading_deg || 0)}deg">▲</span><span class="marker-label"><strong>${esc(vehicle.vehicle_name)}</strong>${numberOrDash(vehicle.speed_kph, 0)} km/h</span></button>`,
        );
      });
  }
  if (state.tracking.location) {
    const location = state.tracking.location;
    const point = mapPixel(location.latitude, location.longitude, rect);
    overlays.push(
      `<button class="map-marker user-marker" style="left:${point.x}px;top:${point.y}px" type="button" data-map-kind="user" data-map-id="current" aria-label="Your live position"><span class="accuracy-ring" style="width:${Math.max(38, Math.min(150, location.accuracy / 2))}px;height:${Math.max(38, Math.min(150, location.accuracy / 2))}px"></span><span class="pin"></span><span class="marker-label"><strong>You</strong>Live position</span></button>`,
    );
  }
  $("#map-layers").innerHTML = overlays.join("");
  renderMapSelection();
}

function renderMap() {
  renderTiles();
  renderMapOverlays();
}

function allMapPoints() {
  if (!state.data) return [];
  const points = [];
  state.data.vehicles.forEach(
    (item) =>
      item.latitude != null &&
      points.push([Number(item.latitude), Number(item.longitude)]),
  );
  state.data.potholes.forEach((item) =>
    points.push([Number(item.latitude), Number(item.longitude)]),
  );
  state.data.weather_alerts.forEach((item) =>
    points.push([Number(item.latitude), Number(item.longitude)]),
  );
  if (state.tracking.location)
    points.push([
      state.tracking.location.latitude,
      state.tracking.location.longitude,
    ]);
  return points;
}

function fitMapToData(force = false) {
  const points = allMapPoints();
  const rect = $("#map").getBoundingClientRect();
  if (!points.length || rect.width < 40) return;
  if (state.map.fitted && !force) return;
  const minLatitude = Math.min(...points.map((point) => point[0]));
  const maxLatitude = Math.max(...points.map((point) => point[0]));
  const minLongitude = Math.min(...points.map((point) => point[1]));
  const maxLongitude = Math.max(...points.map((point) => point[1]));
  state.map.latitude = (minLatitude + maxLatitude) / 2;
  state.map.longitude = (minLongitude + maxLongitude) / 2;
  for (let zoom = 17; zoom >= 3; zoom -= 1) {
    const northWest = worldPoint(maxLatitude, minLongitude, zoom);
    const southEast = worldPoint(minLatitude, maxLongitude, zoom);
    if (
      Math.abs(southEast.x - northWest.x) <= Math.max(120, rect.width - 180) &&
      Math.abs(southEast.y - northWest.y) <= Math.max(120, rect.height - 180)
    ) {
      state.map.zoom = Math.min(15, zoom);
      break;
    }
  }
  state.map.fitted = true;
  state.map.tileKey = "";
  renderMap();
}

function setMapCenter(
  latitude,
  longitude,
  zoom = Math.max(state.map.zoom, 14),
  selected = null,
) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  state.map.latitude = latitude;
  state.map.longitude = longitude;
  state.map.zoom = Math.min(19, Math.max(3, zoom));
  state.map.selected = selected;
  state.map.fitted = true;
  state.map.tileKey = "";
  renderMap();
  $("#live-map").scrollIntoView({ behavior: "smooth", block: "start" });
}

function changeZoom(delta) {
  const next = Math.max(3, Math.min(19, state.map.zoom + delta));
  if (next === state.map.zoom) return;
  state.map.zoom = next;
  state.map.tileKey = "";
  renderMap();
}

function panMap(deltaX, deltaY) {
  const center = worldPoint(
    state.map.latitude,
    state.map.longitude,
    state.map.zoom,
  );
  const coordinates = coordinatesFromWorld(
    center.x + deltaX,
    center.y + deltaY,
    state.map.zoom,
  );
  state.map.latitude = coordinates.latitude;
  state.map.longitude = coordinates.longitude;
  state.map.tileKey = "";
  renderMap();
}

function nearestWeatherAlert() {
  if (!state.data?.weather_alerts?.length) return null;
  return [...state.data.weather_alerts].sort(
    (a, b) => (a.distance_km ?? 9999) - (b.distance_km ?? 9999),
  )[0];
}

function renderTracker() {
  const content = $("#tracker-content");
  const chip = $("#tracker-state");
  const headerButton = $("#track-user");
  if (state.tracking.location) {
    const location = state.tracking.location;
    const weather = nearestWeatherAlert();
    const isLowVisibility =
      weather &&
      ["fog", "heavy_rain", "rain", "dust_storm", "snow"].includes(
        weather.event_type,
      );
    chip.className = `status-chip ${isLowVisibility ? "warning" : "live"}`;
    chip.innerHTML = `<i></i>${isLowVisibility ? "Caution" : "Tracking"}`;
    headerButton.setAttribute("aria-pressed", "true");
    headerButton.classList.add("tracking");
    headerButton.querySelector("span:last-child").textContent = "Tracking on";
    content.innerHTML = `
      <div class="tracker-live-head"><span class="tracker-position-icon"><i></i></span><div><small>Live location</small><strong>${numberOrDash(location.latitude, 4)}, ${numberOrDash(location.longitude, 4)}</strong></div></div>
      <div class="visibility-callout ${isLowVisibility ? "warning" : "safe"}">
        <span aria-hidden="true">${weather ? weatherGlyph(weather.event_type) : "✓"}</span>
        <div><small>${weather ? titleCase(weather.event_type) : "Route conditions"}</small><strong>${weather ? weather.title : "No active weather alert nearby"}</strong><p>${weather ? weather.instructions : "Live monitoring is active around your position."}</p></div>
      </div>
      <div class="tracker-meta"><span>GPS accuracy ±${Math.round(location.accuracy)} m</span>${weather?.distance_km != null ? `<span>${numberOrDash(weather.distance_km, 1)} km from alert centre</span>` : ""}</div>
      <button class="secondary-button" type="button" data-stop-tracking>Stop tracking</button>`;
    $("#map-status").textContent =
      `Following your position · accuracy ±${Math.round(location.accuracy)} m`;
    return;
  }
  chip.className = "status-chip idle";
  chip.innerHTML = "<i></i>Off";
  headerButton.setAttribute("aria-pressed", "false");
  headerButton.classList.remove("tracking");
  headerButton.querySelector("span:last-child").textContent = "Track me";
  content.innerHTML = `
    <div class="tracker-illustration" aria-hidden="true"><span></span></div>
    <h3>${state.tracking.error ? "Location unavailable" : "Track rain and fog around you"}</h3>
    <p>${esc(state.tracking.error || "Turn on location to filter live weather alerts and potholes around your route.")}</p>
    <button id="tracker-start" class="action-button" type="button">${state.tracking.error ? "Try again" : "Start live tracking"}</button>`;
  if (state.data)
    $("#map-status").textContent =
      `${state.data.vehicles.length} vehicles · ${state.data.weather_alerts.length} weather alerts · ${state.data.potholes.length} road hazards`;
}

function stopTracking() {
  if (state.tracking.watchId != null && navigator.geolocation)
    navigator.geolocation.clearWatch(state.tracking.watchId);
  state.tracking.watchId = null;
  state.tracking.location = null;
  state.tracking.error = "";
  state.map.selected = null;
  renderTracker();
  renderMap();
  loadState().catch((error) => setMessage(error.message, true));
}

function startTracking() {
  if (!navigator.geolocation) {
    state.tracking.error = "This browser does not provide location services.";
    renderTracker();
    return;
  }
  state.tracking.error = "";
  $("#tracker-state").className = "status-chip loading";
  $("#tracker-state").innerHTML = "<i></i>Locating";
  state.tracking.watchId = navigator.geolocation.watchPosition(
    (position) => {
      const firstPosition = !state.tracking.location;
      state.tracking.location = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        heading: position.coords.heading,
        speed: position.coords.speed,
      };
      state.tracking.error = "";
      if (firstPosition) {
        state.map.latitude = position.coords.latitude;
        state.map.longitude = position.coords.longitude;
        state.map.zoom = 14;
        state.map.fitted = true;
        state.map.tileKey = "";
      }
      renderTracker();
      renderMap();
      const now = Date.now();
      if (firstPosition || now - state.tracking.lastFetchAt > 5000) {
        state.tracking.lastFetchAt = now;
        loadState().catch((error) => setMessage(error.message, true));
      }
    },
    (error) => {
      state.tracking.watchId = null;
      const messages = {
        1: "Location permission was not granted. Allow it in the browser to track local rain, fog and potholes.",
        2: "Your position could not be determined. Check GPS or network location and try again.",
        3: "Location took too long to respond. Try again in an open area.",
      };
      state.tracking.error =
        messages[error.code] || "Location could not be started.";
      renderTracker();
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 3000 },
  );
}

function toggleTracking() {
  if (state.tracking.watchId != null || state.tracking.location) stopTracking();
  else startTracking();
}

function render(data) {
  state.data = data;
  renderMetrics(data);
  renderWeather(data.weather_alerts);
  renderPriority(data);
  renderVehicles(data.vehicles);
  renderPotholes(data.potholes);
  renderEvents(data.recent_events);
  renderTracker();
  if (!state.map.fitted) fitMapToData();
  else renderMap();
  $("#last-updated").textContent = `Updated ${clockTime(data.generated_at)}`;
  const viewer = $("#viewer-id").value;
  $("#privacy-mode").textContent = viewer
    ? `Authorized owner · ${viewer.replace("usr_", "")}`
    : "Public privacy view";
  $("#privacy-mode").classList.toggle("owner", Boolean(viewer));
}

async function loadState() {
  const headers = {};
  const viewer = $("#viewer-id").value;
  if (viewer) {
    headers.Authorization = `Bearer ${$("#api-key").value}`;
    headers["X-Viewer-User-Id"] = viewer;
  }
  const query = new URLSearchParams();
  if (state.tracking.location) {
    query.set("lat", state.tracking.location.latitude);
    query.set("lon", state.tracking.location.longitude);
    query.set("radius_km", "25");
  }
  const response = await fetch(`/api/state${query.size ? `?${query}` : ""}`, {
    headers,
  });
  if (!response.ok)
    throw new Error(`Live state request failed (${response.status})`);
  render(await response.json());
}

async function post(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${$("#api-key").value}`,
    },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.message || `Request failed (${response.status})`);
  return result;
}

function setMessage(message, error = false) {
  $("#control-message").textContent = message;
  $("#control-message").classList.toggle("error", error);
}

function showToast(title, message, tone = "blue") {
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.innerHTML = `<span aria-hidden="true">${tone === "red" ? "!" : tone === "yellow" ? "☂" : "●"}</span><div><strong>${esc(title)}</strong><p>${esc(message)}</p></div>`;
  $("#toast-region").append(toast);
  window.setTimeout(() => {
    toast.classList.add("leaving");
    window.setTimeout(() => toast.remove(), 250);
  }, 4500);
}

function eventNotification(name, payload) {
  const now = Date.now();
  if (now - (state.lastToast[name] || 0) < 8000) return;
  const detail = payload?.data || {};
  if (name === "weather.alert")
    showToast(
      "New weather alert",
      detail.title || "Conditions changed nearby",
      "yellow",
    );
  else if (name === "pothole.detected")
    showToast(
      "Road hazard detected",
      "A possible pothole was added to the live map.",
      "yellow",
    );
  else if (
    name === "safety.collision" &&
    ["high", "critical"].includes(detail.level)
  )
    showToast("Collision risk", eventAction(detail), "red");
  else if (
    name === "safety.visibility" &&
    ["high", "critical"].includes(detail.level)
  )
    showToast("Low visibility", eventAction(detail), "red");
  else if (name === "safety.traffic_signal")
    showToast("Traffic-light braking", eventAction(detail), "red");
  else return;
  state.lastToast[name] = now;
}

function connectEvents() {
  if (state.stream) state.stream.close();
  const connection = $("#connection");
  const stream = new EventSource("/api/events");
  state.stream = stream;
  stream.onopen = () => {
    connection.className = "connection live";
    connection.innerHTML = "<i></i><span>Live</span>";
  };
  stream.onerror = () => {
    connection.className = "connection offline";
    connection.innerHTML = "<i></i><span>Reconnecting</span>";
  };
  [
    "telemetry.updated",
    "weather.alert",
    "pothole.detected",
    "pothole.updated",
    "safety.collision",
    "safety.visibility",
    "safety.traffic_signal",
  ].forEach((name) => {
    stream.addEventListener(name, (event) => {
      try {
        eventNotification(name, JSON.parse(event.data));
      } catch (_) {
        /* Ignore malformed optional notification data. */
      }
      loadState().catch(() => {});
    });
  });
}

function applyTheme(theme) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = selected;
  localStorage.setItem("mausam-theme", selected);
  const button = $("#theme-toggle");
  button.setAttribute(
    "aria-label",
    selected === "light" ? "Switch to dark theme" : "Switch to light theme",
  );
  $("meta[name='theme-color']").setAttribute(
    "content",
    selected === "light" ? "#ffffff" : "#111318",
  );
}

function installMapInteractions() {
  const map = $("#map");
  map.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    const center = worldPoint(
      state.map.latitude,
      state.map.longitude,
      state.map.zoom,
    );
    state.map.drag = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      center,
    };
    map.setPointerCapture(event.pointerId);
    map.classList.add("dragging");
  });
  map.addEventListener("pointermove", (event) => {
    if (!state.map.drag || state.map.drag.pointerId !== event.pointerId) return;
    const x = state.map.drag.center.x - (event.clientX - state.map.drag.x);
    const y = state.map.drag.center.y - (event.clientY - state.map.drag.y);
    const coordinates = coordinatesFromWorld(x, y, state.map.zoom);
    state.map.latitude = coordinates.latitude;
    state.map.longitude = coordinates.longitude;
    renderMap();
  });
  const endDrag = (event) => {
    if (!state.map.drag || state.map.drag.pointerId !== event.pointerId) return;
    state.map.drag = null;
    map.classList.remove("dragging");
  };
  map.addEventListener("pointerup", endDrag);
  map.addEventListener("pointercancel", endDrag);
  map.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      changeZoom(event.deltaY < 0 ? 1 : -1);
    },
    { passive: false },
  );
  map.addEventListener("dblclick", (event) => {
    if (!event.target.closest("button")) changeZoom(1);
  });
  map.addEventListener("keydown", (event) => {
    const keyActions = {
      "+": () => changeZoom(1),
      "=": () => changeZoom(1),
      "-": () => changeZoom(-1),
      ArrowUp: () => panMap(0, -80),
      ArrowDown: () => panMap(0, 80),
      ArrowLeft: () => panMap(-80, 0),
      ArrowRight: () => panMap(80, 0),
    };
    if (keyActions[event.key]) {
      event.preventDefault();
      keyActions[event.key]();
    }
  });
  $("#map-layers").addEventListener("click", (event) => {
    const target = event.target.closest("[data-map-kind]");
    if (!target) return;
    state.map.selected = {
      kind: target.dataset.mapKind,
      id: target.dataset.mapId,
    };
    renderMapSelection();
  });
  $("#map-selection").addEventListener("click", (event) => {
    if (event.target.closest("#close-map-selection")) {
      state.map.selected = null;
      renderMapSelection();
    }
  });
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      state.map.tileKey = "";
      renderMap();
    }).observe(map);
  }
}

$("#refresh").addEventListener("click", () =>
  loadState()
    .then(() => setMessage("Live view refreshed."))
    .catch((error) => setMessage(error.message, true)),
);
$("#viewer-id").addEventListener("change", () =>
  loadState().catch((error) => setMessage(error.message, true)),
);
$("#step").addEventListener("click", () =>
  post("/api/demo/step")
    .then(loadState)
    .then(() => setMessage("One live demo update generated."))
    .catch((error) => setMessage(error.message, true)),
);
$("#reset").addEventListener("click", () =>
  post("/api/demo/seed", { reset: true })
    .then(() => {
      state.map.fitted = false;
      return loadState();
    })
    .then(() => setMessage("Demo data reset and streaming."))
    .catch((error) => setMessage(error.message, true)),
);
$("#track-user").addEventListener("click", toggleTracking);
$("#tracker-card").addEventListener("click", (event) => {
  if (event.target.closest("#tracker-start")) startTracking();
  if (event.target.closest("[data-stop-tracking]")) stopTracking();
});
$("#theme-toggle").addEventListener("click", () =>
  applyTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark",
  ),
);
$("#zoom-in").addEventListener("click", () => changeZoom(1));
$("#zoom-out").addEventListener("click", () => changeZoom(-1));
$("#fit-map").addEventListener("click", () => {
  state.map.fitted = false;
  fitMapToData(true);
});

$$("[data-map-mode]").forEach((button) =>
  button.addEventListener("click", () => {
    state.map.mode = button.dataset.mapMode;
    state.map.tileKey = "";
    $$("[data-map-mode]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderMap();
  }),
);

$$("[data-layer]").forEach((button) =>
  button.addEventListener("click", () => {
    const layer = button.dataset.layer;
    state.map.layers[layer] = !state.map.layers[layer];
    button.classList.toggle("active", state.map.layers[layer]);
    button.setAttribute("aria-pressed", String(state.map.layers[layer]));
    renderMapOverlays();
  }),
);

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-focus-lat][data-focus-lon]");
  if (!target) return;
  const selected = target.dataset.selectKind
    ? { kind: target.dataset.selectKind, id: target.dataset.selectId }
    : null;
  setMapCenter(
    Number(target.dataset.focusLat),
    Number(target.dataset.focusLon),
    15,
    selected,
  );
});

applyTheme(localStorage.getItem("mausam-theme") || "light");
installMapInteractions();
setInterval(() => {
  $("#clock").textContent = new Date().toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}, 1000);
setInterval(() => loadState().catch(() => {}), 10000);
connectEvents();
loadState().catch((error) => setMessage(error.message, true));
