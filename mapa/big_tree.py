"""Laya aprende a bajar por el árbol de España: comunidad -> provincia -> (mitad) -> grupo -> municipio.

Idea original: "un árbol de decisión a la inversa". Ninguna pregunta pasa de 20 opciones,
que es donde Laya funciona (con 77 opciones se hunde: Banking77 0,43 frente a 0,87 de jev).

Etiquetas: gpt-6-luna eligió para cada frase hasta 15 municipios con nota 1-3 (big_label.py;
a ciegas acertó el 97 % frente al 53 % del buscador de palabras). La nota de cada municipio se
suma hacia arriba, y la respuesta correcta en cada nodo es cómo se reparte esa suma entre sus
hijos. Se entrenan la raíz y, en cada nivel, las preguntas de los 3 nodos con más peso: lo mismo
que hace la búsqueda en haz al contestar.

    .venv-laya/Scripts/python mapa/big_tree.py stats           # cuántas preguntas y de qué tamaño
    .venv-laya/Scripts/python mapa/big_tree.py train [--epochs 2] [--limit N]
    .venv-laya/Scripts/python mapa/big_tree.py eval [--model models/laya-mapa]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIG = HERE / "data" / "big"
BASE = ROOT / "models" / "laya" / "multilingual"
OUT = ROOT / "models" / "laya-mapa"
BEAM = 3
TOP_LAYERS = 8
OPTION_WORDS = 30          # Laya lee ~48 tokens por opción; 30 palabras caben

LEVEL_Q = {
    "es": "¿En qué comunidad autónoma está el sitio que busca esta persona?",
    "c": "¿En qué provincia está el sitio que busca esta persona?",
    "p": "¿En qué zona de la provincia está el sitio que busca esta persona?",
    "s": "¿En qué zona está el sitio que busca esta persona?",
    "g": "¿Qué municipio encaja mejor con lo que busca esta persona?",
}


def short(text: str, words: int = OPTION_WORDS) -> str:
    w = text.split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


class Tree:
    def __init__(self):
        self.root = json.loads((BIG / "arbol.json").read_text(encoding="utf-8"))
        self.desc = json.loads((BIG / "nodos.json").read_text(encoding="utf-8"))
        self.lug = {l["ine"]: l for l in json.loads((BIG / "lugares.json").read_text(encoding="utf-8"))}
        self.node, self.kids, self.parent = {}, {}, {}
        self._index(self.root)

    def _index(self, n):
        self.node[n["id"]] = n
        kids = []
        for k in n.get("children", []):
            kid = k if isinstance(k, str) else k["id"]
            kids.append(kid)
            self.parent[kid] = n["id"]
            if isinstance(k, dict):
                self._index(k)
        self.kids[n["id"]] = kids

    def option(self, kid: str) -> str:
        if kid in self.lug:
            l = self.lug[kid]
            where = {"island": "isla", "africa": "norte de África"}.get(l["reach"], f"{l['hours']} h de Madrid")
            coast = "costa" if l["costero"] else "interior"
            return short(f"{l['name']}: {coast}, {l['pop']} hab., {where}. {l['rasgos'] or 'pueblo sin rasgos destacados'}")
        return short(f"{self.node[kid]['name']}: {self.desc.get(kid, '')}")

    def question(self, nid: str) -> dict:
        level = "es" if nid == "es" else nid.split(":")[0]
        return {"type": "choice", "instructions": LEVEL_Q[level],
                "criteria": {k: self.option(k) for k in self.kids[nid]}}

    def masses(self, picks: dict[str, float]) -> dict[str, float]:
        m: dict[str, float] = {}
        for ine, w in picks.items():
            x = ine
            while x in self.parent:
                m[x] = m.get(x, 0) + w
                x = self.parent[x]
            m["es"] = m.get("es", 0) + w
        return m

    def train_questions(self, picks: dict[str, float]) -> list[tuple[str, list[float]]]:
        """(nodo, reparto objetivo entre sus hijos) para la raíz y los BEAM nodos con más peso por nivel."""
        m = self.masses(picks)
        out, frontier = [], ["es"]
        while frontier:
            nxt = []
            for nid in frontier:
                kids = self.kids[nid]
                if not kids or kids[0] in self.lug and len(kids) == 1:
                    continue
                if len(kids) > 1:
                    tot = m[nid]
                    out.append((nid, [m.get(k, 0) / tot for k in kids]))
                if kids[0] not in self.lug:
                    nxt += [k for k in kids if m.get(k, 0) > 0]
            frontier = sorted(nxt, key=lambda k: -m[k])[:BEAM]
        return out


def load_labels(exam: bool) -> list[dict]:
    rows = [json.loads(l) for l in (BIG / "etiquetas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r.get("examen", False) == exam and r["elegidos"]]


def picks_of(r: dict) -> dict[str, float]:
    return {ine: float(n) for ine, n in r["elegidos"]}


def state(frase: str) -> str:
    return f"Busco: {frase}"


# ---------------------------------------------------------------- búsqueda en haz
def rank(agent, tree: Tree, frase: str, beam: int = BEAM) -> dict[str, float]:
    """Probabilidad de cada municipio alcanzado: producto de las probabilidades de su camino.
    En cada nivel se preguntan a la vez (una pasada por la GPU) los hijos de los nodos del haz."""
    scores = {"es": 1.0}
    frontier = ["es"]
    out: dict[str, float] = {}
    while frontier:
        qs = {nid: tree.question(nid) for nid in frontier if len(tree.kids[nid]) > 1}
        ans = agent.predict(state(frase), qs, head_max_len=1024)["answers"] if qs else {}
        nxt = []
        for nid in frontier:
            kids = tree.kids[nid]
            probs = ans[nid]["probabilities"] if nid in ans else {kids[0]: 1.0}
            for k in kids:
                p = scores[nid] * probs.get(k, 0.0)
                if k in tree.lug:
                    out[k] = p
                else:
                    scores[k] = p
                    nxt.append(k)
        frontier = sorted(nxt, key=lambda k: -scores[k])[:beam]
    return out


def evaluate(agent, tree: Tree, rows: list[dict], k: int = 10) -> dict:
    from review import BM25, doc_text, tokens
    lugares = list(tree.lug.values())
    bm = BM25([tokens(doc_text(l)) for l in lugares])
    rec_s, rec_b, prec_s, ms = [], [], [], []
    for r in rows:
        teacher = set(picks_of(r))
        t0 = time.perf_counter()
        sc = rank(agent, tree, r["frase"])
        ms.append((time.perf_counter() - t0) * 1000)
        top = [x for x, _ in sorted(sc.items(), key=lambda kv: -kv[1])[:k]]
        btop = [lugares[i]["ine"] for i in bm.top(tokens(r["frase"]), k)]
        rec_s.append(len(teacher & set(top)) / len(teacher))
        rec_b.append(len(teacher & set(btop)) / len(teacher))
        prec_s.append(len(teacher & set(top)) / k)
    return {"frases": len(rows), f"alumno_recall@{k}": round(float(np.mean(rec_s)), 3),
            f"buscador_recall@{k}": round(float(np.mean(rec_b)), 3),
            f"alumno_precision@{k}": round(float(np.mean(prec_s)), 3), "ms_mediana": round(float(np.median(ms)))}


# ---------------------------------------------------------------- entrenamiento
def encode(agent, tree: Tree, frase: str, picks: dict) -> list[dict]:
    from laya.agent import Agent
    qs = tree.train_questions(picks)
    ids = [nid for nid, _ in qs]
    internal = {nid: Agent._to_internal(tree.question(nid)) for nid in ids}
    items = agent._encode_state(state(frase), ids, internal, head_max_len=1024)
    for (nid, target), it in zip(qs, items):
        it["target"] = target
        it["qid"] = nid
    return items


def train(args):
    import torch
    import laya
    from laya.common import collate_items
    tree = Tree()
    rows = load_labels(exam=False)
    if args.limit:
        rows = rows[:args.limit]
    exam = load_labels(exam=True)
    agent = laya.load(str(BASE), device="cuda")
    report = {"train_frases": len(rows), "before": evaluate(agent, tree, exam)}
    print("sin entrenar:", json.dumps(report["before"]), flush=True)
    torch.cuda.empty_cache()

    model = agent.model
    layers = model.encoder.layers
    for p in model.parameters():
        p.requires_grad = False
    model.encoder.embeddings.half()
    for layer in layers[:len(layers) - TOP_LAYERS]:
        layer.half()
    trainable = [*layers[-TOP_LAYERS:], model.encoder.final_norm, model.head, model.type_emb, model.scorer]
    for m in trainable:
        for p in m.parameters():
            p.requires_grad = True
    enc = [p for m in trainable[:TOP_LAYERS + 1] for p in m.parameters()]
    head = [p for m in trainable[TOP_LAYERS + 1:] for p in m.parameters()]
    opt = torch.optim.AdamW([{"params": enc, "lr": 3e-5}, {"params": head, "lr": 1e-4}], weight_decay=0.01)

    items = [it for r in rows for it in encode(agent, tree, r["frase"], picks_of(r))]
    lens = sorted(len(it["ids"]) for it in items)
    print(f"{len(items)} preguntas de entrenamiento, tokens p50 {lens[len(lens) // 2]} p90 {lens[int(len(lens) * .9)]}", flush=True)
    steps = args.epochs * math.ceil(len(items) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler("cuda")
    agent.temperature, agent.temperature_by_options = [1.0, 1.0, 1.0], {}
    t0, step = time.time(), 0
    for epoch in range(args.epochs):
        model.train()
        random.Random(epoch).shuffle(items)
        for i in range(0, len(items), args.batch):
            b = collate_items([items[i:i + args.batch]], agent.tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, _ = model(b["input_ids"].cuda(), b["attention_mask"].cuda(), b["marker_pos"].cuda(),
                                  b["marker_mask"].cuda(), b["qtype"].cuda())
            mask = b["marker_mask"].cuda()
            logp = torch.log_softmax(logits.float(), -1).masked_fill(~mask, 0)
            loss = -(b["target"].cuda() * logp).sum(-1).mean()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(enc + head, 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            step += 1
            if step % 200 == 0:
                print(f"  época {epoch + 1} paso {step}/{steps} pérdida {loss.item():.3f} ({time.time() - t0:.0f} s)", flush=True)
        model.eval()
        report[f"epoch_{epoch + 1}"] = evaluate(agent, tree, exam)
        print(f"época {epoch + 1}:", json.dumps(report[f"epoch_{epoch + 1}"]), flush=True)
        torch.cuda.empty_cache()
    report["train_seconds"] = round(time.time() - t0)
    if not args.limit:
        from safetensors.torch import save_file
        os.makedirs(OUT, exist_ok=True)
        for sub in ("tokenizer", "encoder"):
            shutil.copytree(BASE / sub, OUT / sub, dirs_exist_ok=True)
        cfg = dict(agent.cfg)
        cfg.update({"model_name": "laya-mapa", "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                    "distilled_from": "gpt-6-luna"})
        (OUT / "rl_agent_config.json").write_text(json.dumps(cfg, indent=2))
        save_file({k: (v.detach().half() if v.is_floating_point() else v).contiguous().cpu()
                   for k, v in model.state_dict().items()}, str(OUT / "model.safetensors"))
        print(f"alumno guardado en {OUT}")
    (BIG / ("tree-report.json" if not args.limit else "tree-report-smoke.json")).write_text(json.dumps(report, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("stats", "train", "eval"))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=8, help="preguntas por paso")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=str(OUT))
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    tree = Tree()
    if args.cmd == "stats":
        rows = load_labels(exam=False)
        qs = [q for r in rows for q in tree.train_questions(picks_of(r))]
        sizes = [len(tree.kids[n]) for n, _ in qs]
        print(f"{len(rows)} frases de entrenamiento -> {len(qs)} preguntas ({len(qs) / max(1, len(rows)):.1f} por frase); "
              f"opciones p50 {sorted(sizes)[len(sizes) // 2]} máx {max(sizes)}")
        print("ejemplo:", tree.question("es")["criteria"]["c:Asturias"])
        g = next(n for n in tree.kids if n.startswith("g:") and len(tree.kids[n]) > 5)
        print("ejemplo municipio:", tree.question(g)["criteria"][tree.kids[g][0]])
    elif args.cmd == "train":
        train(args)
    else:
        import laya
        agent = laya.load(args.model, device="cuda")
        print(json.dumps(evaluate(agent, tree, load_labels(exam=True))))


if __name__ == "__main__":
    main()
