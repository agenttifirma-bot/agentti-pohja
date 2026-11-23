"""Aivon muistihaun vertailumittari: recall@k keksitylla keskusteluaineistolla.

Mittaa, loytaako haku oikean keskustelun kysymyksen perusteella. Aineisto on keksitty
(aivo/testidata/haku/). Moduuli ei lue oikeaa muistihakemistoa eika kayta verkkoa tai mallia.

Hakufunktion rajapinta: haku(kysymys, kirjasto) -> jarjestetty lista keskustelun tunnisteita
(paras ensin). `kirjasto` on valiaikainen hakemisto, jossa jokainen keskustelu on tiedostona
<tunniste>.md. Oletushaku on nykyinen Aivon haku (aivo.chat.lue_muisti kysymyksen kanssa).
Toinen haku (esim. FTS5) kytketaan parametrilla: --haku moduuli:funktio tai mittaa(haku=...).

Ajo: python3 -m aivo.hakumittari [--k 5] [--aineisto polku] [--haku moduuli:funktio]
"""
import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path

OLETUS_AINEISTO = Path(__file__).resolve().parent / "testidata" / "haku"
OLETUS_K = 5
KYSYMYKSET = "kysymykset.jsonl"


def lue_jsonl(polku):
    return [json.loads(r) for r in Path(polku).read_text(encoding="utf-8").splitlines() if r.strip()]


def lataa_aineisto(hakemisto=OLETUS_AINEISTO):
    """Palauttaa (keskustelut, kysymykset). keskustelut: {tunniste: [rivit]}."""
    juuri = Path(hakemisto)
    keskustelut = {}
    for p in sorted(juuri.glob("*.jsonl")):
        if p.name != KYSYMYKSET:
            keskustelut[p.stem] = lue_jsonl(p)
    return keskustelut, lue_jsonl(juuri / KYSYMYKSET)


def keskustelun_teksti(rivit):
    return "".join("%s: %s\n\n" % ("Tony" if r.get("rooli") == "tony" else "Aivo", r.get("teksti", ""))
                   for r in rivit)


def kirjoita_kirjasto(keskustelut, kohde):
    for tunniste, rivit in keskustelut.items():
        (Path(kohde) / (tunniste + ".md")).write_text(keskustelun_teksti(rivit), encoding="utf-8")


def nykyinen_haku(kysymys, kirjasto):
    """Nykyinen haku: lue_muisti jarjestaa tiedostot kysymyksen sanojen osumien mukaan."""
    from aivo.chat import lue_muisti
    _, tiedostot = lue_muisti(kirjasto, kysymys=kysymys)
    return [Path(t).stem for t in tiedostot]


def recall_at_k(tulokset, k=OLETUS_K):
    """tulokset: [(oikea_tunniste, jarjestetty_lista)]. Osuma, jos oikea on k parhaan joukossa."""
    if not tulokset:
        return 0.0
    return sum(1 for oikea, lista in tulokset if oikea in list(lista)[:k]) / len(tulokset)


def mittaa(haku=nykyinen_haku, aineisto=OLETUS_AINEISTO, k=OLETUS_K):
    keskustelut, kysymykset = lataa_aineisto(aineisto)
    tulokset, virheet = [], []
    with tempfile.TemporaryDirectory(prefix="aivo-hakumittari-") as kirjasto:
        kirjoita_kirjasto(keskustelut, kirjasto)
        for q in kysymykset:
            lista = list(haku(q["kysymys"], kirjasto))
            tulokset.append((q["oikea"], lista))
            if q["oikea"] not in lista[:k]:
                sija = lista.index(q["oikea"]) + 1 if q["oikea"] in lista else None
                virheet.append({"kysymys": q["kysymys"], "oikea": q["oikea"],
                                "tyyppi": q.get("tyyppi", ""), "sija": sija})
    return {"k": k, "kysymyksia": len(kysymykset), "keskusteluja": len(keskustelut),
            "recall": recall_at_k(tulokset, k), "epaonnistuneet": virheet}


def lataa_haku(maare):
    moduuli, _, nimi = maare.partition(":")
    if not moduuli or not nimi:
        raise ValueError("haku-muoto on moduuli:funktio")
    return getattr(importlib.import_module(moduuli), nimi)


def tulosta(t, ulos=sys.stdout):
    osuneet = t["kysymyksia"] - len(t["epaonnistuneet"])
    print("recall@%d = %.3f (%d/%d kysymysta, %d keskustelua)"
          % (t["k"], t["recall"], osuneet, t["kysymyksia"], t["keskusteluja"]), file=ulos)
    for v in t["epaonnistuneet"]:
        print("EPAONNISTUI [%s] %s -> oikea %s, sija %s"
              % (v["tyyppi"], v["kysymys"], v["oikea"], v["sija"] or "ei listalla"), file=ulos)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--k", type=int, default=OLETUS_K)
    p.add_argument("--aineisto", default=str(OLETUS_AINEISTO))
    p.add_argument("--haku", default=None, help="moduuli:funktio (oletus: nykyinen haku)")
    a = p.parse_args(argv)
    try:
        haku = lataa_haku(a.haku) if a.haku else nykyinen_haku
    except (ValueError, ImportError, AttributeError) as e:
        print("haun lataus epaonnistui (%s)" % type(e).__name__, file=sys.stderr)
        return 2
    tulosta(mittaa(haku, a.aineisto, a.k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
