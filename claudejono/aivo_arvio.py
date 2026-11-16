"""Aivon oleellisuusarvio varjotilassa (Tonyn paatos A841, 7.11.2026).

Ennen kuin uusi tehtava ajetaan, Aivo (Clauden tyokalutila, ei OpenRouter/LiteLLM, A329) kirjaa arvion kylla/ei + syy.
Arvio EI esta ajoa. Kirjaukset menevat isannan tilahakemistoon (`aivo-arviot.jsonl`, repon vieressa), ei GitHubiin eika docs-repoon.
Tony tarkistaa viikkosuunnittelussa 5 satunnaista arviota (`otos`) ja kirjaa oman tuomionsa (`tarkista`); osumaprosentti =
Aivon ja Tonyn tuomion yhtenevyys. Kunnes arvioija (Aivon tyokalutila) on kytketty, ajuri ei kirjaa mitaan: arvioija annetaan
`arvioi_varjossa`-funktiolle parametrina, eika tama moduuli keksi arvioita.
"""
import argparse
import hashlib
import json
import os
import random
import re
import stat
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

TIEDOSTO = "aivo-arviot.jsonl"
KAYTTO_TIEDOSTO = "aivo-kaytto.jsonl"   # kayton seuranta: yksi rivi per arviointiyritys (ei paivarajaa, Tony 11.11. A943)
SYY_MAX = 300
OTOS_OLETUS = 5
VAHIMMAIS_LAHTOTASOON = 20   # aivo-valmius.md: vahintaan 20 arvioitua paatosta


def _polku(tila):
    return Path(tila) / TIEDOSTO


def lue(tila):
    """Kaikki rivit; viallinen rivi ohitetaan. Tuoreempi rivi samalla (tehtava, laji) korvaa vanhan."""
    p = _polku(tila)
    if not p.is_file():
        return []
    rivit = []
    for r in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(r)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("tehtava"):
            rivit.append(d)
    return rivit


