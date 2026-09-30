// A whole game with jev deciding, in Node instead of a browser, in real time.
//   python pacman/server.py            (in another terminal)
//   node pacman/tests/play.mjs [--minutes 12] [--seed 1234]
// Headless browsers throttle requestAnimationFrame: a "10 minute" run once advanced the
// game clock by 16 seconds. Here the same game and the same bridge to jev run on a plain
// timer, talking to the real server, so jev's latency weighs as it does on screen.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '..', 'static');
const url = (file) => new URL(`file://${path.join(staticDir, file).replace(/\\/g, '/')}`).href;

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
const minutes = Number(arg('minutes', 12));
const host = arg('host', '127.0.0.1:8770');

globalThis.location = { protocol: 'http:', host };

const { Maze } = await import(url('maze.js'));
const { Game } = await import(url('game.js'));
const { JevLink } = await import(url('jev.js'));

const maze = new Maze(fs.readFileSync(path.join(staticDir, 'maze.txt'), 'utf8'));
const seed = Number(arg('seed', Date.now() & 0xffffffff));
const t0 = Date.now();
const clock = () => ((Date.now() - t0) / 1000).toFixed(0).padStart(4) + ' s';

const game = new Game(maze, {
  seed,
  onEvent: (e) => {
    const where = `nivel ${game.levelIndex + 1}, ${game.pelletsLeft} bolitas, ${game.score} puntos`;
    if (e.type === 'death' || e.type === 'gameover') {
      console.log(`${clock()}  muere (${e.ghost.name}), ${where}`);
      if (process.argv.includes('--debug')) debugDeath(e.ghost);
    }
    else if (e.type === 'levelclear') console.log(`${clock()}  nivel ${e.level + 1} superado, ${game.score} puntos`);
    else if (e.type === 'eaten') console.log(`${clock()}  se come a ${e.ghost.name} (+${e.value})`);
  },
});
const link = new JevLink(game, maze, {});
const trail = [];   // the last few asks, with the rivals as they were, for --debug

function debugDeath(killer) {
  const t = (p) => `${p.c},${p.r}`;
  console.log(`      España en ${t(game.spain.tile)} hacia ${game.spain.dir}; ${killer.name} en ${t(killer.tile)} hacia ${killer.dir} (${killer.state})`);
  for (const a of trail.slice(-4)) console.log(`      ${a}`);
}
link.connect();

console.log(`semilla ${seed}, hasta ${minutes} min`);
await new Promise((resolve) => {
  const wait = setInterval(() => { if (link.connected) { clearInterval(wait); resolve(); } }, 50);
});

let last = performance.now();
const timer = setInterval(() => {
  const now = performance.now();
  game.advance(Math.min((now - last) / 1000, 0.25));
  last = now;
  const before = link.inFlight;
  link.update();
  if (!before && link.inFlight && process.argv.includes('--debug')) {
    const st = link.lastState;
    const rooms = Object.entries(st.by_exit).map(([d, v]) => `${d}:${v.escape_room}/${v.nearest_ghost}`).join(' ');
    const gs = game.ghosts.filter((g) => g.active).map((g) => `${g.name.slice(0, 3)}@${g.tile.c},${g.tile.r}${g.dir[0]}${g.state[0]}`).join(' ');
    trail.push(`t${game.tick} ask ${st.spain.tile} hd ${st.spain.heading} | ${rooms} | ${gs}`);
    if (trail.length > 20) trail.shift();
  }
  const outOfTime = Date.now() - t0 > minutes * 60_000;
  if (game.status === 'won' || game.status === 'lost' || outOfTime) {
    clearInterval(timer);
    const verdict = game.status === 'won' ? 'GANA' : game.status === 'lost' ? 'PIERDE' : 'SIN TERMINAR';
    const s = link.stats;
    console.log(`${clock()}  ${verdict}: nivel ${game.levelIndex + 1}, ${game.score} puntos, ` +
      `${game.lives} vidas, ${game.pelletsLeft} bolitas; ${s.calls} decisiones, ${s.late} tarde, ` +
      `${s.errors} errores, $${s.cost.toFixed(4)}`);
    link.ws?.close();
    setTimeout(() => process.exit(0), 200);
  }
}, 1000 / 60);
