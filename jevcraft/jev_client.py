"""Async client for TypeSafe's jev with pluggable providers.

All providers accept the same body ({model?, state, questions}) and return the
same answer shape, so the rest of the project never cares which one is used.

    openrouter : POST https://openrouter.ai/api/alpha/decisions
    typesafe   : POST https://api.typesafe.ai/v1/systemone
    cloudflare : POST https://api.cloudflare.com/client/v4/accounts/{id}/ai/run/typesafe/jev
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .config import Settings, settings as default_settings


class JevError(RuntimeError):
    pass


@dataclass
class JevResponse:
    answers: dict[str, dict[str, Any]]
    latency_ms: float
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class JevClient:
    def __init__(self, cfg: Settings = default_settings, session: aiohttp.ClientSession | None = None):
        self.cfg = cfg
        self._session = session
        self._own_session = session is None
        self.total_calls = 0
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.provider = cfg.provider
        if self.provider not in ("openrouter", "typesafe", "cloudflare"):
            raise JevError(f"unknown JEV_PROVIDER '{self.provider}'")

    # -- lifecycle -----------------------------------------------------
    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def start(self):
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._own_session = True

    async def close(self):
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    # -- request building -----------------------------------------------
    def _request(self, state: Any, questions: dict[str, Any]) -> tuple[str, dict[str, str], dict[str, Any]]:
        cfg = self.cfg
        headers = {"Content-Type": "application/json"}
        if self.provider == "openrouter":
            if not cfg.openrouter_api_key:
                raise JevError("OPENROUTER_API_KEY is not set")
            headers["Authorization"] = f"Bearer {cfg.openrouter_api_key}"
            headers["HTTP-Referer"] = "https://github.com/alfonso-asenjo/systemone-potential"
            headers["X-Title"] = "systemone-potential"
            body = {"model": cfg.model or "typesafe/jev-1.13", "state": state, "questions": questions}
            return "https://openrouter.ai/api/alpha/decisions", headers, body
        if self.provider == "typesafe":
            if not cfg.typesafe_api_key:
                raise JevError("TYPESAFE_API_KEY is not set")
            headers["Authorization"] = f"Bearer {cfg.typesafe_api_key}"
            body = {"model": cfg.model or "jev-latest", "state": state, "questions": questions}
            return "https://api.typesafe.ai/v1/systemone", headers, body
        # cloudflare
        if not (cfg.cloudflare_account_id and cfg.cloudflare_api_token):
            raise JevError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are not set")
        headers["Authorization"] = f"Bearer {cfg.cloudflare_api_token}"
        url = f"https://api.cloudflare.com/client/v4/accounts/{cfg.cloudflare_account_id}/ai/run/typesafe/jev"
        return url, headers, {"state": state, "questions": questions}

    # -- call -----------------------------------------------------------
    async def decide(self, state: Any, questions: dict[str, Any]) -> JevResponse:
        if self._session is None:
            await self.start()
        url, headers, body = self._request(state, questions)
        t0 = time.perf_counter()
        async with self._session.post(url, json=body, headers=headers) as resp:
            text = await resp.text()
            latency = (time.perf_counter() - t0) * 1000
            if resp.status != 200:
                raise JevError(f"{self.provider} HTTP {resp.status}: {text[:400]}")
            try:
                data = await resp.json(content_type=None)
            except Exception as exc:  # noqa: BLE001
                raise JevError(f"non-JSON response: {text[:200]}") from exc

        if self.provider == "cloudflare":
            if not data.get("success", True):
                raise JevError(f"cloudflare error: {data.get('errors')}")
            data = data.get("result", data)
        if "error" in data:
            raise JevError(f"api error: {data['error']}")
        if "answers" not in data:
            raise JevError(f"unexpected response: {str(data)[:300]}")

        usage = data.get("usage") or {}
        out = JevResponse(
            answers=data["answers"],
            latency_ms=latency,
            model=str(data.get("model", "")),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            cost_usd=float(usage.get("cost", 0) or 0),
            raw=data,
        )
        if not out.cost_usd and out.input_tokens:
            out.cost_usd = out.input_tokens * 0.042 / 1_000_000  # published price, output is free
        self.total_calls += 1
        self.total_cost += out.cost_usd
        self.total_input_tokens += out.input_tokens
        return out
