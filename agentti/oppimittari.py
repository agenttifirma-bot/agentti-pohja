"""Oppimisen mittari (Tonyn p\u00e4\u00e4t\u00f6s 4.11.2026, kompassi "Jatkuva oppiminen"): toistuvatko samat virheet?

Lukee vain virheloki.md:n (siin\u00e4 ovat my\u00f6s riippumattoman tarkastajan kirjaamat l\u00f6yd\u00f6kset, merkint\u00e4 "(tarkastaja ...)").
Jokaisesta merkinn\u00e4st\u00e4 otetaan juurisyyteksti (rivin "Syy:"-osa tai otsikkomerkinn\u00e4n "Miksi:"-rivi) ja se luokitellaan:
  1. jos merkinn\u00e4ss\u00e4 on tunniste `[juurisyy: nimi]`, k\u00e4ytet\u00e4\u00e4n sit\u00e4 (suositeltu uusille merkinn\u00f6ille);
  2. muuten JUURISYYT-taulukon ensimm\u00e4inen s\u00e4\u00e4nt\u00f6, joka osuu juurisyytekstiin;
  3. muuten merkint\u00e4 j\u00e4\u00e4 luokittelematta eik\u00e4 voi olla toisto.
Toisto = merkinn\u00e4n luokka on esiintynyt jo aiemmassa merkinn\u00e4ss\u00e4 (my\u00f6s ennen mittausviikkoa).
Luokittelu on karkea s\u00e4\u00e4nt\u00f6pohjainen arvio, ei LLM-kutsu. Ei verkkoa, ei kirjoitusta, vain stdlib.

K\u00e4ytt\u00f6: python3 -m agentti.oppimittari [VIRHELOKI.md]   (tulostaa mittaririvin)"""
import re
import sys
from datetime import date, datetime, timedelta, timezone

