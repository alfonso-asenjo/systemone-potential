"""User-Agent para las APIs de Wikipedia, que piden un contacto en él.

El contacto va en .env (WIKI_CONTACT=correo o web), no en el código, para que no se publique.
"""
import os
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"


def user_agent(name: str = "jevcraft-mapa/0.1") -> str:
    contact = os.environ.get("WIKI_CONTACT", "")
    if not contact and ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("WIKI_CONTACT="):
                contact = line.split("=", 1)[1].strip()
    if not contact:
        raise SystemExit("falta WIKI_CONTACT en .env: un correo o una web de contacto, lo pide Wikipedia")
    return f"{name} ({contact})"
