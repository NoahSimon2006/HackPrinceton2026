/* Proposal rendering is local and independent from the existing text assessment.
 * Backend proposal.Proposal is the canonical typed, validated contract.
 * @typedef {{site_id:string,workflow:'street'|'water',revision:number,input_revision:number,input_hash:string,development_fixture:boolean,geometry:Array,metrics:Array,recommendation:string}} Proposal
 */
(() => {
  map.createPane("proposal");
  map.getPane("proposal").style.zIndex = 610;
  map.getPane("proposal").style.pointerEvents = "none";
  let selected = null, published = null, layer = null, request = 0, controller;
  const show = $("show-proposal");
  function visible() {
    if (!layer) return;
    if (show.checked) layer.addTo(map); else layer.remove();
  }
  function clear(event) {
    controller?.abort(); ++request;
    selected = event.siteId ? event : null;
    published = null; layer?.remove(); layer = null;
    show.checked = false; show.disabled = true;
    $("proposal-review").hidden = true;
    $("proposal-stale").hidden = true;
    $("load-proposal-fixture").disabled = !selected;
    $("revise-proposal-fixture").disabled = true;
    $("proposal-map-caption").textContent = "No published proposal";
    $("proposal-message").textContent = selected ? "Preview uses synthetic geometry, never live results." : "Select a site to test the proposal overlay.";
  }
  function validate(p, site, revision) {
    if (p.schema_version !== 1 || p.development_fixture !== true || p.site_id !== site.siteId || p.workflow !== site.workflow || p.revision !== revision || p.input_revision !== site.inputRevision) throw new Error("Proposal identity mismatch.");
    if (!p.geometry?.length || !p.metrics?.length || p.geometry.some(g => g.properties.revision !== revision) || p.metrics.some(m => m.revision !== revision || m.input_hash !== p.input_hash)) throw new Error("Proposal revision mismatch.");
    const area = p.metrics.find(m => m.id === "footprint_area");
    if (!area || !Number.isFinite(area.proposed)) throw new Error("Missing footprint measurement.");
    return area;
  }
  async function preview(revise = false) {
    if (!selected) return;
    controller?.abort(); controller = new AbortController();
    const token = ++request, site = { ...selected }, revision = revise && published ? published.revision + 1 : (published?.revision ?? 0) + 1;
    $("proposal-message").textContent = "Preparing local UI fixture…";
    $("load-proposal-fixture").disabled = $("revise-proposal-fixture").disabled = true;
    try {
      const query = new URLSearchParams({lon:site.center.lng,lat:site.center.lat,workflow:site.workflow,site_id:site.siteId,revision,input_revision:site.inputRevision});
      const p = await json(`/api/proposal-fixture?${query}`, { signal: controller.signal });
      if (token !== request) return;
      const area = validate(p, site, revision);
      const replacement = L.geoJSON({type:"FeatureCollection",features:p.geometry}, {pane:"proposal",interactive:false,style:{color:"#e0c4ff",weight:3,dashArray:"7 4",fillColor:"#b388ff",fillOpacity:.42}});
      // Publish geometry, displayed measurements and revision in one synchronous turn.
      layer?.remove(); layer = replacement; published = p;
      show.disabled = false; show.checked = true; visible();
      map.setView(site.center, Math.max(map.getZoom(), 19), {animate:false});
      $("proposal-review").hidden = false;
      $("proposal-title").textContent = site.workflow === "street" ? "Test island footprint" : "Test treatment footprint";
      $("proposal-summary").textContent = p.recommendation;
      $("proposal-area").textContent = `${area.proposed.toFixed(1)} ${area.unit}`;
      $("proposal-revision").textContent = `Revision ${p.revision} · inputs ${p.input_revision} · ${p.input_hash.slice(0,8)}`;
      $("proposal-map-caption").textContent = `DEVELOPMENT FIXTURE · revision ${p.revision}`;
      $("proposal-stale").hidden = true;
      $("proposal-message").textContent = "Purple dashed outline = UI fixture. Access, overlap and benefits remain unassessed.";
    } catch (error) {
      if (token === request && error.name !== "AbortError") $("proposal-message").textContent = `Preview unavailable: ${error.message}`;
    } finally {
      if (token === request) { $("load-proposal-fixture").disabled = !selected; $("revise-proposal-fixture").disabled = !published; }
    }
  }
  show.addEventListener("change", visible);
  $("load-proposal-fixture").addEventListener("click", () => preview());
  $("revise-proposal-fixture").addEventListener("click", () => preview(true));
  map.on("plannersite", clear);
  map.on("plannerinputs", ({inputRevision}) => {
    if (!selected) return;
    selected = {...selected,inputRevision}; controller?.abort(); ++request;
    $("load-proposal-fixture").disabled = false;
    $("revise-proposal-fixture").disabled = !published;
    if (published) { $("proposal-stale").hidden = false; $("proposal-map-caption").textContent = `DEVELOPMENT FIXTURE · revision ${published.revision} · stale inputs`; }
  });
})();
