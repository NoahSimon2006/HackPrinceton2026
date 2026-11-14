const $ = (id) => document.getElementById(id);
const HOME = [34.0522, -118.2437];
const HOME_ZOOM = 13;
const MIN_ZOOM = 10;
const ZOOM_STEP = .125;
const MIN_PROPERTY_ZOOM = 15;
const map = L.map("map", { minZoom: MIN_ZOOM, maxZoom: 20, zoomSnap: ZOOM_STEP, zoomDelta: .5,
  zoomControl: false, scrollWheelZoom: true, wheelPxPerZoomLevel: 120, inertia: false }).setView(HOME, HOME_ZOOM);
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
let coverage = null;
let footprints = [];
let lastAllowed = map.getCenter();
let correcting = false;
let markerById = new Map();
let selectedId = null;
let focusPending = false;
let searchTimer = null;
let propertyRequest = null;
let tileFailures = 0;

function setStatus(title, detail, error = false) {
  $("status-title").textContent = title;
  $("status-detail").textContent = detail;
  $("status-dot").classList.toggle("error", error);
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

function viewportSamples() {
  const half = map.getSize().divideBy(2);
  const samples = [];
  for (const y of [0, -.5, .5, -1, 1]) {
    for (const x of [0, -.5, .5, -1, 1]) {
      samples.push(L.point(x * half.x, y * half.y));
    }
  }
  return samples;
}

function insideImageryView(latlng) {
  // The Vexcel JPEGs have a no-data wedge northeast of LA inside the
  // collection footprints. Follow a conservative curve below that wedge.
  const eastward = Math.max(0, (latlng.lng + 118.38) / .28);
  const northLimit = 34.29 - .12 * eastward ** 2;
  return latlng.lat <= northLimit && insideCoverage(latlng);
}

function coversView(center, zoom, samples) {
  return samples.every((offset) => insideImageryView(map.unproject(center.add(offset), zoom)));
}

function updateMinimumZoom() {
  const samples = viewportSamples();
  let zoom = MIN_ZOOM;
  while (zoom < map.getMaxZoom() && !coversView(map.project(HOME, zoom), zoom, samples)) {
    zoom += ZOOM_STEP;
  }
  map.setMinZoom(zoom);
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
  const samples = viewportSamples();
  const allowed = (position) => coversView(position, zoom, samples);
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
    updateMinimumZoom();
    const zoom = map.getZoom();
    if (!coversView(map.project(map.getCenter(), zoom), zoom, viewportSamples())) {
      map.setView(HOME, zoom, { animate: false });
    }
    lastAllowed = map.getCenter();
    map.dragging.enable();
    setStatus("Imagery ready", "Pan is limited to Vexcel-covered Los Angeles.");
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
    for (const property of data.properties) addMarker(property);
    if (focusPending && markerById.has(selectedId)) {
      markerById.get(selectedId).openPopup();
      focusPending = false;
    }
    setStatus("Imagery ready", `${data.total} CoStar properties in view · coverage limited to Vexcel imagery.`);
  } catch (error) {
    if (error.name !== "AbortError") setStatus("Property layer unavailable", error.message, true);
  }
}

function selectProperty(property) {
  const location = [property.lat, property.lon];
  let zoom = Math.max(17, map.getMinZoom());
  const samples = viewportSamples();
  while (coverage && zoom < map.getMaxZoom() && !coversView(map.project(location, zoom), zoom, samples)) {
    zoom = Math.min(zoom + 1, map.getMaxZoom());
  }
  if (coverage && !coversView(map.project(location, zoom), zoom, samples)) {
    setStatus("Property outside map bounds", "The aerial view would extend beyond the available imagery.", true);
    return;
  }
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
  const q = $("search").value.trim();
  const results = $("results");
  if (q.length < 2) { results.hidden = true; results.replaceChildren(); return; }
  try {
    const data = await json(`/api/search?q=${encodeURIComponent(q)}`);
    if ($("search").value.trim() !== q) return;
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
  } catch (error) { setStatus("Search unavailable", error.message, true); }
}

map.on("moveend", () => {
  if (correcting) return;
  const zoom = map.getZoom();
  if (coverage) {
    const samples = viewportSamples();
    const allowed = (center) => coversView(center, zoom, samples);
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
$("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(search, 220); });
$("reset").addEventListener("click", () => map.setView(HOME, HOME_ZOOM));
const audienceTabs = [...document.querySelectorAll("#audience-tabs [role=tab]")];
function selectAudience(tab, focus = false) {
  for (const option of audienceTabs) {
    const active = option === tab;
    option.setAttribute("aria-selected", String(active));
    option.tabIndex = active ? 0 : -1;
  }
  $("map-workspace").setAttribute("aria-labelledby", tab.id);
  $("planner").hidden = tab.id !== "urban-planners";
  $("planner-title").hidden = $("planner").hidden;
  $("explore-intro").hidden = !$("planner").hidden;
  map.fire("plannervisibility", { visible: !$("planner").hidden });
  if (focus) tab.focus();
}

for (const [index, tab] of audienceTabs.entries()) {
  tab.addEventListener("click", () => selectAudience(tab));
  tab.addEventListener("keydown", (event) => {
    const last = audienceTabs.length - 1;
    const target = {
      ArrowLeft: index === 0 ? last : index - 1,
      ArrowRight: index === last ? 0 : index + 1,
      Home: 0,
      End: last,
    };
    if (!Object.hasOwn(target, event.key)) return;
    event.preventDefault();
    selectAudience(audienceTabs[target[event.key]], true);
  });
}
document.addEventListener("click", (event) => { if (!event.target.closest(".search-block")) $("results").hidden = true; });
new ResizeObserver(() => {
  map.invalidateSize({ pan: true });
  if (coverage && insideCoverage(L.latLng(HOME))) updateMinimumZoom();
}).observe($("map"));
updateMapInfo();
loadCoverage();
