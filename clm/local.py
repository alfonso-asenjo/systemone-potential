"""CLM-8B (Stanford + NVIDIA, Apache 2.0) en una RTX 2070, sin vLLM ni WSL.

El CLM original sirve Qwen3-8B con vLLM (bf16, ~16 GB) como codificador: cada texto da el vector de
su último token, y dos cabezas pequeñas (CLM_v0.1-8B.pt, 76 MB) proyectan por un lado la situación
con la pregunta y por otro cada opción. La probabilidad de una opción es el softmax de
escala * coseno. Aquí Qwen3-8B va comprimido a 4 bits (bitsandbytes nf4) para caber en 8 GB. Es lo
único que cambia respecto al original, y puede restar algo de precisión: las cabezas se entrenaron
con los vectores de Qwen3-8B sin comprimir.

    from clm.local import CLM
    clm = CLM()
    clm.answer(state, {"q": {"type": "choice", "instructions": "...", "criteria": {...}}})

Las plantillas de texto (schema.py) son las del repositorio oficial, Contrastive-LM/CLM.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .schema import answer_from_logits, build_pairs

ROOT = Path(__file__).resolve().parent.parent
QWEN = ROOT / "models" / "qwen3-8b"
HEADS = ROOT / "models" / "clm" / "CLM_v0.1-8B.pt"


def make_head(width, depth=2, proj=512, activation="gelu", layernorm=False, residual=False, hidden=4096):
    """La misma MLP que clm/heads.py: hidden -> width -> ... -> proj."""
    nn = torch.nn
    act = {"gelu": nn.GELU, "relu": nn.ReLU, "silu": nn.SiLU}[activation]

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = nn.Linear(hidden, width)
            self.hidden = nn.ModuleList(nn.Linear(width, width) for _ in range(depth - 2))
            self.norms = nn.ModuleList((nn.LayerNorm(width) if layernorm else nn.Identity()) for _ in range(depth - 2))
            self.out = nn.Linear(width, proj)
            self.act = act()
            self.residual = residual

        def forward(self, x):
            x = self.act(self.inp(x))
            for lin, nrm in zip(self.hidden, self.norms):
                h = self.act(nrm(lin(x)))
                x = x + h if self.residual else h
            return self.out(x)

    return Head()


class CLM:
    def __init__(self, qwen=QWEN, heads=HEADS, compute=torch.float16, cache_size=50_000):
        from transformers import AutoModel, AutoTokenizer, BitsAndBytesConfig
        self.tok = AutoTokenizer.from_pretrained(qwen)
        self.tok.padding_side = "left"          # así el último token de cada fila está al final
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=compute,
                               bnb_4bit_use_double_quant=True)
        self.model = AutoModel.from_pretrained(qwen, quantization_config=q, dtype=compute, device_map="cuda:0",
                                               low_cpu_mem_usage=True).eval()
        ck = torch.load(heads, map_location="cpu")
        cfg = dict(ck["cfg"])
        kw = dict(width=cfg["width"], depth=cfg["depth"], proj=ck.get("projection_dim", cfg.get("projection_dim", 512)),
                  activation=cfg.get("activation", "gelu"), layernorm=cfg.get("layernorm", False),
                  residual=cfg.get("residual", False), hidden=cfg.get("hidden_size", 4096))
        self.sh, self.ah = make_head(**kw), make_head(**kw)
        self.sh.load_state_dict(ck["state_head"]); self.ah.load_state_dict(ck["action_head"])
        self.sh.eval().cuda(); self.ah.eval().cuda()
        self.scale = float(torch.as_tensor(ck["logit_scale"]).float().exp().clamp(max=100.0))
        self.cache: OrderedDict[tuple[str, str], torch.Tensor] = OrderedDict()   # vectores ya proyectados
        self.cache_size = cache_size
        self.nan = 0

    @torch.no_grad()
    def embed(self, texts: list[str], batch: int = 8, max_length: int = 2048) -> torch.Tensor:
        """Vector del último token de cada texto, normalizado (lo que da el servidor de vLLM)."""
        out = []
        for k in range(0, len(texts), batch):
            b = self.tok(texts[k:k + batch], padding=True, truncation=True, max_length=max_length, return_tensors="pt").to("cuda")
            h = self.model(**b).last_hidden_state[:, -1].float()
            if not torch.isfinite(h).all():
                self.nan += 1
            out.append(torch.nn.functional.normalize(h, dim=-1))
        return torch.cat(out)

    @torch.no_grad()
    def _vectors(self, kind: str, texts: list[str]) -> torch.Tensor:
        head = self.sh if kind == "state" else self.ah
        todo = [t for t in dict.fromkeys(texts) if (kind, t) not in self.cache]
        if todo:
            z = torch.nn.functional.normalize(head(self.embed(todo)), dim=-1)
            for t, v in zip(todo, z):
                self.cache[(kind, t)] = v
            while len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return torch.stack([self.cache[(kind, t)] for t in texts])

    def answer(self, state: Any, questions: dict[str, dict]) -> dict:
        t0 = time.perf_counter()
        pairs = build_pairs(state, questions)
        zs = self._vectors("state", [p[0] for p in pairs.values()])
        za = self._vectors("action", [t for p in pairs.values() for t in p[2]])
        answers, k = {}, 0
        for i, (qid, (_, keys, texts)) in enumerate(pairs.items()):
            cos = (za[k:k + len(texts)] @ zs[i]).tolist()
            k += len(texts)
            answers[qid] = answer_from_logits(questions[qid], keys, [self.scale * c for c in cos])
        return {"answers": answers, "latency_ms": (time.perf_counter() - t0) * 1000}
