"""Lukitsee sopimuksen: yojono/kehitys.sh kirjoittaa raporttiin rivin '- Testit: ...',
ja agentti/tilannekuva.py poimii sen yojono_osio():n 'Viimeisimmat raportit' -riville.
Jos etuliite muuttuu toisessa paassa, rivi putoaisi tilannekuvasta hiljaa."""
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from agentti import tilannekuva

JUURI = Path(__file__).resolve().parent.parent
# yojono_osio valitsee raportit tiedostojen muokkausajan (mtime) mukaan, ei nimen paivamaarasta.
# Nimi ja otsikko muodostetaan silti tanaisesta paivasta, jotta testi ei riipu kiinteasta pvm:sta.
PVM = date.today().isoformat()
RAPORTTINIMI = PVM + "-01.md"
RAPORTTI = """# Kehitys: aihe, repo (""" + PVM + """)

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
        (perus / "raportit" / RAPORTTINIMI).write_text(RAPORTTI % testit_rivi, encoding="utf-8")
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
            (perus / "raportit" / RAPORTTINIMI).write_text(teksti, encoding="utf-8")
            osio = tilannekuva.yojono_osio(perus)
            # Positiivinen kontrolli: sama raportti on mukana (nimi ja '- PR'-rivi), joten
            # puuttuminen johtuu etuliitteesta eika raportin suodattumisesta pois.
            self.assertIn(RAPORTTINIMI, osio)
            self.assertIn("- PR: https://github.com/x/y/pull/1", osio)
            self.assertNotIn("Testien tila", osio)


class KehitysShKirjoittaaEtuliitteen(unittest.TestCase):
    def test_kehitys_sh_kirjoittaa_testit_rivin(self):
        lahde = (JUURI / "yojono" / "kehitys.sh").read_text(encoding="utf-8")
        self.assertTrue(
            # Sallii echo/printf ja ' tai " -lainausmerkin; vaatii vain etuliitteen ja $TESTIT-arvon samalla rivilla.
            re.search(r'^\s*(echo|printf)\b.*- Testit: \$\{?TESTIT\}?', lahde, re.M),
            "kehitys.sh ei kirjoita rivia, joka alkaa '- Testit:'")

    def test_etuliite_on_tilannekuvan_poimintalistassa(self):
        lahde = (JUURI / "agentti" / "tilannekuva.py").read_text(encoding="utf-8")
        self.assertRegex(lahde, r"""["']- Testit["']""")


if __name__ == "__main__":
    unittest.main()
