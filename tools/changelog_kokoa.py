"""Kokoaa muutosfragmentit (docs/muutokset/*.md) CHANGELOG.md:n kohtaan "## Unreleased".

Jokainen PR kirjoittaa oman fragmenttitiedostonsa (esim. docs/muutokset/yojono-ajopaiva.md, rivit muotoa "- ..."), joten rinnakkaiset
PR:t eivat enaa konfliktoi CHANGELOG.md:ssa. Kokoaja lisaa rivit Unreleased-listan loppuun nimijarjestyksessa ja poistaa fragmentit.
Kaytto: python3 tools/changelog_kokoa.py [--kuiva]   (ajetaan julkaisun yhteydessa tai viikoittain yhdella PR:lla)"""
import sys
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
OTSIKKO = "## Unreleased"


def lue_fragmentit(hakemisto):
    """[(polku, [rivit])]: vain '- '-alkuiset rivit, nimijarjestyksessa; README.md ohitetaan."""
    tulos = []
    for p in sorted(Path(hakemisto).glob("*.md")):
        if p.name.lower() == "readme.md":
            continue
        rivit = [r.rstrip() for r in p.read_text(encoding="utf-8").splitlines() if r.startswith("- ")]
        if rivit:
            tulos.append((p, rivit))
    return tulos


def lisaa_changelogiin(teksti, rivit):
    """Lisaa rivit Unreleased-listan loppuun (ennen seuraavaa '## '-otsikkoa). Nostaa ValueError jos otsikkoa ei ole."""
    rivit_nyt = teksti.split("\n")
    try:
        alku = rivit_nyt.index(OTSIKKO)
    except ValueError:
        raise ValueError("CHANGELOG.md:sta puuttuu otsikko: " + OTSIKKO)
    loppu = len(rivit_nyt)
    for i in range(alku + 1, len(rivit_nyt)):
        if rivit_nyt[i].startswith("## "):
            loppu = i
            break
    while rivit_nyt[loppu - 1].strip() == "":   # rivi alku on otsikko, joten silmukka pysahtyy viimeistaan siihen
        loppu -= 1
    return "\n".join(rivit_nyt[:loppu] + list(rivit) + rivit_nyt[loppu:])


def main(argv=None, juuri=JUURI):
    a = sys.argv[1:] if argv is None else argv
    if any(x != "--kuiva" for x in a):
        print("kaytto: python3 tools/changelog_kokoa.py [--kuiva]", file=sys.stderr)
        return 2
    juuri = Path(juuri)
    fragmentit = lue_fragmentit(juuri / "docs" / "muutokset")
    if not fragmentit:
        print("Ei fragmentteja.")
        return 0
    kaikki = [r for _, rivit in fragmentit for r in rivit]
    polku = juuri / "CHANGELOG.md"
    try:
        uusi = lisaa_changelogiin(polku.read_text(encoding="utf-8"), kaikki)
    except ValueError as virhe:
        print(str(virhe), file=sys.stderr)
        return 1
    if "--kuiva" in a:
        print("%d rivia, %d fragmenttia (kuiva-ajo, ei muutoksia)" % (len(kaikki), len(fragmentit)))
        return 0
    polku.write_text(uusi, encoding="utf-8")
    for p, _ in fragmentit:
        p.unlink()
    print("Lisatty %d rivia CHANGELOG.md:hen, poistettu %d fragmenttia." % (len(kaikki), len(fragmentit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
