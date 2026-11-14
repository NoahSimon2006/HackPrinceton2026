const get = (id) => document.getElementById(id);
const format = new Intl.NumberFormat("en-US");
const rows = new Map();
let map;
let selectedPin;
let sites = [];
let selected = null;
let dataset;
let siteRequest;
let aerialUrl;
let crashData;
let crashLoadError = false;
let heatLayer;
let siteMarkers;
let filteredSites = [];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

if (window.L) {
  map = L.map("map", {
    minZoom: 10, maxZoom: 20, zoomSnap: .25, zoomDelta: .5,
    scrollWheelZoom: true, wheelPxPerZoomLevel: 120, wheelDebounceTime: 40,
    inertia: true, inertiaDeceleration: 2400, zoomAnimation: !reducedMotion.matches,
  }).setView([34.048, -118.25], 14);
  const imagery = L.tileLayer("/api/vexcel/tiles/{z}/{x}/{y}.jpg", {
    minZoom: 10, maxNativeZoom: 20, maxZoom: 20, keepBuffer: 3,
    updateWhenIdle: true, updateWhenZooming: false,
    attribution: 'Aerial imagery © <a href="https://vexceldata.com/">Vexcel Imaging</a>',
  }).addTo(map);
  const failedTiles = new Set();
  function tileStatus() {
    get("tile-status").hidden = failedTiles.size === 0;
    get("tile-error-message").textContent = "Some Vexcel imagery could not load. Check your connection, key, or coverage, then retry.";
  }
  imagery.on("tileerror", ({ tile }) => { failedTiles.add(tile); tileStatus(); });
  imagery.on("tileload tileunload", ({ tile }) => { failedTiles.delete(tile); tileStatus(); });
  get("retry-tiles").addEventListener("click", () => {
    failedTiles.clear();
    tileStatus();
    imagery.redraw();
  });
  map.createPane("placeLabels");
  map.getPane("placeLabels").style.zIndex = 450;
  map.getPane("placeLabels").style.pointerEvents = "none";
  const labels = L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
    pane: "placeLabels", maxNativeZoom: 19, maxZoom: 20, keepBuffer: 3,
    attribution: 'Labels © Esri, HERE, Garmin, © OpenStreetMap contributors',
  }).addTo(map);
  get("labels-toggle").addEventListener("change", (event) => {
    if (event.target.checked) labels.addTo(map); else labels.remove();
  });
  L.control.scale({ position: "bottomleft", imperial: true, metric: true }).addTo(map);
  siteMarkers = L.layerGroup().addTo(map);
  if (L.heatLayer) {
    heatLayer = L.heatLayer([], {
      radius: 25, blur: 22, maxZoom: 14, minOpacity: .12,
      gradient: { .25: "#27b6c6", .5: "#ffe17b", .75: "#ff8b3d", 1: "#e83834" },
    });
  } else {
    get("heat-toggle").disabled = true;
    get("heat-description").textContent = "The heat-map library could not load. Reload to try again.";
  }
  new ResizeObserver(() => map.invalidateSize({ pan: false })).observe(get("map"));
} else {
  get("map").textContent = "Map unavailable. Reload or use the ranked list.";
  for (const id of ["heat-toggle", "labels-toggle", "map-overview"]) get(id).disabled = true;
}

function showOverview() {
  if (!map || !filteredSites.length) return;
  map.stop();
  map.fitBounds(filteredSites.map((site) => [site.lat, site.lon]), {
    padding: [45, 45], maxZoom: 16, animate: !reducedMotion.matches,
  });
}

function updateMapLayers(ranked) {
  filteredSites = ranked.map(({ site }) => site);
  get("map-overview").disabled = !map || !ranked.length;
  if (!map) return;
  siteMarkers.clearLayers();
  for (const { site, total } of ranked) {
    const label = document.createElement("span");
    label.textContent = `${site.name} · ${total} reports`;
    L.circleMarker([site.lat, site.lon], {
      radius: 4, weight: 1, color: "#fff", fillColor: "#8ed9d1", fillOpacity: .65,
    }).bindTooltip(label).on("click", () => select(site, true)).addTo(siteMarkers);
  }
  if (heatLayer) {
    // Use one scale for all street searches in this period. Counts belong to
    // disjoint legacy name groups; CHP name-matched records are not added.
    const year = get("year").value;
    heatLayer.setOptions({ max: Math.max(1, ...sites.map((site) => count(site, year))) });
    heatLayer.setLatLngs(ranked.map(({ site, total }) => [site.lat, site.lon, total]));
    get("heat-period").textContent = `${year === "all" ? "2022–2023" : year} · LAPD · ${ranked.length} street pairs`;
  }
}

