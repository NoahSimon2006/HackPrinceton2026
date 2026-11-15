// Authoring tool for the landing page hero (public/welcome.html).
//
// The downtown Los Angeles skyline at dusk is described here by hand, building
// by building, and written as inline SVG between the "skyline:start" and
// "skyline:end" comments of public/welcome.html. The page itself needs no
// build step: run this only after changing a building, a delay or a street.
//
//   node scripts/draw_welcome_skyline.mjs
//
// Coordinates: x runs left to right with 0 at the art's centre, y runs up from
// the ground line. One unit is about 0.7 m, so the Wilshire Grand (335 m) is
// 480 units tall. Each building carries --h (how far it rises) and --d (when,
// in seconds); welcome.css turns those into the entrance.
//
// Two drawings come out: the scene itself, which stands still once it has
// built, and a light second layer (traffic, water, beacons, a few windows)
// that keeps moving, so the browser never repaints the whole city for it.

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const PAGE = fileURLToPath(new URL('../public/welcome.html', import.meta.url));
const r1 = (n) => Math.round(n * 10) / 10;
const r2 = (n) => Math.round(n * 100) / 100;

// Seeded generators, so the drawing is the same on every run.
const rng = (s) => () => {
  s |= 0; s = (s + 0x6d2b79f5) | 0;
  let t = Math.imul(s ^ (s >>> 15), 1 | s);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const rnd = rng(20261115);
const between = (a, b) => a + (b - a) * rnd();
const pick = (list) => list[Math.floor(rnd() * list.length)];

const box = (w, h) => `M${r1(-w / 2)} 0V${r1(h)}H${r1(w / 2)}V0`;

// ------------------------------------------------------------------ facades
// A facade is a tile of windows, some lit, repeated over a building's shape.
const WARM = ['#ffd98a', '#ffe9b8', '#f7c066', '#fff4d6'];
const STYLES = {
  office: { cw: 5, ch: 6.5, ww: 3.1, wh: 3.7, lit: 0.36 },
  dense: { cw: 4.4, ch: 5.6, ww: 2.6, wh: 3, lit: 0.42 },
  rib: { cw: 5, ch: 6.5, ww: 3, wh: 3.6, lit: 0.24, rib: true },
  glass: { cw: 6, ch: 6, ww: 4.3, wh: 4.2, lit: 0.3, floor: true, soft: true },
  strip: { cw: 6, ch: 6.5, ww: 6, wh: 2.8, lit: 0.34, band: true },
};
const defs = [];
let facadeCount = 0;
const facade = (style, seed, { width = 40, ox = 0, oy = 5, lit } = {}) => {
  const S = STYLES[style];
  const r = rng(seed);
  const cols = Math.max(2, Math.round(width / S.cw));
  const cw = width / cols;
  const rows = 12;
  const p = lit ?? S.lit;
  const ww = S.band ? cw + 0.05 : Math.min(S.ww, cw - 1.2);
  // Windows are grouped into a few paths (unlit, and lit by colour and
  // brightness) to keep the page small.
  const groups = new Map();
  const add = (key, x, y) => groups.set(key, `${groups.get(key) || ''}M${r1(x)} ${r1(y)}h${r1(ww)}v${S.wh}h${r1(-ww)}z`);
  for (let row = 0; row < rows; row += 1) {
    // Whole floors work late or go home together.
    const floor = r() < 0.16 ? 1.8 : r() < 0.3 ? 0.3 : 1;
    for (let col = 0; col < cols; col += 1) {
      const x = col * cw + (cw - ww) / 2; const y = row * S.ch + (S.ch - S.wh) / 2;
      if (r() < p * floor) {
        const level = [0.42, 0.6, 0.8, 0.97][Math.floor(r() ** 1.5 * 4)] * (S.soft ? 0.8 : 1);
        add(`${WARM[Math.floor(r() * WARM.length)]}|${r2(level)}`, x, y);
      } else add('#eef0ea|0.05', x, y);
    }
  }
  let cells = [...groups].map(([key, d]) => { const [fill, o] = key.split('|'); return `<path d="${d}" fill="${fill}" opacity="${o}"/>`; }).join('');
  if (S.floor) cells += `<path d="${Array.from({ length: rows }, (_, row) => `M0 ${r1(row * S.ch)}h${r1(width)}v.7h${r1(-width)}z`).join('')}" fill="#eef0ea" opacity=".07"/>`;
  if (S.rib) cells += `<path d="${Array.from({ length: cols + 1 }, (_, col) => `M${r1(col * cw - 0.5)} 0h1v${r1(rows * S.ch)}h-1z`).join('')}" fill="#eef0ea" opacity=".13"/>`;
  const id = `sk-f${facadeCount += 1}`;
  defs.push(`<pattern id="${id}" width="${r2(width)}" height="${r2(rows * S.ch)}" patternUnits="userSpaceOnUse" patternTransform="translate(${r1(ox)} ${oy})">${cells}</pattern>`);
  return { id, cw, ch: S.ch, ww: Math.min(S.ww, cw - 1.2), wh: S.wh, cols, ox, oy };
};

// Lights that switch on and off after the scene has built (the second layer).
const twinkles = [];
const twinkle = (x, f, bodyW, bodyH, count) => {
  for (let i = 0; i < count; i += 1) {
    const col = 1 + Math.floor(rnd() * Math.max(1, f.cols - 2));
    const row = 2 + Math.floor(rnd() * Math.max(1, Math.floor((bodyH * 0.72) / f.ch) - 2));
    twinkles.push({ x: r1(x + f.ox + col * f.cw + (f.cw - f.ww) / 2), y: r1(f.oy + row * f.ch + (f.ch - f.wh) / 2), w: r1(f.ww), h: f.wh });
  }
};

// ---------------------------------------------------------------- buildings
// { x, h, d (delay, s), dur (s), body (svg inside the rising group) }
const back = [];
const towers = [];
const front = [];
const beacons = [];

// Plain blocks in the distance, hazy against the sunset. Left of City Hall
// they stay low so the headline has clear sky above them.
const backRight = [
  [215, 50, 236], [300, 56, 262], [372, 46, 228], [500, 50, 284], [572, 52, 248],
  [700, 52, 268], [772, 58, 214], [846, 66, 176], [925, 58, 150], [1004, 76, 112],
  [1092, 66, 132], [1180, 80, 92],
];
for (let x = -1880; x < 200; x += between(78, 112)) {
  const nearCityHall = x > -40;
  back.push({ x: r1(x), w: r1(between(64, 104)), h: r1(nearCityHall ? between(40, 64) : between(52, 128)) });
}
for (const [x, w, h] of backRight) back.push({ x, w, h });
for (let x = 1270; x < 1900; x += between(80, 115)) back.push({ x: r1(x), w: r1(between(64, 100)), h: r1(between(48, 104)) });
back.sort((a, b) => a.x - b.x);
const farFacades = [facade('office', 11, { width: 40, lit: 0.22 }), facade('strip', 12, { width: 42, lit: 0.2 }), facade('dense', 13, { width: 44, lit: 0.26 })];
back.forEach((b, i) => {
  b.d = r1(0.5 + i * 0.027 + between(0, 0.05));
  b.dur = 0.9;
  const d = box(b.w, b.h);
  b.body = `<path d="${d}" fill="url(#sk-far)"/><path class="w" d="${d}" fill="url(#${pick(farFacades).id})" opacity=".55"/>`;
});
// A tower crane on one of the far blocks: downtown is always building.
{
  const b = back.find((it) => it.x === 700);
  b.body += `<path class="ln" d="M8 ${b.h}V${b.h + 62}M-30 ${b.h + 54}H46M8 ${b.h + 62}L-30 ${b.h + 54}M8 ${b.h + 62}L32 ${b.h + 54}M36 ${b.h + 54}V${b.h + 34}"/>`;
  beacons.push({ x: 708, y: b.h + 63, wait: 0.8 });
  b.h += 62;
}

// The towers, left to right. Shapes are silhouettes of the real buildings;
// each gets a dark body, a face that catches the low sun from the left, and
// its own windows.
const tower = ({ name, x, w, h, d, dur = 1.1, shape, style, seed, lit, tone = 'url(#sk-tower)', round = false, extra = '', bodyH = h, twinkles: n = 2 }) => {
  const f = facade(style, seed, { width: w - 4, ox: -w / 2 + 2, lit });
  twinkle(x, f, w, bodyH, n);
  towers.push({
    name, x, h, d, dur,
    body: `<path d="${shape}" fill="${tone}"/><path d="${shape}" fill="url(#${round ? 'sk-round' : 'sk-sunface'})"/>`
      + `<path class="w" d="${shape}" fill="url(#${f.id})"/><path class="edge" d="${shape}"/>${extra}`,
  });
};

tower({ name: 'Two California Plaza', x: 255, w: 54, h: 327, d: 2.0, style: 'office', seed: 101,
  shape: 'M-27 0V317L-19 327H19L27 317V0', extra: '<path class="ln" d="M6 327V341"/>' });
tower({ name: 'Wells Fargo Center', x: 320, w: 50, h: 315, d: 2.1, style: 'strip', seed: 102, tone: 'url(#sk-stone)',
  shape: 'M-25 0V286L25 315V0', bodyH: 286 });
tower({ name: 'Bank of America Plaza', x: 385, w: 58, h: 320, d: 2.2, style: 'rib', seed: 103,
  shape: 'M-29 0V309H-17V320H17V309H29V0' });
tower({ name: 'Gas Company Tower', x: 525, w: 54, h: 326, d: 2.3, style: 'glass', seed: 104, tone: 'url(#sk-glass)',
  shape: 'M-27 0V298H-11Q-9 326 12 326H27V0', bodyH: 298 });
tower({ name: 'Aon Center', x: 590, w: 46, h: 375, d: 2.4, style: 'rib', seed: 105, lit: 0.32,
  shape: box(46, 375), extra: '<path class="ln" d="M-8 375V383H8V375"/>', twinkles: 3 });
tower({ name: '777 Tower', x: 715, w: 52, h: 316, d: 2.5, style: 'office', seed: 106, tone: 'url(#sk-pale)', lit: 0.4,
  shape: 'M-26 0V291Q-26 300-18 300V307Q-18 316-9 316H9Q18 316 18 307V300Q26 300 26 291V0', bodyH: 291 });
tower({ name: 'Figueroa at Wilshire', x: 775, w: 56, h: 312, d: 2.6, style: 'strip', seed: 107, tone: 'url(#sk-stone)',
  shape: 'M-28 0V268L-18 288V299L-8 312H8L18 299V288L28 268V0', bodyH: 268 });
tower({ name: 'City National Plaza, north', x: 833, w: 40, h: 262, d: 2.66, style: 'rib', seed: 108, shape: box(40, 262) });
tower({ name: 'City National Plaza, south', x: 882, w: 40, h: 262, d: 2.72, style: 'rib', seed: 109, shape: box(40, 262) });
tower({ name: 'Ritz-Carlton and JW Marriott', x: 945, w: 48, h: 244, d: 2.8, style: 'dense', seed: 110, tone: 'url(#sk-glass)',
  shape: 'M-24 0V244L24 226V0', bodyH: 226 });
tower({ name: 'US Bank Tower', x: 455, w: 76, h: 443, d: 2.95, dur: 1.25, style: 'office', seed: 111, round: true, lit: 0.4, twinkles: 4, bodyH: 390,
  shape: 'M-38 0V250H-33V330H-28V395H-23V430H-18V443H18V430H23V395H28V330H33V250H38V0',
  extra: '<path class="ln ln--soft" d="M-12 6V428M0 6V428M12 6V428"/><path class="lit crown" d="M-18 431.5H18V441.5H-18Z"/>' });
tower({ name: 'Wilshire Grand Center', x: 655, w: 60, h: 480, d: 3.1, dur: 1.3, style: 'glass', seed: 112, tone: 'url(#sk-glass)', lit: 0.36, twinkles: 4, bodyH: 366,
  shape: 'M-30 0V366C-22 392 0 418 20 424Q28 425 30 416V0',
  extra: '<path class="ln ln--bright" d="M-30 366C-22 392 0 418 20 424Q28 425 30 416"/><path class="spire" d="M14 424V480"/>' });
beacons.push({ x: 669, y: 481, wait: 0 }, { x: 455, y: 446, wait: 1.3 });

// Low buildings in front. Four stand out: the turquoise Eastern Columbia
// clock tower, Walt Disney Concert Hall, floodlit City Hall, and the
// Bonaventure's glass cylinders at the foot of the towers.
const landmarks = [
  { name: 'Eastern Columbia Building', x: -330, half: 34, h: 113, d: 1.55,
    body: (() => {
      const shape = 'M-25 0V70H-16V82H-8V104H-4V113H4V104H8V82H16V70H25V0';
      const f = facade('office', 22, { width: 46, ox: -23, lit: 0.5 });
      return `<path d="${shape}" fill="url(#sk-teal)"/><path d="${shape}" fill="url(#sk-sunface)"/><path class="w" d="${box(50, 68)}" fill="url(#${f.id})"/>`
        + `<circle class="lit" cx="0" cy="92" r="3.4" fill="#ffe9b8"/><path class="ln ln--gold" d="M-25 70H-16V82H-8V104M25 70H16V82H8V104"/>`;
    })() },
  { name: 'Walt Disney Concert Hall', x: -112, half: 74, h: 54, d: 1.72,
    body: `<path d="M-62 0C-60 30-42 44-31 46C-25 30-17 22-8 20C-4 35 6 50 22 53C26 37 34 28 44 26C50 34 56 40 66 40C64 22 62 8 60 0" fill="url(#sk-steel)"/>`
      + `<path class="ln ln--dark" d="M-31 46C-33 30-32 14-28 0M-8 20C-10 12-9 6-7 0M22 53C18 36 18 16 22 0M44 26C42 16 43 8 45 0"/>` },
  { name: 'Los Angeles City Hall', x: 90, half: 84, h: 190, d: 1.9, dur: 1.2,
    body: (() => {
      const shape = 'M-78 0V44H-44V74H-17V138H-14V152H-12V166H-9V171H-6V177H-3V183L0 190L3 183V177H6V171H9V166H12V152H14V138H17V74H44V44H78V0';
      return `<path d="${shape}" fill="url(#sk-civic)"/><path d="${shape}" fill="url(#sk-shade)"/>`
        + `<path class="w" d="M-74 4H74V40H-74Z" fill="url(#sk-slit)"/><path class="w" d="M-41 46H41V71H-41Z" fill="url(#sk-slit)"/>`
        + `<path class="ln ln--ink" d="M-10 80V134M-5 80V134M0 80V134M5 80V134M10 80V134M-11 143V150M-6 143V150M-1 143V150M4 143V150M9 143V150M-12 152H12M-14 138H14M-9 156V164M-3 156V164M3 156V164M9 156V164"/>`;
    })() },
  { name: 'Westin Bonaventure', x: 300, half: 46, h: 150, d: 2.35,
    body: (() => {
      const side = (s) => `M${s * 43} 0V112Q${s * 43} 120 ${s * 30} 120Q${s * 17} 120 ${s * 17} 112V0`;
      const mid = 'M-17 0V141Q-17 150 0 150Q17 150 17 141V0';
      const f = facade('strip', 23, { width: 30, ox: -15, lit: 0.5 });
      return [side(-1), side(1), mid].map((d) =>
        `<path d="${d}" fill="url(#sk-glass)"/><path d="${d}" fill="url(#sk-round)"/><path class="w" d="${d}" fill="url(#${f.id})"/>`).join('');
    })() },
];
beacons.push({ x: 90, y: 191, wait: 2.1, white: true });
const taken = (x) => landmarks.some((l) => Math.abs(x - l.x) < l.half);
const lowFacades = [facade('office', 31, { width: 40 }), facade('dense', 32, { width: 44 }), facade('strip', 33, { width: 42 }), facade('office', 34, { width: 35, lit: 0.34 })];
const lowTones = ['#131918', '#181f1d', '#101615', '#1c1f1c', '#2c1f1a', '#16211f'];
for (let x = -1900; x < 1900; x += between(54, 78)) {
  if (taken(x)) continue;
  const underTowers = x > 200 && x < 1000;
  const kind = pick(['office', 'office', 'flat', 'parking', 'shed', 'flat']);
  const w = r1(kind === 'parking' || kind === 'shed' ? between(64, 92) : between(38, 70));
  const tall = !underTowers && rnd() < 0.22;
  const h = r1(kind === 'shed' ? between(16, 30) : kind === 'parking' ? between(26, 44) : underTowers ? between(26, 66) : tall ? between(84, 118) : between(22, 74));
  const tone = pick(lowTones);
  let top = h;
  const shape = kind === 'office' && rnd() < 0.5
    ? `M${r1(-w / 2)} 0V${r1(h * 0.8)}H${r1(-w / 6)}V${h}H${r1(w / 2)}V0`
    : box(w, h);
  const f = kind === 'parking' ? lowFacades[2] : kind === 'flat' ? lowFacades[1] : kind === 'shed' ? lowFacades[3] : lowFacades[0];
  let body = `<path d="${shape}" fill="${tone}"/><path d="${shape}" fill="url(#sk-sunface)" opacity=".7"/><path class="w" d="${shape}" fill="url(#${f.id})"${kind === 'shed' ? ' opacity=".5"' : ''}/>`;
  const roof = rnd();
  if (kind === 'flat' && roof < 0.3) {          // a rooftop water tank
    body += `<path d="M${r1(w * 0.1)} ${h}V${h + 5}M${r1(w * 0.26)} ${h}V${h + 5}" class="ln ln--dark2"/><rect x="${r1(w * 0.06)}" y="${h + 5}" width="${r1(w * 0.24)}" height="9" rx="1.5" fill="${tone}"/>`;
    top = h + 14;
  } else if ((kind === 'shed' || kind === 'parking') && roof < 0.5) {  // a lit billboard
    body += `<path d="M-9 ${h}V${h + 9}M9 ${h}V${h + 9}" class="ln ln--dark2"/><rect class="lit" x="-15" y="${h + 9}" width="30" height="12" fill="#ffe9b8"/>`;
    top = h + 21;
  } else if (roof > 0.84) {                     // an antenna
    const a = r1(between(14, 26));
    body += `<path class="ln" d="M${r1(w * 0.2)} ${h}V${h + a}"/>`;
    top = h + a;
  }
  front.push({ x: r1(x), h: top, body });
}
front.sort((a, b) => a.x - b.x);
front.forEach((b, i) => { b.d = r1(0.85 + i * 0.022 + between(0, 0.05)); b.dur = 0.9; });
for (const l of landmarks) front.push({ dur: 1, ...l });

// Street trees and fan palms, as silhouettes against the sky.
const greens = [];
for (const x of [-1010, -905, -612, -574, -402, -268, -30, 176, 232, 1046, 1118]) {
  const rad = r1(between(9, 14));
  greens.push({ x, h: rad * 2 + 8, d: r1(1.1 + (x + 1010) / 2000 + between(0, 0.1)), dur: 0.9,
    body: `<path class="trunk" d="M0 0V${r1(rad + 4)}"/><circle cx="0" cy="${r1(rad + 6)}" r="${rad}" fill="#12231f"/><circle cx="${r1(-rad * 0.5)}" cy="${r1(rad + 2)}" r="${r1(rad * 0.7)}" fill="#12231f"/>` });
}
const palm = (x, h, lean, d) => {
  const tx = r1(lean * 1.5);
  const fronds = [[-30, -8, -15, 12], [30, -8, 15, 12], [-24, 8, -10, 16], [24, 8, 10, 16], [-27, -22, -17, 2], [27, -22, 17, 2], [-10, 20, -4, 14], [10, 20, 4, 14], [-16, -28, -12, -6], [16, -28, 12, -6]]
    .map(([ex, ey, cx, cy]) => `M${tx} ${h}Q${r1(tx + cx)} ${r1(h + cy)} ${r1(tx + ex)} ${r1(h + ey)}`).join('');
  return { x, h: h + 24, d, dur: 1.1,
    body: `<path class="palm-trunk" d="M0 0Q${r1(lean * 0.2)} ${r1(h * 0.55)} ${tx} ${h}"/><path class="palm" d="${fronds}"/><circle cx="${tx}" cy="${h}" r="3" fill="#0d1312"/>` };
};
const palms = [palm(-772, 150, 6, 1.2), palm(-738, 122, -5, 1.26), palm(-700, 164, 4, 1.32), palm(-470, 136, 5, 1.44), palm(-440, 108, -4, 1.5),
  palm(-226, 128, -6, 1.62), palm(-192, 152, 4, 1.68), palm(196, 112, -4, 2.05), palm(1012, 126, 5, 2.7), palm(1082, 146, -4, 2.76)];

const rise = (b) =>
  `<g transform="translate(${b.x} 0)"><g class="b" style="--h:${Math.ceil(b.h + 4)};--d:${b.d}${b.dur && b.dur !== 1 ? `;--dur:${b.dur}s` : ''}">${b.body}</g></g>`;

// ------------------------------------------------------------------ streets
// A street plan seen from above the skyline: two street families on a plane,
// turned 24 degrees and projected with perspective, so neither runs level.
// Blocks are uneven and some streets stop short, as on a real map.
const D0 = 420;      // camera distance to the near edge of the plane
const DROP = 300;    // the plane's near edge sits this far under the ground line
const VX = 350;      // the camera looks toward the towers
const project = (X, Z) => { const k = D0 / (D0 + Z); return [VX + X * k, -DROP * k]; };
const TURN = (24 * Math.PI) / 180;
const A = [Math.cos(TURN), Math.sin(TURN)];   // across
const B = [-Math.sin(TURN), Math.cos(TURN)];  // away
const BLOCK = 150;
const REACH = [520, 1300, 3400, 7200];        // how far each street class runs
const GAPS = [0.22, 0.1, 0, 0];               // how often a block of it is missing
const EDGE = 2700;
const hash = (a, b = 0, c = 0) => { const v = Math.sin(a * 127.1 + b * 311.7 + c * 74.7) * 43758.5453; return v - Math.floor(v); };
const levelOf = (k) => { if (k === 0) return 3; let n = 0; let v = Math.abs(k); while (v % 2 === 0 && n < 3) { v /= 2; n += 1; } return n; };
const posOf = (k) => k * BLOCK + (k % 8 === 0 ? 0 : (hash(k) - 0.5) * 76);

const streets = [[], [], [], []];
const arterials = [];
[[A, B], [B, A]].forEach(([dir, off], family) => {
  for (let k = -400; k <= 400; k += 1) {
    const level = levelOf(k);
    const t = posOf(k);
    const at = (s) => [off[0] * t + dir[0] * s, off[1] * t + dir[1] * s];
    let sa = null; let sb = null;
    for (let s = -60000; s <= 60000; s += 25) {
      const [X, Z] = at(s);
      if (Z < -40 || Z > REACH[level]) continue;
      const [x] = project(X, Z);
      if (x < -EDGE || x > EDGE) continue;
      if (sa === null) sa = s;
      sb = s;
    }
    if (sa === null || sb - sa < 60) continue;
    const line = (s1, s2) => {
      const [p, q] = at(s1)[1] > at(s2)[1] ? [s1, s2] : [s2, s1];   // far end first
      const a = project(...at(p)).map(r1); const b = project(...at(q)).map(r1);
      return { d: `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`, nearX: b[0], nearZ: at(q)[1] };
    };
    if (level === 3) {
      const whole = line(sa, sb);
      // The widest streets that come right up to the viewer are drawn one by one.
      if (whole.nearZ < 400 && Math.abs(whole.nearX) < 2200) arterials.push(whole);
      else streets[3].push(whole.d);
      continue;
    }
    let run = null;
    const flush = () => { if (run && run[1] - run[0] > 30) streets[level].push(line(run[0], run[1]).d); run = null; };
    for (let m = Math.floor(sa / BLOCK) - 2; m <= Math.ceil(sb / BLOCK) + 2; m += 1) {
      const s1 = Math.max(sa, posOf(m)); const s2 = Math.min(sb, posOf(m + 1));
      if (s2 <= s1) continue;
      if (hash(family + 1, k, m) < GAPS[level]) { flush(); continue; }
      if (run) run[1] = s2; else run = [s1, s2];
    }
    flush();
  }
});
arterials.sort((a, b) => a.nearX - b.nearX);

// A ribbon on the plane: wider as it comes closer. Used for the freeway and
// for water, which does not follow the grid.
const ribbon = (at, halfAt, N = 90) => {
  const left = []; const right = []; const mid = [];
  for (let i = 0; i <= N; i += 1) {
    const u = i / N;
    const [X, Z] = at(u);
    const [Xa, Za] = at(Math.max(0, u - 0.004)); const [Xb, Zb] = at(Math.min(1, u + 0.004));
    const len = Math.hypot(Xb - Xa, Zb - Za) || 1;
    const nx = -(Zb - Za) / len; const nz = (Xb - Xa) / len;
    const w = Math.max(halfAt(u), 0.7 * (D0 + Z) / D0);
    left.push(project(X + nx * w, Z + nz * w).map(r1));
    right.push(project(X - nx * w, Z - nz * w).map(r1));
    mid.push(project(X, Z).map(r1));
  }
  const pts = (list) => list.map((p) => `${p[0]} ${p[1]}`).join('L');
  return { body: `M${pts(left)}L${pts(right.reverse())}Z`, mid: `M${pts(mid)}` };
};

const riverAt = (u) => [
  -900 + 610 * u + (70 + 900 * (1 - u) ** 2) * Math.sin(0.6 + u * 4.6),
  7600 * (1 - u) ** 2.4 + 360 * (1 - u) - 60 * u,
];
const river = ribbon(riverAt, () => 14);
// Smaller channels run down to the river from both sides.
const tributary = ([x0, z0], join, bend, half = [2.5, 6]) => {
  const [x1, z1] = riverAt(join);
  const len = Math.hypot(x1 - x0, z1 - z0);
  const nx = -(z1 - z0) / len; const nz = (x1 - x0) / len;
  return ribbon((v) => {
    const e = v * v * (3 - 2 * v);
    const side = bend * Math.sin(Math.PI * v) * (1 - v * 0.6) + bend * 0.18 * Math.sin(Math.PI * 3 * v) * (1 - v);
    return [x0 + (x1 - x0) * e + nx * side, Math.max(-50, z0 + (z1 - z0) * e + nz * side)];
  }, (v) => half[0] + (half[1] - half[0]) * v, 60);
};
const channels = [
  tributary([-6500, 2600], 0.5, 380),
  tributary([1700, 1900], 0.66, -260),
  tributary([-1700, 620], 0.8, 50, [3, 7]),
  tributary([2900, 5200], 0.4, 420),
  tributary([700, 330], 0.92, -120, [3, 8]),
];
// One freeway sweeps across the plan from the far right.
const freeway = ribbon((u) => [4200 - 6800 * u + 500 * Math.sin(1.2 + 3 * u), 5200 * (1 - u) ** 2 + 130], () => 13);

// ------------------------------------------------------------------- sky
const ridge = 'M-3200 96L-2500 128L-2180 112L-1900 150L-1760 138L-1560 170L-1420 150L-1290 162L-1180 196L-1085 172L-985 212L-900 180L-800 202L-700 160L-610 176L-520 142L-400 170L-300 134L-180 152L-60 120L60 136L200 106L640 96L1200 118L1500 100L1900 124L2300 98L3200 104V0H-3200Z';
const stop = (offset, color, opacity = 1) => `<stop offset="${offset}" stop-color="${color}"${opacity === 1 ? '' : ` stop-opacity="${opacity}"`}/>`;
const vertical = (id, stops) => `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">${stops}</linearGradient>`;
const across = (id, stops) => `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0">${stops}</linearGradient>`;
// Vertical gradients run from the ground (0) to the roof (1): the art's y points up.
const paint = [
  `<linearGradient id="sk-dusk" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="640">${stop(0, '#ffb961', 0.96)}${stop(0.07, '#ff9040', 0.86)}${stop(0.18, '#e8683c', 0.62)}${stop(0.33, '#96604f', 0.4)}${stop(0.52, '#2e525c', 0.36)}${stop(0.78, '#1d353c', 0.18)}${stop(1, '#151918', 0)}</linearGradient>`,
  `<radialGradient id="sk-halo">${stop(0, '#ffcf80', 0.62)}${stop(0.4, '#ff9a4a', 0.24)}${stop(1, '#ff9a4a', 0)}</radialGradient>`,
  `<radialGradient id="sk-sun">${stop(0, '#fff6d8')}${stop(0.7, '#ffd98a')}${stop(1, '#ffb45c')}</radialGradient>`,
  `<linearGradient id="sk-haze" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="110">${stop(0, '#ff9a55', 0.3)}${stop(1, '#ff9a55', 0)}</linearGradient>`,
  vertical('sk-ridge', stop(0, '#a8643c') + stop(0.5, '#5a463a') + stop(1, '#33363a')),
  vertical('sk-far', stop(0, '#6b4636') + stop(0.45, '#40393a') + stop(1, '#313537')),
  vertical('sk-tower', stop(0, '#30302d') + stop(0.3, '#212928') + stop(1, '#1a2221')),
  vertical('sk-glass', stop(0, '#33363a') + stop(0.3, '#232e33') + stop(1, '#1b262b')),
  vertical('sk-stone', stop(0, '#3a302a') + stop(0.3, '#2a2623') + stop(1, '#221f1d')),
  vertical('sk-pale', stop(0, '#4a4640') + stop(0.3, '#3a403d') + stop(1, '#323937')),
  vertical('sk-teal', stop(0, '#2c5c57') + stop(1, '#1f4a47')),
  vertical('sk-civic', stop(0, '#f4ead2') + stop(0.6, '#e6dcc6') + stop(1, '#d2c8b2')),
  across('sk-steel', stop(0, '#d9b99a') + stop(0.35, '#a9a59c') + stop(1, '#5f6562')),
  across('sk-sunface', stop(0, '#ffac68', 0.24) + stop(0.36, '#ffac68', 0.2) + stop(0.36, '#ffac68', 0) + stop(1, '#ffac68', 0)),
  across('sk-round', stop(0, '#ffb070', 0.06) + stop(0.2, '#ffbe84', 0.3) + stop(0.52, '#ffbe84', 0) + stop(1, '#000', 0.3)),
  across('sk-shade', stop(0, '#17211e', 0) + stop(0.56, '#17211e', 0) + stop(0.56, '#17211e', 0.2) + stop(1, '#17211e', 0.26)),
  `<pattern id="sk-slit" width="6" height="9" patternUnits="userSpaceOnUse"><rect x="1.8" y="2" width="2.2" height="5" fill="#17211e" opacity=".5"/></pattern>`,
  `<linearGradient id="sk-fade" x1="0" y1="0" x2="0" y2="1">${stop(0, '#fff', 0.34)}${stop(0.34, '#fff')}${stop(0.8, '#fff')}${stop(1, '#fff', 0.28)}</linearGradient>`,
  `<mask id="sk-plane" maskUnits="userSpaceOnUse" x="-3200" y="-300" width="6400" height="300"><rect x="-3200" y="-300" width="6400" height="300" fill="url(#sk-fade)"/></mask>`,
  `<clipPath id="sk-above"><rect x="-3200" y="0" width="6400" height="700"/></clipPath>`,
];

// --------------------------------------------------------------------- svg
const scene = `<svg class="sky" viewBox="0 0 2400 860" role="img" aria-label="Downtown Los Angeles at dusk: City Hall, the US Bank Tower and the Wilshire Grand above a street plan lit in green, with water channels in blue" focusable="false">
<defs>
${paint.join('\n')}
${defs.join('\n')}
</defs>
<g transform="translate(1200 560) scale(1 -1)">
<g clip-path="url(#sk-above)">
<g class="sk-dusk">
<rect x="-3200" y="0" width="6400" height="640" fill="url(#sk-dusk)"/>
<circle cx="-560" cy="152" r="380" fill="url(#sk-halo)"/>
<circle cx="-560" cy="152" r="40" fill="url(#sk-sun)"/>
<path d="${ridge}" fill="url(#sk-ridge)"/>
</g>
<g class="sk-back">${back.map(rise).join('\n')}</g>
<rect class="sk-haze" x="-3200" y="0" width="6400" height="110" fill="url(#sk-haze)"/>
<g class="sk-towers">${towers.map(rise).join('\n')}</g>
<g class="sk-front">${front.map(rise).join('\n')}
${greens.map(rise).join('\n')}
${palms.map(rise).join('\n')}</g>
</g>
<g class="sk-streets" mask="url(#sk-plane)">
${streets.map((list, level) => `<path class="st st--${level}" d="${list.join('')}"/>`).reverse().join('\n')}
<path class="wt-body" d="${river.body}"/>
${channels.map((c) => `<path class="wt-body" d="${c.body}"/>`).join('\n')}
<path class="fw-body" d="${freeway.body}"/>
${arterials.map((a, i) => `<path class="ar-glow" style="--i:${i}" pathLength="1" d="${a.d}"/><path class="ar" style="--i:${i}" pathLength="1" d="${a.d}"/>`).join('\n')}
<path class="ar ar--fw" style="--i:${arterials.length}" pathLength="1" d="${freeway.mid}"/>
<path class="wt" style="--i:0" pathLength="1" d="${river.mid}"/>
${channels.map((c, i) => `<path class="wt wt--small" style="--i:${i + 1}" pathLength="1" d="${c.mid}"/>`).join('\n')}
</g>
<path class="sk-ground" d="M-3200 0H3200"/>
</g>
</svg>`;

// The moving layer: headlights along the wide streets, water running down the
// channels, a few windows, the roof beacons and a plane on its way to LAX.
const life = `<svg class="sky sky--life" viewBox="0 0 2400 860" aria-hidden="true" focusable="false">
<g transform="translate(1200 560) scale(1 -1)">
<g mask="url(#sk-plane)">
${arterials.map((a, i) => `<path class="flow flow--cars" style="--t:${r1(3.4 + (i % 3) * 0.7)}s;--w:${r1(-i * 0.9)}s" pathLength="1" d="${a.d}"/>`).join('\n')}
<path class="flow flow--cars" style="--t:5.2s;--w:-2s" pathLength="1" d="${freeway.mid}"/>
<path class="flow flow--water" style="--t:7s;--w:0s" pathLength="1" d="${river.mid}"/>
${channels.map((c, i) => `<path class="flow flow--water flow--small" style="--t:${r1(5 + i * 0.6)}s;--w:${r1(-i * 1.3)}s" pathLength="1" d="${c.mid}"/>`).join('\n')}
</g>
${twinkles.map((t, i) => `<rect class="twinkle" style="--t:${r1(7 + hash(i, 3) * 9)}s;--w:${r1(-hash(i, 5) * 16)}s" x="${t.x}" y="${t.y}" width="${t.w}" height="${t.h}"/>`).join('\n')}
${beacons.map((b) => `<circle class="beacon${b.white ? ' beacon--white' : ''}" style="--w:${b.wait}s" cx="${b.x}" cy="${b.y}" r="2.6"/>`).join('\n')}
<g class="plane"><circle r="1.8" fill="#eef0ea"/><circle class="beacon" style="--w:0s" cx="-5" cy="0" r="1.6"/></g>
</g>
</svg>`;

const page = readFileSync(PAGE, 'utf8');
const start = '<!-- skyline:start -->';
const end = '<!-- skyline:end -->';
const i = page.indexOf(start); const j = page.indexOf(end);
if (i < 0 || j < 0) throw new Error('public/welcome.html has no skyline markers.');
writeFileSync(PAGE, `${page.slice(0, i + start.length)}\n${scene}\n${life}\n${page.slice(j)}`);
console.log(`skyline: ${back.length} far blocks, ${towers.length} towers, ${front.length} low buildings, ${greens.length} trees, ${palms.length} palms, `
  + `${streets.map((s) => s.length).join('/')} streets by class, ${arterials.length} arterials, ${channels.length + 1} channels, `
  + `${twinkles.length} window lights, ${Math.round((scene.length + life.length) / 1024)} KB`);
