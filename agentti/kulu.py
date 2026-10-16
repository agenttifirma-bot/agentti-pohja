"""Kulukirjanpito: varaus ENNEN kutsua, tasaus sen jalkeen. Vikatilassa kutsu estetaan.

Tiedosto: <tila>/kulu.json, lukko <tila>/kulu.lock (flock). Rikkinainen kirjanpito ei nollaudu
hiljaa vaan pysayttaa kutsut (fail closed): parempi ei kutsua kuin ylittaa katto.
"""
import json
import os

from . import config, rajat
from .lukko import kirjoita_atomisesti, lukittu

SAILYTYS_PAIVAA = 62


class KulukattoYlittyi(Exception):
    """syy: kutsut_paiva | kulu_paiva | kulu_kuukausi"""

    def __init__(self, syy):
        super().__init__(syy)
        self.syy = syy


class KirjanpitoVirhe(Exception):
    pass


class Kulu:
    def __init__(self, hakemisto, kello=None):
        self.polku = os.path.join(hakemisto, "kulu.json")
        self.lukko = os.path.join(hakemisto, "kulu.lock")
        self._kello = kello or config.nyt

    def _lue(self):
        try:
            with open(self.polku, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {"paivat": {}}
        except (OSError, ValueError):
            raise KirjanpitoVirhe("kulu.json ei ole luettavissa")
        if not isinstance(data, dict) or not isinstance(data.get("paivat"), dict):
            raise KirjanpitoVirhe("kulu.json rakenne vaara")
        for rivi in data["paivat"].values():
            if not isinstance(rivi, dict) or not isinstance(rivi.get("kutsut"), int) \
                    or not isinstance(rivi.get("usd"), (int, float)):
                raise KirjanpitoVirhe("kulu.json rivi vaara")
        return data

    def _kirjoita(self, data):
        # sailytetaan vain tuoreet paivat; kk-summa tarvitsee nykyisen kuukauden
        avaimet = sorted(data["paivat"])[-SAILYTYS_PAIVAA:]
        data["paivat"] = {k: data["paivat"][k] for k in avaimet}
        kirjoita_atomisesti(self.polku, json.dumps(data, sort_keys=True, indent=1))

    def varaa(self):
        """Tarkistaa katot ja kirjaa varauksen. Palauttaa varaus-dictin kirjaa()-kutsua varten."""
        aika = self._kello()
        paiva, kk = config.paiva(aika), config.kuukausi(aika)
        with lukittu(self.lukko):
            data = self._lue()
            rivi = data["paivat"].setdefault(paiva, {"kutsut": 0, "usd": 0.0})
            kk_summa = sum(r["usd"] for p, r in data["paivat"].items() if p.startswith(kk))
            if rivi["kutsut"] >= rajat.KUTSUT_PAIVA:
                raise KulukattoYlittyi("kutsut_paiva")
            if rivi["usd"] + rajat.KUTSU_ARVIO_USD > rajat.KULU_PAIVA_USD:
                raise KulukattoYlittyi("kulu_paiva")
            if kk_summa + rajat.KUTSU_ARVIO_USD > rajat.KULU_KUUKAUSI_USD:
                raise KulukattoYlittyi("kulu_kuukausi")
            rivi["kutsut"] += 1
            rivi["usd"] = round(rivi["usd"] + rajat.KUTSU_ARVIO_USD, 6)
            self._kirjoita(data)
        return {"paiva": paiva, "arvio": rajat.KUTSU_ARVIO_USD}

    def kirjaa(self, varaus, todellinen_usd=None):
        """Korvaa varauksen todellisella kululla. None = jata pessimistinen varaus."""
        if todellinen_usd is None:
            return
        with lukittu(self.lukko):
            data = self._lue()
            rivi = data["paivat"].get(varaus["paiva"])
            if rivi is None:
                return
            rivi["usd"] = round(max(0.0, rivi["usd"] - varaus["arvio"] + max(0.0, todellinen_usd)), 6)
            self._kirjoita(data)

    def tilanne(self):
        aika = self._kello()
        paiva, kk = config.paiva(aika), config.kuukausi(aika)
        with lukittu(self.lukko):
            data = self._lue()
        rivi = data["paivat"].get(paiva, {"kutsut": 0, "usd": 0.0})
        kk_summa = sum(r["usd"] for p, r in data["paivat"].items() if p.startswith(kk))
        return {"kutsut_tanaan": rivi["kutsut"], "usd_tanaan": rivi["usd"], "usd_kuukausi": round(kk_summa, 6)}
