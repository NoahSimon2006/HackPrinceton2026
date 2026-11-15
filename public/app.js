const $ = (id) => document.getElementById(id);
const HOME = [34.0522, -118.2437];
const HOME_ZOOM = 13;
const MIN_ZOOM = 10;
const MIN_PROPERTY_ZOOM = 15;
const map = L.map("map", { minZoom: MIN_ZOOM, maxZoom: 20, zoomSnap: 0, zoomDelta: .5,
  preferCanvas: true,
  zoomControl: false, scrollWheelZoom: false, inertia: false }).setView(HOME, HOME_ZOOM);
const mapDrag = map.dragging._draggable;
map.dragging.disable();
L.control.zoom({ position: "topright" }).addTo(map);
const imagery = L.tileLayer("/api/tiles/{z}/{x}/{y}.jpg", {
  minZoom: 10, maxNativeZoom: 20, maxZoom: 20, keepBuffer: 2,
  attribution: 'Imagery © <a href="https://vexceldata.com/">Vexcel Imaging</a>'
}).addTo(map);
map.createPane("labels");
map.getPane("labels").style.zIndex = 450;
map.getPane("labels").style.pointerEvents = "none";
const labels = L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
  pane: "labels", maxNativeZoom: 19, maxZoom: 20,
  attribution: 'Labels © Esri, HERE, Garmin, © OpenStreetMap contributors'
});
const propertyLayer = L.layerGroup().addTo(map);
map.createPane("emissions");
map.getPane("emissions").style.zIndex = 430;
const emissionRenderer = L.canvas({ pane: "emissions", padding: .5 });
const emissionsLayer = L.layerGroup();
let emissionsData = null;
let emissionsRequest = null;
let emissionsError = null;
let emissionLines = new Map();
let selectedRoad = null;
let selectedLine = null;
let planningMode = "street";
// The legacy city layer contains assumed class-default volumes. Only comparisons
// backed by a selected official turning sheet are enabled in this checkpoint.
function emissionsActive() { return planningMode === "street" && !$("emissions-layer").disabled; }
let activePeriod = "midday";
let activeMetric = "co2";
let colorThresholds = [];
let coverage = null;
let footprints = [];
let lastAllowed = map.getCenter();
let correcting = false;
let markerById = new Map();
let selectedId = null;
let focusPending = false;
let searchTimer = null;
let propertyRequest = null;
let propertyGeneration = 0;
let searchRequest = null;
let searchGeneration = 0;
let tileFailures = 0;

function setStatus(title, detail, error = false) {
  $("status-title").textContent = title;
  $("status-detail").textContent = detail;
  $("status-dot").classList.toggle("error", error);
}

function setImageryStatus(detail) {
  const note = coverage?.excludedFeatures ? " Some source coverage outlines were invalid and excluded." : "";
  setStatus("Imagery ready", detail + note);
}

function insideRing(point, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[1] > point[1]) !== (b[1] > point[1]) &&
        point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

function insidePolygon(point, rings) {
  return rings.length > 0 && insideRing(point, rings[0]) &&
    !rings.slice(1).some((hole) => insideRing(point, hole));
}

function insideCoverage(latlng) {
  if (!coverage) return false;
  const [west, south, east, north] = coverage.bounds;
  if (latlng.lng < west || latlng.lng > east || latlng.lat < south || latlng.lat > north) return false;
  const point = [latlng.lng, latlng.lat];
  return footprints.some(({ rings, bounds }) => {
    const [west, south, east, north] = bounds;
    return point[0] >= west && point[0] <= east && point[1] >= south && point[1] <= north &&
      insidePolygon(point, rings);
  });
}

