"""Agenttisilmukka: malli kutsuu tyokaluja, kunnes se kutsuu `valmis` tai jokin raja tayttyy.

Mallifunktio injektoidaan (`malli(viestit) -> str`), joten silmukka ei tunne verkkoa eika
palveluntarjoajaa; testeissa kaytetaan korvikemallia. Kello (`nyt`) on myos injektoitu.

Rajat ovat parametreja (oletukset suunnitelman ehdotuksia), eivat kulu- tai budjettikattoja:
- askelraja: jokainen mallikutsu on askel, myos virheellinen lohko tai lohkoton vastaus;
- aikaraja: tarkistetaan ennen jokaista mallikutsua;
- toisto: saman kutsun (nimi + samat argumentit) TOISTO_RAJA:s perakkainen esiintyma keskeytetaan
  ajamatta sita.
Silmukka ei nosta poikkeusta mallin tekstista eika mallifunktion virheesta (vain tyypin nimi).
"""
import json
import secrets
import time
from dataclasses import dataclass

from . import polut, protokolla, tyokalut

OLETUS_ASKELRAJA = 30
OLETUS_AIKARAJA_S = 20 * 60
TOISTO_RAJA = 3
RAJA_LOKI_SELITE = 200      # merkkia per lokirivin selite

VALMIS = "valmis"
RAJA = "raja"
VIRHE = "virhe"


@dataclass(frozen=True)
class Lokirivi:
    askel: int
    nimi: str       # tyokalun nimi, tai "-" kun vastauksessa ei ollut kelvollista kutsua
    ok: bool
    selite: str     # lyhyt kuvaus (virheilmoitus tai tuloksen koko), ei tiedostojen sisaltoa


@dataclass(frozen=True)
class Tulos:
    tila: str               # VALMIS, RAJA tai VIRHE
    syy: str                # raja: "askelraja", "aikaraja" tai "toisto"; virhe: lyhyt syy
    raportti: str           # valmis-tyokalun raportti (tyhja, ellei tila ole VALMIS)
    loki: tuple             # Lokirivi-oliot jarjestyksessa
    askelia: int
    kesto_s: float


def _kehys(teksti):
    """Tyokalun tulos mallille dataksi merkittyna (satunnainen tunnus estaa kehyksen vaarentamisen)."""
    t = secrets.token_hex(8)
    return "<<<DATA tunnus=%s>>>\n%s\n<<<LOPPU %s>>>" % (t, teksti, t)


def _avain(kutsu):
    try:
        return (kutsu.nimi, json.dumps(kutsu.arg, sort_keys=True, ensure_ascii=True))
    except (TypeError, ValueError):
        return (kutsu.nimi, repr(sorted(kutsu.arg)))


def aja(malli, tehtava, juuri, askelraja=OLETUS_ASKELRAJA, aikaraja_s=OLETUS_AIKARAJA_S, nyt=time.monotonic):
    """Ajaa silmukan tyokansiossa `juuri`. Palauttaa Tulos-olion; ei nosta poikkeusta mallin takia."""
    alku = nyt()
    loki = []
    viestit = [{"role": "user", "content": tehtava}]

    def lopeta(tila, syy, raportti="", askelia=0):
        return Tulos(tila, syy, raportti, tuple(loki), askelia, nyt() - alku)

    try:
        polut.siivoa_valiaikaiset(juuri)     # keskeytyneen kirjoituksen jaannokset eivat laske rajaa
    except (polut.PolkuVirhe, OSError):
        return lopeta(VIRHE, "tyokansiota ei voi avata")

    askelia = 0
    edellinen = None
    toistoja = 0
    while True:
        if askelia >= askelraja:
            return lopeta(RAJA, "askelraja", askelia=askelia)
        if nyt() - alku >= aikaraja_s:
            return lopeta(RAJA, "aikaraja", askelia=askelia)
        try:
            vastaus = malli(list(viestit))
        except Exception as e:  # mallifunktion virhe: vain tyypin nimi, ei viestia
            return lopeta(VIRHE, "mallikutsu epaonnistui (" + type(e).__name__ + ")", askelia=askelia)
        askelia += 1
        viestit.append({"role": "assistant", "content": vastaus if isinstance(vastaus, str) else ""})
        j = protokolla.jasenna(vastaus)
        if j.kutsu is None:
            syy = j.virhe or "vastauksessa ei ollut tyokalulohkoa; kutsu tyokalua tai valmis"
            loki.append(Lokirivi(askelia, "-", False, syy[:RAJA_LOKI_SELITE]))
            viestit.append({"role": "user", "content": _kehys("virhe: " + syy)})
            edellinen = None
            toistoja = 0
            continue
        avain = _avain(j.kutsu)
        toistoja = toistoja + 1 if avain == edellinen else 1
        edellinen = avain
        if toistoja >= TOISTO_RAJA:
            loki.append(Lokirivi(askelia, j.kutsu.nimi, False, "toisto: sama kutsu %d kertaa" % toistoja))
            return lopeta(RAJA, "toisto", askelia=askelia)
        t = tyokalut.suorita(juuri, j.kutsu.nimi, j.kutsu.arg)
        if t.valmis and t.ok:
            loki.append(Lokirivi(askelia, j.kutsu.nimi, True, "raportti %d merkkia" % len(t.teksti)))
            return lopeta(VALMIS, "", t.teksti, askelia)
        selite = ("tulos %d merkkia" % len(t.teksti)) if t.ok else t.teksti[:RAJA_LOKI_SELITE]
        loki.append(Lokirivi(askelia, j.kutsu.nimi, t.ok, selite))
        viestit.append({"role": "user", "content": _kehys(t.teksti if t.ok else "virhe: " + t.teksti)})
