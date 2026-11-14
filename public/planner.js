(() => {
  const featureTypes = {
    crossing: { label: "Crossing", line: true, color: "#f4d983" },
    access: { label: "Driveway keep-clear area", color: "#ffa68f" },
    drainage: { label: "Contributing drainage area", color: "#78dbee" },
    treatment: { label: "Treatment footprint", color: "#ade7a4" },
  };
  const workflows = {
    street: { kinds: ["crossing", "access"], brief: "Shorten this crossing while keeping nearby driveways and loading entrances clear." },
    water: { kinds: ["drainage", "treatment"], brief: "Compare a rain garden and a cistern for the area marked on the map." },
  };
  const siteLayer = L.layerGroup();
  const watershedLayer = L.geoJSON(null, { interactive: false, style: {
    color: "#7cbdff", weight: 2, dashArray: "6 5", fillOpacity: .08,
  } });
  const featuresLayer = L.layerGroup();
  const draftLayer = L.layerGroup();
  const overlays = L.layerGroup([watershedLayer, siteLayer, featuresLayer, draftLayer]);
  const sites = new Map();
  let workflow = "street";
  let site = null;
  let picking = false;
  let draft = null;
  let siteRequest;

  function setStatus(message) {
    $("planner-status").textContent = message;
  }

  function mapHint(message = "") {
    $("planner-map-hint").textContent = message;
    $("planner-map-hint").hidden = !message;
    $("map").classList.toggle("planner-capture", Boolean(message));
  }

  function setPicking(enabled) {
    picking = enabled;
    const button = $("pick-site");
    button.setAttribute("aria-pressed", String(enabled));
    button.textContent = enabled ? "Cancel site selection" : site ? "Choose another site on the map" : "Pick a site on the map";
    mapHint(enabled ? "Click the map to select a site" : "");
  }

  function featureLayer(feature, options = {}) {
    const kind = featureTypes[feature.kind];
    const style = { color: kind.color, weight: 3, fillOpacity: .22, interactive: false, ...options };
    const draw = kind.line || feature.points.length < 3 ? L.polyline : L.polygon;
    return draw(feature.points, style);
  }

  function showFeatures() {
    featuresLayer.clearLayers();
    const list = $("shape-list");
    list.replaceChildren();
    for (const feature of site[workflow].features) {
      if (draft?.feature === feature) continue;
      featureLayer(feature).addTo(featuresLayer);
      const row = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = featureTypes[feature.kind].label;
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      edit.setAttribute("aria-label", `Edit ${label.textContent.toLowerCase()}`);
      edit.disabled = Boolean(draft);
      edit.addEventListener("click", () => startDrawing(feature.kind, feature));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${label.textContent.toLowerCase()}`);
      remove.disabled = Boolean(draft);
      remove.addEventListener("click", () => {
        site[workflow].features = site[workflow].features.filter((entry) => entry !== feature);
        showFeatures();
        setStatus(`${label.textContent} removed.`);
      });
      row.append(label, edit, remove);
      list.append(row);
    }
  }

  function drawPreview() {
    draftLayer.clearLayers();
    featureLayer(draft, { dashArray: "5 4" }).addTo(draftLayer);
    for (const [index, point] of draft.points.entries()) {
      const icon = L.divIcon({ className: "planner-vertex", iconSize: [14, 14] });
      const handle = L.marker(point, { draggable: true, icon, keyboard: false, zIndexOffset: 1500 }).addTo(draftLayer);
      handle.on("drag", () => {
        draft.points[index] = handle.getLatLng();
        draftLayer.eachLayer((layer) => {
          if (layer instanceof L.Polyline) layer.setLatLngs(draft.points);
        });
      });
    }
    $("draw-save").disabled = draft.points.length < (featureTypes[draft.kind].line ? 2 : 3);
    $("draw-undo").disabled = draft.points.length === 0;
  }

  function finishDrawing() {
    draft = null;
    draftLayer.clearLayers();
    $("draw-shape").disabled = false;
    $("draw-controls").hidden = true;
    mapHint();
    if (site) showFeatures();
  }

  function startDrawing(kind, feature = null) {
    setPicking(false);
    map.closePopup();
    draft = { kind, feature, points: feature ? [...feature.points] : [] };
    $("draw-shape").disabled = true;
    $("draw-controls").hidden = false;
    showFeatures();
    drawPreview();
    const minimum = featureTypes[kind].line ? 2 : 3;
    mapHint(feature ? "Drag the handles to edit, then select Save" : `Click ${minimum} or more points, then select Save`);
    setStatus(`Editing ${featureTypes[kind].label.toLowerCase()}.`);
  }

  function showRainfall() {
    const record = site.water;
    $("rain-result").textContent = record.rainMessage;
    $("watershed-result").textContent = record.watershedMessage;
    $("rain-depth").value = record.depth;
    $("rain-source").value = record.source;
    watershedLayer.clearLayers();
    if (workflow === "water" && record.watershed) watershedLayer.addData(record.watershed);
  }

  function loadHydrology() {
    const record = site.water;
    const query = new URLSearchParams({ lat: site.center.lat, lon: site.center.lng });
    record.rainMessage = "Looking up the county’s 24-hour rainfall depth…";
    record.watershedMessage = "Looking up the watershed…";

    const refresh = () => {
      if (site?.water === record && workflow === "water") showRainfall();
    };
    json(`/api/rainfall?${query}`).then(({ estimate }) => {
      if (!estimate) {
        record.rainMessage = "No reliable contour estimate here. Enter a sourced depth.";
      } else {
        const { inches, depth_range: range, method } = estimate;
        record.rainMessage = method === "on_contour"
          ? `${inches.toFixed(2)} in · county 85th-percentile, 24-hour contour.`
          : `About ${inches.toFixed(2)} in · estimated between the ${range[0]} and ${range[1]} in county contours (85th-percentile, 24-hour).`;
        if (!record.rainEdited) {
          record.depth = inches;
          record.source = method === "on_contour" ? "LA County 24-hour rainfall contour" : "LA County 24-hour rainfall contour estimate";
        }
      }
      refresh();
    }).catch(() => {
      record.rainMessage = "County rainfall is unavailable. Enter a sourced depth.";
      refresh();
    });

    json(`/api/watershed?${query}`).then((data) => {
      record.watershed = data;
      const names = [...new Set(data.features.map(({ properties }) => properties.WATERSHED?.trim()).filter(Boolean))];
      record.watershedMessage = names.length
        ? `Watershed: ${names.map((name) => name.replace(/\b\w/g, (letter) => letter.toUpperCase())).join(", ")}`
        : data.features.length ? "County subbasin shown on the map." : "No county subbasin found for this point.";
      refresh();
    }).catch(() => {
      record.watershedMessage = "Watershed boundary unavailable.";
      refresh();
    });
  }

  function showWorkflow() {
    $("water-tools").hidden = workflow !== "water";
    $("shape-kind").replaceChildren(...workflows[workflow].kinds.map((kind) => new Option(featureTypes[kind].label, kind)));
    $("planning-brief").value = site[workflow].brief;
    showFeatures();
    if (workflow === "water" && !site.water.rainMessage) loadHydrology();
    showRainfall();
  }

  function selectSite(center, property = null) {
    finishDrawing();
    const key = property ? `property:${property.id}` : `${center.lat.toFixed(6)},${center.lng.toFixed(6)}`;
    if (site && sites.get(key) === site) {
      setPicking(false);
      return;
    }
    siteRequest?.abort();
    siteRequest = new AbortController();
    site = sites.get(key) ?? { center,
      street: { features: [], brief: "" },
      water: { features: [], brief: "", depth: "", source: "" } };
    sites.set(key, site);
    setPicking(false);
    $("site-card").hidden = false;
    $("site-tools").hidden = false;
    $("site-name").textContent = property?.name ?? "Map location";
    $("site-location").textContent = [property?.address, `${center.lat.toFixed(5)}, ${center.lng.toFixed(5)}`].filter(Boolean).join(" · ");
    $("site-property").textContent = property?.type ?? "";
    siteLayer.clearLayers();
    L.circleMarker(center, { radius: 8, weight: 2, color: "#fff", fillColor: "#a7e5a3",
      fillOpacity: 1, interactive: false }).addTo(siteLayer);
    showWorkflow();
    setStatus("Choose a workflow or mark a feature on the map.");

    if (!property) return;
    const selectedSite = site;
    const signal = siteRequest.signal;
    json(`/api/property-detail?id=${encodeURIComponent(property.id)}`, { signal }).then((detail) => {
      if (site !== selectedSite || signal.aborted) return;
      const fields = [property.type];
      if (detail.units != null) fields.push(`${detail.units.toLocaleString()} units`);
      if (detail.vacancyPercent != null) fields.push(`${detail.vacancyPercent}% reported vacancy`);
      if (detail.reportedParkingSpaces != null) fields.push(`${detail.reportedParkingSpaces.toLocaleString()} reported parking spaces`);
      if (detail.reportedLoadingDocks != null) fields.push(`${detail.reportedLoadingDocks.toLocaleString()} reported loading docks`);
      if (detail.buildingAreaSqFt != null) fields.push(`${Math.round(detail.buildingAreaSqFt).toLocaleString()} sq ft gross building area`);
      $("site-property").textContent = `${fields.join(" · ")} (CoStar)`;
    }).catch((error) => {
      if (error.name !== "AbortError" && site === selectedSite) {
        $("site-property").textContent = `${property.type} · Additional CoStar fields unavailable.`;
      }
    });
  }

  $("pick-site").addEventListener("click", () => {
    finishDrawing();
    setPicking(!picking);
    if (picking) map.closePopup();
    setStatus(picking ? "Click any covered location on the map." : "Site selection canceled.");
  });
  map.on("click", ({ latlng }) => {
    if (!picking && !draft) return;
    if (coverage && !insideCoverage(latlng)) {
      setStatus("Choose a point inside the imagery coverage.");
      return;
    }
    if (picking) {
      selectSite(latlng);
      map.setView(latlng, Math.max(map.getZoom(), 17), { animate: false });
    } else {
      draft.points.push(latlng);
      drawPreview();
    }
  });
  map.on("plannerproperty", ({ property, searched }) => {
    if (!$("planner").hidden && (searched || (!picking && !draft))) {
      selectSite(L.latLng(property.lat, property.lon), property);
    }
  });
  map.on("plannervisibility", ({ visible }) => {
    if (visible) overlays.addTo(map);
    else {
      finishDrawing();
      setPicking(false);
      overlays.remove();
    }
  });
  for (const input of document.querySelectorAll('input[name="workflow"]')) {
    input.addEventListener("change", () => {
      finishDrawing();
      setPicking(false);
      workflow = input.value;
      showWorkflow();
      setStatus(`${input.nextElementSibling.textContent.replace(/\s+/g, " ")} workflow active.`);
    });
  }
  $("draw-shape").addEventListener("click", () => startDrawing($("shape-kind").value));
  $("draw-cancel").addEventListener("click", () => {
    finishDrawing();
    setStatus("Edits canceled.");
  });
  $("draw-undo").addEventListener("click", () => {
    draft.points.pop();
    drawPreview();
  });
  $("draw-save").addEventListener("click", () => {
    const distinct = new Set(draft.points.map(({ lat, lng }) => `${lat.toFixed(7)},${lng.toFixed(7)}`));
    if (distinct.size < (featureTypes[draft.kind].line ? 2 : 3)) {
      setStatus("Add distinct points to save this feature.");
      return;
    }
    if (coverage && draft.points.some((point) => !insideCoverage(point))) {
      setStatus("Move all points inside the imagery coverage before saving.");
      return;
    }
    if (draft.feature) draft.feature.points = draft.points;
    else site[workflow].features.push({ kind: draft.kind, points: draft.points });
    const label = featureTypes[draft.kind].label;
    finishDrawing();
    setStatus(`${label} saved.`);
  });
  for (const [id, field] of [["rain-depth", "depth"], ["rain-source", "source"]]) {
    $(id).addEventListener("input", ({ target }) => {
      site.water[field] = target.value;
      site.water.rainEdited = true;
    });
  }
  $("suggest-brief").addEventListener("click", () => {
    const input = $("planning-brief");
    input.value = workflows[workflow].brief;
    site[workflow].brief = input.value;
    input.focus();
  });
  $("planning-brief").addEventListener("input", ({ target }) => { site[workflow].brief = target.value; });
})();
