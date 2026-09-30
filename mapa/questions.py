"""Qué se le pregunta a jev y qué decide el código antes de preguntar.

Una sola pregunta: un Choice entre los lugares que quedan, cada uno descrito por lo que lo
distingue. Lo que jev no hace bien lo hace el código: en la prueba inicial, con "a menos de
3 horas de Madrid" siguió poniendo primero Mundaka, que está a 4 y media. Los límites de
tiempo y el "sin avión" se leen aquí y apagan lugares antes de preguntar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

INSTRUCTIONS = (
    "Someone describes, in Spanish, the place in Spain they are looking for. Which of these "
    "places matches best? Judge by what they ask for (sea or mountains, food, calm or party, "
    "size, how far they want to travel) against what each place is known for."
)

NUMBERS = {"una": 1, "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}


def describe(p: dict[str, Any]) -> str:
    coast = "interior, sin mar" if p["coast"] == "interior" else f"costa {p['coast']}"
    if p["reach"] == "island":
        reach = "en una isla, hay que ir en avión o barco"
    elif p["reach"] == "africa":
        reach = "en el norte de África, hay que ir en barco o avión"
    else:
        h = p["hours"]
        reach = f"unas {str(h).replace('.0', '').replace('.', ',')} horas en coche desde Madrid"
    return f"{p['name']} ({p['prov']}): {coast}; unos {p['pop']} habitantes; {reach}; {p['traits']}."


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


@dataclass
class Constraints:
    max_hours: float | None = None
    no_flight: bool = False
    notes: list[str] = field(default_factory=list)

    def allows(self, p: dict[str, Any]) -> bool:
        if (self.no_flight or self.max_hours is not None) and p["reach"] != "road":
            return False
        if self.max_hours is not None and p["hours"] > self.max_hours:
            return False
        return True


def parse(text: str) -> Constraints:
    """Los límites que el código sabe leer. Todo lo demás es juicio y se lo queda jev."""
    t = _plain(text)
    c = Constraints()
    num = r"(\d+(?:[.,]\d+)?|" + "|".join(NUMBERS) + r")"
    m = re.search(r"(?:a )?(?:menos de|como mucho|maximo|max\.?|no mas de|hasta) " + num + r"( y media)? horas?", t)
    if not m:
        m = re.search(num + r"( y media)? horas? (?:como mucho|como maximo|maximo)", t)
    if m:
        raw = m.group(1)
        hours = float(raw.replace(",", ".")) if raw[0].isdigit() else NUMBERS[raw]
        if m.group(2):
            hours += 0.5
        c.max_hours = hours
        c.notes.append(f"a {str(hours).replace('.0', '').replace('.', ',')} h o menos de Madrid en coche")
    elif re.search(r"hora y media", t):
        c.max_hours = 1.5
        c.notes.append("a 1,5 h o menos de Madrid en coche")
    elif re.search(r"media hora", t):
        c.max_hours = 0.5
        c.notes.append("a media hora o menos de Madrid en coche")
    if re.search(r"sin (coger |tomar )?(el )?avion|en coche|sin volar|por carretera", t):
        c.no_flight = True
        if not c.max_hours:
            c.notes.append("sin avión ni barco")
    return c


def build(places: list[dict[str, Any]]) -> dict[str, Any]:
    return {"lugar": {
        "type": "choice",
        "instructions": INSTRUCTIONS,
        "criteria": {str(p["id"]): describe(p) for p in places},
    }}
