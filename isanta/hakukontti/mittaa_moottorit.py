"""Hakukontin moottorimittaus: kuinka usein kukin SearXNG-moottori estaa Tor-liikenteen tai palauttaa liian vahan tuloksia.

Ajetaan hakukontissa kayttajana aivo-haku (nftables sallii sille vain silmukkaosoitteen portit 8888 ja 9050):
  setpriv --reuid=aivo-haku --regid=aivo-haku --init-groups python3 -I /usr/local/lib/hakukontti/mittaa_moottorit.py

Jokainen moottori kysytaan erikseen (`engines=<nimi>`) neutraaleilla, kiinteilla testilausekkeilla. Tulos luokitellaan:
  ok      vahintaan 3 tulosta
  vahan   1-2 tulosta
  tyhja   0 tulosta ilman virhetta
  esto    moottori on vastaamattomissa estoon viittaavalla syylla (CAPTCHA, 403, 429, access denied, suspended ...)
  virhe   muu vastaamattomuus, aikakatko tai SearXNG:n HTTP-virhe

Suunnitelman (kohta 3.2) VPN-mittari: jos yli 30 % hauista palauttaa alle 3 tulosta, Tony harkitsee varareittia.
Siksi tuloste nayttaa moottorikohtaisesti seka estoprosentin etta alle 3 tuloksen osuuden.

Vain stdlib, ei ulkoisia riippuvuuksia. Skripti ei tallenna mitaan (tulos tulostetaan; --json kirjoittaa tiedoston).
Paluukoodi: 0 = mittaus tehty, 2 = SearXNG ei vastannut yhteenkaan kyselyyn, 1 = virheellinen kaytto.
"""
import argparse
import json
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OLETUS_OSOITE = "http://127.0.0.1:8888"
OLETUS_MOOTTORIT = ("duckduckgo", "brave", "mojeek", "wikipedia", "wikidata", "bing")
# Neutraalit, yleiset lausekkeet: eivat kerro kenestakaan mitaan.
TESTILAUSEKKEET = (
    "photosynthesis",
    "python list comprehension",
    "linux file permissions",
    "history of the printing press",
    "tcp three way handshake",
    "boiling point of water",
    "how do vaccines work",
    "prime number definition",
    "baltic sea",
    "binary search algorithm",
    "sourdough bread recipe",
    "solar system planets",
)
ESTO_RE = re.compile(r"captcha|access denied|forbidden|too many requests|suspend|blocked|\b403\b|\b429\b", re.IGNORECASE)
LUOKAT = ("ok", "vahan", "tyhja", "esto", "virhe")
VASTAUS_MAX = 4 * 1024 * 1024


def luokittele(vastaus, moottori):
    """Yhden kyselyn tulos: (luokka, tulosten maara). `vastaus` on SearXNG:n JSON-sanakirja."""
    tulokset = [t for t in vastaus.get("results") or [] if isinstance(t, dict)
                and (t.get("engine") == moottori or moottori in (t.get("engines") or []))]
    maara = len(tulokset)
    if maara >= 3:
        return "ok", maara
    if maara > 0:
        return "vahan", maara
    for rivi in vastaus.get("unresponsive_engines") or []:
        if isinstance(rivi, (list, tuple)) and rivi and rivi[0] == moottori:
            syy = " ".join(str(x) for x in rivi[1:])
            return ("esto" if ESTO_RE.search(syy) else "virhe"), 0
    return "tyhja", 0


def kysy(osoite, lauseke, moottori, aikaraja, avaa=urllib.request.urlopen):
    """Palauttaa (luokka, tulosten maara, kesto sekunteina, http_ok)."""
    kysely = urllib.parse.urlencode({"q": lauseke, "format": "json", "engines": moottori})
    alku = time.monotonic()
    try:
        with avaa(osoite.rstrip("/") + "/search?" + kysely, timeout=aikaraja) as v:
            raaka = v.read(VASTAUS_MAX + 1)
        if len(raaka) > VASTAUS_MAX:
            return "virhe", 0, time.monotonic() - alku, True
        vastaus = json.loads(raaka.decode("utf-8"))
    except urllib.error.HTTPError:
        return "virhe", 0, time.monotonic() - alku, False
    except (urllib.error.URLError, OSError, ValueError):
        return "virhe", 0, time.monotonic() - alku, False
    if not isinstance(vastaus, dict):
        return "virhe", 0, time.monotonic() - alku, True
    luokka, maara = luokittele(vastaus, moottori)
    return luokka, maara, time.monotonic() - alku, True


