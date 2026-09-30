// The bridge to jev: when to ask, what state to send, and what to do with the answer.
// Everything the code can work out (distances, counts) is worked out here, so jev is
// only ever asked for a judgement.

import { DIRS, OPPOSITE, key } from './maze.js';
import { ROLE_LABEL } from './ghosts.js';

// Every question is asked about the tile Spain is entering, never the one she is standing
// on: that buys the answer a whole tile of travel to arrive, about 400 ms at her speed.
// Asking about the current tile instead made two thirds of the answers arrive too late.

// Even a sound judgement to turn round becomes pacing on the spot if it can fire every
// tile, so a turn has to be at least this many tiles after the last one.
const TURN_BACK_COOLDOWN_TILES = 4;

// Escape room is counted up to this many tiles; reaching it means open ground.
const ESCAPE_ROOM_OPEN = 12;
// Spain must reach a tile at least this long before a rival can. They collide when their
// centres are 0.55 tiles apart, so passing head on needs about 0.55/2.2 + 0.55/1.6 s; 0.3
// let her die in junctions a rival entered at the same moment.
const ESCAPE_SLACK_S = 0.6;

export class JevLink {
  constructor(game, maze, { onDecision, onStats, onHello, replay = null } = {}) {
    this.game = game;
    this.maze = maze;
    this.onHello = onHello || (() => {});
    this.onDecision = onDecision || (() => {});
    this.onStats = onStats || (() => {});
    this.replay = replay;               // Map of recvTick to a recorded message
    this.ws = null;
    this.connected = false;
    this.inFlight = null;
    this.lastNextKey = null;
    this.prevGhostDist = {};
    this.lastDecision = null;
    this.lastTurnBackTile = -999;   // in tiles entered, not ticks
    this.tilesEntered = 0;
    this.stats = { calls: 0, late: 0, errors: 0, cost: 0, latency: null, latencies: [] };
  }

  connect() {
    if (this.replay) { this.connected = true; return; }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws.onopen = () => {
      this.connected = true;
      this.ws.send(JSON.stringify({ type: 'hello', seed: this.game.seed }));
    };
    this.ws.onclose = () => { this.connected = false; setTimeout(() => this.connect(), 1500); };
    this.ws.onmessage = (ev) => this.receive(JSON.parse(ev.data));
  }

  // ------------------------------------------------------------ when to ask
  update() {
    const game = this.game;
    if (this.replay) {
      const msg = this.replay.get(game.tick);   // checked on every tick, pauses included
      if (msg) this.receive(msg);
      return;
    }
    if (game.status !== 'playing') return;
    if (!this.connected || this.inFlight) return;

    const next = game.spain.next;
    if (!next) return;
    const nextKey = key(next.c, next.r);
    if (nextKey === this.lastNextKey) return;
    this.lastNextKey = nextKey;

    // At a junction the way back is left out, so the options are real choices. In a
    // corridor it stays in, which is how Spain is able to turn round and run.
    this.tilesEntered++;
    // The way back is never one of the options: it is its own judgement, asked every tile.
    const junction = this.maze.isJunction(next.c, next.r);
    this.ask(next, OPPOSITE[game.spain.dir], junction ? 'cruce' : 'pasillo');
  }

  nearestLiveGhostDistance() {
    const s = this.game.spain.tile;
    const dist = this.maze.distancesFrom(s.c, s.r);
    let best = null;
    for (const g of this.game.ghosts) {
      if (!g.active) continue;
      const d = dist.get(g.tile.c, g.tile.r);
      if (d !== null && (best === null || d < best)) best = d;
    }
    return best;
  }

  ask(tile, behind, reason) {
    const all = this.maze.exits(tile.c, tile.r).map((e) => e.dir);
    const forward = all.filter((dir) => dir !== behind);
    if (forward.length === 0) return;                 // a dead end: only the way back

    const state = this.buildState(tile, forward, behind);
    this.inFlight = { tile: { ...tile }, tileKey: key(tile.c, tile.r), askTick: this.game.tick, reason };
    this.ws.send(JSON.stringify({
      type: 'ask',
      tick: this.game.tick,
      reason,
      exits: forward,
      state,
    }));
    this.lastState = state;
  }

