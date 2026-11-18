"""Hylkaa PR:n, joka muokkaa CHANGELOG.md:ta suoraan (muutosrivi kuuluu fragmenttiin docs/muutokset/<haara>.md).

Syy: jokainen PR, joka lisaa rivin CHANGELOG.md:n alkuun, konfliktoi muiden kanssa (17.-18.11.2026 viisi hyvaksyttya PR:aa).
GitHubin yhdistaminen ei kayta .gitattributes-asetuksen merge=union-ajuria, joten fragmentit ovat ainoa luotettava tapa.
Poikkeus: kokoaja-PR (tools/changelog_kokoa.py), joka muuttaa CHANGELOG.md:ta ja poistaa samalla vahintaan yhden fragmentin.

Kaytto: python3 tools/changelog_tarkista.py [--pohja REF] [HAKEMISTO]
  --pohja REF  vertailukohta (oletus origin/main, sitten main); erotus lasketaan muodossa REF...HEAD
Paluukoodi: 0 = kunnossa, 1 = suora CHANGELOG-muutos, 2 = kayttovirhe tai vertailua ei voitu laskea (ei oleteta kunnossa)."""
import subprocess
import sys

CHANGELOG = "CHANGELOG.md"
FRAGMENTTI_ALKU = "docs/muutokset/"
OLETUSPOHJAT = ("origin/main", "main")


def _git(hakemisto, *args):
    p = subprocess.run(["git", "-C", hakemisto, *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def _on_fragmentti(polku):
    nimi = polku[len(FRAGMENTTI_ALKU):]
    return (polku.startswith(FRAGMENTTI_ALKU) and "/" not in nimi and nimi.endswith(".md")
            and nimi.lower() != "readme.md")


def muutokset(hakemisto, pohja):
    """(muutetut, poistetut) polut; None jos erotusta ei voi laskea."""
    koodi, ulos = _git(hakemisto, "diff", "--name-status", "--no-renames", pohja + "...HEAD")
    if koodi != 0:
        return None
    muutetut, poistetut = [], []
    for rivi in ulos.splitlines():
        tila, erotin, polku = rivi.partition("\t")
        if not erotin:
            continue
        (poistetut if tila.startswith("D") else muutetut).append(polku)
    return muutetut, poistetut


def arvioi(muutetut, poistetut):
    """Palauttaa virheviestin tai None. Puhdas funktio testeja varten."""
    if CHANGELOG not in muutetut and CHANGELOG not in poistetut:
        return None
    if CHANGELOG in muutetut and any(_on_fragmentti(p) for p in poistetut):
        return None   # kokoaja-PR
    return ("%s:ta ei muokata PR:ssa (rinnakkaiset PR:t konfliktoivat). Kirjoita rivi(t) muodossa '- aihe: mita ja miksi' "
            "tiedostoon %s<haara>.md ja palauta %s mainin versioon." % (CHANGELOG, FRAGMENTTI_ALKU, CHANGELOG))


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    pohjat = OLETUSPOHJAT
    if "--pohja" in a:
        i = a.index("--pohja")
        if i + 1 >= len(a):
            print("kaytto: changelog_tarkista.py [--pohja REF] [HAKEMISTO]", file=sys.stderr)
            return 2
        pohjat = (a[i + 1],)
        del a[i:i + 2]
    if len(a) > 1:
        print("kaytto: changelog_tarkista.py [--pohja REF] [HAKEMISTO]", file=sys.stderr)
        return 2
    hakemisto = a[0] if a else "."
    tulos = None
    for pohja in pohjat:
        tulos = muutokset(hakemisto, pohja)
        if tulos is not None:
            break
    if tulos is None:
        print("changelog_tarkista: vertailua ei voitu laskea (pohja: %s)" % ", ".join(pohjat), file=sys.stderr)
        return 2
    virhe = arvioi(*tulos)
    if virhe:
        print("changelog_tarkista: " + virhe, file=sys.stderr)
        return 1
    print("changelog_tarkista: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