function moveInsideCoverage(center, delta, allowed) {
  const distance = Math.hypot(delta.x, delta.y);
  if (distance === 0) return center;
  const steps = Math.ceil(distance / 8);
  for (let step = 1; step <= steps; step++) {
    let blocked = step / steps;
    const target = center.add(delta.multiplyBy(blocked));
    if (allowed(target)) continue;
    let safe = (step - 1) / steps;
    while ((blocked - safe) * distance > 0.25) {
      const midpoint = (safe + blocked) / 2;
      if (allowed(center.add(delta.multiplyBy(midpoint)))) safe = midpoint;
      else blocked = midpoint;
    }
    return center.add(delta.multiplyBy(safe));
  }
  return center.add(delta);
}

function installSmoothWheelZoom() {
  // Leaflet 1.9.4's wheel handler batches input into discrete zoom operations.
  // Use its continuous pinch movement path so tiles and the emissions canvas
  // share the same transform; commit zoomend/moveend once the gesture settles.
  const container = map.getContainer();
  let frame = null;
  let active = false;
  let internalMove = false;
  let targetZoom, anchor, pointer, previousTime, lastInput;
  const clamp = (zoom) => Math.min(map.getMaxZoom(), Math.max(map.getMinZoom(), zoom));

  function finish() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    if (!active) return;
    active = false;
    map._moveEnd(true);
  }

  function animate(now) {
    frame = null;
    if (!active) return;
    const elapsed = Math.min(64, Math.max(1, now - previousTime));
    previousTime = now;
    targetZoom = clamp(targetZoom);
    const current = map.getZoom();
    const remaining = targetZoom - current;
    const zoom = Math.abs(remaining) < .0001 ? targetZoom :
      current + remaining * (1 - Math.exp(-elapsed / 65));
    const offset = pointer.subtract(map.getSize().divideBy(2));
    let center = map.project(anchor, zoom).subtract(offset);
    if (coverage) {
      const allowed = (position) => insideCoverage(map.unproject(position, zoom));
      if (!allowed(center)) {
        const previous = map.project(map.getCenter(), zoom);
        if (!allowed(previous)) {
          // Stop at the imagery boundary without snapping back across the city.
          targetZoom = current;
          finish();
          return;
        }
        center = moveInsideCoverage(previous, center.subtract(previous), allowed);
      }
    }
    internalMove = true;
    map._move(map.unproject(center, zoom), zoom, { pinch: true, round: false });
    internalMove = false;
    if (zoom === targetZoom && now - lastInput > 100) finish();
    else frame = requestAnimationFrame(animate);
  }

  container.addEventListener("wheel", (event) => {
    if (event.target.closest(".leaflet-control, .leaflet-popup")) return;
    event.preventDefault();
    if (!event.deltaY || map._animatingZoom) return;
    const now = performance.now();
    if (!active) {
      map.stop();
      targetZoom = map.getZoom();
      previousTime = now;
      active = true;
      internalMove = true;
      map._moveStart(true, false);
      internalMove = false;
    }
    pointer = map.mouseEventToContainerPoint(event);
    anchor = map.containerPointToLatLng(pointer);
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? map.getSize().y : 1;
    // Preserve small trackpad deltas; cap large mouse-wheel ticks to avoid jumps.
    const pixels = Math.max(-120, Math.min(120, event.deltaY * unit * (event.ctrlKey ? 3 : 1)));
    targetZoom = clamp(targetZoom - pixels / 300);
    lastInput = now;
    if (frame === null) frame = requestAnimationFrame(animate);
  }, { passive: false });
  container.addEventListener("pointerdown", finish);
  container.addEventListener("keydown", finish);
  window.addEventListener("blur", finish);
  map.on("movestart zoomstart", () => { if (!internalMove) finish(); });
}

installSmoothWheelZoom();

let previousDragPosition;
map.on("dragstart", () => {
  previousDragPosition = L.DomUtil.getPosition(map.getPane("mapPane"));
});

