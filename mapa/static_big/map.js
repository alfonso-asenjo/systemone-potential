// Luces de España con los 8.131 municipios. Cada municipio es un punto de luz tenue; lo que
// brilla es cuánto encaja con lo que escribes según Laya, que reordena en local los 50
// candidatos de un buscador de palabras. Sin API: 0 € por búsqueda.

const $ = (id) => document.getElementById(id);
const EXAMPLES = [
  'pueblo tranquilo con playa y surf',
  'ver las estrellas',
  'comer pulpo y marisco',
  'montaña y silencio',
  'ruta de vinos y bodegas',
  'playa con dunas y naturaleza',
  'castillos medievales a menos de 2 horas de Madrid',
  'fiestas con toros en agosto',
];
const DEBOUNCE_MS = 170;

const state = {
  places: [],
  target: new Float32Array(0),
  shown: new Float32Array(0),
  lit: new Set(),                // índices con luz, para no recorrer los 8.131 en cada fotograma
  allowed: null,
  xy: [],
  seq: 0,
  lastAnswered: 0,
  typing: null,
};

let ws;
let projection;
let dpr = 1;
let scale = 1;
const canvas = $('lights');
const ctx = canvas.getContext('2d');
const base = document.createElement('canvas');   // los 8.131 puntos, pintados una sola vez
const bctx = base.getContext('2d');
const fmt = new Intl.NumberFormat('es-ES', { useGrouping: 'always' });   // sin esto, 8131 en vez de 8.131

// ------------------------------------------------------------------ arranque
Promise.all([
  fetch('places.json').then((r) => r.json()),
  fetch('vendor/provinces.json').then((r) => r.json()),
]).then(([places, topo]) => {
  state.places = places;
  state.target = new Float32Array(places.length);
  state.shown = new Float32Array(places.length);
  $('opts').textContent = fmt.format(places.length);
  drawLand(topo);
  window.addEventListener('resize', () => drawLand(topo));
  connect();
  setupInput();
  requestAnimationFrame(frame);
});

function drawLand(topo) {
  const stage = $('stage');
  const w = stage.clientWidth;
  const h = stage.clientHeight;
  dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  base.width = w * dpr;
  base.height = h * dpr;

  const provinces = topojson.feature(topo, topo.objects.provinces);
  projection = d3.geoConicConformalSpain().fitExtent([[40, 40], [w - 40, h - 30]], provinces);
  const path = d3.geoPath(projection);
  const svg = d3.select('#land').attr('viewBox', `0 0 ${w} ${h}`);
  svg.selectAll('*').remove();
  svg.selectAll('path.prov').data(provinces.features).join('path').attr('class', 'prov').attr('d', path);
  svg.append('path').attr('class', 'frame').attr('d', projection.getCompositionBorders());

  scale = Math.max(0.55, Math.min(w, h * 1.3) / 1000);
  state.xy = state.places.map((p) => projection([p.lon, p.lat]) || [-99, -99]);
  drawBase();
}

// Los 8.131 municipios de fondo, más grandes cuanta más gente vive allí. Solo se repinta si
// cambia el tamaño o el filtro del código (horas, avión), no en cada fotograma.
function drawBase() {
  bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  bctx.clearRect(0, 0, base.width, base.height);
  const n = state.places.length;
  for (let i = 0; i < n; i++) {
    const [x, y] = state.xy[i];
    const off = state.allowed && !state.allowed.has(i);
    const r = (0.35 + Math.log10(state.places[i].pop) * 0.28) * Math.max(0.8, scale);
    bctx.fillStyle = off ? 'rgba(70, 80, 100, 0.25)' : 'rgba(255, 214, 150, 0.30)';
    bctx.beginPath();
    bctx.arc(x, y, r, 0, Math.PI * 2);
    bctx.fill();
  }
}

// ------------------------------------------------------------------ conexión
// ?grabacion: sin servidor, con las respuestas guardadas de las búsquedas de ejemplo (mapa/grabar.py).
// Es lo que se publica en GitHub Pages, que no tiene servidor ni gráfica.
const GRABADAS = new URLSearchParams(location.search).has('grabacion')
  ? fetch('grabacion.json').then((r) => r.json()) : null;


