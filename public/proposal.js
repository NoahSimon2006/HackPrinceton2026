/* Backend proposal.Proposal is the canonical revision-bound geometry contract.
 * Development fixtures and evaluated designs deliberately use separate rendering paths.
 */
(() => {
  map.createPane("proposal");
  map.getPane("proposal").style.zIndex = 610;
  map.getPane("proposal").style.pointerEvents = "none";
  let selected = null, published = null, comparison = null, layer = null, request = 0, controller;
  let realRevision = 0;
  const show = $("show-proposal");
  const element = (tag, text) => { const el = document.createElement(tag); if (text != null) el.textContent = text; return el; };
  const label = name => String(name).replaceAll("_", " ").replaceAll("-", " ");
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const maximum = value => {
    if (finite(value)) return value;
    const numbers = Object.values(value ?? {});
    return numbers.length && numbers.every(finite) ? Math.max(...numbers) : null;
  };
  const number = (value, unit = "", digits = 1) => finite(value)
    ? `${value.toLocaleString(undefined, {maximumFractionDigits:digits})}${unit ? ` ${unit}` : ""}` : "Not assessed";
  function visible() {
    if (!layer) return;
    if (show.checked) layer.addTo(map); else layer.remove();
  }
  function caption(stale = false) {
    if (!published) return "No published proposal";
    return `${published.development_fixture ? "DEVELOPMENT FIXTURE" : "PROPOSED LAYOUT"} · revision ${published.revision}${stale ? " · stale inputs" : ""}`;
  }
  function removeProposal() {
    published = null; layer?.remove(); layer = null;
    show.checked = false; show.disabled = true;
    $("proposal-review").hidden = true;
    $("proposal-stale").hidden = true;
    $("revise-proposal-fixture").disabled = true;
    $("proposal-map-caption").textContent = caption();
  }
  function clear(event) {
    controller?.abort(); ++request;
    selected = event.siteId ? event : null;
    comparison = null; realRevision = 0;
    removeProposal();
    $("traffic-comparison").hidden = true;
    $("water-comparison").hidden = true;
    $("comparison-stale").hidden = true;
    $("proposal-result-message").hidden = true;
    $("load-proposal-fixture").disabled = !selected;
    $("proposal-message").textContent = selected ? "Preview uses synthetic geometry, never live results." : "Select a site to test the proposal overlay.";
  }
  function identity(value, site, revision) {
    return value?.site_id === site.siteId && value.workflow === site.workflow && value.revision === revision &&
      value.input_revision === site.inputRevision && typeof value.input_hash === "string" && value.input_hash.length > 0;
  }
  function validate(p, site, revision, fixture) {
    if (p.schema_version !== 1 || p.development_fixture !== fixture || !identity(p, site, revision)) throw new Error("Proposal identity mismatch.");
    if (!Array.isArray(p.geometry) || !p.geometry.length || !Array.isArray(p.metrics) || !p.metrics.length ||
        p.geometry.some(g => g.properties?.revision !== revision) ||
        p.metrics.some(m => m.revision !== revision || m.input_hash !== p.input_hash)) throw new Error("Proposal revision mismatch.");
    const area = p.metrics.find(m => m.id === "footprint_area");
    if (!area || !finite(area.proposed)) throw new Error("Missing footprint measurement.");
    return area;
  }
  function prepareLayer(p, site) {
    const fixture = p.development_fixture;
    return L.geoJSON({type:"FeatureCollection",features:p.geometry}, {
      pane:"proposal", interactive:false,
      style:fixture ? {color:"#e0c4ff",weight:3,dashArray:"7 4",fillColor:"#b388ff",fillOpacity:.42}
        : site.workflow === "water" ? feature => feature.properties?.role === "contributing"
          ? {color:"#78dbee",weight:2,dashArray:"5 4",fillColor:"#78dbee",fillOpacity:.12}
          : {color:"#ade7a4",weight:3,fillColor:"#80cf91",fillOpacity:.4}
        : {color:"#ffdc83",weight:3,fillColor:"#e4ad39",fillOpacity:.5},
    });
  }
  function publish(p, area, site, replacement = prepareLayer(p, site)) {
    const fixture = p.development_fixture;
    // Publish geometry, measurements and identity together after validation.
    layer?.remove(); layer = replacement; published = p;
    show.disabled = false; show.checked = true; visible();
    $("proposal-review").hidden = false;
    $("proposal-review").setAttribute("data-fixture", String(fixture));
    $("proposal-kind").textContent = fixture ? "DEVELOPMENT FIXTURE" : site.workflow === "water" ? "CONDITIONAL TREATMENT · SCREENING" : "EVALUATED PROPOSAL · SIMULATED";
    $("proposal-title").textContent = fixture ? (site.workflow === "street" ? "Test island footprint" : "Test treatment footprint") : label(p.geometry[0]?.properties?.layout ?? (site.workflow === "water" ? "Conditional treatment" : "Recommended lane reallocation"));
    $("proposal-summary").textContent = p.recommendation;
    $("proposal-area-label").textContent = fixture ? "Test footprint" : site.workflow === "water" ? "Proposed treatment area" : "Measured footprint";
    $("proposal-area").textContent = `${area.proposed.toFixed(1)} ${area.unit}`;
    $("proposal-impact").textContent = fixture ? "Unassessed" : "See comparison below";
    $("proposal-checks").replaceChildren();
    if (!fixture) for (const [name, check] of [["Access",p.access],["Overlap",p.overlap]]) {
      $("proposal-checks").append(element("p", `${name}: ${check?.text ?? "Not assessed"}`));
    }
    $("proposal-revision").textContent = `Revision ${p.revision} · inputs ${p.input_revision} · ${p.input_hash.slice(0,8)}`;
    $("proposal-map-caption").textContent = caption();
    $("proposal-stale").hidden = true;
    $("revise-proposal-fixture").disabled = !fixture;
  }
  const metrics = [
    ["Total CO₂", "kg / demand hour", r => r.co2_kg_per_hour],
    ["CO₂ per completed vehicle", "g / vehicle", r => r.co2_g_per_completed_vehicle],
    ["NOₓ", "g / demand hour", r => r.nox_g_per_hour],
    ["Mean delay", "s / vehicle", r => r.mean_delay_s],
    ["Demand completed", "%", r => finite(r.completion_share) ? r.completion_share * 100 : null],
    ["Unable to enter", "%", r => finite(r.unable_to_enter_share) ? r.unable_to_enter_share * 100 : null],
    ["Maximum approach queue", "m", r => maximum(r.max_queue_m)],
    ["Maximum approach hourly noise", "dB(A)", r => maximum(r.max_noise_db)],
  ];
  function renderWaterComparison(c) {
    $("traffic-comparison").hidden = true;
    $("water-comparison").hidden = false;
    const names = Object.keys(c.results ?? {}).filter(name => name !== "baseline"), winner = c.ranking?.recommended;
    $("water-comparison-title").textContent = winner ? "A conditional treatment option" : "No treatment recommended";
    $("water-comparison-outcome").textContent = c.ranking?.reason || (winner ? `${label(winner)} ranks highest under the confirmed screening inputs.` : "The available evidence does not support a recommendation.");
    $("water-comparison-rainfall").textContent = `${c.rainfall?.label ?? "Rainfall event unavailable"} · ${number(c.rainfall?.inches,"in")} · ${c.rainfall?.basis ?? "source unavailable"}`;
    $("water-comparison-stale").hidden = true;
    $("water-comparison-revision").textContent = `Revision ${c.revision} · inputs ${c.input_revision} · ${c.input_hash.slice(0,8)}`;
    const table = element("table"), head = element("thead"), heading = element("tr");
    for (const name of ["Metric","baseline",...names]) {
      const cell = element("th",name === "baseline" ? "No added treatment" : name === "Metric" ? name : label(name));
      cell.setAttribute("scope","col"); if(name === winner) cell.className = "recommended-column"; heading.append(cell);
    }
    head.append(heading); table.append(head);
    const body = element("tbody");
    for (const [key,title,unit] of [["runoff_m3","Contributing runoff","m³"],["captured_m3","Temporarily stored runoff","m³"],
      ["excess_m3","Excess contributing runoff","m³"],["capacity_m3","Added storage capacity","m³"],
      ["direct_rain_m3","Rain onto treatment","m³"],["direct_excess_m3","Excess direct rain","m³"],["footprint_m2","Treatment footprint","m²"]]) {
      const row = element("tr"), titleCell = element("th",title); titleCell.setAttribute("scope","row"); titleCell.append(element("small",unit)); row.append(titleCell);
      for (const name of ["baseline",...names]) { const cell = element("td",number(c.results[name]?.[key],"",2)); if(name === winner) cell.className="recommended-column"; row.append(cell); }
      body.append(row);
    }
    table.append(body); $("water-comparison-table").replaceChildren(table);
    $("water-comparison-chart").replaceChildren();
    for (const name of names) {
      const values = c.results[name], row = element("div"); row.className="water-volume-row";
      row.append(element("strong",label(name)));
      const totals = `Stored ${number(values.captured_m3,"m³",2)} · excess ${number(values.excess_m3,"m³",2)}`;
      const bar = element("div"); bar.className="water-volume-bar"; bar.setAttribute("role","img"); bar.setAttribute("aria-label",`${label(name)}: ${totals}`);
      if(finite(values.runoff_m3) && values.runoff_m3 > 0 && finite(values.captured_m3) && finite(values.excess_m3)) {
        for(const [key,klass] of [["captured_m3","stored"],["excess_m3","excess"]]) { const segment=element("span"); segment.className=klass; segment.setAttribute("style",`width:${Math.max(0,Math.min(100,values[key]/values.runoff_m3*100))}%`); bar.append(segment); }
      }
      row.append(bar,element("small",totals)); $("water-comparison-chart").append(row);
    }
    $("water-comparison-alternatives").replaceChildren();
    for (const name of names) {
      const card=element("details"), summary=element("summary",label(name)), verdict=c.ranking?.verdicts?.[name] ?? {};
      summary.append(element("span",name === winner ? "Conditional choice" : verdict.eligible ? "Not selected" : "Not eligible")); card.append(summary);
      for(const reason of [...(verdict.ineligible_reasons ?? []),...(verdict.tradeoffs ?? [])]) card.append(element("p",reason));
      if(c.descriptions?.[name]) card.append(element("p",c.descriptions[name]));
      for(const [key,value] of Object.entries(c.checks?.[name] ?? {})) {
        if(value === null || ["boolean","number","string"].includes(typeof value)) {
          const areaKey=key.endsWith("_m2"), title=label(areaKey ? key.slice(0,-3) : key);
          card.append(element("p",`${title}: ${typeof value === "boolean" ? value ? "Yes" : "No" : typeof value === "string" ? value : number(value,areaKey ? "m²" : "",2)}`));
        }
      }
      const terrain=c.checks?.[name]?.terrain;
      if(terrain) {
        card.append(element("p",`Terrain screening: ${terrain.status ?? "Not assessed"}. Median slope ${number(terrain.median_slope_percent,"%",2)}; maximum slope ${number(terrain.max_slope_percent,"%",2)}; relief ${number(terrain.relief_m,"m",2)}.`));
        if(terrain.source) {
          const origin=terrain.source;
          card.append(element("p",`Terrain source: ${typeof origin === "string" ? origin : origin.label ?? origin.provider ?? "Local elevation dataset"}. Publication: ${origin.publication_date ?? "unknown"}; acquisition: ${origin.observed_at ?? "unknown"}.`));
          if(typeof origin.url === "string" && /^https?:\/\//i.test(origin.url)) {const link=element("a","Open terrain source ↗");link.href=origin.url;link.target="_blank";link.rel="noopener noreferrer";card.append(link);}
        }
        if(terrain.reason) card.append(element("p",terrain.reason));
        for(const note of terrain.limitations ?? []) card.append(element("p",note));
      } else card.append(element("p","Terrain at this treatment: not assessed. Mapped terrain does not establish a drainage connection."));
      $("water-comparison-alternatives").append(card);
    }
    $("water-comparison-method").textContent = c.method ?? "Contributing runoff = rainfall × contributing area × runoff coefficient. Storage = treatment area × proposed depth. Direct rainfall uses storage first.";
    $("water-comparison-sources").replaceChildren();
    $("water-comparison-sources").append(element("p",`Contributing area: ${number(c.contributing_area_m2,"m²",2)}. Proposed storage depth: ${number(c.design?.storage_depth_m,"m",3)}. Planner runoff coefficient: ${number(c.design?.runoff_coefficient,"",3)}.`));
    if(c.confirmations?.confirmation_note) $("water-comparison-sources").append(element("p",`Planner input basis: ${c.confirmations.confirmation_note}`));
    for (const item of c.sources ?? []) {
      const title = typeof item === "string" ? item : item.label ?? item.provider ?? item.title ?? "Source";
      const url = typeof item === "object" ? item.url : null;
      const row=element("p"), link=element(typeof url === "string" && /^https?:\/\//i.test(url) ? "a" : "span",title);
      if(link.tagName === "A" || (typeof url === "string" && /^https?:\/\//i.test(url))) {link.href=url;link.target="_blank";link.rel="noopener noreferrer";} row.append(link);
      if(typeof item === "object") row.append(element("small",` · Observed: ${item.observed_at ?? "not recorded"}${item.retrieved_at ? ` · Retrieved: ${item.retrieved_at}` : ""}${item.basis ? ` · ${item.basis}` : ""}`));
      $("water-comparison-sources").append(row);
    }
    $("water-comparison-assumptions").replaceChildren();
    for(const assumption of c.assumptions ?? []) $("water-comparison-assumptions").append(element("li",typeof assumption === "string" ? assumption : assumption.text ?? JSON.stringify(assumption)));
  }
  function renderComparison(c) {
    $("water-comparison").hidden = true;
    const names = Object.keys(c.results ?? {}).filter(name => name !== "baseline");
    const recommended = c.ranking?.recommended;
    $("traffic-comparison").hidden = false;
    $("comparison-title").textContent = recommended ? "A layout meets the comparison rules" : "No layout recommended";
    $("comparison-outcome").textContent = c.ranking?.reason ?? (recommended ? `${label(recommended)} is the recommended option under these simulation inputs.` : "None of the tested layouts met the recommendation rules.");
    $("comparison-period").textContent = `LADOT count: ${c.count_date ?? "date unavailable"} · ${c.peak_hour ?? c.period ?? "period unavailable"}`;
    $("comparison-stale").hidden = true;
    $("comparison-revision").textContent = `Revision ${c.revision} · inputs ${c.input_revision} · ${c.input_hash.slice(0,8)}`;
    const table = element("table"), head = element("thead"), heading = element("tr");
    const corner = element("th", "Metric"); corner.setAttribute("scope", "col"); heading.append(corner);
    for (const name of ["baseline", ...names]) {
      const cell = element("th", name === "baseline" ? "Baseline" : label(name));
      cell.setAttribute("scope", "col"); if (name === recommended) cell.className = "recommended-column";
      heading.append(cell);
    }
    head.append(heading); table.append(head);
    const body = element("tbody");
    for (const [title, unit, get] of metrics) {
      const row = element("tr"), titleCell = element("th", title);
      titleCell.setAttribute("scope", "row"); titleCell.append(element("small", unit)); row.append(titleCell);
      for (const name of ["baseline", ...names]) {
        const cell = element("td", number(get(c.results?.[name] ?? {})));
        if (name === recommended) cell.className = "recommended-column";
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body); $("comparison-table").replaceChildren(table);
    $("comparison-alternatives").replaceChildren();
    for (const name of names) {
      const verdict = c.ranking?.verdicts?.[name] ?? {}, check = c.checks?.[name] ?? {};
      const card = element("details"), summary = element("summary", label(name));
      const status = element("span", name === recommended ? "Recommended" : verdict.eligible === true ? "Eligible, not selected" : verdict.eligible === false ? "Not eligible" : "Not assessed");
      status.className = "comparison-verdict"; summary.append(status); card.append(summary);
      if (c.descriptions?.[name]) card.append(element("p", c.descriptions[name]));
      const reasons = [...(verdict.ineligible_reasons ?? []), ...(verdict.tradeoffs ?? [])];
      if (reasons.length) {
        const list = element("ul"); for (const reason of reasons) list.append(element("li", reason)); card.append(list);
      }
      card.append(element("p", `Parcel overlap: ${number(check.parcel_overlap_m2, "m²")}. Building overlap: ${number(check.building_overlap_m2, "m²")}.`));
      card.append(element("p", `Mapped access conflicts: ${number(check.access_conflicts, "", 0)}. Keep-clear conflict: ${check.keep_clear_conflict === true ? "Yes" : check.keep_clear_conflict === false ? "No" : "Not assessed"}.`));
      const detectionStatus = {ready:"Available", empty:"No candidates returned", unavailable:"Unavailable"}[check.detection_status] ?? "Not assessed";
      card.append(element("p", `Crossing/driveway detection: ${detectionStatus}. Overlapping crosswalk candidates: ${number(check.candidate_crosswalk_overlaps, "", 0)}. Driveway candidates: ${number(check.candidate_driveway_overlaps, "", 0)}.`));
      card.append(element("p", "Detection candidates require field verification; an empty response does not confirm that a crossing or driveway is absent."));
      card.append(element("p", "Mapped checks do not establish ownership, access approval or construction feasibility."));
      $("comparison-alternatives").append(card);
    }
    $("comparison-sources").replaceChildren();
    if (typeof c.sheet_url === "string" && /^https?:\/\//i.test(c.sheet_url)) {
      const link = element("a", "Open official LADOT count sheet ↗"); link.href = c.sheet_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      $("comparison-sources").append(link);
    }
    $("comparison-assumptions").replaceChildren();
    for (const assumption of c.assumptions ?? []) $("comparison-assumptions").append(element("li", typeof assumption === "string" ? assumption : assumption.text ?? assumption.description ?? JSON.stringify(assumption)));
    if (!c.assumptions?.length) $("comparison-assumptions").append(element("li", "No assumption details were supplied. Review source evidence before relying on this comparison."));
  }
  function receive(event) {
    if (!selected || event.siteId !== selected.siteId || event.workflow !== selected.workflow ||
        event.inputRevision !== selected.inputRevision || !Number.isInteger(event.revision) || event.revision <= realRevision) return;
    const p = event.proposal, c = event.comparison;
    try {
      if (!c || !identity(c, selected, event.revision) || !c.ranking) throw new Error("Comparison identity mismatch.");
      if (c.status === "unavailable") {
        if (p) throw new Error("An unavailable comparison cannot publish a proposal.");
        controller?.abort(); ++request; realRevision = event.revision;
        $("proposal-result-message").hidden = false;
        $("proposal-result-message").textContent = `Comparison unavailable: ${c.ranking.reason ?? "Required evidence or simulation results could not be obtained."}${published || comparison ? " The previous result is preserved below; it has not been updated." : ""}`;
        if (published) $("proposal-map-caption").textContent = `${caption(published.input_revision !== selected.inputRevision)} · previous result`;
        $("load-proposal-fixture").disabled = false;
        $("revise-proposal-fixture").disabled = !published?.development_fixture;
        return;
      }
      if (!c.results?.baseline) throw new Error("Comparison metrics are missing.");
      const area = p ? validate(p, selected, event.revision, false) : null;
      if (p && (p.input_hash !== c.input_hash || !c.ranking.recommended ||
          p.geometry.some(g => g.properties.layout !== c.ranking.recommended))) throw new Error("Proposal and comparison mismatch.");
      if (!p && c.ranking.recommended) throw new Error("Recommended proposal is missing.");
      // Leaflet validates/builds the geometry before any new metrics or revision
      // are installed; a rejected shape must not mix new figures with an old map.
      const replacement = p ? prepareLayer(p, selected) : null;
      controller?.abort(); ++request;
      $("proposal-result-message").hidden = true;
      if(c.workflow === "water") renderWaterComparison(c); else renderComparison(c);
      if (p) publish(p, area, selected, replacement); else removeProposal();
      realRevision = event.revision; comparison = c;
      $("load-proposal-fixture").disabled = false;
      $("proposal-message").textContent = "Development preview replaces the map with a clearly labeled synthetic UI fixture.";
    } catch (error) {
      $("proposal-message").textContent = `Design result unavailable: ${error.message}`;
      $("proposal-result-message").hidden = false;
      $("proposal-result-message").textContent = `Design result could not be displayed: ${error.message} The previous result has not been replaced.`;
    }
  }
  async function preview() {
    if (!selected) return;
    controller?.abort(); controller = new AbortController();
    const token = ++request, site = {...selected}, revision = (published?.revision ?? 0) + 1;
    $("proposal-message").textContent = "Preparing local UI fixture…";
    $("load-proposal-fixture").disabled = $("revise-proposal-fixture").disabled = true;
    try {
      const query = new URLSearchParams({lon:site.center.lng,lat:site.center.lat,workflow:site.workflow,site_id:site.siteId,revision,input_revision:site.inputRevision});
      const p = await json(`/api/proposal-fixture?${query}`, {signal:controller.signal});
      if (token !== request) return;
      const area = validate(p, site, revision, true);
      publish(p, area, site);
      comparison = null; $("traffic-comparison").hidden = true; $("water-comparison").hidden = true;
      map.setView(site.center, Math.max(map.getZoom(), 19), {animate:false});
      $("proposal-message").textContent = "Purple dashed outline = UI fixture. Access, overlap and benefits remain unassessed.";
    } catch (error) {
      if (token === request && error.name !== "AbortError") $("proposal-message").textContent = `Preview unavailable: ${error.message}`;
    } finally {
      if (token === request) { $("load-proposal-fixture").disabled = !selected; $("revise-proposal-fixture").disabled = !published?.development_fixture; }
    }
  }
  show.addEventListener("change", visible);
  $("load-proposal-fixture").addEventListener("click", preview);
  $("revise-proposal-fixture").addEventListener("click", preview);
  map.on("plannersite", clear);
  map.on("plannerresult", receive);
  map.on("plannerinputs", ({inputRevision}) => {
    if (!selected) return;
    selected = {...selected,inputRevision}; controller?.abort(); ++request;
    $("load-proposal-fixture").disabled = false;
    $("revise-proposal-fixture").disabled = !published?.development_fixture;
    if (published) { $("proposal-stale").hidden = false; $("proposal-map-caption").textContent = caption(true); }
    if (comparison) $(comparison.workflow === "water" ? "water-comparison-stale" : "comparison-stale").hidden = false;
  });
})();