// Leaflet 1.9.4 lets predrag listeners adjust the pane position before it is drawn.
mapDrag.on("predrag", () => {
  const current = L.DomUtil.getPosition(map.getPane("mapPane"));
  const delta = previousDragPosition.subtract(mapDrag._newPos);
  previousDragPosition = mapDrag._newPos;
  const zoom = map.getZoom();
  const center = map.project(map.getCenter(), zoom);
  const allowed = (position) => insideCoverage(map.unproject(position, zoom));
  // Short steps let the slide follow changes in the boundary during a fast gesture.
  const steps = Math.max(1, Math.ceil(Math.hypot(delta.x, delta.y) / 12));
  const motion = delta.divideBy(steps);
  let position = center;
  for (let step = 0; step < steps; step++) {
    const target = position.add(motion);
    const direct = moveInsideCoverage(position, motion, allowed);
    position = direct;
    if (direct.equals(target)) continue;

    const remaining = target.subtract(direct);
    let best = direct;
    let nearest = best.distanceTo(target);
    // Try nearby directions on both sides of the blocked motion and keep
    // the one that gets closest to the pointer's intended destination.
    for (const angle of [15, -15, 30, -30, 45, -45, 60, -60, 75, -75]) {
      const radians = angle * Math.PI / 180;
      const cos = Math.cos(radians);
      const sin = Math.sin(radians);
      const slide = L.point(remaining.x * cos - remaining.y * sin,
        remaining.x * sin + remaining.y * cos).multiplyBy(cos);
      const candidate = moveInsideCoverage(direct, slide, allowed);
      const distance = candidate.distanceTo(target);
      if (distance < nearest) {
        best = candidate;
        nearest = distance;
      }
    }
    position = best;
  }
  mapDrag._newPos = current.add(center.subtract(position));
});

