/* Existing-site walkthrough only. This controller never renders a proposed design
 * or treats a cross-origin iframe load event as verification of scan coverage.
 */
(() => {
  const PROPERTY_ID = "6067080", MODEL_ID = "35LT5s1GSfA", SITE_ID = `property:${PROPERTY_ID}`;
  const dialog = $("site-view-dialog"), open = $("open-site-view");
  let selectedSite = null, workflow = planningMode, descriptor = null;
  let request = 0, controller = null, frame = null, pending = false, selecting = false, returnFocus = null;

  function validate(value) {
    const property = value?.property, scan = value?.scan;
    if (value?.status !== "linked" || property?.id !== PROPERTY_ID || scan?.modelId !== MODEL_ID ||
        !Number.isFinite(property.lat) || !Number.isFinite(property.lon) ||
        property.lat < 33.70 || property.lat > 34.35 || property.lon < -118.67 || property.lon > -118.10 ||
        typeof property.name !== "string" || !property.name.trim() ||
        typeof property.address !== "string" || !property.address.trim() ||
        typeof scan.title !== "string" || !scan.title.trim()) throw new Error("The site and walkthrough association could not be verified.");
    let url;
    try { url = new URL(scan.url); } catch { throw new Error("The walkthrough URL is invalid."); }
    if (url.origin !== "https://my.matterport.com" || url.pathname !== "/show/" || url.username || url.password || url.hash ||
        url.searchParams.getAll("m").length !== 1 || url.searchParams.get("m") !== MODEL_ID ||
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
    else open.focus({preventScroll:true});
  }
  function cleanup() {
    controller?.abort(); controller = null; ++request;
    pending = false; descriptor = null;
    cleanupFrame();
    open.disabled = false;
    $("site-view-retry").disabled = true;
    $("site-view-proposed").disabled = true;
    $("site-view-external").removeAttribute("href");
  }
  function closeView() {
    const active = dialog.open || pending || Boolean(returnFocus);
    const wasPending = pending;
    cleanup();
    if (wasPending) $("site-view-entry-status").textContent = "Linked CoStar exterior walkthrough · existing conditions only.";
    if (dialog.open) dialog.close();
    if (active && returnFocus) restoreFocus();
  }
  function status(message, error = false) {
    $("site-view-status").textContent = message;
    $("site-view-status").setAttribute("data-error", String(error));
  }
  function loadFrame() {
    if (!descriptor || !dialog.open || selectedSite !== SITE_ID) return;
    cleanupFrame();
    const token = request, current = document.createElement("iframe");
    frame = current;
    current.title = `${descriptor.scan.title} · ${descriptor.property.address}`;
    current.setAttribute("allow", "fullscreen");
    current.setAttribute("allowfullscreen", "");
    current.referrerPolicy = "no-referrer";
    current.addEventListener("load", () => {
      if (frame !== current || token !== request || !dialog.open) return;
      status("Explore the linked exterior tour. If it is blank or unavailable, retry or open it in a new tab.");
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
    const source = value.source ?? {};
    const date = typeof source.attachmentDate === "string" ? new Date(source.attachmentDate) : null;
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
    if (pending || dialog.open) return;
    controller?.abort(); controller = new AbortController();
    const token = ++request, mode = workflow;
    pending = true; returnFocus = document.activeElement || open;
    open.disabled = true; $("site-view-entry-retry").hidden = true;
    $("site-view-entry-status").textContent = "Checking the property’s linked exterior walkthrough…";
    try {
      const value = validate(await json("/api/site-view", {signal:controller.signal}));
      if (token !== request || workflow !== mode) return;
      selecting = true;
      try { selectProperty(value.property); } finally { selecting = false; }
      if (token !== request || workflow !== mode || selectedSite !== SITE_ID) throw new Error("Select the linked property inside available imagery coverage before opening its walkthrough.");
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
      if (token === request) { pending = false; open.disabled = false; controller = null; }
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
  map.on("plannersite", event => {
    const next = event.siteId ?? null, mode = event.workflow ?? workflow;
    const changed = next !== selectedSite || mode !== workflow;
    selectedSite = next; workflow = mode;
    if (changed && !(selecting && next === SITE_ID)) {
      if (pending || dialog.open) closeView();
      $("site-view-entry-status").textContent = "Linked CoStar exterior walkthrough · existing conditions only.";
    }
  });
  map.on("plannerworkspace", event => {
    if (event.mode !== workflow || event.visible === false) {
      workflow = event.mode;
      if (pending || dialog.open) closeView();
    }
  });
})();