  /**
   * How far Spain can run leaving `tile` by `dir` without any chasing rival cutting her off,
   * through as many junctions as it takes, capped at ESCAPE_ROOM_OPEN. A small number is a
   * trap: every way on from there is reached by a rival first. Looking one junction ahead
   * was not enough; with four rivals closing in she escaped a corridor only to find every
   * exit of the next junction already cut.
   */
  escapeRoom(tile, dir, ghostTimes = this.ghostArrival()) {
    const maze = this.maze;
    const first = maze.step(tile.c, tile.r, dir);
    if (!first) return null;
    const idx = (c, r) => r * maze.w + c;
    const seen = new Uint8Array(maze.w * maze.h);
    seen[idx(tile.c, tile.r)] = 1;
    // She is about a tile short of `tile` when the question is asked, hence the +1.
    const safe = (c, r, steps) => (steps + 1) / this.game.spainSpeed + ESCAPE_SLACK_S < ghostTimes[idx(c, r)];
    // The tile she is entering comes first: a rival arriving there with her cuts every exit.
    if (!safe(tile.c, tile.r, 0) || !safe(first.c, first.r, 1)) return 0;
    seen[idx(first.c, first.r)] = 1;
    const queue = [{ ...first, d: 1 }];
    let best = 1;
    for (let head = 0; head < queue.length; head++) {
      const cur = queue[head];
      best = Math.max(best, cur.d);
      if (best >= ESCAPE_ROOM_OPEN) return ESCAPE_ROOM_OPEN;
      for (const nxt of maze.exits(cur.c, cur.r)) {
        const k = idx(nxt.c, nxt.r);
        if (seen[k] || !safe(nxt.c, nxt.r, cur.d + 1)) continue;
        seen[k] = 1;
        queue.push({ c: nxt.c, r: nxt.r, d: cur.d + 1 });
      }
    }
    return best;
  }

  /** Seconds until the first chasing rival can stand on each tile. Rivals cannot reverse. */
  ghostArrival() {
    const maze = this.maze;
    const idx = (c, r) => r * maze.w + c;
    const times = new Float64Array(maze.w * maze.h).fill(Infinity);
    for (const g of this.game.ghosts) {
      if (!g.active) continue;
      const dist = new Int16Array(maze.w * maze.h).fill(-1);
      dist[idx(g.tile.c, g.tile.r)] = 0;
      const queue = [g.tile];
      for (let head = 0; head < queue.length; head++) {
        const cur = queue[head];
        const d = dist[idx(cur.c, cur.r)];
        for (const nxt of maze.exits(cur.c, cur.r, true)) {
          if (head === 0 && nxt.dir === OPPOSITE[g.dir]) continue;
          if (dist[idx(nxt.c, nxt.r)] !== -1) continue;
          dist[idx(nxt.c, nxt.r)] = d + 1;
          queue.push(nxt);
        }
      }
      for (let k = 0; k < dist.length; k++) {
        if (dist[k] >= 0) times[k] = Math.min(times[k], dist[k] / g.speed);
      }
    }
    return times;
  }

  // --------------------------------------------------------------- the state
  buildState(tile, exits, behind) {
    const game = this.game;
    const maze = this.maze;
    const fromSpain = maze.distancesFrom(game.spain.tile.c, game.spain.tile.r);

    const ghosts = game.ghosts.map((g) => {
      const d = fromSpain.get(g.tile.c, g.tile.r);
      const prev = this.prevGhostDist[g.code];
      this.prevGhostDist[g.code] = d;
      return {
        name: g.name,
        role: g.role,
        dist: d === null ? 99 : d,
        approaching: prev !== undefined && d !== null && d < prev,
        state: g.state === 'house' ? 'in_house' : g.state,
      };
    });

    const byExit = {};
    const ghostTimes = this.ghostArrival();
    for (const dir of behind ? [...exits, behind] : exits) {
      const step = maze.step(tile.c, tile.r, dir);
      if (!step) continue;
      const dist = maze.distancesFrom(step.c, step.r);
      let nearestGhost = 99;
      let frightened = null;
      for (const g of game.ghosts) {
        const d = dist.get(g.tile.c, g.tile.r);
        if (d === null) continue;
        if (g.state === 'frightened') frightened = frightened === null ? d : Math.min(frightened, d);
        else if (g.active && d < nearestGhost) nearestGhost = d;
      }
      let pellets = 0;
      for (const k of maze.pellets) {
        const [c, r] = k.split(',').map(Number);
        const d = dist.get(c, r);
        if (d !== null && d <= 8) pellets++;
      }
      let power = null;
      for (const k of maze.powerPellets) {
        const [c, r] = k.split(',').map(Number);
        const d = dist.get(c, r);
        if (d !== null && (power === null || d < power)) power = d;
      }
      // How far the nearest pellet still is that way. Without this, once a stretch is
      // cleared every exit looks the same and jev is choosing where to eat blind.
      let nearestPellet = null;
      for (const k of maze.pellets) {
        const [c, r] = k.split(',').map(Number);
        const d = dist.get(c, r);
        if (d !== null && (nearestPellet === null || d < nearestPellet)) nearestPellet = d;
      }
      byExit[dir] = {
        nearest_ghost: nearestGhost,
        escape_room: this.escapeRoom(tile, dir, ghostTimes),
        nearest_pellet_dist: nearestPellet,
        pellets_within_8: pellets,
        power_pellet_dist: power,
        frightened_ghost_dist: frightened,
      };
    }

    return {
      level: game.levelIndex + 1,
      level_name: game.level.name,
      score: game.score,
      lives: game.lives,
      pellets_left: game.pelletsLeft,
      power_mode: {
        active: game.powerLeft > 0,
        seconds_left: Math.round(game.powerLeft * 10) / 10,
      },
      spain: {
        tile: [tile.c, tile.r],
        heading: game.spain.dir,
        exits,
        behind: behind || null,
        tiles_since_turn_back: this.tilesEntered - this.lastTurnBackTile,
      },
      ghosts,
      by_exit: byExit,
      previous_decision: this.lastDecision
        ? { direction: this.lastDecision.direction, danger: this.lastDecision.danger }
        : {},
    };
  }

