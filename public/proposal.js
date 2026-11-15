/* Render revision-bound proposals and preserve earlier results on source failure. */
(() => {
  map.createPane("proposal");
  map.getPane("proposal").style.zIndex = 610;
  map.getPane("proposal").style.pointerEvents = "none";
  const plantingRenderer = L.svg({pane:"proposal"});
  let selected = null, published = null, comparison = null, layer = null, request = 0, controller;
  let realRevision = 0;
  let currentWater = null, currentTraffic = null, hasRoadConcept = false;
  let sourceInspectButtons = [];
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
  const approximate = value => value.toLocaleString(undefined, {maximumSignificantDigits:2});
  function savedNotice(study) {
    if(!study?.restored && !study?.savedAt)return '';
    const timestamp=typeof study.savedAt==='string'?Date.parse(study.savedAt):NaN;
    const publication=Number.isFinite(timestamp)
      ? `published ${new Date(timestamp).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,' UTC')}`
      : 'original publication time unavailable';
    return `Saved result · ${publication}. Historical evaluation; reopening does not rerun it. Source observation dates are separate.`;
  }
  function visible() {
    if (!layer) return;
    if (show.checked) layer.addTo(map); else layer.remove();
  }
  function caption(stale = false) {
    if (!published) return "No published proposal";
    const kind = ["draft","conditional"].includes(published.status) ? "Rain garden concept" : statuses[published.status];
    return `${kind} · revision ${published.revision}${stale ? " · stale inputs" : ""}`;
  }
  function removeProposal() {
    map.fire("proposaldisplay", {proposal:null});
    published = null; layer?.remove(); layer = null;
    $("proposal-identity").textContent = "";
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
    currentWater = null; currentTraffic = null; hasRoadConcept = false;
    sourceInspectButtons = [];
    removeProposal();
    $("traffic-comparison").hidden = true;
    $("comparison-identity").textContent = "";
    $("water-design-review").hidden = true;
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
    const allowed = fixture ? ["fixture"] : site.workflow === "water" ? ["draft","conditional"] : ["recommended","tested","rejected"];
    if (!allowed.includes(p.status)) throw new Error("Proposal status mismatch.");
    if (!Array.isArray(p.geometry) || !p.geometry.length || !Array.isArray(p.metrics) || !p.metrics.length ||
        p.geometry.some(g => g.properties?.revision !== revision) ||
        p.metrics.some(m => m.revision !== revision || m.input_hash !== p.input_hash)) throw new Error("Proposal revision mismatch.");
    const area = p.metrics.find(m => m.id === "footprint_area");
    if (!area || !finite(area.proposed)) throw new Error("Missing footprint measurement.");
    return area;
  }
  function prepareLayer(p) {
    const collection = {type:"FeatureCollection",features:p.geometry};
    if (!p.development_fixture && p.workflow === "water" && p.status !== "rejected") {
      const planted = new Set(p.proposed_geometry_ids);
      return L.geoJSON(collection, {
        pane:"proposal", renderer:plantingRenderer, interactive:false,
        style:feature => planted.has(feature.id)
          ? {className:"rain-garden-footprint",color:"#b5efaa",weight:3,fillColor:"#38754c",fillOpacity:.82,
            dashArray:p.status === "draft" ? "5 3" : null}
          : {color:"#78dbee",weight:2,dashArray:"5 4",fillColor:"#78dbee",fillOpacity:.12},
      });
    }
    const fixture = p.development_fixture;
    return L.geoJSON(collection, {
      pane:"proposal", interactive:false,
      style:fixture ? {color:"#e0c4ff",weight:3,dashArray:"7 4",fillColor:"#b388ff",fillOpacity:.42}
        : p.status === "rejected" ? {color:"#ffaf98",weight:3,dashArray:"6 4",fillColor:"#db7358",fillOpacity:.45}
        : {color:"#ffdc83",weight:3,fillColor:"#e4ad39",fillOpacity:.5},
    });
  }
  function publish(p, area, site, replacement = prepareLayer(p), study = null) {
    const fixture = p.development_fixture, draft = !fixture && site.workflow === 'water';
    const rejected = study?.displayStatus === 'rejected';
    // Publish geometry, measurements and identity together after validation.
    layer?.remove(); layer = replacement; published = p;
    show.disabled = false; show.checked = true; visible();
    $("proposal-review").hidden = false;
    $("proposal-review").setAttribute("data-fixture", String(fixture));
    $("proposal-review").setAttribute("data-status", p.status);
    $("proposal-review").setAttribute("data-stormwater", String(draft));
    $("proposal-kind").textContent = draft ? (study?.restored ? "Saved concept" : "Concept") : statuses[p.status];
    const layout = p.geometry.find(feature => p.proposed_geometry_ids?.includes(feature.id))?.properties?.layout;
    $("proposal-title").textContent = fixture ? (site.workflow === "street" ? "Test island footprint" : "Test treatment footprint")
      : draft ? ({compact:"Compact rain garden",linear:"Linear rain garden"}[layout] || "Rain garden") : label(p.geometry[0].properties.layout);
    $("proposal-summary").textContent = p.recommendation;
    $("proposal-summary").hidden = draft && !rejected;
    $("proposal-overview-metrics").hidden = draft;
    $("proposal-calculation").open = !draft;
    $("proposal-calculation-label").hidden = !draft;
    $("proposal-water-rationale").hidden = !draft;
    $("proposal-water-rationale").textContent = draft ? p.recommendation : "";
    $("proposal-area-label").textContent = "Footprint";
    $("proposal-area").textContent = `${area.proposed.toFixed(1)} ${area.unit}`;
    $("proposal-impact").textContent = fixture ? "Unassessed" : "Simulated · see comparison";
    const highlights = $("water-design-highlights");
    highlights.hidden = !draft;
    highlights.replaceChildren();
    const runoff = $("water-design-runoff");
    runoff.hidden = !draft || rejected;
    runoff.textContent = "";
    if (draft) {
      const storage = p.metrics.find(metric => metric.id === "storage_volume")?.proposed;
      highlights.append(
        element("dt","Planted area"),element("dd",`${approximate(area.proposed / .09290304)} sq ft`),
        element("dt","Temporary storage"),element("dd",finite(storage) ? `About ${approximate(storage / .003785411784)} gal` : "Unknown"));
      const capture = p.metrics.find(metric => metric.id === "captured_volume")?.proposed;
      const depth = p.design?.storage_depth_m;
      const connection = finite(capture)
        ? `What-if: the garden could hold about ${approximate(capture / .003785411784)} gal of runoff if the marked area drains into it.`
        : "Runoff capture is unknown.";
      runoff.textContent = finite(depth) && finite(storage)
        ? `${connection} The storage estimate assumes about ${Math.round(depth / .0254)} inches of ponding.` : connection;
    }
    $("proposal-water-metrics").hidden = !draft;
    $("proposal-water-metrics").replaceChildren();
    if (draft) for (const [id, title] of [["footprint_area","Measured footprint"],["storage_volume","Ponding storage"],["direct_rain_volume","Rain onto treatment"],
      ["contributing_area","Marked contributing area (union)"],
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
    $("proposal-revision").textContent = [`Revision ${p.revision}`,savedNotice(study)].filter(Boolean).join('. ');
    // Input identity is kept for traceability under the project details.
    $("proposal-identity").textContent = `Design revision ${p.revision} · inputs ${p.input_revision} · ${p.input_hash.slice(0,8)}`;
    const stale = p.input_revision !== site.inputRevision || Boolean(study?.historicalReference);
    $("proposal-map-caption").textContent = caption(stale);
    $("proposal-stale").hidden = !stale;
    $("revise-proposal-fixture").disabled = !fixture;
    // The 3D view follows this validated, actually displayed footprint, including
    // read-only history and explicitly inspected rejected alternatives.
    map.fire('proposaldisplay',{proposal:p,projectId:study?.projectId,siteId:site.siteId,
      workflow:site.workflow,inputRevision:site.inputRevision,stale,savedAt:study?.savedAt,
      historical:Boolean(study?.historical),displayStatus:study?.displayStatus || p.status,
      viewLabel:study?.viewLabel || (study?.historical?`Earlier revision ${p.revision}`:statuses[p.status])});
  }
  function renderWaterStudy(study, preview='', alternativeEntry=null) {
    const plan=study.waterPlan, c=plan?.comparison ?? {}, p=alternativeEntry?study.alternatives?.[alternativeEntry.id]:study.proposal;
    $('water-design-review').hidden=!plan && !(currentWater?.designHistory?.length);
    $('water-return-current').hidden=!preview;
    $('water-design-stale').hidden=study.inputRevision===selected.inputRevision && !study.historicalReference;
    $('water-design-selection').textContent=alternativeEntry
      ? `Inspecting ${alternativeEntry.label || label(alternativeEntry.id)}: ${alternativeEntry.reason || alternativeEntry.status || 'Alternative footprint.'}`
      : c.selectionBasis || c.reason || (p?'A provisional concept selected from the available mapped space.':'No eligible concept fits the checked constraints.');
    const scenario=plan?.scenario ?? c.scenario ?? {}, settings=plan?.settings ?? {};
    const assumed=(scenario.drainageAssumption ?? settings.drainageAssumption)==='marked_connected';
    const captured=p?.metrics?.find(m=>m.id==='captured_volume');
    const name=scenario.name || scenario.label || scenario.rainfallSource || scenario.source;
    $('water-design-scenario').textContent=[name?`Event: ${name}.`:'Event assumptions are recorded with the footprint.',
      assumed?'What-if: marked runoff areas are assumed connected. Capture is temporary event storage, not verified drainage or flood protection.':
        captured?.status==='calculated'?'Scenario calculation; inspect the stated drainage assumptions before relying on capture.':'Drainage connection is unknown. Runoff capture is not assessed.',
      `Study revision ${study.revision}.`,savedNotice(study),preview].filter(Boolean).join(' ');
    $('water-design-decisions').replaceChildren();
    sourceInspectButtons=[];
    const decisions=alternativeEntry?(alternativeEntry.decisions ?? []):(plan?.decisions ?? []);
    for(const decision of decisions) {
      const text=typeof decision==='string'?decision:[decision.source || decision.provider,decision.decision || decision.text || decision.reason].filter(Boolean).join(': ');
      const item=element('li',text || 'Inspect the sourced siting evidence.');
      if(typeof decision==='object' && (decision.evidence_ids || decision.evidenceIds)?.length)
        item.append(element('small',` Evidence: ${(decision.evidence_ids || decision.evidenceIds).join(', ')}`));
      if(study===currentWater && !study.historicalReference && !alternativeEntry && typeof decision==='object' && (decision.evidence_ids || decision.evidenceIds)?.length) {
        const inspect=element('button','Inspect source evidence');inspect.type='button';
        inspect.addEventListener('click',()=>{
          if(study!==currentWater || study.historicalReference || study.siteId!==selected?.siteId)return;
          map.fire('plannerinspectevidence',{siteId:study.siteId,
            evidenceIds:[...(decision.fact_id?[decision.fact_id]:[]),...(decision.evidence_ids || decision.evidenceIds)]});
        });item.append(inspect);sourceInspectButtons.push(inspect);
      }
      $('water-design-decisions').append(item);
    }
    if(!$('water-design-decisions').children.length) $('water-design-decisions').append(element('li',alternativeEntry
      ? 'No separate decisions were recorded for this option. The selected concept’s decisions do not apply to this preview.'
      : 'No separate decisions were recorded for this revision.'));
    $('water-design-alternatives').replaceChildren();
    const entries=Array.isArray(c.results)?c.results:Object.entries(c.results ?? {}).map(([id,value])=>({id,...value}));
    for(const entry of entries) {
      const card=element('div');card.className='water-alternative';
      const chosen=entry.id===c.selected;
      card.append(element('strong',`${entry.label || label(entry.id)}${chosen?' · selected concept':''}`));
      card.append(element('p',entry.reason || entry.status || 'Inspect the checked alternative.'));
      const alternative=study.alternatives?.[entry.id];
      if(alternative) {
        const inspect=element('button','Inspect this footprint');inspect.type='button';
        inspect.addEventListener('click',()=>{
          if(!currentWater || currentWater.siteId!==selected.siteId || study!==currentWater)return;
          try {
            const ownSite={...selected,inputRevision:study.inputRevision};
            const area=validate(alternative,ownSite,study.revision,false);
            publish(alternative,area,selected,prepareLayer(entry.status==='rejected'?{...alternative,status:'rejected'}:alternative),{...study,displayStatus:entry.status==='rejected'?'rejected':alternative.status,viewLabel:'Study alternative'});focus();
            renderWaterStudy(study,'Alternative footprint · read-only inspection. The saved concept and its constraints are unchanged.',entry);
            $('proposal-kind').textContent=`Study alternative · ${entry.status || 'concept'}`;
            if(entry.status==='rejected') {
              $('proposal-review').setAttribute('data-status','rejected');
              $('proposal-summary').textContent=`Rejected: ${entry.reason || 'This footprint failed the siting checks.'}`;
            }
            $('proposal-map-caption').textContent=`${entry.status==='rejected'?'Rejected alternative':'Alternative'} preview · revision ${study.revision}${study.inputRevision!==selected.inputRevision || study.historicalReference?' · stale inputs':''}`;
            $('water-return-current').hidden=false;
          } catch(error) {$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Alternative unavailable: ${error.message}`;}
        });card.append(inspect);
      }
      $('water-design-alternatives').append(card);
    }
    // An empty disclosure is noise; show it only when there is something to open.
    $('water-design-alternatives-box').hidden=!entries.length;
    $('water-design-history').replaceChildren();
    for(const saved of currentWater?.designHistory ?? []) {
      if(!saved.proposal || saved.revision>=currentWater.revision)continue;
      const inspect=element('button',`Inspect revision ${saved.revision}`);inspect.type='button';
      inspect.addEventListener('click',()=>{
        if(!currentWater || currentWater.siteId!==selected.siteId)return;
        try {
          const ownSite={...selected,inputRevision:saved.inputRevision ?? saved.proposal.input_revision};
          const area=validate(saved.proposal,ownSite,saved.revision,false);
          const historical={...saved,projectId:currentWater.projectId,inputRevision:ownSite.inputRevision,restored:true,historical:true};
          publish(saved.proposal,area,selected,undefined,historical);focus();
          renderWaterStudy(historical,'Earlier revision · read-only inspection. The current concept is unchanged.');
          $('proposal-kind').textContent=`Earlier revision ${saved.revision} · read only`;
          $('proposal-map-caption').textContent=`Earlier revision ${saved.revision} · read-only preview`;
          // Earlier geometry is an intentional inspection, not a request to
          // rerun the already-current design. Its own metrics remain attached.
          $('proposal-stale').hidden=true;
          $('water-design-stale').hidden=true;
        }catch(error){$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Earlier revision unavailable: ${error.message}`;}
      });$('water-design-history').append(inspect);
    }
    $('water-design-history-box').hidden=!$('water-design-history').children.length;
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
  function trafficAlternatives(study) {
    const c=study.comparison, site={...selected,inputRevision:study.inputRevision};
    if(!c || !identity(c,site,study.revision) || c.workflow!=='street' || !c.ranking)throw new Error('Comparison identity mismatch.');
    if(c.status==='unavailable') {
      if(study.proposal)throw new Error('An unavailable comparison cannot publish a proposal.');
      return {};
    }
    if(!c.results?.baseline)throw new Error('Comparison metrics are missing.');
    const names=Object.keys(c.results).filter(name=>name!=='baseline');
    if(!names.length)throw new Error('Tested layouts are missing.');
    const alternatives=Object.fromEntries(names.map(name=>{
      const layout=study.alternatives?.[name],verdict=c.ranking.verdicts?.[name];
      const expected=name===c.ranking.recommended?'recommended':verdict?.eligible?'tested':'rejected';
      const area=layout && validate(layout,site,study.revision,false);
      if(!area || !verdict || layout.status!==expected || layout.input_hash!==c.input_hash ||
          layout.geometry.some(g=>g.properties.layout!==name))throw new Error('Tested layout and comparison mismatch.');
      return [name,[layout,area,prepareLayer(layout)]];
    }));
    const winner=alternatives[c.ranking.recommended];
    if(Boolean(winner)!==Boolean(study.proposal) || winner &&
        (!c.ranking.verdicts[c.ranking.recommended].eligible || JSON.stringify(winner[0])!==JSON.stringify(study.proposal)))
      throw new Error('Recommended proposal and comparison mismatch.');
    return alternatives;
  }
  function showTrafficEvaluation(study, alternatives, preview=false) {
    const c=study.comparison, winner=alternatives[c.ranking.recommended];
    renderComparison(c,alternatives,study,preview); comparison=c;
    if(winner)publish(...winner.slice(0,2),selected,winner[2],study);else removeProposal();
    if(preview) {
      $('comparison-stale').hidden=true;$('proposal-stale').hidden=true;
      if(published){$('proposal-kind').textContent=`Earlier evaluation ${study.revision} · read only`;
        $('proposal-map-caption').textContent=`Earlier evaluation ${study.revision} · read-only preview`;}
    } else $('comparison-stale').hidden=study.inputRevision===selected.inputRevision && !study.historicalReference;
  }
  function renderTrafficContext(study, preview) {
    const c=study.comparison,plan=study.trafficPlan ?? {},readiness=plan.readiness ?? c.readiness;
    const order=Array.isArray(c.ranking.selection_order)?c.ranking.selection_order.join(' → '):c.ranking.selection_order;
    $('comparison-policy').textContent=`${order || (c.ranking.policy?.startsWith('strict')?'Earlier weighted comparison policy; inspect its recorded assumptions.':'Environmental impact first; feasibility and disruption next.')} Evidence availability is shown separately.`;
    $('comparison-readiness').textContent=typeof readiness==='string'?readiness:
      readiness?.label || readiness?.basis || (c.status==='unavailable'?'Required simulation inputs are incomplete.':
        'Simulation completed under the listed historical inputs. Inspect each layout’s unresolved source and feasibility checks before relying on its result.');
    $('comparison-missing').replaceChildren();
    for(const missing of readiness?.missing ?? [])$('comparison-missing').append(element('li',typeof missing==='string'?missing:missing.label || missing.reason || 'Required evidence remains unavailable.'));
    const revisionText=typeof plan.revisionSummary==='string'?plan.revisionSummary:plan.revisionSummary?.text;
    const notice=savedNotice(study);
    $('comparison-revision-summary').hidden=!preview && !revisionText && !notice;
    $('comparison-revision-summary').textContent=[preview?'Earlier evaluation · read-only inspection. The current project and constraints are unchanged.':'',notice,revisionText].filter(Boolean).join(' ');
    $('traffic-design-decisions').replaceChildren();
    sourceInspectButtons=[];
    for(const decision of plan.sourceDecisions ?? []) {
      const item=element('li',typeof decision==='string'?decision:[decision.source,decision.decision || decision.text].filter(Boolean).join(': '));
      if(decision.evidence_ids?.length)item.append(element('small',` Evidence: ${decision.evidence_ids.join(', ')}`));
      if(!preview && !study.historicalReference && decision.fact_id) {
        const inspect=element('button','Inspect source evidence');inspect.type='button';
        inspect.addEventListener('click',()=>{
          if(study!==currentTraffic || study.historicalReference || study.siteId!==selected?.siteId)return;
          map.fire('plannerinspectevidence',{siteId:study.siteId,evidenceIds:[decision.fact_id,...(decision.evidence_ids ?? [])]});
        });item.append(inspect);sourceInspectButtons.push(inspect);
      }
      $('traffic-design-decisions').append(item);
    }
    if(!$('traffic-design-decisions').children.length)$('traffic-design-decisions').append(element('li','Inspect each layout’s parcel, building, access and crossing checks below. No separate design decisions were recorded.'));
    $('traffic-design-history').replaceChildren();
    for(const saved of currentTraffic?.trafficDesignHistory ?? []) {
      if(!saved.comparison || saved.revision>=currentTraffic.revision)continue;
      const inspect=element('button',`Inspect evaluation ${saved.revision}`);inspect.type='button';
      inspect.addEventListener('click',()=>{
        if(!selected || selected.workflow!=='street' || currentTraffic?.siteId!==selected.siteId)return;
        try {
          const own={...saved,projectId:currentTraffic.projectId,siteId:currentTraffic.siteId,workflow:'street',inputRevision:saved.inputRevision ?? saved.comparison.input_revision,restored:true,historical:true};
          showTrafficEvaluation(own,trafficAlternatives(own),true);
        }catch(error){$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Earlier evaluation unavailable: ${error.message}`;}
      });$('traffic-design-history').append(inspect);
    }
    $('traffic-design-history-box').hidden=!$('traffic-design-history').children.length;
    $('traffic-return-current').hidden=!preview;
  }
  function renderComparison(c, alternatives, study=currentTraffic, preview=false) {
    const names = Object.keys(c.results ?? {}).filter(name => name !== "baseline");
    const recommended = c.ranking?.recommended;
    $("comparison-table").hidden=!names.length;
    $("traffic-comparison").hidden = false;
    $("comparison-title").textContent = c.status==='unavailable'?'Traffic evaluation needs evidence':recommended ? "A layout meets the comparison rules" : "No layout recommended";
    renderTrafficContext(study,preview);
    $("comparison-outcome").textContent = c.ranking?.reason ?? c.ranking?.selection_reason ?? (recommended ? `${label(recommended)} is the recommended option under these simulation inputs.` : "None of the tested layouts met the recommendation rules.");
    $("comparison-period").textContent = `LADOT count: ${c.count_date ?? "date unavailable"} · ${c.peak_hour ?? c.period ?? "period unavailable"}`;
    $("comparison-stale").hidden = true;
    $("comparison-revision").textContent = `Revision ${c.revision}`;
    $("comparison-identity").textContent = `Evaluation revision ${c.revision} · inputs ${c.input_revision} · ${c.input_hash.slice(0,8)} · policy ${c.ranking?.policy || study?.trafficPlan?.policy || 'recorded with this evaluation'}`;
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
      const before=c.results.baseline,after=c.results[name];
      const change=finite(before.co2_kg_per_hour) && before.co2_kg_per_hour>0 && finite(after.co2_kg_per_hour)
        ? 100*(after.co2_kg_per_hour/before.co2_kg_per_hour-1):null;
      const environment=element('p',`Environmental result: ${number(after.co2_kg_per_hour,'kg CO₂ / demand hour')}${finite(change)?` · ${number(Math.abs(change),'%')} ${change<0?'lower':change>0?'higher':'change'} than baseline`:'. Change not assessed'}.`);
      environment.className='comparison-environment';card.append(environment);
      const practical=element('p',`Feasibility & disruption: ${number(after.mean_delay_s,'s / vehicle')} mean delay; ${number(finite(after.completion_share)?after.completion_share*100:null,'%')} of offered demand completed; ${number(maximum(after.max_queue_m),'m')} maximum approach queue.`);
      practical.className='comparison-practical';card.append(practical);
      if(finite(verdict.changes?.queue))card.append(element('p',`Worst individual approach queue change: ${verdict.changes.queue>0?'+':''}${number(verdict.changes.queue*100,'%')} versus that approach’s own baseline. This gate differs from the overall maximum shown in the table.`));
      if(verdict.readiness)card.append(element('p',`Evidence available: ${verdict.readiness.status==='evaluated'?'required checks evaluated':'additional evidence needed'}${verdict.readiness.gaps?.length?`. ${verdict.readiness.gaps.join('; ')}`:''}. This does not increase the environmental rank.`));
      const inspect = element("button", "Show footprint on map");
      inspect.type = "button";
      inspect.addEventListener("click", () => {
        if (comparison !== c) return;
        publish(proposal, area, selected, replacement, study);
        if(preview){$('proposal-kind').textContent=`Earlier evaluation ${study.revision} · ${statuses[proposal.status]}`;
          $('proposal-map-caption').textContent=`Earlier evaluation ${study.revision} · ${statuses[proposal.status]} · read-only preview`;
          $('proposal-stale').hidden=true;}
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
  function suppressUnavailableComparison() {
    if (hasRoadConcept && currentTraffic?.comparison?.status === 'unavailable' && comparison?.status !== 'completed') {
      $('traffic-comparison').hidden = true;
      $('proposal-result-message').hidden = true;
    }
  }
  function receive(event) {
    if (!selected || event.siteId !== selected.siteId || event.workflow !== selected.workflow ||
        event.inputRevision !== selected.inputRevision || !Number.isInteger(event.revision) || event.revision <= realRevision) return;
    const p = event.proposal, c = event.comparison;
    try {
      if (selected.workflow === "water" && !c) {
        if (p && (!["draft","conditional"].includes(p.status) || event.draftQuestion)) throw new Error("Stormwater draft mismatch.");
        const area = p ? validate(p, selected, event.revision, false) : null;
        const waterComparison=event.waterPlan?.comparison;
        if(p && waterComparison?.selected) {
          const chosen=event.alternatives?.[waterComparison.selected];
          const row=(waterComparison.results ?? []).find(item=>item.id===waterComparison.selected);
          if(!chosen || !row || row.status==='rejected' || chosen.input_hash!==p.input_hash ||
              JSON.stringify(chosen.geometry)!==JSON.stringify(p.geometry) || JSON.stringify(chosen.metrics)!==JSON.stringify(p.metrics) ||
              row.inputHash && row.inputHash!==p.input_hash || row.revision && row.revision!==event.revision)
            throw new Error('Stormwater selection and geometry mismatch.');
        }
        const replacement = p ? prepareLayer(p) : null;
        controller?.abort(); ++request;
        comparison = null; realRevision = event.revision;
        currentWater={...event};
        $("proposal-result-message").hidden = Boolean(p);
        if (p) {
          publish(p, area, selected, replacement, currentWater);
          focus();
        } else {
          if(published) {$("proposal-stale").hidden=false;$("proposal-map-caption").textContent=`${caption(true)} · previous result`;}
          $("proposal-result-message").textContent = `${event.draftQuestion ?? "No rain garden was placed."}${published?' The map shows the earlier design.':''}`;
        }
        renderWaterStudy(currentWater);
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
        if(!comparison){currentTraffic={...event};showTrafficEvaluation(currentTraffic,trafficAlternatives(event));}
        suppressUnavailableComparison();
        $("load-proposal-fixture").disabled = false;
        $("revise-proposal-fixture").disabled = !published?.development_fixture;
        return;
      }
      if (!c.results?.baseline) throw new Error("Comparison metrics are missing.");
      if (c.workflow !== "street") throw new Error("Only traffic comparisons are supported. Analyze the site for a stormwater draft.");
      const prepared=trafficAlternatives(event);
      controller?.abort(); ++request;
      currentTraffic={...event};
      showTrafficEvaluation(currentTraffic,prepared);
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
  $('water-return-current').addEventListener('click',()=>{
    if(!currentWater || !selected || currentWater.siteId!==selected.siteId)return;
    if(currentWater.proposal)publish(currentWater.proposal,validate(currentWater.proposal,{...selected,inputRevision:currentWater.inputRevision},currentWater.revision,false),selected,undefined,currentWater);
    else removeProposal();
    renderWaterStudy(currentWater);
  });
  $('traffic-return-current').addEventListener('click',()=>{
    if(!selected || selected.workflow!=='street' || currentTraffic?.siteId!==selected.siteId)return;
    try{showTrafficEvaluation(currentTraffic,trafficAlternatives(currentTraffic));}
    catch(error){$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Current evaluation unavailable: ${error.message}`;}
  });
  map.on("plannersite", clear);
  map.on('roadconceptdisplay', event => {
    hasRoadConcept = Boolean(event.concept);
    if (event.visible) {
      show.checked = false; visible();
    }
    // The concept card explains unassessed performance, including when an
    // existing comparison arrives after a restored or preserved concept.
    suppressUnavailableComparison();
  });
  map.on("plannerresult", receive);
  map.on('plannerinvestigation',event=>{
    if(!selected || event.siteId!==selected.siteId || event.workflow!==selected.workflow ||
      event.inputRevision!==selected.inputRevision || !Number.isInteger(event.revision) || event.revision<=realRevision)return;
    const study=selected.workflow==='water'?currentWater:currentTraffic;
    if(study)study.historicalReference=true;
    // The next run may reuse source IDs with new values. Preserve the displayed
    // footprint/preview, but detach its evidence links before that ledger changes.
    for(const button of sourceInspectButtons){button.hidden=true;button.disabled=true;}
    if(published){$('proposal-stale').hidden=false;$('proposal-map-caption').textContent=caption(true);}
    if(comparison)$('comparison-stale').hidden=false;
    if(currentWater)$('water-design-stale').hidden=false;
  });
  map.on('plannerrestore',event=>{
    if(selected?.workflow==='street' && event.workflow==='street' && event.siteId===selected.siteId &&
        event.comparison && event.inputRevision<=selected.inputRevision && event.revision>=realRevision) {
      try {
        const prepared=trafficAlternatives(event);currentTraffic={...event,restored:true};realRevision=event.revision;
        showTrafficEvaluation(currentTraffic,prepared);$('comparison-stale').hidden=false;
        if(published){$('proposal-stale').hidden=false;$('proposal-map-caption').textContent=`${caption(true)} · saved previous result`;}
      }catch(error){$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Saved evaluation unavailable: ${error.message}`;}
      return;
    }
    if(!selected || selected.workflow!=='water' || event.workflow!=='water' || event.siteId!==selected.siteId ||
      !event.proposal || event.inputRevision>selected.inputRevision || event.revision<realRevision)return;
    try {
      const area=validate(event.proposal,{...selected,inputRevision:event.inputRevision},event.revision,false);
      currentWater={...event,restored:true};realRevision=event.revision;
      publish(event.proposal,area,selected,undefined,currentWater);renderWaterStudy(currentWater);
      $('proposal-stale').hidden=false;$('water-design-stale').hidden=false;
      $('proposal-map-caption').textContent=`${caption(true)} · saved previous result`;
    }catch(error){$('proposal-result-message').hidden=false;$('proposal-result-message').textContent=`Saved footprint unavailable: ${error.message}`;}
  });
  map.on("plannerinputs", ({inputRevision}) => {
    if (!selected) return;
    selected = {...selected,inputRevision}; controller?.abort(); ++request;
    $("load-proposal-fixture").disabled = false;
    $("revise-proposal-fixture").disabled = !published?.development_fixture;
    if (published) { $("proposal-stale").hidden = false; $("proposal-map-caption").textContent = caption(true); }
    if (comparison) $("comparison-stale").hidden = false;
    if(currentWater)$('water-design-stale').hidden=false;
  });
})();
