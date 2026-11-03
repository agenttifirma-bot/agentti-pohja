"""Tonyn varaus Claude-tilauksesta ja kayttorajapysaytys (Tonyn paatos 3.11.2026).

Claude-tilauksen viikkoraja on yhteinen Tonyn kanssa. Agenttien osuus on enintaan AGENTTIOSUUS_OLETUS (60 %); Tony muuttaa sen
yhdesta asetuksesta CLAUDEJONO_AGENTTIOSUUS (prosentti, 1-100). Tilauksen prosenttia ei voi lukea koneellisesti, joten:
  1. Tony ajaa 2-3 kertaa viikossa `python3 -m claudejono.kulutus kalibroi <asetussivun %>`.
  2. Kalibrointien valisesta agenttien kulutuksesta (usd, kulutus.jsonl) lasketaan kerroin "prosenttia per usd".
     Tonyn oma kaytto kuuluu samaan prosenttilukuun, joten jokainen kalibrointivali antaa kertoimelle YLARAJAN; kaytetaan
     pienin (tiukin) ylaraja. Arvio on siis konservatiivinen: se ylittaa agenttien todellisen osuuden, ei alita sita.
  3. Arvio = kerroin * agenttien viikon usd. Taso: normaali | hidastettu (>= 80 % rajasta: vain kaista 1) | pysaytetty (>= raja).
  4. Ilman kalibrointia arviota ei voi laskea: taso `ei_kalibroitu` (ei rajoiteta) ja aamukooste pyytaa lukua.
Kayttorajavirhe (rate limit) pysayttaa Clauden kaikki kaistat heti RATE_LIMIT_TAUKO_S ajaksi. Tehtavalle ei kirjata tulosta
(se ei kulu), eika sita yriteta uudelleen ennen taukoa -> ei silmukkaa. OpenRouter-reitti ei kuulu pysaytyksiin.
Tilatiedostot: <tila>/rate-limit.json, <tila>/varaus-tila.json (viimeksi ilmoitettu taso)."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import kulutus

AGENTTIOSUUS_OLETUS = 60.0
HIDASTUS_ALKAA = 0.8            # osuus rajasta, josta alkaen vain kaista 1 ajaa
KALIBROINTI_VANHENEE_S = 3 * 86400
VALI_MIN_USD = 1.0              # alle taman agenttien kulutuksella kalibrointivali on liian kohinainen
VALI_MIN_PROSENTTI = 1.0        # asetussivun luku on kokonaisluku: 0 % muutos ei kerro mitaan
RATE_LIMIT_TAUKO_S = 3600
RATE_LIMIT_RE = re.compile(r"(?i)(usage limit|rate[ _-]?limit|limit reached|hit your limit|too many requests|\b429\b)")


def agenttiosuus(env):
    try:
        arvo = float(str(env.get("CLAUDEJONO_AGENTTIOSUUS", "")).replace(",", ".").replace("%", ""))
    except ValueError:
        return AGENTTIOSUUS_OLETUS
    return arvo if 1 <= arvo <= 100 else AGENTTIOSUUS_OLETUS


def on_rate_limit(d, stdout="", stderr=""):
    """Tunnistaa Clauden kayttorajavirheen: api_error_status 429 tai tunnusomainen ilmaus tuloksessa/virhetulosteessa.
    Ilmaukset ovat arvauksia (oikeaa rajaa ei ole osuttu); 429-kentta on varmempi."""
    if isinstance(d, dict):
        if d.get("api_error_status") == 429:
            return True
        if d.get("is_error") is True and isinstance(d.get("result"), str) and RATE_LIMIT_RE.search(d["result"][:500]):
            return True
        return False
    return bool(RATE_LIMIT_RE.search(str(stderr)[:1000] + " " + str(stdout)[:500]))


def aseta_rate_limit(tila, nyt_s=None, tauko_s=RATE_LIMIT_TAUKO_S):
    nyt_s = time.time() if nyt_s is None else nyt_s
    polku = Path(tila) / "rate-limit.json"
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text(json.dumps({"aika": nyt_s, "asti": nyt_s + tauko_s}), encoding="utf-8")


def rate_limit_asti(tila, nyt_s=None):
    """Aikaleima, johon asti Claude on pysaytetty, tai None."""
    nyt_s = time.time() if nyt_s is None else nyt_s
    try:
        asti = float(json.loads((Path(tila) / "rate-limit.json").read_text(encoding="utf-8")).get("asti", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return asti if asti > nyt_s else None


def kerroin(rivit, kalibroinnit, nyt):
    """(prosenttia per usd, laatu) tai (None, syy). laatu: 'vali' (>= 2 kalibrointia) | 'karkea' (yksi, olettaa nollauksen maanantaina)."""
    alku = kulutus.viikon_alku(nyt)
    claude = sorted((r for r in rivit if r.get("reitti") == "claude" and isinstance(r.get("usd"), (int, float))
                     and alku <= r["_aika"] <= nyt), key=lambda r: r["_aika"])
    kal = sorted((k for k in kalibroinnit if alku <= k["_aika"] <= nyt and isinstance(k.get("prosentti"), (int, float))),
                 key=lambda k: k["_aika"])
    if not kal:
        return None, "ei_kalibrointia"

    def usd_valilla(a, b):
        return sum(r["usd"] for r in claude if a < r["_aika"] <= b)

    ylarajat = []
    for a, b in zip(kal, kal[1:]):
        dp, du = b["prosentti"] - a["prosentti"], usd_valilla(a["_aika"], b["_aika"])
        if dp >= VALI_MIN_PROSENTTI and du >= VALI_MIN_USD:   # negatiivinen dp = viikon nollautuminen, ohitetaan
            ylarajat.append(dp / du)
    if ylarajat:
        return min(ylarajat), "vali"
    u = usd_valilla(alku, kal[0]["_aika"])
    if kal[0]["prosentti"] >= VALI_MIN_PROSENTTI and u >= VALI_MIN_USD:
        return kal[0]["prosentti"] / u, "karkea"
    return None, "data_ei_riita"


def arvio(tila, env, nyt):
    """Tila-sanakirja: taso, osuus_pros (arvio), raja_pros, kerroin, laatu, kalibroinnin_ika_s, usd_viikko."""
    rivit = kulutus.lue(tila)
    kal = kulutus.lue(tila, kulutus.KALIBROINTI_TIEDOSTO)
    raja = agenttiosuus(env)
    alku = kulutus.viikon_alku(nyt)
    usd_viikko = sum(r["usd"] for r in rivit if r.get("reitti") == "claude" and isinstance(r.get("usd"), (int, float))
                     and alku <= r["_aika"] <= nyt)
    k, laatu = kerroin(rivit, kal, nyt)
    viimeinen = max((x["_aika"] for x in kal), default=None)
    ika = (nyt - viimeinen).total_seconds() if viimeinen else None
    tulos = {"raja_pros": raja, "kerroin": k, "laatu": laatu, "usd_viikko": usd_viikko, "kalibroinnin_ika_s": ika, "osuus_pros": None}
    if k is None:
        tulos["taso"] = "ei_kalibroitu"
        return tulos
    osuus = k * usd_viikko
    tulos["osuus_pros"] = osuus
    tulos["taso"] = "pysaytetty" if osuus >= raja else "hidastettu" if osuus >= HIDASTUS_ALKAA * raja else "normaali"
    return tulos


def lupa(tila, env, nyt, kaista=1):
    """(saa_ajaa_claude, taso, syy). Rate limit ja varausraja koskevat vain Claude-reittia."""
    asti = rate_limit_asti(tila, nyt.timestamp())
    if asti:
        return False, "rate_limit", "Clauden kayttoraja tuli vastaan, tauko " + datetime.fromtimestamp(asti, kulutus.TZ).strftime("%H:%M") + " asti"
    a = arvio(tila, env, nyt)
    if a["taso"] == "pysaytetty":
        return False, "pysaytetty", (f"agenttien arvioitu osuus {a['osuus_pros']:.0f} % ylittaa rajan {a['raja_pros']:.0f} % "
                                     "(Tonyn varaus); jatkuu viikon vaihtuessa tai kun raja nostetaan")
    if a["taso"] == "hidastettu" and kaista > 1:
        return False, "hidastettu", f"agenttien arvioitu osuus {a['osuus_pros']:.0f} % lahestyy rajaa {a['raja_pros']:.0f} %: vain kaista 1 ajaa"
    return True, a["taso"], ""


def ilmoita_tason_muutos(tila, taso, syy, laheta):
    """Ilmoittaa Tonylle vain kun taso vaihtuu rajoittavaksi tai pois siita (ei joka 30 min ajossa). True jos viesti lahti."""
    polku = Path(tila) / "varaus-tila.json"
    try:
        vanha = json.loads(polku.read_text(encoding="utf-8")).get("taso")
    except (OSError, ValueError, AttributeError):
        vanha = None
    rajoittava = ("rate_limit", "pysaytetty", "hidastettu")
    if taso == vanha or (taso not in rajoittava and vanha not in rajoittava):
        return False
    try:
        polku.write_text(json.dumps({"taso": taso}), encoding="utf-8")
    except OSError:
        pass
    if laheta:
        laheta(f"claude-jono: Clauden kaytto {taso}" + (f" - {syy}" if syy else " - rajoitus purkautui"))
    return True


def kalibrointikysymys(tila, nyt):
    """Aamukoosteen pyynto, jos viimeisesta kalibroinnista on yli 3 vrk tai sellaista ei ole. Muuten ''."""
    kal = kulutus.lue(tila, kulutus.KALIBROINTI_TIEDOSTO)
    if kal and (nyt - max(k["_aika"] for k in kal)).total_seconds() < KALIBROINTI_VANHENEE_S:
        return ""
    return "kerro Clauden asetussivun \"T\u00e4ll\u00e4 viikolla x % k\u00e4ytetty\" (python3 -m claudejono.kulutus kalibroi x)"


def varausrivi(tila, env, nyt):
    """Aamukoosteen varausosa."""
    a = arvio(tila, env, nyt)
    raja = f"{a['raja_pros']:.0f} %"
    if a["taso"] == "ei_kalibroitu":
        return f"Tonyn varaus: agenttien raja {raja} tilauksen viikkorajasta, osuutta ei voi arvioida ilman kalibrointia."
    teksti = f"Tonyn varaus: agenttien arvioitu osuus {a['osuus_pros']:.0f} % / {raja} ({a['taso']})"
    if rate_limit_asti(tila, nyt.timestamp()):
        teksti += ", k\u00e4ytt\u00f6raja vastassa"
    return teksti + "."
