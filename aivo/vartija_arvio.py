"""Arviointiajuri vartijamallin kehotteelle (aivo/vartija_kehote.py).

Tony ajaa kontissa, jossa llama-server kuuntelee loopbackissa:
    python3 -m aivo.vartija_arvio [--aineisto polku.json] [--url http://127.0.0.1:8081] [--kahdesti] [--tulos ulos.json]

Ajuri kutsuu vain loopback-osoitetta. Jos mallia ei ole kaynnissa (/health ei vastaa), ajuri kertoo sen ja lopettaa
paluukoodilla 2 kutsumatta mitaan muuta. Ei OpenRouteria, ei muuta verkkoa.

Aineisto: JSON-lista tai {"tekstit": [...]}; jokaisessa "id", "teksti" ja odotus kentassa "odotus" (tai "riski"):
"ei" | "pieni" | "suuri". Valitsimella --tyypeista odotus johdetaan totuustiedon listasta "tyypit" kaksiarvoisesti
(tyhja -> "ei", muuten "riski" = pieni tai suuri). Kohteet ilman odotusta lasketaan, mutta niita ei laheteta."""
import argparse
import json
import sys
from pathlib import Path

from aivo import vartija_kehote as vk
from aivo import yksityinen

OLETUS_AINEISTO = Path(__file__).resolve().parent / "testidata" / "vartija_kehote_arvio.json"
RISKI_BINAARI = "riski"          # --tyypeista: odotus on "jokin riski" (pieni tai suuri)
MAX_TEKSTEJA = 1_000


class AineistoVirhe(Exception):
    pass


def lue_aineisto(polku, tyypeista=False):
    try:
        d = json.loads(Path(polku).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AineistoVirhe("aineistoa ei voi lukea: %s" % type(e).__name__)
    kohteet = d.get("tekstit") if isinstance(d, dict) else d
    if not isinstance(kohteet, list) or not kohteet:
        raise AineistoVirhe("aineistossa ei ole tekstilistaa")
    if len(kohteet) > MAX_TEKSTEJA:
        raise AineistoVirhe("aineistossa on yli %d teksti\u00e4" % MAX_TEKSTEJA)
    tulos, ilman = [], 0
    for i, k in enumerate(kohteet):
        if not isinstance(k, dict) or not isinstance(k.get("teksti"), str):
            raise AineistoVirhe("kohde %d: teksti puuttuu" % i)
        odotus = k.get("odotus", k.get("riski"))
        if odotus is None and tyypeista and isinstance(k.get("tyypit"), list):
            odotus = RISKI_BINAARI if k["tyypit"] else "ei"
        if odotus is None:
            ilman += 1
            continue
        if odotus not in vk.RISKIT and odotus != RISKI_BINAARI:
            raise AineistoVirhe("kohde %d: tuntematon odotus" % i)
        tulos.append({"id": str(k.get("id", i)), "teksti": k["teksti"], "odotus": odotus})
    return tulos, ilman


def _osuu(odotus, riski):
    if odotus == RISKI_BINAARI:
        return riski in ("pieni", "suuri")
    return riski == odotus


def laske(rivit):
    """rivit: [{"id", "odotus", "tulos": {...}, "toinen": {...} | None}] -> yhteenveto."""
    s = {"tekstit": len(rivit), "tarkistettu": 0, "ei-tarkistanut": 0, "osui": 0,
         "riski_tunnistettu": 0, "riski_odotettu": 0, "vaaranegatiivinen_suuri": 0,
         "vaara_halytys": 0, "puhtaita": 0, "erimielisia": 0,
         "sekaannus": {}}
    for r in rivit:
        t, o = r["tulos"], r["odotus"]
        if o != "ei":
            s["riski_odotettu"] += 1
        else:
            s["puhtaita"] += 1
        if t["tila"] != vk.TILA_TARKISTETTU:
            s["ei-tarkistanut"] += 1
            continue
        s["tarkistettu"] += 1
        riski = t["riski"]
        avain = "%s->%s" % (o, riski)
        s["sekaannus"][avain] = s["sekaannus"].get(avain, 0) + 1
        if _osuu(o, riski):
            s["osui"] += 1
        if o != "ei" and riski != "ei":
            s["riski_tunnistettu"] += 1
        if o == "suuri" and riski == "ei":
            s["vaaranegatiivinen_suuri"] += 1
        if o == "ei" and riski != "ei":
            s["vaara_halytys"] += 1
        toinen = r.get("toinen")
        if toinen is not None and (toinen["tila"] != vk.TILA_TARKISTETTU or toinen["riski"] != riski):
            s["erimielisia"] += 1
    s["osuvuus"] = round(s["osui"] / s["tekstit"], 3) if s["tekstit"] else 0.0
    return s


def aja(kohteet, url, kahdesti=False, arvioi=vk.arvioi):
    rivit = []
    for k in kohteet:
        rivi = {"id": k["id"], "odotus": k["odotus"], "tulos": arvioi(k["teksti"], url=url), "toinen": None}
        if kahdesti:
            rivi["toinen"] = arvioi(k["teksti"], url=url, kaanteinen=True)
        rivit.append(rivi)
    return rivit


def main(argv=None, kaynnissa=vk.malli_kaynnissa, arvioi=vk.arvioi):
    ap = argparse.ArgumentParser(prog="aivo.vartija_arvio")
    ap.add_argument("--aineisto", default=str(OLETUS_AINEISTO))
    ap.add_argument("--url", default=yksityinen.OLETUS_MALLI_URL)
    ap.add_argument("--kahdesti", action="store_true", help="toinen ajo k\u00e4\u00e4nnetyll\u00e4 esimerkkij\u00e4rjestyksell\u00e4")
    ap.add_argument("--tyypeista", action="store_true", help="odotus totuustiedon tyypit-listasta (kaksiarvoinen)")
    ap.add_argument("--tulos", help="kirjoita rivit ja yhteenveto JSON-tiedostoon")
    a = ap.parse_args(argv)
    if not yksityinen.sallittu_malli_osoite(a.url):
        print("virhe: osoite ei ole http + loopback-IP; mit\u00e4\u00e4n ei kutsuttu", file=sys.stderr)
        return 1
    try:
        kohteet, ilman = lue_aineisto(a.aineisto, a.tyypeista)
    except AineistoVirhe as e:
        print("virhe:", e, file=sys.stderr)
        return 1
    if not kaynnissa(a.url):
        print("Mallia ei ole k\u00e4ynniss\u00e4 osoitteessa %s (/health ei vastaa). Mit\u00e4\u00e4n ei kutsuttu." % a.url)
        return 2
    rivit = aja(kohteet, a.url, a.kahdesti, arvioi)
    s = laske(rivit)
    s["ilman_odotusta"] = ilman
    for r in rivit:
        t = r["tulos"]
        print("%-12s odotus=%-6s tila=%-14s riski=%-6s %s" % (r["id"], r["odotus"], t["tila"], t["riski"] or "-", t["syy"]))
    print(json.dumps(s, ensure_ascii=False, indent=1))
    if a.tulos:
        Path(a.tulos).write_text(json.dumps({"yhteenveto": s, "rivit": rivit}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
