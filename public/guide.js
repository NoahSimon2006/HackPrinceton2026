/* Guided assistant: one planning step at a time, always saying what comes next.
 * Presentation only. It reads state the controllers already publish (element
 * visibility and map events); it never sends requests or changes planning data.
 */
(() => {
  const root = $('guide');
  const steps = ['focus', 'place', 'site', 'brief', 'results'];
  // Detail views opened from a step. The map view is a utility open from any step.
  const details = {settings:'brief', rain:'brief', markings:'brief', map:null};
  const methods = ['scout', 'direct', 'saved'];
  const tabs = ['assessment', 'design', 'evidence', 'project'];
  let step = 'focus', detail = null, method = 'scout', tab = 'assessment';
  let acted = false, lastSite = null, expectSiteUntil = 0, pending = null;

  const shown = id => !$(id).hidden;
  const hasSite = () => shown('site-card');
  const running = () => shown('cancel-site-analysis');
  const hasAssessment = () => shown('agent-assessment') || $('activity-list').children.length > 0;
  const hasDesign = () => ['proposal-review', 'water-design-review', 'traffic-comparison', 'proposal-result-message'].some(shown);
  // The saved-project route is offered only when there is a project to open.
  const hasSaved = () => $('saved-projects').children.length > 1;
  const water = () => $('workspace-water').getAttribute('aria-pressed') === 'true';
  // Steps after Place describe one site, so they need one.
  const canEnter = name => name === 'focus' || name === 'place' || hasSite();
  const heading = view => view === 'focus' ? 'planner-title' : `guide-title-${view}`;
  let wasRunning = running();

  function remember() {
    try { sessionStorage.setItem('planning-guide', JSON.stringify({step, method, tab})); } catch {}
  }

  // What the footer offers and says for the visible view.
  function prompt(view, {site, busy, results}) {
    if (view === 'map') return {next:'Done'};
    if (details[view]) return {next:'Done', hint:'Changes save with this project.'};
    if (view === 'focus') return {next:'Continue', hint:'Next: find a place to work on.'};
    if (view === 'place') {
      if (method === 'scout') return {back:true, skip:site ? 'Keep current site' : '',
        hint:shown('scout-cancel') ? 'The agent is investigating this area. Locations appear above.'
          : Number($('scout-results').getAttribute('data-selectable-count')) > 0 ? 'Choose a location to continue.'
          : $('scout-results').children.length ? 'Find locations again, or pick a spot directly.'
          : 'Describe a goal, frame the map, then find locations.'};
      // The planner's own status line already says how to set a site; don't repeat it.
      if (method === 'direct') return {back:true, next:'Continue', enabled:site,
        hint:site ? 'Site set. Continue to check it.' : $('planner-status').textContent ? '' : 'Set a site to continue.'};
      return {back:true, next:'Continue', enabled:site,
        hint:site ? 'Continue with the current site, or open another project.' : 'Open a saved project to continue.'};
    }
    if (view === 'site') return {back:true, next:'Continue', skip:results || busy ? 'See results' : '', hint:'Next: brief the agent.'};
    if (view === 'brief') return {back:true, skip:results || busy ? 'See results' : '',
      hint:busy ? 'The agent is working. See results for its progress.'
        : $('run-site-analysis').disabled ? 'Checking the site. Analysis unlocks in a moment.'
        : results ? 'Change the brief or a detail, then run the project again.' : 'Next: analyze the site.'};
    // While the agent runs, the only action offered is the controller's own Cancel.
    if (busy) return {hint:'The agent is working. Findings appear here as they arrive.'};
    return {skip:'New site', next:'Refine brief',
      hint:results ? 'Refine the brief to revise, or start on another site.'
        : 'No results yet. Refine the brief, then analyze the site.'};
  }

  function render() {
    const view = detail ?? step, site = hasSite(), busy = running();
    const assessment = hasAssessment(), design = hasDesign();
    for (const [name, value] of [['step', step], ['view', view], ['method', method], ['tab', tab],
      ['assessment', assessment], ['design', design]]) root.setAttribute(`data-${name}`, String(value));
    const current = steps.indexOf(step);
    steps.forEach((name, index) => {
      const button = $(`guide-step-${name}`);
      button.disabled = !canEnter(name);
      if (name === step) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
      button.setAttribute('data-done', String(index < current));
    });
    for (const name of methods) $(`guide-method-${name}`).setAttribute('aria-pressed', String(name === method));
    for (const name of tabs) $(`guide-tab-${name}`).setAttribute('aria-pressed', String(name === tab));
    $('guide-map').setAttribute('aria-pressed', String(detail === 'map'));
    $('guide-method-saved').hidden = !hasSaved();
    $('guide-resume').hidden = !site;
    $('guide-resume-name').textContent = $('site-name').textContent;
    const markings = $('shape-list').children.length;
    $('guide-markings-count').textContent = markings
      ? `${markings} saved ${markings === 1 ? 'marking' : 'markings'}` : 'Outline areas to keep clear or consider';
    const {back = false, next = '', enabled = true, skip = '', hint = ''} = prompt(view, {site, busy, results:assessment || design});
    $('guide-back').hidden = !back;
    $('guide-next').hidden = !next;
    $('guide-next').textContent = next || 'Continue';
    $('guide-next').disabled = !enabled;
    $('guide-skip').hidden = !skip;
    $('guide-skip').textContent = skip;
    // Leave unchanged text alone so the live region only announces new prompts.
    if ($('guide-hint').textContent !== hint) $('guide-hint').textContent = hint;
  }

  function show(name, {focus = false, into = null} = {}) {
    step = canEnter(name) ? name : 'place';
    detail = into;
    remember(); render();
    $('planner').scrollTop = 0;
    if (focus) $(heading(detail ?? step)).focus({preventScroll:true});
  }
  function openDetail(name) {
    show(details[name] ?? step, {focus:true, into:name});
  }
  function closeDetail() {
    const opener = detail === 'map' ? 'guide-map' : `guide-open-${detail}`;
    detail = null; render();
    $('planner').scrollTop = 0;
    $(opener).focus({preventScroll:true});
  }

  // Follow what the controllers publish without asking them to know about steps.
  function sync() {
    const busy = running();
    if (busy && !wasRunning && step === 'brief') {
      step = 'results'; detail = null; tab = 'assessment';
      $('agent-activity').open = true;
      $('planner').scrollTop = 0;
      remember();
    }
    // Once the assessment is in, fold the activity log so the findings lead.
    if (!busy && wasRunning && shown('agent-assessment')) $('agent-activity').open = false;
    wasRunning = busy;
    if (pending && canEnter(pending.step)) { ({step, method, tab} = pending); detail = null; pending = null; }
    if (!canEnter(step)) { step = 'place'; detail = null; }
    if (method === 'saved' && !hasSaved()) method = 'scout';
    if (!water() && (detail === 'settings' || detail === 'rain')) detail = null;
    render();
  }

  for (const name of steps) $(`guide-step-${name}`).addEventListener('click', () => show(name, {focus:true}));
  for (const name of methods) $(`guide-method-${name}`).addEventListener('click', () => { method = name; remember(); render(); });
  for (const name of tabs) $(`guide-tab-${name}`).addEventListener('click', () => { tab = name; remember(); render(); });
  for (const name of ['settings', 'rain', 'markings']) $(`guide-open-${name}`).addEventListener('click', () => openDetail(name));
  $('guide-map').addEventListener('click', () => detail === 'map' ? closeDetail() : openDetail('map'));
  $('guide-back').addEventListener('click', () => show(steps[Math.max(0, steps.indexOf(step) - 1)], {focus:true}));
  $('guide-next').addEventListener('click', () => {
    if (detail) closeDetail();
    else show(step === 'results' ? 'brief' : steps[steps.indexOf(step) + 1], {focus:true});
  });
  $('guide-skip').addEventListener('click', () =>
    show(step === 'place' ? 'site' : step === 'results' ? 'place' : 'results', {focus:true}));
  $('guide-resume-open').addEventListener('click', () =>
    show(hasAssessment() || hasDesign() || running() ? 'results' : 'brief', {focus:true}));

  // A new site moves the assistant to the site check. A project restored while
  // the page loads is not the user's move, so it only offers "Resume".
  map.on('plannersite', event => {
    const id = event.siteId ?? null, changed = Boolean(id) && id !== lastSite;
    if (id) lastSite = id;
    if (id && acted && (changed || Date.now() < expectSiteUntil)) { expectSiteUntil = 0; show('site'); }
    else sync();
  });
  // Reopening the site already selected publishes no change, yet is still a request to continue.
  const expectSite = () => { expectSiteUntil = Date.now() + 20000; };
  map.on('scoutselect', expectSite);
  $('open-project').addEventListener('click', expectSite);
  // Results belong to one focus. After switching, return to the brief unless
  // this focus already has results for the site.
  map.on('plannerworkspace', () => {
    if (step === 'results' && !running() && !hasAssessment() && !hasDesign()) { step = 'brief'; detail = null; remember(); }
    sync();
  });

  // Controllers "open" the evidence section before scrolling to a source. That
  // section is a results tab here, so opening it shows the tab first.
  Object.defineProperty($('site-tools'), 'open', {configurable:true,
    get: () => step === 'results' && tab === 'evidence' && !detail,
    set(value) { if (value) { tab = 'evidence'; show('results'); } }});

  document.addEventListener('click', event => {
    // A numbered map marker scrolls to its researched location; show that list first.
    if (event.target?.closest?.('.scout-map-number')) { method = 'scout'; show('place'); }
  }, true);
  for (const type of ['pointerdown', 'keydown']) document.addEventListener(type, () => { acted = true; pending = null; }, true);

  if (typeof MutationObserver === 'function') {
    const observer = new MutationObserver(sync);
    for (const id of ['site-card', 'site-name', 'cancel-site-analysis', 'run-site-analysis', 'agent-assessment', 'activity-list',
      'proposal-review', 'water-design-review', 'traffic-comparison', 'proposal-result-message',
      'scout-cancel', 'scout-results', 'planner-status', 'shape-list', 'saved-projects'])
      observer.observe($(id), {attributes:true, attributeFilter:['hidden', 'disabled', 'aria-pressed', 'data-selectable-count'], childList:true});
  }

  // Synthetic test fixtures are a developer tool, reachable only with ?dev in the address.
  $('proposal-development').hidden = !/[?&]dev\b/.test(typeof location === 'object' ? location.search : '');

  // A reload in the same tab returns to the step in progress once its site is restored.
  try {
    const saved = JSON.parse(sessionStorage.getItem('planning-guide'));
    if (steps.includes(saved?.step) && methods.includes(saved.method) && tabs.includes(saved.tab)) pending = saved;
  } catch {}
  sync();
})();
