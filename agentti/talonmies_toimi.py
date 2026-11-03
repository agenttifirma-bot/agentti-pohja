"""Talonmies, vaihe 2: A-tason toimenpiteet ja B-tason tietoturvapaivitys kapean tyokalun kautta.

Ajo: python3 -m agentti.talonmies_toimi ajo <tila>
  1. ajaa vaiheen 1 ehdotusajon (agentti.talonmies.ajo), joka vain lukee tilan
  2. toteuttaa ehdotuksista vain ne toimenpiteet, jotka Tony on sallinut tiedostossa <tila>/sallitut.txt
     (rivit: kaatunut-palvelu, levy-taynna, tietoturvapaivitys). Tiedosto puuttuu -> mitaan ei tehda, vain ehdotukset.

Rajat ovat koodissa (agentti ei voi muuttaa niita):
  - kaikki muutokset kulkevat komennolla sudo -n /usr/local/sbin/talonmies-toimi (isanta/talonmies_toimi_sudo.py); ei muita komentoja
  - kaatunut palvelu: 1 uudelleenkaynnistys per palvelu ja vuorokausi; toinen kaatuminen samana paivana -> halytys, ei uutta yritysta
  - siivous: 1 per vuorokausi, vain kun levy on 80-89 % (90 % tai enemman on halytys Tonylle)
  - B-paivitys: 1 per vuorokausi, vain jos <tila>/ei-kriittiset.txt sisaltaa rivin ct115 (Tonyn paatos), snapshot ensin,
    terveystarkistus jalkeen, peruutus jos tarkistus epaonnistuu
  - pysaytystiedosto <tila>/PYSAYTA estaa kaiken
Kaikki toimet kirjataan tiedostoon <tila>/toimet.jsonl ja nakyvat aamukoosteessa (aamurivi).
Poikkeuksista kirjataan vain tyypin nimi. Koodi on ASCII-muotoista; ihmiselle menevat tekstit \\u-koodein.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from . import talonmies
from .lukko import lukittu

WRAPPER = "/usr/local/sbin/talonmies-toimi"
SUDO = ["sudo", "-n", WRAPPER]
TOIMET = "toimet.jsonl"
SALLITUT = "sallitut.txt"
EI_KRIITTISET = "ei-kriittiset.txt"
TERVEYS = "terveys.txt"
SALLITUT_TOIMENPITEET = ("kaatunut-palvelu", "levy-taynna", "tietoturvapaivitys")
ODOTUS_PALVELU_S = 60
ODOTUS_PAIVITYS_S = 30
LEVY_ALARAJA = talonmies.LEVY_RAJA
LEVY_YLARAJA = talonmies.LEVY_HALYTYS
YKSIKKO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@:._-]{0,80}\.service$")
SNAPSHOT_PREFIKSI = "ennen-paivitys-"


def _lue_rivit(polku):
    try:
        with open(polku, encoding="utf-8") as f:
            return {r.strip() for r in f if r.strip() and not r.lstrip().startswith("#")}
    except OSError:
        return set()


def sallitut(tila):
    return _lue_rivit(os.path.join(tila, SALLITUT)) & set(SALLITUT_TOIMENPITEET)


def pysaytetty(tila):
    return os.path.exists(os.path.join(tila, talonmies.PYSAYTUS))


def kirjaa(tila, nyt, toimenpide, kohde, tulos, huomio=""):
    rivi = {"aika": nyt.strftime("%Y-%m-%dT%H:%M:%SZ"), "pvm": nyt.strftime("%Y-%m-%d"), "toimenpide": toimenpide,
            "kohde": kohde, "tulos": tulos, "huomio": "".join(c for c in str(huomio) if c >= " ")[:200]}
    polku = os.path.join(tila, TOIMET)
    os.makedirs(tila, exist_ok=True)
    with lukittu(polku + ".lock"):
        with open(polku, "a", encoding="utf-8") as f:
            f.write(json.dumps(rivi, ensure_ascii=True, sort_keys=True) + "\n")
    return rivi


def lue_toimet(tila):
    return talonmies._lue_jsonl(os.path.join(tila, TOIMET))


def _tanaan(tila, nyt, toimenpide, kohde=None):
    pvm = nyt.strftime("%Y-%m-%d")
    return [r for r in lue_toimet(tila) if r.get("pvm") == pvm and r.get("toimenpide") == toimenpide
            and (kohde is None or r.get("kohde") == kohde)]


def _sudo(komento, suorita, aikaraja=1300):
    """Ajaa kiinteat sudo-komennot. Palauttaa wrapperin JSON-vastauksen sanakirjana (virhetilanteessa ok=False)."""
    try:
        r = suorita(SUDO + komento, capture_output=True, text=True, timeout=aikaraja)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "virhe": type(e).__name__}
    try:
        tulos = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "virhe": "ei_json", "koodi": r.returncode}
    return tulos if isinstance(tulos, dict) else {"ok": False, "virhe": "odottamaton_vastaus"}


def _aktiivinen(yksikko, suorita):
    try:
        r = suorita(["systemctl", "is-active", yksikko], capture_output=True, text=True, timeout=30,
                    env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (r.stdout or "").strip() == "active"


def halyta_oletus(otsikko, teksti):
    from . import ilmoita
    try:
        return ilmoita.ilmoita("virhe", otsikko, teksti)
    except Exception as e:
        return type(e).__name__


# ---- A: kaatunut palvelu ----

def kaynnista_uudelleen(tila, yksikko, nyt, suorita=subprocess.run, odota=time.sleep, halyta=halyta_oletus):
    """Palauttaa tuloksen: 'ok', 'epaonnistui', 'halytys' (jo yritetty tanaan), 'ohitettu' tai 'pysaytetty'."""
    if pysaytetty(tila):
        return "pysaytetty"
    if not YKSIKKO_RE.match(yksikko or "") or any(k in yksikko for k in talonmies.KOHINA):
        return "ohitettu"
    edelliset = _tanaan(tila, nyt, "kaatunut-palvelu", yksikko)
    if any(r.get("tulos") == "halytys" for r in edelliset):
        return "halytys"        # halytys on jo kirjattu ja lahetetty tanaan: ei toistoa joka ajolla
    if edelliset:
        kirjaa(tila, nyt, "kaatunut-palvelu", yksikko, "halytys", "kaatui uudelleen, ei uutta yritysta")
        halyta("Palvelu %s kaatui uudelleen" % yksikko, "Talonmies k\u00e4ynnisti sen jo t\u00e4n\u00e4\u00e4n. Ei uutta yrityst\u00e4.")
        return "halytys"
    vastaus = _sudo(["kaynnista", yksikko], suorita)
    if not vastaus.get("ok"):
        kirjaa(tila, nyt, "kaatunut-palvelu", yksikko, "epaonnistui", vastaus.get("virhe", "kaynnistys"))
        halyta("Palvelun %s uudelleenk\u00e4ynnistys ei onnistunut" % yksikko, str(vastaus.get("virhe", "?")))
        return "epaonnistui"
    odota(ODOTUS_PALVELU_S)
    if _aktiivinen(yksikko, suorita):
        kirjaa(tila, nyt, "kaatunut-palvelu", yksikko, "ok", "aktiivinen %d s k\u00e4ynnistyksen j\u00e4lkeen" % ODOTUS_PALVELU_S)
        return "ok"
    kirjaa(tila, nyt, "kaatunut-palvelu", yksikko, "epaonnistui", "ei aktiivinen k\u00e4ynnistyksen j\u00e4lkeen")
    halyta("Palvelu %s ei k\u00e4ynnisty" % yksikko, "Uudelleenk\u00e4ynnistyksen j\u00e4lkeen palvelu ei ole aktiivinen. Ei uutta yrityst\u00e4.")
    return "epaonnistui"


# ---- A: levyn siivous ----

def siivoa_levy(tila, nyt, pros, suorita=subprocess.run, halyta=halyta_oletus):
    if pysaytetty(tila):
        return "pysaytetty"
    if pros < LEVY_ALARAJA or pros >= LEVY_YLARAJA:
        return "ohitettu"
    if _tanaan(tila, nyt, "levy-taynna"):
        return "ohitettu"
    vastaus = _sudo(["siivoa"], suorita)
    if not vastaus.get("ok"):
        kirjaa(tila, nyt, "levy-taynna", "/", "epaonnistui", vastaus.get("virhe", "siivous"))
        halyta("Levyn siivous ei onnistunut", str(vastaus.get("virhe", "?")))
        return "epaonnistui"
    jalkeen = vastaus.get("levy_jalkeen")
    huomio = "levy %s %% -> %s %%, %s v\u00e4liaikaistiedostoa" % (vastaus.get("levy_ennen"), jalkeen, vastaus.get("tiedostoja"))
    if isinstance(jalkeen, int) and jalkeen >= LEVY_ALARAJA:
        kirjaa(tila, nyt, "levy-taynna", "/", "halytys", huomio)
        halyta("Levy on siivouksen j\u00e4lkeen edelleen t\u00e4ynn\u00e4", huomio)
        return "halytys"
    kirjaa(tila, nyt, "levy-taynna", "/", "ok", huomio)
    return "ok"


# ---- B: tietoturvapaivitys ----

def _epaonnistuneet(suorita):
    try:
        r = suorita(talonmies.KOMENNOT["epaonnistuneet"], capture_output=True, text=True, timeout=30,
                    env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    ulos = set()
    for rivi in (r.stdout or "").splitlines():
        osat = [o for o in rivi.split() if o not in ("\u25cf", "*")]
        if osat and not any(k in osat[0] for k in talonmies.KOHINA):
            ulos.add(osat[0])
    return ulos


def terveys_ok(tila, ennen, suorita):
    """Uusia failed-yksikoita ei saa tulla, ja tiedoston terveys.txt yksikoiden pitaa olla aktiivisia."""
    nyt_failed = _epaonnistuneet(suorita)
    if nyt_failed is None or ennen is None:
        return False, "failed-tilaa ei saatu luettua"
    uudet = sorted(nyt_failed - ennen)
    if uudet:
        return False, "uusia failed-yksik\u00f6it\u00e4: " + ", ".join(uudet[:5])
    for y in sorted(_lue_rivit(os.path.join(tila, TERVEYS))):
        if YKSIKKO_RE.match(y) and not _aktiivinen(y, suorita):
            return False, "yksikk\u00f6 %s ei ole aktiivinen" % y
    return True, "ok"


def paivita_turva(tila, nyt, suorita=subprocess.run, odota=time.sleep, halyta=halyta_oletus, ota_snapshot=None):
    """Snapshot -> paivitys -> terveystarkistus -> peruutus epaonnistuessa. Palauttaa tuloksen kuten kaynnista_uudelleen."""
    if pysaytetty(tila):
        return "pysaytetty"
    if "ct115" not in _lue_rivit(os.path.join(tila, EI_KRIITTISET)):
        return "ei_lupaa"       # Tony ei ole nimennyt kontteja ei-kriittisiksi: pysyy tason C ehdotuksena
    if _tanaan(tila, nyt, "tietoturvapaivitys"):
        return "ohitettu"
    if ota_snapshot is None:
        from . import snapshot_kutsu
        ota_snapshot = snapshot_kutsu.ota
    nimi = SNAPSHOT_PREFIKSI + nyt.strftime("%Y%m%d")
    try:
        tulos = ota_snapshot(nimi)
        snapshot_ok = isinstance(tulos, dict) and tulos.get("ok") is True
        syy = str(tulos.get("virhe", "?"))[:80] if isinstance(tulos, dict) and not snapshot_ok else ""
    except Exception as e:      # vain tyyppi
        snapshot_ok, syy = False, type(e).__name__
    if not snapshot_ok:
        kirjaa(tila, nyt, "tietoturvapaivitys", "ct115", "ei_tehty", "snapshot ep\u00e4onnistui: " + syy)
        halyta("Tietoturvap\u00e4ivitys j\u00e4i tekem\u00e4tt\u00e4", "Snapshotin otto ep\u00e4onnistui (%s), p\u00e4ivityst\u00e4 ei tehty." % syy)
        return "ei_tehty"
    ennen = _epaonnistuneet(suorita)
    vastaus = _sudo(["paivita"], suorita)
    paketit = vastaus.get("paketit") or []
    if vastaus.get("ok") and not paketit:
        kirjaa(tila, nyt, "tietoturvapaivitys", "ct115", "ok", "ei p\u00e4ivitett\u00e4v\u00e4\u00e4, snapshot %s" % nimi)
        return "ok"
    odota(ODOTUS_PAIVITYS_S)
    kunto, syy = (terveys_ok(tila, ennen, suorita) if vastaus.get("ok") else (False, "p\u00e4ivityskomento ep\u00e4onnistui"))
    yhteenveto = "%d pakettia, snapshot %s" % (len(paketit), nimi)
    if kunto:
        kirjaa(tila, nyt, "tietoturvapaivitys", "ct115", "ok", yhteenveto)
        return "ok"
    paluu = _sudo(["peruuta"], suorita)
    odota(ODOTUS_PAIVITYS_S)
    palautettu = bool(paluu.get("ok")) and terveys_ok(tila, ennen, suorita)[0]
    if palautettu:
        kirjaa(tila, nyt, "tietoturvapaivitys", "ct115", "peruttu", "%s; syy: %s" % (yhteenveto, syy))
        halyta("Tietoturvap\u00e4ivitys peruttu", "Terveystarkistus ep\u00e4onnistui (%s). Paketit palautettu. Snapshot %s on tallessa." % (syy, nimi))
        return "peruttu"
    kirjaa(tila, nyt, "tietoturvapaivitys", "ct115", "peruutus_epaonnistui", "%s; syy: %s" % (yhteenveto, syy))
    halyta("Tietoturvap\u00e4ivityksen peruutus ep\u00e4onnistui",
           "Terveystarkistus ep\u00e4onnistui (%s) eik\u00e4 pakettien palautus korjannut tilaa. Palauta kontti snapshotista %s "
           "(Tony ajaa is\u00e4nn\u00e4ll\u00e4: pct rollback 115 %s)." % (syy, nimi, nimi))
    return "peruutus_epaonnistui"


# ---- Ajo ja aamurivi ----

def ajo(tila, nyt=None, suorita=subprocess.run, odota=time.sleep, halyta=halyta_oletus, ota_snapshot=None, hae_isanta=None):
    """Ehdotusajo + sallittujen toimenpiteiden toteutus. Palauttaa (raporttiteksti, toimet-sanakirja)."""
    nyt = nyt or datetime.now(timezone.utc)
    teksti, ehd = talonmies.ajo(tila, nyt, suorita, hae_isanta)
    if pysaytetty(tila):
        return teksti, {}
    lupa = sallitut(tila)
    toimet = {}
    for e in ehd:
        t = e["toimenpide"]
        if t not in lupa:
            continue
        if t == "kaatunut-palvelu" and ":" not in e["kohde"].split(".service")[0]:
            toimet[e["tunniste"]] = kaynnista_uudelleen(tila, e["kohde"], nyt, suorita, odota, halyta)
        elif t == "levy-taynna" and e["taso"] == "A":
            pros = dict(talonmies.jasenna_levy(talonmies.aja_komento("levy", suorita))).get(e["kohde"])
            if pros is not None:
                toimet[e["tunniste"]] = siivoa_levy(tila, nyt, pros, suorita, halyta)
        elif t == "tietoturvapaivitys":
            toimet[e["tunniste"]] = paivita_turva(tila, nyt, suorita, odota, halyta, ota_snapshot)
    return teksti, toimet


def aamurivi(tila, nyt, tunnit=24):
    """Yksi rivi aamukoosteeseen viime vuorokauden toimista, tai None."""
    raja = nyt - timedelta(hours=tunnit)
    osat = []
    for r in lue_toimet(tila):
        try:
            aika = datetime.strptime(r["aika"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if aika >= raja:
            osat.append("%s %s: %s" % (r.get("toimenpide"), r.get("kohde"), r.get("tulos")))
    if not osat:
        return None
    return "Talonmies: " + "; ".join(osat[:4]) + (" (+%d)" % (len(osat) - 4) if len(osat) > 4 else "")


def main(argv=None):
    a = sys.argv[1:] if argv is None else list(argv)
    if len(a) == 2 and a[0] == "ajo":
        try:
            teksti, toimet = ajo(a[1])
        except Exception as e:      # vain tyyppi, viesti voi sisaltaa salaisuuksia
            print("VIRHE: %s" % type(e).__name__)
            return 1
        print(teksti)
        for tunn, tulos in sorted(toimet.items()):
            print("toimi: %s -> %s" % (tunn, tulos))
        if not toimet:
            print("toimia ei tehty (sallitut: %s)" % (", ".join(sorted(sallitut(a[1]))) or "ei yht\u00e4\u00e4n"))
        return 0
    print("k\u00e4ytt\u00f6: python3 -m agentti.talonmies_toimi ajo <tila>")
    return 2


if __name__ == "__main__":
    sys.exit(main())
