"""Pakotettu kilpatesti: vastaus ei saa lahtea ennen kuin kasittelijan lukko on vapautettu.

Lukon release() viivastetaan. Jos kasittelija lahettaa vastauksen ennen vapautusta, asiakas ehtii nahda
vastauksen ja seuraava acquire(blocking=False) epaonnistuu (satunnainen 429 tuotannossa). Testi tekee
tasta deterministisen."""
import threading
import time
import unittest

from aivo import yksityinen
from aivo.test_yksityinen_hyvaksynta import Pohja

VIIVE = 0.5


class HidasLukko:
    """Kietoo lukon: release() odottaa VIIVE sekunnin ennen oikeaa vapautusta."""

    def __init__(self):
        self.lukko = threading.Lock()

    def acquire(self, blocking=True):
        return self.lukko.acquire(blocking)

    def release(self):
        time.sleep(VIIVE)
        self.lukko.release()


class LukkoKilpaTesti(Pohja):
    def hidasta(self, nimi):
        setattr(self.tila, nimi, HidasLukko())
        return getattr(self.tila, nimi)

    def assertVapaa(self, lukko, selite):
        # vastauksen saanut asiakas voi heti jatkaa: lukon pitaa olla jo vapaa
        self.assertTrue(lukko.acquire(blocking=False), "lukko oli viela varattu vastauksen jalkeen: " + selite)
        lukko.release()

    def test_hyvaksy_onnistuu(self):
        kid = self.uusi()
        eid, s8 = self.ehdota()
        lukko = self.hidasta("ehdotuslukko")
        self.assertEqual(self.hyvaksy(kid, eid, "kyll\u00e4 " + s8)[0], 200)
        self.assertVapaa(lukko, "hyvaksy 200")

    def test_hyvaksy_409(self):
        kid = self.uusi()
        eid, s8 = self.ehdota()
        lukko = self.hidasta("ehdotuslukko")
        self.assertEqual(self.hyvaksy(kid, eid, "kyll\u00e4 00000000")[0], 409)
        self.assertVapaa(lukko, "hyvaksy 409")

    def test_hyvaksy_500(self):
        kid = self.uusi()
        eid, s8 = self.ehdota()
        lukko = self.hidasta("ehdotuslukko")
        vanha = yksityinen.hyvaksy_ehdotus

        def rikki(*a):
            raise OSError("levy taynna")
        yksityinen.hyvaksy_ehdotus = rikki
        try:
            self.assertEqual(self.hyvaksy(kid, eid, "kyll\u00e4 " + s8)[0], 500)
        finally:
            yksityinen.hyvaksy_ehdotus = vanha
        self.assertVapaa(lukko, "hyvaksy 500")

    def test_hylkaa_onnistuu(self):
        kid = self.uusi()
        eid, _ = self.ehdota()
        lukko = self.hidasta("ehdotuslukko")
        s, _ = self.pyynto("POST", "/api/ehdotus/hylkaa", {"keskustelu": kid, "tunnus": eid})
        self.assertEqual(s, 200)
        self.assertVapaa(lukko, "hylkaa 200")

    def test_hylkaa_409(self):
        kid = self.uusi()
        lukko = self.hidasta("ehdotuslukko")
        s, _ = self.pyynto("POST", "/api/ehdotus/hylkaa", {"keskustelu": kid, "tunnus": "ei-ole-olemassa"})
        self.assertEqual(s, 409)
        self.assertVapaa(lukko, "hylkaa 409")

    def test_viesti_yksityinen(self):
        kid = self.uusi()
        lukko = self.hidasta("yks_vastauslukko")
        s, _ = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "moi"})
        self.assertEqual(s, 200)
        self.assertVapaa(lukko, "viesti yksityinen")

    def test_viesti_tyokalutila(self):
        kid = self.uusi("tyokalu")
        lukko = self.hidasta("vastauslukko")
        s, _ = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "moi"})
        self.assertEqual(s, 200)
        self.assertVapaa(lukko, "viesti tyokalutila")


if __name__ == "__main__":
    unittest.main()
