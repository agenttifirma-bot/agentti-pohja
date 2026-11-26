"""Valmis-portti (A515-A516): tila VALMIS vaatii riippumattoman tarkastajan merkinn\u00e4n.

Merkint\u00e4 on tiedosto tulokset/<tulos>.tarkastus.md (esim. tulokset/2026-11-05-17.md -> tulokset/2026-11-05-17.tarkastus.md):
  - Tarkastaja: <malli tai istunto>     (eri mallip\u00e4\u00e4 kuin tuloksen "- Malli:"-rivi; opus = claude-opus-5-5; puuttuva Malli-rivi on ep\u00e4varma = ei kelpaa)
  - Toimii k\u00e4yt\u00f6ss\u00e4: kyll\u00e4 | ei
  - Todiste: <lokirivi, tuloste tai URL>  (tyhj\u00e4 tai pelkk\u00e4 viiva ei kelpaa)
VALMIS ilman kelvollista merkint\u00e4\u00e4 n\u00e4ytet\u00e4\u00e4n tilassa KESKEN. Merkint\u00e4 "Toimii k\u00e4yt\u00f6ss\u00e4: ei" VALMIS-tulokselle
on virhe, jonka virhemittari laskee. Vain stdlib, vain luku."""
import re
from pathlib import Path

PAATE = ".tarkastus.md"
TARKASTAJA_RE = re.compile(r"^[ \t>*_-]*Tarkastaja[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
TOIMII_RE = re.compile(r"^[ \t>*_-]*Toimii k(?:\u00e4|a)yt(?:\u00f6|o)ss(?:\u00e4|a)[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
TODISTE_RE = re.compile(r"^[ \t>*_-]*Todiste[ \t]*:(?:\*\*|__)?[ \t]*(\S.*?)[ \t]*$", re.I | re.M)
MALLI_RE = re.compile(r"^- Malli:[ \t]*(\S.*?)[ \t]*$", re.M)
TYHJA_RE = re.compile(r"^[\s\-\u2013\u2014.:*_]*(?:tbd|todo|n/?a|ei mit(?:\u00e4|a)(?:\u00e4|a)n|ei ole|ei todistetta)?[\s\-\u2013\u2014.:*_]*$", re.I)
# Koko arvo (ei alkuosa): "kyll\u00e4, mutta ei toimi" tai "ok mutta rikki" ei ole kyll\u00e4. Korostusmerkit ja loppupiste sallitaan.
KYLLA_RE = re.compile(r"^[*_`]*(?:kyll(?:\u00e4|a)|ok)[.!]?[*_`]*$", re.I)
EI_RE = re.compile(r"^(?:ei|false)\b", re.I)


def on_tarkastustiedosto(nimi):
    """True, jos tiedostonimi on tarkastusmerkint\u00e4 (*.tarkastus.md) eik\u00e4 jonotulos. Yhteinen suodatin aamukoosteelle ja virhemittarille."""
    return str(nimi).endswith(PAATE)


def tulostiedostot(hakemisto):
    """tulokset-hakemiston jonotulokset (*.md) ilman tarkastusmerkint\u00f6j\u00e4, nimij\u00e4rjestyksess\u00e4."""
    return [p for p in sorted(Path(hakemisto).glob("*.md")) if not on_tarkastustiedosto(p.name)]


def tarkastuspolku(hakemisto, tulosnimi):
    """tulokset-hakemiston tarkastustiedosto tulosnimelle (esim. 'a.md' -> 'a.tarkastus.md')."""
    return Path(hakemisto) / (Path(tulosnimi).stem + PAATE)


def lue(tarkastusteksti):
    """J\u00e4sent\u00e4\u00e4 merkinn\u00e4n: {tarkastaja, toimii (True/False/None), todiste}. Puuttuva kentt\u00e4 on None."""
    teksti = tarkastusteksti or ""
    haku = lambda re_: (lambda m: m.group(1) if m else None)(re_.search(teksti))
    toimii = haku(TOIMII_RE)
    return {"tarkastaja": haku(TARKASTAJA_RE),
            "toimii": True if toimii and KYLLA_RE.match(toimii) else (False if toimii and EI_RE.match(toimii) else None),
            "todiste": haku(TODISTE_RE)}


def _todiste_ok(todiste):
    return bool(todiste) and not TYHJA_RE.match(todiste)


MALLIPERHEET = frozenset(("opus", "sonnet", "haiku", "fable", "deepseek", "qwen"))
KIELTOSANAT = frozenset(("ei", "not", "non", "no", "except", "paitsi"))


def malliperhe(nimi):
    """Normalisoi mallin tai istunnon nimen perheeseen: 'opus', 'claude-opus-5-5', 'Claude Opus 5.5', 'anthropic/claude-opus-5-5:beta',
    'Claude Code (Opus 5.5)', 'claude3opus' ja 'opus-istunto-7' -> 'opus'; 'openrouter:deepseek-flash' -> 'deepseek', 'qwen-coder' -> 'qwen'. Nimi jaetaan kaikista muista merkeist\u00e4 kuin a-z, ja perhe on nimess\u00e4
    esiintyv\u00e4 tunnettu malliperhe (MALLIPERHEET). Tyhj\u00e4, tunnistamaton ('istunto-7', 'Claude Code'), moniselitteinen ('opus/sonnet')
    tai kielletty ('ei opus') nimi -> '' (ep\u00e4varma). Sallilista vain tiukentaa: tuntematon nimi ei ole koskaan 'eri perhe'."""
    tokenit = re.split(r"[^a-z]+", (nimi or "").lower())
    if KIELTOSANAT.intersection(tokenit):
        return ""
    perheet = MALLIPERHEET.intersection(tokenit)
    return next(iter(perheet)) if len(perheet) == 1 else ""


def _riippumaton(tulosteksti, tarkastaja):
    """Riippumaton vain, kun molemmat mallit tunnetaan ja niiden perheet eroavat. Puuttuva '- Malli:'-rivi on ep\u00e4varma = ei kelpaa."""
    if not tarkastaja or TYHJA_RE.match(tarkastaja):
        return False
    malli = MALLI_RE.search(tulosteksti or "")
    if not malli or TYHJA_RE.match(malli.group(1)):
        return False
    tekija, tarkastaja_perhe = malliperhe(malli.group(1)), malliperhe(tarkastaja)
    return bool(tekija) and bool(tarkastaja_perhe) and tekija != tarkastaja_perhe


def kelvollinen(tulosteksti, tarkastusteksti):
    """True, jos merkint\u00e4ss\u00e4 on riippumaton tarkastaja, 'toimii k\u00e4yt\u00f6ss\u00e4: kyll\u00e4' ja todisteviite."""
    if not tarkastusteksti:
        return False
    t = lue(tarkastusteksti)
    return t["toimii"] is True and _todiste_ok(t["todiste"]) and _riippumaton(tulosteksti, t["tarkastaja"])


def toimimaton(tarkastusteksti):
    """True, jos tarkastaja totesi tuloksen toimimattomaksi ('Toimii k\u00e4yt\u00f6ss\u00e4: ei') ja liitti todisteen."""
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
