/* Shared browsing layer. Site-analysis evidence remains in its own pane. */
(() => {
  const MIN_ZOOM = 17, TILE_ZOOM = 17, MAX_TILES = 128, CACHE_SIZE = 256;
  const LA = [-118.67, 33.70, -118.10, 34.35];
  const toggle = document.getElementById("parcels");
  const status = document.getElementById("parcel-status");
  const info = document.getElementById("parcel-info");
  const retry = document.getElementById("parcel-retry");
  try {
    const saved = localStorage.getItem("map-parcels-visible");
    if (saved !== null) toggle.checked = saved === "true";
  } catch (_) { /* Storage can be disabled; the toggle still works. */ }
  map.createPane("parcel-context");
  const pane = map.getPane("parcel-context");
  pane.style.zIndex = 390; // Below default overlays, selected sites and markers.
  pane.style.pointerEvents = "none";
  const renderer = L.canvas({ pane: "parcel-context", padding: .25 });
  const outlines = L.geoJSON([], {
    pane: "parcel-context", renderer, interactive: false,
    style: feature => ({
      color: feature.properties.label === "Parcel boundary" ? "#8ebeff" : "#a7e5a3",
      weight: 1.25, opacity: .7, fill: false,
    }),
  });
  const cache = new Map(), pending = new Map(), failures = new Map();
  let wanted = [], timer;
  const active = () => toggle.checked && map.getZoom() >= MIN_ZOOM;
  const tileX = lon => (lon + 180) / 360 * 2 ** TILE_ZOOM;
  const tileY = lat => (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * 2 ** TILE_ZOOM;
  const cached = key => {
    const entry = cache.get(key);
    if (entry && entry.expires > Date.now()) return entry.data;
    cache.delete(key);
    return null;
  };

  function visibleTiles() {
    const bounds = map.getBounds();
    const west = Math.max(LA[0], bounds.getWest()), east = Math.min(LA[2], bounds.getEast());
    const south = Math.max(LA[1], bounds.getSouth()), north = Math.min(LA[3], bounds.getNorth());
    if (west >= east || south >= north) return [];
    const left = Math.floor(tileX(west)), right = Math.ceil(tileX(east)) - 1;
    const top = Math.floor(tileY(north)), bottom = Math.ceil(tileY(south)) - 1;
    if ((right - left + 1) * (bottom - top + 1) > MAX_TILES) return null;
    const tiles = [];
    for (let x = left; x <= right; x++) for (let y = top; y <= bottom; y++) tiles.push({
      key: `${TILE_ZOOM}/${x}/${y}`, distance: (x - (left + right) / 2) ** 2 + (y - (top + bottom) / 2) ** 2,
    });
    return tiles.sort((a, b) => a.distance - b.distance).map(tile => tile.key);
  }

  function render() {
    if (!active()) return;
    const unique = new Map();
    let loaded = 0, partial = false, failed = 0;
    for (const key of wanted) {
      const data = cached(key);
      if (!data) { if (failures.has(key)) failed++; continue; }
      loaded++;
      partial ||= data.status === "partial";
      for (const feature of data.features) {
        const prior = unique.get(feature.id);
        if (!prior || (feature.properties.date || "") >= (prior.properties.date || "")) unique.set(feature.id, feature);
      }
    }
    outlines.clearLayers();
    outlines.addData({ type: "FeatureCollection", features: [...unique.values()] });
    outlines.addTo(map);
    retry.hidden = !failed && !partial;
    if (failed) status.textContent = "Some outlines couldn’t load. Retry to fill the gaps.";
    else if (loaded < wanted.length) status.textContent = `Loading outlines… ${loaded}/${wanted.length} areas`;
    else if (partial) status.textContent = "Some outlines are incomplete. Try zooming in or retry.";
    else status.textContent = unique.size ? "Blue parcels · green buildings. Reference outlines; coverage varies."
      : "No Vexcel parcel outlines available in this view.";
  }

  function pump() {
    if (!active()) return;
    for (const key of wanted) {
      if (pending.size >= 2) break;
      if (cached(key) || pending.has(key) || failures.has(key)) continue;
      const controller = new AbortController();
      pending.set(key, controller);
      (async () => {
        try {
          const response = await fetch(`/api/parcels/${key}.json`, { signal: controller.signal });
          const data = await response.json();
          if (!response.ok || data.type !== "FeatureCollection" || !Array.isArray(data.features)) throw new Error("Outlines unavailable");
          if (controller.signal.aborted) return;
          cache.delete(key);
          cache.set(key, { data, expires: Date.now() + (data.status === "partial" ? 300_000 : 3_600_000) });
          while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value);
        } catch (error) {
          if (!controller.signal.aborted) failures.set(key, Date.now());
        } finally {
          pending.delete(key);
          // Render only currently wanted cells; old requests can warm the cache
          // but never replace the new viewport or restore a hidden layer.
          if (active() && wanted.length) render();
          pump();
        }
      })();
    }
  }

  function update() {
    clearTimeout(timer);
    info.hidden = !toggle.checked;
    retry.hidden = true;
    if (!active()) {
      wanted = [];
      for (const request of pending.values()) request.abort();
      outlines.clearLayers();
      outlines.remove();
      status.textContent = "Zoom in to level 17 to see outlines.";
      return;
    }
    for (const [key, at] of failures) if (Date.now() - at > 30_000) failures.delete(key);
    const tiles = visibleTiles();
    wanted = tiles || [];
    if (!tiles) {
      outlines.clearLayers();
      status.textContent = "Zoom in further to see parcel and building outlines.";
      return;
    }
    render();
    pump();
  }
  map.on("moveend", () => { clearTimeout(timer); timer = setTimeout(update, 180); });
  map.on("zoomend", () => { if (!active()) update(); });
  toggle.addEventListener("change", () => {
    try { localStorage.setItem("map-parcels-visible", String(toggle.checked)); } catch (_) { /* optional */ }
    update();
  });
  retry.addEventListener("click", () => {
    for (const key of wanted) {
      failures.delete(key);
      if (cached(key)?.status === "partial") cache.delete(key);
    }
    update();
  });
  update();
})();
