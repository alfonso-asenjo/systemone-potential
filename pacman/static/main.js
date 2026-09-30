// Boot and the frame loop.

import { Maze, TILE, flagSrc } from './maze.js';
import { Game } from './game.js';
import { LEVELS } from './ghosts.js';
import { Renderer } from './render.js';
import { Panel } from './panel.js';
import { JevLink } from './jev.js';

const params = new URLSearchParams(location.search);
const KEYS = {
  ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down',
  a: 'left', d: 'right', w: 'up', s: 'down',
};

async function boot() {
  const maze = await Maze.load();
  const panel = new Panel();

  // A published build ships one recorded game and plays it back; with the server running,
  // ?replay=<file> picks any recording from logs/.
  let replay = null;
  let replayMeta = null;
  const bundled = window.__BUNDLED_REPLAY;
  if (bundled || params.get('replay')) {
    const data = window.__REPLAY_DATA
      || await (await fetch(bundled || `replay/${encodeURIComponent(params.get('replay'))}`)).json();
    replay = new Map(data.decisions.map((m) => [m.recv_tick, m]));
    replayMeta = data;
    document.querySelectorAll('img[data-flag]').forEach((img) => { img.src = flagSrc(img.dataset.flag); });
    params.set('seed', String(data.seed));
  }

  const game = new Game(maze, {
    seed: params.has('seed') ? Number(params.get('seed')) : undefined,
    speed: params.has('speed') ? Number(params.get('speed')) : undefined,
    onEvent: (e) => onEvent(e),
  });

  let last = performance.now();
  const renderer = new Renderer(document.getElementById('pitch'), maze);
  const codes = ['es', ...new Set(LEVELS.flatMap((l) => l.rivals))];
  await renderer.loadFlags(codes);

  let current = null;           // the decision being shown
  const link = new JevLink(game, maze, {
    replay,
    onDecision: (msg) => {
      if (msg.error) { panel.decision(msg); return; }
      current = msg.decision;
      panel.decision(msg);
      const probs = (msg.answers.direction && msg.answers.direction.probabilities) || {};
      // Only junction decisions are drawn on the pitch. In a corridor the options are
      // "carry on" and "turn round", and the arrow for turning round lands under Spain.
      if (msg.reason !== 'cruce') return;
      renderer.setArrows({
        tile: msg.tile,
        direction: msg.decision.direction,
        probabilities: probs,
        held: Boolean(msg.decision.held || msg.decision.fallback),
        tick: game.tick,
      });
    },
    onStats: (stats) => panel.stats(stats, link.medianLatency),
    onHello: (msg) => panel.setBrain(msg.brain),
  });
  link.connect();

  // Do not kick off before the decider is listening, or Spain plays the opening blind.
  if (!replay) {
    game.paused = true;
    const ready = Date.now();
    const waitForLink = setInterval(() => {
      if (link.connected || Date.now() - ready > 4000) {
        clearInterval(waitForLink);
        game.paused = false;
        last = performance.now();
      }
    }, 60);
  }

  function onEvent(e) {
    if (e.type === 'eaten') {
      panel.showResult(e.ghost.rival);
      const p = e.ghost.position(TILE);
      renderer.addPopup(String(e.value), p.x, p.y - 16);
    } else if (e.type === 'levelclear') {
      panel.showLevelCleared(LEVELS[e.level]);
    } else if (e.type === 'won') {
      panel.curtain('Campeona', `España termina con ${game.score.toLocaleString('es-ES')} puntos, como en el Mundial.`, restart);
    } else if (e.type === 'gameover') {
      panel.curtain('Eliminada', `${e.ghost.name} alcanza a España. ${game.score.toLocaleString('es-ES')} puntos.`, restart);
    }
  }

  function restart() {
    if (!replay) game.seed = (Date.now() & 0xffffffff);   // a replay keeps its own seed
    game.reset();
    link.stats = { calls: 0, late: 0, errors: 0, cost: 0, latency: null, latencies: [] };
    panel.stats(link.stats, null);
    current = null;
    renderer.clearArrows();
    panel.hideCurtain();
  }

  document.addEventListener('keydown', (ev) => {
    const dir = KEYS[ev.key] || KEYS[ev.key.toLowerCase?.()];
    // Taking the wheel during a replay would pull the game off the recorded track.
    if (dir && !replay) { ev.preventDefault(); game.setDirection(dir); game.manual = true; panel.mode('teclado'); return; }
    if (ev.key === 'j' || ev.key === 'J') { game.manual = false; panel.mode('ia'); }
    if (ev.key === ' ') { ev.preventDefault(); game.paused = !game.paused; }
    if (ev.key === 'r' || ev.key === 'R') restart();
  });

  let panelClock = 0;
  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.25);
    last = now;
    if (!game.paused) {
      game.advance(dt);
      if (!game.manual) link.update();
    }
    renderer.draw(game, current ? { danger: current.danger, tag: tagFor(current, game) } : null);

    panelClock += dt;
    if (panelClock > 0.15) {
      panelClock = 0;
      panel.scoreboard(game);
      panel.rivals(game);
    }
    requestAnimationFrame(frame);
  }

  if (replay) { panel.setBrain(replayMeta.brain); panel.replayMode(replayMeta); }
  window.__game = game;      // handles for the screenshot harness and the console
  window.__panel = panel;
  window.__link = link;
  panel.scoreboard(game);
  panel.rivals(game);
  requestAnimationFrame(frame);
}

function tagFor(decision, game) {
  if (game.powerLeft > 0 && decision.hunt > 0.6) return 'a cazar';
  if (game.powerLeft <= 0 && decision.go_for_power > 0.6) return 'a por el trofeo';
  return null;
}

boot().catch((err) => {
  document.body.insertAdjacentHTML('afterbegin',
    `<p style="padding:20px;color:#d1343a">No se pudo arrancar el juego: ${err.message}</p>`);
  console.error(err);
});
