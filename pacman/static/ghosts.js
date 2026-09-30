// The rivals. Four personalities, the classic scatter/chase timeline, the house and the door.

import { DIRS, DIR_NAMES, OPPOSITE } from './maze.js';

/** Spain's eight opponents on the way to the 2026 title, in the order they were played. */
export const RIVALS = {
  cv: { name: 'Cabo Verde', flag: 'cv', score: '0-0', phase: 'Grupo H', date: '15 de junio' },
  sa: { name: 'Arabia Saudí', flag: 'sa', score: '4-0', phase: 'Grupo H', date: '21 de junio' },
  uy: { name: 'Uruguay', flag: 'uy', score: '1-0', phase: 'Grupo H', date: '26 de junio' },
  at: { name: 'Austria', flag: 'at', score: '3-0', phase: 'Dieciseisavos', date: '2 de julio' },
  pt: { name: 'Portugal', flag: 'pt', score: '1-0', phase: 'Octavos', date: '6 de julio' },
  be: { name: 'Bélgica', flag: 'be', score: '2-1', phase: 'Cuartos', date: '10 de julio' },
  fr: { name: 'Francia', flag: 'fr', score: '2-0', phase: 'Semifinal', date: '14 de julio' },
  ar: { name: 'Argentina', flag: 'ar', score: '1-0', phase: 'Final, en la prórroga', date: '19 de julio' },
};

export const LEVELS = [
  { name: 'Fase de grupos y dieciseisavos', rivals: ['uy', 'at', 'sa', 'cv'] },
  { name: 'Camino a la final', rivals: ['ar', 'fr', 'be', 'pt'] },
];

export const ROLES = ['chaser', 'ambusher', 'flanker', 'wanderer'];
export const ROLE_LABEL = {
  chaser: 'va directo a por España',
  ambusher: 'se adelanta para cortarle el paso',
  flanker: 'la rodea por el otro lado',
  wanderer: 'ronda su esquina y ataca de lejos',
};

const RELEASE_SECONDS = [0, 5, 11, 17];

// Scatter corners, one per role, in tile coordinates.
const CORNERS = {
  chaser: { c: 19, r: 1 },
  ambusher: { c: 1, r: 1 },
  flanker: { c: 19, r: 20 },
  wanderer: { c: 1, r: 20 },
};

// Alternating global mood, as in the original: scatter, chase, ... then chase for good.
const TIMELINE = [
  { mode: 'scatter', seconds: 12 },
  { mode: 'chase', seconds: 20 },
  { mode: 'scatter', seconds: 7 },
  { mode: 'chase', seconds: 20 },
  { mode: 'scatter', seconds: 5 },
  { mode: 'chase', seconds: Infinity },
];

export function globalMode(elapsedSeconds) {
  let t = elapsedSeconds;
  for (const phase of TIMELINE) {
    if (t < phase.seconds) return phase.mode;
    t -= phase.seconds;
  }
  return 'chase';
}

export class Ghost {
  constructor(code, role, index, maze) {
    this.code = code;
    this.rival = RIVALS[code];
    this.name = this.rival.name;
    this.role = role;
    this.index = index;
    this.maze = maze;
    this.releaseAt = RELEASE_SECONDS[index];
    this.reset();
  }

  reset() {
    const house = this.maze.houseCentre;
    this.tile = { c: house.c, r: house.r };
    this.progress = 0;
    this.dir = 'up';
    this.next = null;
    this.state = 'house';        // house | scatter | chase | frightened | eyes
    this.eatenValue = 0;
  }

  get speed() {
    if (this.state === 'eyes') return 4.0;
    if (this.state === 'frightened') return 1.25;
    return 1.6;
  }

  get active() {
    return this.state === 'scatter' || this.state === 'chase';
  }

  /** Pixel centre, interpolating between the current tile and the one being entered. */
  position(tileSize) {
    const from = this.tile;
    const to = this.next || this.tile;
    let dc = to.c - from.c;
    if (Math.abs(dc) > 1) dc = -Math.sign(dc);   // crossing the tunnel
    const dr = to.r - from.r;
    return {
      x: (from.c + 0.5 + dc * this.progress) * tileSize,
      y: (from.r + 0.5 + dr * this.progress) * tileSize,
    };
  }

