// The escape room on hand-placed rivals, no browser and no jev.
//   node pacman/tests/escape.mjs
// Spain is about to enter (5,1), the junction at the top left, and looks right: a corridor
// that runs to (9,1), turns down and reaches the junction at (9,4) after 7 tiles.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '..', 'static');
const url = (file) => new URL(`file://${path.join(staticDir, file).replace(/\\/g, '/')}`).href;

const { Maze } = await import(url('maze.js'));
const { JevLink } = await import(url('jev.js'));

const maze = new Maze(fs.readFileSync(path.join(staticDir, 'maze.txt'), 'utf8'));
const OPEN = 12;

let failures = 0;
function check(name, ok, detail) {
  if (!ok) failures++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}  ${detail}`);
}

function room(ghosts, dir = 'right') {
  const link = Object.create(JevLink.prototype);
  link.maze = maze;
  link.game = {
    spainSpeed: 2.2,
    ghosts: ghosts.map((g) => ({ active: true, speed: 1.6, ...g })),
  };
  return link.escapeRoom({ c: 5, r: 1 }, dir);
}

let r = room([{ tile: { c: 9, r: 4 }, dir: 'up' }]);
check('rival coming up at the far end: a trap', r < 7, `room ${r}`);
r = room([{ tile: { c: 1, r: 1 }, dir: 'right' }]);
check('rival behind her: open ground', r === OPEN, `room ${r}`);
r = room([{ tile: { c: 9, r: 4 }, dir: 'up' }], 'down');
check('same rival, the other exit is open', r === OPEN, `room ${r}`);
r = room([{ tile: { c: 9, r: 4 }, dir: 'up', active: false }]);
check('a frightened rival does not cut her off', r === OPEN, `room ${r}`);
r = room([{ tile: { c: 1, r: 1 }, dir: 'right' }, { tile: { c: 9, r: 4 }, dir: 'up' }]);
check('behind and ahead at once: a trap', r < 7, `room ${r}`);
// Past the first junction: the corridor itself is clear, but rivals hold every way on from
// (9,4). The one-junction margin called this safe.
r = room([{ tile: { c: 13, r: 4 }, dir: 'left' }, { tile: { c: 6, r: 4 }, dir: 'right' }, { tile: { c: 9, r: 6 }, dir: 'up' }]);
check('clear corridor, every way on from the next junction cut', r < OPEN, `room ${r}`);

console.log(failures ? `\n${failures} failing` : '\nall good');
process.exit(failures ? 1 : 0);
