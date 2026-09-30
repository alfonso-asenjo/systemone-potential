// Drawing. The pitch at night: chalk lines on mown grass, the World Cup trophy as the
// power pellet, rivals wearing their flag. The one loud thing on screen is jev's arrows.

import { DIRS, TILE, flagSrc } from './maze.js';

const C = {
  grass: '#1f6f3d',
  grass2: '#1a5f34',
  dugout: '#16273a',
  chalk: '#f2efe6',
  red: '#c8102e',
  gold: '#f5b700',
  night: '#0c1424',
  danger: ['#3aa655', '#f5b700', '#f07f2e', '#d1343a'],
};

export class Renderer {
  constructor(canvas, maze) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.maze = maze;
    this.flags = {};
    this.popups = [];
    this.arrows = null;
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = maze.w * TILE * dpr;
    canvas.height = maze.h * TILE * dpr;
    canvas.style.width = `${maze.w * TILE}px`;
    canvas.style.height = `${maze.h * TILE}px`;
    this.ctx.scale(dpr, dpr);

    // Only tiles a ghost can reach are pitch; the rest is the stand.
    const reach = maze.distancesFrom(maze.houseCentre.c, maze.houseCentre.r, true);
    this.inPlay = new Set();
    for (let r = 0; r < maze.h; r++) {
      for (let c = 0; c < maze.w; c++) if (reach.get(c, r) !== null) this.inPlay.add(`${c},${r}`);
    }
    this.pitch = document.createElement('canvas');
    this.pitch.width = canvas.width;
    this.pitch.height = canvas.height;
    const pctx = this.pitch.getContext('2d');
    pctx.scale(dpr, dpr);
    this.drawPitch(pctx);
  }

  async loadFlags(codes) {
    await Promise.all(codes.map((code) => new Promise((resolve) => {
      const img = new Image();
      img.onload = () => { this.flags[code] = img; resolve(); };
      img.onerror = () => resolve();
      img.src = flagSrc(code);
    })));
  }

  isPlay(c, r) { return this.inPlay.has(`${c},${r}`); }

  // ------------------------------------------------------------- static pitch
  drawPitch(ctx) {
    const { maze } = this;
    const W = maze.w * TILE;
    const H = maze.h * TILE;

    ctx.fillStyle = C.night;
    ctx.fillRect(0, 0, W, H);

    // mown stripes, two tiles wide, only under the playable maze
    for (let r = 0; r < maze.h; r++) {
      for (let c = 0; c < maze.w; c++) {
        if (!this.isPlay(c, r)) continue;
        ctx.fillStyle = Math.floor(c / 2) % 2 === 0 ? C.grass : C.grass2;
        ctx.fillRect(c * TILE - 1, r * TILE - 1, TILE + 2, TILE + 2);
      }
    }

    // the rivals wait in the dugout, so it should not read as more pitch
    for (const t of [...maze.house, maze.door]) {
      if (!t) continue;
      ctx.fillStyle = C.dugout;
      ctx.fillRect(t.c * TILE - 1, t.r * TILE - 1, TILE + 2, TILE + 2);
    }

    // chalk lines wherever a wall meets the pitch
    ctx.strokeStyle = C.chalk;
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    for (let r = 0; r < maze.h; r++) {
      for (let c = 0; c < maze.w; c++) {
        if (maze.at(c, r) !== '#') continue;
        const x = c * TILE;
        const y = r * TILE;
        const sides = [
          [0, -1, 0, 0, 1, 0],   // up:    neighbour (0,-1), line across the top
          [0, 1, 0, 1, 1, 1],    // down:  neighbour (0,+1), line across the bottom
          [1, 0, 1, 0, 1, 1],    // right
          [-1, 0, 0, 0, 0, 1],   // left
        ];
        for (const [dc, dr, ax, ay, bx, by] of sides) {
          if (!this.isPlay(c + dc, r + dr)) continue;
          ctx.moveTo(x + ax * TILE, y + ay * TILE);
          ctx.lineTo(x + bx * TILE, y + by * TILE);
        }
      }
    }
    ctx.stroke();

    if (maze.door) {                      // the dugout mouth, drawn as an opening
      const x = maze.door.c * TILE;
      const y = (maze.door.r + 1) * TILE;
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 2;
      ctx.globalAlpha = 0.6;
      ctx.beginPath();
      ctx.moveTo(x + 2, y - TILE);
      ctx.lineTo(x + TILE - 2, y - TILE);
      ctx.stroke();
      ctx.restore();
    }
    ctx.globalAlpha = 1;

    // the stand darkens towards the edges
    const vign = ctx.createRadialGradient(W / 2, H / 2, H * 0.25, W / 2, H / 2, H * 0.72);
    vign.addColorStop(0, 'rgba(0,0,0,0)');
    vign.addColorStop(1, 'rgba(4,10,20,0.55)');
    ctx.fillStyle = vign;
    ctx.fillRect(0, 0, W, H);
  }

  // ------------------------------------------------------------------- frame
  draw(game, decision) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.maze.w * TILE, this.maze.h * TILE);
    ctx.drawImage(this.pitch, 0, 0, this.maze.w * TILE, this.maze.h * TILE);

    this.drawPellets(game);
    if (this.arrows) this.drawArrows(game);
    for (const g of game.ghosts) this.drawGhost(ctx, g, game);
    this.drawSpain(ctx, game, decision);
    this.drawPopups(ctx);
  }

  drawPellets(game) {
    const ctx = this.ctx;
    ctx.fillStyle = C.chalk;
    for (const k of game.maze.pellets) {
      if (game.maze.powerPellets.has(k)) continue;
      const [c, r] = k.split(',').map(Number);
      ctx.beginPath();
      ctx.arc((c + 0.5) * TILE, (r + 0.5) * TILE, 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
    const pulse = this.reducedMotion ? 1 : 0.86 + 0.14 * Math.sin(game.tick * 0.06);
    for (const k of game.maze.powerPellets) {
      const [c, r] = k.split(',').map(Number);
      this.drawTrophy(ctx, (c + 0.5) * TILE, (r + 0.5) * TILE, pulse);
    }
  }

  /** The power pellet is the trophy: taking it is what let Spain turn on its hunters. */
  drawTrophy(ctx, x, y, scale) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.shadowColor = 'rgba(245,183,0,0.75)';
    ctx.shadowBlur = 10;
    ctx.fillStyle = C.gold;
    ctx.beginPath();                       // bowl
    ctx.moveTo(-5, -6.5);
    ctx.lineTo(5, -6.5);
    ctx.quadraticCurveTo(4.6, 0.5, 1.7, 1.5);
    ctx.lineTo(-1.7, 1.5);
    ctx.quadraticCurveTo(-4.6, 0.5, -5, -6.5);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(-1.6, 1.2, 3.2, 3);       // stem
    ctx.beginPath();                       // base
    ctx.moveTo(-4.6, 6.6);
    ctx.lineTo(4.6, 6.6);
    ctx.lineTo(3.4, 4.1);
    ctx.lineTo(-3.4, 4.1);
    ctx.closePath();
    ctx.fill();
    ctx.lineWidth = 1.4;                   // handles
    ctx.strokeStyle = C.gold;
    ctx.beginPath();
    ctx.arc(-5.6, -3.6, 2.4, Math.PI * 0.55, Math.PI * 1.55);
    ctx.moveTo(5.6, -6);
    ctx.arc(5.6, -3.6, 2.4, Math.PI * 1.45, Math.PI * 0.45);
    ctx.stroke();
    ctx.restore();
  }

  // -------------------------------------------------------- jev's decision
  setArrows(arrows) { this.arrows = arrows; }
  clearArrows() { this.arrows = null; }

  drawArrows(game) {
    const a = this.arrows;
    const age = (game.tick - a.tick) / 60;
    const LIFE = 1.5;
    if (age > LIFE) { this.arrows = null; return; }
    const fade = Math.min(1, age / 0.1) * Math.min(1, (LIFE - age) / 0.45);
    const ctx = this.ctx;
    const x = (a.tile.c + 0.5) * TILE;
    const y = (a.tile.r + 0.5) * TILE;

    for (const [dir, p] of Object.entries(a.probabilities)) {
      const d = DIRS[dir];
      if (!d) continue;
      const chosen = dir === a.direction;
      const len = TILE * 0.95 * (0.5 + 0.5 * p);
      ctx.save();
      ctx.globalAlpha = fade * (0.3 + 0.7 * p);
      ctx.strokeStyle = chosen ? C.gold : C.chalk;
      ctx.fillStyle = chosen ? C.gold : C.chalk;
      ctx.lineWidth = 2.5 + 6.5 * p;
      ctx.lineCap = 'round';
      if (chosen && a.held) ctx.setLineDash([4, 4]);
      const x2 = x + d.dc * len;
      const y2 = y + d.dr * len;
      ctx.beginPath();
      ctx.moveTo(x + d.dc * 5, y + d.dr * 5);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();                       // head
      const h = 5 + 4 * p;
      ctx.moveTo(x2 + d.dc * h, y2 + d.dr * h);
      ctx.lineTo(x2 - d.dc * h + d.dr * h, y2 - d.dr * h + d.dc * h);
      ctx.lineTo(x2 - d.dc * h - d.dr * h, y2 - d.dr * h - d.dc * h);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }
  }

  // ------------------------------------------------------------------ Spain
  drawSpain(ctx, game, decision) {
    const p = game.position(game.spain);
    const r = 12;
    const angle = DIRS[game.spain.dir].angle;
    const mouth = 0.3 * Math.PI * (this.reducedMotion ? 0.45 : game.spain.mouth);

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.arc(p.x, p.y, r, angle + mouth, angle - mouth + Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    ctx.fillStyle = C.red;                       // the flag stays level whichever way she faces
    ctx.fillRect(p.x - r, p.y - r, r * 2, r * 2);
    ctx.fillStyle = C.gold;
    ctx.fillRect(p.x - r, p.y - r * 0.5, r * 2, r);
    ctx.restore();

    if (decision && typeof decision.danger === 'number') {
      const level = Math.max(0, Math.min(3, Math.round(decision.danger)));
      ctx.save();
      ctx.strokeStyle = C.danger[level];
      ctx.globalAlpha = 0.45 + 0.18 * level;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    const tag = decision && decision.tag;
    if (tag) {
      ctx.save();
      ctx.font = '600 11px "Barlow Condensed", sans-serif';
      ctx.fillStyle = C.gold;
      ctx.textAlign = 'center';
      ctx.fillText(tag, p.x, p.y - r - 7);
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- rivals
  drawGhost(ctx, g, game) {
    if (g.state === 'house' && game.elapsed < g.releaseAt) {
      // waiting on the bench: a small flag inside the house
      const p = g.position(TILE);
      this.drawFlagBadge(ctx, p.x - 8 + g.index * 5, p.y - 5, 10);
      return;
    }
    const p = g.position(TILE);
    const r = 12;

    if (g.state === 'eyes') {
      this.drawFlagBadge(ctx, p.x - 5, p.y - 16, 10, g.code);
      this.drawEyes(ctx, p.x, p.y, r, g.dir);
      return;
    }

    const frightened = g.state === 'frightened';
    const wobble = frightened && !this.reducedMotion ? Math.sin(game.tick * 0.35) * 1.2 : 0;

    ctx.save();
    ctx.beginPath();
    ctx.arc(p.x, p.y - 1, r, Math.PI, 0);
    ctx.lineTo(p.x + r, p.y + r * 0.7);
    for (let i = 0; i < 3; i++) {
      const x1 = p.x + r - ((2 * r) / 3) * (i + 0.5);
      const x2 = p.x + r - ((2 * r) / 3) * (i + 1);
      ctx.quadraticCurveTo(x1, p.y + r * 1.15 + wobble, x2, p.y + r * 0.7);
    }
    ctx.lineTo(p.x - r, p.y - 1);
    ctx.closePath();
    ctx.save();
    ctx.clip();
    const img = this.flags[g.code];
    if (img) {
      if (frightened) ctx.filter = 'grayscale(1) brightness(0.75)';
      drawCover(ctx, img, p.x - r, p.y - r - 1, r * 2, r * 2.2);
      ctx.filter = 'none';
    } else {
      ctx.fillStyle = frightened ? '#2850dc' : '#8892a4';
      ctx.fillRect(p.x - r, p.y - r, r * 2, r * 2.2);
    }
    if (frightened) {
      ctx.fillStyle = 'rgba(40,80,220,0.55)';
      ctx.fillRect(p.x - r, p.y - r - 1, r * 2, r * 2.2);
    }
    ctx.restore();
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(12,20,36,0.85)';
    ctx.stroke();
    ctx.restore();

    this.drawEyes(ctx, p.x, p.y, r, g.dir, frightened);

    ctx.save();
    ctx.font = '600 11px "Barlow Condensed", sans-serif';
    ctx.fillStyle = C.chalk;
    ctx.globalAlpha = 0.72;
    ctx.textAlign = 'center';
    ctx.fillText(g.name, p.x, p.y + r + 11);
    ctx.restore();
  }

  drawEyes(ctx, x, y, r, dir, frightened = false) {
    const d = DIRS[dir] || DIRS.left;
    ctx.save();
    for (const side of [-1, 1]) {
      const ex = x + side * r * 0.36;
      const ey = y - r * 0.18;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.ellipse(ex, ey, r * 0.3, r * 0.38, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = frightened ? '#20306a' : '#12203c';
      ctx.beginPath();
      ctx.arc(ex + d.dc * r * 0.13, ey + d.dr * r * 0.15, r * 0.16, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  drawFlagBadge(ctx, x, y, size, code) {
    const img = code && this.flags[code];
    if (!img) return;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, size, size * 0.75);
    ctx.clip();
    ctx.drawImage(img, x, y, size, size * 0.75);
    ctx.restore();
  }

  // ---------------------------------------------------------------- popups
  addPopup(text, x, y, colour = C.gold) {
    this.popups.push({ text, x, y, colour, life: 1.1 });
  }

  drawPopups(ctx) {
    this.popups = this.popups.filter((p) => p.life > 0);
    for (const p of this.popups) {
      p.life -= 1 / 60;
      p.y -= 0.35;
      ctx.save();
      ctx.globalAlpha = Math.max(0, Math.min(1, p.life * 1.6));
      ctx.font = '700 16px "Barlow Condensed", sans-serif';
      ctx.fillStyle = p.colour;
      ctx.textAlign = 'center';
      ctx.fillText(p.text, p.x, p.y);
      ctx.restore();
    }
  }
}

function drawCover(ctx, img, x, y, w, h) {
  const ar = (img.naturalWidth || 4) / (img.naturalHeight || 3);
  let dw = w;
  let dh = w / ar;
  if (dh < h) { dh = h; dw = h * ar; }
  ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}
