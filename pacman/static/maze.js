// The maze: parsing, walkability, tunnel wrap, junctions and BFS distances.
// Single source of truth is maze.txt, shared with pacman/tests/test_maze.py.

export const TILE = 28;

export const DIRS = {
  left:  { dc: -1, dr: 0, angle: Math.PI },
  right: { dc: 1, dr: 0, angle: 0 },
  up:    { dc: 0, dr: -1, angle: -Math.PI / 2 },
  down:  { dc: 0, dr: 1, angle: Math.PI / 2 },
};
export const DIR_NAMES = ['left', 'right', 'up', 'down'];
export const OPPOSITE = { left: 'right', right: 'left', up: 'down', down: 'up' };

const PAC_WALKABLE = new Set([' ', '.', 'o', 'P', 'T']);
const GHOST_WALKABLE = new Set([' ', '.', 'o', 'P', 'T', 'G', '-']);

export class Maze {
  constructor(text) {
    this.rows = text.replace(/\r/g, '').split('\n').filter((l) => l.length > 0);
    this.h = this.rows.length;
    this.w = this.rows[0].length;
    this.grid = this.rows.map((line) => line.split(''));

    this.pellets = new Set();
    this.powerPellets = new Set();
    this.start = null;
    this.house = [];
    this.door = null;
    this.tunnels = [];

    for (let r = 0; r < this.h; r++) {
      for (let c = 0; c < this.w; c++) {
        const ch = this.grid[r][c];
        if (ch === '.') this.pellets.add(key(c, r));
        else if (ch === 'o') { this.pellets.add(key(c, r)); this.powerPellets.add(key(c, r)); }
        else if (ch === 'P') this.start = { c, r };
        else if (ch === 'G') this.house.push({ c, r });
        else if (ch === '-') this.door = { c, r };
        else if (ch === 'T') this.tunnels.push({ c, r });
      }
    }
    this.totalPellets = this.pellets.size;
    this.houseCentre = this.door ? { c: this.door.c, r: this.door.r + 1 } : this.house[0];
    this.junctionCache = new Map();
  }

  static async load(url = 'maze.txt') {
    if (typeof window !== 'undefined' && window.__MAZE_TEXT) return new Maze(window.__MAZE_TEXT);
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`cannot load the maze (${res.status})`);
    return new Maze(await res.text());
  }

  at(c, r) {
    if (r < 0 || r >= this.h) return '#';
    if (c < 0 || c >= this.w) return '#';
    return this.grid[r][c];
  }

  /** Tunnel wrap: stepping off the side of the tunnel row comes back on the other side. */
  wrap(c, r) {
    if (c < 0) return { c: this.w - 1, r };
    if (c >= this.w) return { c: 0, r };
    return { c, r };
  }

  walkable(c, r, forGhost = false) {
    const set = forGhost ? GHOST_WALKABLE : PAC_WALKABLE;
    return set.has(this.at(c, r));
  }

  /** The tile you reach leaving (c,r) in `dir`, or null if it is a wall. */
  step(c, r, dir, forGhost = false) {
    const d = DIRS[dir];
    let nc = c + d.dc;
    const nr = r + d.dr;
    if (nc < 0 || nc >= this.w) {
      if (this.at(c, r) !== 'T' || d.dr !== 0) return null;
      nc = (nc + this.w) % this.w;
    }
    return this.walkable(nc, nr, forGhost) ? { c: nc, r: nr } : null;
  }

  exits(c, r, forGhost = false) {
    const out = [];
    for (const dir of DIR_NAMES) {
      const t = this.step(c, r, dir, forGhost);
      if (t) out.push({ dir, ...t });
    }
    return out;
  }

  /** A junction is a tile Spain can leave three or more ways: somewhere a choice exists. */
  isJunction(c, r) {
    const k = key(c, r);
    if (!this.junctionCache.has(k)) this.junctionCache.set(k, this.exits(c, r).length >= 3);
    return this.junctionCache.get(k);
  }

  /** Breadth-first distance in tiles from one tile to every reachable tile. */
  distancesFrom(c, r, forGhost = false) {
    const dist = new Int16Array(this.w * this.h).fill(-1);
    const idx = (cc, rr) => rr * this.w + cc;
    dist[idx(c, r)] = 0;
    const queue = [{ c, r }];
    for (let head = 0; head < queue.length; head++) {
      const cur = queue[head];
      const d = dist[idx(cur.c, cur.r)];
      for (const nxt of this.exits(cur.c, cur.r, forGhost)) {
        if (dist[idx(nxt.c, nxt.r)] === -1) {
          dist[idx(nxt.c, nxt.r)] = d + 1;
          queue.push({ c: nxt.c, r: nxt.r });
        }
      }
    }
    dist.get = (cc, rr) => {
      const v = dist[idx(cc, rr)];
      return v === -1 ? null : v;
    };
    return dist;
  }

  eatPellet(c, r) {
    const k = key(c, r);
    if (!this.pellets.has(k)) return null;
    this.pellets.delete(k);
    if (this.powerPellets.has(k)) { this.powerPellets.delete(k); return 'power'; }
    return 'pellet';
  }

  reset() {
    this.pellets.clear();
    this.powerPellets.clear();
    for (let r = 0; r < this.h; r++) {
      for (let c = 0; c < this.w; c++) {
        const ch = this.grid[r][c];
        if (ch === '.') this.pellets.add(key(c, r));
        else if (ch === 'o') { this.pellets.add(key(c, r)); this.powerPellets.add(key(c, r)); }
      }
    }
  }
}

/** Flags come from files while developing and from inlined data when published. */
export const flagSrc = (code) =>
  (typeof window !== 'undefined' && window.__FLAGS && window.__FLAGS[code]) || `flags/${code}.svg`;

export const key = (c, r) => `${c},${r}`;
export const unkey = (k) => { const [c, r] = k.split(',').map(Number); return { c, r }; };

/** Deterministic RNG so a seed plus the recorded decisions replays a game exactly. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function rand() {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
