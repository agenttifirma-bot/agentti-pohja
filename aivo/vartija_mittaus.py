"""Vuotovartijan mekaanisen tarkistuksen mittaus synteettista aineistoa vastaan (aivo/vartija_aineisto.py).

Ei verkkoa eika mallikutsuja: vain vartija.mekaaninen(). Vartija ei muuta tekstia, eika mittaus muuta sita.

Laskenta:
  * osuma: totuuden elementti, jonka kanssa jokin vartijan merkinta menee paallekkain ja merkinnan ryhma on sama;
  * ohitus: totuuden elementti ilman samanryhmaista paallekkaista merkintaa;
  * vaara halytys: vartijan merkinta, joka ei mene paallekkain minkaan totuuden elementin kanssa;
  * ristiosuma: merkinta osuu elementtiin, mutta ryhma on eri (ei osuma eika vaara halytys, raportoidaan erikseen).

Kaytto: python3 -m aivo.vartija_mittaus [--aineisto HAKEMISTO | --siemen N] [--nimet T] [--avainsanat T] [--json]"""
import argparse
import json
import sys
from collections import OrderedDict

from aivo import vartija, vartija_aineisto

# Vartijan syy -> ryhma. Nimilistan ja avainsanalistan osumat tunnistetaan etuliitteesta.
SYY_RYHMA = {
    "s\u00e4hk\u00f6postiosoite": "sahkoposti",
    "puhelinnumero": "puhelin",
    "IP-osoite": "ip",
    "tailnet-nimi": "tailnet",
    "henkil\u00f6tunnus": "hetu",
    "tilinumero": "iban",
    "SSH-yksityisavain": "avain",
    "SSH-julkisavain": "avain",
    "API-avain": "avain",
    "avain avainsanan j\u00e4lkeen": "avain",
}
# Vartijan syy -> rivi, jolle vaara halytys kirjataan.
SYY_RIVI = {
    "SSH-yksityisavain": "ssh-yksityisavain",
    "SSH-julkisavain": "ssh-julkisavain",
    "API-avain": "api-avain",
    "avain avainsanan j\u00e4lkeen": "avainsana-arvo",
}
TYYPPI_RYHMA = {
    "sahkoposti": "sahkoposti", "ip": "ip", "hetu": "hetu", "iban": "iban",
    "ssh-yksityisavain": "avain", "ssh-julkisavain": "avain", "api-avain": "avain", "avainsana-arvo": "avain",
    "nimi": "nimi", "paikka": "paikka",
}


def syyn_ryhma(syy):
    if syy.startswith("nimi nimilistalta"):
        return "nimi"
    if syy.startswith("avainsana:"):
        return "paikka"
    return SYY_RYHMA.get(syy, "muu")


def syyn_rivi(syy):
    if syy in SYY_RIVI:
        return SYY_RIVI[syy]
    return syyn_ryhma(syy)


def _paallekkain(a, b):
    return a["alku"] < b["loppu"] and b["alku"] < a["loppu"]


def mittaa(aineisto, nimet=(), avainsanat=()):
    """Palauttaa sanakirjan: rivit (tyyppi -> osumat, ohitukset, vaarat), muodot, ristiosumat, tekstitason luvut
    ja ohitettujen/vaarien halytysten esimerkit (tunnus, tyyppi, kohta)."""
    rivit = OrderedDict((t, {"osumat": 0, "ohitukset": 0, "vaarat": 0, "vaarat_erilaiset": 0})
                        for t in vartija_aineisto.TYYPIT)
    erilaiset = {}
    muodot = OrderedDict()
    ristiosumat = 0
    turvalliset_halyttivat = 0
    kaikki_loytyi = 0
    arkaluonteisia = 0
    ohitetut, vaarat = [], []
    for t in aineisto:
        merkinnat = vartija.mekaaninen(t["teksti"], nimet=nimet, avainsanat=avainsanat)
        elementit = t["elementit"]
        loytyi_kaikki = True
        for e in elementit:
            ryhma = TYYPPI_RYHMA[e["tyyppi"]]
            osui = any(_paallekkain(e, m) and syyn_ryhma(m["syy"]) == ryhma for m in merkinnat)
            avain = "%s / %s" % (e["tyyppi"], e["muoto"])
            mu = muodot.setdefault(avain, {"osumat": 0, "ohitukset": 0})
            if osui:
                rivit[e["tyyppi"]]["osumat"] += 1
                mu["osumat"] += 1
            else:
                rivit[e["tyyppi"]]["ohitukset"] += 1
                mu["ohitukset"] += 1
                loytyi_kaikki = False
                ohitetut.append({"tunnus": t["tunnus"], "tyyppi": avain, "kohta": e["kohta"][:60]})
        for m in merkinnat:
            osuvat = [e for e in elementit if _paallekkain(e, m)]
            if not osuvat:
                rivi = syyn_rivi(m["syy"])
                rivit.setdefault(rivi, {"osumat": 0, "ohitukset": 0, "vaarat": 0, "vaarat_erilaiset": 0})["vaarat"] += 1
                erilaiset.setdefault(rivi, set()).add(m["kohta"])
                vaarat.append({"tunnus": t["tunnus"], "tyyppi": rivi, "kohta": m["kohta"][:60]})
            elif not any(TYYPPI_RYHMA[e["tyyppi"]] == syyn_ryhma(m["syy"]) for e in osuvat):
                ristiosumat += 1
        if t["luokka"] == vartija_aineisto.TURVALLINEN:
            turvalliset_halyttivat += bool(merkinnat)
        elif elementit:
            arkaluonteisia += 1
            kaikki_loytyi += loytyi_kaikki
    for rivi, kohdat in erilaiset.items():
        rivit[rivi]["vaarat_erilaiset"] = len(kohdat)
    return {
        "tekstit": len(aineisto),
        "rivit": rivit,
        "muodot": muodot,
        "ristiosumat": ristiosumat,
        "turvallisia": sum(1 for t in aineisto if t["luokka"] == vartija_aineisto.TURVALLINEN),
        "turvalliset_halyttivat": turvalliset_halyttivat,
        "arkaluonteisia": arkaluonteisia,
        "arkaluonteiset_kaikki_loytyi": kaikki_loytyi,
        "ohitetut": ohitetut,
        "vaarat": vaarat,
    }


