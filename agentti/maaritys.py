"""Agenttimaaritys: yksi JSON-tiedosto kuvaa agentin (doc 34 kohta 4). Vain tarkistus, ei suoritusta.

Tonyn muokattava osa on ohjetiedosto (`ohje_tiedosto`, vapaa teksti). Muut kentat ovat rajattuja:
jokainen arvo tarkistetaan ja kovakoodatut rajat (rajat.py) ovat kattona, joten maaritys ei voi
nostaa kulu- tai tokenrajaa lakia suuremmaksi. Datavyohyke 2 (henkilokohtainen) ei saa lukea
ulkopuolista sisaltoa samassa agentissa (prompt injection -suoja).

Kentat:
  nimi, kuvaus, ohje_tiedosto (suhteellinen polku, ei ..), malli, budjetti_usd_paivassa,
  max_tokens, vyohyke (1|2), oikeustaso ("sandbox"|"rajattu"), tyokalut (lista), lahteet
  (lista, kukin "paikallinen:<nimi>" tai "ulkoinen:<nimi>"), tulosmuoto, mittari (teksti),
  ajastus (systemd OnCalendar-muoto, yksinkertaistettu), halytys ("telegram"|"ei").
"""
import json
import re

from . import rajat

NIMI = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
POLKU = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,99}$")
MALLI = re.compile(r"^[A-Za-z0-9_./:-]{1,80}$")
LAHDE = re.compile(r"^(paikallinen|ulkoinen):[a-z0-9_.-]{1,60}$")
AJASTUS = re.compile(r"^(daily|weekly|hourly|(Mon|Tue|Wed|Thu|Fri|Sat|Sun)( \*)? \d{2}:\d{2}|\d{2}:\d{2}|\*-\*-\* \d{2}:\d{2}:\d{2})$")
WEB_TYOKALUT = frozenset({"hae_github", "hae_npm", "hae_netista", "hae_sivu"})  # lukevat ulkopuolista sisaltoa
TYOKALUT_SALLITUT = frozenset({"lue_tiedosto", "hae_github", "hae_npm", "laheta_telegram", "kirjaa_loki", "hae_netista", "hae_sivu", "ehdota_muutos"})
OIKEUSTASOT = ("sandbox", "rajattu")
KENTAT = {"nimi", "kuvaus", "ohje_tiedosto", "malli", "budjetti_usd_paivassa", "max_tokens", "vyohyke",
          "oikeustaso", "tyokalut", "lahteet", "tulosmuoto", "mittari", "ajastus", "halytys"}
PAKOLLISET = KENTAT - {"tyokalut", "lahteet"}


class MaaritysVirhe(Exception):
    """Sisaltaa kaikki loydetyt virheet: .virheet (lista merkkijonoja)."""

    def __init__(self, virheet):
        super().__init__("; ".join(virheet))
        self.virheet = virheet


def _teksti(arvo, raja):
    return isinstance(arvo, str) and 0 < len(arvo.strip()) <= raja


def tarkista(m):
    """Palauttaa normalisoidun maarityksen (kopio) tai nostaa MaaritysVirhe."""
    if not isinstance(m, dict):
        raise MaaritysVirhe(["maaritys ei ole objekti"])
    v = []
    for k in sorted(set(m) - KENTAT):
        v.append("tuntematon kentta: %s" % k)
    for k in sorted(PAKOLLISET - set(m)):
        v.append("puuttuu: %s" % k)
    if v:
        raise MaaritysVirhe(v)
    if not (isinstance(m["nimi"], str) and NIMI.match(m["nimi"])):
        v.append("nimi: pienet kirjaimet, numerot, _ ja -, 2-40 merkkia, alkaa kirjaimella")
    if not _teksti(m["kuvaus"], 300):
        v.append("kuvaus: 1-300 merkkia")
    if not (isinstance(m["ohje_tiedosto"], str) and POLKU.match(m["ohje_tiedosto"]) and ".." not in m["ohje_tiedosto"]
            and not m["ohje_tiedosto"].startswith("/")):
        v.append("ohje_tiedosto: suhteellinen polku ilman ..")
    if not (isinstance(m["malli"], str) and MALLI.match(m["malli"])):
        v.append("malli: tuntematon muoto")
    b = m["budjetti_usd_paivassa"]
    if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 < b <= rajat.KULU_PAIVA_USD:
        v.append("budjetti_usd_paivassa: yli 0 ja enintaan %s (laki)" % rajat.KULU_PAIVA_USD)
    t = m["max_tokens"]
    if isinstance(t, bool) or not isinstance(t, int) or not 0 < t <= rajat.MAX_TOKENS:
        v.append("max_tokens: 1-%d (laki)" % rajat.MAX_TOKENS)
    if m["vyohyke"] not in (1, 2) or isinstance(m["vyohyke"], bool):
        v.append("vyohyke: 1 tai 2 (3 ei ole kaytossa)")
    if m["oikeustaso"] not in OIKEUSTASOT:
        v.append("oikeustaso: " + " | ".join(OIKEUSTASOT))
    tyokalut = m.get("tyokalut", [])
    if not isinstance(tyokalut, list) or any(x not in TYOKALUT_SALLITUT for x in tyokalut):
        v.append("tyokalut: sallitut " + ", ".join(sorted(TYOKALUT_SALLITUT)))
    lahteet = m.get("lahteet", [])
    if not isinstance(lahteet, list) or any(not (isinstance(x, str) and LAHDE.match(x)) for x in lahteet):
        v.append("lahteet: muoto paikallinen:<nimi> tai ulkoinen:<nimi>")
    if not _teksti(m["tulosmuoto"], 60):
        v.append("tulosmuoto: 1-60 merkkia")
    if not _teksti(m["mittari"], 300):
        v.append("mittari: 1-300 merkkia (etukateen sovittu onnistumisen mittari)")
    if not (isinstance(m["ajastus"], str) and AJASTUS.match(m["ajastus"])):
        v.append("ajastus: esim. daily, 07:30, Mon 17:30, *-*-* 07:30:00")
    if m["halytys"] not in ("telegram", "ei"):
        v.append("halytys: telegram | ei")
    if not v:
        ulkoinen = any(x.startswith("ulkoinen:") for x in lahteet)
        if m["vyohyke"] == 2 and ulkoinen:
            v.append("vyohyke 2 ei saa lukea ulkopuolista sisaltoa (ulkoinen:-lahde)")
        if m["vyohyke"] == 2 and any(x in WEB_TYOKALUT for x in tyokalut):
            v.append("vyohyke 2 ei saa kayttaa verkkohakutyokaluja")
    if v:
        raise MaaritysVirhe(v)
    tulos = dict(m)
    tulos["tyokalut"] = list(tyokalut)
    tulos["lahteet"] = list(lahteet)
    return tulos


def lue(polku):
    """Lukee ja tarkistaa maarityksen JSON-tiedostosta."""
    try:
        with open(polku, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise MaaritysVirhe(["luku epaonnistui: %s" % type(e).__name__])
    return tarkista(data)
