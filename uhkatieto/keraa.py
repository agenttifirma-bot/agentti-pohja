"""Keraaja: hakee lahteet, tallentaa raakatiedostot (gzip, paivakohtaiset) ja normalisoidut rivit SQLiteen.

Ei LLM-kutsuja eika lahetyksia (ei Telegramia). Yksi lahde voi epaonnistua muiden estamatta; poistumiskoodi 1 jos jokin epaonnistui.
Lahteet: kev, atlas, nvd. abuse.ch (URLhaus/ThreatFox) vaatii nykyisin Auth-Keyn -> vain suunnitelma, ks. README.
"""
import argparse
import datetime
import gzip
import hashlib
import os
import re
import sys
import time
import urllib.parse

from . import haku, jasentimet, tietokanta

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
ATLAS_HAKEMISTO = "https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/v6/"
# ATLAS-latest.yaml on git-symlink: raw-palvelu palauttaa vain kohteen nimen (esim. ATLAS-2026.10.yaml)
ATLAS_NIMI_RE = re.compile(r"^ATLAS-\d{4}\.\d{2}(\.\d+)?\.yaml$")
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_HAKUSANAT = ("LLM", "AI", "agent", "MCP")
NVD_SIVUKOKO = 500
NVD_MAX_SIVUJA = 4
NVD_VALI_S = 7  # avaimeton NVD-raja: 5 pyyntoa / 30 s
NVD_MAX_PAIVIA = 120  # NVD:n pubStartDate-pubEndDate -ikkunan enimmaisleveys
LAHTEET = ("kev", "atlas", "nvd")


def tallenna_raaka(yhteys, tila, pvm, nimi, data):
    """Tallentaa gzip-raakatiedoston tila/raaka/PVM/nimi.gz, ellei sisalto ole sama kuin viimeksi talletettu. Palauttaa True jos tallennettiin."""
    sha = hashlib.sha256(data).hexdigest()
    if tietokanta.viimeinen_tiiviste(yhteys, nimi) == sha:
        return False
    hak = os.path.join(tila, "raaka", pvm)
    os.makedirs(hak, mode=0o750, exist_ok=True)
    polku = os.path.join(hak, nimi + ".gz")
    tmp = polku + ".tmp"
    with open(tmp, "wb") as f:
        f.write(gzip.compress(data, 6, mtime=0))
    os.replace(tmp, polku)
    tietokanta.kirjaa_tiiviste(yhteys, nimi, pvm, sha)
    return True


def _kev(hae, yhteys, tila, pvm, nyt, uni, nvd_paivia):
    data = hae(KEV_URL)
    tallenna_raaka(yhteys, tila, pvm, "kev.json", data)
    return jasentimet.jasenna_kev(data)


def _atlas(hae, yhteys, tila, pvm, nyt, uni, nvd_paivia):
    osoitin = hae(ATLAS_HAKEMISTO + "ATLAS-latest.yaml")
    if len(osoitin) < 100:  # symlink -> kohdetiedoston nimi; nimi validoidaan, ettei data valitse osoitetta vapaasti
        nimi = osoitin.decode("ascii", "replace").strip()
        if not ATLAS_NIMI_RE.match(nimi):
            raise ValueError("atlas: odottamaton osoitin")
        data = hae(ATLAS_HAKEMISTO + nimi)
    else:
        data = osoitin
    tallenna_raaka(yhteys, tila, pvm, "atlas.yaml", data)
    return jasentimet.jasenna_atlas(data)