get("map-overview").addEventListener("click", showOverview);
get("map-selected").addEventListener("click", () => { if (selected) select(selected, true); });
get("heat-toggle").addEventListener("change", (event) => {
  if (!map || !heatLayer) return;
  const enabled = event.target.checked;
  if (enabled) heatLayer.addTo(map); else heatLayer.remove();
  get("heat-legend").hidden = !enabled;
});
get("heat-opacity").addEventListener("input", (event) => {
  const opacity = Number(event.target.value);
  get("map").style.setProperty("--heat-opacity", opacity / 100);
  get("heat-opacity-value").value = `${opacity}%`;
});

function count(site, year) {
  if (year !== "all") return site.years[year] ?? 0;
  return Object.values(site.years).reduce((total, value) => total + value, 0);
}

function select(site, zoom = false) {
  const changed = selected !== site;
  selected = site;
  get("map-selected").disabled = !map || !site;
  get("map-selection").textContent = site ? site.name : "No intersection selected";
  if (changed) showSponsorContext(site);
  resetBrief();
  if (changed) showCrashHistory();
  for (const [item, button] of rows) {
    button.setAttribute("aria-pressed", String(item === site));
  }
  if (map && changed) {
    selectedPin?.remove();
    selectedPin = site ? L.circleMarker([site.lat, site.lon], {
      radius: 9, weight: 3, color: "#fff", fillColor: "#e89b3c", fillOpacity: 1,
      interactive: false,
    }).addTo(map) : undefined;
  }
  selectedPin?.bringToFront();
  const link = get("street-map");
  link.hidden = !site;
  if (!site) {
    get("evidence").textContent = "Select a street pair to view its reported collision totals.";
    return;
  }
  const year = get("year").value;
  const reports = count(site, year);
  get("evidence").textContent = `${site.name} recorded ${format.format(reports)} collision ${reports === 1 ? "report" : "reports"} in ${year === "all" ? "2022–2023" : year}.`;
  link.href = `https://www.openstreetmap.org/#map=18/${site.lat}/${site.lon}`;
  if (zoom && map) {
    map.stop();
    map.flyTo([site.lat, site.lon], Math.max(map.getZoom(), 16), { duration: .65, animate: !reducedMotion.matches });
  }
}

function render() {
  if (!dataset) return;
  const year = get("year").value;
  const terms = get("search").value.toUpperCase().trim().split(/\s+/);
  const ranked = sites.map((site) => ({ site, total: count(site, year) }))
    .filter(({ site, total }) => total && terms.every((term) => site.name.includes(term)))
    .sort((a, b) => b.total - a.total || a.site.name.localeCompare(b.site.name));
  get("ranking").replaceChildren();
  rows.clear();
  for (const { site, total } of ranked) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    const name = document.createElement("span");
    const number = document.createElement("strong");
    name.textContent = site.name;
    number.textContent = format.format(total);
    button.type = "button";
    button.append(name, number);
    button.addEventListener("click", () => select(site, true));
    row.append(button);
    get("ranking").append(row);
    rows.set(site, button);
  }
  get("status").textContent = ranked.length
    ? `${format.format(ranked.length)} matches · ${format.format(dataset.excluded)} reports excluded from the full extract`
    : "No intersections match these filters.";
  const next = rows.has(selected) ? selected : ranked[0]?.site ?? null;
  updateMapLayers(ranked);
  select(next);
}

get("city").addEventListener("change", () => {
  const houston = get("city").value === "houston";
  get("houston").hidden = !houston;
  get("la").hidden = houston;
  resetBrief();
  if (!houston && map) map.invalidateSize();
});
get("year").addEventListener("change", render);
get("search").addEventListener("input", render);
fetch("data/la.json").then((response) => {
  if (!response.ok) throw new Error("Collision totals missing");
  return response.json();
}).then((data) => {
  dataset = data;
  sites = data.sites;
  render();
  showOverview();
}).catch(() => {
  get("status").textContent = "Collision totals are unavailable. Run python3 scripts/import_la.py from the project folder, then reload.";
});

