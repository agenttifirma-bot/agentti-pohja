"""Tulos: 'ok' tai 'ei_tietoa'. 'En tieda' on aina sallittu ja hyvaksytty lopputulos.

Periaate: agentti saa myontaa, ettei tieda tai ettei data riita. Se on parempi kuin
pakotettu vastaus, joka ei toimi. Koodi ei koskaan rankaise ei_tietoa-vastauksesta.
"""
import json
import re
from dataclasses import dataclass
from typing import Optional

from . import skeema

TILAT = ("ok", "ei_tietoa")


class TulosVirhe(Exception):
    """koodi: llm_vastaus_ei_json | llm_skeema"""

    def __init__(self, koodi):
        super().__init__(koodi)
        self.koodi = koodi


@dataclass
class Tulos:
    tila: str
    sisalto: Optional[dict] = None
    syy: Optional[str] = None


def kuori_skeema(sisalto_skeema):
    """Agentin oma sisaltoskeema + pakollinen tila/syy-kuori."""
    return {
        "type": "object",
        "required": ["tila"],
        "properties": {
            "tila": {"type": "string", "enum": list(TILAT)},
            "syy": {"type": "string", "maxLength": 500},
            "sisalto": sisalto_skeema,
        },
    }


_AITA = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def lue(teksti, sisalto_skeema):
    """Parsii LLM:n tekstivastauksen. Nostaa TulosVirhe, jos muoto ei kelpaa."""
    m = _AITA.match(teksti)
    if m:
        teksti = m.group(1)
    try:
        data = json.loads(teksti)
    except ValueError:
        raise TulosVirhe("llm_vastaus_ei_json")
    try:
        skeema.tarkista(data, kuori_skeema(sisalto_skeema))
    except skeema.SkeemaVirhe:
        raise TulosVirhe("llm_skeema")
    if data["tila"] == "ei_tietoa":
        syy = (data.get("syy") or "").strip()
        if not syy:
            raise TulosVirhe("llm_skeema")  # ei_tietoa vaatii perustelun
        return Tulos("ei_tietoa", None, syy)
    if "sisalto" not in data:
        raise TulosVirhe("llm_skeema")
    return Tulos("ok", data["sisalto"], None)
