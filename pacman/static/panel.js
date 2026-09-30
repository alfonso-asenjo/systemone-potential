// The panel and the scoreboard. Everything jev answers is shown here, including when
// its answer was not used.

import { directionArrow, directionLabel } from './jev.js';
import { ROLE_LABEL, RIVALS } from './ghosts.js';
import { flagSrc } from './maze.js';

const ORDER = ['left', 'up', 'right', 'down'];
const DANGER_TEXT = [
  'sin rivales cerca',
  'un rival rondando, sin acercarse',
  'un rival cerca y viniendo',
  'rival encima, sin salida cómoda',
];

const $ = (id) => document.getElementById(id);
const pct = (v) => `${Math.round(v * 100)} %`;

export class Panel {
  constructor() {
    this.dirs = $('dirs');
    this.dirs.innerHTML = ORDER.map((dir) => `
      <div class="dir" data-dir="${dir}">
        <span class="dir-name"><span class="dir-arrow">${directionArrow(dir)}</span>${directionLabel(dir)}</span>
        <span class="track"><span class="fill"></span></span>
        <span class="dir-pct">–</span>
      </div>`).join('');
    this.rows = {};
    for (const el of this.dirs.querySelectorAll('.dir')) this.rows[el.dataset.dir] = el;
    this.resultTimer = null;
    this.turnBackMin = 0.28;        // hasta que llegue la primera decisión del servidor
    this.brain = 'jev';             // quién decide: lo dice el servidor al saludar, o la grabación
  }

  /** jev o Laya: todos los textos que nombran a quien decide salen de aquí. */
  setBrain(id) {
    this.brain = id === 'laya' ? 'Laya' : 'jev';
    for (const el of document.querySelectorAll('[data-brain]')) el.textContent = this.brain;
    const tag = $('mode-tag');
    if (tag.classList.contains('tag-jev')) tag.textContent = `${this.brain} al mando`;
  }

  // ------------------------------------------------------------ scoreboard
  scoreboard(game) {
    $('score').textContent = game.score.toLocaleString('es-ES');
    $('level-no').textContent = `Nivel ${game.levelIndex + 1}`;
    $('level-name').textContent = game.level.name;

    const lives = $('lives');
    if (lives.childElementCount !== 3) {
      const es = flagSrc('es');
      lives.innerHTML = `<img src="${es}" alt=""><img src="${es}" alt=""><img src="${es}" alt="">`;
    }
    [...lives.children].forEach((img, i) => img.classList.toggle('spent', i >= game.lives));
  }

  /** On eating a rival, the board shows the match Spain actually played against them. */
  showResult(rival, seconds = 2) {
    $('result-flag').src = flagSrc(rival.flag);
    $('result-score').textContent = `España ${rival.score} ${rival.name}`;
    $('result-phase').textContent = `${rival.phase}, ${rival.date}`;
    $('score').hidden = true;
    $('result').hidden = false;
    clearTimeout(this.resultTimer);
    this.resultTimer = setTimeout(() => {
      $('result').hidden = true;
      $('score').hidden = false;
    }, seconds * 1000);
  }

  // -------------------------------------------------------------- decision
  decision(msg) {
    if (msg.error) {
      const meta = $('dir-meta');
      meta.className = 'meta error';
      meta.textContent = `${this.brain} no responde, España sigue con la regla de seguridad. ${msg.error}`;
      return;
    }
    const { decision: d, answers, applied } = msg;
    const meta = $('dir-meta');

    // The bars only move at a fork. In a corridor there is nothing to choose between, so
    // the last fork stays on screen and the line below says what jev is weighing now.
    if (d.at_fork) {
      const probs = (answers.direction && answers.direction.probabilities) || {};
      for (const dir of ORDER) {
        const row = this.rows[dir];
        const p = probs[dir];
        const legal = p !== undefined;
        row.classList.toggle('illegal', !legal);
        row.classList.toggle('win', legal && dir === d.direction);
        row.querySelector('.fill').style.width = legal ? `${p * 100}%` : '0%';
        row.querySelector('.dir-pct').textContent = legal ? pct(p) : '–';
      }
    }

    if (d.vetoed) {
      meta.className = 'meta held';
      meta.innerHTML = `${this.brain} quiere volver, pero detrás hay una trampa y delante más sitio. La regla de seguridad sigue hacia <b>${directionLabel(d.direction)}</b>.`;
    } else if (d.forced) {
      meta.className = 'meta held';
      meta.innerHTML = `Un rival cierra el pasillo por delante y detrás está libre. La regla de seguridad la hace volver hacia <b>${directionLabel(d.direction)}</b>.`;
    } else if (d.turned_back) {
      meta.className = 'meta held';
      meta.innerHTML = `${this.brain} la hace volver sobre sus pasos, hacia <b>${directionLabel(d.direction)}</b>.`;
    } else if (d.turn_back_on_cooldown) {
      meta.className = 'meta held';
      meta.innerHTML = `${this.brain} quiere volver otra vez, pero acaba de hacerlo. Sigue adelante.`;
    } else if (!d.at_fork) {
      meta.className = 'meta';
      meta.innerHTML = 'En el pasillo no hay nada que elegir. Las barras son del último cruce.';
    } else if (d.fallback) {
      meta.className = 'meta held';
      meta.innerHTML = `Confianza del ${pct(d.confidence)}, por debajo del umbral. Decide la regla de seguridad: <b>${directionLabel(d.direction)}</b>.`;
    } else if (applied === 'late') {
      meta.className = 'meta held';
      meta.innerHTML = `La respuesta llegó tarde al cruce, decidió la regla de seguridad. ${this.brain} elegía <b>${directionLabel(d.direction)}</b>.`;
    } else {
      meta.className = 'meta';
      meta.innerHTML = `${this.brain} elige <b>${directionLabel(d.direction)}</b> con una confianza del ${pct(d.confidence)}.`;
    }

    // The bar's mark is the listón from decide.py, sent with the decision: written here by
    // hand it would quietly lie the day the listón moves.
    const min = msg.turn_back_min ?? this.turnBackMin;
    this.turnBackMin = min;
    const back = d.turn_back || 0;
    $('back-v').textContent = pct(back);
    const backBar = $('back-bar');
    backBar.style.width = `${back * 100}%`;
    backBar.classList.toggle('over', back >= min);
    const mark = document.querySelector('.turnback .bar-mark');
    if (mark) mark.style.left = `${min * 100}%`;

    const level = Math.max(0, Math.min(3, Math.round(d.danger)));
    $('danger').className = `danger l${level}`;
    $('danger-label').textContent = `${d.danger.toFixed(1)} de 3, ${DANGER_TEXT[level]}`;

    $('power-v').textContent = pct(d.go_for_power);
    $('power-bar').style.width = `${d.go_for_power * 100}%`;
    $('hunt-v').textContent = pct(d.hunt);
    $('hunt-bar').style.width = `${d.hunt * 100}%`;

    if (msg.state) $('state-json').textContent = JSON.stringify(msg.state, null, 1);
  }

