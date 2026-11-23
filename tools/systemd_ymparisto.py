"""systemd_ymparisto.py: tarkistaa repon systemd-mallien ja ohjeiden Environment=-rivit.

systemd pilkkoo Environment=-arvon sanoiksi valilyonneista (lainausmerkit ja kenoviivat
huomioiden) ja hylkaa jokaisen sanan, joka ei ole muotoa AVAIN=arvo, varoituksella
"Invalid environment assignment, ignoring". Siksi rivi
    Environment=GIT_SSH_COMMAND=ssh -i /polku
asettaa vain GIT_SSH_COMMAND=ssh. Oikein: Environment="GIT_SSH_COMMAND=ssh -i /polku".

Tarkistettavat tiedostot:
  - kaikki *.service.mall, *.service, *.socket.mall, *.conf.mall (yksikkotiedostot ja drop-init)
  - docs/**.md ja muut .md-tiedostot: rivit, jotka (sisennyksen jalkeen) alkavat "Environment="
    (yksikkolohkot ohjeissa). Taulukkorivit ja tekstin sisaiset maininnat eivat ala nain.

Kaytto: python3 tools/systemd_ymparisto.py [juuri]   -> paluukoodi 0 = OK, 1 = virheita.
"""

import os
import re
import shlex
import sys

AVAIN_ARVO = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
YKSIKKOPAATTEET = (".service.mall", ".service", ".socket.mall", ".conf.mall")
OHITETTAVAT_HAKEMISTOT = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def pilko(arvo):
    """Pilkkoo Environment=-arvon sanoiksi kuten systemd (lainaukset ja kenoviivat).

    Palauttaa (sanat, virhe). Virhe on merkkijono, jos lainausmerkit ovat parittomat.
    """
    try:
        lex = shlex.shlex(arvo, posix=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex), None
    except ValueError:
        return [], "lainausmerkit parittomat"


def tarkista_arvo(arvo):
    """Palauttaa listan virheita yhdelle Environment=-arvolle (tyhja lista = OK)."""
    sanat, virhe = pilko(arvo)
    if virhe:
        return [virhe]
    return ["ei AVAIN=arvo -muotoa: %r" % s for s in sanat if not AVAIN_ARVO.match(s)]


def environment_rivit(teksti, ohje=False):
    """Palauttaa (rivinumero, arvo) jokaiselle Environment=-riville.

    Yksikkotiedostossa jatkorivit (rivin lopussa kenoviiva) yhdistetaan kuten systemd.
    Ohjeessa (ohje=True) rivin alussa saa olla sisennysta.
    """
    tulos = []
    rivit = teksti.splitlines()
    i = 0
    while i < len(rivit):
        alku = i
        rivi = rivit[i]
        while rivi.endswith("\\") and i + 1 < len(rivit) and not ohje:
            i += 1
            rivi = rivi[:-1] + " " + rivit[i]
        i += 1
        s = rivi.lstrip() if ohje else rivi
        if s.startswith("Environment="):
            tulos.append((alku + 1, s[len("Environment="):].strip()))
    return tulos


def tiedostot(juuri):
    """Palauttaa (polku, ohje) -parit tarkistettavista tiedostoista lajiteltuna."""
    loydetyt = []
    for hak, alihak, nimet in os.walk(juuri):
        alihak[:] = sorted(d for d in alihak if d not in OHITETTAVAT_HAKEMISTOT)
        for nimi in sorted(nimet):
            polku = os.path.join(hak, nimi)
            if nimi.endswith(YKSIKKOPAATTEET):
                loydetyt.append((polku, False))
            elif nimi.endswith(".md"):
                loydetyt.append((polku, True))
    return loydetyt


def tarkista(juuri):
    """Palauttaa listan virheita muodossa (polku, rivi, viesti)."""
    virheet = []
    for polku, ohje in tiedostot(juuri):
        with open(polku, encoding="utf-8", errors="replace") as f:
            teksti = f.read()
        for rivi, arvo in environment_rivit(teksti, ohje=ohje):
            for viesti in tarkista_arvo(arvo):
                virheet.append((os.path.relpath(polku, juuri), rivi, viesti))
    return virheet


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    juuri = argv[0] if argv else "."
    virheet = tarkista(juuri)
    for polku, rivi, viesti in virheet:
        print("%s:%d: Environment=: %s (lainaa koko AVAIN=arvo lainausmerkkeihin)" % (polku, rivi, viesti))
    print("systemd_ymparisto: %s" % ("OK" if not virheet else "%d virhetta" % len(virheet)))
    return 1 if virheet else 0


if __name__ == "__main__":
    sys.exit(main())
