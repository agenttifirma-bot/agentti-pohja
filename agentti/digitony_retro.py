"""Digi-Tony, takautuva testi: piilota vanhoja paatoksia muistista ja anna varjotilan arvata ne.

Kaytto: python3 -m agentti.digitony_retro PAATOKSET.jsonl [--n 20] [--siemen 1] [--kaikki]

Oletus: piilotetaan --n paatosta (tasaisesti luokkien yli, rahapaatokset mukaan lukien) ja
arvataan ne jaljelle jaavalla muistilla. --kaikki ajaa lisaksi "yksi pois kerrallaan" -testin
koko muistille. Vaihtoehtojen jarjestys sekoitetaan (kiintea siemen), jotta jarjestys ei
vihjaa vastausta. Perustason vertailut: "aina ensimmainen" (sekoitetussa jarjestyksessa) ja
kylla/ei-kysymyksissa "aina kylla".
"""

import argparse
import random
import sys

from agentti import digitony as d


def valitse_piilotettavat(muisti, n):
    """Tasainen otos luokittain (kiintea jarjestys, ei satunnaisuutta): kierretaan luokat ja otetaan joka toinen."""
    luokittain = {}
    for i, m in enumerate(muisti):
        luokittain.setdefault(d.luokka_avain(m["luokka"]), []).append(i)
    valitut = []
    jonot = {k: v[1::2] or v[:1] for k, v in sorted(luokittain.items())}
    while len(valitut) < n and any(jonot.values()):
        for k in sorted(jonot):
            if jonot[k] and len(valitut) < n:
                valitut.append(jonot[k].pop(0))
    return sorted(valitut)


def aja(muisti, piilotetut, siemen=1):
    """Arvaa piilotetut jaljelle jaavalla muistilla. Palauttaa rivit (paatos, arvaus, jarjestetyt vaihtoehdot)."""
    rng = random.Random(siemen)
    pois = set(piilotetut)
    jaljella = [m for i, m in enumerate(muisti) if i not in pois]
    indeksi = d._Indeksi(jaljella)
    ulos = []
    for i in piilotetut:
        m = muisti[i]
        vaih = list(m["vaihtoehdot"])
        rng.shuffle(vaih)
        a = d.arvaa(m["kysymys"], vaih, jaljella, luokka=m["luokka"], indeksi=indeksi)
        ulos.append((m, a, vaih))
    return ulos


def tiivista(tulokset):
    """Luokittain ja yhteensa: n, arvattu, osumia, en_tieda, tonylle + perustasot."""
    luokat = {}
    for m, a, vaih in tulokset:
        k = luokat.setdefault(d.luokka_avain(m["luokka"]), {"n": 0, "arvattu": 0, "osumia": 0, "en_tieda": 0,
                                                            "tonylle": 0, "perus_ensimmainen": 0,
                                                            "yn_n": 0, "yn_kylla": 0})
        k["n"] += 1
        if a.tila == "arvaus":
            k["arvattu"] += 1
            k["osumia"] += 1 if a.valittu == m["valittu"] else 0
        elif a.tila == "en_tieda":
            k["en_tieda"] += 1
        else:
            k["tonylle"] += 1
        if a.tila != "tonylle":
            k["perus_ensimmainen"] += 1 if vaih[0] == m["valittu"] else 0
            if {d._kanoninen(v) for v in vaih} == {"kylla", "ei"}:
                k["yn_n"] += 1
                k["yn_kylla"] += 1 if d._kanoninen(m["valittu"]) == "kylla" else 0
    return luokat


def _summa(luokat):
    yht = {}
    for k in luokat.values():
        for avain, arvo in k.items():
            yht[avain] = yht.get(avain, 0) + arvo
    return yht


def tulosta(otsikko, luokat, ulos=sys.stdout):
    ulos.write("%s\n" % otsikko)
    ulos.write("%-12s %3s %8s %7s %9s %8s\n" % ("luokka", "n", "arvattu", "osumia", "en_tieda", "tonylle"))
    for nimi in sorted(luokat) + ["YHTEENSA"]:
        k = luokat[nimi] if nimi != "YHTEENSA" else _summa(luokat)
        pros = ("%d %%" % round(100.0 * k["osumia"] / k["arvattu"])) if k["arvattu"] else "-"
        ulos.write("%-12s %3d %8d %7d %9d %8d  osuma/arvattu %s\n"
                   % (nimi, k["n"], k["arvattu"], k["osumia"], k["en_tieda"], k["tonylle"], pros))
    y = _summa(luokat)
    ei_raha = y["n"] - y["tonylle"]
    ulos.write("Kattavuus (arvattu / ei-raha): %d/%d. Perustaso 'aina ensimmainen': %d/%d. "
               "Kylla/ei-kysymyksissa 'aina kylla': %d/%d.\n"
               % (y["arvattu"], ei_raha, y["perus_ensimmainen"], ei_raha, y["yn_kylla"], y["yn_n"]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("muisti")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--siemen", type=int, default=1)
    p.add_argument("--kaikki", action="store_true", help="aja myos yksi pois kerrallaan koko muistille")
    a = p.parse_args(argv)
    muisti = d.lataa_muisti(a.muisti)
    piilo = valitse_piilotettavat(muisti, a.n)
    print("Muisti: %d paatosta, piilotettu %d: %s" % (len(muisti), len(piilo), ", ".join(muisti[i]["id"] for i in piilo)))
    tulosta("== Piilotettu otos ==", tiivista(aja(muisti, piilo, a.siemen)))
    if a.kaikki:
        kaikki = []
        for i in range(len(muisti)):
            kaikki.extend(aja(muisti, [i], a.siemen))
        tulosta("== Yksi pois kerrallaan (kaikki) ==", tiivista(kaikki))
    return 0


if __name__ == "__main__":
    sys.exit(main())
