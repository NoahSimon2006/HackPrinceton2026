(() => {
  const featureTypes = {
    crossing: { label: "Crossing", action: "Mark an existing crossing", line: true, color: "#f4d983",
      description: "Mark both ends of the crosswalk.",
      instruction: "Click one end of the crosswalk, then the other." },
    access: { label: "Keep-clear area", action: "Mark a driveway to keep clear", color: "#ffa68f",
      description: "Outline a driveway or loading entrance.",
      instruction: "Click around the entrance to outline the space to keep clear." },
    drainage: { label: "Runoff source", action: "Outline where runoff starts", color: "#78dbee",
      description: "Mark a roof or paved area that drains toward the site.",
      instruction: "Click around the roof or pavement that contributes runoff." },
    treatment: { label: "Treatment area", action: "Outline a spot for a rain garden or cistern", color: "#ade7a4",
      description: "Mark the space you want to consider for a treatment.",
      instruction: "Click around the space you want to use for the rain garden or cistern." },
  };
  const workflows = {
    street: { kinds: ["crossing", "access"], brief: "Find the crossings and driveway entrances near this site. What could shorten a crossing while preserving access?" },
    water: { kinds: ["drainage", "treatment"], brief: "Find possible sources of runoff and check the local rainfall. What could we evaluate for a rain garden or cistern?" },
  };
  const siteLayer = L.layerGroup();
  const watershedLayer = L.geoJSON(null, { interactive: false, style: {
    color: "#7cbdff", weight: 2, dashArray: "6 5", fillOpacity: .08,
  } });
  const featuresLayer = L.layerGroup();
  const draftLayer = L.layerGroup();
  const evidenceLayer = L.layerGroup();
  const overlays = L.layerGroup([watershedLayer, evidenceLayer, siteLayer, featuresLayer, draftLayer]);
  const sites = new Map();
  let workflow = "street";
  let site = null;
  let picking = false;
  let draft = null;
  let siteRequest;

  function addEvidence(item, color, style = {}) {
    const layer = L.geoJSON(item, { style: { color, weight: 2, fillOpacity: .1, ...style } });
    const label = document.createElement("span");
    const { label: name, date, score } = item.properties;
    label.textContent = [name, date, score == null ? null : `detector score ${score.toFixed(2)}`].filter(Boolean).join(" · ");
    layer.bindTooltip(label).addTo(evidenceLayer);
  }

  function showEvidence() {
    evidenceLayer.clearLayers();
    const record = site[workflow];
    const evidence = record.evidence;
    const list = $("site-evidence-list");
    list.replaceChildren();
    $("run-site-analysis").disabled = Boolean(record.evidencePending);
    const assessment = $("agent-assessment");
    assessment.hidden = !record.assessment;
    assessment.textContent = record.assessment ?? "";
    $("site-search-toggle").hidden = !evidence?.search?.length;
    $("site-evidence-note").hidden = !evidence;
    if (!evidence) {
      $("site-evidence-status").textContent = record.evidencePending ? "The agent is checking the site…"
        : record.evidenceError || "Analyze this site to map evidence.";
      return;
    }
    const { outlines, detections, frontages, search, unavailable } = evidence;
    const featureCount = outlines.length + detections.length + frontages.length;
    $("site-evidence-status").textContent = featureCount
      ? `${featureCount} ${featureCount === 1 ? "feature" : "features"} on the map` : "No mapped features found at this site.";
    const legend = new Map();
    for (const item of outlines) {
      const label = item.properties.label;
      const color = label === "Parcel boundary" ? "#8ebeff" : "#a7e5a3";
      addEvidence(item, color, { fillOpacity: label === "Parcel boundary" ? 0 : .12 });
      legend.set(`${label} · Vexcel`, color);
    }
    for (const item of detections) {
      addEvidence(item, "#f4d983", { dashArray: "5 4" });
      legend.set(`${item.properties.label} candidate · Vexcel`, "#f4d983");
    }
    for (const frontage of frontages) {
      const label = [frontage.street, "CoStar frontage", frontage.curbCuts == null ? null : `${frontage.curbCuts} reported curb cuts`].filter(Boolean).join(" · ");
      addEvidence({ type: "Feature", geometry: frontage.geometry, properties: { label } }, "#eb9eff", { weight: 4 });
      legend.set("Street frontage · CoStar", "#eb9eff");
    }
    if ($("show-search-matches").checked) {
      for (const item of search) addEvidence(item, "#d0acff", { dashArray: "3 5", fillOpacity: 0 });
      if (search.length) legend.set("Imagery search area · Vexcel", "#d0acff");
    }
    for (const [label, color] of legend) {
      const entry = document.createElement("li");
      const text = document.createElement("span");
      text.className = "mark-label";
      text.style.setProperty("--mark-color", color);
      text.textContent = label;
      entry.append(text);
      list.append(entry);
    }
    const found = new Set(detections.map(({ properties }) => properties.label));
    const notes = workflow === "street"
      ? [!found.has("Driveway entrance") && "Driveway location unverified.", !found.has("Zebra crosswalk") && "Crossing location unverified."]
      : ["Building and parking outlines show potential runoff surfaces. Drainage direction and treatment suitability are unverified."];
    if (unavailable.some((group) => group !== "hydrology")) notes.push("Some Vexcel data could not be loaded.");
    if (unavailable.includes("hydrology")) notes.push("County rainfall or watershed data could not be loaded.");
    if (evidence.costarUnavailable) notes.push("CoStar frontage unavailable.");
    $("site-evidence-note").textContent = notes.filter(Boolean).join(" ");
  }

  async function loadEvidence(event) {
    event.preventDefault();
    const selected = site;
    const mode = workflow;
    const record = selected[mode];
    if (record.evidencePending) return;
    const question = record.brief.trim();
    if (!question) return;
    record.evidencePending = true;
    record.evidenceError = "";
    record.evidence = null;
    record.assessment = "";
    showEvidence();
    try {
      const result = await json("/api/site-analysis", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ lat: selected.center.lat, lon: selected.center.lng,
          propertyId: selected.propertyId, workflow: mode, question,
          markings: record.features.map(({ kind }) => kind) }),
      });
      record.evidence = result.evidence;
      record.assessment = result.assessment;
      if (result.hydrology) applyHydrology(selected.water, result.hydrology);
    } catch (error) {
      record.evidenceError = error.message;
    } finally {
      record.evidencePending = false;
      if (site?.[workflow] === record) {
        showEvidence();
        showRainfall();
      }
    }
  }

  function setStatus(message) {
    $("planner-status").textContent = message;
  }

  function mapHint(message = "") {
    $("planner-map-hint").textContent = message;
    $("planner-map-panel").hidden = !message;
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
      if (draft?.feature !== feature) featureLayer(feature).addTo(featuresLayer);
      const row = document.createElement("li");
      const label = document.createElement("span");
      label.className = "mark-label";
      label.style.setProperty("--mark-color", featureTypes[feature.kind].color);
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

  function showMarkActions() {
    const actions = $("mark-actions");
    actions.replaceChildren();
    for (const kind of workflows[workflow].kinds) {
      const type = featureTypes[kind];
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mark-action";
      button.style.setProperty("--mark-color", type.color);
      button.setAttribute("aria-label", type.action);
      button.disabled = Boolean(draft);
      const title = document.createElement("strong");
      title.textContent = type.action;
      const description = document.createElement("small");
      description.textContent = type.description;
      button.append(title, description);
      button.addEventListener("click", () => startDrawing(kind));
      actions.append(button);
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
    const count = draft.points.length;
    const type = featureTypes[draft.kind];
    const minimum = type.line ? 2 : 3;
    $("draw-save").disabled = count < minimum;
    $("draw-undo").disabled = count === 0;
    const saveLabel = `Save ${type.label.toLowerCase()}`;
    $("draw-save").textContent = saveLabel;
    let hint = type.instruction;
    if (count >= minimum) {
      const editHint = type.line ? "Drag either endpoint to adjust." : "Drag a point to adjust or click to add another.";
      hint = `${editHint} Select “${saveLabel}” when ready.`;
    } else if (count > 0) {
      const remaining = minimum - count;
      hint += ` Add ${remaining} more ${remaining === 1 ? "point" : "points"} to save.`;
    }
    mapHint(hint);
  }

  function finishDrawing() {
    draft = null;
    draftLayer.clearLayers();
    $("draw-controls").hidden = true;
    mapHint();
    if (site) {
      showFeatures();
      showMarkActions();
    }
  }

  function startDrawing(kind, feature = null) {
    setPicking(false);
    map.closePopup();
    draft = { kind, feature, points: feature ? [...feature.points] : [] };
    $("draw-controls").hidden = false;
    showFeatures();
    showMarkActions();
    drawPreview();
    setStatus("");
  }

  function showRainfall() {
    const record = site.water;
    $("rain-result").textContent = record.rainMessage ?? "Analyze the site for a county estimate, or enter a depth.";
    $("watershed-result").textContent = record.watershedMessage ?? "";
    $("rain-depth").value = record.depth;
    $("rain-source").value = record.source;
    watershedLayer.clearLayers();
    if (workflow === "water" && record.watershed) watershedLayer.addData(record.watershed);
  }

  function applyHydrology(record, { estimate, watershed }) {
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
    record.watershed = watershed;
    const names = [...new Set(watershed.features.map(({ properties }) => properties.WATERSHED?.trim()).filter(Boolean))];
    record.watershedMessage = names.length
      ? `Watershed: ${names.map((name) => name.replace(/\b\w/g, (letter) => letter.toUpperCase())).join(", ")}`
      : watershed.features.length ? "County subbasin shown on the map." : "No county subbasin found for this point.";
  }

  function showWorkflow() {
    $("water-tools").hidden = workflow !== "water";
    $("planning-brief").value = site[workflow].brief;
    showMarkActions();
    showFeatures();
    showEvidence();
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
    site = sites.get(key) ?? { center, propertyId: property?.id,
      street: { features: [], brief: workflows.street.brief },
      water: { features: [], brief: workflows.water.brief, depth: "", source: "" } };
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
    setStatus("");

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
    } else if (!featureTypes[draft.kind].line || draft.points.length < 2) {
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
  // app.js may already have opened the workspace through #urban-planners
  // before this deferred script registered its visibility listener.
  if (!$("planner").hidden) overlays.addTo(map);
  for (const input of document.querySelectorAll('input[name="workflow"]')) {
    input.addEventListener("change", () => {
      finishDrawing();
      setPicking(false);
      workflow = input.value;
      showWorkflow();
      setStatus("");
    });
  }
  $("draw-cancel").addEventListener("click", () => {
    finishDrawing();
    setStatus("Edits canceled.");
  });
  $("show-search-matches").addEventListener("change", showEvidence);
  $("site-analysis").addEventListener("submit", loadEvidence);
  $("draw-undo").addEventListener("click", () => {
    draft.points.pop();
    drawPreview();
  });
  $("draw-save").addEventListener("click", () => {
    const distinct = new Set(draft.points.map(({ lat, lng }) => `${lat.toFixed(7)},${lng.toFixed(7)}`));
    if (distinct.size < (featureTypes[draft.kind].line ? 2 : 3)) {
      mapHint("Place each point in a different location before saving.");
      return;
    }
    if (coverage && draft.points.some((point) => !insideCoverage(point))) {
      mapHint("Move all points inside the imagery coverage before saving.");
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
  $("planning-brief").addEventListener("input", ({ target }) => { site[workflow].brief = target.value; });
})();
