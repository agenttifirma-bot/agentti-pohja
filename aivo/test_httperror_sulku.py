"""HTTPError-vastaukset suljetaan jokaisessa Aivon verkkokutsupaikassa.

urllib.error.HTTPError pitaa vastauksen (ja oikeassa kutsussa socketin) auki, kunnes se suljetaan.
Jokainen testi antaa kutsupaikalle HTTPError-olion, jonka runko on seurattava BytesIO, ja tarkistaa,
etta runko on suljettu poikkeuskasittelyn jalkeen. Virheilmoitusten sisalto ja paluuarvot pysyvat
ennallaan; ne tarkistetaan samalla. Ei verkkoa, ei tunnistetiedostoja.
"""
import io
import unittest
import urllib.error
import urllib.request
from unittest import mock

from aivo import drive, kalenteri, tiivista_yksityinen, yksityinen, yksityinen_or

KALENTERI_OSOITE = "https://calendar.google.com/calendar/ical/keksitty%40esimerkki.invalid/private-X/basic.ics"
LOOPBACK = "http://127.0.0.1:8081"


def tee_virhe(tila, url="https://esimerkki.invalid/"):
    """HTTPError, jonka runko on seurattava BytesIO (kuten urlopenin palauttama virhevastaus)."""
    runko = io.BytesIO(b"virherunko")
    return urllib.error.HTTPError(url, tila, "x", {}, runko), runko


def nostaja(virhe):
    def avaa(pyynto, timeout=None):
        raise virhe
    return avaa


class HTTPErrorSuljetaan(unittest.TestCase):
    def test_drive_pyynto_sulkee_virheen(self):
        virhe, runko = tee_virhe(403)
        tila, data = drive._pyynto("GET", drive.SALLITUT_ALUT[0], avaa=nostaja(virhe))
        self.assertEqual((tila, data), (403, b""))
        self.assertTrue(runko.closed, "drive._pyynto jatti HTTPError-vastauksen auki")

    def test_kalenteri_hae_https_sulkee_virheen(self):
        virhe, runko = tee_virhe(404, KALENTERI_OSOITE)

        class Avaaja:
            open = staticmethod(nostaja(virhe))

        with mock.patch.object(kalenteri.urllib.request, "build_opener", lambda *a: Avaaja()):
            with self.assertRaises(kalenteri.KalenteriVirhe) as e:
                kalenteri.hae_https(KALENTERI_OSOITE)
        self.assertEqual(str(e.exception), "haku epaonnistui (HTTP 404)")
        self.assertTrue(runko.closed, "kalenteri.hae_https jatti HTTPError-vastauksen auki")

    def test_yksityinen_or_kuljetin_sulkee_virheen(self):
        virhe, runko = tee_virhe(401)
        laheta = yksityinen_or.tee_kuljetin("avain-testi", avaa=nostaja(virhe))
        with self.assertRaises(yksityinen.YksityinenVirhe) as e:
            laheta({"provider": {"zdr": True, "data_collection": "deny"}})
        self.assertEqual(str(e.exception), "mallipalvelu hylkasi pyynnon (HTTP 401)")
        self.assertTrue(runko.closed, "yksityinen_or-kuljetin jatti HTTPError-vastauksen auki")

    def test_yksityinen_kysy_paikalliselta_sulkee_virheen(self):
        virhe, runko = tee_virhe(500)
        with self.assertRaises(yksityinen.YksityinenVirhe) as e:
            yksityinen.kysy_paikalliselta("m", [], "", LOOPBACK, avaa=nostaja(virhe))
        self.assertEqual(str(e.exception), "paikallinen malli ei vastannut (HTTPError)")
        self.assertTrue(runko.closed, "yksityinen.kysy_paikalliselta jatti HTTPError-vastauksen auki")

    def test_tiivista_yksityinen_kysy_paikalliselta_sulkee_virheen(self):
        virhe, runko = tee_virhe(503)
        with self.assertRaises(tiivista_yksityinen.TiivistaVirhe) as e:
            tiivista_yksityinen.kysy_paikalliselta(LOOPBACK, "o", "d", avaa=nostaja(virhe))
        self.assertEqual(str(e.exception), "paikallinen malli ei vastannut (HTTPError)")
        self.assertTrue(runko.closed, "tiivista_yksityinen.kysy_paikalliselta jatti HTTPError-vastauksen auki")

    def test_muu_oserror_ei_kaada_sulkemista(self):
        # Pelkka OSError (ei HTTPError) kulkee samaan haaraan; sulkemisen ei pida kaatua siihen.
        def avaa(pyynto, timeout=None):
            raise ConnectionRefusedError("x")
        with self.assertRaises(yksityinen.YksityinenVirhe) as e:
            yksityinen.kysy_paikalliselta("m", [], "", LOOPBACK, avaa=avaa)
        self.assertEqual(str(e.exception), "paikallinen malli ei vastannut (ConnectionRefusedError)")
        with self.assertRaises(tiivista_yksityinen.TiivistaVirhe):
            tiivista_yksityinen.kysy_paikalliselta(LOOPBACK, "o", "d", avaa=avaa)


if __name__ == "__main__":
    unittest.main()
