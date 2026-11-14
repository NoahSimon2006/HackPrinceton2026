// Design chat with Grok, the before/after diagram, and the aerial overlay.
// All model and user content is inserted as text, never as HTML.
(() => {
  const el = (id) => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const chats = new Map();      // site name -> latest snapshot
  const shown = new Map();      // site name -> design version on display
  let site = null, revision = 0, pollTimer, lastKey = '', overlay, overlayOn = false, overlayCenter = null, simTimer;
  const sims = new Map();       // chat id + design version -> re-simulation run
  const roles = {lead:'Lead designer', 'crash-analyst':'Crash analyst', 'site-analyst':'Site analyst', 'guidance-researcher':'Guidance researcher', 'traffic-analyst':'Traffic-flow analyst', 'follow-up':'Lead designer'};
  const typeNames = {chicane:'Chicane (deliberate curves)', lane_reduction:'Lane reduction', roundabout:'Roundabout', median_refuge:'Median / refuge island', curb_extension:'Curb extensions', raised_crossing:'Raised crossing', high_visibility_crosswalk:'High-visibility crosswalk', speed_cushion:'Speed cushions', protected_left_turn:'Protected left turn', leading_pedestrian_interval:'Leading pedestrian interval', signal_visibility:'Signal visibility', lighting:'Lighting', daylighting:'Corner daylighting', protected_bike_lane:'Protected bike lane', hardened_centerline:'Hardened centreline', other:'Other change'};
  const suggestions = ['What crash pattern stands out here, and what redesign would you try first?', 'Design something that makes drivers naturally slow down on the approaches.', 'Which approach idles and pollutes most here, why, and what would you change?'];
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
  const svg = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); parent?.append(n); return n; };

  async function api(action, fields = {}) {
    const response = await fetch(`/api/${action}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({site:site.name, ...fields})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'The request could not complete.');
    return body;
  }

  // ---------- Before / after schematic ----------
  function streetsOf(design) {
    const names = design.siteName.split(' & ');
    return [{key:'first', name:names[0], before:design.first_street_lanes_before, after:design.first_street_lanes_after},
            {key:'second', name:names[1] || 'Cross street', before:design.second_street_lanes_before, after:design.second_street_lanes_after}];
  }
  function diagram(design, proposed) {
    const C = 150, root = svg('svg', {viewBox:'0 0 300 300', role:'img', 'aria-label': proposed ? 'Proposed layout diagram' : 'Current layout diagram'});
    svg('rect', {width:300, height:300, fill:'#dde6da'}, root);
    const streets = streetsOf(design);
    const lane = Math.min(11, 76 / Math.max(...streets.map(s => Math.max(s.before, s.after))));
    const has = (type, key) => proposed && design.elements.some(e => e.type === type && (e.street === key || e.street === 'both'));
    const anyHas = (type) => proposed && design.elements.some(e => e.type === type);
    const info = streets.map(s => ({...s, curb: s.before * lane + 8, lanes: proposed ? s.after : s.before}));
    info.forEach(s => { s.curb = Math.max(s.curb, s.lanes * lane + 8); s.half = s.curb / 2; });
    const asphalt = '#59615e', walk = '#c5cec2';
    info.forEach((s, index) => {
      const other = info[1 - index], g = svg('g', index ? {transform:`rotate(90 ${C} ${C})`} : {}, root);
      const d = has('chicane', s.key)
        ? `M0,${C} C16,${C} 16,${C-12} 32,${C-12} C52,${C-12} 52,${C+12} 72,${C+12} C86,${C+12} 86,${C} 98,${C} L202,${C} C214,${C} 214,${C-12} 228,${C-12} C248,${C-12} 248,${C+12} 268,${C+12} C284,${C+12} 284,${C} 300,${C}`
        : `M0,${C} L300,${C}`;
      const stroke = (color, width, extra = {}) => svg('path', {d, fill:'none', stroke:color, 'stroke-width':width, ...extra}, g);
      stroke(walk, s.curb + 10); stroke(asphalt, s.curb);
      const travel = s.lanes * lane;
      if (s.curb - travel > 9) {
        stroke(has('protected_bike_lane', s.key) || has('lane_reduction', s.key) ? '#6db27c' : '#8b968f', s.curb - 2);
        stroke('#f2f2ea', travel + 2.4); stroke(asphalt, travel);
      } else if (has('protected_bike_lane', s.key)) {
        stroke('#6db27c', s.curb - 2); stroke(asphalt, s.curb - 12);
      }
      const offsets = [];
      for (let o = (s.lanes % 2 ? lane / 2 : lane); o < travel / 2 - 1; o += lane) offsets.push(o);
      offsets.reverse().forEach((o, i, all) => {
        const innerTurn = s.lanes % 2 && i === all.length - 1 && s.lanes > 1;
        stroke(innerTurn ? '#f1c84b' : '#f2f2ea', 2 * o + 1.2, innerTurn ? {} : {'stroke-dasharray':'7 6'});
        stroke(asphalt, 2 * o - 1.2);
      });
      if (s.lanes % 2 === 0) stroke('#f1c84b', 1.5);
      s.group = g; s.other = other;
    });
    svg('rect', {x:C - info[1].half, y:C - info[0].half, width:info[1].curb, height:info[0].curb, fill:asphalt}, root);
    info.forEach((s, index) => {
      const g = svg('g', index ? {transform:`rotate(90 ${C} ${C})`} : {}, root), other = s.other;
      for (const side of [-1, 1]) {
        const x = C + side * (other.half + 8), top = C - s.half, raised = has('raised_crossing', s.key), bold = raised || has('high_visibility_crosswalk', s.key);
        if (raised) svg('rect', {x:x - 7, y:top, width:14, height:s.curb, fill:'#d8a35a'}, g);
        if (bold) for (let y = top + 2; y < top + s.curb - 2; y += 6) svg('rect', {x:x - 5, y, width:10, height:3.2, fill:'#fff'}, g);
        else for (const dx of [-4, 4]) svg('line', {x1:x + dx, x2:x + dx, y1:top + 1, y2:top + s.curb - 1, stroke:'#e9ebe4', 'stroke-width':1.2}, g);
        if (has('median_refuge', s.key)) svg('rect', {x: side < 0 ? 22 : x + 9, y:C - 3, width:Math.max(10, C - other.half - 8 - 9 - 22), height:6, rx:3, fill:'#7fbb86', stroke:'#f2f2ea', 'stroke-width':.8}, g);
        if (has('hardened_centerline', s.key)) svg('line', {x1:x + side * 8, x2:x + side * 30, y1:C, y2:C, stroke:'#f1c84b', 'stroke-width':3.5, 'stroke-dasharray':'3 2'}, g);
        if (has('speed_cushion', s.key)) svg('rect', {x:C + side * 92 - 3, y:C - s.lanes * lane / 2 + 1, width:6, height:s.lanes * lane - 2, rx:1.5, fill:'#e3b34c'}, g);
        if (has('protected_left_turn', s.key)) svg('text', {x:x + side * 20, y:C + side * (lane * .5) + 3.5, 'font-size':10, fill:'#fff', 'text-anchor':'middle', 'font-weight':700}, g).textContent = side < 0 ? '↰' : '↲';
        for (const edge of [-1, 1]) {
          if (has('curb_extension', s.key)) svg('rect', {x:Math.min(x - side * 6, x + side * 12), y: edge < 0 ? top - 1 : top + s.curb - 6, width:18, height:7, rx:3, fill:walk, stroke:'#7d8a80', 'stroke-width':.7}, g);
          if (has('daylighting', s.key)) svg('line', {x1:x + side * 6, x2:x + side * 28, y1:C + edge * s.half, y2:C + edge * s.half, stroke:'#d9534f', 'stroke-width':2.4}, g);
        }
      }
    });
    if (anyHas('roundabout')) {
      const r = Math.max(info[0].half, info[1].half) + 14;
      svg('circle', {cx:C, cy:C, r:r + 5, fill:walk}, root); svg('circle', {cx:C, cy:C, r, fill:asphalt}, root);
      svg('circle', {cx:C, cy:C, r:r * .72, fill:'none', stroke:'#f2f2ea', 'stroke-width':1, 'stroke-dasharray':'5 5'}, root);
      svg('circle', {cx:C, cy:C, r:r * .45, fill:'#7fbb86', stroke:'#f2f2ea', 'stroke-width':1.2}, root);
    }
    const corner = (dx, dy, pad) => [C + dx * (info[1].half + pad), C + dy * (info[0].half + pad)];
    if (anyHas('lighting')) for (const [dx, dy] of [[-1,-1],[1,-1],[-1,1],[1,1]]) { const [x, y] = corner(dx, dy, 9); svg('circle', {cx:x, cy:y, r:7, fill:'#ffe17b', opacity:.45}, root); svg('circle', {cx:x, cy:y, r:2.6, fill:'#f5b301'}, root); }
    const badges = [['leading_pedestrian_interval', 'LPI', -1, -1], ['signal_visibility', 'SIGNAL', 1, 1], ['protected_left_turn', 'PROT. LEFT', -1, 1]];
    for (const [type, label, dx, dy] of badges) if (anyHas(type)) {
      const [x, y] = corner(dx, dy, 22), w = label.length * 4.6 + 8;
      svg('rect', {x:x - w / 2, y:y - 6, width:w, height:12, rx:6, fill:'#234538'}, root);
      svg('text', {x, y:y + 3, 'font-size':7.5, fill:'#fff', 'text-anchor':'middle', 'font-weight':700}, root).textContent = label;
    }
    const name = (text, attrs) => { const t = svg('text', {'font-size':9, 'font-weight':700, fill:'#2c3d35', ...attrs}, root); t.textContent = text; };
    name(info[0].name, {x:6, y:C - info[0].half - 10});
    name(info[1].name, {x:0, y:0, transform:`translate(${C + info[1].half + 14} 8) rotate(90)`});
    if (proposed) design.elements.forEach((element, i) => {
      const [x, y] = markerSpot(element, i, info, C);
      svg('circle', {cx:x, cy:y, r:8, fill:'#e8642c', stroke:'#fff', 'stroke-width':1.5}, root);
      svg('text', {x, y:y + 3.4, 'font-size':9.5, fill:'#fff', 'text-anchor':'middle', 'font-weight':700}, root).textContent = i + 1;
    });
    return root;
  }
  function markerSpot(element, i, info, C) {
    const index = element.street === 'second' ? 1 : 0, s = info[index], o = info[1 - index];
    const spots = {chicane:[52, C - s.half - 24], lane_reduction:[250, C - s.half - 14], roundabout:[C, C], median_refuge:[78, C + s.half + 14], curb_extension:[C - o.half - 26, C - s.half - 14],
      raised_crossing:[C + o.half + 8, C + s.half + 16], high_visibility_crosswalk:[C + o.half + 8, C + s.half + 16], speed_cushion:[C + 92, C + s.half + 14], protected_left_turn:[C - o.half - 44, C + s.half + 14],
      leading_pedestrian_interval:[C - o.half - 46, C - s.half - 34], signal_visibility:[C + o.half + 46, C + s.half + 34], lighting:[C + o.half + 22, C - s.half - 22], daylighting:[C + o.half + 34, C - s.half - 12],
      protected_bike_lane:[222, C + s.half + 14], hardened_centerline:[C + o.half + 34, C + s.half + 14], other:[18 + i * 20, 286]};
    let [x, y] = spots[element.type] || spots.other;
    if (index && element.type !== 'other') [x, y] = [2 * C - y, x];
    return [Math.max(10, Math.min(290, x)), Math.max(10, Math.min(290, y))];
  }

  // ---------- Aerial overlay ----------
  function drawOverlay(design, snapshot) {
    overlay?.remove(); overlay = null;
    if (!overlayOn || typeof map === 'undefined' || !map || !window.L) return;
    overlay = L.layerGroup().addTo(map);
    const centre = overlayCenter || snapshot.location, rad = Math.PI / 180;
    const streets = streetsOf(design).map(s => ({...s, bearing:snapshot.bearings[s.key], half:Math.max(s.before, s.after) * 3.3 / 2 + 1}));
    const at = (street, along, lateral) => {
      const b = street.bearing * rad, east = along * Math.sin(b) + lateral * Math.cos(b), north = along * Math.cos(b) - lateral * Math.sin(b);
      return [centre.lat + north / 111195, centre.lon + east / (111195 * Math.cos(centre.lat * rad))];
    };
    const box = (s, a1, a2, l1, l2, style) => L.polygon([at(s, a1, l1), at(s, a2, l1), at(s, a2, l2), at(s, a1, l2)], {weight:1, color:'#fff', fillOpacity:.85, interactive:false, ...style}).addTo(overlay);
    const line = (points, style) => L.polyline(points, {interactive:false, ...style}).addTo(overlay);
    const range = (a, b, step) => { const out = []; for (let v = a; v <= b; v += step) out.push(v); return out; };
    design.elements.forEach((element, i) => {
      const targets = streets.filter(s => element.street === 'both' || s.key === element.street);
      let anchor = null;
      targets.forEach(s => {
        const o = streets.find(x => x !== s), start = o.half + 4;
        for (const side of [-1, 1]) {
          const A = (v) => side * v;
          switch (element.type) {
            case 'chicane':
              for (const edge of [-1, 0, 1]) line(range(start + 8, start + 92, 3).map(a => at(s, A(a), edge * (s.half - 1.5) + 3.4 * Math.sin((a - start - 8) / 84 * 2 * Math.PI))), {color: edge ? '#ffd23f' : '#fff', weight: edge ? 4 : 2, opacity:.95, dashArray: edge ? null : '6 8'});
              anchor ??= at(s, A(start + 30), s.half + 5); break;
            case 'lane_reduction': {
              const edge = s.after * 3.3 / 2;
              for (const t of [-1, 1]) { line([at(s, A(start), t * edge), at(s, A(125), t * edge)], {color:'#7df0a0', weight:3, dashArray:'10 6'}); box(s, A(start), A(125), t * edge, t * (s.half - .5), {fillColor:'#58d68d', fillOpacity:.35, weight:0}); }
              anchor ??= at(s, A(70), s.half + 5); break; }
            case 'protected_bike_lane':
              for (const t of [-1, 1]) box(s, A(start), A(125), t * (s.half - 2.4), t * (s.half - .4), {fillColor:'#35c46a', fillOpacity:.75, weight:0});
              anchor ??= at(s, A(90), -(s.half + 5)); break;
            case 'median_refuge': box(s, A(start + 5), A(start + 42), -1.3, 1.3, {fillColor:'#6fcf7f'}); anchor ??= at(s, A(start + 24), 6); break;
            case 'raised_crossing': box(s, A(start - 2), A(start + 3), -s.half, s.half, {fillColor:'#e0a14f'}); anchor ??= at(s, A(start + 1), s.half + 5); break;
            case 'high_visibility_crosswalk': box(s, A(start - 2), A(start + 2.5), -s.half, s.half, {fillColor:'#fff', fillOpacity:.8, color:'#234538', dashArray:'3 3'}); anchor ??= at(s, A(start + 1), s.half + 5); break;
            case 'speed_cushion': box(s, A(start + 55), A(start + 58.5), -(s.half - 1.5), s.half - 1.5, {fillColor:'#f2b632'}); anchor ??= at(s, A(start + 57), s.half + 5); break;
            case 'hardened_centerline': line([at(s, A(start + 3), 0), at(s, A(start + 24), 0)], {color:'#ffd23f', weight:5, dashArray:'4 4'}); anchor ??= at(s, A(start + 14), 5); break;
            case 'curb_extension': for (const t of [-1, 1]) box(s, A(start - 3), A(start + 6), t * (s.half - 2.6), t * (s.half + .3), {fillColor:'#f4f1de'}); anchor ??= at(s, A(start + 2), s.half + 6); break;
            case 'daylighting': for (const t of [-1, 1]) line([at(s, A(start), t * s.half), at(s, A(start + 10), t * s.half)], {color:'#ff5a4f', weight:5}); anchor ??= at(s, A(start + 5), -(s.half + 6)); break;
            case 'lighting': for (const t of [-1, 1]) L.circleMarker(at(s, A(o.half + 2), t * (s.half + 2)), {radius:6, color:'#fff', weight:1, fillColor:'#ffd23f', fillOpacity:1, interactive:false}).addTo(overlay); anchor ??= at(s, A(o.half + 8), s.half + 8); break;
            case 'roundabout': break;
            default: anchor ??= at(s, A(start + 12 + i * 3), -(s.half + 7));
          }
        }
      });
      if (element.type === 'roundabout') {
        const r = Math.max(...streets.map(s => s.half)) + 7;
        L.circle([centre.lat, centre.lon], {radius:r, color:'#fff', weight:3, fillColor:'#59615e', fillOpacity:.75, interactive:false}).addTo(overlay);
        L.circle([centre.lat, centre.lon], {radius:r * .45, color:'#fff', weight:2, fillColor:'#6fcf7f', fillOpacity:.95, interactive:false}).addTo(overlay);
        anchor = at(streets[0], r + 4, r + 4);
      }
      const label = node('span', `${i + 1}. ${element.label}`);
      L.marker(anchor || [centre.lat, centre.lon], {icon:L.divIcon({className:'design-pin', html:String(i + 1), iconSize:[22, 22]}), keyboard:false}).bindTooltip(label).addTo(overlay);
    });
    const handle = L.marker([centre.lat, centre.lon], {draggable:true, icon:L.divIcon({className:'design-handle', html:'✥', iconSize:[26, 26]}), title:'Drag to line the overlay up with the junction'}).addTo(overlay);
    handle.on('dragend', () => { const p = handle.getLatLng(); overlayCenter = {lat:p.lat, lon:p.lng}; drawOverlay(design, snapshot); });
  }

  // ---------- Rendering ----------
  function currentDesign(snapshot) {
    if (!snapshot?.designs.length) return null;
    const version = shown.get(snapshot.site) ?? snapshot.designs.at(-1).version;
    return snapshot.designs.find(d => d.version === version) || snapshot.designs.at(-1);
  }
  function renderDesign(snapshot) {
    const design = currentDesign(snapshot), panel = el('design-panel');
    el('design-empty').hidden = !!design; panel.hidden = !design;
    if (!design) { overlay?.remove(); overlay = null; return; }
    design.siteName = snapshot.site;
    const versions = el('design-versions'); versions.replaceChildren();
    if (snapshot.designs.length > 1) snapshot.designs.forEach(d => {
      const b = node('button', `Design ${d.version}`, d.version === design.version ? 'chip active' : 'chip'); b.type = 'button';
      b.addEventListener('click', () => { shown.set(snapshot.site, d.version); renderDesign(snapshot); }); versions.append(b);
    });
    el('design-title').textContent = design.title;
    el('design-target').textContent = design.target_pattern;
    el('design-summary').textContent = design.summary;
    el('design-idling').hidden = !design.idling_effect; el('design-idling').textContent = design.idling_effect ? `Idling and emissions: ${design.idling_effect}` : '';
    el('design-before').replaceChildren(diagram(design, false));
    el('design-after').replaceChildren(diagram(design, true));
    el('design-before-note').textContent = `${design.first_street_lanes_before} and ${design.second_street_lanes_before} through lanes · ${design.baseline_basis === 'aerial estimate' ? 'estimated by Grok from the aerial image' : 'assumed, not surveyed'}`;
    el('design-after-note').textContent = `${design.first_street_lanes_after} and ${design.second_street_lanes_after} through lanes · numbered changes below`;
    const list = el('design-elements'); list.replaceChildren();
    design.elements.forEach(e => { const li = node('li'); li.append(node('strong', e.label), node('span', ` · ${typeNames[e.type] || e.type}`, 'note'), node('p', e.purpose)); list.append(li); });
    const fill = (id, items) => { const ul = el(id); ul.replaceChildren(); items.forEach(t => ul.append(node('li', t))); };
    fill('design-tradeoffs', design.tradeoffs); fill('design-checks', design.checks);
    const cites = el('design-sources'); cites.replaceChildren();
    [...design.evidence_ids, ...design.guidance_ids].forEach(id => {
      const source = snapshot.sources[id]; if (!source) return;
      const li = node('li', source.kind === 'guidance' ? source.title : (source.text || source.title));
      if (source.kind === 'guidance') { try { const url = new URL(source.url); if (url.protocol === 'https:' && url.hostname === 'highways.dot.gov') { const a = node('a', ' Open source'); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; li.append(a); } } catch {} }
      cites.append(li);
    });
    el('design-overlay').textContent = overlayOn ? 'Hide from aerial map' : 'Show on aerial map';
    el('design-overlay-note').hidden = !overlayOn;
    el('design-overlay-note').textContent = `Approximate placement: street angles are ${snapshot.bearings.basis}, widths are illustrative, and the map point may sit off the junction. Drag the ✥ handle to line it up.`;
    drawOverlay(design, snapshot);
    renderSim(snapshot, design);
  }
  // ---------- Re-simulation of a design ----------
  const simKey = (snapshot, design) => `${snapshot.id}:${design.version}`;
  function renderSim(snapshot, design) {
    const run = sims.get(simKey(snapshot, design)), box = el('design-sim'), button = el('design-simulate');
    button.disabled = run?.status === 'running';
    button.textContent = run?.status === 'complete' ? 'Simulate again' : 'Simulate idling and emissions';
    box.hidden = !run; box.replaceChildren();
    if (!run) return;
    if (run.status !== 'complete') {
      box.append(node('p', run.status === 'running' ? `${run.message}… ${run.elapsed}s. The first run for an intersection takes a minute or two.` : run.message, 'note'));
      if (run.status === 'running') { const cancel = node('button', 'Cancel simulation', 'chip'); cancel.type = 'button'; cancel.addEventListener('click', async () => { try { sims.set(simKey(snapshot, design), await api('simulate-cancel', {run_id:run.id})); renderSim(snapshot, design); } catch {} }); box.append(cancel); }
      return;
    }
    const r = run.result, list = (title, items) => { if (!items.length) return; box.append(node('h4', title)); const ul = node('ul'); items.forEach(t => ul.append(node('li', t))); box.append(ul); };
    box.append(node('h4', `Simulated before and after · ${r.period}`));
    if (!r.scenario) box.append(node('p', run.message + '.'));
    else {
      const table = node('table'), head = node('tr');
      ['Where', 'Idling per vehicle', 'Time stopped', 'CO₂ per vehicle-km'].forEach(t => head.append(node('th', t))); table.append(head);
      const cell = (before, after, unit, lowerIsBetter = true) => { const td = node('td', `${before}${unit} → ${after}${unit}`); if (after !== before) td.className = (after < before) === lowerIsBetter ? 'better' : 'worse'; return td; };
      Object.keys(r.baseline.approaches).forEach(id => {
        const b = r.baseline.approaches[id], a = r.scenario.approaches[id]; if (!a) return;
        const tr = node('tr'); tr.append(node('td', r.approach_names[id] || id), cell(b.idle_s, a.idle_s, ' s'), cell(Math.round(b.stopped_share * 100), Math.round(a.stopped_share * 100), '%'), cell(b.co2_g_vkm, a.co2_g_vkm, ' g')); table.append(tr);
      });
      const b = r.baseline.area, a = r.scenario.area, tr = node('tr', undefined, 'total');
      tr.append(node('td', `Whole area (${r.radius_m} m around)`), cell(b.idle_veh_h, a.idle_veh_h, ' veh-h'), cell(Math.round(b.stopped_share * 100), Math.round(a.stopped_share * 100), '%'), cell(b.co2_kg, a.co2_kg, ' kg total'));
      table.append(tr); const wrap = node('div', undefined, 'crash-table'); wrap.append(table); box.append(wrap);
      box.append(node('p', 'Ask Grok about this result: it can now cite the comparison.', 'note'));
    }
    list('Modelled', r.simulated); list('Not modelled', r.not_simulated); list('Read with care', r.caveats);
  }
  function pollSim(snapshot, design, token) {
    clearTimeout(simTimer);
    simTimer = setTimeout(async () => {
      const key = simKey(snapshot, design), run = sims.get(key);
      if (!run || run.status !== 'running' || token !== revision) return;
      try { sims.set(key, await api('simulate-state', {run_id:run.id})); } catch (error) { sims.set(key, {...run, status:'failed', message:error.message}); }
      if (token === revision && currentDesign(chats.get(site?.name))?.version === design.version) renderSim(snapshot, design);
      pollSim(snapshot, design, token);
    }, 2000);
  }
  function render(snapshot) {
    const key = JSON.stringify([snapshot?.messages, snapshot?.designs.length, snapshot?.running, snapshot?.activity]);
    const log = el('chat-log');
    el('chat-suggestions').hidden = !!snapshot?.messages.length;
    el('chat-send').disabled = !!snapshot?.running; el('chat-cancel').hidden = !snapshot?.running;
    if (key !== lastKey) {
      lastKey = key; log.replaceChildren();
      (snapshot?.messages || []).forEach(m => {
        const bubble = node('div', undefined, `chat-msg ${m.role} ${m.status}`);
        bubble.append(node('span', m.role === 'user' ? 'You' : 'Grok', 'chat-who'));
        if (m.status === 'running') bubble.append(node('p', snapshot.activity || 'Thinking…', 'chat-working'));
        else bubble.append(node('p', m.text));
        if (m.design) { const b = node('button', `View design ${m.design}`, 'chip'); b.type = 'button'; b.addEventListener('click', () => { shown.set(snapshot.site, m.design); renderDesign(snapshot); el('design-panel').scrollIntoView({block:'nearest', behavior:'smooth'}); }); bubble.append(b); }
        log.append(bubble);
      });
      log.scrollTop = log.scrollHeight;
      renderDesign(snapshot || {designs:[]});
    }
    const activity = el('chat-activity'); activity.replaceChildren();
    el('chat-activity-box').hidden = !snapshot?.events.length;
    if (snapshot) {
      snapshot.events.filter(e => e.kind !== 'working').forEach(e => activity.append(node('li', `${e.seconds}s · ${roles[e.role] || e.role}: ${e.text}`)));
      el('chat-usage').textContent = `${snapshot.usage.model_calls} Grok calls · ${snapshot.usage.input_tokens.toLocaleString()} input and ${snapshot.usage.output_tokens.toLocaleString()} output tokens in this conversation.`;
      const notes = el('chat-notes'); notes.replaceChildren();
      Object.entries(snapshot.notes).forEach(([role, text]) => { const d = node('details'); d.append(node('summary', `${roles[role] || role} notes`), node('pre', text)); notes.append(d); });
    }
  }
  function schedule(snapshot, token) {
    clearTimeout(pollTimer);
    if (token !== revision || !snapshot.running) return;
    pollTimer = setTimeout(async () => {
      try { const next = await api('chat-state', {chat_id:snapshot.id}); chats.set(next.site, next); if (token === revision) { if (!next.running) shown.delete(next.site); render(next); schedule(next, token); } }
      catch (error) { if (token === revision) el('chat-status').textContent = error.message; }
    }, 1500);
  }
  async function send(text) {
    if (!site || !text.trim()) return;
    const token = revision, previous = chats.get(site.name);
    el('chat-send').disabled = true; el('chat-status').textContent = '';
    try {
      const next = await api('chat', {message:text.trim(), ...(previous ? {chat_id:previous.id} : {})});
      chats.set(next.site, next);
      if (token === revision) { el('chat-input').value = ''; render(next); schedule(next, token); }
    } catch (error) {
      if (token !== revision) return;
      if (/expired/.test(error.message)) chats.delete(site.name);
      el('chat-status').textContent = error.message; el('chat-send').disabled = false;
    }
  }
  window.designSelect = (next) => {
    if (site?.name === next?.name) return;
    site = next; revision++; clearTimeout(pollTimer); lastKey = ''; overlayCenter = null;
    el('designer').hidden = !site;
    overlay?.remove(); overlay = null;
    if (!site) return;
    el('chat-site').textContent = site.name; el('chat-status').textContent = ''; el('chat-input').value = '';
    const snapshot = chats.get(site.name);
    render(snapshot); if (snapshot) schedule(snapshot, revision);
  };
  const chips = el('chat-suggestions');
  suggestions.forEach(text => { const b = node('button', text, 'chip'); b.type = 'button'; b.addEventListener('click', () => send(text)); chips.append(b); });
  el('chat-form').addEventListener('submit', (event) => { event.preventDefault(); send(el('chat-input').value); });
  el('chat-input').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); el('chat-form').requestSubmit(); } });
  el('chat-cancel').addEventListener('click', async () => {
    const snapshot = chats.get(site?.name), token = revision; if (!snapshot) return;
    try { const next = await api('chat-cancel', {chat_id:snapshot.id}); chats.set(next.site, next); if (token === revision) { render(next); schedule(next, token); } } catch (error) { el('chat-status').textContent = error.message; }
  });
  el('design-overlay').addEventListener('click', () => {
    overlayOn = !overlayOn;
    const snapshot = chats.get(site?.name); if (!snapshot) return;
    renderDesign(snapshot);
    if (overlayOn && typeof map !== 'undefined' && map) { map.stop(); map.flyTo([snapshot.location.lat, snapshot.location.lon], 19, {duration:.6}); el('map').scrollIntoView({block:'center', behavior:'smooth'}); }
  });
  el('design-simulate').addEventListener('click', async () => {
    const snapshot = chats.get(site?.name), design = currentDesign(snapshot), token = revision; if (!design) return;
    const key = simKey(snapshot, design);
    try { sims.set(key, await api('simulate', {chat_id:snapshot.id, version:design.version})); }
    catch (error) { sims.set(key, {status:'failed', message:error.message}); }
    if (token === revision) { renderSim(snapshot, design); pollSim(snapshot, design, token); }
  });
  window.designSelect(typeof selected === 'undefined' ? null : selected);
})();