def _nvd(hae, yhteys, tila, pvm, nyt, uni, nvd_paivia):
    paivia = max(1, min(int(nvd_paivia), NVD_MAX_PAIVIA))
    alku = (nyt - datetime.timedelta(days=paivia)).strftime("%Y-%m-%dT%H:%M:%S.000")
    loppu = nyt.strftime("%Y-%m-%dT%H:%M:%S.000")
    rivit = []
    ensimmainen = True
    for sana in NVD_HAKUSANAT:
        alkuind = 0
        for sivu in range(NVD_MAX_SIVUJA):
            if not ensimmainen:
                uni(NVD_VALI_S)
            ensimmainen = False
            parametrit = urllib.parse.urlencode({"keywordSearch": sana, "pubStartDate": alku, "pubEndDate": loppu,
                                                 "resultsPerPage": NVD_SIVUKOKO, "startIndex": alkuind})
            data = hae(NVD_URL + "?" + parametrit)
            tallenna_raaka(yhteys, tila, pvm, "nvd-%s-%d.json" % (sana.lower(), sivu), data)
            rivit += jasentimet.jasenna_nvd(data, sana.lower())
            yht = _nvd_yhteensa(data)
            alkuind += NVD_SIVUKOKO
            if alkuind >= yht:
                break
    return rivit


def _nvd_yhteensa(data):
    import json
    try:
        return int(json.loads(data.decode("utf-8", "replace")).get("totalResults", 0))
    except (ValueError, AttributeError, TypeError):
        return 0


_LAHDEFUNKTIOT = {"kev": _kev, "atlas": _atlas, "nvd": _nvd}


def aja(tila, lahteet=LAHTEET, nvd_paivia=7, hae=haku.hae, nyt=None, uni=time.sleep, tulosta=print):
    """Ajaa valitut lahteet. Palauttaa (onnistuneet, epaonnistuneet) -sanakirjat: lahde -> uudet rivit / virhetyyppi."""
    nyt = nyt or datetime.datetime.now(datetime.timezone.utc)
    pvm = nyt.strftime("%Y-%m-%d")
    os.makedirs(tila, mode=0o750, exist_ok=True)
    yhteys = tietokanta.avaa(os.path.join(tila, "uhkatieto.sqlite"))
    ok, virheet = {}, {}
    try:
        for lahde in lahteet:
            try:
                rivit = _LAHDEFUNKTIOT[lahde](hae, yhteys, tila, pvm, nyt, uni, nvd_paivia)
                uudet = tietokanta.tallenna(yhteys, rivit, nyt.strftime("%Y-%m-%dT%H:%M:%SZ"))
                tietokanta.kirjaa_ajo(yhteys, nyt.isoformat(), lahde, "ok", uudet, len(rivit))
                ok[lahde] = uudet
                tulosta("%s: ok, %d rivia, %d uutta" % (lahde, len(rivit), uudet))
            except Exception as e:  # vain tyyppi (ja haku.HakuVirheen turvallinen viesti); syotteen sisaltoa ei tulosteta
                kuvaus = str(e) if isinstance(e, haku.HakuVirhe) else type(e).__name__
                tietokanta.kirjaa_ajo(yhteys, nyt.isoformat(), lahde, "virhe", 0, 0)
                virheet[lahde] = kuvaus
                tulosta("%s: VIRHE %s" % (lahde, kuvaus))
    finally:
        yhteys.close()
    return ok, virheet


def main(argv):
    p = argparse.ArgumentParser(prog="uhkatieto", description="Keraa julkiset tietoturvasyotteet (ei LLM:aa, ei lahetyksia).")
    p.add_argument("--tila", default=os.environ.get("UHKATIETO_TILA", "tila"), help="tilahakemisto (raaka/ + uhkatieto.sqlite)")
    p.add_argument("--lahteet", default=",".join(LAHTEET), help="pilkulla erotettu: kev,atlas,nvd")
    p.add_argument("--nvd-paivia", type=int, default=7, help="NVD: montako paivaa taaksepain (oletus 7, enintaan 120)")
    a = p.parse_args(argv)
    valitut = [x.strip() for x in a.lahteet.split(",") if x.strip()]
    tuntematon = [x for x in valitut if x not in LAHTEET]
    if tuntematon:
        print("tuntematon lahde: " + ",".join(tuntematon), file=sys.stderr)
        return 2
    _, virheet = aja(a.tila, valitut, a.nvd_paivia)
    return 1 if virheet else 0
