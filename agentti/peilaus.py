"""Raporttipeilaus: kopioi yojonon raportit ja tilan SIIVOTTUINA kohdehakemistoon (esim. yksityisen repon kansio).

Kayttotarkoitus: Claude (pilvessa) ei paase palvelimelle, joten palvelin vie siivotut raportit yksityiseen repoon, josta ne luetaan.
Vain luku lahteesta; salaisuuden nakoiset merkkijonot poistetaan (agentti.tilannekuva.siivoa); vain .md/.json raportit viimeiselta N paivalta.
Kaytto: python3 -m agentti.peilaus <perus> <kohde> [paivia]
"""
import json
import shutil
import sys
import time
from pathlib import Path

from .tilannekuva import siivoa

OLETUS_PAIVIA = 14
MAX_KOKO = 200_000  # tavua / tiedosto


def _kopioi_siivottuna(lahde, kohde):
    teksti = Path(lahde).read_text(encoding="utf-8", errors="replace")[:MAX_KOKO]
    Path(kohde).parent.mkdir(parents=True, exist_ok=True)
    Path(kohde).write_text(siivoa(teksti), encoding="utf-8")


def peilaa(perus, kohde, paivia=OLETUS_PAIVIA, nyt=None):
    """Palauttaa kopioitujen tiedostojen maaran. Poistaa kohteesta vanhat raportit, jotta kansio vastaa lahdetta."""
    perus, kohde = Path(perus), Path(kohde)
    kohde.mkdir(parents=True, exist_ok=True)
    raja = (nyt if nyt is not None else time.time()) - paivia * 86400
    raportit_kohde = kohde / "raportit"
    if raportit_kohde.exists():
        shutil.rmtree(raportit_kohde)
    n = 0
    lahde_raportit = perus / "raportit"
    if lahde_raportit.is_dir():
        for p in sorted(lahde_raportit.iterdir()):
            if p.is_file() and p.suffix in (".md", ".json") and p.stat().st_mtime >= raja:
                _kopioi_siivottuna(p, raportit_kohde / p.name)
                n += 1
    for nimi in ("tila.json", "jono.json"):
        if (perus / nimi).is_file():
            _kopioi_siivottuna(perus / nimi, kohde / nimi)
            n += 1
    (kohde / "paivitetty.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(nyt)) + "\n", encoding="utf-8")
    return n


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (2, 3):
        print("kaytto: python3 -m agentti.peilaus <perus> <kohde> [paivia]", file=sys.stderr)
        return 2
    try:
        paivia = int(argv[2]) if len(argv) == 3 else OLETUS_PAIVIA
    except ValueError:
        print("paivia pitaa olla kokonaisluku", file=sys.stderr)
        return 2
    print("peilattu %d tiedostoa" % peilaa(argv[0], argv[1], paivia))
    return 0


if __name__ == "__main__":
    sys.exit(main())
