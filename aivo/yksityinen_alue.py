"""Yksityisen tilan muistialue (/var/lib/aivo-yksityinen). Tama moduuli kasittelee yksityista dataa, joten se ei saa
tuoda alaprosesseja, verkkoa tai tyokalutilan moduuleja eika viitata Claudeen, OpenRouteriin tai LiteLLM:aan.
Rajaus todennetaan test_alue_erottelu.py:ssa."""

from aivo.alue import Alue

OLETUS_JUURI = "/var/lib/aivo-yksityinen"
ALIKANSIOT = ("chat", "muisti", "ehdotukset", "ydinohjeet", "tiivistelmat", "indeksi", "siirrot")


def yksityinen_alue(juuri=OLETUS_JUURI):
    return Alue("yksityinen", juuri, ALIKANSIOT)
