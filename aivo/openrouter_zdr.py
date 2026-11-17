"""ZDR-pakotus OpenRouter-pyyntoihin (kompassi A831, A728).

Puhdas funktio: rakentaa pyynnon rungon ja asettaa aina `provider.zdr = true`
(nollassailytys) ja `provider.data_collection = "deny"`. Ei verkkokutsua, ei avainten lukua. Mallia tai avainta
ei kovakoodata: ne tulevat kutsujalta.

Saannot:
  * Kutsuja ei voi ohittaa zdr:aa (zdr=False, provider.zdr != True tai
    ylimaarainen `zdr`-avain) -> ZdrVirhe.
  * Samassa kohdassa pakotetaan `provider.data_collection = "deny"` (A912): palveluntarjoaja
    ei saa kayttaa dataa koulutukseen. Ohitusyritys (`"allow"`, iso avain, ylimaarainen
    avain) -> ZdrVirhe. Taman moduulin kautta kulkevat kaikki henkilotietoa sisaltavat
    pyynnot; muut pyynnot eivat kulje taman funktion kautta, joten niihin ei koske mikaan.
  * `yksityinen_chat=True` (muutettu avoimesti Tonyn paatoksella A984; aiemmin A728: ei koskaan): sallitaan vain, kun
    (a) ZDR ja data_collection=deny on pakotettu (rakenne ei salli muuta: ohitusyritys -> ZdrVirhe) ja (b) malli on
    avoin malli listalta AVOIMET_MALLIT. Muuten ZdrVirhe. Arvon pitaa olla tasmalleen True tai False. Lippu ei
    poista muita saantoja: katto, avain ja ZDR pysyvat ennallaan. Lippu kuuluu antaa aina yksityisen tilan kutsuissa
    (aivo/yksityinen_or.py), jotta saantoa ei voi kiertaa jattamalla se pois silta, missa sita tarvitaan.
  * Tata moduulia ei ole kytketty mihinkaan ajoon.
  * `OSOITE` on ainoa kiintea tieto: rajapinnan osoite on vain tassa tiedostossa (staattinen vartija
    test_openrouter_zdr.py tarkistaa, ettei se esiinny muualla aivo/-kansiossa). Moduuli ei itse kayta sita.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


OSOITE = "https://openrouter.ai/api/v1/chat/completions"

# Avoimet mallit (painot julkaistu). Etuliite, joka alkaa tasmalleen naista, kelpaa; suljetut saman valmistajan
# mallit (esim. qwen-max, mistral-large) eivat. Uuden perheen lisays vaatii koodimuutoksen ja Tonyn luvan.
AVOIMET_MALLIT = (
    "meta-llama/llama-3",
    "meta-llama/llama-4",
    "qwen/qwen3",
    "qwen/qwen2.5",
    "qwen/qwq",
    "google/gemma-2",
    "google/gemma-3",
    "mistralai/mistral-small",
    "mistralai/mistral-nemo",
    "mistralai/mixtral-",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1",
)
_MALLI_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*(?::[a-z0-9_-]+)?$")
KIELLETYT_LIITTEET = (":free", ":online", ":nitro", ":floor", ":exacto")


def avoin_malli(malli: Any) -> bool:
    """Tosi vain, jos malli on avointen perheiden listalla eika siina ole kiellettya liitetta."""
    if not isinstance(malli, str) or not _MALLI_RE.match(malli):
        return False
    if any(malli.endswith(l) for l in KIELLETYT_LIITTEET):
        return False
    return malli.startswith(AVOIMET_MALLIT)


class ZdrVirhe(ValueError):
    """Pyynto hylatty, koska ZDR-saantoa yritettiin rikkoa."""


def _on_zdr_avain(avain: Any) -> bool:
    """Tosi, jos avain on 'zdr' kirjainkoosta ja ymparoivista valeista riippumatta."""
    return str(avain).strip().lower() == "zdr"


def _on_dc_avain(avain: Any) -> bool:
    """Tosi, jos avain on 'data_collection' kirjainkoosta ja ymparoivista valeista riippumatta."""
    return str(avain).strip().lower() == "data_collection"


# Avaimet, jotka funktio omistaa: kutsuja ei voi antaa niita lisaparametreina.
_VARATUT = frozenset({"model", "messages", "provider"})


def _viestit(viestit: Any) -> list[dict[str, Any]]:
    """Kopioi viestilistan; vaara muoto -> ZdrVirhe (viestin sisaltoa ei nayteta)."""
    if isinstance(viestit, (str, bytes, Mapping)):
        raise ZdrVirhe("viestit pitaa olla lista kuvauksia")
    try:
        tulos = list(viestit)
    except TypeError:
        raise ZdrVirhe("viestit pitaa olla lista kuvauksia") from None
    if not all(isinstance(v, Mapping) for v in tulos):
        raise ZdrVirhe("viestit pitaa olla lista kuvauksia")
    return [dict(v) for v in tulos]


def rakenna_runko(
    malli: str,
    viestit: Iterable[Mapping[str, Any]],
    *,
    yksityinen_chat: bool = False,
    provider: Mapping[str, Any] | None = None,
    **lisa: Any,
) -> dict[str, Any]:
    """Palauttaa OpenRouter chat completions -pyynnon rungon, jossa provider.zdr on True."""
    if yksityinen_chat is not False and yksityinen_chat is not True:
        raise ZdrVirhe("yksityinen_chat pitaa olla True tai False")
    if not isinstance(malli, str) or not malli:
        raise ZdrVirhe("malli puuttuu")
    if yksityinen_chat is True and not avoin_malli(malli):
        raise ZdrVirhe("yksityinen chat sallitaan vain avoimella mallilla (A984)")
    if any(_on_zdr_avain(k) for k in lisa):
        raise ZdrVirhe("zdr ei ole kutsujan asetettavissa")
    if any(_on_dc_avain(k) for k in lisa):
        raise ZdrVirhe("data_collection ei ole kutsujan asetettavissa")
    varatut = _VARATUT.intersection(lisa)
    if varatut:
        raise ZdrVirhe("varattu avain lisaparametreissa")
    prov: dict[str, Any] = {}
    if provider is not None:
        if not isinstance(provider, Mapping):
            raise ZdrVirhe("provider ei ole kuvaus")
        prov = dict(provider)
        # Kaikki zdr-kirjoitusasut ('ZDR', 'Zdr', ' zdr ') kasitellaan samoin:
        # vain tarkka 'zdr': True sallitaan, muuten pyynto hylataan.
        for k, v in prov.items():
            if _on_zdr_avain(k) and not (k == "zdr" and v is True):
                raise ZdrVirhe("provider.zdr pitaa olla True")
            if _on_dc_avain(k) and not (k == "data_collection" and v == "deny"):
                raise ZdrVirhe('provider.data_collection pitaa olla "deny"')
    prov["zdr"] = True
    prov["data_collection"] = "deny"
    runko: dict[str, Any] = dict(lisa)
    runko["model"] = malli
    runko["messages"] = _viestit(viestit)
    runko["provider"] = prov
    return runko