  get inHouse() {
    const ch = this.maze.at(this.tile.c, this.tile.r);
    return ch === 'G' || ch === '-';
  }

  target(game) {
    if (this.state === 'eyes') return this.maze.houseCentre;
    // Inside the house and alive: the only thing that matters is getting out of the door.
    // Without this a rival that has just been eaten walks back in and rattles around forever.
    if (this.inHouse) return { c: this.maze.door.c, r: this.maze.door.r - 1 };
    if (this.state === 'scatter') return CORNERS[this.role];

    const spain = game.spain.tile;
    const heading = DIRS[game.spain.dir];
    switch (this.role) {
      case 'chaser':
        return spain;
      case 'ambusher':
        return { c: spain.c + heading.dc * 4, r: spain.r + heading.dr * 4 };
      case 'flanker': {
        const pivot = { c: spain.c + heading.dc * 2, r: spain.r + heading.dr * 2 };
        const chaser = game.ghosts.find((g) => g.role === 'chaser') || this;
        return { c: pivot.c * 2 - chaser.tile.c, r: pivot.r * 2 - chaser.tile.r };
      }
      case 'wanderer':
      default: {
        const d = Math.hypot(spain.c - this.tile.c, spain.r - this.tile.r);
        return d > 8 ? spain : CORNERS.wanderer;
      }
    }
  }

  /** Classic rule: at every tile, take the exit whose tile lands nearest the target, never reversing. */
  chooseDirection(game) {
    const { c, r } = this.tile;
    const inHouse = this.inHouse;
    const exits = this.maze.exits(c, r, true).filter((e) => {
      if (e.dir === OPPOSITE[this.dir] && !this.reverseQueued) return false;
      // only eyes and ghosts still leaving may use the door, and never downwards into the house
      const ch = this.maze.at(e.c, e.r);
      if (ch === '-' && !(this.state === 'eyes' || inHouse)) return false;
      if (ch === 'G' && this.state !== 'eyes' && !inHouse) return false;
      return true;
    });
    this.reverseQueued = false;
    if (exits.length === 0) return OPPOSITE[this.dir];

    if (this.state === 'frightened') {
      return exits[Math.floor(game.rand() * exits.length)].dir;
    }
    const target = this.target(game);
    let best = exits[0];
    let bestD = Infinity;
    for (const e of exits) {
      const d = (e.c - target.c) ** 2 + (e.r - target.r) ** 2;
      if (d < bestD) { bestD = d; best = e; }
    }
    return best.dir;
  }

  reverse() {
    this.reverseQueued = true;
  }

  update(dt, game) {
    if (this.state === 'house') {
      if (game.elapsed >= this.releaseAt) {
        this.state = game.mode;
        this.dir = 'up';
      } else {
        return;
      }
    }

    if (!this.next) {
      this.dir = this.chooseDirection(game);
      this.next = this.maze.step(this.tile.c, this.tile.r, this.dir, true) || null;
      if (!this.next) { this.dir = OPPOSITE[this.dir]; return; }
    }

    this.progress += this.speed * dt;
    while (this.progress >= 1) {
      this.progress -= 1;
      this.tile = this.next;
      if (this.state === 'eyes'
          && this.tile.c === this.maze.houseCentre.c && this.tile.r === this.maze.houseCentre.r) {
        this.state = game.mode;
        this.dir = 'up';
        this.progress = 0;
        this.next = null;
        return;
      }
      this.dir = this.chooseDirection(game);
      this.next = this.maze.step(this.tile.c, this.tile.r, this.dir, true) || null;
      if (!this.next) { this.progress = 0; break; }
    }
  }
}

export function buildGhosts(levelIndex, maze) {
  const level = LEVELS[Math.min(levelIndex, LEVELS.length - 1)];
  return level.rivals.map((code, i) => new Ghost(code, ROLES[i], i, maze));
}
