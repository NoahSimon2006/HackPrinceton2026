/* Render revision-bound proposals and preserve earlier results on source failure. */
(() => {
  map.createPane("proposal");
  map.getPane("proposal").style.zIndex = 610;
  map.getPane("proposal").style.pointerEvents = "none";
  let selected = null, published = null, comparison = null, layer = null, request = 0, controller;
  let realRevision = 0;
  const show = $("show-proposal");
  const statuses = {fixture:"Development fixture", draft:"Draft concept", conditional:"Conditional treatment", recommended:"Recommended",
    tested:"Tested, eligible", rejected:"Tested, rejected"};
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
    return `${statuses[published.status]} · revision ${published.revision}${stale ? " · stale inputs" : ""}`;
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
    const allowed = fixture ? ["fixture"] : site.workflow === "water" ? ["draft"] : ["recommended","tested","rejected"];
    if (!allowed.includes(p.status)) throw new Error("Proposal status mismatch.");
    if (!Array.isArray(p.geometry) || !p.geometry.length || !Array.isArray(p.metrics) || !p.metrics.length ||
        p.geometry.some(g => g.properties?.revision !== revision) ||
        p.metrics.some(m => m.revision !== revision || m.input_hash !== p.input_hash)) throw new Error("Proposal revision mismatch.");
    const area = p.metrics.find(m => m.id === "footprint_area");
    if (!area || !finite(area.proposed)) throw new Error("Missing footprint measurement.");
    return area;
  }
  function prepareLayer(p) {
    const fixture = p.development_fixture;
    return L.geoJSON({type:"FeatureCollection",features:p.geometry}, {
      pane:"proposal", interactive:false,
      style:fixture ? {color:"#e0c4ff",weight:3,dashArray:"7 4",fillColor:"#b388ff",fillOpacity:.42}
        : p.status === "draft" ? {color:"#91ebbd",weight:3,dashArray:"5 3",fillColor:"#5bd58f",fillOpacity:.6}
        : p.status === "conditional" ? feature => feature.properties?.role === "contributing"
          ? {color:"#78dbee",weight:2,dashArray:"5 4",fillColor:"#78dbee",fillOpacity:.12}
          : {color:"#ade7a4",weight:3,fillColor:"#80cf91",fillOpacity:.4}
        : p.status === "rejected" ? {color:"#ffaf98",weight:3,dashArray:"6 4",fillColor:"#db7358",fillOpacity:.45}
        : {color:"#ffdc83",weight:3,fillColor:"#e4ad39",fillOpacity:.5},
    });
  }
  function publish(p, area, site, replacement = prepareLayer(p)) {
    const fixture = p.development_fixture, draft = p.status === "draft";
    // Publish geometry, measurements and identity together after validation.
    layer?.remove(); layer = replacement; published = p;
    show.disabled = false; show.checked = true; visible();
    $("proposal-review").hidden = false;
    $("proposal-review").setAttribute("data-fixture", String(fixture));
    $("proposal-review").setAttribute("data-status", p.status);
    $("proposal-kind").textContent = statuses[p.status];
    $("proposal-title").textContent = fixture ? (site.workflow === "street" ? "Test island footprint" : "Test treatment footprint")
      : draft ? "Rain garden" : label(p.geometry[0].properties.layout);
    $("proposal-summary").textContent = p.recommendation;
    $("proposal-area-label").textContent = "Footprint";
    $("proposal-area").textContent = `${area.proposed.toFixed(1)} ${area.unit}`;
    $("proposal-impact").textContent = fixture ? "Unassessed" : draft ? "Screening estimate" : "Simulated · see comparison";
    $("proposal-water-metrics").hidden = !draft;
    $("proposal-water-metrics").replaceChildren();
    if (draft) for (const [id, title] of [["storage_volume","Ponding storage"],["direct_rain_volume","Rain onto garden"],
      ["runoff_volume","Contributing runoff"],["captured_volume","Capture"],["overflow_volume","Excess contributing runoff"],
      ["direct_overflow_volume","Excess direct rain"]]) {
      const metric = p.metrics.find(m => m.id === id);
      $("proposal-water-metrics").append(element("dt", title), element("dd", number(metric?.proposed, metric?.unit, 3)));
    }
    $("proposal-assumptions").hidden = !draft;
    $("proposal-assumptions").replaceChildren(...(draft ? p.assumptions.map(text => element("li", text)) : []));
    $("proposal-checks").replaceChildren();
    if (!fixture) for (const [name, check] of [["Access",p.access],["Overlap",p.overlap]]) {
      $("proposal-checks").append(element("p", `${name}: ${check?.text ?? "Not assessed"}`));
    }
    $("proposal-revision").textContent = `Revision ${p.revision} · inputs ${p.input_revision} · ${p.input_hash.slice(0,8)}`;
    const stale = p.input_revision !== site.inputRevision;
    $("proposal-map-caption").textContent = caption(stale);
    $("proposal-stale").hidden = !stale;
    $("revise-proposal-fixture").disabled = !fixture;
  }
  function focus() {
    const bounds = layer?.getBounds?.();
    if (bounds?.isValid()) map.fitBounds(bounds, {maxZoom:20, padding:[60,60]});
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
  function renderComparison(c, alternatives) {
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
      const [proposal, area, replacement] = alternatives[name];
      const status = element("span", statuses[proposal.status]);
      status.className = "comparison-verdict"; summary.append(status); card.append(summary);
      if (c.descriptions?.[name]) card.append(element("p", c.descriptions[name]));
      const inspect = element("button", "Show footprint on map");
      inspect.type = "button";
      inspect.addEventListener("click", () => {
        if (comparison !== c) return;
        publish(proposal, area, selected, replacement);
        focus();
      });
      card.append(inspect);
      const reasons = [...(verdict.ineligible_reasons ?? []), ...(verdict.tradeoffs ?? [])];
      if (reasons.length) {
        const list = element("ul"); for (const reason of reasons) list.append(element("li", reason)); card.append(list);
      }
      card.append(element("p", `Parcel overlap: ${number(check.parcel_overlap_m2, "m²")}. Building overlap: ${number(check.building_overlap_m2, "m²")}.`));
      if (finite(check.overlapping_costar_records)) card.append(element("p", `CoStar records located within touched mapped parcels: ${check.overlapping_costar_records}.`));
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
      if (selected.workflow === "water" && !c) {
        if (p && (p.status !== "draft" || event.draftQuestion)) throw new Error("Stormwater draft mismatch.");
        const area = p ? validate(p, selected, event.revision, false) : null;
        const replacement = p ? prepareLayer(p) : null;
        controller?.abort(); ++request;
        comparison = null; realRevision = event.revision;
        $("proposal-result-message").hidden = Boolean(p);
        if (p) {
          publish(p, area, selected, replacement);
          focus();
        } else {
          removeProposal();
          $("proposal-result-message").textContent = event.draftQuestion ?? "No draft is available for this revision.";
        }
        $("load-proposal-fixture").disabled = false;
        return;
      }
      if (!c || !identity(c, selected, event.revision) || !c.ranking) throw new Error("Comparison identity mismatch.");
      if (c.workflow === "street" && c.status === "unavailable") {
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
      if (c.workflow !== "street") throw new Error("Only traffic comparisons are supported. Analyze the site for a stormwater draft.");
      {
        const names = Object.keys(c.results).filter(name => name !== "baseline");
        if (!names.length) throw new Error("Tested layouts are missing.");
        const alternatives = Object.fromEntries(names.map(name => {
          const layout = event.alternatives?.[name], verdict = c.ranking.verdicts[name];
          const expected = name === c.ranking.recommended ? "recommended" : verdict?.eligible ? "tested" : "rejected";
          const area = layout && validate(layout, selected, event.revision, false);
          if (!area || !verdict || layout.status !== expected || layout.input_hash !== c.input_hash ||
              layout.geometry.some(g => g.properties.layout !== name)) throw new Error("Tested layout and comparison mismatch.");
          return [name, [layout, area, prepareLayer(layout)]];
        }));
        const winner = alternatives[c.ranking.recommended];
        if ((Boolean(winner) !== Boolean(p)) || (winner &&
            (!c.ranking.verdicts[c.ranking.recommended].eligible || JSON.stringify(winner[0]) !== JSON.stringify(p))))
          throw new Error("Recommended proposal and comparison mismatch.");
        controller?.abort(); ++request;
        renderComparison(c, alternatives);
        if (winner) {
          const [proposal, area, replacement] = winner;
          publish(proposal, area, selected, replacement);
        } else removeProposal();
      }
      realRevision = event.revision; comparison = c;
      $("proposal-result-message").hidden = true;
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
      comparison = null; $("traffic-comparison").hidden = true;
      map.setView(site.center, Math.max(map.getZoom(), 19), {animate:false});
      $("proposal-message").textContent = "Purple dashed outline = UI fixture. Access, overlap and benefits remain unassessed.";
    } catch (error) {
      if (token === request && error.name !== "AbortError") $("proposal-message").textContent = `Preview unavailable: ${error.message}`;
    } finally {
      if (token === request) { $("load-proposal-fixture").disabled = !selected; $("revise-proposal-fixture").disabled = !published?.development_fixture; }
    }
  }
  show.addEventListener("change", visible);
  $("focus-proposal").addEventListener("click", () => { show.checked = true; visible(); focus(); });
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
    if (comparison) $("comparison-stale").hidden = false;
  });
})();
