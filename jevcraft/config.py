"""Configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # jev access: openrouter | cloudflare | typesafe
    provider: str = os.environ.get("JEV_PROVIDER", "openrouter").lower()
    model: str | None = os.environ.get("JEV_MODEL") or None
    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    typesafe_api_key: str = os.environ.get("TYPESAFE_API_KEY", "")
    cloudflare_account_id: str = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    cloudflare_api_token: str = os.environ.get("CLOUDFLARE_API_TOKEN", "")

    # commander loop
    decision_interval: float = _f("DECISION_INTERVAL", 1.5)   # wall-clock seconds between calls
    confidence_min: float = _f("CONFIDENCE_MIN", 0.20)        # below this, keep previous decision
    switch_margin: float = _f("SWITCH_MARGIN", 0.10)          # new choice must beat the current one by this much
    request_timeout: float = _f("JEV_TIMEOUT", 8.0)

    # dashboard
    dashboard_port: int = int(os.environ.get("DASHBOARD_PORT", "8765"))
    log_dir: Path = ROOT / "logs"


settings = Settings()
