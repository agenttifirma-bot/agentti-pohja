import io
import unittest
import urllib.error
from unittest import mock

from uhkatieto import haku, tietokanta


def rivi(**kw):
    r = {"lahde": "kev", "id": "A", "pvm": "2026-01-01", "otsikko": "t", "tagit": ["a"], "url": "u"}
    r.update(kw)
    return r


class TallennaTagitTesti(unittest.TestCase):
    def setUp(self):
        self.y = tietokanta.avaa(":memory:")

    def tagit(self):
        return self.y.execute("SELECT tagit FROM uhkat WHERE lahde='kev' AND id='A'").fetchone()[0]

    def test_tagit_yhdistetaan_ilman_duplikaatteja_ja_jarjestys_sailyy(self):
        tietokanta.tallenna(self.y, [rivi(tagit=["a", "b"])], "x")
        self.assertEqual(tietokanta.tallenna(self.y, [rivi(tagit=["b", "c"])], "x"), 0)
        self.assertEqual(self.tagit(), "a,b,c")

    def test_tagit_rajataan_20_kappaleeseen(self):
        tietokanta.tallenna(self.y, [rivi(tagit=["t%d" % i for i in range(15)])], "x")
        tietokanta.tallenna(self.y, [rivi(tagit=["u%d" % i for i in range(15)])], "x")
        tagit = self.tagit().split(",")
        self.assertEqual(len(tagit), 20)
        self.assertEqual(tagit[:15], ["t%d" % i for i in range(15)])

    def test_tyhjat_tagit_tallentuvat_ja_taydentyvat(self):
        tietokanta.tallenna(self.y, [rivi(tagit=[])], "x")
        self.assertEqual(self.tagit(), "")
        tietokanta.tallenna(self.y, [rivi(tagit=["z"])], "x")
        self.assertEqual(self.tagit(), "z")

    def test_vanhat_kentat_ja_haettu_eivat_muutu_paivityksessa(self):
        tietokanta.tallenna(self.y, [rivi()], "ensin")
        tietokanta.tallenna(self.y, [rivi(otsikko="uusi", tagit=["b"])], "myohemmin")
        otsikko, haettu = self.y.execute("SELECT otsikko, haettu FROM uhkat").fetchone()
        self.assertEqual((otsikko, haettu), ("t", "ensin"))


class AjoJaTiivisteTesti(unittest.TestCase):
    def setUp(self):
        self.y = tietokanta.avaa(":memory:")

    def test_kirjaa_ajo_tallentaa_rivin(self):
        tietokanta.kirjaa_ajo(self.y, "2026-11-01T01:00", "nvd", "ok", 3, 10)
        self.assertEqual(self.y.execute("SELECT * FROM ajot").fetchall(),
                         [("2026-11-01T01:00", "nvd", "ok", 3, 10)])

    def test_viimeinen_tiiviste_on_none_kun_tyhja(self):
        self.assertIsNone(tietokanta.viimeinen_tiiviste(self.y, "nvd"))

    def test_viimeinen_tiiviste_palauttaa_uusimman_lahteittain(self):
        tietokanta.kirjaa_tiiviste(self.y, "nvd", "2026-10-30", "aaa")
        tietokanta.kirjaa_tiiviste(self.y, "kev", "2026-10-30", "kkk")
        tietokanta.kirjaa_tiiviste(self.y, "nvd", "2026-10-31", "bbb")
        self.assertEqual(tietokanta.viimeinen_tiiviste(self.y, "nvd"), "bbb")
        self.assertEqual(tietokanta.viimeinen_tiiviste(self.y, "kev"), "kkk")
        self.assertIsNone(tietokanta.viimeinen_tiiviste(self.y, "muu"))

    def test_avaa_on_idempotentti_ja_sailyttaa_datan(self):
        tietokanta.tallenna(self.y, [rivi()], "x")
        self.y.executescript(tietokanta.SKEEMA)
        self.assertEqual(self.y.execute("SELECT COUNT(*) FROM uhkat").fetchone()[0], 1)


class FakeVastaus(io.BytesIO):
    def __init__(self, data=b"", url="https://example.com/x"):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url


class HakuTesti(unittest.TestCase):
    def test_onnistunut_haku_palauttaa_datan_ja_asettaa_otsakkeet_ja_aikarajan(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeVastaus(b"abc")) as uo:
            self.assertEqual(haku.hae("https://example.com/x"), b"abc")
        pyynto = uo.call_args.args[0]
        self.assertEqual(pyynto.get_header("User-agent"), haku.AGENTTI)
        self.assertEqual(uo.call_args.kwargs["timeout"], haku.AIKARAJA)

    def test_uudelleenohjaus_ei_https_hylataan(self):
        vastaus = FakeVastaus(b"x", url="http://example.com/y")
        with mock.patch("urllib.request.urlopen", return_value=vastaus):
            with self.assertRaises(haku.HakuVirhe) as c:
                haku.hae("https://example.com/x")
        self.assertIn("ei-https", str(c.exception))

    def test_http_virhe_kertoo_vain_tilakoodin(self):
        e = urllib.error.HTTPError("https://example.com/x?avain=salainen", 429, "liikaa", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=e):
            with self.assertRaises(haku.HakuVirhe) as c:
                haku.hae("https://example.com/x?avain=salainen")
        self.assertEqual(str(c.exception), "HTTPError 429")

    def test_muu_virhe_kertoo_vain_tyypin_nimen(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("salainen-osoite")):
            with self.assertRaises(haku.HakuVirhe) as c:
                haku.hae("https://example.com/x")
        self.assertEqual(str(c.exception), "TimeoutError")

    def test_liian_suuri_vastaus_hylataan_ja_lukua_rajataan(self):
        suuri = FakeVastaus(b"x" * (haku.MAX_TAVUA + 5))
        with mock.patch("urllib.request.urlopen", return_value=suuri):
            with self.assertRaises(haku.HakuVirhe) as c:
                haku.hae("https://example.com/x")
        self.assertEqual(str(c.exception), "vastaus liian suuri")

    def test_tasan_rajan_kokoinen_vastaus_hyvaksytaan(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeVastaus(b"x" * 100)):
            with mock.patch.object(haku, "MAX_TAVUA", 100):
                self.assertEqual(len(haku.hae("https://example.com/x")), 100)

    def test_ei_https_hylataan_ilman_verkkokutsua(self):
        with mock.patch("urllib.request.urlopen") as uo:
            for url in ("http://example.com", "ftp://example.com", "file:///etc/passwd", ""):
                with self.assertRaises(haku.HakuVirhe):
                    haku.hae(url)
        uo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
