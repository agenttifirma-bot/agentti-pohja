import unittest

from claudejono import valmis

TULOS = "# Tulos: a.md\n\n- Tila: VALMIS\n- Aika: 2026-11-05T10:00+02:00\n- Malli: sonnet\n\nTehty.\n"
OK = "- Tarkastaja: opus\n- Toimii käytössä: kyllä\n- Todiste: https://example.invalid/log#L12\n"


class Valmis(unittest.TestCase):
    def test_kelvollinen(self):
        self.assertTrue(valmis.kelvollinen(TULOS, OK))
        self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, OK), "VALMIS")

    def test_puuttuva_tai_vajaa_merkinta_on_kesken(self):
        for teksti in (None, "", "- Tarkastaja: opus\n- Toimii käytössä: kyllä\n",
                       OK.replace("opus", "sonnet"),          # sama malli kuin tuloksessa
                       OK.replace("kyllä", "ei"),
                       OK.replace("https://example.invalid/log#L12", "-"),
                       "- Toimii käytössä: kyllä\n- Todiste: loki\n"):   # tarkastaja puuttuu
            self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, teksti), "KESKEN", teksti)

    def test_muut_tilat_ennallaan(self):
        for tila in ("KESKEN", "EPAONNISTUI", "HYLATTY"):
            self.assertEqual(valmis.tehokas_tila(tila, TULOS, None), tila)

    def test_toimimaton(self):
        self.assertTrue(valmis.toimimaton(OK.replace("kyllä", "ei")))
        self.assertFalse(valmis.toimimaton(OK))
        self.assertFalse(valmis.toimimaton("- Toimii käytössä: ei\n"))   # ilman todistetta ei lasketa

    def test_polku(self):
        self.assertEqual(valmis.tarkastuspolku("/x", "2026-11-05-17.md").name, "2026-11-05-17.tarkastus.md")


if __name__ == "__main__":
    unittest.main()
