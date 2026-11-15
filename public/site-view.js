/* Existing-site walkthrough only. This controller never renders a proposed design
 * or treats a cross-origin iframe load event as verification of scan coverage.
 */
(() => {
  const dialog = $("site-view-dialog"), open = $("open-site-view");
  let selectedSite = null, selectedProperty = null, workflow = planningMode, descriptor = null;
  let request = 0, controller = null, frame = null, pending = false, returnFocus = null;

  function validate(value, propertyId) {
    const property = value?.property, scan = value?.scan;
    if (value?.status !== "linked" || property?.id !== propertyId || scan?.exteriorHint !== true || !/^[A-Za-z0-9]{11}$/.test(scan?.modelId ?? "") ||
        !Number.isFinite(property.lat) || !Number.isFinite(property.lon) ||
        property.lat < 33.70 || property.lat > 34.35 || property.lon < -118.67 || property.lon > -118.10 ||
        typeof property.name !== "string" || !property.name.trim() ||
        typeof property.address !== "string" || !property.address.trim() ||
        typeof scan.title !== "string" || !scan.title.trim()) throw new Error("The site and walkthrough association could not be verified.");
    let url;
    try { url = new URL(scan.url); } catch { throw new Error("The walkthrough URL is invalid."); }
    if (url.origin !== "https://my.matterport.com" || url.pathname !== "/show/" || url.username || url.password || url.hash ||
        url.searchParams.getAll("m").length !== 1 || url.searchParams.get("m") !== scan.modelId ||
        [...url.searchParams.keys()].some(key => key !== "m")) throw new Error("The walkthrough does not match this property's approved Matterport model.");
    return {...value, scan:{...scan,url:url.href}};
  }
  function cleanupFrame() {
    const old = frame; frame = null;
    if (old) old.removeAttribute("src");
    $("site-view-stage").replaceChildren();
  }
  function restoreFocus() {
    const target = returnFocus; returnFocus = null;
    if (target?.isConnected && !target.disabled && !target.hidden &&
        (!target.getClientRects || target.getClientRects().length) && typeof target.focus === "function") target.focus({preventScroll:true});
    else (open.disabled ? $("pick-site") : open).focus({preventScroll:true});
  }
  function cleanup() {
    controller?.abort(); controller = null; ++request;
    pending = false; descriptor = null;
    cleanupFrame();
    open.disabled = !selectedProperty;
    $("site-view-retry").disabled = true;
    $("site-view-proposed").disabled = true;
    $("site-view-external").removeAttribute("href");
  }
  function closeView() {
    const active = dialog.open || pending || Boolean(returnFocus);
    const wasPending = pending;
    cleanup();
    if (wasPending) entry();
    if (dialog.open) dialog.close();
    if (active && returnFocus) restoreFocus();
  }
  function status(message, error = false) {
    $("site-view-status").textContent = message;
    $("site-view-status").setAttribute("data-error", String(error));
  }
  function loadFrame() {
    if (!descriptor || !dialog.open || descriptor.property.id !== selectedProperty) return;
    cleanupFrame();
    const token = request, current = document.createElement("iframe");
    frame = current;
    current.title = `${descriptor.scan.title} · ${descriptor.property.address}`;
    current.setAttribute("allow", "fullscreen");
    current.setAttribute("allowfullscreen", "");
    current.referrerPolicy = "no-referrer";
    current.addEventListener("load", () => {
      if (frame !== current || token !== request || !dialog.open) return;
      status("Explore the linked tour. If it is blank or unavailable, retry or open it in a new tab.");
    });
    current.addEventListener("error", () => {
      if (frame !== current || token !== request || !dialog.open) return;
      cleanupFrame();
      status("The embedded view could not be opened. Retry, or open Matterport in a new tab.", true);
    });
    status("Opening Matterport… If the view stays blank or shows an error, retry or open it in a new tab.");
    $("site-view-retry").disabled = false;
    current.src = descriptor.scan.url;
    $("site-view-stage").append(current);
  }
  function fill(value) {
    $("site-view-title").textContent = value.property.address;
    $("site-view-tour-title").textContent = value.scan.title;
    const choices = $("site-view-tour-choice"); choices.replaceChildren();
    for (const scan of value.scans) {
      const option = document.createElement("option"); option.value = scan.modelId;
      option.textContent = scan.title; choices.append(option);
    }
    choices.value = value.scan.modelId;
    choices.disabled = value.scans.length < 2;
    const source = value.source ?? {};
    const date = typeof value.scan.attachmentDate === "string" ? new Date(value.scan.attachmentDate) : null;
    const dateLabel = date && Number.isFinite(date.getTime())
      ? date.toLocaleDateString(undefined, {year:"numeric",month:"short",day:"numeric"}) : null;
    $("site-view-source").textContent = [typeof source.provider === "string" ? source.provider : "CoStar property attachment",
      dateLabel ? `Attachment date: ${dateLabel}` : null].filter(Boolean).join(" · ");
    $("site-view-limitations").replaceChildren();
    if (typeof source.association === "string") {
      const item = document.createElement("li"); item.textContent = source.association; $("site-view-limitations").append(item);
    }
    for (const text of value.limitations ?? []) {
      if (typeof text !== "string") continue;
      const item = document.createElement("li"); item.textContent = text; $("site-view-limitations").append(item);
    }
    $("site-view-external").href = value.scan.url;
    $("site-view-proposed").disabled = true;
  }
  async function openView() {
    if (pending || dialog.open || !selectedProperty) return;
    controller?.abort(); controller = new AbortController();
    const token = ++request, mode = workflow, siteId = selectedSite, propertyId = selectedProperty;
    pending = true; returnFocus = document.activeElement || open;
    open.disabled = true; $("site-view-entry-retry").hidden = true;
    $("site-view-entry-status").textContent = "Checking exterior or site-context tours for this property…";
    try {
      const response = await json(`/api/site-view?propertyId=${encodeURIComponent(propertyId)}`, {signal:controller.signal});
      if (token !== request || workflow !== mode || selectedSite !== siteId || selectedProperty !== propertyId) return;
      if (["unavailable", "ambiguous"].includes(response?.status) && response.property?.id === propertyId) {
        $("site-view-entry-status").textContent = response.message || "No relevant exterior tour for the selected property.";
        open.disabled = false; restoreFocus(); return;
      }
      const value = validate(response, propertyId);
      if (!Array.isArray(value.scans) || !value.scans.length || value.scans.length > 100 ||
          new Set(value.scans.map(scan => scan.modelId)).size !== value.scans.length ||
          !value.scans.some(scan => JSON.stringify(scan) === JSON.stringify(value.scan))) throw new Error("Invalid tour choices.");
      value.scans = value.scans.map(scan => validate({...value, scan}, propertyId).scan);
      descriptor = value; fill(value);
      dialog.showModal();
      $("site-view-close").focus({preventScroll:true});
      $("site-view-entry-status").textContent = "Existing-site view only · intervention coverage and alignment are unverified.";
      loadFrame();
    } catch (error) {
      if (token !== request || error.name === "AbortError") return;
      cleanupFrame(); descriptor = null;
      $("site-view-entry-status").textContent = `Walkthrough unavailable: ${error.message}`;
      $("site-view-entry-retry").hidden = false;
      if (dialog.open) closeView();
      else { open.disabled = false; restoreFocus(); }
    } finally {
      if (token === request) { pending = false; open.disabled = !selectedProperty; controller = null; }
    }
  }
  open.addEventListener("click", openView);
  $("site-view-entry-retry").addEventListener("click", openView);
  $("site-view-retry").addEventListener("click", loadFrame);
  $("site-view-close").addEventListener("click", closeView);
  dialog.addEventListener("cancel", event => {event.preventDefault();closeView();});
  dialog.addEventListener("close", () => {
    if (dialog.open) return; // A queued close from an older opening cannot clear a new view.
    cleanup();
    if (returnFocus) restoreFocus();
  });
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeView();
  });
  function entry(property = null) {
    $("site-view-entry-title").textContent = property?.address || (selectedProperty ? "Selected property" : "Select a property");
    $("site-view-entry-status").textContent = selectedProperty
      ? "Check exterior, courtyard, loading-area or roof tours linked to this property. Interior-only tours are excluded."
      : "No property is assigned to this point. Choose a property or use the map evidence.";
    open.disabled = !selectedProperty;
    $("site-view-entry-retry").hidden = true;
  }
  function updateSelection(event) {
    const next = event.siteId ?? null, mode = event.workflow ?? workflow;
    const propertyId = event.property?.id ?? null;
    const changed = next !== selectedSite || mode !== workflow || propertyId !== selectedProperty;
    selectedSite = next; workflow = mode; selectedProperty = propertyId;
    if (changed) {
      if (pending || dialog.open) closeView();
      entry(event.property);
    }
  }
  map.on("plannersite", updateSelection);
  map.on("planneridentity", event => { if (event.siteId === selectedSite) updateSelection(event); });
  map.on("plannerworkspace", event => {
    if (event.mode !== workflow || event.visible === false) {
      workflow = event.mode;
      if (pending || dialog.open) closeView();
    }
  });
  $("site-view-tour-choice").addEventListener("change", event => {
    const scan = descriptor?.scans.find(item => item.modelId === event.target.value);
    if (!scan || descriptor.property.id !== selectedProperty) return;
    descriptor = {...descriptor, scan}; fill(descriptor); loadFrame();
  });
  entry();
})();
