import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from agentti import peilaus


class PeilausTesti(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.perus, self.kohde = self.t / "perus", self.t / "kohde"
        (self.perus / "raportit").mkdir(parents=True)

    def raportti(self, nimi, teksti, ika_pv=0):
        p = self.perus / "raportit" / nimi
        p.write_text(teksti)
        t = time.time() - ika_pv * 86400
        os.utime(p, (t, t))

    def test_kopioi_siivottuna(self):
        self.raportti("a.md", "# A\navain ghp_" + "x" * 30 + " loppu\n")
        (self.perus / "tila.json").write_text(json.dumps({"tehtavat": {}}))
        n = peilaus.peilaa(self.perus, self.kohde)
        self.assertEqual(n, 2)
        teksti = (self.kohde / "raportit" / "a.md").read_text()
        self.assertIn("[poistettu]", teksti)
        self.assertNotIn("ghp_", teksti)
        self.assertTrue((self.kohde / "tila.json").exists())
        self.assertTrue((self.kohde / "paivitetty.txt").exists())

    def test_vanhat_ja_muut_tiedostot_pois(self):
        self.raportti("uusi.md", "u")
        self.raportti("vanha.md", "v", ika_pv=30)
        self.raportti("kuva.png", "x")
        peilaus.peilaa(self.perus, self.kohde, paivia=14)
        nimet = sorted(p.name for p in (self.kohde / "raportit").iterdir())
        self.assertEqual(nimet, ["uusi.md"])

    def test_kohde_vastaa_lahdetta_poistuneet_poistetaan(self):
        self.raportti("a.md", "a")
        peilaus.peilaa(self.perus, self.kohde)
        (self.perus / "raportit" / "a.md").unlink()
        peilaus.peilaa(self.perus, self.kohde)
        self.assertEqual(list((self.kohde / "raportit").iterdir()) if (self.kohde / "raportit").exists() else [], [])

    def test_puuttuva_lahde_ei_kaada(self):
        self.assertEqual(peilaus.peilaa(self.t / "ei-ole", self.kohde), 0)

    def test_suuri_tiedosto_katkaistaan(self):
        self.raportti("iso.md", "x" * (peilaus.MAX_KOKO + 5000))
        peilaus.peilaa(self.perus, self.kohde)
        self.assertLessEqual(len((self.kohde / "raportit" / "iso.md").read_text()), peilaus.MAX_KOKO + 2)

    def test_main_virheet(self):
        self.assertEqual(peilaus.main([]), 2)
        self.assertEqual(peilaus.main(["a", "b", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
