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


# Avaimet, jotka funktio omistaa: kutsuja ei voi antaa niita lisaparametreina.
_VARATUT = frozenset({"model", "messages", "provider"})


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
    if "zdr" in lisa or any(str(k).lower() == "zdr" for k in lisa):
        raise ZdrVirhe("zdr ei ole kutsujan asetettavissa")
    varatut = _VARATUT.intersection(lisa)
    if varatut:
        raise ZdrVirhe("varattu avain lisaparametreissa")
    prov: dict[str, Any] = {}
    if provider is not None:
        if not isinstance(provider, Mapping):
            raise ZdrVirhe("provider ei ole kuvaus")
        prov = dict(provider)
        if "zdr" in prov and prov["zdr"] is not True:
            raise ZdrVirhe("provider.zdr pitaa olla True")
    prov["zdr"] = True
    runko: dict[str, Any] = dict(lisa)
    runko["model"] = malli
    runko["messages"] = [dict(v) for v in viestit]
    runko["provider"] = prov
    return runko
