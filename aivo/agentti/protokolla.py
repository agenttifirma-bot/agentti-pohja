"""Tyokaluprotokollan jasennys.

Malli kutsuu tyokalua vastauksensa lopussa yhdella lohkolla:

    [[TYOKALU {"nimi": "lue", "arg": {"polku": "muistio.md"}}]]

Jasennin ei koskaan nosta poikkeusta mallin tekstista: virheellinen JSON, kaksi lohkoa, tuntematon
nimi tai muu rikkeen palautetaan `Jasennys.virhe`-kentassa, jonka silmukka antaa mallille takaisin.
"""
import json
from dataclasses import dataclass

ALKU = "[[TYOKALU"
LOPPU = "]]"
NIMET = ("lue", "kirjoita", "listaa", "valmis")
RAJA_VASTAUS = 400_000    # merkkia; sita pidemman vastauksen lohkoa ei jasenneta


@dataclass(frozen=True)
class Kutsu:
    nimi: str
    arg: dict


@dataclass(frozen=True)
class Jasennys:
    """Tasan yksi kolmesta: kutsu, virhe tai (kumpikin None) pelkka teksti ilman lohkoa."""
    kutsu: object = None      # Kutsu tai None
    virhe: object = None      # merkkijono tai None
    teksti: str = ""          # lohkoa edeltava teksti


def _virhe(syy, teksti=""):
    return Jasennys(virhe=syy, teksti=teksti)


def jasenna(vastaus, sallitut=NIMET):
    """Jasentaa mallin vastauksen. Ei nosta poikkeuksia."""
    try:
        return _jasenna(vastaus, sallitut)
    except Exception as e:  # puolustava reuna: mallin teksti ei saa kaataa silmukkaa
        return _virhe("jasennys epaonnistui (" + type(e).__name__ + ")")


def _jasenna(vastaus, sallitut):
    if not isinstance(vastaus, str):
        return _virhe("vastaus ei ole teksti")
    if len(vastaus) > RAJA_VASTAUS:
        return _virhe("vastaus on liian pitka")
    alku = vastaus.find(ALKU)
    if alku < 0:
        return Jasennys(teksti=vastaus)
    ennen = vastaus[:alku]
    i = alku + len(ALKU)
    if i >= len(vastaus) or not vastaus[i].isspace():
        return _virhe("lohkon muoto on virheellinen: odotettiin [[TYOKALU {json}]]", ennen)
    # raw_decode lukee yhden JSON-arvon: "]]" merkkijonon sisalla (esim. tiedoston sisalto) ei katkaise lohkoa.
    try:
        data, loppu = json.JSONDecoder().raw_decode(vastaus, _ohita_tyhja(vastaus, i))
    except ValueError:
        return _virhe("lohkon JSON on virheellinen", ennen)
    j = _ohita_tyhja(vastaus, loppu)
    if not vastaus.startswith(LOPPU, j):
        return _virhe("lohkon paatemerkki ]] puuttuu", ennen)
    jalkeen = vastaus[j + len(LOPPU):]
    if ALKU in jalkeen:
        return _virhe("vastauksessa on useita tyokalulohkoja; sallittu on yksi", ennen)
    if jalkeen.strip():
        return _virhe("lohko ei ole vastauksen lopussa", ennen)
    if not isinstance(data, dict):
        return _virhe("lohkon pitaa olla JSON-olio", ennen)
    ylimaarat = set(data) - {"nimi", "arg"}
    if ylimaarat:
        return _virhe("lohkossa on tuntemattomia kenttia", ennen)
    nimi = data.get("nimi")
    if not isinstance(nimi, str) or nimi not in sallitut:
        return _virhe("tuntematon tyokalu (sallitut: " + ", ".join(sallitut) + ")", ennen)
    arg = data.get("arg", {})
    if not isinstance(arg, dict):
        return _virhe("arg pitaa olla JSON-olio", ennen)
    return Jasennys(kutsu=Kutsu(nimi, arg), teksti=ennen)


def _ohita_tyhja(teksti, i):
    while i < len(teksti) and teksti[i].isspace():
        i += 1
    return i