// el aviso grande de las grabaciones: no hay ningún modelo funcionando, pero es lo que uno dijo en directo
if (GRABADAS) GRABADAS.then((d) => {
  const m = d._meta || {};
  delete d._meta;
  const el = document.getElementById('rec');
  el.innerHTML = '<b>● Búsquedas grabadas</b> Las respuestas las dio ' + (m.modelo || 'el modelo') + ' en directo'
    + (m.fecha ? ' el ' + m.fecha : '') + '. Aquí se reproducen tal cual, sin ningún modelo funcionando: '
    + 'solo responden las búsquedas de ejemplo.';
  el.hidden = false;
});

function connect() {
  if (GRABADAS) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => receive(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 1200);
}

let debounce = null;
function ask(text) {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    if (GRABADAS) {
      GRABADAS.then((saved) => {
        const t = text.trim(), m = saved[t];
        state.seq++;
        if (m || !t) receive({ ...(m || { probs: {}, text: '' }), type: 'answer', seq: state.seq });
        else if (!Object.keys(saved).some((e) => e.startsWith(t)))
          setStatus('versión grabada: prueba una de las búsquedas de ejemplo', false);
      });
      return;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    state.seq++;
    ws.send(JSON.stringify({ type: 'ask', seq: state.seq, text }));
    setStatus(text.trim() ? 'buscando' : '', !!text.trim());
  }, DEBOUNCE_MS);
}

function receive(msg) {
  if (msg.type !== 'answer' || msg.seq < state.lastAnswered) return;
  state.lastAnswered = msg.seq;
  if (msg.seq === state.seq) setStatus(msg.latency_ms ? `${msg.latency_ms} ms` : '', false);

  for (const i of state.lit) state.target[i] = 0;
  for (const [id, p] of Object.entries(msg.probs || {})) {
    state.target[Number(id)] = p;
    state.lit.add(Number(id));
  }
  const allowed = msg.allowed ? new Set(msg.allowed) : null;
  const changed = (allowed ? allowed.size : -1) !== (state.allowed ? state.allowed.size : -1);
  state.allowed = allowed;
  if (changed) drawBase();

  if (msg.latency_ms) $('lat').textContent = `${msg.latency_ms} ms`;
  $('opts').textContent = fmt.format(msg.allowed ? msg.allowed.length : state.places.length);

  const rules = msg.notes || [];
  $('rules-block').hidden = rules.length === 0;
  $('rules').innerHTML = rules.map((r) => `<span>${escapeHtml(r)}</span>`).join('');
  $('empty').hidden = !msg.empty;

  renderTop(msg.text ? msg.probs || {} : {});
  renderDoubt(msg.text ? msg.probs || {} : null, msg.candidates || 100);
}

// ------------------------------------------------------------------ panel
function ranked(probs) {
  return Object.entries(probs).map(([id, p]) => [Number(id), p]).sort((a, b) => b[1] - a[1]);
}

function renderTop(probs) {
  const top = ranked(probs).slice(0, 5);
  const max = top.length ? top[0][1] : 1;
  $('top').innerHTML = top.map(([id, p]) => {
    const pl = state.places[id];
    return `<li><span><span class="name">${escapeHtml(pl.name)}</span><span class="prov">${escapeHtml(pl.prov)}</span></span>
      <span class="pct">${pct(p)}</span><span class="bar"><i style="width:${(p / max) * 100}%"></i></span></li>`;
  }).join('');
}

