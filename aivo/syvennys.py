"""Syventaminen yksityisesta chatista: Tonyn painallus kirjoittaa taustaajon tyon (A1040 kohta 2, A1104).

Kulku:
  1. Yksityisen tilan vastauksen alla on painike "Syvenna". Painallus (POST /api/syvenna/uusi) luo vain ehdotuksen
     yksityiseen kansioon (0700, tiedostot 0600). Teksti on Tonyn kysymys palvelimen tallentamasta historiasta,
     ei selaimen lahettamana.
  2. Tony voi muokata tekstia (uusi sha). Tyo kirjoitetaan taustaajon jonoon (taustaajo.kirjoita_tyo) vain
     kutsulla `kaynnista`, jonka vahvistus on tasmalleen "kylla <sha8>" ja sha8 on ehdotuksen tekstin tiiviste.
  3. Ehdotus siirretaan ensin kansioon kaynnistetyt/ (os.rename, atominen). Sama ehdotus ei siksi voi kirjoittaa
     kahta tyota. Jos jonoon kirjoitus epaonnistuu, ehdotus palautetaan odottamaan.

Turvarajat (koodi on laki):
  * Mallin merkinta [[SYVENNA]] on vain vihje painikkeen tekstiin. Se poistetaan vastauksesta, eika se luo
    ehdotusta eika tyota.
  * Este (taustaajon paivaraja tai yhteinen paivakatto) tarkistetaan ennen ehdotusta ja uudelleen ennen jonoon
    kirjoitusta. Rajat ovat taustaajossa ja yksityinen_or:ssa; tama moduuli lukee ne eika muuta niita.
  * Moduuli ei tee mallikutsuja eika verkkokutsuja. Virheviesteissa ei ole tekstin sisaltoa."""
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

from aivo import taustaajo, yksityinen
from aivo.yksityinen import YksityinenVirhe

KANSIO = "syvennykset"            # yksityisen datan viereinen kansio (0700)
KAYNNISTETYT = "kaynnistetyt"
HYLATYT = "hylatyt"
TEHTAVA_YLARAJA = taustaajo.TEHTAVA_YLARAJA
TUNNUS_RE = re.compile(r"\A[0-9a-f]{12}\Z")
VAHVISTUS_RE = re.compile(r"\Akyll\u00e4 [0-9a-f]{8}\Z")
MERKINTA_RE = re.compile(r"[ \t]*\[\[SYVENNA\]\][ \t]*\n?")
ESTEET = {
    "paivaraja": "p\u00e4iv\u00e4n syvent\u00e4misraja on t\u00e4ynn\u00e4 (%d/%d)",
    "kulukatto": "yhteinen p\u00e4iv\u00e4katto (%s \u20ac) on t\u00e4ynn\u00e4",
    "kirjanpito": "kulukirjanpitoa ei voi lukea, joten kutsut on estetty",
    "jono": "taustajonon tilaa ei voi lukea",
}


def _nyt():
    return datetime.now(timezone.utc)


def irrota_merkinta(vastaus):
    """Poistaa mallin vastauksesta [[SYVENNA]]-merkinnat. Palauttaa (teksti, ehdottaa)."""
    if not isinstance(vastaus, str):
        return vastaus, False
    uusi, n = MERKINTA_RE.subn("", vastaus)
    return (uusi.strip() if n else vastaus), n > 0


def puhdista(teksti):
    """Sama puhdistus kuin taustaajo.kirjoita_tyo: jonoon menee tasmalleen kortin teksti."""
    if not isinstance(teksti, str) or not teksti.strip():
        raise YksityinenVirhe("syvennett\u00e4v\u00e4 teksti puuttuu")
    t = "".join(c for c in teksti.strip() if not taustaajo._ohjausmerkki(c))
    if not t:
        raise YksityinenVirhe("syvennett\u00e4v\u00e4 teksti puuttuu")
    if len(t) > TEHTAVA_YLARAJA:
        raise YksityinenVirhe("teksti on liian pitk\u00e4 (%d merkki\u00e4, raja %d)" % (len(t), TEHTAVA_YLARAJA))
    return t


