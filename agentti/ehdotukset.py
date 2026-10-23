"""Ehdotukset: agentti voi VAIN ehdottaa uutta ohjetta. Hyvaksynta on tama koodi, jota ajaa omistaja (root).

Portti-prosessilla (kayttaja portti) on kirjoitusoikeus vain ehdotushakemistoon, ei ohjetiedostoon. Ohje
vaihtuu vasta, kun omistaja ajaa komennon `hyvaksy` (python3 -m agentti.portti hyvaksy <id>). Vanha ohje
tallennetaan versiohakemistoon, joten kaikki muutokset ovat palautettavissa. Jos ohje on ehtinyt muuttua
ehdotuksen jalkeen, ehdotus on vanhentunut eika sita voi hyvaksya.
"""
import difflib
import hashlib
import json
import os
import re
import time

from .lukko import kirjoita_atomisesti, lukittu

OHJE_MAX = 20000
PERUSTELU_MAX = 2000
LAHTEET_MAX = 10
LAHDE_MAX = 500
ODOTTAVIA_MAX = 20
TUNNUS_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}-\d{8}-\d{6}(-\d+)?$")


class EhdotusVirhe(Exception):
    pass


def tiiviste(teksti):
    return hashlib.sha256(teksti.encode("utf-8")).hexdigest()


def _hakemisto(tila):
    return os.path.join(tila, "ehdotukset")


def _polku(tila, tunnus):
    if not isinstance(tunnus, str) or not TUNNUS_RE.match(tunnus):
        raise EhdotusVirhe("virheellinen tunnus")
    return os.path.join(_hakemisto(tila), tunnus + ".json")