async function json(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function updateMapInfo() {
  const center = map.getCenter();
  $("coordinates").textContent = `${center.lat.toFixed(4)}, ${center.lng.toFixed(4)}`;
  $("zoom").textContent = map.getZoom().toFixed(1);
}

async function loadCoverage() {
  try {
    coverage = await json("/api/coverage");
    for (const { geometry } of coverage.features) {
      const polygons = geometry.type === "Polygon" ? [geometry.coordinates] :
        geometry.type === "MultiPolygon" ? geometry.coordinates : [];
      for (const rings of polygons) {
        const bounds = [Infinity, Infinity, -Infinity, -Infinity];
        for (const [lng, lat] of rings[0] ?? []) {
          bounds[0] = Math.min(bounds[0], lng);
          bounds[1] = Math.min(bounds[1], lat);
          bounds[2] = Math.max(bounds[2], lng);
          bounds[3] = Math.max(bounds[3], lat);
        }
        footprints.push({ rings, bounds });
      }
    }
    if (!insideCoverage(L.latLng(HOME))) {
      setStatus("Coverage unavailable here", "The opening point is outside Vexcel coverage.", true);
      return;
    }
    const zoom = map.getZoom();
    if (!insideCoverage(map.getCenter())) {
      map.setView(HOME, zoom, { animate: false });
    }
    lastAllowed = map.getCenter();
    map.dragging.enable();
    setImageryStatus("Pan is limited to Vexcel-covered Los Angeles.");
  } catch (error) {
    setStatus("Coverage check failed", error.message, true);
  }
}

function popupContent(property) {
  const box = document.createElement("div");
  box.className = "property-popup";
  for (const [tag, value] of [["strong", property.name], ["span", property.address || "Address unavailable"], ["span", property.type]]) {
    const node = document.createElement(tag);
    node.textContent = value;
    box.append(node);
  }
  return box;
}

function addMarker(property) {
  const icon = L.divIcon({ className: `property-marker${property.id === selectedId ? " selected" : ""}`,
    iconSize: [13, 13], iconAnchor: [6, 6] });
  const marker = L.marker([property.lat, property.lon], { icon, title: property.name });
  marker.bindPopup(popupContent(property));
  marker.on("click", () => map.fire("plannerproperty", { property }));
  marker.addTo(propertyLayer);
  markerById.set(property.id, marker);
  return marker;
}

async function updateProperties() {
  const generation = ++propertyGeneration;
  const enabled = $("properties").checked;
  $("layer-note").hidden = !enabled || map.getZoom() >= MIN_PROPERTY_ZOOM;
  propertyLayer.clearLayers();
  markerById = new Map();
  if (propertyRequest) propertyRequest.abort();
  if (!enabled || map.getZoom() < MIN_PROPERTY_ZOOM) return;
  const bounds = map.getBounds();
  const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map((n) => n.toFixed(6)).join(",");
  propertyRequest = new AbortController();
  try {
    const data = await json(`/api/properties?bbox=${bbox}`, { signal: propertyRequest.signal });
    if (generation !== propertyGeneration) return;
    for (const property of data.properties) addMarker(property);
    if (focusPending && markerById.has(selectedId)) {
      markerById.get(selectedId).openPopup();
      focusPending = false;
    }
    setImageryStatus(`${data.total} CoStar properties in view · coverage limited to Vexcel imagery.`);
  } catch (error) {
    if (generation === propertyGeneration && error.name !== "AbortError") setStatus("Property layer unavailable", error.message, true);
  }
}

function selectProperty(property) {
  const location = [property.lat, property.lon];
  const zoom = Math.max(17, map.getMinZoom());
  if (coverage && !insideCoverage(L.latLng(location))) {
    setStatus("Property outside map bounds", "This property's center is outside the available Vexcel coverage.", true);
    return;
  }
  clearTimeout(searchTimer); ++searchGeneration; searchRequest?.abort();
  selectedId = property.id;
  focusPending = true;
  $("properties").checked = true;
  $("results").hidden = true;
  $("search").value = property.name;
  map.setView(location, zoom);
  map.fire("plannerproperty", { property, searched: true });
  updateProperties();
}

async function search() {
  const generation = ++searchGeneration;
  searchRequest?.abort(); searchRequest = new AbortController();
  const q = $("search").value.trim();
  const results = $("results");
  if (q.length < 2) { results.hidden = true; results.replaceChildren(); return; }
  try {
    const data = await json(`/api/search?q=${encodeURIComponent(q)}`, {signal:searchRequest.signal});
    if (generation !== searchGeneration || $("search").value.trim() !== q) return;
    results.replaceChildren();
    if (!data.results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-results";
      empty.textContent = "No matching CoStar properties.";
      results.append(empty);
    }
    for (const property of data.results) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result";
      button.setAttribute("role", "option");
      const name = document.createElement("strong"); name.textContent = property.name;
      const address = document.createElement("small"); address.textContent = property.address || property.type;
      button.append(name, address);
      button.addEventListener("click", () => selectProperty(property));
      results.append(button);
    }
    results.hidden = false;
  } catch (error) { if (generation === searchGeneration && error.name !== "AbortError") setStatus("Search unavailable", error.message, true); }
}

map.on("moveend", () => {
  if (correcting) return;
  const zoom = map.getZoom();
  if (coverage) {
    const allowed = (center) => insideCoverage(map.unproject(center, zoom));
    const requested = map.project(map.getCenter(), zoom);
    if (!allowed(requested)) {
      const previous = map.project(lastAllowed, zoom);
      const start = allowed(previous) ? previous : map.project(HOME, zoom);
      const target = moveInsideCoverage(start, requested.subtract(start), allowed);
      correcting = true;
      map.setView(map.unproject(target, zoom), zoom, { animate: false });
      correcting = false;
    }
  }
  lastAllowed = map.getCenter();
  updateMapInfo();
  updateProperties();
});
map.on("zoomend", updateMapInfo);
imagery.on("tileerror", () => {
  tileFailures++;
  if (tileFailures === 1) setStatus("Some imagery unavailable", "A Vexcel tile did not load. Try another zoom or check access.", true);
});
imagery.on("tileload", () => { if (tileFailures) tileFailures = 0; });
$("labels").addEventListener("change", (event) => event.target.checked ? labels.addTo(map) : labels.remove());
$("properties").addEventListener("change", updateProperties);
$("emissions-layer").addEventListener("change", () => {
  if (emissionsActive() && $("emissions-layer").checked) loadEmissions();
  syncEmissionsVisibility();
});
$("retry-emissions").addEventListener("click", loadEmissions);
$("search").addEventListener("input", () => {
  ++searchGeneration; searchRequest?.abort(); $("results").hidden = true;
  clearTimeout(searchTimer); searchTimer = setTimeout(search, 220);
});
$("reset").addEventListener("click", () => emissionsActive() ?
  map.fitBounds([[34.034, -118.268], [34.070, -118.219]],
    { padding: [35, 35], maxZoom: 14 }) : map.setView(HOME, HOME_ZOOM));

