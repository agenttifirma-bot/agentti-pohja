import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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


class TilaTarkkaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.polku = os.path.join(self.tmp.name, "tila.json")

    def kirjoita(self, teksti):
        with open(self.polku, "w") as f:
            f.write(teksti)

    def test_oletukset_ja_virheet(self):
        self.assertEqual(k._lue_tila(self.polku), (0, 0))  # puuttuu
        self.kirjoita('{"siirtyma": 5}')
        self.assertEqual(k._lue_tila(self.polku), (5, 0))
        self.kirjoita('{"inode": 7}')
        self.assertEqual(k._lue_tila(self.polku), (0, 7))
        self.kirjoita('{"siirtyma": 5, "inode": 7}')
        self.assertEqual(k._lue_tila(self.polku), (5, 7))
        for huono in ("ei jsonia", "[1, 2]", '{"siirtyma": "x"}', '{"siirtyma": null}'):
            self.kirjoita(huono)
            self.assertEqual(k._lue_tila(self.polku), (0, 0), huono)


class TapahtumaTarkkaTest(unittest.TestCase):
    def test_kulu_ei_mene_tietoihin_muut_kentat_menevat(self):
        t = k.tapahtuma_riveista(*k.jasenna_rivi(KATSAUS_OK))
        self.assertEqual(t["tiedot"], {"tapahtuma": "valmis", "finish": "stop"})
        self.assertEqual(t["kulu_usd"], 0.0074)

    def test_kenttien_maara_rajataan(self):
        rivi = "2026-10-20T07:30:05+03:00 katsaus " + " ".join("k%d=v" % i for i in range(30)) + "\n"
        t = k.tapahtuma_riveista(*k.jasenna_rivi(rivi))
        self.assertEqual(len(t["tiedot"]), k.MAX_KENTTIA)

    def test_virhekoodi_viiva_ei_ole_virhe_ja_negatiivinen_kulu_hylataan(self):
        rivi = "2026-10-20T07:30:05+03:00 katsaus tapahtuma=valmis virhekoodi=- kulu_usd=-1\n"
        t = k.tapahtuma_riveista(*k.jasenna_rivi(rivi))
        self.assertEqual((t["tulos"], t["kulu_usd"]), ("valmis", None))


class KerausTarkkaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loki = os.path.join(self.tmp.name, "a.log")
        self.tila = os.path.join(self.tmp.name, "tila.json")
        self.db = os.path.join(self.tmp.name, "loki.db")

    def kirjoita(self, data, tila="ab"):
        with open(self.loki, tila) as f:
            f.write(data)

    def siirtyma(self):
        with open(self.tila) as f:
            return json.load(f)["siirtyma"]

    def keraa(self, **kw):
        return k.keraa(self.loki, self.tila, self.db, "l", "a", **kw)

    def test_rivikatto_tallentaa_tarkan_tavusiirtyman(self):
        self.kirjoita((KATSAUS_OK * 5).encode())
        self.assertEqual(self.keraa(max_rivia=3), 3)
        self.assertEqual(self.siirtyma(), 3 * len(KATSAUS_OK))
        self.assertEqual(self.keraa(max_rivia=3), 2)
        self.assertEqual(self.siirtyma(), 5 * len(KATSAUS_OK))
        yht = tl.avaa(self.db)
        self.assertEqual(yht.execute("SELECT COUNT(*) FROM tapahtuma").fetchone()[0], 5)
        yht.close()

    def test_monitavuiset_merkit_siirtymassa(self):
        rivi = "2026-10-20T07:30:05+03:00 katsaus tapahtuma=valmis nimi=" + chr(0xE4) + chr(0xF6) + "\n"
        self.kirjoita((rivi * 3).encode("utf-8"))
        self.assertEqual(self.keraa(max_rivia=2), 2)
        self.assertEqual(self.siirtyma(), 2 * len(rivi.encode("utf-8")))
        self.assertEqual(self.keraa(max_rivia=2), 1)

    def test_lukuraja_on_tasan_4_000_000_tavua(self):
        alku = b"2026-10-20T07:30:05+03:00 katsaus tapahtuma=valmis x="
        rivi = alku + b"a" * (4_000_001 - len(alku) - 1) + b"\n"
        self.assertEqual(len(rivi), 4_000_001)
        self.kirjoita(rivi)
        self.assertEqual(self.keraa(), 0)
        self.assertEqual(self.siirtyma(), 0)

    def test_tila_ja_inode_tallentuvat(self):
        self.kirjoita(KATSAUS_OK.encode())
        self.keraa()
        with open(self.tila) as f:
            t = json.load(f)
        self.assertEqual(t, {"siirtyma": len(KATSAUS_OK), "inode": os.stat(self.loki).st_ino})

    def test_vaihtunut_inode_luetaan_alusta(self):
        self.kirjoita((KATSAUS_OK * 2).encode())
        self.keraa()
        with open(self.tila, "w") as f:
            json.dump({"siirtyma": len(KATSAUS_OK), "inode": os.stat(self.loki).st_ino + 1}, f)
        self.assertEqual(self.keraa(), 2)

    def test_sama_inode_jatkaa_siirtymasta(self):
        self.kirjoita((KATSAUS_OK * 2).encode())
        self.keraa()
        self.assertEqual(self.keraa(), 0)


class MainTarkkaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loki = os.path.join(self.tmp.name, "a.log")
        self.tila = os.path.join(self.tmp.name, "tila.json")
        self.db = os.path.join(self.tmp.name, "loki.db")
        with open(self.loki, "w") as f:
            f.write(KATSAUS_OK)

    def aja(self, argv, env=True):
        ulos, virhe = io.StringIO(), io.StringIO()
        ymp = {"TAPAHTUMALOKI": self.db} if env else {}
        with mock.patch.dict(os.environ, ymp, clear=not env), contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = k.main(argv)
        return rc, ulos.getvalue(), virhe.getvalue()

    def test_argumentit_menevat_oikeisiin_paikkoihin(self):
        rc, ulos, _ = self.aja([self.loki, self.tila, "lahde1", "agentti1"])
        self.assertEqual((rc, ulos), (0, "kerattu: 1\n"))
        self.assertTrue(os.path.exists(self.tila))
        yht = tl.avaa(self.db)
        self.assertEqual(yht.execute("SELECT lahde, agentti FROM tapahtuma").fetchall(), [("lahde1", "agentti1")])
        yht.close()

    def test_kayttovirheet(self):
        rc, ulos, virhe = self.aja([self.loki, self.tila, "l"])
        self.assertEqual((rc, ulos), (2, ""))
        self.assertIn("kaytto:", virhe)
        self.assertEqual(self.aja([self.loki, self.tila, "l", "a"], env=False)[0], 2)
        self.assertEqual(self.aja([self.loki, self.tila, "l", "a", "extra"])[0], 2)

    def test_ilman_argumenttia_luetaan_sys_argv(self):
        with mock.patch.object(sys, "argv", ["x", self.loki, self.tila, "l", "a"]):
            rc, ulos, _ = self.aja(None)
        self.assertEqual((rc, ulos), (0, "kerattu: 1\n"))


if __name__ == "__main__":
    unittest.main()
