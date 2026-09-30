// Luces de España. España de noche: cada lugar es una luz, y lo que brilla es la
// probabilidad que jev le da a lo que escribes. La luz se mueve con cada tecla.

const $ = (id) => document.getElementById(id);
// 1 $ = 0,88 €: referencia del BCE del 30-09-2026 (0,8825). Las APIs cobran en dólares.
const EUR_PER_USD = 0.88;
const EXAMPLES = [
  'pueblo tranquilo con playa',
  'pueblo tranquilo con playa y surf',
  'fiesta',
  'comer marisco',
  'montaña y silencio',
  'escapada romántica a menos de 2 horas de Madrid',
  'ver las estrellas',
  'algo con vino y sin coger avión',
];
const DEBOUNCE_MS = 170;

const state = {
  places: [],
  target: new Float32Array(0),   // lo que ha dicho jev
  shown: new Float32Array(0),    // lo que se pinta, que persigue a target
  allowed: null,                 // Set de ids que pasan el filtro del código, o null
  xy: [],
  seq: 0,
  lastAnswered: 0,
  typing: null,
};

let ws;
let projection;
let dpr = 1;
let scale = 1;   // halos a escala del mapa: 1 con 1000 px de ancho
const canvas = $('lights');
const ctx = canvas.getContext('2d');

// ------------------------------------------------------------------ arranque
Promise.all([
  fetch('places.json').then((r) => r.json()),
  fetch('vendor/provinces.json').then((r) => r.json()),
]).then(([places, topo]) => {
  state.places = places;
  state.target = new Float32Array(places.length);
  state.shown = new Float32Array(places.length);
  $('opts').textContent = places.length;
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

  const provinces = topojson.feature(topo, topo.objects.provinces);
  projection = d3.geoConicConformalSpain().fitExtent([[40, 40], [w - 40, h - 30]], provinces);
  const path = d3.geoPath(projection);
  const svg = d3.select('#land').attr('viewBox', `0 0 ${w} ${h}`);
  svg.selectAll('*').remove();
  svg.selectAll('path.prov').data(provinces.features).join('path').attr('class', 'prov').attr('d', path);
  svg.append('path').attr('class', 'frame').attr('d', projection.getCompositionBorders());

  scale = Math.max(0.55, Math.min(w, h * 1.3) / 1000);
  state.xy = state.places.map((p) => projection([p.lon, p.lat]) || [-99, -99]);
}

// ------------------------------------------------------------------ conexión
// ?grabacion: sin servidor, con las respuestas guardadas de las búsquedas de ejemplo (mapa/grabar.py).
// Es lo que se publica en GitHub Pages, que no tiene servidor ni gráfica.
const GRABADAS = new URLSearchParams(location.search).has('grabacion')
  ? fetch('grabacion.json').then((r) => r.json()) : null;

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
    setStatus(text.trim() ? 'pensando' : '', !!text.trim());
  }, DEBOUNCE_MS);
}

function receive(msg) {
  if (msg.type !== 'answer' || msg.seq < state.lastAnswered) return;
  state.lastAnswered = msg.seq;
  if (msg.seq === state.seq) setStatus(msg.latency_ms ? `${msg.latency_ms} ms` : '', false);
  if (msg.error) { setStatus('jev no contesta', false); return; }

  state.target.fill(0);
  for (const [id, p] of Object.entries(msg.probs || {})) state.target[Number(id)] = p;
  state.allowed = msg.allowed ? new Set(msg.allowed) : null;

  if (msg.latency_ms) $('lat').textContent = `${msg.latency_ms} ms`;
  if (msg.total_cost_usd != null) $('cost').textContent = `${(msg.total_cost_usd * EUR_PER_USD).toFixed(4).replace('.', ',')} €`;
  $('opts').textContent = msg.allowed ? msg.allowed.length : state.places.length;

  const rules = msg.notes || [];
  $('rules-block').hidden = rules.length === 0;
  $('rules').innerHTML = rules.map((r) => `<span>${escapeHtml(r)}</span>`).join('');
  $('empty').hidden = !msg.empty;

  renderTop(msg.text ? msg.probs || {} : {});
  renderDoubt(msg.text ? msg.probs || {} : null);
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

function renderDoubt(probs) {
  if (!probs || !Object.keys(probs).length) {
    $('doubt-n').textContent = '–';
    $('doubt-text').textContent = 'Escribe algo para empezar.';
    $('doubt-bar').firstElementChild.style.width = '0';
    return;
  }
  // Número efectivo de opciones: e elevado a la entropía. 1 es certeza; 255, no saber nada.
  let h = 0;
  for (const p of Object.values(probs)) if (p > 0) h -= p * Math.log(p);
  const n = Math.exp(h);
  $('doubt-n').textContent = n < 10 ? n.toFixed(1).replace('.', ',') : Math.round(n);
  $('doubt-text').textContent = n < 1.6 ? 'Lo tiene claro.'
    : n < 4 ? 'Duda entre unos pocos sitios.'
    : n < 12 ? 'Duda entre bastantes sitios.'
    : 'Podría ser casi cualquier sitio.';
  $('doubt-bar').firstElementChild.style.width = `${(Math.log(n) / Math.log(state.places.length)) * 100}%`;
}

function setStatus(text, busy) {
  $('status').textContent = text;
  $('status').classList.toggle('busy', busy);
}

// ------------------------------------------------------------------ luces
function frame() {
  const n = state.places.length;
  for (let i = 0; i < n; i++) state.shown[i] += (state.target[i] - state.shown[i]) * 0.12;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Todas las luces encendidas al mínimo, más grandes cuanta más gente vive allí.
  for (let i = 0; i < n; i++) {
    const [x, y] = state.xy[i];
    const off = state.allowed && !state.allowed.has(i);
    const r = 0.8 + Math.log10(state.places[i].pop) * 0.35;
    ctx.fillStyle = off ? 'rgba(80, 90, 110, 0.3)' : 'rgba(255, 214, 150, 0.38)';
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // Lo que jev ilumina: halos que se suman donde se juntan.
  ctx.globalCompositeOperation = 'lighter';
  const t = performance.now() / 1000;
  for (let i = 0; i < n; i++) {
    const p = state.shown[i];
    if (p < 0.003) continue;
    const [x, y] = state.xy[i];
    const flicker = 1 + Math.sin(t * 2.3 + i) * 0.04;
    const r = (12 + 150 * Math.sqrt(p)) * scale * flicker;
    const a = Math.min(1, 0.25 + p * 1.6);
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
  state.target.forEach((p, i) => { if (p >= 0.08) top.push([i, p]); });
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
  // Si el texto nuevo continúa el que ya hay, se sigue escribiendo; si no, se empieza de cero.
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
