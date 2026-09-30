"""Destilar jev en Laya: jev hace de profesor y Laya aprende a responder como él.

Pérdida: entropía cruzada contra las probabilidades de jev (objetivo blando), no contra la
opción ganadora, para que el alumno herede también la seguridad del profesor.

Memoria: la RTX 2070 tiene 8 GB y ModernBERT-large no cabe entero con Adam, así que se
entrenan solo las TOP_LAYERS capas de arriba del codificador y la cabeza de decisión. Las
de abajo, que saben leer, se quedan como vienen y en media precisión. Medido: con 8 capas
y todo en fp32 el pico era 6,5 GB, Windows desbordaba a la memoria del sistema y cada paso
tardaba 6-10 s; con 4 capas y lo congelado en fp16, 0,4 s y 4,5 GB.

Uso (con el entorno de Laya):
  .venv-laya/Scripts/python pacman/distill/train.py [--epochs 3] [--limit N]
Escribe el alumno en models/laya-pacman/ y el informe en pacman/distill/data/report.json.
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

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from compact import questions, state_text  # noqa: E402
from decide import TURN_BACK_MIN, safest_exit  # noqa: E402

import laya  # noqa: E402
from laya.agent import Agent  # noqa: E402
from laya.common import collate_items  # noqa: E402

TEACHER_BASE = os.path.join(ROOT, "models", "laya", "typed-decisions")
STUDENT_DIR = os.path.join(ROOT, "models", "laya-pacman")
DATA = os.path.join(HERE, "data")
TOP_LAYERS = 4
QUESTION_WEIGHT = {"direction": 3.0}
# jev dice "vuelve" en el 2 % de las casillas; sin más peso el alumno aprende a no decirlo nunca.
TURN_BACK_YES_WEIGHT = 10.0
# v3 subió del 80 % al 87 % de acuerdo en el examen y aun así perdió las mismas 18 vidas:
# lo que falla está en los momentos con un rival cerca, que son pocos entre tantos cruces
# tranquilos. Esas casillas pesan más al entrenar y se miden aparte en el examen.
RISKY_GHOST = 4
RISKY_WEIGHT = 3.0
# Medido en 2.725 cruces de jev: su confianza queda por debajo de 0,25 en el 11,6 %.
JEV_FALLBACK_RATE = 0.116


def load_rows(name: str, limit: int | None = None) -> list[dict]:
    rows = [json.loads(l) for l in open(os.path.join(DATA, name), encoding="utf-8")]
    return rows[:limit] if limit else rows


def risky(state: dict) -> bool:
    """Un rival que persigue a 4 casillas o menos por alguna salida."""
    near = [v.get("nearest_ghost") for v in state.get("by_exit", {}).values()]
    return min([g for g in near if g is not None] or [99]) <= RISKY_GHOST


def encode_row(agent: Agent, row: dict) -> list[dict]:
    qs = questions(row["exits"], row["state"])
    ids = [q for q in qs if q in row["targets"]]
    internal = {q: Agent._to_internal(qs[q]) for q in ids}
    items = agent._encode_state(state_text(row["state"]), ids, internal)
    for qid, it in zip(ids, items):
        it["target"] = row["targets"][qid]
        it["qid"] = qid
        it["weight"] = QUESTION_WEIGHT.get(qid, 1.0)
        if qid == "turn_back" and it["target"][1] >= TURN_BACK_MIN:
            it["weight"] = TURN_BACK_YES_WEIGHT
        if risky(row["state"]):
            it["weight"] *= RISKY_WEIGHT
    return items


def evaluate(agent: Agent, rows: list[dict]) -> dict:
    """Cuánto se parece el alumno al profesor en las decisiones que de verdad mueven a España."""
    agent.model.eval()
    dir_hit = dir_n = dir_conf_hit = dir_conf_n = rule_hit = 0
    risky_hit = risky_n = risky_rule = 0
    danger_err, danger_hit = [], 0
    dir_confs = []
    tb_pairs, noul_pairs = [], {"go_for_power": [], "hunt": []}
    t0 = time.perf_counter()
    for row in rows:
        qs = questions(row["exits"], row["state"])
        qs = {q: v for q, v in qs.items() if q in row["targets"]}
        ans = agent.predict(state_text(row["state"]), qs)["answers"]
        t = row["targets"]
        if "direction" in t:
            keys = list(qs["direction"]["criteria"])
            teacher = keys[int(np.argmax(t["direction"]))]
            hit = ans["direction"]["choice"] == teacher
            dir_hit += hit
            dir_n += 1
            dir_confs.append(ans["direction"]["confidence"])
            rule_hit += safest_exit(row["state"], keys) == teacher
            if risky(row["state"]):
                risky_hit += hit
                risky_n += 1
                risky_rule += safest_exit(row["state"], keys) == teacher
            if max(t["direction"]) >= 0.6:  # decisiones en las que jev lo tenía claro
                dir_conf_hit += hit
                dir_conf_n += 1
        if "danger" in t:
            p = [ans["danger"]["probabilities"][str(i)] for i in range(len(t["danger"]))]
            danger_err.append(abs(sum(i * x for i, x in enumerate(p)) - sum(i * x for i, x in enumerate(t["danger"]))))
            danger_hit += int(np.argmax(p)) == int(np.argmax(t["danger"]))
        if "turn_back" in t:
            tb_pairs.append((t["turn_back"][1], ans["turn_back"]["noul"]))
        for q in noul_pairs:
            if q in t:
                noul_pairs[q].append((t[q][1], ans[q]["noul"]))
    ms = (time.perf_counter() - t0) * 1000 / max(1, len(rows))

    def corr(pairs):
        a = np.array(pairs)
        return float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]) if len(a) > 2 and a[:, 1].std() > 0 else 0.0

    tb = np.array(tb_pairs)
    teacher_back = tb[:, 0] >= TURN_BACK_MIN
    # El listón del alumno se mide, no se copia: el que le hace decir "vuelve" tan a menudo
    # como jev. Es el que usa laya_client.py en partida.
    student_min = float(np.quantile(tb[:, 1], 1 - teacher_back.mean()))
    student_back = tb[:, 1] >= student_min
    return {
        "direction_agree": round(dir_hit / max(1, dir_n), 3),
        "direction_agree_when_jev_sure": round(dir_conf_hit / max(1, dir_conf_n), 3),
        "direction_n": dir_n,
        "direction_agree_risky": round(risky_hit / max(1, risky_n), 3),
        "direction_risky_n": risky_n,
        "rule_safest_exit_agree_risky": round(risky_rule / max(1, risky_n), 3),
        "rule_safest_exit_agree": round(rule_hit / max(1, dir_n), 3),
        "danger_mae": round(float(np.mean(danger_err)), 3),
        "danger_level_agree": round(danger_hit / max(1, len(danger_err)), 3),
        "turn_back_corr": round(corr(tb_pairs), 3),
        "turn_back_jev_yes": int(teacher_back.sum()),
        "turn_back_both_yes": int((teacher_back & student_back).sum()),
        "turn_back_student_yes": int(student_back.sum()),
        "turn_back_student_min": round(student_min, 4),
        # Con este mínimo el alumno cae en la regla de seguridad tan a menudo como jev con 0,25.
        "confidence_student_min": round(float(np.quantile(dir_confs, JEV_FALLBACK_RATE)), 4),
        "go_for_power_corr": round(corr(noul_pairs["go_for_power"]), 3),
        "hunt_corr": round(corr(noul_pairs["hunt"]), 3),
        "ms_per_decision": round(ms, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8, help="decisiones por paso")
    ap.add_argument("--limit", type=int, default=None, help="recortar datos para una prueba rápida")
    ap.add_argument("--eval-only", metavar="MODEL_DIR", help="solo examinar un alumno ya guardado")
    args = ap.parse_args()

    if args.eval_only:
        agent = laya.load(args.eval_only, device="cuda")
        print(json.dumps(evaluate(agent, load_rows("test.jsonl", args.limit)), indent=1))
        return

    torch.manual_seed(0)
    random.seed(0)
    agent = laya.load(TEACHER_BASE, device="cuda")
    train, test = load_rows("train.jsonl", args.limit), load_rows("test.jsonl", args.limit)
    report = {"train_decisions": len(train), "test_decisions": len(test)}

    print("Laya sin entrenar...", flush=True)
    report["before"] = evaluate(agent, test)
    print(json.dumps(report["before"], indent=1), flush=True)

    model = agent.model
    enc_layers = model.encoder.layers
    for p in model.parameters():
        p.requires_grad = False
    model.encoder.embeddings.half()
    for layer in enc_layers[:len(enc_layers) - TOP_LAYERS]:
        layer.half()
    trainable = [*enc_layers[-TOP_LAYERS:], model.encoder.final_norm, model.head, model.type_emb, model.scorer]
    for m in trainable:
        for p in m.parameters():
            p.requires_grad = True
    enc_params = [p for m in trainable[:TOP_LAYERS + 1] for p in m.parameters()]
    head_params = [p for m in trainable[TOP_LAYERS + 1:] for p in m.parameters()]
    opt = torch.optim.AdamW([{"params": enc_params, "lr": 2e-5}, {"params": head_params, "lr": 1e-4}],
                            weight_decay=0.01)
    steps = args.epochs * math.ceil(len(train) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(1, steps * 0.06)) * max(0.0, (steps - s) / steps))
    scaler = torch.amp.GradScaler("cuda")
    n_train = sum(p.numel() for p in enc_params + head_params)
    print(f"entrenando {n_train / 1e6:.0f} M parámetros, {steps} pasos", flush=True)

    encoded = [encode_row(agent, r) for r in train]
    # Laya aplica sus temperaturas al contestar; el alumno se entrena sobre los logits
    # crudos contra probabilidades ya calibradas por jev, así que sin temperatura.
    agent.temperature, agent.temperature_by_options = [1.0, 1.0, 1.0], {}

    step = 0
    t0 = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        order = list(range(len(encoded)))
        random.shuffle(order)
        running = 0.0
        for i in range(0, len(order), args.batch):
            batch = collate_items([encoded[j] for j in order[i:i + args.batch]], agent.tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                logits, _ = model(batch["input_ids"].cuda(), batch["attention_mask"].cuda(),
                                  batch["marker_pos"].cuda(), batch["marker_mask"].cuda(),
                                  batch["qtype"].cuda())
            logp = torch.log_softmax(logits.float(), -1)
            target = batch["target"].cuda()
            per_item = -(target * logp.masked_fill(~batch["marker_mask"].cuda(), 0)).sum(-1)
            w = torch.tensor([m["weight"] for m in batch["meta"]], device="cuda")
            loss = (per_item * w).sum() / w.sum()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(enc_params + head_params, 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            running = 0.98 * running + 0.02 * loss.item() if step > 1 else loss.item()
            if step % 100 == 0:
                print(f"  época {epoch + 1} paso {step}/{steps} pérdida {running:.4f} "
                      f"({time.perf_counter() - t0:.0f} s)", flush=True)
        res = evaluate(agent, test)
        report[f"after_epoch_{epoch + 1}"] = res
        print(f"época {epoch + 1}: {json.dumps(res)}", flush=True)

    report["train_seconds"] = round(time.perf_counter() - t0)
    report["after"] = report[f"after_epoch_{args.epochs}"]

    if not args.limit:
        from safetensors.torch import save_file
        os.makedirs(STUDENT_DIR, exist_ok=True)
        for sub in ("tokenizer", "encoder"):
            shutil.copytree(os.path.join(TEACHER_BASE, sub), os.path.join(STUDENT_DIR, sub), dirs_exist_ok=True)
        cfg = dict(agent.cfg)
        cfg.update({"model_name": "laya-pacman", "temperature": [1.0, 1.0, 1.0], "temperature_by_options": {},
                    "distilled_from": "typesafe/jev-1.13", "training": {
                        "decisions": len(train), "epochs": args.epochs, "top_layers": TOP_LAYERS,
                        "seconds": report["train_seconds"]},
                    "pacman": {"confidence_min": report["after"]["confidence_student_min"],
                               "turn_back_min": report["after"]["turn_back_student_min"]}})
        with open(os.path.join(STUDENT_DIR, "rl_agent_config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        state = {k: v.detach().half().contiguous().cpu() if v.is_floating_point() else v.cpu()
                 for k, v in model.state_dict().items()}
        save_file(state, os.path.join(STUDENT_DIR, "model.safetensors"))
        print(f"alumno guardado en {STUDENT_DIR}")

    with open(os.path.join(DATA, "report.json" if not args.limit else "report-smoke.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
