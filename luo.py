"""Luo uuden agentin pohjasta: python luo.py NIMI [--maaritys POLKU.json]

Tekee agentti/agentit/NIMI.py (kopio esimerkista), test/test_NIMI.py (perustestit mallista) ja
systemd/agentti-NIMI.service + .timer.
Valinnaisella --maaritys-valitsimella tarkistetaan agenttimaaritys (agentti/maaritys.py) ennen mitaan
kirjoitusta ja luodaan lisaksi maaritykset/NIMI.json, ohjetiedosto (runko) ja evalit/NIMI.json (eval-runko,
jossa mittari on mukana). Virheellinen maaritys ei luo mitaan.
Ei ylikirjoita mitaan olemassa olevaa."""
import json
import os
import re
import sys

JUURI = os.path.dirname(os.path.abspath(__file__))
NIMI_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def _maaritys_kohteet(nimi, maaritys_polku, juuri):
    """Tarkistaa maarityksen ja palauttaa {kohde: teksti}. Nostaa ValueError tai MaaritysVirhe."""
    from agentti import maaritys
    m = maaritys.lue(maaritys_polku)
    if m["nimi"].replace("-", "_") != nimi:
        raise ValueError("maarityksen nimi (%s) ei vastaa agentin nimea (%s)" % (m["nimi"], nimi))
    ohje = os.path.join(juuri, m["ohje_tiedosto"])
    eval_runko = {"agentti": nimi, "mittari": m["mittari"], "tapaukset": []}
    return {
        os.path.join(juuri, "maaritykset", nimi + ".json"): json.dumps(m, ensure_ascii=False, indent=2) + "\n",
        ohje: "# Ohje: %s\n\n%s\n\nKirjoita tahan agentin ohje (Tonyn muokattava osa).\n" % (nimi, m["kuvaus"]),
        os.path.join(juuri, "evalit", nimi + ".json"): json.dumps(eval_runko, ensure_ascii=False, indent=2) + "\n",
    }


def luo(nimi, juuri=JUURI, maaritys_polku=None):
    if not NIMI_RE.match(nimi) or nimi == "esimerkki":
        raise ValueError("nimi: pienet kirjaimet, numerot ja _ (2-31 merkkia), ei 'esimerkki'")
    lisat = _maaritys_kohteet(nimi, maaritys_polku, juuri) if maaritys_polku else {}
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
    for kohde in list(kohteet) + list(lisat):
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
    for kohde, teksti in lisat.items():
        os.makedirs(os.path.dirname(kohde), exist_ok=True)
        with open(kohde, "w", encoding="utf-8") as f:
            f.write(teksti)
    return [os.path.relpath(k, juuri) for k in list(kohteet) + list(lisat)]


if __name__ == "__main__":
    args = sys.argv[1:]
    polku = None
    if len(args) == 3 and args[1] == "--maaritys":
        polku = args[2]
        args = args[:1]
    if len(args) != 1:
        print("kaytto: python luo.py NIMI [--maaritys POLKU.json]", file=sys.stderr)
        sys.exit(2)
    try:
        for p in luo(args[0], maaritys_polku=polku):
            print("luotu:", p)
    except Exception as e:  # ValueError, FileExistsError, MaaritysVirhe
        print("virhe: %s" % e, file=sys.stderr)
        sys.exit(2)
