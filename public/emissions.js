// Simulated idling and emissions: map layer, ranked roads and per-segment detail.
// Values come from an uncalibrated SUMO run (public/data/sim.json); all text is inserted as text.
(() => {
  const el = (id) => document.getElementById(id);
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
  const measures = {
    idle_veh_h: {label:'Total idling', unit:'vehicle-hours in the hour', digits:1, perVehicle:false},
    idle_s: {label:'Idling per vehicle', unit:'seconds stopped per vehicle', digits:0, perVehicle:true},
    stopped_share: {label:'Share of time stopped', unit:'% of time on the segment', digits:0, perVehicle:true, percent:true},
    co2_kg_km: {label:'CO₂ per km of road', unit:'kg per km in the hour', digits:0, perVehicle:false},
    co2_g_vkm: {label:'CO₂ per vehicle-km', unit:'g per vehicle-km', digits:0, perVehicle:true},
    nox_g_km: {label:'NOx per km of road', unit:'g per km in the hour', digits:0, perVehicle:false},
  };
  const ramp = ['#fff3b0', '#fdc66b', '#f98e3c', '#e4502c', '#a8182b', '#5c0a2e'];
  const basisText = {counted:'LADOT count', assumed:'assumed volume', unconstrained:'no volume target'};
  let sim, layer, renderer, lines = new Map(), breaks = [];
  const period = () => el('sim-period').value, measure = () => el('sim-measure').value;
  const fmt = (key, value) => { const m = measures[key]; return (m.percent ? value * 100 : value).toLocaleString('en-US', {maximumFractionDigits:m.digits}) + (m.percent ? '%' : ''); };
  const title = (s) => `${s.name} ${s.dir}${s.toward ? ` toward ${s.toward}` : ''}`;

  function visible() {
    const freeways = el('sim-freeways').checked, key = measure(), min = measures[key].perVehicle ? 100 : 0;
    return Object.entries(sim.segments).filter(([, s]) => s.data[period()] && (freeways || s.class !== 'motorway') && s.data[period()].flow >= min);
  }
  function colourOf(value) { let i = 0; while (i < breaks.length && value > breaks[i]) i++; return ramp[i]; }
  function detail(id) {
    const s = sim.segments[id], d = s.data[period()], box = node('div', undefined, 'sim-popup');
    box.append(node('strong', title(s)), node('p', `${sim.periods[period()].label} · simulated`, 'note'));
    const list = node('ul');
    [['Idling per vehicle', `${fmt('idle_s', d.idle_s)} s`], ['Time stopped', fmt('stopped_share', d.stopped_share)], ['Total idling', `${fmt('idle_veh_h', d.idle_veh_h)} vehicle-hours`],
     ['Speed', `${d.speed_kmh} km/h (${Math.round(d.speed_ratio * 100)}% of free flow)`], ['Flow', `${d.flow.toLocaleString()} vehicles/hour · ${s.lanes} ${s.lanes === 1 ? 'lane' : 'lanes'}`],
     ['CO₂', `${fmt('co2_g_vkm', d.co2_g_vkm)} g per vehicle-km · ${fmt('co2_kg_km', d.co2_kg_km)} kg per km`], ['NOx', `${fmt('nox_g_km', d.nox_g_km)} g per km`],
     ['Traffic volume basis', basisText[d.basis]]].forEach(([k, v]) => { const li = node('li'); li.append(node('span', k + ': ', 'note'), document.createTextNode(v)); list.append(li); });
    box.append(list);
    box.append(node('strong', d.causes.length ? 'Why vehicles idle here' : 'No idling cause flagged'));
    d.causes.forEach(c => box.append(node('p', c.text)));
    if (d.idle_spread !== undefined && d.idle_spread > 0.5) box.append(node('p', 'Idling here varied a lot between simulation runs; treat it as unstable.', 'note'));
    return box;
  }
  function draw() {
    if (!sim || typeof map === 'undefined' || !map) return;
    const key = measure(), rows = visible(), values = rows.map(([, s]) => s.data[period()][key]).sort((a, b) => a - b);
    breaks = [.3, .55, .75, .9, .97].map(q => values[Math.min(values.length - 1, Math.floor(q * values.length))] ?? 0);
    layer.clearLayers(); lines.clear();
    for (const [id, s] of rows) {
      const value = s.data[period()][key];
      const line = L.polyline(s.shape, {renderer, color:colourOf(value), weight:Math.min(7, 2 + s.lanes), opacity:.9}).addTo(layer);
      line.on('click', (event) => L.popup({maxWidth:340}).setLatLng(event.latlng).setContent(detail(id)).openOn(map));
      lines.set(id, line);
    }
    const scale = el('sim-scale'); scale.replaceChildren();
    ramp.forEach((colour, i) => { const item = node('span', i === 0 ? `≤ ${fmt(key, breaks[0])}` : i === ramp.length - 1 ? `> ${fmt(key, breaks[i - 1])}` : `${fmt(key, breaks[i])}`); item.style.setProperty('--swatch', colour); scale.append(item); });
    el('sim-legend-title').textContent = `${measures[key].label} · ${measures[key].unit}`;
    el('sim-legend-period').textContent = `${sim.periods[period()].label} · simulated, not measured`;
    rank(rows, key);
  }
  function rank(rows, key) {
    const body = el('sim-ranking'); body.replaceChildren();
    rows.sort((a, b) => b[1].data[period()][key] - a[1].data[period()][key]).slice(0, 25).forEach(([id, s], i) => {
      const d = s.data[period()], tr = node('tr'); tr.tabIndex = 0;
      [String(i + 1), title(s), fmt(key, d[key]), `${fmt('idle_s', d.idle_s)} s`, fmt('stopped_share', d.stopped_share), fmt('co2_g_vkm', d.co2_g_vkm), d.flow.toLocaleString(), basisText[d.basis], d.causes[0]?.text || '—']
        .forEach(text => tr.append(node('td', text)));
      const go = () => { el('sim-toggle').checked = true; toggle(); const line = lines.get(id); if (!line) return; map.stop(); map.flyToBounds(line.getBounds(), {maxZoom:17, duration:.6}); L.popup({maxWidth:340}).setLatLng(line.getBounds().getCenter()).setContent(detail(id)).openOn(map); el('map').scrollIntoView({block:'center', behavior:'smooth'}); };
      tr.addEventListener('click', go); tr.addEventListener('keydown', (event) => { if (event.key === 'Enter') go(); });
      body.append(tr);
    });
    el('sim-measure-head').textContent = measures[key].label;
    el('sim-status').textContent = `${rows.length.toLocaleString()} road segments · ${measures[key].perVehicle ? 'segments under 100 vehicles an hour are left out of per-vehicle rankings · ' : ''}select a row to see it on the map.`;
  }
  function toggle() {
    if (!layer) return;
    const on = el('sim-toggle').checked;
    if (on) layer.addTo(map); else layer.remove();
    el('sim-legend').hidden = !on;
  }
  // Exposed for the design chat: the approaches into a catalogued intersection.
  window.simProfile = (siteName) => sim?.sites[siteName]?.map(id => ({id, ...sim.segments[id]})) || null;

  fetch('/data/sim.json').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => {
    sim = data;
    el('sim-panel').hidden = false;
    const select = el('sim-period'); select.replaceChildren();
    Object.entries(sim.periods).forEach(([key, p]) => { const o = node('option', p.label); o.value = key; select.append(o); });
    const pick = el('sim-measure'); pick.replaceChildren();
    Object.entries(measures).forEach(([key, m]) => { const o = node('option', m.label); o.value = key; pick.append(o); });
    el('sim-method').textContent = `${sim.method.engine}. Traffic: ${sim.method.demand}. ${sim.method.signals}. Emissions: ${sim.method.emission_model}. ${sim.method.caveat}`;
    const seeds = Math.min(...Object.values(sim.periods).map(p => p.seeds));
    if (seeds < 3) el('sim-method').textContent += ` Based on ${seeds} simulation run${seeds === 1 ? '' : 's'} per period, so rankings have not been checked for stability.`;
    if (typeof map !== 'undefined' && map && window.L) {
      renderer = L.canvas({padding:.3, tolerance:6}); layer = L.layerGroup();
      el('sim-toggle').disabled = false;
    }
    draw();
    ['sim-period', 'sim-measure', 'sim-freeways'].forEach(id => el(id).addEventListener('change', draw));
    el('sim-toggle').addEventListener('change', toggle);
  }).catch(() => {
    el('sim-toggle').disabled = true;
    el('sim-toggle').parentElement.title = 'Run the simulation scripts to enable this layer.';
  });
})();
