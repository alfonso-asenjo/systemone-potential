// The game itself: fixed-step, seeded, deterministic. Given a seed and the decisions
// keyed by tick, a game replays exactly.

import { DIRS, OPPOSITE, TILE, mulberry32, key } from './maze.js';
import { LEVELS, buildGhosts, globalMode } from './ghosts.js';

const STEP = 1 / 60;
const POWER_SECONDS = 7;
const GHOST_VALUES = [200, 400, 800, 1600];
const DEATH_PAUSE = 1.6;
const LEVEL_PAUSE = 2.4;

export class Game {
  constructor(maze, opts = {}) {
    this.maze = maze;
    this.seed = opts.seed ?? (Date.now() & 0xffffffff);
    // 2.2 tiles a second gives an answer 455 ms to arrive. At 2.5 the budget was 400 ms
    // and a measured tenth of the answers missed it.
    this.spainSpeed = opts.speed ?? 2.2;
    this.onEvent = opts.onEvent || (() => {});
    this.paused = false;
    this.manual = false;        // true while a human holds the keyboard
    this.reset();
  }

  reset() {
    this.rand = mulberry32(this.seed);
    this.tick = 0;
    this.elapsed = 0;          // seconds of the current level, drives the ghost timeline
    this.levelIndex = 0;
    this.score = 0;
    this.lives = 3;
    this.status = 'playing';   // playing | dead | levelup | won | lost
    this.pauseFor = 0;
    this.powerLeft = 0;
    this.ghostChain = 0;
    this.maze.reset();
    this.startLevel(0);
  }

  startLevel(index) {
    this.levelIndex = index;
    this.level = LEVELS[Math.min(index, LEVELS.length - 1)];
    this.maze.reset();
    this.ghosts = buildGhosts(index, this.maze);
    this.elapsed = 0;
    this.powerLeft = 0;
    this.resetPositions();
  }

  resetPositions() {
    const s = this.maze.start;
    this.spain = {
      tile: { c: s.c, r: s.r },
      next: null,
      progress: 0,
      dir: 'left',
      mouth: 0,
    };
    this.queuedDir = null;      // keyboard
    this.pending = null;        // decision waiting for the tile it was asked about
    for (const g of this.ghosts) g.reset();
  }

  get mode() {
    return globalMode(this.elapsed);
  }

  get pelletsLeft() {
    return this.maze.pellets.size;
  }

  position(entity) {
    const from = entity.tile;
    const to = entity.next || entity.tile;
    let dc = to.c - from.c;
    if (Math.abs(dc) > 1) dc = -Math.sign(dc);
    const dr = to.r - from.r;
    return {
      x: (from.c + 0.5 + dc * entity.progress) * TILE,
      y: (from.r + 0.5 + dr * entity.progress) * TILE,
    };
  }

  /** Advance real time in fixed steps so physics never depends on frame rate. */
  advance(dtSeconds) {
    this.accumulator = (this.accumulator || 0) + Math.min(dtSeconds, 0.25);
    while (this.accumulator >= STEP) {
      this.accumulator -= STEP;
      this.step();
    }
  }

  step() {
    this.tick++;
    if (this.status === 'won' || this.status === 'lost') return;

    if (this.pauseFor > 0) {
      this.pauseFor -= STEP;
      if (this.pauseFor <= 0) {
        if (this.status === 'dead') {
          this.status = 'playing';
          this.resetPositions();
        } else if (this.status === 'levelup') {
          if (this.levelIndex + 1 >= LEVELS.length) {
            this.status = 'won';
            this.onEvent({ type: 'won', score: this.score });
          } else {
            this.status = 'playing';
            this.startLevel(this.levelIndex + 1);
            this.onEvent({ type: 'level', level: this.levelIndex });
          }
        }
      }
      return;
    }

    this.elapsed += STEP;
    if (this.powerLeft > 0) {
      this.powerLeft -= STEP;
      if (this.powerLeft <= 0) {
        this.powerLeft = 0;
        this.ghostChain = 0;
        for (const g of this.ghosts) if (g.state === 'frightened') g.state = this.mode;
      }
    }

    this.moveSpain();
    for (const g of this.ghosts) {
      const wasActive = g.active;
      g.update(STEP, this);
      if (wasActive && g.active && g.state !== this.mode && this.powerLeft <= 0) {
        g.state = this.mode;      // follow the global scatter/chase timeline
        g.reverse();
      }
    }
    this.checkCollisions();
  }

