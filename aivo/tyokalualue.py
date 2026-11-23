"""Tyokalutilan muistialue (/var/lib/aivo). Tama moduuli ei tunne yksityista aluetta: ei tuo yksityisen tilan
moduuleja eika viittaa sen polkuihin. Erottelu todennetaan test_alue_erottelu.py:ssa."""

from aivo.alue import Alue

OLETUS_JUURI = "/var/lib/aivo"
ALIKANSIOT = ("chat", "kirjasto", "tiivistelmat", "indeksi")
GIT_ALIKANSIOT = ("kirjasto",)    # kirjasto on git-klooni (.git sallitaan, muut alikansiot eivat)


def tyokalualue(juuri=OLETUS_JUURI):
    return Alue("tyokalu", juuri, ALIKANSIOT, git_alikansiot=GIT_ALIKANSIOT)
