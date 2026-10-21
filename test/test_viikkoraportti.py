import unittest

from agentti import tapahtumaloki as tl
from agentti import viikkoraportti as vr

NYT = 1_000_000.0


class ViikkoraporttiTest(unittest.TestCase):
    def setUp(self):
        self.y = tl.avaa(":memory:")
        self.addCleanup(self.y.close)

    def kirjaa(self, agentti, tulos="ok", kulu=0.0, tiedot=None, ika_pv=1):
        tl.kirjaa(self.y, "yojono", agentti, "ajo", tulos, kulu_usd=kulu, tiedot=tiedot, nyt=NYT - ika_pv * 86400)

    def test_tyhja_loki(self):
        t = vr.keraa(self.y, 7, nyt=NYT)
        self.assertEqual(t["tapahtumia"], 0)
        teksti = vr.muodosta(t, {})
        self.assertIn("Ei tapahtumia", teksti)
        self.assertIn("ei huomautettavaa", teksti)

    def test_kulut_ja_virheet(self):
        self.kirjaa("katsaus", kulu=0.5)
        self.kirjaa("yojono", kulu=1.5)
        self.kirjaa("yojono", tulos="virhe", tiedot={"virhekoodi": "E42"})
        self.kirjaa("yojono", tulos="virhe", tiedot={"virhekoodi": "E42"})
        self.kirjaa("yojono", tulos="virhe")
        t = vr.keraa(self.y, 7, nyt=NYT)
        self.assertEqual(t["tapahtumia"], 5)
        self.assertEqual(t["virheita"], 3)
        self.assertEqual(t["virhekoodit"], {"E42": 2, "tuntematon": 1})
        self.assertAlmostEqual(t["kulu_agentti"]["yojono"], 1.5)

    def test_vanhat_ohitetaan(self):
        self.kirjaa("yojono", kulu=9.0, ika_pv=30)
        self.assertEqual(vr.keraa(self.y, 7, nyt=NYT)["tapahtumia"], 0)

    def test_vihjeet(self):
        self.kirjaa("yojono", kulu=3.0)
        self.kirjaa("katsaus", kulu=0.1)
        for _ in range(3):
            self.kirjaa("yojono", tulos="virhe", tiedot={"virhekoodi": "E7"})
        t = vr.keraa(self.y, 7, nyt=NYT)
        v = " ".join(vr.vihjeet(t, {"levy_kaytetty_pros": 91.0, "muisti_vapaa_pros": 10.0}))
        self.assertIn("yojono", v)
        self.assertIn("E7", v)
        self.assertIn("Levy", v)
        self.assertIn("muistia", v)

    def test_kulu_vihje_vaatii_kaksi_kuluttajaa(self):
        self.kirjaa("yojono", kulu=3.0)
        self.kirjaa("katsaus", kulu=0.0)
        self.assertEqual(vr.vihjeet(vr.keraa(self.y, 7, nyt=NYT), {}), [])

    def test_hyvaksymis_vihje_vaatii_tarpeeksi_paatoksia(self):
        for i in range(4):
            tl.kirjaa_palaute(self.y, tl.ehdota(self.y, "o%d" % i, "p"), "hylkaa")
        self.assertEqual(vr.vihjeet(vr.keraa(self.y, 7, nyt=NYT), {}), [])
        tl.kirjaa_palaute(self.y, tl.ehdota(self.y, "viides", "p"), "hylkaa")
        self.assertTrue(any("hyvaksytty" in v for v in vr.vihjeet(vr.keraa(self.y, 7, nyt=NYT), {})))

    def test_ei_muuta_kantaa_ja_teksti_rajattu(self):
        for i in range(60):
            self.kirjaa("agentti%d" % i, tulos="virhe", kulu=0.1, tiedot={"virhekoodi": "K%d" % i})
        ennen = self.y.execute("SELECT COUNT(*) FROM tapahtuma").fetchone()[0]
        teksti = vr.muodosta(vr.keraa(self.y, 7, nyt=NYT), vr.resurssit())
        self.assertLessEqual(len(teksti), vr.TEKSTI_MAX)
        self.assertEqual(self.y.execute("SELECT COUNT(*) FROM tapahtuma").fetchone()[0], ennen)

    def test_resurssit_palauttaa_avaimet(self):
        self.assertEqual(set(vr.resurssit()), {"levy_kaytetty_pros", "muisti_vapaa_pros", "kuorma_1min"})

    def test_main_kayttovirheet(self):
        self.assertEqual(vr.main(["1", "2"]), 2)
        import os
        os.environ.pop("TAPAHTUMALOKI", None)
        self.assertEqual(vr.main([]), 2)


if __name__ == "__main__":
    unittest.main()
