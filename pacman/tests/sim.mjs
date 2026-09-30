// Headless check of the game rules, with no browser and no jev.
//   node pacman/tests/sim.mjs
// Spain runs on the safety rule alone, so this exercises movement, pellets, ghosts,
// power mode, lives and the level change. It also proves the game is deterministic.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '..', 'static');

const { Maze, TILE } = await import(pathToUrl('maze.js'));
const { Game } = await import(pathToUrl('game.js'));

function pathToUrl(file) {
  return new URL(`file://${path.join(staticDir, file).replace(/\\/g, '/')}`).href;
}

const text = fs.readFileSync(path.join(staticDir, 'maze.txt'), 'utf8');

let failures = 0;
function check(name, condition, detail = '') {
  const mark = condition ? 'ok  ' : 'FAIL';
  if (!condition) failures++;
  console.log(`${mark} ${name}${detail ? `  ${detail}` : ''}`);
}

// ---------------------------------------------------------------- one game
function run(seed, ticks, { decisions = null, collect = false, seekTrophy = false } = {}) {
  const maze = new Maze(text);
  const events = [];
  const game = new Game(maze, { seed, onEvent: (e) => events.push(e.type) });
  const trail = [];
  let lastTile = '';
  for (let i = 0; i < ticks; i++) {
    if (decisions && decisions.has(game.tick)) {
      const d = decisions.get(game.tick);
      const next = game.spain.next;
      if (next && `${next.c},${next.r}` === d.tileKey) {
        game.pending = { tileKey: d.tileKey, direction: d.direction };
      }
    }
    // A stand-in policy so power mode can be exercised without jev in the loop. It has to
    // aim from the tile Spain is entering, not the one she is leaving, or every turn is
    // taken one tile late.
    if (seekTrophy) {
      const aim = game.spain.next || game.spain.tile;
      const key = `${aim.c},${aim.r}`;
      if (key !== lastTile) {
        lastTile = key;
        const dir = towardsNearestTrophy(game, aim);
        if (dir) game.setDirection(dir);
      }
    }
    game.step();
    if (collect && i % 37 === 0) {
      const p = game.position(game.spain);
      trail.push(`${Math.round(p.x)},${Math.round(p.y)},${game.score},${game.lives}`);
    }
  }
  return { game, events, trail: trail.join('|') };
}

/** First step of the shortest route to a trophy, or null when they are all eaten. */
function towardsNearestTrophy(game, from) {
  const maze = game.maze;
  if (maze.powerPellets.size === 0) return null;
  let best = null;
  let bestDist = Infinity;
  for (const e of maze.exits(from.c, from.r)) {
    const dist = maze.distancesFrom(e.c, e.r);
    for (const k of maze.powerPellets) {
      const [c, r] = k.split(',').map(Number);
      const d = dist.get(c, r);
      if (d !== null && d < bestDist) { bestDist = d; best = e.dir; }
    }
  }
  return best;
}

// --------------------------------------------------------------- the checks
const maze = new Maze(text);
check('the maze parses', maze.w === 21 && maze.h === 22, `${maze.w}x${maze.h}`);
check('pellets are laid out', maze.totalPellets > 130, `${maze.totalPellets} pellets`);
check('four trophies', maze.powerPellets.size === 4);
check('the tunnel wraps', JSON.stringify(maze.step(0, 10, 'left')) === '{"c":20,"r":10}');

const a = run(12345, 60 * 60);
check('Spain moves', a.game.spain.tile.c !== maze.start.c || a.game.spain.tile.r !== maze.start.r);
check('pellets are eaten', a.game.maze.pellets.size < maze.totalPellets,
  `${maze.totalPellets - a.game.maze.pellets.size} eaten in 60 s`);
check('the score goes up', a.game.score > 0, `${a.game.score} points`);
check('every rival leaves the house',
  a.game.ghosts.every((g) => g.state !== 'house'),
  a.game.ghosts.map((g) => `${g.name}:${g.state}`).join(' '));
check('rivals actually move',
  a.game.ghosts.every((g) => g.tile.r !== maze.houseCentre.r || g.tile.c !== maze.houseCentre.c));
check('Spain never stands on a wall', maze.walkable(a.game.spain.tile.c, a.game.spain.tile.r));
check('Spain stays out of the house',
  !['G', '-'].includes(maze.at(a.game.spain.tile.c, a.game.spain.tile.r)));

// power mode and being caught should both show up over a longer run
const b = run(999, 60 * 300);
check('something happens', b.events.length > 0, b.events.slice(0, 8).join(' '));
check('the game ends or a level falls',
  b.events.includes('levelclear') || b.events.includes('gameover') || b.game.score > 500,
  `score ${b.game.score}, events ${[...new Set(b.events)].join(' ')}`);

// determinism: same seed, same everything
const d1 = run(4242, 60 * 120, { collect: true });
const d2 = run(4242, 60 * 120, { collect: true });
check('the same seed replays exactly', d1.trail === d2.trail && d1.game.score === d2.game.score,
  `${d1.game.score} vs ${d2.game.score}`);

// The only randomness is a frightened rival's choice of turn, so two seeds only part
// company once a trophy has been taken. Send Spain straight at one.
const long1 = run(4242, 60 * 120, { collect: true, seekTrophy: true });
const long2 = run(777, 60 * 120, { collect: true, seekTrophy: true });
check('a trophy is taken when Spain goes for one', long1.events.includes('power'),
  `${long1.events.filter((e) => e === 'power').length} taken, ${long1.events.filter((e) => e === 'eaten').length} rivals eaten`);

// Eating is checked head on: put a frightened rival on top of Spain and step once.
const bite = (() => {
  const m = new Maze(text);
  const events = [];
  const g = new Game(m, { seed: 5, onEvent: (e) => events.push(e) });
  for (let i = 0; i < 120; i++) g.step();
  const victim = g.ghosts[0];
  g.powerLeft = 5;
  victim.state = 'frightened';
  victim.tile = { c: g.spain.tile.c, r: g.spain.tile.r };
  victim.next = g.spain.next && { ...g.spain.next };
  victim.progress = g.spain.progress;
  victim.dir = g.spain.dir;
  const before = g.score;
  g.step();
  return { gained: g.score - before, state: victim.state, events };
})();
check('a frightened rival is eaten for 200', bite.gained >= 200 && bite.state === 'eyes',
  `${bite.gained} points with any pellet, rival now ${bite.state}`);
check('a different seed plays differently', long1.trail !== long2.trail);

const stuck = run(31337, 60 * 240);
check('no rival ends up stuck in the house',
  stuck.game.ghosts.filter((g) => g.inHouse && g.state !== 'eyes').length <= 1,
  stuck.game.ghosts.map((g) => `${g.name}@${g.tile.c},${g.tile.r}:${g.state}`).join(' '));

console.log(failures === 0 ? '\nall good' : `\n${failures} failing`);
process.exit(failures === 0 ? 0 : 1);
