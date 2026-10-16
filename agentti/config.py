"""Asetukset ja apufunktiot: paivan maaritelma, tilahakemisto, env-tiedoston luku."""
import datetime
import os
import zoneinfo

AIKAVYOHYKE = "Europe/Helsinki"


def nyt():
    return datetime.datetime.now(zoneinfo.ZoneInfo(AIKAVYOHYKE))


def _paikallinen(aika):
    if aika is None:
        return nyt()
    if aika.tzinfo is None:
        raise ValueError("aika vaatii aikavyohykkeen")
    return aika.astimezone(zoneinfo.ZoneInfo(AIKAVYOHYKE))


def paiva(aika=None):
    """Yksi ainoa paivan maaritelma (Europe/Helsinki): 'VVVV-KK-PP'."""
    return _paikallinen(aika).strftime("%Y-%m-%d")


def kuukausi(aika=None):
    return _paikallinen(aika).strftime("%Y-%m")


class EnvVirhe(Exception):
    pass


def lue_env(polku):
    """Lukee KEY=VALUE-tiedoston. Arvoja ei koskaan tulosteta."""
    ulos = {}
    try:
        with open(polku, encoding="utf-8") as f:
            for rivi in f:
                rivi = rivi.strip()
                if rivi and not rivi.startswith("#") and "=" in rivi:
                    k, v = rivi.split("=", 1)
                    ulos[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        raise EnvVirhe("env-tiedostoa ei voi lukea")
    return ulos
