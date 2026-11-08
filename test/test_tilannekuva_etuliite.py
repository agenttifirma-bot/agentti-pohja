"""Lukitsee sopimuksen: yojono/kehitys.sh kirjoittaa raporttiin rivin '- Testit: ...',
ja agentti/tilannekuva.py poimii sen yojono_osio():n 'Viimeisimmat raportit' -riville.
Jos etuliite muuttuu toisessa paassa, rivi putoaisi tilannekuvasta hiljaa."""
import re
import tempfile
import unittest
from pathlib import Path

from agentti import tilannekuva

JUURI = Path(__file__).resolve().parent.parent
RAPORTTI = """# Kehitys: aihe, repo (2026-11-08)

- Haara: yo/esim
- PR: https://github.com/x/y/pull/1
- Testit: %s

## Muutetut tiedostot
(ei muutoksia)
"""


def _osio(testit_rivi):
    with tempfile.TemporaryDirectory() as t:
        perus = Path(t)
        (perus / "raportit").mkdir()
        (perus / "raportit" / "2026-11-08-01.md").write_text(RAPORTTI % testit_rivi, encoding="utf-8")
        return tilannekuva.yojono_osio(perus)


class TestitEtuliitePoiminta(unittest.TestCase):
    def test_vihrea_lukumaaralla(self):
        rivi = "vihrea, 12 testia (Ran 12 tests in 0.5s OK)"
        self.assertIn("- Testit: " + rivi, _osio(rivi))

    def test_vihrea_ilman_lukumaaraa(self):
        rivi = "vihrea (Ran 12 tests in 0.5s OK)"
        self.assertIn("- Testit: " + rivi, _osio(rivi))

    def test_muu_etuliite_putoaa_pois(self):
        # Vastatesti: nimenmuutos '- Testien tila' ei tule mukaan (sopimus on tarkka).
        with tempfile.TemporaryDirectory() as t:
            perus = Path(t)
            (perus / "raportit").mkdir()
            teksti = (RAPORTTI % "vihrea").replace("- Testit:", "- Testien tila:")
            (perus / "raportit" / "2026-11-08-01.md").write_text(teksti, encoding="utf-8")
            self.assertNotIn("Testien tila", tilannekuva.yojono_osio(perus))


class KehitysShKirjoittaaEtuliitteen(unittest.TestCase):
    def test_kehitys_sh_kirjoittaa_testit_rivin(self):
        lahde = (JUURI / "yojono" / "kehitys.sh").read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r'^\s*echo "- Testit: \$TESTIT"\s*$', lahde, re.M),
            "kehitys.sh ei kirjoita rivia, joka alkaa '- Testit:'")

    def test_etuliite_on_tilannekuvan_poimintalistassa(self):
        lahde = (JUURI / "agentti" / "tilannekuva.py").read_text(encoding="utf-8")
        self.assertIn('"- Testit"', lahde)


if __name__ == "__main__":
    unittest.main()
