"""Vaiteportti opetusmateriaalille (virheiden ehkaisy, juurisyy 2: muistista eika lahteesta).

Saanto: aanikirjat/matka/<nimi>.md saa olla README:ssa (aanikirjat/README.md) tilassa "valmis" vain, jos vieressa on
tiedosto aanikirjat/matka/<nimi>.tarkastus.md (riippumattoman tarkastajan raportti, ei tyhja).
README:n rivi tulkitaan: rivi, jossa mainitaan <nimi> (tai nimen M-tunnus, esim. M04) ja sana "valmis" (ei "ei valmis").

Kaytto: python3 -m claudejono.vaiteportti DOCS_JUURI   (poistumiskoodi 1, jos puutteita)
Aamukooste kutsuu puutteet()-funktiota ja nostaa puutteet halytyksiin. Vain luku."""
import re
import sys
from pathlib import Path

MATKA = "aanikirjat/matka"
README = "aanikirjat/README.md"
VALMIS_RE = re.compile(r"(?<![\w-])(?<!ei )(?<!ei\u00a0)valmis(?![\w-])", re.IGNORECASE)
TUNNUS_RE = re.compile(r"^(M\d+)", re.IGNORECASE)


def lahteet(juuri):
    """Matkamateriaalit (nimen runko), ilman .tarkastus.md-tiedostoja."""
    hak = Path(juuri) / MATKA
    if not hak.is_dir():
        return []
    return sorted(p.stem for p in hak.glob("*.md") if not p.name.endswith(".tarkastus.md") and p.is_file())


def valmiiksi_merkityt(juuri, nimet):
    """Nimet, joiden README-rivilla on tila valmis."""
    readme = Path(juuri) / README
    if not readme.is_file():
        return []
    rivit = readme.read_text(encoding="utf-8", errors="replace").splitlines()
    ulos = []
    for nimi in nimet:
        tunnus = TUNNUS_RE.match(nimi)
        avaimet = [nimi.lower()] + ([tunnus.group(1).lower()] if tunnus else [])
        for rivi in rivit:
            alempi = rivi.lower()
            if any(re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w])", alempi) for a in avaimet) and VALMIS_RE.search(rivi):
                ulos.append(nimi)
                break
    return ulos


def puutteet(juuri):
    """Lista nimia, jotka on merkitty valmiiksi ilman ei-tyhjaa <nimi>.tarkastus.md-tiedostoa."""
    ulos = []
    for nimi in valmiiksi_merkityt(juuri, lahteet(juuri)):
        t = Path(juuri) / MATKA / f"{nimi}.tarkastus.md"
        if not (t.is_file() and t.read_text(encoding="utf-8", errors="replace").strip()):
            ulos.append(nimi)
    return ulos


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("kaytto: python3 -m claudejono.vaiteportti DOCS_JUURI", file=sys.stderr)
        return 2
    p = puutteet(argv[0])
    for nimi in p:
        print(f"HYLATTY: {nimi} on README:ssa valmis, mutta {nimi}.tarkastus.md puuttuu tai on tyhja")
    if not p:
        print("ok: kaikilla valmiiksi merkityilla on tarkastus")
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main())
