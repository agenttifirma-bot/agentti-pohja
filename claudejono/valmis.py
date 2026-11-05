"""Valmis-portti (A515-A516): tila VALMIS vaatii riippumattoman tarkastajan merkinnän.

Merkintä on tiedosto tulokset/<tulos>.tarkastus.md (esim. tulokset/2026-11-05-17.md -> tulokset/2026-11-05-17.tarkastus.md):
  - Tarkastaja: <malli tai istunto>     (eri kuin tuloksen "- Malli:"-rivi; sama arvo ei ole riippumaton)
  - Toimii käytössä: kyllä | ei
  - Todiste: <lokirivi, tuloste tai URL>  (tyhjä tai pelkkä viiva ei kelpaa)
VALMIS ilman kelvollista merkintää näytetään tilassa KESKEN. Merkintä "Toimii käytössä: ei" VALMIS-tulokselle
on virhe, jonka virhemittari laskee. Vain stdlib, vain luku."""
import re
from pathlib import Path

PAATE = ".tarkastus.md"
TARKASTAJA_RE = re.compile(r"^[ \t>*_-]*Tarkastaja[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
TOIMII_RE = re.compile(r"^[ \t>*_-]*Toimii k(?:ä|a)yt(?:ö|o)ss(?:ä|a)[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
TODISTE_RE = re.compile(r"^[ \t>*_-]*Todiste[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
MALLI_RE = re.compile(r"^- Malli:[ \t]*(\S.*?)[ \t]*$", re.M)
TYHJA_RE = re.compile(r"^[\s\-–—.:*_]*(?:tbd|todo|n/?a|ei mit(?:ä|a)(?:ä|a)n|ei ole|ei todistetta)?[\s\-–—.:*_]*$", re.I)
KYLLA_RE = re.compile(r"^(?:kyll(?:ä|a)|on|ok)\b", re.I)
EI_RE = re.compile(r"^(?:ei|false)\b", re.I)


def tarkastuspolku(hakemisto, tulosnimi):
    """tulokset-hakemiston tarkastustiedosto tulosnimelle (esim. 'a.md' -> 'a.tarkastus.md')."""
    return Path(hakemisto) / (Path(tulosnimi).stem + PAATE)


def lue(tarkastusteksti):
    """Jäsentää merkinnän: {tarkastaja, toimii (True/False/None), todiste}. Puuttuva kenttä on None."""
    teksti = tarkastusteksti or ""
    haku = lambda re_: (lambda m: m.group(1) if m else None)(re_.search(teksti))
    toimii = haku(TOIMII_RE)
    return {"tarkastaja": haku(TARKASTAJA_RE),
            "toimii": True if toimii and KYLLA_RE.match(toimii) else (False if toimii and EI_RE.match(toimii) else None),
            "todiste": haku(TODISTE_RE)}


def _todiste_ok(todiste):
    return bool(todiste) and not TYHJA_RE.match(todiste)


def _riippumaton(tulosteksti, tarkastaja):
    if not tarkastaja or TYHJA_RE.match(tarkastaja):
        return False
    malli = MALLI_RE.search(tulosteksti or "")
    return not (malli and malli.group(1).strip().lower() == tarkastaja.strip().lower())


def kelvollinen(tulosteksti, tarkastusteksti):
    """True, jos merkintässä on riippumaton tarkastaja, 'toimii käytössä: kyllä' ja todisteviite."""
    if not tarkastusteksti:
        return False
    t = lue(tarkastusteksti)
    return t["toimii"] is True and _todiste_ok(t["todiste"]) and _riippumaton(tulosteksti, t["tarkastaja"])


def toimimaton(tarkastusteksti):
    """True, jos tarkastaja totesi tuloksen toimimattomaksi ('Toimii käytössä: ei') ja liitti todisteen."""
    t = lue(tarkastusteksti)
    return t["toimii"] is False and _todiste_ok(t["todiste"])


def lue_tarkastus(hakemisto, tulosnimi):
    try:
        return tarkastuspolku(hakemisto, tulosnimi).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def tehokas_tila(tila, tulosteksti, tarkastusteksti):
    """VALMIS ilman kelvollista tarkastusta -> KESKEN; muut tilat sellaisenaan."""
    if tila == "VALMIS" and not kelvollinen(tulosteksti, tarkastusteksti):
        return "KESKEN"
    return tila
