"""Aivon oleellisuusarvio varjotilassa (Tonyn paatos A841, 7.11.2026).

Ennen kuin uusi tehtava ajetaan, Aivo (Clauden tyokalutila, ei OpenRouter/LiteLLM, A329) kirjaa arvion kylla/ei + syy.
Arvio EI esta ajoa. Kirjaukset menevat isannan tilahakemistoon (`aivo-arviot.jsonl`, repon vieressa), ei GitHubiin eika docs-repoon.
Tony tarkistaa viikkosuunnittelussa 5 satunnaista arviota (`otos`) ja kirjaa oman tuomionsa (`tarkista`); osumaprosentti =
Aivon ja Tonyn tuomion yhtenevyys. Kunnes arvioija (Aivon tyokalutila) on kytketty, ajuri ei kirjaa mitaan: arvioija annetaan
`arvioi_varjossa`-funktiolle parametrina, eika tama moduuli keksi arvioita.
"""
import argparse
import json
import os
import random
import re
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
RYHMA_MIN = 5   # alle taman ryhmat nakyvat koosteessa muodossa "<5"
_TILA_RE = re.compile(r"(?m)^- Tila: ([A-Z]+)\s*$")
_VALMIS = "VALMIS"
_EI_VALMIS = ("HYLATTY", "KESKEN")   # EPAONNISTUI on tekninen vika, ei oleellisuuden tuomio: ei oteta vertailuun


def _peita(n):
    return n if n >= RYHMA_MIN else "<" + str(RYHMA_MIN)


def _prosentti(osa, kaikki):
    return round(100 * osa / kaikki, 1) if kaikki >= RYHMA_MIN else None


def _tulos_tila(tulokset_hak, tehtava):
    """Tehtavan tuloksen Tila-rivi (VALMIS, KESKEN, ...) tai None. Vain nimeen luotetaan, ei polun osiin."""
    if tulokset_hak is None or Path(tehtava).name != tehtava:
        return None
    try:
        with open(Path(tulokset_hak) / tehtava, encoding="utf-8", errors="replace") as f:
            m = _TILA_RE.search(f.read(2000))
    except OSError:
        return None
    return m.group(1) if m else None


def laske_kooste(tila, tulokset_hak=None, nyt=None):
    """Koosteluvut Aivon arvioista: vain lukumaaria ja prosentteja. EI tehtavien nimia, EI syita, EI yksittaisia rivia.
    Alle RYHMA_MIN kokoiset ryhmat nakyvat muodossa "<5" eika niista lasketa prosenttia."""
    nyt = nyt or datetime.now().astimezone()
    aivo, tony = {}, {}
    for d in lue(tila):
        if not isinstance(d.get("kylla"), bool):
            continue
        if d.get("laji") == "aivo":
            aivo[d["tehtava"]] = d
        elif d.get("laji") == "tony":
            tony[d["tehtava"]] = d
    tony = {k: v for k, v in tony.items() if k in aivo}
    n = len(aivo)
    kylla = sum(1 for d in aivo.values() if d["kylla"])
    ei = n - kylla
    jakauma_peitetty = kylla < RYHMA_MIN or ei < RYHMA_MIN   # muuten pieni ryhma paattelisi yhteissummasta
    paivat = {}
    mallit = {}
    for d in aivo.values():
        pv = str(d.get("aika", ""))[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pv):
            paivat[pv] = paivat.get(pv, 0) + 1
        if isinstance(d.get("malli"), str) and re.fullmatch(r"[A-Za-z0-9._:/-]{1,60}", d["malli"]):
            mallit[d["malli"]] = mallit.get(d["malli"], 0) + 1
    tony_osumat = sum(1 for k, v in tony.items() if v["kylla"] == aivo[k]["kylla"])
    vertailtu = osumat = 0
    for k, d in aivo.items():
        t = _tulos_tila(tulokset_hak, k)
        if t == _VALMIS or t in _EI_VALMIS:
            vertailtu += 1
            osumat += 1 if (d["kylla"] == (t == _VALMIS)) else 0
    return {
        "laskettu": nyt.isoformat(timespec="seconds"),
        "ryhman_vahimmaiskoko": RYHMA_MIN,
        "arvioita_yhteensa": _peita(n),
        "kylla": "<5" if jakauma_peitetty else kylla,
        "ei": "<5" if jakauma_peitetty else ei,
        "mallit": {m: _peita(c) for m, c in sorted(mallit.items())},
        "ensimmainen_paiva": min(paivat) if n >= RYHMA_MIN and paivat else None,
        "viimeinen_paiva": max(paivat) if n >= RYHMA_MIN and paivat else None,
        "paivittain": {pv: _peita(c) for pv, c in sorted(paivat.items())},
        "tony_tarkistanut": _peita(len(tony)),
        "yhtenevyys_tonyn_kanssa_prosenttia": _prosentti(tony_osumat, len(tony)),
        "tulokseen_verrattu": _peita(vertailtu),
        "yhtenevyys_tuloksen_kanssa_prosenttia": _prosentti(osumat, vertailtu),
        "yhtenevyys_tuloksen_kanssa_selitys": "Aivon kylla = tehtava loppui tilaan VALMIS; Aivon ei = tulos on HYLATTY tai KESKEN. "
                                               "Muut tilat (esim. EPAONNISTUI) ja tehtavat ilman tulosta jatetaan pois.",
        "lahtotasoon_riittavasti_arvioita": n >= VAHIMMAIS_LAHTOTASOON,
        "lahtotason_raja": VAHIMMAIS_LAHTOTASOON,
    }


def kirjoita_kooste(tila, tulokset_hak=None, nyt=None):
    """Laskee koosteen ja kirjoittaa sen atomisesti (valiaikaistiedosto + rename) tiedostoon tila/aivo-kooste.json, oikeudet 0644."""
    kooste = laske_kooste(tila, tulokset_hak, nyt)
    kohde = Path(tila) / KOOSTE_TIEDOSTO
    fd, vali = tempfile.mkstemp(prefix=KOOSTE_TIEDOSTO + ".", suffix=".tmp", dir=str(tila))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(kooste, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.chmod(vali, 0o644)   # mkstemp luo 0600; umask ei saa vaikuttaa
        os.replace(vali, kohde)
    except BaseException:
        try:
            os.unlink(vali)
        except OSError:
            pass
        raise
    return kohde


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