def kysymys(historia, indeksi):
    """Tonyn kysymys, johon vastaus `indeksi` vastasi: lahin aiempi Tonyn viesti. Vastauksen pitaa olla mallin oma
    vastaus (rooli aivo, ei taustavastaus)."""
    if not isinstance(indeksi, int) or isinstance(indeksi, bool) or not 0 <= indeksi < len(historia):
        raise YksityinenVirhe("viesti\u00e4 ei ole")
    v = historia[indeksi]
    if v.get("rooli") != "aivo" or "tausta" in v:
        raise YksityinenVirhe("syvent\u00e4\u00e4 voi vain Aivon vastausta")
    for i in range(indeksi - 1, -1, -1):
        if historia[i].get("rooli") == "tony" and isinstance(historia[i].get("teksti"), str):
            return historia[i]["teksti"]
    raise YksityinenVirhe("vastaukselle ei l\u00f6ydy kysymyst\u00e4")


def este(jono, paivaraja, kulut, nyt=None):
    """None tai (syy, teksti). `kulut` on chat.kulut_yhteenveto-tulos (luettavissa, katto_taynna, paivakatto_eur)."""
    if not kulut.get("luettavissa"):
        return "kirjanpito", ESTEET["kirjanpito"]
    if kulut.get("katto_taynna"):
        return "kulukatto", ESTEET["kulukatto"] % ("%g" % kulut.get("paivakatto_eur", 0))
    try:
        kaytetty = taustaajo.paivan_kaytto(jono, nyt)
    except (taustaajo.TaustaVirhe, OSError):
        return "jono", ESTEET["jono"]
    if kaytetty >= paivaraja:
        return "paivaraja", ESTEET["paivaraja"] % (kaytetty, paivaraja)
    return None


# --- Ehdotukset ----------------------------------------------------------------------------------

def _tunnus(t):
    if not isinstance(t, str) or not TUNNUS_RE.match(t):
        raise YksityinenVirhe("virheellinen syvennyksen tunnus")
    return t


