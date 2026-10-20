import os
import sqlite3
import stat
import tempfile
import unittest

from agentti import tapahtumaloki as tl


class LokiTest(unittest.TestCase):
    def setUp(self):
        self.y = tl.avaa(":memory:")
        self.addCleanup(self.y.close)

    def test_kirjaa_ja_yhteenveto(self):
        tl.kirjaa(self.y, "yojono", "katsaus", "ajo", "ok", kulu_usd=0.01, tiedot={"a": 1}, nyt=1000)
        tl.kirjaa(self.y, "yojono", "katsaus", "ajo", "virhe", kulu_usd=0.02, nyt=1000)
        y = tl.yhteenveto(self.y, 7, nyt=1000 + 86400)
        self.assertEqual(y["tapahtumat"], {"ajo/ok": 1, "ajo/virhe": 1})
        self.assertAlmostEqual(y["kulu_usd"], 0.03)

    def test_validointi(self):
        for kw in ({"lahde": ""}, {"agentti": " "}, {"tyyppi": None}, {"kulu_usd": -1}, {"kulu_usd": True}):
            args = dict(lahde="l", agentti="a", tyyppi="t", tulos="r")
            args.update(kw)
            with self.assertRaises(ValueError):
                tl.kirjaa(self.y, **args)

    def test_tapahtumaa_ei_voi_muokata_mutta_vanhenee(self):
        id_ = tl.kirjaa(self.y, "l", "a", "t", "r", nyt=100)
        with self.assertRaises(sqlite3.DatabaseError):
            self.y.execute("UPDATE tapahtuma SET tulos='x' WHERE id=?", (id_,))
        self.assertEqual(tl.siivoa(self.y, 90, nyt=100 + 91 * 86400), 1)
        self.assertEqual(tl.siivoa(self.y, 90, nyt=100 + 91 * 86400), 0)

    def test_salaisuudet_poistuvat(self):
        tl.kirjaa(self.y, "l", "a", "t", "r",
                  tiedot={"avain": "sk-abcdefghijklmnop", "h": "Bearer abc123", "tg": "123456789:" + "A" * 35})
        teksti = self.y.execute("SELECT tiedot_json FROM tapahtuma").fetchone()[0]
        for osa in ("sk-abcdef", "abc123", "AAAAAAAAAA"):
            self.assertNotIn(osa, teksti)
        self.assertIn("[poistettu]", teksti)

    def test_tiedot_rajataan(self):
        tl.kirjaa(self.y, "l", "a", "t", "r", tiedot={"x": "y" * 10000})
        self.assertLessEqual(len(self.y.execute("SELECT tiedot_json FROM tapahtuma").fetchone()[0]), tl.TIEDOT_MAX)

    def test_ehdotus_ja_palaute(self):
        a = tl.ehdota(self.y, "Idea", "toistui 4 kertaa", esitutkimus="ei valmista", mittari="alle 5 min")
        tl.paivita_ehdotus(self.y, a, tila="kokeilussa")
        tl.paivita_ehdotus(self.y, a, tila="onnistui", tulos="toimi")
        tl.kirjaa_palaute(self.y, a, "hyvaksy", "hyva")
        b = tl.ehdota(self.y, "Toinen", "x")
        tl.kirjaa_palaute(self.y, b, "hylkaa")
        y = tl.yhteenveto(self.y)
        self.assertEqual(y["ehdotukset"], {"hyvaksytty": 1, "hylatty": 1})
        self.assertEqual(y["hyvaksymis_pros"], 50.0)

    def test_ehdotus_virheet(self):
        with self.assertRaises(ValueError):
            tl.ehdota(self.y, "", "x")
        with self.assertRaises(ValueError):
            tl.paivita_ehdotus(self.y, 99, tila="onnistui")
        a = tl.ehdota(self.y, "I", "p")
        with self.assertRaises(ValueError):
            tl.paivita_ehdotus(self.y, a, tila="outo")
        with self.assertRaises(ValueError):
            tl.kirjaa_palaute(self.y, a, "ehka")

    def test_palautetta_ei_voi_muokata(self):
        a = tl.ehdota(self.y, "I", "p")
        p = tl.kirjaa_palaute(self.y, a, "hyvaksy")
        with self.assertRaises(sqlite3.DatabaseError):
            self.y.execute("UPDATE palaute SET paatos='hylkaa' WHERE id=?", (p,))

    def test_tyhja_yhteenveto(self):
        self.assertIsNone(tl.yhteenveto(self.y)["hyvaksymis_pros"])

    def test_tiedoston_oikeudet(self):
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "loki.db")
            tl.avaa(polku).close()
            self.assertEqual(stat.S_IMODE(os.stat(polku).st_mode), 0o600)
            tl.avaa(polku).close()  # uudelleenavaus ei riko skeemaa


if __name__ == "__main__":
    unittest.main()