  /** Between levels the board reads like the end of a round: the rivals just knocked out. */
  showLevelCleared(level) {
    const names = level.rivals.map((c) => RIVALS[c].name).join(', ');
    $('result-flag').src = flagSrc('es');
    $('result-score').textContent = 'Fase superada';
    $('result-phase').textContent = names;
    $('score').hidden = true;
    $('result').hidden = false;
    clearTimeout(this.resultTimer);
    this.resultTimer = setTimeout(() => {
      $('result').hidden = true;
      $('score').hidden = false;
    }, 2400);
  }

  stats(stats, medianLatency) {
    $('stat-lat').textContent = stats.latency === null ? '–' : `${Math.round(medianLatency ?? stats.latency)} ms`;
    $('stat-calls').textContent = stats.calls;
    $('stat-late').textContent = stats.late;
    $('stat-cost').textContent = `$${stats.cost.toFixed(4).replace('.', ',')}`;
  }

  // ---------------------------------------------------------------- rivals
  rivals(game) {
    const list = $('rivals');
    const codes = game.ghosts.map((g) => g.code).join();
    if (this.rivalCodes !== codes) {
      this.rivalCodes = codes;
      list.innerHTML = game.ghosts.map((g) => `
        <li data-code="${g.code}">
          <img src="${flagSrc(g.code)}" alt="">
          <span><span class="rival-name">${g.name}</span><span class="rival-role">${ROLE_LABEL[g.role]}</span></span>
          <span class="rival-state"></span>
        </li>`).join('');
    }
    for (const g of game.ghosts) {
      const li = list.querySelector(`li[data-code="${g.code}"]`);
      if (!li) continue;
      let text = 'en el campo';
      if (g.state === 'house') text = 'en el banquillo';
      else if (g.state === 'frightened') text = 'huyendo';
      else if (g.state === 'eyes') text = `comida, ${g.rival.score}`;
      li.querySelector('.rival-state').textContent = text;
      li.classList.toggle('gone', g.state === 'eyes');
    }
  }

  /** A recording is labelled as one, with the day it was played. */
  replayMode(meta) {
    const tag = $('mode-tag');
    tag.textContent = 'partida grabada';
    tag.className = 'tag tag-replay';
    const hint = document.querySelector('.hint');
    if (hint) {
      const when = meta && meta.played
        ? new Date(meta.played * 1000).toLocaleDateString('es-ES',
            { day: 'numeric', month: 'long', year: 'numeric' })
        : null;
      hint.textContent = when
        ? `Cada decisión es la que ${this.brain} tomó de verdad el ${when}. Espacio pausa, R vuelve a empezar.`
        : `Cada decisión es la que ${this.brain} tomó de verdad. Espacio pausa, R vuelve a empezar.`;
      hint.style.display = '';
    }
  }

  mode(source) {
    const tag = $('mode-tag');
    const manual = source === 'teclado';
    tag.textContent = manual ? 'control manual' : `${this.brain} al mando`;
    tag.className = `tag ${manual ? 'tag-manual' : 'tag-jev'}`;
  }

  curtain(title, text, onRestart) {
    $('curtain-title').textContent = title;
    $('curtain-text').textContent = text;
    $('curtain').hidden = false;
    $('curtain-btn').onclick = () => { $('curtain').hidden = true; onRestart(); };
  }

  hideCurtain() { $('curtain').hidden = true; }
}