async function requestContext(feature, site, options = {}) {
  const { signal, ...fields } = options;
  const response = await fetch(`/api/${feature}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ site: site.name, ...fields }),
    signal,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  if (!response.ok) {
    const result = isJson ? await response.json() : {};
    throw new Error(result.error || "Start the local Crossing Lab server to use this feature.");
  }
  return feature === "vexcel" ? response.blob() : response.json();
}

async function showSponsorContext(site) {
  siteRequest?.abort();
  const signal = (siteRequest = new AbortController()).signal;
  get("sponsor").hidden = !site;
  get("aerial").hidden = true;
  get("aerial").removeAttribute("src");
  if (aerialUrl) URL.revokeObjectURL(aerialUrl);
  aerialUrl = undefined;
  get("aerial-status").textContent = "";
  get("load-aerial").disabled = false;
  get("costar-types").replaceChildren();
  if (!site) return;

  get("costar-status").textContent = "Loading property counts…";
  try {
    const { total, types } = await requestContext("costar", site, { signal });
    if (signal.aborted) return;
    get("costar-status").textContent = total
      ? `${format.format(total)} ${total === 1 ? "property" : "properties"} in the kit near this intersection.`
      : "The CoStar kit has no geocoded commercial properties within this radius.";
    for (const [type, count] of Object.entries(types)) {
      const item = document.createElement("li");
      item.textContent = `${type} · ${format.format(count)}`;
      get("costar-types").append(item);
    }
  } catch (error) {
    if (!signal.aborted) get("costar-status").textContent = error.message;
  }
}

get("load-aerial").addEventListener("click", async () => {
  if (!selected) return;
  const { signal } = siteRequest;
  get("load-aerial").disabled = true;
  get("aerial-status").textContent = "Loading Vexcel imagery…";
  try {
    const image = await requestContext("vexcel", selected, { signal });
    if (signal.aborted) return;
    if (aerialUrl) URL.revokeObjectURL(aerialUrl);
    aerialUrl = URL.createObjectURL(image);
    get("aerial").src = aerialUrl;
    get("aerial").hidden = false;
    get("aerial-status").textContent = "";
  } catch (error) {
    if (!signal.aborted) get("aerial-status").textContent = error.message;
  } finally {
    if (!signal.aborted) get("load-aerial").disabled = false;
  }
});

function resetBrief() {
  window.investigationSelect?.(get("city").value === "la" ? selected : null);
  window.designSelect?.(get("city").value === "la" ? selected : null);
}

function showCrashHistory() {
  const location = get("crash-location");
  const details = get("crash-details");
  get("crash-records").replaceChildren();
  details.hidden = true;
  details.open = false;
  if (!selected) {
    location.textContent = "Select a street pair to see why it may warrant a closer look.";
    return;
  }
  if (!crashData) {
    location.textContent = crashLoadError
      ? "Crash history unavailable. Run python3 scripts/import_ccrs.py and reload."
      : "Loading CHP crash reports…";
    return;
  }
  const records = crashData.sites[selected.name] ?? [];
  if (!records.length) {
    location.textContent = `No CHP reports matched ${selected.name} in 2023–2024 using the street-name rule. Unmatched or unreported crashes may be missing.`;
    return;
  }
  location.textContent = `${selected.name} · ${records.length} ${records.length === 1 ? "report names" : "reports name"} both streets.`;
  get("crash-radius").textContent = crashData.near_ft;
  get("crash-detail-label").textContent = `View ${records.length} matched CHP ${records.length === 1 ? "report" : "reports"}`;
  for (const row of records) {
    const entry = document.createElement("tr");
    const offset = row.offset_ft === null ? "Unknown"
      : row.offset_ft === 0 ? "0 ft · junction" : `${row.offset_ft} ft from ${row.cross}`;
    for (const value of [
      row.when?.replace("T", " ").slice(0, 16), row.road, offset,
      row.type, row.involved_with, row.light, row.injured, row.killed,
    ]) {
      const cell = document.createElement("td");
      cell.textContent = value ?? "Unknown";
      entry.append(cell);
    }
    get("crash-records").append(entry);
  }
  details.hidden = false;
}

fetch("/data/ccrs.json").then((response) => {
  if (!response.ok) throw new Error("Crash data unavailable");
  return response.json();
}).then((data) => {
  crashData = data;
  showCrashHistory();
}).catch(() => {
  crashLoadError = true;
  showCrashHistory();
});