const ROAD_COLORS = ["#7bdec0", "#b8d878", "#f5bb5d", "#ed7757", "#bd354e"];
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
function roadValue(road) { return road.periods[activePeriod][activeMetric === "co2" ? "co2_kg_h" : "nox_g_h"]; }
function quantile(values, fraction) {
  return values[Math.min(values.length - 1, Math.floor((values.length - 1) * fraction))] || 0;
}
function roadColor(value) {
  for (let index = 0; index < colorThresholds.length; index++) {
    if (value <= colorThresholds[index]) return ROAD_COLORS[index];
  }
  return ROAD_COLORS.at(-1);
}
function updateInspector() {
  if (!selectedRoad || !emissionsActive()) { $("road-inspector").hidden = true; return; }
  const road = selectedRoad, values = road.periods[activePeriod];
  $("road-inspector").hidden = false;
  $("road-name").textContent = road.name;
  const basisLabel = { counted: "own LADOT count", same_street: "from counts on this street", class_median: "typical counted volume for this road class", assumed: "assumed volume", historical_count: "historical count anchor", class_assumption: "assumed traffic volume" };
  $("road-basis").textContent = `${road.class.replaceAll("_", " ")} · ${integer.format(road.length_m)} m segment · ${basisLabel[road.basis] ?? road.basis}`;
  $("road-co2").textContent = values.co2_kg_h.toFixed(1);
  $("road-nox").textContent = values.nox_g_h.toFixed(1);
  $("road-vehicles").textContent = integer.format(values.vehicles_h);
  $("road-speed").textContent = values.speed_kmh.toFixed(1);
  const share = emissionsData.periods?.[activePeriod]?.share_of_daily;
  const hourly = share ? ` Hourly volume is ${(share * 100).toFixed(2)}% of daily traffic, as observed on official LADOT 24-hour count sheets.` : "";
  const detail = road.basis_detail || {};
  $("road-count-detail").textContent = road.count ?
    `LADOT automated 24-hour count at ${road.count.street} / ${road.count.cross}, ${road.count.date}: ${integer.format(road.count.daily)} vehicles per day in this direction.${hourly}` :
    road.basis === "same_street" ? `No count on this segment. ${integer.format(road.daily_vehicles)} vehicles per day estimated from ${detail.sources} LADOT count${detail.sources === 1 ? "" : "s"} on the same street and direction (nearest ${integer.format(detail.nearest_m)} m away; ${detail.dates?.join(", ")}).${hourly}` :
    road.basis === "class_median" ? `No count on this street. ${integer.format(road.daily_vehicles)} vehicles per day is the median of ${detail.counted_roads} counted downtown roads of this class.${hourly}` :
    `No counted road of this class exists in the pilot; ${integer.format(road.daily_vehicles ?? 0)} vehicles per day is an assumed default.${hourly}`;
}
function selectRoad(road) {
  if (selectedLine) selectedLine.setStyle({ color: roadColor(roadValue(selectedRoad)), weight: 3.4, opacity: .9 });
  selectedRoad = road;
  selectedLine = emissionLines.get(road.id);
  selectedLine?.setStyle({ color: "#fff7d7", weight: 7, opacity: 1 });
  selectedLine?.bringToFront();
  updateInspector();
}
function renderEmissions() {
  if (!emissionsData) return;
  const values = emissionsData.roads.map(roadValue).sort((a, b) => a - b);
  colorThresholds = [.2, .4, .6, .8].map(q => quantile(values, q));
  for (const road of emissionsData.roads) {
    const line = emissionLines.get(road.id);
    line.setStyle({ color: road === selectedRoad ? "#fff7d7" : roadColor(roadValue(road)),
      weight: road === selectedRoad ? 7 : 3.4, opacity: road === selectedRoad ? 1 : .9 });
  }
  const sum = emissionsData.summary[activePeriod];
  $("pilot-total").textContent = integer.format(activeMetric === "co2" ? sum.co2_kg_h : sum.nox_g_h);
  $("pilot-unit").textContent = activeMetric === "co2" ? "kg CO₂ / hour" : "g NOₓ / hour";
  $("pilot-secondary").textContent = activeMetric === "co2" ? `${integer.format(sum.nox_g_h)} g NOₓ / h` : `${integer.format(sum.co2_kg_h)} kg CO₂ / h`;
  $("pilot-count").textContent = `${integer.format(emissionsData.quality.historical_anchor_edges)} counted segments`;
  $("legend-unit").textContent = activeMetric === "co2" ? "CO₂ · kg / h" : "NOₓ · g / h";
  $("legend-low").textContent = `${quantile(values, .1).toFixed(1)}`;
  $("legend-high").textContent = `${quantile(values, .9).toFixed(1)}+`;
  updateInspector();
}
function syncEmissionsVisibility() {
  const enabled = emissionsActive() && $("emissions-layer").checked;
  const ready = enabled && Boolean(emissionsData);
  if (ready) emissionsLayer.addTo(map);
  else emissionsLayer.remove();
  $("emissions-legend").hidden = !ready;
  $("emissions-notice").hidden = !enabled || Boolean(emissionsData);
  $("emissions-message").textContent = emissionsError || "Loading road emissions…";
  $("retry-emissions").hidden = !emissionsError;
  if (!ready) $("road-inspector").hidden = true;
}
function loadEmissions() {
  // Archived class-assumption traffic is not an approved real-data baseline.
  if ($("emissions-layer").disabled) return;
  if (emissionsData) {
    renderEmissions();
    syncEmissionsVisibility();
    return;
  }
  if (emissionsRequest) return emissionsRequest;
  emissionsError = null;
  syncEmissionsVisibility();
  emissionsRequest = (async () => {
  try {
    const response = await fetch("/api/emissions", { cache: "no-store" });
    if (response.status === 404) {
      throw new Error("This map server needs a restart to load road emissions. Restart server.py, then select Retry.");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Road emissions could not be loaded. Please retry.");
    emissionsData = data;
    for (const road of emissionsData.roads) {
      const line = L.polyline(road.coordinates.map(([lon, lat]) => [lat, lon]), {
        pane: "emissions", renderer: emissionRenderer, color: ROAD_COLORS[0], weight: 3.4,
        opacity: .9, lineCap: "round", lineJoin: "round", interactive: true
      });
      line.on("click", () => selectRoad(road));
      line.bindTooltip(road.name, { sticky: true, direction: "top", opacity: .9 });
      line.addTo(emissionsLayer);
      emissionLines.set(road.id, line);
    }
    $("method-text").textContent = [emissionsData.method.headline, emissionsData.method.traffic,
      emissionsData.method.volume, emissionsData.method.emissions, emissionsData.method.signal,
      emissionsData.method.uncertainty].join(" ");
    for (const source of emissionsData.sources) {
      const link = document.createElement("a");
      link.href = source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = `↗ ${source.label}`;
      $("source-links").append(link);
    }
    renderEmissions();
    if (emissionsActive()) setStatus("Emissions pilot ready", `${integer.format(emissionsData.quality.road_edges)} road segments · ${integer.format(emissionsData.quality.historical_anchor_edges)} with their own LADOT count.`);
  } catch (error) {
    emissionsData = null;
    emissionsLayer.clearLayers();
    emissionLines.clear();
    $("source-links").replaceChildren();
    emissionsError = error.message;
    if (emissionsActive()) setStatus("Emissions pilot unavailable", emissionsError, true);
  } finally {
    emissionsRequest = null;
    syncEmissionsVisibility();
  }
  })();
  return emissionsRequest;
}
function setPeriod(period) {
  activePeriod = period;
  for (const key of ["midday", "pm_peak"]) {
    const button = $(`period-${key}`);
    button.classList.toggle("selected", key === period);
    button.setAttribute("aria-pressed", String(key === period));
  }
  renderEmissions();
}
function setMetric(metric) {
  activeMetric = metric;
  for (const key of ["co2", "nox"]) {
    const button = $(`metric-${key}`);
    button.classList.toggle("selected", key === metric);
    button.setAttribute("aria-pressed", String(key === metric));
  }
  renderEmissions();
}
for (const period of ["midday", "pm_peak"]) $(`period-${period}`).addEventListener("click", () => setPeriod(period));
for (const metric of ["co2", "nox"]) $(`metric-${metric}`).addEventListener("click", () => setMetric(metric));
$("close-inspector").addEventListener("click", () => { selectedRoad = null; selectedLine = null; $("road-inspector").hidden = true; renderEmissions(); });

function selectPlanningWorkspace(mode, zoom = false) {
  planningMode = mode === "water" ? "water" : "street";
  const water = planningMode === "water";
  for (const name of ["street", "water"]) $(`workspace-${name}`).setAttribute("aria-pressed", String(name === planningMode));
  for (const id of ["planner", "planner-title", "site-intro"]) $(id).hidden = false;
  $("planner-title").textContent = water ? "Make room for water." : "Better streets start here.";
  $("site-intro").textContent = water ? "Find promising places to manage stormwater, then develop a site concept." : "Find street improvements worth investigating, then develop and evaluate a concept.";
  $("planner-controls").hidden = true;
  $("emissions-layer-row").hidden = water;
  $("map-workspace").classList.toggle("water-mode", water);
  $("brand-caption").textContent = "Planning workspace · Los Angeles";
  $("footer-caption").textContent = "Vexcel × CoStar · sourced site evidence";
  $("map-title").textContent = water ? "Watershed & stormwater" : "Traffic & emissions";
  $("map-eyebrow").textContent = "LOS ANGELES · SITE PLANNING";
  $("map-badge").textContent = water ? "TERRAIN · RAINFALL · DRAINAGE" : "CURRENT SPEED · SLOW APPROACHES";
  $("reset").innerHTML = water ? "↗ &nbsp; Back to Los Angeles" : "↗ &nbsp; Back to pilot";
  if (!water && $("emissions-layer").checked) loadEmissions();
  syncEmissionsVisibility();
  document.querySelector(".sidebar-body").scrollTop = 0;
  map.fire("plannerworkspace", { mode: planningMode, visible: true });
  if (zoom && !water) map.fitBounds([[34.034, -118.268], [34.070, -118.219]], { padding: [35, 35], maxZoom: 14 });
  setTimeout(() => map.invalidateSize(), 0);
}
for (const mode of ["street", "water"]) {
  $(`workspace-${mode}`).addEventListener("click", () => {
    window.location.hash = mode === "water" ? "stormwater" : "urban-planners";
  });
}
window.addEventListener("hashchange", () => selectPlanningWorkspace(window.location.hash === "#stormwater" ? "water" : "street"));
document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-block")) {
    clearTimeout(searchTimer); ++searchGeneration; searchRequest?.abort();
    $("results").hidden = true;
  }
});
new ResizeObserver(() => {
  map.invalidateSize({ pan: true });
}).observe($("map"));
updateMapInfo();
loadCoverage();
// Keep legacy planner links and independent Stormwater entry.
selectPlanningWorkspace(window.location.hash === "#stormwater" ? "water" : "street", true);