  // ------------------------------------------------------------ the answer
  receive(msg) {
    if (msg.type === 'hello') { this.onHello(msg); return; }
    if (msg.type === 'error') {
      this.stats.errors++;
      this.inFlight = null;
      this.onDecision({ error: msg.message });
      this.onStats(this.stats);
      return;
    }
    if (msg.type !== 'decision') return;

    const game = this.game;
    const ask = this.inFlight || askFromState(msg.state);
    this.inFlight = null;

    this.stats.calls++;
    this.stats.latency = msg.latency_ms;
    this.stats.latencies.push(msg.latency_ms);
    this.stats.cost = msg.total_cost_usd ?? this.stats.cost;

    const d = msg.decision;
    if (d.turned_back) {
      // An escape from a trap is exempt: waiting out the cooldown is what got her caught.
      if (!d.escape && this.tilesEntered - this.lastTurnBackTile < TURN_BACK_COOLDOWN_TILES) {
        d.turned_back = false;
        d.turn_back_on_cooldown = true;
        // `forward` is what she would have done without the turn. Older recordings lack it.
        d.direction = d.forward || (msg.exits && msg.exits[0]) || d.direction;
      } else {
        this.lastTurnBackTile = this.tilesEntered;
      }
    }
    let applied = 'pending';
    const next = game.spain.next;
    if (next && key(next.c, next.r) === ask.tileKey) {
      game.pending = { tileKey: ask.tileKey, direction: d.direction };
    } else if (key(game.spain.tile.c, game.spain.tile.r) === ask.tileKey) {
      applied = game.redirect(d.direction) ? 'now' : 'late';
    } else {
      applied = 'late';
    }
    if (applied === 'late') this.stats.late++;

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'applied', seq: msg.seq, recv_tick: game.tick, applied, score: game.score,
      }));
    }

    this.lastDecision = d;
    this.onDecision({
      decision: d,
      answers: msg.answers,
      latency: msg.latency_ms,
      state: msg.state || this.lastState,
      tile: ask.tile,
      applied,
      reason: msg.reason || (this.inFlight && this.inFlight.reason),
    });
    this.onStats(this.stats);
  }

  get medianLatency() {
    if (!this.stats.latencies.length) return null;
    const s = [...this.stats.latencies].sort((a, b) => a - b);
    return s[Math.floor(s.length / 2)];
  }
}

/** In replay there is no request in flight, so the asked tile comes from the record. */
function askFromState(state) {
  const tile = state && state.spain && state.spain.tile;
  if (!tile) return { tileKey: null, tile: null };
  return { tileKey: key(tile[0], tile[1]), tile: { c: tile[0], r: tile[1] } };
}

export function directionLabel(dir) {
  return { left: 'izquierda', right: 'derecha', up: 'arriba', down: 'abajo' }[dir] || dir;
}

export function directionArrow(dir) {
  return { left: '←', right: '→', up: '↑', down: '↓' }[dir] || '';
}

export { ROLE_LABEL, DIRS };