  // ------------------------------------------------------------------ Spain
  moveSpain() {
    const s = this.spain;
    s.mouth = Math.abs(Math.sin(this.tick * 0.18));

    if (!s.next) {
      const dir = this.pickDirection();
      const t = this.maze.step(s.tile.c, s.tile.r, dir);
      if (!t) return;
      s.dir = dir;
      s.next = t;
    }

    s.progress += this.spainSpeed * STEP;
    while (s.progress >= 1) {
      s.progress -= 1;
      s.tile = s.next;
      this.arriveAt(s.tile);
      if (this.status !== 'playing') { s.progress = 0; s.next = null; return; }
      const dir = this.pickDirection();
      const t = this.maze.step(s.tile.c, s.tile.r, dir);
      if (!t) { s.progress = 0; s.next = null; return; }
      s.dir = dir;
      s.next = t;
    }
  }

  /** Keyboard first, then a decision waiting for this tile, then straight on, then the safe exit. */
  pickDirection() {
    const s = this.spain;
    if (this.queuedDir && this.maze.step(s.tile.c, s.tile.r, this.queuedDir)) {
      const dir = this.queuedDir;
      this.queuedDir = null;
      this.lastSource = 'teclado';
      return dir;
    }
    if (this.pending && this.pending.tileKey === key(s.tile.c, s.tile.r)) {
      const dir = this.pending.direction;
      this.pending = null;
      if (this.maze.step(s.tile.c, s.tile.r, dir)) {
        this.lastSource = 'jev';
        return dir;
      }
    }
    if (this.maze.step(s.tile.c, s.tile.r, s.dir)) {
      this.lastSource = this.lastSource === 'jev' ? 'jev' : 'recto';
      return s.dir;
    }
    this.lastSource = 'regla de seguridad';
    return this.safestExit();
  }

  /** No answer and no way straight on: take the exit whose nearest live ghost is furthest. */
  safestExit() {
    const s = this.spain;
    const exits = this.maze.exits(s.tile.c, s.tile.r);
    if (exits.length === 0) return OPPOSITE[s.dir];
    let best = exits[0];
    let bestScore = -Infinity;
    for (const e of exits) {
      const dist = this.maze.distancesFrom(e.c, e.r);
      let nearest = 99;
      for (const g of this.ghosts) {
        if (g.state === 'eyes' || g.state === 'frightened' || g.state === 'house') continue;
        const d = dist.get(g.tile.c, g.tile.r);
        if (d !== null && d < nearest) nearest = d;
      }
      const score = nearest - (e.dir === OPPOSITE[s.dir] ? 2 : 0);
      if (score > bestScore) { bestScore = score; best = e; }
    }
    return best.dir;
  }

  arriveAt(tile) {
    const eaten = this.maze.eatPellet(tile.c, tile.r);
    if (eaten === 'pellet') {
      this.score += 10;
    } else if (eaten === 'power') {
      this.score += 50;
      this.powerLeft = POWER_SECONDS;
      this.ghostChain = 0;
      for (const g of this.ghosts) {
        if (g.active) { g.state = 'frightened'; g.reverse(); }
      }
      this.onEvent({ type: 'power' });
    }
    if (this.pelletsLeft === 0) {
      this.status = 'levelup';
      this.pauseFor = LEVEL_PAUSE;
      this.onEvent({ type: 'levelclear', level: this.levelIndex });
    }
  }

  // ------------------------------------------------------------ collisions
  checkCollisions() {
    const p = this.position(this.spain);
    for (const g of this.ghosts) {
      if (g.state === 'eyes' || g.state === 'house') continue;
      const q = g.position(TILE);
      if (Math.hypot(p.x - q.x, p.y - q.y) > TILE * 0.55) continue;

      if (g.state === 'frightened') {
        const value = GHOST_VALUES[Math.min(this.ghostChain, GHOST_VALUES.length - 1)];
        this.ghostChain++;
        this.score += value;
        g.state = 'eyes';
        g.eatenValue = value;
        this.onEvent({ type: 'eaten', ghost: g, value });
      } else {
        this.lives--;
        this.status = this.lives > 0 ? 'dead' : 'lost';
        this.pauseFor = DEATH_PAUSE;
        this.onEvent({ type: this.lives > 0 ? 'death' : 'gameover', ghost: g });
        return;
      }
    }
  }

  /** A decision that arrived a moment late can still be used, if she has barely left the tile. */
  redirect(dir) {
    const s = this.spain;
    if (s.progress > 0.25) return false;
    const t = this.maze.step(s.tile.c, s.tile.r, dir);
    if (!t) return false;
    s.dir = dir;
    s.next = t;
    s.progress = 0;
    this.lastSource = 'jev';
    return true;
  }

  // ------------------------------------------------------- input for humans
  setDirection(dir) {
    if (DIRS[dir]) this.queuedDir = dir;
  }
}
