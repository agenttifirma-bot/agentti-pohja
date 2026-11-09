"""ZDR-pakotus OpenRouter-pyyntoihin (kompassi A831, A728).

Puhdas funktio: rakentaa pyynnon rungon ja asettaa aina `provider.zdr = true`
(nollassailytys). Ei verkkokutsua, ei avainten lukua. Mallia, osoitetta tai
avainta ei kovakoodata: ne tulevat kutsujalta.

Saannot:
  * Kutsuja ei voi ohittaa zdr:aa (zdr=False, provider.zdr != True tai
    ylimaarainen `zdr`-avain) -> ZdrVirhe.
  * `yksityinen_chat=True` -> ZdrVirhe: yksityisen chatin sisalto ei koskaan lahde (A728).
  * Tata moduulia ei ole kytketty mihinkaan ajoon.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


class ZdrVirhe(ValueError):
    """Pyynto hylatty, koska ZDR-saantoa yritettiin rikkoa."""


def _on_zdr_avain(avain: Any) -> bool:
    """Tosi, jos avain on 'zdr' kirjainkoosta ja ymparoivista valeista riippumatta."""
    return str(avain).strip().lower() == "zdr"


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
    if yksityinen_chat is not False:
        raise ZdrVirhe("yksityinen chat ei koskaan lahde OpenRouteriin (A728)")
    if not isinstance(malli, str) or not malli:
        raise ZdrVirhe("malli puuttuu")
    if any(_on_zdr_avain(k) for k in lisa):
        raise ZdrVirhe("zdr ei ole kutsujan asetettavissa")
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
    prov["zdr"] = True
    runko: dict[str, Any] = dict(lisa)
    runko["model"] = malli
    runko["messages"] = _viestit(viestit)
    runko["provider"] = prov
    return runko
