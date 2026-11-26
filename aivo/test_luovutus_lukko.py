"""Luovutuslukon kilpa: virhevastaus saa lahtea vasta, kun luovutuslukko on vapautettu.

Jos vastaus lahtee try-lohkon sisalta, asiakas saa sen ennen finally-lohkon release()-kutsua ja seuraava pyynto voi
saada aiheettoman 429:n (koeyhdistys, tulos 23-10). HidasVapautusLukko venyttaa vapautusta, joten vika toistuu joka
kerta: heti vastauksen jalkeen lukko on yha varattu. Korjatussa koodissa release() on valmis ennen vastausta. Vain stdlib.
"""
import threading
import time
import unittest

from aivo import luovutus
from aivo.test_luovutus import LuovutusPohja


class HidasVapautusLukko:
    """threading.Lock, jonka release() odottaa ensin VIIVE sekuntia ja vapauttaa vasta sitten."""
    VIIVE = 0.3

    def __init__(self):
        self._l = threading.Lock()

    def acquire(self, *a, **k):
        return self._l.acquire(*a, **k)

    def release(self):
        time.sleep(self.VIIVE)
        self._l.release()

    def locked(self):
        return self._l.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *a):
        self.release()


class LuovutusLukkoKilpaTesti(LuovutusPohja):
    def setUp(self):
        super().setUp()
        self.lukko = self.tila.luovutuslukko = HidasVapautusLukko()

    def tarkista_vapaa(self, s, odotettu, nimi):
        self.assertEqual(s, odotettu, nimi)
        self.assertFalse(self.lukko.locked(), "%s: vastaus lahti ennen lukon vapautusta" % nimi)

    def test_hyvaksynnan_409_vapauttaa_lukon_ennen_vastausta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        s = self.hyvaksy_l(kid, "../ulkona", "kyll\u00e4 " + s8)[0]
        self.tarkista_vapaa(s, 409, "hyvaksy 409")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 200)   # perakkainen pyynto ei saa 429:aa

    def test_hyvaksynnan_500_vapauttaa_lukon_ennen_vastausta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        alkup = luovutus.hyvaksy

        def kaatuu(*a, **k):
            raise OSError("levy")
        luovutus.hyvaksy = kaatuu
        try:
            s = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0]
        finally:
            luovutus.hyvaksy = alkup
        self.tarkista_vapaa(s, 500, "hyvaksy 500")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 200)

    def test_hylkayksen_409_vapauttaa_lukon_ennen_vastausta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        s = self.pyynto("POST", "/api/luovutus/hylkaa", {"keskustelu": kid, "tunnus": "../ulkona"})[0]
        self.tarkista_vapaa(s, 409, "hylkaa 409")
        s, d = self.pyynto("POST", "/api/luovutus/hylkaa", {"keskustelu": kid, "tunnus": t})
        self.assertEqual((s, d.get("tulos")), (200, "hylatty"))

    def test_muokkauksen_virhe_vapauttaa_lukon_ennen_vastausta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        s = self.pyynto("POST", "/api/luovutus/muokkaa", {"keskustelu": kid, "tunnus": "../ulkona", "teksti": "y"})[0]
        self.assertIn(s, (400, 409))
        self.assertFalse(self.lukko.locked(), "muokkaa: vastaus lahti ennen lukon vapautusta")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 200)

    def test_kasitellyksi_merkinnan_409_vapauttaa_lukon_ennen_vastausta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 200)
        tkid = self.uusi("tyokalu")
        s = self.pyynto("POST", "/api/saapuneet/kasitelty", {"keskustelu": tkid, "tunnus": "../ulkona"})[0]
        self.tarkista_vapaa(s, 409, "kasitelty 409")
        s, d = self.pyynto("POST", "/api/saapuneet/kasitelty", {"keskustelu": tkid, "tunnus": t})
        self.assertEqual(s, 200)

    def test_polkujen_ohitus_perakkain_ei_saa_429(self):
        """Koeyhdistyksen epavakaan testin kuvio: monta virhepyyntoa perakkain, mikaan ei saa 429:aa."""
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        for paha in ("../ulkona", "/etc/passwd", t.upper()):
            for polku, lisa in (("/api/luovutus/hyvaksy", {"vahvistus": "kyll\u00e4 " + s8}),
                                ("/api/luovutus/muokkaa", {"teksti": "y"}), ("/api/luovutus/hylkaa", {})):
                s = self.pyynto("POST", polku, dict({"keskustelu": kid, "tunnus": paha}, **lisa))[0]
                self.assertIn(s, (400, 409), (polku, paha))


if __name__ == "__main__":
    unittest.main()
