const $ = (id) => document.getElementById(id);
const HOME = [34.0522, -118.2437];
const MIN_PROPERTY_ZOOM = 15;
const map = L.map("map", { minZoom: 10, maxZoom: 20, zoomSnap: .25, zoomDelta: .5,
  scrollWheelZoom: true, inertia: true }).setView(HOME, 11);
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
  return coverage.features.some(({ geometry }) => {
    if (geometry.type === "Polygon") return insidePolygon(point, geometry.coordinates);
    if (geometry.type === "MultiPolygon") return geometry.coordinates.some((rings) => insidePolygon(point, rings));
    return false;
  });
}

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
    if (!insideCoverage(map.getCenter())) {
      setStatus("Coverage unavailable here", "The opening point is outside Vexcel coverage.", true);
      return;
    }
    lastAllowed = map.getCenter();
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
  if (coverage && !insideCoverage({ lat: property.lat, lng: property.lon })) {
    setStatus("Property outside coverage", "This property is outside the available Vexcel imagery.", true);
    return;
  }
  selectedId = property.id;
  focusPending = true;
  $("properties").checked = true;
  $("results").hidden = true;
  $("search").value = property.name;
  map.setView([property.lat, property.lon], 17);
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
  if (correcting) { correcting = false; return; }
  if (coverage && !insideCoverage(map.getCenter())) {
    correcting = true;
    map.panTo(lastAllowed, { animate: false });
    setStatus("Vexcel coverage edge", "The map center must stay inside available imagery.");
    return;
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
$("reset").addEventListener("click", () => map.setView(HOME, 11));
document.addEventListener("click", (event) => { if (!event.target.closest(".search-block")) $("results").hidden = true; });
new ResizeObserver(() => map.invalidateSize({ pan: false })).observe($("map"));
updateMapInfo();
loadCoverage();
