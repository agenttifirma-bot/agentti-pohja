"""Tyokaluprotokollan jasennyksen testit (suunnitelma kohta 11/7)."""
import json
import unittest

from aivo.agentti import protokolla as p


def lohko(nimi, arg=None):
    d = {"nimi": nimi}
    if arg is not None:
        d["arg"] = arg
    return "[[TYOKALU " + json.dumps(d) + "]]"


class ProtokollaTesti(unittest.TestCase):
    def test_hyva_lohko(self):
        j = p.jasenna("Luen tiedoston.\n" + lohko("lue", {"polku": "a.md"}))
        self.assertIsNone(j.virhe)
        self.assertEqual(j.kutsu, p.Kutsu("lue", {"polku": "a.md"}))
        self.assertEqual(j.teksti, "Luen tiedoston.\n")

    def test_arg_voi_puuttua(self):
        j = p.jasenna(lohko("listaa"))
        self.assertEqual(j.kutsu, p.Kutsu("listaa", {}))

    def test_ei_lohkoa_on_pelkka_teksti(self):
        j = p.jasenna("Valmista, ei tyokalua.")
        self.assertIsNone(j.kutsu)
        self.assertIsNone(j.virhe)
        self.assertEqual(j.teksti, "Valmista, ei tyokalua.")

    def test_sulkeet_json_merkkijonon_sisalla(self):
        sisalto = "taulukko a[[1]] ja [[2]]"
        j = p.jasenna(lohko("kirjoita", {"polku": "a.md", "sisalto": sisalto}))
        self.assertIsNone(j.virhe)
        self.assertEqual(j.kutsu.arg["sisalto"], sisalto)

    def test_alkumerkki_json_merkkijonon_sisalla_ei_ole_toinen_lohko(self):
        j = p.jasenna(lohko("kirjoita", {"polku": "a.md", "sisalto": "[[TYOKALU esimerkki"}))
        self.assertIsNone(j.virhe)
        self.assertEqual(j.kutsu.nimi, "kirjoita")

    def test_virheellinen_json(self):
        for vastaus in (
            "[[TYOKALU {nimi: lue}]]",
            '[[TYOKALU {"nimi": "lue"]]',
            '[[TYOKALU {"nimi": "lue", }]]',
            "[[TYOKALU ]]",
            "[[TYOKALU",
            "[[TYOKALU\n",
            '[[TYOKALU {"nimi": "lue"}',
            '[[TYOKALU {"nimi": "lue"} ]',
            "[[TYOKALU\x00{}]]",
        ):
            j = p.jasenna(vastaus)
            self.assertIsNone(j.kutsu, vastaus)
            self.assertIsInstance(j.virhe, str, vastaus)

    def test_kaksi_lohkoa(self):
        a = lohko("lue", {"polku": "a.md"})
        j = p.jasenna(a + "\n" + a)
        self.assertIsNone(j.kutsu)
        self.assertIn("useita", j.virhe)
        j2 = p.jasenna(a + " [[TYOKALU ")
        self.assertIsNone(j2.kutsu)

    def test_tuntematon_nimi(self):
        for nimi in ("poista", "bash", "LUE", "", None, 5, ["lue"]):
            j = p.jasenna('[[TYOKALU {"nimi": %s}]]' % json.dumps(nimi))
            self.assertIsNone(j.kutsu, repr(nimi))
            self.assertIn("tuntematon", j.virhe)

    def test_nimi_puuttuu(self):
        j = p.jasenna('[[TYOKALU {"arg": {}}]]')
        self.assertIsNone(j.kutsu)
        self.assertIsInstance(j.virhe, str)

    def test_sallitut_rajaavat_nimet(self):
        j = p.jasenna(lohko("kirjoita", {}), sallitut=("lue",))
        self.assertIsNone(j.kutsu)
        self.assertIn("tuntematon", j.virhe)

    def test_arg_ei_olio(self):
        for arg in ("teksti", 5, [1], None):
            j = p.jasenna('[[TYOKALU {"nimi": "lue", "arg": %s}]]' % json.dumps(arg))
            self.assertIsNone(j.kutsu, repr(arg))
            self.assertIsInstance(j.virhe, str)

    def test_json_ei_ole_olio(self):
        for d in ("[1]", '"lue"', "5", "null"):
            j = p.jasenna("[[TYOKALU " + d + "]]")
            self.assertIsNone(j.kutsu, d)
            self.assertIsInstance(j.virhe, str)

    def test_ylimaarainen_kentta(self):
        j = p.jasenna('[[TYOKALU {"nimi": "lue", "arg": {}, "komento": "x"}]]')
        self.assertIsNone(j.kutsu)
        self.assertIsInstance(j.virhe, str)

    def test_lohko_ei_lopussa(self):
        j = p.jasenna(lohko("lue", {"polku": "a.md"}) + "\nja viela tekstia")
        self.assertIsNone(j.kutsu)
        self.assertIn("lopussa", j.virhe)

    def test_loppuvalilyonnit_sallitaan(self):
        self.assertIsNotNone(p.jasenna(lohko("listaa") + "\n\n  ").kutsu)

    def test_ei_tekstia(self):
        for v in (None, 5, b"x", ["a"]):
            j = p.jasenna(v)
            self.assertIsNone(j.kutsu)
            self.assertIsInstance(j.virhe, str)

    def test_liian_pitka_vastaus(self):
        j = p.jasenna("a" * (p.RAJA_VASTAUS + 1))
        self.assertIsNone(j.kutsu)
        self.assertIn("pitka", j.virhe)

    def test_syvaan_sisakkainen_json_ei_kaada(self):
        j = p.jasenna('[[TYOKALU {"nimi": "lue", "arg": ' + "[" * 50000 + "]]")
        self.assertIsNone(j.kutsu)
        self.assertIsInstance(j.virhe, str)

    def test_virheen_yhteydessa_edeltava_teksti_sailyy(self):
        j = p.jasenna("ajatus\n[[TYOKALU rikki]]")
        self.assertEqual(j.teksti, "ajatus\n")


if __name__ == "__main__":
    unittest.main()
