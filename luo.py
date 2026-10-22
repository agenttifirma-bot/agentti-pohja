"""Luo uuden agentin pohjasta: python luo.py NIMI

Tekee agentti/agentit/NIMI.py (kopio esimerkista), test/test_NIMI.py (perustestit mallista) ja
systemd/agentti-NIMI.service + .timer.
Ei ylikirjoita mitaan olemassa olevaa."""
import os
import re
import sys

JUURI = os.path.dirname(os.path.abspath(__file__))
NIMI_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def luo(nimi, juuri=JUURI):
    if not NIMI_RE.match(nimi) or nimi == "esimerkki":
        raise ValueError("nimi: pienet kirjaimet, numerot ja _ (2-31 merkkia), ei 'esimerkki'")
    kohteet = {
        os.path.join(juuri, "agentti", "agentit", nimi + ".py"):
            os.path.join(juuri, "agentti", "agentit", "esimerkki.py"),
        os.path.join(juuri, "test", "test_%s.py" % nimi):
            os.path.join(juuri, "test", "agentti.test.mall"),
        os.path.join(juuri, "systemd", "agentti-%s.service" % nimi):
            os.path.join(juuri, "systemd", "agentti.service.mall"),
        os.path.join(juuri, "systemd", "agentti-%s.timer" % nimi):
            os.path.join(juuri, "systemd", "agentti.timer.mall"),
    }
    for kohde in kohteet:
        if os.path.exists(kohde):
            raise FileExistsError(os.path.relpath(kohde, juuri))
    for kohde, lahde in kohteet.items():
        with open(lahde, encoding="utf-8") as f:
            teksti = f.read()
        if lahde.endswith("esimerkki.py"):
            teksti = teksti.replace('NIMI = "esimerkki"', 'NIMI = "%s"' % nimi)
        elif lahde.endswith("agentti.test.mall"):
            teksti = teksti.replace("@NIMI@", nimi)
        else:
            teksti = teksti.replace("@NIMI@", nimi)
        with open(kohde, "w", encoding="utf-8") as f:
            f.write(teksti)
    return [os.path.relpath(k, juuri) for k in kohteet]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("kaytto: python luo.py NIMI", file=sys.stderr)
        sys.exit(2)
    try:
        for polku in luo(sys.argv[1]):
            print("luotu:", polku)
    except (ValueError, FileExistsError) as e:
        print("virhe: %s" % e, file=sys.stderr)
        sys.exit(2)