# Juurisyyluokat. Saannot ovat tarkoituksella vahaiset: lisaa uusi vasta kun sama syy on nahty kahdesti.
JUURISYYT = (
    ("aikapommi", re.compile(r"(?i)aikapomm|kiinte[a\u00e4]\w* p[a\u00e4]iv|oikeaa kelloa")),
    ("ei_todennettu", re.compile(r"(?i)ei katsottu|ajettiin vain k[a\u00e4]sin|vain keinotekoisia|ei todennettu|vain claudejono-testit|ei koko ci")),
    ("muistista", re.compile(r"(?i)muistikuva|muistista|tarkistamatta|ei riippumatonta|lukua ei sidottu")),
    ("ymparisto", re.compile(r"(?i)pilvi-istunto|cronin|crlf|ty[o\u00f6]puu|taustaty[o\u00f6]")),
)
TUNNISTE_RE = re.compile(r"\[juurisyy:\s*([a-z0-9_]+)\s*\]")
RIVI_RE = re.compile(r"^- (\d{4})-(\d{2})-(\d{2})\b(.*)$")
OTSIKKO_RE = re.compile(r"^##\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
SYY_RE = re.compile(r"Syy:\s*(.*?)(?:\s*S[a\u00e4]\u00e4nt\u00f6:|$)")
MIKSI_RE = re.compile(r"^- (?:Miksi|Syy):\s*(.*)$")


def jasenna(teksti):
    """Palauttaa listan merkint\u00f6j\u00e4 j\u00e4rjestyksess\u00e4: {paiva: date, syy: str|None, luokka: str|None, tarkastaja: bool}."""
    ulos, blokki = [], None
    for rivi in teksti.splitlines():
        m = RIVI_RE.match(rivi)
        if m:
            blokki = None
            try:
                pv = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            s = SYY_RE.search(rivi)
            ulos.append(_merkinta(pv, s.group(1) if s else None, rivi))
            continue
        h = OTSIKKO_RE.match(rivi)
        if h:
            try:
                otsikko_pv = date(int(h.group(3)), int(h.group(2)), int(h.group(1)))
            except ValueError:
                otsikko_pv = None
            blokki = None
            if otsikko_pv:
                blokki = {"pv": otsikko_pv, "rivit": [rivi]}
                ulos.append(blokki)     # rivit taydentyvat alla
            continue
        if blokki is not None:
            blokki["rivit"].append(rivi)
    return [_viimeistele(x) for x in ulos]


def _merkinta(pv, syy, rivi):
    return {"paiva": pv, "syy": syy, "teksti": rivi}


def _viimeistele(x):
    if "rivit" in x:      # otsikkomerkinta: juurisyy on "Miksi:"-rivi
        syy = next((m.group(1) for r in x["rivit"] if (m := MIKSI_RE.match(r))), None)
        x = {"paiva": x["pv"], "syy": syy, "teksti": "\n".join(x["rivit"])}
    luokka = None
    t = TUNNISTE_RE.search(x["teksti"])
    if t:
        luokka = t.group(1)
    elif x["syy"]:
        luokka = next((nimi for nimi, re_ in JUURISYYT if re_.search(x["syy"])), None)
    return {"paiva": x["paiva"], "syy": x["syy"], "luokka": luokka, "tarkastaja": "(tarkastaja" in x["teksti"][:80]}


def laske(merkinnat, alku, loppu):
    """Merkinn\u00e4t v\u00e4lill\u00e4 (alku, loppu]; toisto = luokka n\u00e4hty aiemmassa merkinn\u00e4ss\u00e4 (listaj\u00e4rjestys, my\u00f6s ennen ikkunaa)."""
    nahty, n, toistot, luokittelematta, tark = set(), 0, {}, 0, 0
    for m in merkinnat:
        ikkunassa = alku < m["paiva"] <= loppu
        if ikkunassa:
            n += 1
            tark += 1 if m["tarkastaja"] else 0
            if m["luokka"] is None:
                luokittelematta += 1
            elif m["luokka"] in nahty:
                toistot[m["luokka"]] = toistot.get(m["luokka"], 0) + 1
        if m["luokka"] is not None:
            nahty.add(m["luokka"])
    return {"n": n, "toistoja": sum(toistot.values()), "luokat": toistot, "luokittelematta": luokittelematta, "tarkastajan": tark}


def mittari(teksti, nyt):
    """Kuluneen 7 vrk:n ja sit\u00e4 edellisen viikon luvut. `nyt`: date (injektoitu kello)."""
    mm = jasenna(teksti)
    return {"nyt": laske(mm, nyt - timedelta(days=7), nyt), "ed": laske(mm, nyt - timedelta(days=14), nyt - timedelta(days=7))}


def suunta(nyt_, ed):
    """Toistojen osuus merkinn\u00f6ist\u00e4 t\u00e4ll\u00e4 viikolla vs edellisell\u00e4. Jos jommallakummalla viikolla ei ole merkint\u00f6j\u00e4, osuuksia ei vertailla."""
    if nyt_["n"] == 0 or ed["n"] == 0:
        return "data ei riit\u00e4 (viikolta puuttuu merkint\u00f6j\u00e4)"
    a, b = nyt_["toistoja"] / nyt_["n"], ed["toistoja"] / ed["n"]
    if a < b:
        return "parempi"
    return "huonompi" if a > b else "ei muutosta"


def rivi(teksti, nyt):
    """Yksi rivi viikkokoosteeseen. Tyhj\u00e4/puuttuva virheloki antaa rehellisen 'ei dataa' -rivin."""
    if teksti is None:
        return "Oppiminen: virhelokia ei saatu luettua."
    v = mittari(teksti, nyt)
    a, e = v["nyt"], v["ed"]
    osat = ["Oppiminen: viikon virhelokimerkinn\u00e4t %d, toistoja %d" % (a["n"], a["toistoja"])]
    if a["luokat"]:
        osat[0] += " (" + ", ".join("%s x%d" % (k, c) for k, c in sorted(a["luokat"].items(), key=lambda p: -p[1])[:3]) + ")"
    if a["tarkastajan"]:
        osat.append("niist\u00e4 tarkastajan kirjaamia %d" % a["tarkastajan"])
    osat.append("edellinen viikko %d/%d" % (e["toistoja"], e["n"]))
    osat.append("suunta: " + suunta(a, e))
    if a["luokittelematta"]:
        osat.append("luokittelematta %d" % a["luokittelematta"])
    return "; ".join(osat) + "."


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("kaytto: python3 -m agentti.oppimittari VIRHELOKI.md", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as f:
            teksti = f.read()
    except OSError as e:
        print("oppimittari: luku ep\u00e4onnistui (%s)" % type(e).__name__, file=sys.stderr)
        return 2
    print(rivi(teksti, datetime.now(timezone.utc).date()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
