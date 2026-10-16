"""Pieni JSON-skeemavalidaattori (tyypit, required, enum, items, properties).

Tarkoituksella suppea: LLM-vastaus hyvaksytaan vain, jos se tasmaa skeemaan. Ylimaaraisia
kenttia ei sallita (additionalProperties on oletuksena epatosi).
"""

TYYPIT = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
}


class SkeemaVirhe(Exception):
    pass


def _tyyppi_ok(arvo, tyyppi):
    if tyyppi == "integer":
        return isinstance(arvo, int) and not isinstance(arvo, bool)
    if tyyppi == "number":
        return isinstance(arvo, (int, float)) and not isinstance(arvo, bool)
    if tyyppi == "boolean":
        return isinstance(arvo, bool)
    return isinstance(arvo, TYYPIT[tyyppi])


def tarkista(arvo, skeema, polku="$"):
    tyyppi = skeema.get("type")
    if tyyppi is not None:
        if tyyppi not in TYYPIT and tyyppi not in ("integer", "number"):
            raise SkeemaVirhe("%s: tuntematon tyyppi %r skeemassa" % (polku, tyyppi))
        if not _tyyppi_ok(arvo, tyyppi):
            raise SkeemaVirhe("%s: odotettiin %s" % (polku, tyyppi))
    if "enum" in skeema and arvo not in skeema["enum"]:
        raise SkeemaVirhe("%s: arvo ei ole sallittujen joukossa" % polku)
    if isinstance(arvo, str):
        if len(arvo) < skeema.get("minLength", 0):
            raise SkeemaVirhe("%s: liian lyhyt" % polku)
        if len(arvo) > skeema.get("maxLength", 10 ** 9):
            raise SkeemaVirhe("%s: liian pitka" % polku)
    if isinstance(arvo, dict):
        ominaisuudet = skeema.get("properties", {})
        for avain in skeema.get("required", []):
            if avain not in arvo:
                raise SkeemaVirhe("%s: puuttuu kentta %s" % (polku, avain))
        for avain, v in arvo.items():
            if avain in ominaisuudet:
                tarkista(v, ominaisuudet[avain], "%s.%s" % (polku, avain))
            elif not skeema.get("additionalProperties", False):
                raise SkeemaVirhe("%s: ylimaarainen kentta %s" % (polku, avain))
    if isinstance(arvo, list):
        if len(arvo) > skeema.get("maxItems", 10 ** 6):
            raise SkeemaVirhe("%s: liian monta alkiota" % polku)
        if "items" in skeema:
            for i, v in enumerate(arvo):
                tarkista(v, skeema["items"], "%s[%d]" % (polku, i))