def taulukko(tulos):
    """Markdown-taulukot: tyypeittain ja muodoittain seka tekstitason luvut."""
    r = ["| Tyyppi | Osumat | Ohitukset | V\u00e4\u00e4r\u00e4t h\u00e4lytykset | Eri kohtia |", "|---|---:|---:|---:|---:|"]
    yht = [0, 0, 0, 0]
    for tyyppi, v in tulos["rivit"].items():
        luvut = (v["osumat"], v["ohitukset"], v["vaarat"], v["vaarat_erilaiset"])
        r.append("| %s | %d | %d | %d | %d |" % ((tyyppi,) + luvut))
        yht = [a + b for a, b in zip(yht, luvut)]
    r.append("| **yhteens\u00e4** | %d | %d | %d | %d |" % tuple(yht))
    r += ["", "| Tyyppi / muoto | Osumat | Ohitukset |", "|---|---:|---:|"]
    for avain, v in tulos["muodot"].items():
        r.append("| %s | %d | %d |" % (avain, v["osumat"], v["ohitukset"]))
    r += ["",
          "Tekstej\u00e4 %d. Turvallisista %d/%d sai v\u00e4hint\u00e4\u00e4n yhden h\u00e4lytyksen. "
          "Arkaluonteisista ja vaikeista %d/%d l\u00f6ytyi kokonaan. Ristiosumia %d."
          % (tulos["tekstit"], tulos["turvalliset_halyttivat"], tulos["turvallisia"],
             tulos["arkaluonteiset_kaikki_loytyi"], tulos["arkaluonteisia"], tulos["ristiosumat"])]
    return "\n".join(r)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vuotovartijan mekaanisen tarkistuksen mittaus (ei verkkoa, ei mallia).")
    ap.add_argument("--aineisto", help="vartija_aineisto.py:n kirjoittama hakemisto (oletus: generoidaan muistissa)")
    ap.add_argument("--siemen", type=int, default=vartija_aineisto.SIEMEN)
    ap.add_argument("--nimet", help="nimilista (rivi per nimi), kuten luovutukset/vartija/nimet.txt")
    ap.add_argument("--avainsanat", help="avainsanalista (rivi per sana)")
    ap.add_argument("--json", action="store_true", help="tulosta koko tulos JSONina")
    ap.add_argument("--esimerkit", action="store_true", help="listaa ohitukset ja vaarat halytykset")
    a = ap.parse_args(argv)
    aineisto = vartija_aineisto.lue(a.aineisto) if a.aineisto else vartija_aineisto.generoi(a.siemen)
    tulos = mittaa(aineisto, nimet=vartija.lue_lista(a.nimet), avainsanat=vartija.lue_lista(a.avainsanat))
    if a.json:
        print(json.dumps(tulos, ensure_ascii=False, indent=1))
        return 0
    print(taulukko(tulos))
    if a.esimerkit:
        print("\nOhitukset:")
        for o in tulos["ohitetut"]:
            print("- %s %s: %s" % (o["tunnus"], o["tyyppi"], json.dumps(o["kohta"], ensure_ascii=False)))
        print("\nV\u00e4\u00e4r\u00e4t h\u00e4lytykset:")
        for o in tulos["vaarat"]:
            print("- %s %s: %s" % (o["tunnus"], o["tyyppi"], json.dumps(o["kohta"], ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