def yhteenveto(rivit):
    """rivit: lista (moottori, luokka, maara, kesto). Palauttaa moottorikohtaisen yhteenvedon."""
    tulos = {}
    for moottori, luokka, _maara, kesto in rivit:
        m = tulos.setdefault(moottori, {"kyselyja": 0, "kestot": [], **{k: 0 for k in LUOKAT}})
        m["kyselyja"] += 1
        m[luokka] += 1
        m["kestot"].append(kesto)
    for m in tulos.values():
        n = m["kyselyja"]
        m["esto_pros"] = round(100.0 * m["esto"] / n, 1)
        m["alle3_pros"] = round(100.0 * (n - m["ok"]) / n, 1)
        m["mediaani_s"] = round(statistics.median(m.pop("kestot")), 1)
    return tulos


def tulosta(tulos, ulos=None):
    ulos = ulos or sys.stdout
    otsikko = "%-12s %5s %4s %5s %5s %5s %5s %7s %8s %7s" % (
        "moottori", "n", "ok", "vahan", "tyhja", "esto", "virhe", "esto%", "alle3%", "med_s")
    print(otsikko, file=ulos)
    for nimi in sorted(tulos):
        m = tulos[nimi]
        print("%-12s %5d %4d %5d %5d %5d %5d %7.1f %8.1f %7.1f" % (
            nimi, m["kyselyja"], m["ok"], m["vahan"], m["tyhja"], m["esto"], m["virhe"],
            m["esto_pros"], m["alle3_pros"], m["mediaani_s"]), file=ulos)


def mittaa(osoite, moottorit, kyselyja, vali_min, vali_max, aikaraja, avaa=urllib.request.urlopen,
           nuku=time.sleep, satunnainen=None):
    """Ajaa mittauksen. Palauttaa (yhteenveto, http_vastauksia)."""
    satunnainen = satunnainen or random.Random()
    lausekkeet = list(TESTILAUSEKKEET[:kyselyja])
    tyot = [(m, l) for m in moottorit for l in lausekkeet]
    satunnainen.shuffle(tyot)          # sekoitus: moottori ei saa perakkaisia kyselyja
    rivit, http_ok = [], 0
    for i, (moottori, lauseke) in enumerate(tyot):
        if i and vali_max > 0:
            nuku(satunnainen.uniform(vali_min, vali_max))
        luokka, maara, kesto, ok = kysy(osoite, lauseke, moottori, aikaraja, avaa=avaa)
        http_ok += 1 if ok else 0
        rivit.append((moottori, luokka, maara, kesto))
    return yhteenveto(rivit), http_ok


def jasenna(argv):
    p = argparse.ArgumentParser(description="SearXNG-moottorien esto- ja tulosmittaus Torin kautta")
    p.add_argument("--osoite", default=OLETUS_OSOITE, help="SearXNG:n osoite (oletus %(default)s)")
    p.add_argument("--moottorit", default=",".join(OLETUS_MOOTTORIT), help="pilkuin eroteltu lista")
    p.add_argument("--kyselyja", type=int, default=10, help="lausekkeita moottoria kohden (1-%d)" % len(TESTILAUSEKKEET))
    p.add_argument("--vali-min", type=float, default=3.0, help="kyselyjen valin alaraja sekunteina")
    p.add_argument("--vali-max", type=float, default=8.0, help="kyselyjen valin ylaraja sekunteina")
    p.add_argument("--aikaraja", type=float, default=60.0, help="yhden kyselyn aikaraja sekunteina")
    p.add_argument("--json", dest="json_polku", help="kirjoita yhteenveto myos JSON-tiedostoon")
    a = p.parse_args(argv)
    a.moottorit = [m.strip() for m in a.moottorit.split(",") if m.strip()]
    if not a.moottorit or any(not re.fullmatch(r"[a-z0-9_ ]{1,40}", m) for m in a.moottorit):
        p.error("--moottorit: vain pienia kirjaimia, numeroita, alaviivoja ja valilyonteja")
    if not 1 <= a.kyselyja <= len(TESTILAUSEKKEET):
        p.error("--kyselyja: 1-%d" % len(TESTILAUSEKKEET))
    if a.vali_min < 0 or a.vali_max < a.vali_min or a.aikaraja <= 0:
        p.error("valit ja aikaraja: 0 <= vali-min <= vali-max, aikaraja > 0")
    if not a.osoite.startswith(("http://127.0.0.1:", "http://localhost:")):
        p.error("--osoite: vain silmukkaosoite (SearXNG kuuntelee vain sita)")
    return a


def main(argv=None):
    a = jasenna(sys.argv[1:] if argv is None else argv)
    tulos, http_ok = mittaa(a.osoite, a.moottorit, a.kyselyja, a.vali_min, a.vali_max, a.aikaraja)
    tulosta(tulos)
    if a.json_polku:
        with open(a.json_polku, "w", encoding="utf-8") as f:
            json.dump({"moottorit": tulos, "kyselyja_moottoria_kohden": a.kyselyja}, f, indent=2, sort_keys=True)
    if http_ok == 0:
        print("mittaa_moottorit: SearXNG ei vastannut yhteenkaan kyselyyn", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