def _lue(polku):
    try:
        with open(polku, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        raise EhdotusVirhe("ehdotusta ei loydy")
    except (OSError, ValueError):
        raise EhdotusVirhe("ehdotus ei ole luettavissa")
    if not isinstance(d, dict) or d.get("tila") not in ("odottaa", "hyvaksytty", "hylatty") or not isinstance(d.get("ohje"), str):
        raise EhdotusVirhe("ehdotuksen rakenne vaara")
    return d


def listaa(tila, vain_odottavat=True):
    ulos = []
    try:
        nimet = sorted(os.listdir(_hakemisto(tila)))
    except FileNotFoundError:
        return ulos
    for n in nimet:
        if not n.endswith(".json") or not TUNNUS_RE.match(n[:-5]):
            continue
        try:
            d = _lue(os.path.join(_hakemisto(tila), n))
        except EhdotusVirhe:
            continue
        if d["tila"] == "odottaa" or not vain_odottavat:
            ulos.append(d)
    return ulos


def luo(tila, agentti, vanha_ohje, ohje, perustelu, lahteet, nyt=None):
    """Tallentaa ehdotuksen tilaan odottaa. Palauttaa tunnuksen. Ei muuta ohjetta."""
    if not isinstance(ohje, str) or not ohje.strip() or len(ohje) > OHJE_MAX:
        raise EhdotusVirhe("ohjeen pitaa olla 1-%d merkkia" % OHJE_MAX)
    if ohje.strip() == vanha_ohje.strip():
        raise EhdotusVirhe("ehdotus on sama kuin nykyinen ohje")
    perustelu = perustelu if isinstance(perustelu, str) else ""
    if not perustelu.strip() or len(perustelu) > PERUSTELU_MAX:
        raise EhdotusVirhe("perustelun pitaa olla 1-%d merkkia" % PERUSTELU_MAX)
    lahteet = lahteet if isinstance(lahteet, list) else []
    lahteet = [str(x)[:LAHDE_MAX] for x in lahteet[:LAHTEET_MAX] if isinstance(x, str)]
    os.makedirs(_hakemisto(tila), mode=0o700, exist_ok=True)
    with lukittu(os.path.join(tila, "ehdotukset.lock")):
        if sum(1 for d in listaa(tila) if d.get("agentti") == agentti) >= ODOTTAVIA_MAX:
            raise EhdotusVirhe("liikaa odottavia ehdotuksia: kasittele ne ensin")
        aika = time.localtime(nyt)
        pohja = "%s-%s" % (agentti, time.strftime("%Y%m%d-%H%M%S", aika))
        tunnus, n = pohja, 1
        while os.path.exists(os.path.join(_hakemisto(tila), tunnus + ".json")):
            n += 1
            tunnus = "%s-%d" % (pohja, n)
        kirjoita_atomisesti(os.path.join(_hakemisto(tila), tunnus + ".json"), json.dumps({
            "id": tunnus, "agentti": agentti, "tila": "odottaa", "luotu": time.strftime("%Y-%m-%d %H:%M:%S", aika),
            "vanha_tiiviste": tiiviste(vanha_ohje), "ohje": ohje, "perustelu": perustelu, "lahteet": lahteet,
        }, ensure_ascii=False, indent=1))
    return tunnus


def nayta(tila, tunnus, nykyinen_ohje):
    """Palauttaa tekstin: perustelu, lahteet ja diff nykyisesta ohjeesta ehdotettuun."""
    d = _lue(_polku(tila, tunnus))
    ero = "".join(difflib.unified_diff(nykyinen_ohje.splitlines(True), d["ohje"].splitlines(True), "nykyinen", "ehdotus"))
    vanhentunut = d["tila"] == "odottaa" and tiiviste(nykyinen_ohje) != d["vanha_tiiviste"]
    return "Ehdotus %s (%s)%s\nAgentti: %s, luotu %s\nPerustelu: %s\nLahteet: %s\n\n%s" % (
        d["id"], d["tila"], " VANHENTUNUT (ohje on muuttunut)" if vanhentunut else "", d["agentti"], d["luotu"],
        d["perustelu"], ", ".join(d["lahteet"]) or "-", ero or "(ei eroa)")


def _palauta_oikeudet(polku, ennen):
    """kirjoita_atomisesti luo tiedoston oikeuksilla 600 (mkstemp): palautetaan entiset, jotta portti-kayttaja
    voi edelleen lukea ohjeen. Muuten portti kayttaisi hiljaa vanhaa ohjetta."""
    os.chmod(polku, ennen.st_mode & 0o7777)
    try:
        os.chown(polku, ennen.st_uid, ennen.st_gid)
    except (PermissionError, AttributeError, OSError):
        pass  # ei rootina: omistaja jaa ennalleen jo luonnostaan


def _merkitse(polku, d, tila):
    d["tila"] = tila
    d["kasitelty"] = time.strftime("%Y-%m-%d %H:%M:%S")
    kirjoita_atomisesti(polku, json.dumps(d, ensure_ascii=False, indent=1))


def hylkaa(tila, tunnus):
    polku = _polku(tila, tunnus)
    with lukittu(os.path.join(tila, "ehdotukset.lock")):
        d = _lue(polku)
        if d["tila"] != "odottaa":
            raise EhdotusVirhe("ehdotus on jo kasitelty (%s)" % d["tila"])
        _merkitse(polku, d, "hylatty")


def hyvaksy(tila, tunnus, ohjepolku):
    """Kirjoittaa ehdotetun ohjeen ohjetiedostoon. Vanha ohje talteen: <ohjepolku>.versiot/<aika>.md"""
    polku = _polku(tila, tunnus)
    with lukittu(os.path.join(tila, "ehdotukset.lock")):
        d = _lue(polku)
        if d["tila"] != "odottaa":
            raise EhdotusVirhe("ehdotus on jo kasitelty (%s)" % d["tila"])
        with open(ohjepolku, encoding="utf-8") as f:
            vanha = f.read()
        if tiiviste(vanha) != d["vanha_tiiviste"]:
            raise EhdotusVirhe("ehdotus on vanhentunut: ohje on muuttunut sen jalkeen")
        versiot = ohjepolku + ".versiot"
        os.makedirs(versiot, exist_ok=True)
        kirjoita_atomisesti(os.path.join(versiot, time.strftime("%Y%m%d-%H%M%S") + "-ennen-" + tunnus + ".md"), vanha)
        tila_ennen = os.stat(ohjepolku)
        kirjoita_atomisesti(ohjepolku, d["ohje"])
        _palauta_oikeudet(ohjepolku, tila_ennen)
        _merkitse(polku, d, "hyvaksytty")