def _kirjoita(polku, d, uusi):
    teksti = json.dumps(d, ensure_ascii=False)
    if uusi:
        fd = os.open(polku, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(teksti)
        return
    tmp = polku.with_name(".%s.%s.tmp" % (polku.name, secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(teksti)
    os.replace(tmp, polku)


def _lue(polku, keskustelu):
    try:
        fd = os.open(polku, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError
            raaka = f.read(4 * TEHTAVA_YLARAJA + 4096 + 1)
        if len(raaka) > 4 * TEHTAVA_YLARAJA + 4096:
            raise ValueError
        d = json.loads(raaka.decode("utf-8"))
        if (not isinstance(d, dict) or not isinstance(d.get("teksti"), str) or not isinstance(d.get("sha"), str)
                or d.get("keskustelu") != keskustelu or yksityinen.sha(d["teksti"]) != d["sha"]):
            raise ValueError
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        raise YksityinenVirhe("syvennyst\u00e4 ei voi lukea") from None
    return d


def tallenna_ehdotus(hakemisto, teksti, keskustelu):
    """Tallentaa ehdotuksen. Ei kirjoita jonoon. Palauttaa tunnuksen (12 heksamerkkia)."""
    teksti = puhdista(teksti)
    if not isinstance(keskustelu, str) or not taustaajo.KID_RE.fullmatch(keskustelu):
        raise YksityinenVirhe("virheellinen keskustelun tunniste")
    h = yksityinen.tarkista_yksityinen_hakemisto(hakemisto)
    t = secrets.token_hex(6)
    _kirjoita(h / (t + ".json"), {"teksti": teksti, "sha": yksityinen.sha(teksti), "keskustelu": keskustelu,
                                  "luotu": _nyt().isoformat(timespec="seconds")}, uusi=True)
    return t


def lue_ehdotus(hakemisto, tunnus, keskustelu):
    """Odottava ehdotus. Toisen keskustelun ehdotus hylataan kuin sita ei olisi."""
    return _lue(Path(hakemisto) / (_tunnus(tunnus) + ".json"), keskustelu)


def muokkaa_ehdotus(hakemisto, tunnus, keskustelu, teksti):
    """Tonyn muokkaus: uusi teksti ja uusi sha. Palauttaa uuden sha:n."""
    d = lue_ehdotus(hakemisto, tunnus, keskustelu)
    d["teksti"] = puhdista(teksti)
    d["sha"] = yksityinen.sha(d["teksti"])
    _kirjoita(Path(hakemisto) / (tunnus + ".json"), d, uusi=False)
    return d["sha"]


def hylkaa_ehdotus(hakemisto, tunnus, keskustelu):
    lue_ehdotus(hakemisto, tunnus, keskustelu)
    kohde = yksityinen.tarkista_yksityinen_hakemisto(Path(hakemisto) / HYLATYT)
    os.rename(Path(hakemisto) / (tunnus + ".json"), kohde / (tunnus + ".json"))


def kaynnista(hakemisto, jono, tunnus, keskustelu, vahvistus, este_, nyt=None):
    """Tonyn painallus: tarkistaa vahvistuksen ja esteen, siirtaa ehdotuksen kaynnistetyt/:iin ja kirjoittaa yhden
    tyon taustaajon jonoon. Palauttaa (tyon tunnus, sha). Mikaan muu ei kutsu taustaajo.kirjoita_tyo-funktiota."""
    if not isinstance(vahvistus, str) or not VAHVISTUS_RE.match(vahvistus):
        raise YksityinenVirhe("vahvistuksen pit\u00e4\u00e4 olla t\u00e4sm\u00e4lleen 'kyll\u00e4 <sha8>'")
    d = lue_ehdotus(hakemisto, tunnus, keskustelu)
    if vahvistus != "kyll\u00e4 " + d["sha"][:8]:
        raise YksityinenVirhe("vahvistus ei vastaa teksti\u00e4 (sha muuttui tai on v\u00e4\u00e4r\u00e4)")
    if este_ is not None:
        raise YksityinenVirhe("syvent\u00e4minen on estetty: " + este_[1])
    h = Path(hakemisto)
    kohde = yksityinen.tarkista_yksityinen_hakemisto(h / KAYNNISTETYT) / (tunnus + ".json")
    try:
        os.rename(h / (tunnus + ".json"), kohde)            # atominen varaus: toinen painallus ei loyda ehdotusta
    except OSError:
        raise YksityinenVirhe("syvennyst\u00e4 ei voi lukea") from None
    try:
        tyo = taustaajo.kirjoita_tyo(jono, keskustelu, d["teksti"], nyt=nyt)
    except (taustaajo.TaustaVirhe, OSError) as e:
        os.rename(kohde, h / (tunnus + ".json"))            # ei tyota: ehdotus odottaa taas
        raise YksityinenVirhe("ty\u00f6t\u00e4 ei voitu kirjoittaa jonoon (%s)" % type(e).__name__) from None
    d.update(tyo=tyo, kaynnistetty=(nyt or _nyt()).isoformat(timespec="seconds"))
    try:
        _kirjoita(kohde, d, uusi=False)
    except OSError:
        pass                                                # tyo on jo jonossa; tieto on vain kirjanpitoa
    return tyo, d["sha"]


def kaynnistys_merkinta(tyo, sha8):
    return ("[J\u00e4rjestelm\u00e4: Tony k\u00e4ynnisti syvent\u00e4misen (ty\u00f6 %s, sha %s). Vastaus tulee "
            "t\u00e4h\u00e4n keskusteluun, kun se on valmis.]" % (tyo, sha8))