def _liita(tila, d):
    fd = os.open(_polku(tila), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def kirjaa_kaytto(tila, tehtava, kesto_s, ok, nyt=None):
    """Kirjaa arvioinnin keston ja onnistumisen; viikkoraportti summaa nama. Ei salaisuuksia: vain nimi, kesto, ok."""
    nyt = nyt or datetime.now().astimezone()
    d = {"aika": nyt.isoformat(timespec="seconds"), "tehtava": tehtava, "kesto_s": round(float(kesto_s), 2), "ok": bool(ok)}
    fd = os.open(Path(tila) / KAYTTO_TIEDOSTO, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def kaytto(tila, alkaen=None):
    """(arvioita, onnistuneita, kesto yhteensa s) rivit, joiden aika >= alkaen (datetime tai None = kaikki)."""
    p = Path(tila) / KAYTTO_TIEDOSTO
    n = ok = 0
    kesto = 0.0
    if p.is_file():
        for r in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(r)
                if alkaen is not None and datetime.fromisoformat(d["aika"]) < alkaen:
                    continue
                kesto += float(d["kesto_s"])
                n += 1
                ok += 1 if d.get("ok") is True else 0
            except (ValueError, KeyError, TypeError):
                continue
    return n, ok, round(kesto, 2)


def arviot(tila):
    """{tehtava: {"kylla": bool, "syy": str, "tony": bool|None}}"""
    ulos = {}
    for d in lue(tila):
        e = ulos.setdefault(d["tehtava"], {"kylla": None, "syy": "", "tony": None})
        if d.get("laji") == "aivo" and isinstance(d.get("kylla"), bool):
            e["kylla"], e["syy"] = d["kylla"], str(d.get("syy", ""))[:SYY_MAX]
        elif d.get("laji") == "tony" and isinstance(d.get("kylla"), bool):
            e["tony"] = d["kylla"]
    return {k: v for k, v in ulos.items() if v["kylla"] is not None}


def kirjaa_arvio(tila, tehtava, kylla, syy, nyt=None):
    nyt = nyt or datetime.now().astimezone()
    _liita(tila, {"aika": nyt.isoformat(timespec="seconds"), "laji": "aivo", "tehtava": tehtava, "kylla": bool(kylla), "syy": str(syy)[:SYY_MAX]})


def arvioi_varjossa(tila, tehtava_polku, arvioija, nyt=None):
    """Kutsuu arvioijaa (teksti -> (kylla: bool, syy: str)) kerran per tehtava. Ei koskaan nosta virhetta eika esta ajoa.
    Palauttaa True, jos arvio kirjattiin. Virheesta kirjataan vain tyyppi."""
    if arvioija is None:
        return False
    nimi = Path(tehtava_polku).name
    try:
        if nimi in arviot(tila):
            return False
        teksti = Path(tehtava_polku).read_bytes()[:20000].decode("utf-8", "replace")
        alku = time.monotonic()
        try:
            kylla, syy = arvioija(teksti)
        except Exception:
            kirjaa_kaytto(tila, nimi, time.monotonic() - alku, False, nyt)
            raise
        kirjaa_kaytto(tila, nimi, time.monotonic() - alku, isinstance(kylla, bool), nyt)
        if not isinstance(kylla, bool):
            return False
        kirjaa_arvio(tila, nimi, kylla, syy, nyt)
        return True
    except Exception as e:   # varjotila: mikaan ei saa kaataa ajoa; viestia ei tulosteta (voi sisaltaa salaisuuksia)
        print(f"aivo_arvio: arviointi epaonnistui ({type(e).__name__})", file=sys.stderr)
        return False


def otos(tila, n=OTOS_OLETUS, rng=None):
    """n satunnaista arviota, joita Tony ei ole viela tarkistanut."""
    avoimet = sorted(k for k, v in arviot(tila).items() if v["tony"] is None)
    rng = rng or random.Random()
    return [(k, arviot(tila)[k]) for k in rng.sample(avoimet, min(n, len(avoimet)))]


def tarkista(tila, tehtava, kylla, nyt=None):
    if tehtava not in arviot(tila):
        raise KeyError("ei Aivon arviota tehtavalle")
    nyt = nyt or datetime.now().astimezone()
    _liita(tila, {"aika": nyt.isoformat(timespec="seconds"), "laji": "tony", "tehtava": tehtava, "kylla": bool(kylla)})


def osuma(tila):
    """(tarkistettuja, osumia, prosentti|None, arvioituja_yhteensa)"""
    a = arviot(tila)
    tark = [v for v in a.values() if v["tony"] is not None]
    osumat = sum(1 for v in tark if v["tony"] == v["kylla"])
    return len(tark), osumat, (round(100 * osumat / len(tark), 1) if tark else None), len(a)


def viikkoosio(tila, n=OTOS_OLETUS, rng=None):
    """Markdown viikkosuunnittelun pohjaan: otos Tonyn tarkistettavaksi ja osumaprosentti."""
    tark, osumia, pros, yht = osuma(tila)
    rivit = ["## Aivon oleellisuusarviot (varjotila, ei est\u00e4 ajoa)", "",
             f"Arvioituja yhteens\u00e4 {yht}; Tony on tarkistanut {tark}; osumia {osumia}; osumaprosentti "
             + (f"{pros} %." if pros is not None else "ei viel\u00e4 laskettavissa.")
             + f" L\u00e4ht\u00f6tason raja: v\u00e4hint\u00e4\u00e4n {VAHIMMAIS_LAHTOTASOON} arvioitua p\u00e4\u00e4t\u00f6st\u00e4."]
    k_n, k_ok, k_s = kaytto(tila, datetime.now().astimezone() - timedelta(days=7))
    rivit += ["", f"K\u00e4ytt\u00f6 viimeiset 7 vrk: {k_n} arviointiajoa ({k_ok} onnistui), kesto yhteens\u00e4 {k_s} s."]
    o = otos(tila, n, rng)
    if not o:
        rivit += ["", "Tarkistettavia arvioita ei ole (arvioija ei ole viel\u00e4 kytketty tai kaikki on tarkistettu)."]
    else:
        rivit += ["", f"Tarkista {len(o)} satunnaista arviota (`python3 -m claudejono.aivo_arvio tarkista <tehtava> kylla|ei`):", ""]
        kylla_sana = "kyll\u00e4"
        rivit += [f"- {k}: Aivo sanoi {kylla_sana if v['kylla'] else 'ei'} - {v['syy']}" for k, v in o]
    return "\n".join(rivit) + "\n"


KOOSTE_TIEDOSTO = "aivo-kooste.json"
KOOSTE_TILA_TIEDOSTO = "aivo-kooste.tila.json"   # vain ajurin oma kirjanpito (tarkat luvut), oikeudet 0600, ei koskaan agenttien luettavaksi
RYHMA_MIN = 5   # alle taman ryhmat nakyvat koosteessa muodossa "<5"
PYORISTYS = 5   # julkaistavat maarat pyoristetaan lahimpaan viiteen
KOOSTE_VALI = timedelta(hours=24)   # koostetta paivitetaan enintaan kerran vuorokaudessa
KOOSTE_UUSIA_MIN = 10               # ... ja vain kun uusia arvioita/tarkistuksia/vertailuja on kertynyt vahintaan taman verran
_TILA_RE = re.compile(r"(?m)^- Tila: ([A-Z]+)\s*$")
_VALMIS = "VALMIS"
_EI_VALMIS = ("HYLATTY", "KESKEN")   # EPAONNISTUI on tekninen vika, ei oleellisuuden tuomio: ei oteta vertailuun


def _peita(n):
    """Julkaistava maara: alle RYHMA_MIN -> "<5", muuten pyoristetty lahimpaan viiteen (5, 5, 10, ...)."""
    if n < RYHMA_MIN:
        return "<" + str(RYHMA_MIN)
    return (n + PYORISTYS // 2) // PYORISTYS * PYORISTYS


def _prosentti(osa, kaikki):
    return round(100 * osa / kaikki) if kaikki >= RYHMA_MIN else None   # kokonaisluku


def _viikko(pv):
    """ISO-viikko muodossa 2026-V46 tai None, jos paiva ei jasenny."""
    try:
        v = datetime.strptime(pv, "%Y-%m-%d").date().isocalendar()
    except ValueError:
        return None
    return f"{v[0]}-V{v[1]:02d}"


def _tulos_tila(tulokset_hak, tehtava):
    """Tehtavan tuloksen Tila-rivi (VALMIS, KESKEN, ...) tai None. Vain nimeen luotetaan, ei polun osiin.
    tulokset/ on agentin kirjoitettavissa ja ajuri on root, joten tiedosto avataan varovasti: O_NOFOLLOW (symlinkki
    ei kelpaa), O_NONBLOCK (FIFO ei jumita open-kutsua) ja fstat: vain tavallinen tiedosto luetaan."""
    if tulokset_hak is None or Path(tehtava).name != tehtava:
        return None
    try:
        fd = os.open(Path(tulokset_hak) / tehtava, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        teksti = os.read(fd, 2000).decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)
    m = _TILA_RE.search(teksti)
    return m.group(1) if m else None


def _raaka(tila, tulokset_hak=None):
    """Tarkat luvut (EI julkaista): n, kylla, viikot, tony-osumat, vertailu. Vain ajurin sisaiseen kayttoon."""
    aivo, tony = {}, {}
    for d in lue(tila):
        if not isinstance(d.get("kylla"), bool):
            continue
        if d.get("laji") == "aivo":
            aivo[d["tehtava"]] = d
        elif d.get("laji") == "tony":
            tony[d["tehtava"]] = d
    tony = {k: v for k, v in tony.items() if k in aivo}
    viikot = {}
    for d in aivo.values():
        v = _viikko(str(d.get("aika", ""))[:10])
        if v:
            viikot[v] = viikot.get(v, 0) + 1
    vertailtu = osumat = 0
    kohteet = {}
    for k, d in aivo.items():
        t = _tulos_tila(tulokset_hak, k)
        vertailussa = t == _VALMIS or t in _EI_VALMIS
        if vertailussa:
            vertailtu += 1
            osumat += 1 if (d["kylla"] == (t == _VALMIS)) else 0
        # kohteen sormenjalki portille: vain ajurin omasta 0600-datasta (oma arvio, Tonin tarkistus). Tulostila EI ole
        # mukana: tulokset/ on agentin kirjoitettavissa, joten agentti voisi tuottaa tilanvaihdoilla "muutoksia" ja
        # avata portin yhdella aidolla muutoksella (9 tunnettua + 1).
        kohteet[_tiiviste(k)] = _tiiviste(json.dumps([d["kylla"], tony[k]["kylla"] if k in tony else None]))
    return {
        "n": len(aivo),
        "kylla": sum(1 for d in aivo.values() if d["kylla"]),
        "viikot": viikot,
        "tony": len(tony),
        "tony_osumat": sum(1 for k, v in tony.items() if v["kylla"] == aivo[k]["kylla"]),
        "vertailtu": vertailtu,
        "osumat": osumat,
        "kohteet": kohteet,
    }


def _tiiviste(teksti):
    return hashlib.sha256(teksti.encode("utf-8")).hexdigest()[:16]


def _muutokset(kohteet, vanhat):
    """Montako kohdetta on uusi, poistunut tai muuttunut (korvattu arvio, kaantynyt Tonin tarkistus)
    edelliseen julkaisuun verrattuna. Sisallon tiiviste, ei lukumaaria: korvaus ei saa jaada huomaamatta."""
    return sum(1 for k in kohteet.keys() | vanhat.keys() if kohteet.get(k) != vanhat.get(k))


def _muodosta(r, nyt):
    n = r["n"]
    ei = n - r["kylla"]
    jakauma_peitetty = r["kylla"] < RYHMA_MIN or ei < RYHMA_MIN   # muuten pieni ryhma paattelisi yhteissummasta
    viikot = sorted(r["viikot"])
    return {
        "laskettu": nyt.date().isoformat(),   # vain paiva: tarkka kellonaika ei kerro, milloin arvio tuli
        "ryhman_vahimmaiskoko": RYHMA_MIN,
        "pyoristys": f"maarat pyoristetaan lahimpaan viiteen, prosentit kokonaisluvuiksi; koostetta paivitetaan enintaan kerran {int(KOOSTE_VALI.total_seconds() // 3600)} h valein ja vasta kun uusia on vahintaan {KOOSTE_UUSIA_MIN}",
        "arvioita_yhteensa": _peita(n),
        "kylla": "<5" if jakauma_peitetty else _peita(r["kylla"]),
        "ei": "<5" if jakauma_peitetty else _peita(ei),
        "ensimmainen_viikko": viikot[0] if n >= RYHMA_MIN and viikot else None,
        "viimeinen_viikko": viikot[-1] if n >= RYHMA_MIN and viikot else None,
        "viikoittain": {v: _peita(r["viikot"][v]) for v in viikot},
        "tony_tarkistanut": _peita(r["tony"]),
        "yhtenevyys_tonyn_kanssa_prosenttia": _prosentti(r["tony_osumat"], r["tony"]),
        "tulokseen_verrattu": _peita(r["vertailtu"]),
        "yhtenevyys_tuloksen_kanssa_prosenttia": _prosentti(r["osumat"], r["vertailtu"]),
        "yhtenevyys_tuloksen_kanssa_selitys": "Aivon kylla = tehtava loppui tilaan VALMIS; Aivon ei = tulos on HYLATTY tai KESKEN. "
                                               "Muut tilat (esim. EPAONNISTUI) ja tehtavat ilman tulosta jatetaan pois.",
        "lahtotasoon_riittavasti_arvioita": n >= VAHIMMAIS_LAHTOTASOON,
        "lahtotason_raja": VAHIMMAIS_LAHTOTASOON,
    }


def laske_kooste(tila, tulokset_hak=None, nyt=None):
    """Koosteluvut Aivon arvioista: vain pyoristettyja lukumaaria ja prosentteja, viikkotasolla.
    EI tehtavien nimia, EI syita, EI yksittaisia rivia, EI malli- eika paivakohtaisia maaria.
    Alle RYHMA_MIN kokoiset ryhmat nakyvat muodossa "<5" eika niista lasketa prosenttia."""
    return _muodosta(_raaka(tila, tulokset_hak), nyt or datetime.now().astimezone())


def _kirjoita_atomisesti(tila, nimi, teksti, oikeudet):
    """Kirjoittaa tiedoston tila/nimi atomisesti: valiaikaistiedosto (mkstemp = O_EXCL, ei seuraa symlinkkia),
    oikeudet asetetaan tiedostokahvalla (fchmod) ENNEN nimeamista. Ei koskaan chmod polun kautta, koska
    polku voisi vaihtua symlinkiksi (kilpa) ja root muuttaisi muun tiedoston oikeuksia."""
    kohde = Path(tila) / nimi
    fd, vali = tempfile.mkstemp(prefix=nimi + ".", suffix=".tmp", dir=str(tila))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), oikeudet)   # mkstemp luo 0600; umask ei saa vaikuttaa
            f.write(teksti)
        os.replace(vali, kohde)   # korvaa mahdollisen symlinkin itsensa, ei sen kohdetta
    except BaseException:
        try:
            os.unlink(vali)
        except OSError:
            pass
        raise
    return kohde


def _portti_auki(tila, kohteet, nyt):
    """True, jos koosteen saa paivittaa: edellisesta on >= KOOSTE_VALI ja muuttuneita kohteita >= KOOSTE_UUSIA_MIN.
    FAIL-CLOSED: paatos tehdaan kirjanpitotiedostosta (aivo-kooste.tila.json). Jos kirjanpito puuttuu tai on
    rikki, portti pysyy kiinni, vaikka koostetta ei olisi: poistettu tiedosto ei saa avata porttia.
    Ainoa sallittu avaus ilman kirjanpitoa on aito ensijulkaisu (ei kirjanpitoa eika koostetta).
    Puuttuvan koosteen (kirjanpito kunnossa) luo seuraava normaali avaus. Toipuminen rikkinaisesta tilasta:
    Tony poistaa molemmat tiedostot kasin."""
    kooste_on = (Path(tila) / KOOSTE_TIEDOSTO).exists()
    kirjanpito_on = (Path(tila) / KOOSTE_TILA_TIEDOSTO).exists()
    if not kooste_on and not kirjanpito_on:
        return True
    try:
        with open(Path(tila) / KOOSTE_TILA_TIEDOSTO, encoding="utf-8") as f:
            edellinen = json.load(f)
        aika = datetime.fromisoformat(edellinen["aika"])
        vanhat = edellinen["kohteet"]
        if not isinstance(vanhat, dict):
            return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return nyt - aika >= KOOSTE_VALI and _muutokset(kohteet, vanhat) >= KOOSTE_UUSIA_MIN


def kirjoita_kooste(tila, tulokset_hak=None, nyt=None):
    """Paivittaa tiedoston tila/aivo-kooste.json (oikeudet 0644, atominen kirjoitus) vain, jos portti on auki:
    vahintaan KOOSTE_VALI edellisesta ja vahintaan KOOSTE_UUSIA_MIN muuttunutta kohdetta. Palauttaa polun tai None (ei paivitetty).
    Syy: kahden perakkaisen koosteen erotuksesta ei saa voida paatella yksittaista arviota (erotushyokkays)."""
    nyt = nyt or datetime.now().astimezone()
    r = _raaka(tila, tulokset_hak)
    if not _portti_auki(tila, r["kohteet"], nyt):
        return None
    teksti = json.dumps(_muodosta(r, nyt), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # kirjanpito ensin: jos koosteen kirjoitus kaatuu, paivitys vain viivastyy (ei kaksoisjulkaisua)
    _kirjoita_atomisesti(tila, KOOSTE_TILA_TIEDOSTO,
                         json.dumps({"aika": nyt.isoformat(timespec="seconds"), "kohteet": r["kohteet"]}) + "\n", 0o600)
    return _kirjoita_atomisesti(tila, KOOSTE_TIEDOSTO, teksti, 0o644)


def kirjoita_kooste_varmasti(tila, tulokset_hak=None, nyt=None):
    """Kuten kirjoita_kooste, mutta ei koskaan nosta virhetta (ajo ei saa kaatua). Virheesta kirjataan vain tyyppi. True = onnistui."""
    try:
        kirjoita_kooste(tila, tulokset_hak, nyt)
        return True
    except Exception as e:
        print(f"aivo_arvio: koosteen laskenta epaonnistui ({type(e).__name__})", file=sys.stderr)
        return False


def main(argv=None):
    p = argparse.ArgumentParser(description="Aivon oleellisuusarviot (varjotila)")
    p.add_argument("--tila", default=os.environ.get("CLAUDEJONO_TILA", "/var/lib/claude-jono"))
    s = p.add_subparsers(dest="komento", required=True)
    s.add_parser("otos")
    s.add_parser("osuma")
    t = s.add_parser("tarkista")
    t.add_argument("tehtava")
    t.add_argument("tuomio", choices=("kylla", "ei"))
    a = p.parse_args(argv)
    if a.komento == "otos":
        print(viikkoosio(a.tila), end="")
    elif a.komento == "osuma":
        print(osuma(a.tila))
    else:
        try:
            tarkista(a.tila, a.tehtava, a.tuomio == "kylla")
        except KeyError as e:
            print(f"virhe: {e.args[0]}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


VALMIUS_TIEDOSTO = "claude-jono/aivo-valmius.md"
RUUTU_RE = __import__("re").compile(r"(?m)^[ \t]*- \[([ xX])\]")


def valmius_taynna(repo):
    """True, kun aivo-valmius.md:ssa on vahintaan 5 ruutua ja jokainen on rastitettu. Puuttuva tiedosto -> False.
    Ruudut rastittaa Tony tai Claude vasta todennettuaan kohdan; tama funktio vain lukee."""
    try:
        teksti = (Path(repo) / VALMIUS_TIEDOSTO).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    ruudut = RUUTU_RE.findall(teksti)
    return len(ruudut) >= 5 and all(r in "xX" for r in ruudut)
