import os
import tempfile
import unittest

from agentti import loki_keraaja as k
from agentti import tapahtumaloki as tl

KOMENNOT = "2026-10-20T13:38:24+03:00 komennot tapahtuma=tyhja kesto_s=0.17\n"
KATSAUS_OK = "2026-10-20T07:30:05+03:00 katsaus tapahtuma=valmis finish=stop kulu_usd=0.0074\n"
KATSAUS_VIRHE = "2026-10-20T07:30:06+03:00 katsaus finish=length virhekoodi=llm_vastaus_katkaistu\n"


class JasennysTest(unittest.TestCase):
    def test_rivi(self):
        aika, komp, kentat = k.jasenna_rivi(KATSAUS_VIRHE)
        self.assertEqual(komp, "katsaus")
        self.assertEqual(kentat["virhekoodi"], "llm_vastaus_katkaistu")
        self.assertIsInstance(aika, float)

    def test_tuntematon_rivi(self):
        self.assertIsNone(k.jasenna_rivi("roskaa"))
        self.assertIsNone(k.jasenna_rivi("ei-aika katsaus a=b"))
        self.assertIsNone(k.jasenna_rivi(""))

    def test_tapahtumat(self):
        self.assertIsNone(k.tapahtuma_riveista(*k.jasenna_rivi(KOMENNOT)))
        t = k.tapahtuma_riveista(*k.jasenna_rivi(KATSAUS_OK))
        self.assertEqual((t["tyyppi"], t["tulos"], t["kulu_usd"]), ("katsaus", "valmis", 0.0074))
        self.assertEqual(k.tapahtuma_riveista(*k.jasenna_rivi(KATSAUS_VIRHE))["tulos"], "virhe")
        ilman = "2026-10-20T07:30:05+03:00 katsaus finish=stop\n"
        self.assertEqual(k.tapahtuma_riveista(*k.jasenna_rivi(ilman))["tulos"], "ok")

    def test_virheellinen_kulu_ei_kaada(self):
        rivi = "2026-10-20T07:30:05+03:00 katsaus kulu_usd=abc\n"
        self.assertIsNone(k.tapahtuma_riveista(*k.jasenna_rivi(rivi))["kulu_usd"])


class KerausTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loki = os.path.join(self.tmp.name, "a.log")
        self.tila = os.path.join(self.tmp.name, "tila.json")
        self.db = os.path.join(self.tmp.name, "loki.db")

    def kirjoita(self, teksti, tila="a"):
        with open(self.loki, tila) as f:
            f.write(teksti)

    def keraa(self, **kw):
        return k.keraa(self.loki, self.tila, self.db, "paivakatsaus", "paivakatsaus", **kw)

    def rivit(self):
        yht = tl.avaa(self.db)
        try:
            return yht.execute("SELECT lahde, agentti, tyyppi, tulos FROM tapahtuma ORDER BY id").fetchall()
        finally:
            yht.close()

    def test_keraa_ja_ohittaa_hiljaiset(self):
        self.kirjoita(KOMENNOT + KATSAUS_OK + KATSAUS_VIRHE)
        self.assertEqual(self.keraa(), 2)
        self.assertEqual(self.rivit(), [("paivakatsaus", "paivakatsaus", "katsaus", "valmis"),
                                        ("paivakatsaus", "paivakatsaus", "katsaus", "virhe")])

    def test_ei_kahta_kertaa(self):
        self.kirjoita(KATSAUS_OK)
        self.assertEqual(self.keraa(), 1)
        self.assertEqual(self.keraa(), 0)
        self.kirjoita(KATSAUS_VIRHE)
        self.assertEqual(self.keraa(), 1)
        self.assertEqual(len(self.rivit()), 2)

    def test_keskenerainen_rivi_odottaa(self):
        self.kirjoita(KATSAUS_OK + "2026-10-20T07:31:00+03:00 katsaus tapah")
        self.assertEqual(self.keraa(), 1)
        self.kirjoita("tuma=valmis\n")
        self.assertEqual(self.keraa(), 1)
        self.assertEqual(self.rivit()[-1][3], "valmis")

    def test_kierto_luetaan_alusta(self):
        self.kirjoita(KATSAUS_OK + KATSAUS_OK)
        self.keraa()
        self.kirjoita(KATSAUS_VIRHE, tila="w")  # lyhyempi tiedosto
        self.assertEqual(self.keraa(), 1)
        self.assertEqual(self.rivit()[-1][3], "virhe")

    def test_puuttuva_loki(self):
        self.assertEqual(self.keraa(), 0)

    def test_roskarivit_ohitetaan(self):
        self.kirjoita("roskaa\n" + KATSAUS_OK + "\xe4\xf6 rikkinainen\n")
        self.assertEqual(self.keraa(), 1)

    def test_rivikatto_jatkuu_seuraavalla_ajolla(self):
        self.kirjoita(KATSAUS_OK * 5)
        self.assertEqual(self.keraa(max_rivia=3), 3)
        self.assertEqual(self.keraa(max_rivia=3), 2)
        self.assertEqual(self.keraa(max_rivia=3), 0)

    def test_komentorivi(self):
        self.kirjoita(KATSAUS_OK)
        import contextlib
        import io
        from unittest import mock
        with mock.patch.dict(os.environ, {"TAPAHTUMALOKI": self.db}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(k.main([self.loki, self.tila, "x", "y"]), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(k.main([]), 2)


if __name__ == "__main__":
    unittest.main()