function renderDoubt(probs, n0) {
  if (!probs || !Object.keys(probs).length) {
    $('doubt-n').textContent = '–';
    $('doubt-text').textContent = 'Escribe algo para empezar.';
    $('doubt-bar').firstElementChild.style.width = '0';
    return;
  }
  // Número efectivo de opciones entre los candidatos: e elevado a la entropía.
  let h = 0;
  for (const p of Object.values(probs)) if (p > 0) h -= p * Math.log(p);
  const n = Math.exp(h);
  $('doubt-n').textContent = n < 10 ? n.toFixed(1).replace('.', ',') : Math.round(n);
  $('doubt-text').textContent = n < 1.6 ? 'Lo tiene claro.'
    : n < 4 ? 'Duda entre unos pocos sitios.'
    : n < 12 ? 'Duda entre bastantes sitios.'
    : 'Podría ser casi cualquiera de los candidatos.';
  $('doubt-bar').firstElementChild.style.width = `${(Math.log(n) / Math.log(n0)) * 100}%`;
}

function setStatus(text, busy) {
  $('status').textContent = text;
  $('status').classList.toggle('busy', busy);
}

// ------------------------------------------------------------------ luces
function frame() {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(base, 0, 0);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.globalCompositeOperation = 'lighter';
  const t = performance.now() / 1000;
  for (const i of state.lit) {
    state.shown[i] += (state.target[i] - state.shown[i]) * 0.12;
    const p = state.shown[i];
    if (p < 0.002) {
      if (state.target[i] === 0) state.lit.delete(i);
      continue;
    }
    const [x, y] = state.xy[i];
    const flicker = 1 + Math.sin(t * 2.3 + i) * 0.04;
    const r = (7 + 110 * Math.sqrt(p)) * scale * flicker;
    const a = Math.min(1, 0.3 + p * 2.2);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, `rgba(255, 241, 201, ${a})`);
    g.addColorStop(0.18, `rgba(255, 181, 71, ${a * 0.75})`);
    g.addColorStop(0.55, `rgba(214, 96, 24, ${a * 0.22})`);
    g.addColorStop(1, 'rgba(120, 40, 0, 0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';

  placeLabels();
  requestAnimationFrame(frame);
}

let labelKey = '';
function placeLabels() {
  const top = [];
  for (const i of state.lit) if (state.target[i] >= 0.05) top.push([i, state.target[i]]);
  top.sort((a, b) => b[1] - a[1]);
  const pick = top.slice(0, 3);
  const key = pick.map(([i, p]) => `${i}:${Math.round(p * 100)}`).join('|') + `@${state.xy.length && state.xy[0][0]}`;
  if (key === labelKey) return;
  labelKey = key;
  $('labels').innerHTML = pick.map(([i, p]) => {
    const [x, y] = state.xy[i];
    return `<div class="label" style="left:${x}px;top:${y}px">${escapeHtml(state.places[i].name)}<small>${pct(p)}</small></div>`;
  }).join('');
}

// ------------------------------------------------------------------ entrada
function setupInput() {
  const q = $('q');
  q.addEventListener('input', () => { stopTyping(); ask(q.value); });
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { clearTimeout(debounce); ask(q.value); } });

  $('chips').innerHTML = EXAMPLES.map((e) => `<button type="button">${escapeHtml(e)}</button>`).join('');
  $('chips').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => typeOut(b.textContent)));

  // ?demo escribe los ejemplos uno tras otro, letra a letra, para grabar sin tocar nada.
  if (new URLSearchParams(location.search).has('demo')) {
    let k = 0;
    const next = () => typeOut(EXAMPLES[k++ % EXAMPLES.length], () => setTimeout(next, 3200));
    setTimeout(next, 1200);
  }
}

function typeOut(text, done) {
  stopTyping();
  const q = $('q');
  let i = text.startsWith(q.value) ? q.value.length : 0;
  if (i === 0) q.value = '';
  state.typing = setInterval(() => {
    if (i >= text.length) { stopTyping(); if (done) done(); return; }
    q.value += text[i++];
    ask(q.value);
  }, 65);
}

function stopTyping() {
  if (state.typing) clearInterval(state.typing);
  state.typing = null;
}

// ------------------------------------------------------------------ utilidades
function pct(p) {
  return p >= 0.995 ? '99 %' : `${Math.max(1, Math.round(p * 100))} %`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
