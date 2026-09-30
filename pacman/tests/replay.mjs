// Determinism: a recorded game must replay to the same score, tick for tick.
//   node pacman/tests/replay.mjs [logs/pacman-XXXX.jsonl]
// The game takes no input except the seed and jev's decisions keyed by tick, so feeding
// a recording back in has to reproduce the original run exactly. This is what lets the
// demo be published as a replay that costs nothing to watch.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '..', 'static');
const logsDir = path.join(here, '..', 'logs');
const url = (f) => new URL(`file://${path.join(staticDir, f).replace(/\\/g, '/')}`).href;

const { Maze } = await import(url('maze.js'));
const { Game } = await import(url('game.js'));
const mazeText = fs.readFileSync(path.join(staticDir, 'maze.txt'), 'utf8');

const logPath = process.argv[2] || newestLog();
if (!logPath) {
  console.log('no recording with decisions yet: play a game with the server running first');
  process.exit(0);
}

/** The newest recording that has decisions in it. Opening the page and closing it
 *  leaves a file with only the header, and that is not a game to replay. */
function newestLog() {
  if (!fs.existsSync(logsDir)) return null;
  const files = fs.readdirSync(logsDir)
    .filter((f) => f.startsWith('pacman-') && f.endsWith('.jsonl'))
    .map((f) => path.join(logsDir, f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return files.find(hasDecisions) || null;
}

function hasDecisions(file) {
  return fs.readFileSync(file, 'utf8').split('\n')
    .filter((l) => l.trim())
    .some((l) => {
      const record = JSON.parse(l);
      return record.type === 'decision' && record.recv_tick != null;
    });
}

const lines = fs.readFileSync(logPath, 'utf8').split('\n').filter((l) => l.trim());
const records = lines.map((l) => JSON.parse(l));
const header = records.find((r) => r.type === 'header');
const decisions = records
  .filter((r) => r.type === 'decision' && r.recv_tick != null)
  .sort((a, b) => a.recv_tick - b.recv_tick);

if (!header || decisions.length === 0) {
  console.log(`${path.basename(logPath)} has no applied decisions to replay`);
  process.exit(0);
}

/** Replay exactly as the browser does: set the pending move on the recorded tick. */
function replay(untilTick) {
  const maze = new Maze(mazeText);
  const game = new Game(maze, { seed: header.seed });
  const byTick = new Map(decisions.map((d) => [d.recv_tick, d]));
  const trail = [];
  while (game.tick < untilTick) {
    const d = byTick.get(game.tick);
    if (d) {
      const tile = d.state.spain.tile;
      const tileKey = `${tile[0]},${tile[1]}`;
      const next = game.spain.next;
      if (next && `${next.c},${next.r}` === tileKey) {
        game.pending = { tileKey, direction: d.decision.direction };
      } else if (`${game.spain.tile.c},${game.spain.tile.r}` === tileKey) {
        game.redirect(d.decision.direction);
      }
    }
    game.step();
    if (game.tick % 60 === 0) trail.push(`${game.tick}:${game.score}:${game.lives}`);
  }
  return { score: game.score, lives: game.lives, level: game.levelIndex, trail: trail.join('|') };
}

const last = decisions[decisions.length - 1];
const end = last.recv_tick + 1;

let failures = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? `  ${detail}` : ''}`);
  if (!ok) failures++;
};

console.log(`replaying ${path.basename(logPath)}: seed ${header.seed}, ${decisions.length} decisions, `
  + `${(end / 60).toFixed(1)} s of play\n`);

const a = replay(end);
const b = replay(end);
check('two replays agree', a.trail === b.trail && a.score === b.score, `${a.score} and ${b.score} points`);

const recorded = last.score_at_recv;
if (recorded == null) {
  console.log('note  this recording predates score logging, so it cannot be checked against the browser');
} else {
  check('the replay matches the browser that recorded it', a.score === recorded,
    `replay ${a.score}, browser ${recorded}`);
}

const half = replay(Math.floor(end / 2));
check('the replay is consistent part way through', a.trail.startsWith(half.trail));

console.log(failures === 0 ? '\nall good' : `\n${failures} failing`);
process.exit(failures === 0 ? 0 : 1);
