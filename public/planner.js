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
    treatment: { label: "Treatment area", action: "Outline a spot for a rain garden", color: "#ade7a4",
      description: "Mark the space you want to consider for a treatment.",
      instruction: "Click around the space you want to use for the rain garden." },
  };
  const workflows = {
    street: { kinds: ["crossing", "access"], brief: "Find the crossings and driveway entrances near this site. What could shorten a crossing while preserving access?" },
    water: { kinds: ["access", "drainage", "treatment"], brief: "Draft a rain garden for this site. Show where it could fit and what surfaces could feed it." },
  };
  const siteLayer = L.layerGroup();
  map.createPane("watershed");
  map.getPane("watershed").style.zIndex = 390;
  map.getPane("watershed").style.pointerEvents = "none";
  const watershedLayer = L.geoJSON(null, { pane: "watershed", interactive: false, style: {
    color: "#80d7ff", weight: 3, dashArray: "8 5", fillColor: "#46afd4", fillOpacity: .18,
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
  let activeAnalysis = null;
  let workspaceVisible = false;
  let coordinateInputs = [];

  let projectLoadGeneration = 0;

  const waterDefaults = {targetAreaM2:null,storageDepthM:null,layout:'auto',placement:'auto',
    runoffCoefficient:null,drainageAssumption:'unknown',protectAccess:false};
  const waterFields = {'water-target-area':'targetAreaM2','water-storage-depth':'storageDepthM',
    'water-layout':'layout','water-placement':'placement','water-runoff-coefficient':'runoffCoefficient',
    'water-drainage-assumption':'drainageAssumption','water-protect-access':'protectAccess'};
  function waterSettings(record, analyze=false) {
    const value={...waterDefaults,...record.stormwaterSettings};
    for(const [key,min,max,label] of [['targetAreaM2',2,500,'Target treatment area'],['storageDepthM',.05,.30,'Effective ponding depth'],['runoffCoefficient',0,1,'Runoff coefficient']]) {
      if(value[key]===null || value[key]==='') {value[key]=null;continue;}
      value[key]=Number(value[key]);
      if(!Number.isFinite(value[key]) || value[key]<min || value[key]>max) throw new Error(`${label} must be between ${min} and ${max}.`);
    }
    if(analyze && value.drainageAssumption==='marked_connected') {
      if(value.runoffCoefficient===null) throw new Error('Enter an explicit runoff coefficient for the marked-area what-if.');
      if(!record.features.some(item=>item.kind==='drainage')) throw new Error('Outline a potential runoff source before evaluating the marked-area what-if.');
    }
    return value;
  }
  function showWaterSettings() {
    $('stormwater-settings').hidden=workflow!=='water';
    const record=site?.water, values={...waterDefaults,...record?.stormwaterSettings};
    for(const [id,key] of Object.entries(waterFields)) {
      const input=$(id);input.disabled=!site;
      if(key==='protectAccess')input.checked=Boolean(values[key]);else input.value=values[key] ?? '';
    }
    $('water-what-if-note').hidden=values.drainageAssumption!=='marked_connected';
    $('water-runoff-coefficient').disabled=!site || values.drainageAssumption!=='marked_connected';
  }

  function projectSnapshot(selected, mode) {
    const record = selected[mode];
    const markings = record.features.map(({kind, points}) => {
      const coordinates = points.map(({lat,lng}) => [lng,lat]);
      return {kind, geometry:kind === "crossing" ? {type:"LineString",coordinates}
        : {type:"Polygon",coordinates:[[...coordinates,coordinates[0]]]}};
    });
    let rainfallScenario = null;
    if (mode === "water" && record.rainEdited) {
      const inches = Number(record.depth);
      if (!String(record.depth).trim() || !Number.isFinite(inches) || inches < 0 || inches > 100 || !record.source.trim())
        throw new Error("Complete the rainfall depth and source to save this scenario.");
      rainfallScenario = {inches, source:record.source.trim()};
    }
    return {workflow:mode,siteId:selected.key,lon:selected.center.lng,lat:selected.center.lat,
      propertyId:selected.propertyId ?? null,question:record.brief.trim(),markings,rainfallScenario,
      ...(mode==='water'?{stormwaterSettings:waterSettings(record)}:{}),
      inputRevision:record.revision ?? 0,proposalRevision:Math.max(1,record.proposalRevision ?? 1)};
  }

  function showProject(record = site?.[workflow]) {
    const value = record?.project?.value;
    $("project-status").textContent = record?.saveError || (value
      ? `Saved locally · revision ${value.version} · ${value.status.replaceAll('_',' ')}${record.stale ? ' · inputs changed' : ''}`
      : "Site, brief and constraints save locally as you work.");
    $("run-site-analysis").textContent = value?.result ? "Continue project" : "Analyze site";
    const list = $("project-file-list"); list.replaceChildren();
    $("project-file-count").textContent = value?.artifacts?.length ? `· ${value.artifacts.length}` : "";
    for (const artifact of value?.artifacts ?? []) {
      const row = document.createElement("li"), button = document.createElement("button");
      button.type = "button"; button.textContent = artifact.path.replace('/project/','');
      button.addEventListener("click", async () => {
        try {
          const file = await json(`/api/project-artifact?${new URLSearchParams({id:value.id,path:artifact.path})}`);
          if (site?.[workflow] !== record) return;
          let content = file.content;
          try { content = JSON.stringify(JSON.parse(content),null,2); } catch {}
          $("project-file-preview").textContent = content;
          $("project-file-preview").hidden = false;
        } catch (error) { if (site?.[workflow] === record) $("project-status").textContent = error.message; }
      });
      row.append(button); list.append(row);
    }
  }

  async function refreshProjects() {
    const mode = workflow;
    try {
      const {projects} = await json('/api/projects');
      if (workflow !== mode) return;
      const picker = $("saved-projects"), selected = site?.[mode]?.project?.value?.id;
      picker.replaceChildren();
      const placeholder = document.createElement('option'); placeholder.value=''; placeholder.textContent='Choose a saved project'; picker.append(placeholder);
      for (const project of projects.filter(p => p.workflow === mode)) {
        const option=document.createElement('option'); option.value=project.id;
        option.textContent=`${project.question.slice(0,65) || 'Untitled site'} · ${project.status.replaceAll('_',' ')}`;
        picker.append(option);
      }
      picker.value=selected || '';
    } catch (error) { $("project-status").textContent=error.message; }
  }

  async function saveProject(selected, mode) {
    const record=selected[mode];
    clearTimeout(record.saveTimer); record.saveTimer=null;
    record.project ??= new SavedProject();
    try {
      const value=await record.project.save(projectSnapshot(selected,mode));
      record.saveError='';
      if (site === selected && workflow === mode) {
        try { localStorage.setItem(`planning-project-${mode}`,value.id); } catch {}
        showProject(record); refreshProjects();
      }
      return value;
    } catch (error) {
      record.saveError=error.message;
      if (site === selected && workflow === mode) showProject(record);
      throw error;
    }
  }

  function scheduleProjectSave(record) {
    if (!site) return;
    const selected=site, mode=selected.water === record ? 'water':'street';
    clearTimeout(record.saveTimer);
    record.saveTimer=setTimeout(() => saveProject(selected,mode).catch(()=>{}),500);
    if (site?.[workflow] === record) $("project-status").textContent="Saving project…";
  }

  function restoreResult(selected, mode, value) {
    const record=selected[mode], result=value.result;
    const stopped=Boolean(result?.analysisError) || ['canceled','interrupted','failed'].includes(value.status);
    const stoppedMessage='The previous run stopped. Saved constraints and retrieved evidence are available; continue when ready.';
    record.activity=value.events ?? [];
    const restorePreviousWater=()=>{
      if(mode!=='water')return;
      const history=(value.designHistory ?? result?.designHistory ?? []).filter(entry=>{
        const proposal=entry.proposal, inputRevision=entry.inputRevision ?? proposal?.input_revision;
        return proposal?.site_id===selected.key && proposal.workflow==='water' && !proposal.development_fixture &&
          Number.isInteger(entry.revision) && entry.revision>=1 && entry.revision===proposal.revision &&
          entry.revision<=(record.proposalRevision ?? 0) && Number.isInteger(inputRevision) && inputRevision>=0 &&
          inputRevision===proposal.input_revision && inputRevision<=(record.revision ?? 0);
      });
      const saved=[...history].sort((a,b)=>b.revision-a.revision)[0];
      if(!saved)return;
      record.stale=true;
      record.evidenceError=[record.evidenceError,'The earlier stormwater concept remains available below as a saved reference; this attempt did not update it.'].filter(Boolean).join(' ');
      // Keep historical source IDs readable without linking them to the failed
      // attempt's newer evidence ledger.
      map.fire('plannerrestore',{siteId:selected.key,workflow:mode,
        inputRevision:saved.inputRevision ?? saved.proposal.input_revision,revision:saved.revision,
        proposal:saved.proposal,alternatives:saved.alternatives ?? {},waterPlan:saved.waterPlan,
        designHistory:history,savedAt:saved.savedAt,restored:true,historicalReference:true});
    };
    const restorePreviousTraffic=()=>{
      if(mode!=='street')return;
      const history=value.trafficDesignHistory ?? result?.trafficDesignHistory ?? [];
      const saved=history.filter(entry=>entry.comparison?.status==='completed' &&
        entry.comparison.site_id===selected.key && entry.comparison.workflow==='street' &&
        Number.isInteger(entry.revision) && entry.revision<=(record.proposalRevision ?? 0) &&
        (entry.inputRevision ?? entry.comparison.input_revision)<=(record.revision ?? 0))
        .sort((a,b)=>b.revision-a.revision)[0];
      if(!saved)return;
      // The failed attempt's source ledger is still visible. Historical source
      // decisions may be read, but must not link to those newer fact IDs.
      const plan=saved.trafficPlan?{...saved.trafficPlan,sourceDecisions:(saved.trafficPlan.sourceDecisions ?? []).map(decision=>{
        if(typeof decision!=='object' || !decision)return decision;
        const {fact_id,...archived}=decision;return archived;
      })}:null;
      record.stale=true;
      record.evidenceError=[record.evidenceError,'Earlier evaluated layouts remain available below as a saved reference; this attempt did not update them.'].filter(Boolean).join(' ');
      map.fire('plannerrestore',{siteId:selected.key,workflow:mode,
        inputRevision:saved.inputRevision ?? saved.comparison.input_revision,revision:saved.revision,
        proposal:saved.proposal,comparison:saved.comparison,alternatives:saved.alternatives ?? {},trafficPlan:plan,
        trafficDesignHistory:history,savedAt:saved.savedAt,restored:true,historicalReference:true});
    };
    const restorePrevious=()=>mode==='water'?restorePreviousWater():restorePreviousTraffic();
    if (result) {
      Object.assign(record,{evidence:result.evidence,report:result.report,facts:result.facts ?? [],
        synthesisWarning:result.synthesisWarning || '',
        sourceWarnings:result.sourceWarnings ?? [],sourceStatus:result.sourceStatus,evidenceError:result.analysisError || result.resumeNotice || (stopped?stoppedMessage:''),
        stale:value.resultVersion !== value.version || stopped});
      if(result.hydrology) applyHydrology(selected.water,result.hydrology);
      if(value.resultVersion === value.version && !stopped && (result.proposal || result.comparison || result.draftQuestion))
        map.fire('plannerresult',{siteId:selected.key,workflow:mode,inputRevision:record.revision ?? 0,
          revision:record.proposalRevision,proposal:result.proposal,comparison:result.comparison,
          alternatives:result.alternatives ?? {},draftQuestion:result.draftQuestion,waterPlan:result.waterPlan,designHistory:value.designHistory ?? result.designHistory ?? [],
          trafficPlan:result.trafficPlan,trafficDesignHistory:value.trafficDesignHistory ?? result.trafficDesignHistory ?? [],
          savedAt:result.savedAt,restored:true});
      else if(mode==='water' && !stopped && result.proposal) map.fire('plannerrestore',{
        siteId:selected.key,workflow:mode,inputRevision:result.proposal.input_revision,revision:result.proposal.revision,
        proposal:result.proposal,alternatives:result.alternatives ?? {},waterPlan:result.waterPlan,
        designHistory:value.designHistory ?? result.designHistory ?? [],savedAt:result.savedAt,restored:true});
      else if(mode==='street' && !stopped && result.comparison) map.fire('plannerrestore',{
        siteId:selected.key,workflow:mode,inputRevision:result.comparison.input_revision,revision:result.comparison.revision,
        proposal:result.proposal,comparison:result.comparison,alternatives:result.alternatives ?? {},trafficPlan:result.trafficPlan,
        trafficDesignHistory:value.trafficDesignHistory ?? result.trafficDesignHistory ?? [],savedAt:result.savedAt,restored:true});
      else if(stopped)restorePrevious();
    } else {
      const facts = new Map();
      for (const event of record.activity) for (const fact of event.facts ?? []) facts.set(fact.id,fact);
      record.facts=[...facts.values()];
      if (stopped) {
        record.evidenceError=stoppedMessage;
        record.stale=true;
      }
      restorePrevious();
    }
    showEvidence(); showRainfall(); showProject(record);
  }

  async function openProject(id, generation = ++projectLoadGeneration) {
    if (!id) return;
    $("project-status").textContent="Opening the saved project…";
    try {
      const value=await json(`/api/projects?id=${encodeURIComponent(id)}`);
      if(generation !== projectLoadGeneration || value.snapshot.workflow !== workflow) return;
      const snapshot=value.snapshot;
      let property=null;
      if(snapshot.propertyId) {
        try {
          const resolution=await json(`/api/site-resolution?${new URLSearchParams({lon:snapshot.lon,lat:snapshot.lat,workflow,propertyId:snapshot.propertyId})}`);
          if(resolution.property?.id === snapshot.propertyId) property=resolution.property;
        } catch {}
      }
      if(generation !== projectLoadGeneration || snapshot.workflow !== workflow) return;
      cancelAnalysis();
      selectSite(L.latLng(snapshot.lat,snapshot.lon),property,value);
      map.setView(site.center,17,{animate:false});
      restoreResult(site,workflow,value);
      try { localStorage.setItem(`planning-project-${workflow}`,id); } catch {}
      if(value.activeRun) pollSavedRun(site,workflow,id);
    } catch(error) { if(generation === projectLoadGeneration) $("project-status").textContent=error.message; }
  }

  function pollSavedRun(selected,mode,id) {
    setTimeout(async () => {
      if(site !== selected || workflow !== mode || activeAnalysis) return;
      try {
        const value=await json(`/api/projects?id=${id}`);
        if(site !== selected || workflow !== mode || activeAnalysis || selected[mode].saveTimer) return;
        // Local edits must never be replaced by a delayed server response.
        if(value.version !== selected[mode].project.value.version) return;
        selected[mode].project.value=value;
        restoreResult(selected,mode,value);
        if(value.activeRun) pollSavedRun(selected,mode,id);
      } catch {}
    },1500);
  }
  $("open-project").addEventListener('click',()=>openProject($("saved-projects").value));
  // Choosing an opportunity restores its explicit site project; it never starts
  // design generation. The next site request remains the publication gate.
  map.on('scoutselect', ({project}) => {
    if (project?.snapshot?.workflow === workflow) openProject(project.id);
  });
  map.on('plannerinspectevidence',({siteId,evidenceIds})=>{
    if(!site || site.key!==siteId)return;
    const match=(site[workflow].facts ?? []).find(f=>evidenceIds.includes(f.id) || (f.feature_ids ?? []).some(id=>evidenceIds.includes(id)));
    $('site-tools').open=true;
    if(match) {
      const row=$(`fact-${match.id}`);row.open=true;row.scrollIntoView({block:'nearest'});row.focus?.({preventScroll:true});
    } else $('site-facts').scrollIntoView({block:'nearest'});
  });

  function pointError(point, marking = false) {
    if (!point || !Number.isFinite(point.lat) || !Number.isFinite(point.lng)) return "Enter a finite latitude and longitude for every point.";
    if (point.lat < 33.70 || point.lat > 34.35 || point.lng < -118.67 || point.lng > -118.10) return "Choose coordinates within the Los Angeles map bounds.";
    if (coverage && !insideCoverage(point)) return "Choose a point inside the imagery coverage.";
    if (marking && site) {
      const radians = Math.PI / 180, a = site.center.lat * radians, b = point.lat * radians;
      const h = Math.sin((b-a)/2)**2 + Math.cos(a)*Math.cos(b)*Math.sin((point.lng-site.center.lng)*radians/2)**2;
      // Leave a small margin inside the server's projected 1 km polygonal
      // buffer: spherical browser distances differ slightly from UTM lengths.
      if (2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(h))) > 990) return "Keep marking points within 990 m of the selected site.";
    }
    return "";
  }

  function addEvidence(item, color, style = {}) {
    const layer = L.geoJSON(item, { style: { color, weight: 2, fillOpacity: .1, ...style } });
    const label = document.createElement("span");
    const { label: name, date, score, evidenceId } = item.properties;
    label.textContent = [name, evidenceId, date, score == null ? null : `detector score ${score.toFixed(2)}`].filter(Boolean).join(" · ");
    layer.bindTooltip(label).addTo(evidenceLayer);
  }

  function renderSafely(record, render) {
    try { render(); }
    catch (error) {
      // Presentation failures must not cancel the stream or strand its controls.
      record.displayWarning = "Some evidence could not be displayed. The remaining assessment is still available.";
      $("analysis-message").hidden = false;
      $("analysis-message").textContent = record.evidenceError || record.displayWarning;
    }
  }

  function showReview(record) {
    renderSafely(record, () => renderReview(record));
  }

  function renderReview(record) {
    const facts = Array.isArray(record.facts) ? record.facts : [];
    const output = $("agent-assessment");
    output.replaceChildren();
    output.hidden = !record.report;
    $("analysis-message").hidden = !record.evidencePending && !record.evidenceError && !record.displayWarning;
    $("analysis-message").textContent = record.evidencePending ? (record.activitySummary || "Starting site investigation…") : record.evidenceError || record.displayWarning || "";
    $('analysis-synthesis-warning').hidden=!record.synthesisWarning || record.evidencePending;
    $('analysis-synthesis-warning').textContent=record.synthesisWarning ? `Agent summary incomplete. ${record.synthesisWarning}`:'';
    $("cancel-site-analysis").hidden = !record.evidencePending;
    showActivity(record);
    $("analysis-stale").hidden = !record.stale;
    if (record.report) {
      for (const [key, heading] of [["findings", "What the evidence shows"], ["recommendations", "Options to evaluate"], ["questions", "Confirm next"]]) {
        const entries = record.report[key] ?? [];
        if (!entries.length) continue;
        const title = document.createElement("h3");
        title.textContent = heading;
        output.append(title);
        for (const entry of entries) {
          const paragraph = document.createElement("p");
          paragraph.textContent = typeof entry === "string" ? entry : entry.text;
          for (const id of entry.fact_ids ?? []) {
            const index = facts.findIndex((fact) => fact?.id === id);
            if (index < 0) continue;
            const link = document.createElement("button");
            link.type = "button";
            link.className = "fact-reference";
            link.textContent = `[${index + 1}]`;
            link.setAttribute("aria-label", `Source ${index + 1}: ${facts[index].label}`);
            link.addEventListener("click", () => {
              $("site-tools").open = true;
              const row = $(`fact-${id}`);
              row.open = true;
              row.scrollIntoView({ block: "center" });
              row.focus({ preventScroll: true });
            });
            paragraph.append(link);
          }
          output.append(paragraph);
        }
      }
    }
    $("site-facts").hidden = !facts.length && !record.sourceStatus;
    const list = $("site-facts-list");
    const expanded = new Set([...(list.querySelectorAll?.("details[open]") ?? [])].map(row => row.id));
    const focused = document.activeElement?.id;
    list.replaceChildren();
    const labels = { measured: "Measured", reported: "Reported", estimated: "Estimated", candidate: "Candidate", user_marked: "User marked", assumption: "Assumption", availability: "Source status" };
    facts.forEach((fact, index) => {
      const row = document.createElement("li");
      try {
        if (!fact || typeof fact !== "object" || typeof fact.id !== "string") throw new Error("Invalid evidence item.");
        const detail = document.createElement("details");
        detail.id = `fact-${fact.id}`;
        detail.tabIndex = -1;
        detail.open = expanded.has(detail.id);
        const summary = document.createElement("summary");
        const name = document.createElement("span");
        name.textContent = `${index + 1}. ${fact.label}`;
        const value = document.createElement("strong");
        value.textContent = fact.display;
        const badge = document.createElement("small");
        badge.className = `fact-basis ${fact.basis}`;
        badge.textContent = labels[fact.basis] || fact.basis;
        summary.append(name, value, badge);
        detail.append(summary);
        for (const text of [fact.method, fact.note]) {
          if (!text) continue;
          const paragraph = document.createElement("p");
          paragraph.textContent = text;
          detail.append(paragraph);
        }
        const source = fact.source && typeof fact.source === "object" ? fact.source : {};
        const sourceUrl = typeof source.url === "string" && /^https?:\/\//i.test(source.url) ? source.url : null;
        const origin = document.createElement(sourceUrl ? "a" : "span");
        origin.textContent = typeof source.provider === "string" ? source.provider : "Source unavailable";
        if (sourceUrl) { origin.href = sourceUrl; origin.target = "_blank"; origin.rel = "noopener"; }
        detail.append(origin);
        const metadata = document.createElement("p");
        metadata.className = "fact-metadata";
        const retrieved = typeof source.retrieved_at === "string" && Number.isFinite(Date.parse(source.retrieved_at))
          ? `Retrieved ${source.retrieved_at.slice(0, 10)}` : "Retrieval date unavailable";
        const references = Array.isArray(fact.feature_ids) ? fact.feature_ids.filter(id => typeof id === "string") : [];
        metadata.textContent = [typeof source.observed_at === "string" && source.observed_at ? `Observed ${source.observed_at}` : "Observation date unavailable",
          retrieved, typeof source.collection === "string" && source.collection ? `Collection ${source.collection}` : null,
          references.length ? `Map references: ${references.join(", ")}` : null].filter(Boolean).join(" · ");
        detail.append(metadata);
        row.append(detail);
        list.append(row);
        if (focused === detail.id) detail.focus({preventScroll:true});
      } catch (error) {
        row.replaceChildren();
        row.textContent = "Evidence item unavailable; the remaining assessment is still available.";
        if (!list.children || !Array.from(list.children).includes(row)) list.append(row);
      }
    });
    const statuses = { outlines: "Parcel & buildings", detections: "Feature detection", property: "CoStar", hydrology: "County hydrology", search: "Imagery search" };
    $("site-source-status").textContent = Object.entries(record.sourceStatus ?? {})
      .map(([name, status]) => `${statuses[name] ?? name}: ${status === "empty" ? "no usable facts" : status}`).join(" · ");
    $("site-source-warnings").replaceChildren();
    for (const warning of record.sourceWarnings ?? []) {
      const item = document.createElement("li");
      item.textContent = warning;
      $("site-source-warnings").append(item);
    }
  }

  function inputsChanged(record) {
    if (activeAnalysis?.record === record) cancelAnalysis();
    record.revision = (record.revision ?? 0) + 1;
    if (record.report || record.evidencePending || record.facts?.length) record.stale = true;
    showReview(record);
    map.fire("plannerinputs", { inputRevision: record.revision });
    scheduleProjectSave(record);
  }

  function showEvidence() {
    evidenceLayer.clearLayers();
    const record = site[workflow];
    const evidence = record.evidence;
    const list = $("site-evidence-list");
    list.replaceChildren();
    $("run-site-analysis").disabled = Boolean(record.evidencePending || site.identityPending);
    showReview(record);
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
      addEvidence({ type: "Feature", geometry: frontage.geometry, properties: { label, evidenceId: frontage.evidenceId } }, "#eb9eff", { weight: 4 });
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
    if (unavailable.some((group) => ["outlines", "detections", "search"].includes(group))) notes.push("Some Vexcel data could not be loaded.");
    if (unavailable.includes("hydrology")) notes.push("County rainfall or watershed data could not be loaded.");
    if (unavailable.includes("property")) notes.push("CoStar context unavailable.");
    $("site-evidence-note").textContent = notes.filter(Boolean).join(" ");
  }

  function showActivity(record) {
    const list = $("activity-list");
    list.replaceChildren();
    $("activity-count").textContent = record.activity?.length ? `· ${record.activity.length}` : "";
    for (const event of record.activity ?? []) {
      const row = document.createElement("li");
      row.setAttribute("data-status", event.status);
      const title = document.createElement("strong");
      title.textContent = `${event.specialist} · ${event.status}`;
      const text = document.createElement("span"); text.textContent = event.summary;
      row.append(title, text);
      for (const id of event.fact_ids ?? []) {
        const fact = record.facts?.find(f => f.id === id);
        if (!fact) continue;
        const button = document.createElement("button"); button.type = "button";
        button.textContent = fact.label;
        button.addEventListener("click", () => {
          $("site-tools").open = true;
          const target = $(`fact-${id}`); if (!target) return;
          target.open = true; target.scrollIntoView({block:"center"}); target.focus({preventScroll:true});
        });
        row.append(button);
      }
      list.append(row);
    }
  }

  function cancelAnalysis() {
    if (!activeAnalysis) {
      const savedRun=site?.[workflow]?.project?.value?.activeRun;
      if(savedRun) cancelSiteAnalysis(savedRun);
      return;
    }
    const {record, controller} = activeAnalysis;
    cancelSiteAnalysis(activeAnalysis.serverRunId);
    activeAnalysis = null; controller.abort();
    record.evidencePending = false;
    record.evidenceError = "Analysis canceled. Retrieved evidence is preserved.";
    record.stale = true;
    if (site?.[workflow] === record) showEvidence();
  }
  $("cancel-site-analysis").addEventListener("click", cancelAnalysis);

  async function loadEvidence(event) {
    event.preventDefault();
    if (!site || site.identityPending) return;
    const selected = site;
    const mode = workflow;
    const record = selected[mode];
    if (record.evidencePending) return;
    const question = record.brief.trim();
    if (!question) return;
    const revision = record.revision ?? 0;
    const proposalRevision = (record.proposalRevision ?? 0) + 1;
    const markings = record.features.map(({ kind, points }) => {
      const coordinates = points.map(({ lat, lng }) => [lng, lat]);
      return { kind, geometry: kind === "crossing" ? { type: "LineString", coordinates }
        : { type: "Polygon", coordinates: [[...coordinates, coordinates[0]]] } };
    });
    let rainfallScenario = null;
    if (mode === "water" && record.rainEdited) {
      const inches = Number(record.depth);
      if (String(record.depth).trim() === "" || !Number.isFinite(inches) || inches < 0 || inches > 100 || !record.source.trim()) {
        record.evidenceError = "Enter a scenario rainfall depth from 0 to 100 inches and its source, or assumption, before analysis.";
        showReview(record);
        return;
      }
      rainfallScenario = { inches, source: record.source.trim() };
    }
    let stormwaterSettings;
    if(mode==='water') {
      try {stormwaterSettings=waterSettings(record,true);} catch(error) {record.evidenceError=error.message;showReview(record);return;}
    }
    record.evidencePending = true;
    record.proposalRevision = proposalRevision;
    record.evidenceError = "";
    record.displayWarning = "";
    // Keep retrieved evidence visible while the new run is in flight.
    record.report = null;
    record.synthesisWarning = '';
    record.activity = [];
    record.activitySummary = "Starting site investigation…";
    record.stale = Boolean(record.facts?.length);
    const controller = new AbortController();
    const run = {record, controller}; activeAnalysis = run;
    try {
      map.fire('plannerinvestigation',{siteId:selected.key,workflow:mode,inputRevision:revision,revision:proposalRevision});
      renderSafely(record, showEvidence);
      const saved = await saveProject(selected,mode);
      if(activeAnalysis !== run || controller.signal.aborted) return;
      const result = await streamSiteAnalysis({ projectId:saved.id, projectVersion:saved.version,
        lat:selected.center.lat, lon:selected.center.lng,
        propertyId:selected.propertyId, workflow:mode, question, markings, rainfallScenario,
        ...(mode==='water'?{stormwaterSettings}:{}),
        siteId:selected.key, inputRevision:revision, proposalRevision,
        discoveryReference:record.discovery?.reference ?? null }, {
        signal:controller.signal,
        onEvent(event) {
          if (activeAnalysis !== run || controller.signal.aborted) return;
          run.serverRunId = event.run_id;
          if (record.project?.value) {
            record.project.value.status = 'investigating';
            if (site?.[workflow] === record) showProject(record);
          }
          record.activity.push(event);
          record.activitySummary = event.summary;
          if (Array.isArray(event.facts) && event.facts.length) {
            const ledger = new Map((Array.isArray(record.facts) ? record.facts : []).filter(f => f && typeof f.id === "string").map(f => [f.id,f]));
            for (const fact of event.facts) if (fact && typeof fact.id === "string") ledger.set(fact.id,fact);
            record.facts = [...ledger.values()];
          }
          if (site?.[workflow] === record) showReview(record);
          if (event.stage === 'artifact-write' && record.project?.value) {
            json(`/api/projects?id=${record.project.value.id}`).then(value => {
              if (activeAnalysis !== run || value.version !== record.project.value.version) return;
              record.project.value=value;
              if(site?.[workflow] === record) showProject(record);
            }).catch(()=>{});
          }
        },
      });
      if (activeAnalysis !== run || controller.signal.aborted) return;
      record.evidence = result.evidence;
      record.report = result.report;
      record.synthesisWarning = result.synthesisWarning || '';
      if (result.facts?.length || result.report) record.facts = result.facts ?? [];
      record.sourceWarnings = result.sourceWarnings ?? [];
      record.sourceStatus = result.sourceStatus;
      record.evidenceError = result.analysisError ?? "";
      if (result.hydrology) applyHydrology(selected.water, result.hydrology);
      // A changed site or marking must never publish geometry from an older run.
      if (site === selected && workflow === mode && (record.revision ?? 0) === revision &&
          !result.analysisError && (result.proposal || result.comparison || result.draftQuestion)) {
        map.fire("plannerresult", {siteId:selected.key, workflow:mode, inputRevision:revision,
          revision:proposalRevision, proposal:result.proposal ?? null, comparison:result.comparison ?? null,
          alternatives:result.alternatives ?? {}, draftQuestion:result.draftQuestion ?? null,
          waterPlan:result.waterPlan,designHistory:result.designHistory ?? [],trafficPlan:result.trafficPlan,
          trafficDesignHistory:result.trafficDesignHistory ?? []});
      }
    } catch (error) {
      if (activeAnalysis !== run) return;
      record.evidenceError = error.name === "AbortError" ? "Analysis canceled. Retrieved evidence is preserved." : error.message;
    } finally {
      if (activeAnalysis !== run) return;
      activeAnalysis = null;
      record.evidencePending = false;
      record.stale = (record.revision ?? 0) !== revision || Boolean(record.evidenceError);
      if (site?.[workflow] === record) {
        $("run-site-analysis").disabled = Boolean(site.identityPending);
        $("cancel-site-analysis").hidden = true;
        renderSafely(record, showEvidence);
        renderSafely(record, showRainfall);
      }
      if (record.project?.value?.id) {
        const id=record.project.value.id;
        json(`/api/projects?id=${id}`).then(value=>{
          if (record.project.value.version !== value.version) return;
          record.project.value=value;
          if(site === selected && workflow === mode) { showProject(record); refreshProjects(); }
        }).catch(()=>{});
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
        inputsChanged(site[workflow]);
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

  function renderCoordinates() {
    coordinateInputs = [];
    $("draw-coordinates").replaceChildren();
    draft.coordinateError = "";
    for (const [index, point] of draft.points.entries()) {
      const row = document.createElement("fieldset"); row.className = "vertex-coordinates";
      const legend = document.createElement("legend"); legend.textContent = `Point ${index + 1}`; row.append(legend);
      const inputs = {};
      for (const [axis, title] of [["lat", "Latitude"], ["lng", "Longitude"]]) {
        const label = document.createElement("label"); label.textContent = title;
        const input = document.createElement("input"); input.type = "text"; input.inputMode = "decimal";
        input.value = point[axis].toFixed(7); input.setAttribute("aria-label", `Point ${index + 1} ${title.toLowerCase()}`);
        input.setAttribute("aria-describedby", "draw-coordinate-error"); input.setAttribute("aria-invalid", "false");
        input.addEventListener("input", () => {
          const points = coordinateInputs.map(fields => {
            const lat = fields.lat.value.trim(), lng = fields.lng.value.trim();
            return lat && lng ? {lat:Number(lat),lng:Number(lng)} : {lat:NaN,lng:NaN};
          });
          const errors = points.map(p => pointError(p, true));
          coordinateInputs.forEach((fields, i) => Object.values(fields).forEach(field => field.setAttribute("aria-invalid", String(Boolean(errors[i])))));
          draft.coordinateError = errors.find(Boolean) || "";
          if (!draft.coordinateError) draft.points = points.map(p => L.latLng(p.lat, p.lng));
          drawPreview(false);
        });
        inputs[axis] = input; label.append(input); row.append(label);
      }
      coordinateInputs.push(inputs); $("draw-coordinates").append(row);
    }
  }

  function drawPreview(refreshCoordinates = true) {
    if (refreshCoordinates) renderCoordinates();
    draftLayer.clearLayers();
    featureLayer(draft, { dashArray: "5 4" }).addTo(draftLayer);
    for (const [index, point] of draft.points.entries()) {
      const icon = L.divIcon({ className: "planner-vertex", iconSize: [14, 14] });
      const handle = L.marker(point, { draggable: !draft.coordinateError, icon, keyboard: false, zIndexOffset: 1500 }).addTo(draftLayer);
      handle.on("drag", () => {
        draft.points[index] = handle.getLatLng();
        draftLayer.eachLayer((layer) => {
          if (layer instanceof L.Polyline) layer.setLatLngs(draft.points);
        });
      });
      handle.on("dragend", () => {
        const error = pointError(draft.points[index], true);
        if (error) draft.points[index] = point;
        drawPreview();
        if (error) mapHint(error);
      });
    }
    const count = draft.points.length;
    const type = featureTypes[draft.kind];
    const minimum = type.line ? 2 : 3;
    $("draw-save").disabled = count < minimum || Boolean(draft.coordinateError);
    $("draw-add-center").disabled = Boolean(draft.coordinateError) || (type.line && count >= 2);
    $("draw-coordinate-error").textContent = draft.coordinateError || "";
    $("draw-coordinate-error").hidden = !draft.coordinateError;
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
    $("keyboard-marking-editor").hidden = true;
    coordinateInputs = [];
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
    $("keyboard-marking-editor").hidden = false;
    showFeatures();
    showMarkActions();
    drawPreview();
    setStatus("");
  }

  function showRainfall() {
    if (!site) { $("watershed-legend").hidden = true; return; }
    const record = site.water;
    $("rain-result").textContent = record.rainState === "loading" ? "Loading county rainfall contours…"
      : record.rainError || record.rainMessage || "County rainfall loads automatically for the selected site.";
    $("watershed-result").textContent = record.watershedState === "loading" ? "Finding the county subbasin…"
      : record.watershedError || record.watershedMessage || "County subbasin loads automatically for the selected site.";
    $("watershed-name").textContent = record.watershedName || "—";
    $("rain-value").textContent = record.estimate?.inches.toFixed(2) ?? "—";
    $("rain-depth").value = record.depth;
    $("rain-source").value = record.source;
    const hasBoundary = Boolean(record.watershed?.features.length);
    $("show-watershed").disabled = !hasBoundary;
    $("view-watershed").disabled = !hasBoundary;
    $("retry-hydrology").hidden = !record.rainError && !record.watershedError;
    $("retry-hydrology").disabled = record.rainState === "loading" || record.watershedState === "loading";
    const visible = workflow === "water" && !$("planner").hidden && $("show-watershed").checked && hasBoundary;
    watershedLayer.clearLayers();
    if (visible) watershedLayer.addData(record.watershed);
    $("watershed-legend").hidden = !visible;
    $("watershed-map-name").textContent = record.watershedName || "County subbasin";
  }

  function applyHydrology(record, { estimate, watershed, unavailable = [] }, fromRequest = false) {
    for (const [field, value, failure] of [["rain", estimate, "rainfall"], ["watershed", watershed, "watershed"]]) {
      if (!fromRequest && (value !== undefined || unavailable.includes(failure))) {
        record[`${field}Generation`] = (record[`${field}Generation`] ?? 0) + 1;
      }
      if (unavailable.includes(failure)) {
        record[`${field}State`] = "error";
        record[`${field}Error`] = `${field === "rain" ? "Rainfall" : "Watershed"} unavailable in the latest analysis. Any previous value shown is cached; retry county data.`;
      }
    }
    // Each source can succeed independently. A missing estimate (null) is a
    // valid result; an omitted estimate must not erase previously loaded data.
    if (estimate !== undefined) {
      record.estimate = estimate;
      record.rainState = "ready";
      record.rainError = "";
      if (!estimate) {
        record.rainMessage = "No reliable contour estimate here. Enter a sourced scenario depth below.";
      } else {
        const { inches, depth_range: range, method } = estimate;
        record.rainMessage = method === "on_contour"
          ? "Site lies on the county rainfall contour."
          : `Estimated between the ${range[0]} and ${range[1]} in county contours that bracket this site.`;
        if (!record.rainEdited) {
          record.depth = inches;
          record.source = method === "on_contour" ? "LA County 24-hour rainfall contour" : "LA County 24-hour rainfall contour estimate";
        }
      }
    }
    if (!watershed) return;
    record.watershedState = "ready";
    record.watershedError = "";
    record.watershed = watershed;
    const title = (name) => name.toLowerCase() === "lariver" ? "Los Angeles River"
      : name.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    const names = [...new Set(watershed.features.map(({ properties }) => properties?.WATERSHED?.trim()).filter(Boolean))];
    const subbasins = [...new Set(watershed.features.map(({ properties }) => properties?.NAME?.trim()).filter(Boolean))];
    record.watershedName = names.map(title).join(" / ") || (watershed.features.length ? "County subbasin" : "Outside mapped subbasins");
    record.watershedMessage = subbasins.length ? `Subbasin: ${subbasins.map(title).join(", ")}.`
      : watershed.features.length ? "Containing subbasin mapped by LA County Public Works."
      : "No county subbasin found for this point.";
  }

  function loadHydrology(selected, retry = false) {
    const record = selected.water;
    const query = new URLSearchParams({ lat: selected.center.lat, lon: selected.center.lng });
    for (const [field, endpoint] of [["rain", "rainfall"], ["watershed", "watershed"]]) {
      if (record[`${field}State`] === "ready" || record[`${field}State`] === "loading") continue;
      if (record[`${field}State`] === "error" && !retry) continue;
      record[`${field}State`] = "loading";
      record[`${field}Error`] = "";
      const generation = record[`${field}Generation`] = (record[`${field}Generation`] ?? 0) + 1;
      json(`/api/${endpoint}?${query}`).then((result) => {
        if (generation !== record[`${field}Generation`]) return;
        applyHydrology(record, field === "rain" ? { estimate: result.estimate } : { watershed: result }, true);
      }).catch((error) => {
        if (generation !== record[`${field}Generation`]) return;
        record[`${field}State`] = "error";
        record[`${field}Error`] = `${field === "rain" ? "Rainfall" : "Watershed"} unavailable. ${error.message}`;
      }).finally(() => {
        // Keep results cached for their site without painting over a newer selection.
        if (site === selected && generation === record[`${field}Generation`]) showRainfall();
      });
    }
    if (site === selected) showRainfall();
  }

  function showWorkflow() {
    showProject();
    showWaterSettings();
    $("project-file-preview").hidden=true;
    $("traffic-design-guide").hidden = workflow !== "street";
    $("water-tools").hidden = workflow !== "water";
    renderDiscoveryContext(site?.[workflow]?.discovery);
    $("run-site-analysis").disabled = !site || Boolean(site.identityPending || site[workflow].evidencePending);
    $("planning-brief").disabled = !site;
    $("analysis-site-hint").hidden = Boolean(site);
    if (!site) { $("activity-list").replaceChildren(); $("activity-count").textContent = ""; $("cancel-site-analysis").hidden = true; $("planning-brief").value = workflows[workflow].brief; return; }
    $("planning-brief").value = site[workflow].brief;
    showMarkActions();
    showFeatures();
    showEvidence();
    showRainfall();
    if (workflow === "water") loadHydrology(site);
  }

  function selectSite(center, property = null, restored = null) {
    projectLoadGeneration += 1;
    finishDrawing();
    const key = restored?.snapshot.siteId ?? (property ? `property:${property.id}` : `${center.lat.toFixed(6)},${center.lng.toFixed(6)}`);
    if (!restored && site && sites.get(key) === site) {
      setPicking(false);
      return;
    }
    cancelAnalysis();
    siteRequest?.abort();
    siteRequest = new AbortController();
    site = (!restored && sites.get(key)) || { center, propertyId: property?.id, property,
      street: { features: [], brief: workflows.street.brief },
      water: { features: [], brief: workflows.water.brief, depth: "", source: "" } };
    if (restored) {
      const snapshot=restored.snapshot, record=site[snapshot.workflow];
      Object.assign(record,{brief:snapshot.question,revision:snapshot.inputRevision,proposalRevision:snapshot.proposalRevision,
        stormwaterSettings:{...waterDefaults,...snapshot.stormwaterSettings},
        project:new SavedProject(restored),rainEdited:Boolean(snapshot.rainfallScenario),
        depth:snapshot.rainfallScenario?.inches ?? '',source:snapshot.rainfallScenario?.source ?? '',
        features:snapshot.markings.map(({kind,geometry})=>({kind,points:(kind === 'crossing' ? geometry.coordinates : geometry.coordinates[0].slice(0,-1)).map(([lng,lat])=>L.latLng(lat,lng))}))});
      site.propertyId=snapshot.propertyId;
    }
    property = site.property ?? property;
    site.identityPending = false;
    site.key = key;
    sites.set(key, site);
    setPicking(false);
    $("site-card").hidden = false;
    $("site-tools").hidden = false;
    $("site-name").textContent = property?.name ?? "Map location";
    $("site-location").textContent = [property?.address, `${center.lat.toFixed(5)}, ${center.lng.toFixed(5)}`].filter(Boolean).join(" · ");
    $("site-property").textContent = property?.type ?? "";
    $("site-resolution-candidates").replaceChildren();
    $("site-resolution-status").textContent = site.identity?.message ?? (property ? "Selected CoStar property." : "Checking the mapped parcel and nearby properties…");
    $("retry-site-resolution").hidden = Boolean(property);
    siteLayer.clearLayers();
    L.circleMarker(center, { radius: 8, weight: 2, color: "#fff", fillColor: "#a7e5a3",
      fillOpacity: 1, interactive: false }).addTo(siteLayer);
    showWorkflow();
    map.fire("plannersite", { siteId: key, center, workflow, property, inputRevision: site[workflow].revision ?? 0 });
    setStatus("");
    $("site-card").scrollIntoView({ block: "start" });

    refreshProjects();
    if (!restored) scheduleProjectSave(site[workflow]);
    if (!property) {
      if(restored) { $("site-resolution-status").textContent="Saved selection retained. Source association will be checked during analysis."; return; }
      resolveSelection(site); return;
    }
    showPropertyDetails(site, property);
  }

  function showPropertyDetails(selectedSite, property) {
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

  function resolveSelection(selected) {
    const generation = selected.identityGeneration = (selected.identityGeneration ?? 0) + 1;
    selected.identityPending = true;
    showWorkflow();
    const signal = siteRequest.signal;
    $("site-resolution-status").textContent = "Checking the mapped parcel and nearby properties…";
    $("retry-site-resolution").hidden = true;
    const query = new URLSearchParams({lat:selected.center.lat, lon:selected.center.lng, workflow});
    json(`/api/site-resolution?${query}`, {signal}).then(value => {
      if (site !== selected || signal.aborted || generation !== selected.identityGeneration) return;
      if (!["matched", "ambiguous", "unmatched", "unavailable"].includes(value?.status)) throw new Error("Invalid property resolution.");
      const property = value.status === "matched" ? value.property : null;
      if (property && (typeof property.id !== "string" || !property.id || !Number.isFinite(property.lat) || !Number.isFinite(property.lon))) throw new Error("Invalid matched property.");
      if (selected.propertyId !== property?.id) {
        inputsChanged(selected[workflow]);
        const other = selected[workflow === "water" ? "street" : "water"];
        other.revision = (other.revision ?? 0) + 1;
        if (other.facts?.length || other.report) other.stale = true;
      }
      selected.propertyId = property?.id;
      selected.property = property;
      selected.identity = value;
      $("site-name").textContent = property?.name ?? "Map location";
      $("site-location").textContent = [property?.address, `${selected.center.lat.toFixed(5)}, ${selected.center.lng.toFixed(5)}`].filter(Boolean).join(" · ");
      $("site-resolution-status").textContent = value.message;
      $("site-resolution-candidates").replaceChildren();
      for (const candidate of value.candidates ?? []) {
        const button = document.createElement("button"); button.type = "button";
        button.textContent = `Use ${candidate.name} · ${candidate.address}`;
        button.addEventListener("click", () => selectProperty(candidate));
        $("site-resolution-candidates").append(button);
      }
      if (property) showPropertyDetails(selected, property);
      else $("site-property").textContent = "CoStar property unassigned";
      map.fire("planneridentity", {siteId:selected.key, property, workflow});
      $("retry-site-resolution").hidden = value.status !== "unavailable";
    }).catch(error => {
      if (site !== selected || signal.aborted || generation !== selected.identityGeneration) return;
      $("site-resolution-status").textContent = "Property matching is unavailable. You can still investigate this map point or select a property through search.";
      $("retry-site-resolution").hidden = false;
    }).finally(() => {
      if (generation !== selected.identityGeneration) return;
      selected.identityPending = false;
      if (site === selected && !signal.aborted) showWorkflow();
    });
  }
  $("retry-site-resolution").addEventListener("click", () => {
    if (site && !site.identityPending) resolveSelection(site);
  });

  $("pick-site").addEventListener("click", () => {
    finishDrawing();
    setPicking(!picking);
    if (picking) map.closePopup();
    setStatus(picking ? "Click any covered location on the map." : "Site selection canceled.");
  });
  $("use-map-center").addEventListener("click", () => {
    const center = map.getCenter(), error = pointError(center);
    if (error) { setStatus(error); return; }
    finishDrawing(); selectSite(L.latLng(center.lat, center.lng));
  });
  $("draw-add-center").addEventListener("click", () => {
    if (!draft || draft.coordinateError || (featureTypes[draft.kind].line && draft.points.length >= 2)) return;
    const center = map.getCenter(), error = pointError(center, true);
    if (error) { mapHint(error); return; }
    draft.points.push(L.latLng(center.lat, center.lng)); drawPreview();
  });
  map.on("click", ({ latlng }) => {
    if (!picking && !draft) return;
    const error = pointError(latlng, Boolean(draft));
    if (error) { setStatus(error); return; }
    if (draft?.coordinateError) { mapHint("Correct the invalid point coordinates before adding another point."); return; }
    if (picking) {
      selectSite(latlng);
      map.setView(latlng, Math.max(map.getZoom(), 17), { animate: false });
    } else if (!featureTypes[draft.kind].line || draft.points.length < 2) {
      draft.points.push(latlng);
      drawPreview();
    }
  });
  function renderDiscoveryContext(selected) {
    $("discovery-context").hidden = !selected;
    if (!selected) return;
    const {feature, layer, source} = selected;
    const p = feature.properties;
    $("discovery-feature-title").textContent = p.label;
    $("discovery-feature-value").textContent = ['flow','approaches'].includes(layer.id)
      ? (p.scalar_detail?.road_closure ? 'Road closed' : `${p.scalar_detail?.speed_kmh} km/h · ${p.value}% of free flow`)
      : `${typeof p.value === "number" ? p.value.toLocaleString() : p.value} ${layer.unit}`;
    $("discovery-feature-period").textContent = p.period || layer.period;
    const details = $("discovery-feature-details"); details.replaceChildren();
    const link = document.createElement("a"); link.textContent = source.label; link.href = source.url; link.target = "_blank"; link.rel = "noopener"; details.append(link);
    const date = `Source date: ${source.observed_at || source.published_at || "not supplied"}${source.published_at && !source.observed_at ? " (publication, not acquisition)" : ""}. Retrieved: ${source.retrieved_at || "not recorded"}.`;
    const detail=p.scalar_detail ?? {}, rows=[];
    if (p.summary) rows.push(p.summary);
    if (['flow','approaches'].includes(layer.id)) {
      if (layer.id === 'approaches') rows.push(`${detail.member_count} connected portions; speeds range from ${detail.speed_min_kmh} to ${detail.speed_max_kmh} km/h. No unobserved connectors are included.`);
      rows.push(`Direction: ${detail.direction_verified ? detail.direction+'bound; checked against OpenLR anchors' : 'unresolved; no direction inferred'}.`);
      rows.push(`Displayed road length: ${detail.length_m} m. Estimated speed: ${detail.speed_kmh} km/h. Derived free-flow reference: ${detail.free_flow_kmh ?? 'unavailable'} km/h.`);
      rows.push(detail.time_penalty_s == null ? 'Travel-time penalty unavailable for this stopped, closed or unsupported segment.' : `Screened travel-time penalty: ${detail.time_penalty_s} seconds over this displayed length (${detail.travel_time_s} seconds versus ${detail.free_flow_time_s} seconds at derived free flow).`);
      rows.push(detail.baseline, detail.speed_basis, 'Per-segment confidence and observation time: not supplied. '+detail.road_name_method+'.');
    }
    if (detail.interval) rows.push(`Reporting interval: ${detail.interval}`);
    for (const [key,label] of [['upstream_elevation_m','Terrain elevation at path start'],['downstream_elevation_m','Terrain elevation at path end'],['elevation_m','Terrain elevation'],['drop_m','Elevation drop along path'],['path_length_m','Mapped path length']]) {
      if(detail[key] != null) rows.push(`${label}: ${detail[key].toLocaleString()} m${key.includes('elevation')?' (NAVD88)':''}.`);
    }
    if (detail.window_edge_contribution != null) rows.push(`Contributions from the DEM window edge: ${detail.window_edge_contribution?'yes; contributing area is incomplete':'none detected; still limited to this DEM window'}.`);
    if (detail.county_context) rows.push(`County catchment context: ${detail.county_context}.`);
    if (detail.classification) rows.push(detail.classification);
    if (detail.interpolation) rows.push(`Rainfall method: ${detail.interpolation}.`);
    if (detail.bracketing_contours_in) rows.push(`Surrounding rainfall contours: ${detail.bracketing_contours_in.join('–')} inches.`);
    if (detail.outfall_reference) rows.push(`County outfall reference: ${detail.outfall_reference}. This does not verify a connection from this site.`);
    if (detail.scope) rows.push(detail.scope);
    for (const text of [date,layer.method,layer.limitations,...rows]) {
      const row = document.createElement("p"); row.textContent = text; details.append(row);
    }
  }
  map.on("discoveryselect", (selected) => {
    if (selected.workflow !== workflow) return;
    const [lng,lat] = selected.feature.properties.center;
    if (coverage && !insideCoverage(L.latLng(lat,lng))) { setStatus("This feature lies outside available imagery coverage."); return; }
    cancelAnalysis();
    selectSite(L.latLng(lat,lng));
    site[workflow].discovery = selected;
    site[workflow].brief = workflow === "water"
      ? "Use the selected discovery evidence to screen a rain garden. Map a draft where the site evidence supports it and explain what still needs verification."
      : "Investigate this current surface-street slowdown and nearby source evidence. Explain estimated speed versus free flow and identify physical opportunities to investigate. Keep historical turning demand, recurring congestion and modeled emissions separate from this snapshot.";
    inputsChanged(site[workflow]);
    $("planning-brief").value = site[workflow].brief;
    renderDiscoveryContext(selected);
    setStatus("Discovery evidence added to this site's brief. Analyze when ready.");
  });
  map.on('discoveryexpired', ({version}) => {
    const selected = site?.street?.discovery;
    if (workflow === 'street' && ['flow','approaches'].includes(selected?.reference?.layer) && selected.reference.version === version) {
      $("discovery-feature-period").textContent = 'Snapshot expired. Refresh current traffic and select a road before analyzing.';
      setStatus('Traffic snapshot expired; refresh and select a current road.');
    }
  });
  map.on("plannerproperty", ({ property, searched }) => {
    if (!$("planner").hidden && (searched || (!picking && !draft))) {
      const center = L.latLng(property.lat, property.lon), error = pointError(center);
      if (error) { setStatus(error); return; }
      selectSite(center, property);
    }
  });
  function showWorkspace({ mode, visible }) {
    if (visible && workspaceVisible && mode === workflow) return;
    workspaceVisible = visible;
    if (mode !== workflow || !visible) cancelAnalysis();
    finishDrawing();
    setPicking(false);
    if (visible) {
      workflow = mode;
      overlays.addTo(map);
      showWorkflow();
      refreshProjects();
      map.fire("plannersite", site ? { siteId: site.key, center: site.center, workflow, property:site.property, inputRevision: site[workflow].revision ?? 0 } : { workflow });
      setStatus(site ? "" : "Search for a property or pick any covered location.");
      if (site) $("site-card").scrollIntoView({ block: "start" });
    } else {
      overlays.remove();
      $("watershed-legend").hidden = true;
    }
  }
  map.on("plannerworkspace", showWorkspace);
  // app.js may have selected a workspace from a direct link before we subscribed.
  showWorkspace({ mode: planningMode, visible: !$("planner").hidden });
  refreshProjects();
  try {
    const saved=localStorage.getItem(`planning-project-${workflow}`);
    if(saved && !site) openProject(saved);
  } catch {}
  window.addEventListener('pagehide', () => {
    if(activeAnalysis) cancelSiteAnalysis(activeAnalysis.serverRunId);
    if(site?.[workflow]?.saveTimer) saveProject(site,workflow).catch(()=>{});
  });
  $("retry-hydrology").addEventListener("click", () => loadHydrology(site, true));
  $("show-watershed").addEventListener("change", showRainfall);
  $("return-to-site").addEventListener("click", () => map.setView(site.center, 17));
  $("view-watershed").addEventListener("click", () => {
    $("show-watershed").checked = true;
    showRainfall();
    const bounds = watershedLayer.getBounds();
    if (!bounds.isValid()) return;
    // Keep the selected, covered site at the center even for a county polygon
    // extending beyond our Vexcel area; the imagery coverage guard still applies.
    const latRadius = Math.max(Math.abs(bounds.getNorth() - site.center.lat), Math.abs(bounds.getSouth() - site.center.lat));
    const lngRadius = Math.max(Math.abs(bounds.getEast() - site.center.lng), Math.abs(bounds.getWest() - site.center.lng));
    const extent = L.latLngBounds([site.center.lat - latRadius, site.center.lng - lngRadius],
      [site.center.lat + latRadius, site.center.lng + lngRadius]);
    map.setView(site.center, Math.min(14, map.getBoundsZoom(extent, false, L.point(48, 48))));
  });
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
    if (!draft || draft.coordinateError) return;
    const distinct = new Set(draft.points.map(({ lat, lng }) => `${lat.toFixed(7)},${lng.toFixed(7)}`));
    if (distinct.size < (featureTypes[draft.kind].line ? 2 : 3)) {
      mapHint("Place each point in a different location before saving.");
      return;
    }
    const error = draft.points.map(point => pointError(point, true)).find(Boolean);
    if (error) {
      mapHint(error);
      return;
    }
    if (draft.feature) draft.feature.points = draft.points;
    else site[workflow].features.push({ kind: draft.kind, points: draft.points });
    inputsChanged(site[workflow]);
    const label = featureTypes[draft.kind].label;
    finishDrawing();
    setStatus(`${label} saved.`);
  });
  for (const [id, field] of [["rain-depth", "depth"], ["rain-source", "source"]]) {
    $(id).addEventListener("input", ({ target }) => {
      site.water[field] = target.value;
      site.water.rainEdited = true;
      inputsChanged(site.water);
    });
  }
  for(const [id,key] of Object.entries(waterFields)) {
    $(id).addEventListener(['layout','placement','drainageAssumption','protectAccess'].includes(key)?'change':'input',({target})=>{
      if(!site || workflow!=='water')return;
      site.water.stormwaterSettings={...waterDefaults,...site.water.stormwaterSettings,
        [key]:key==='protectAccess'?Boolean(target.checked):target.value};
      $('water-what-if-note').hidden=site.water.stormwaterSettings.drainageAssumption!=='marked_connected';
      $('water-runoff-coefficient').disabled=site.water.stormwaterSettings.drainageAssumption!=='marked_connected';
      inputsChanged(site.water);
    });
  }
  $("planning-brief").addEventListener("input", ({ target }) => { site[workflow].brief = target.value; inputsChanged(site[workflow]); });
})();
