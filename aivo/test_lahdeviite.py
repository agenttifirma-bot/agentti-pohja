"""Testit lahdeviitteen sisaltotarkistukselle (aivo/lahdeviite.py ja chat.lahteiden_sisalto). Ei verkkoa, ei mallia.

Tapaus 26.11.2026: vastaus mainitsi A1116:n oikein, mutta viittasi tiedostoon agenttidata/kompassi.md, vaikka
paatos on tiedostossa agenttidata/pohdinta-vastaukset.md. tarkista_lahteet hyvaksyi viitteen, koska tiedosto on
muistissa."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aivo import agenttidata_kehote as ak, chat, itsetarkistus as it, lahdeviite as lv

R = chat.RAJA
KOMPASSI = "agenttidata/kompassi.md"
POHDINTA = "agenttidata/pohdinta-vastaukset.md"
FAKTAT = "agenttidata/faktat.md"


def osa(nimi, sisalto):
    return "%s\n### TIEDOSTO: %s\n%s\n" % (R, nimi, sisalto)


MUISTI = (osa(KOMPASSI, "# Kompassi\nTavoite: Aivo-koe 7.12. Painopiste A1001.")
          + osa(FAKTAT, "# Faktat\nKutsuraja 4 per viesti. Muisti 300000 tavua.")
          + osa(POHDINTA, "- **A1115** (25.11. klo 18.02): jotain\n- **A1116** (2026-11-26 klo 8.41): tuorein"))
TIEDOSTOT = [KOMPASSI, FAKTAT, POHDINTA]


class Tunnisteet(unittest.TestCase):
    def test_lajit(self):
        t = lv.tunnisteet("A1116 tehtiin 26.11. klo 8.41, raja 300000 ja 4 kutsua, 2026-11-25")
        self.assertEqual([(x[0], x[1]) for x in t],
                         [("paatos", "A1116"), ("pvm", "2026-11-25"), ("pvm", "26.11."), ("luku", "300000")])

    def test_osittainen_a_numero_ei_osu(self):
        self.assertFalse(lv._esiintyy(("paatos", "A111", "111"), "A1116"))
        self.assertTrue(lv._esiintyy(("paatos", "A1116", "1116"), "**A1116**"))

    def test_paivamaara_eri_muodoissa(self):
        t = ("pvm", "26.11.", (26, 11))
        self.assertTrue(lv._esiintyy(t, "2026-11-26"))
        self.assertTrue(lv._esiintyy(t, "26.11.2026"))
        self.assertFalse(lv._esiintyy(t, "6.11."))
        self.assertFalse(lv._esiintyy(t, "26.1.2026"))

    def test_vakiot_samat_kuin_chatissa(self):
        self.assertEqual(lv.RAJA, chat.RAJA)
        self.assertEqual(lv.LAHDE_RE.pattern, chat.LAHDE_RE.pattern)


class Tarkista(unittest.TestCase):
    def test_oikea_lahde_ei_muutosta(self):
        v = "Tuorein A-p\u00e4\u00e4t\u00f6s on A1116 (26.11.) [l\u00e4hde: %s]." % POHDINTA
        self.assertEqual(lv.tarkista(v, MUISTI, TIEDOSTOT), (v, []))

    def test_vaara_lahde_korjataan_ainoaan_ehdokkaaseen(self):
        v = "Tuorein A-p\u00e4\u00e4t\u00f6s on A1116, 26.11. klo 8.41 [l\u00e4hde: %s]." % KOMPASSI
        t, h = lv.tarkista(v, MUISTI, TIEDOSTOT)
        self.assertIn("[l\u00e4hde: %s] (palvelin korjasi l\u00e4hteen: A1116, 26.11. ei ole tiedostossa %s)"
                      % (POHDINTA, KOMPASSI), t)
        self.assertNotIn("[l\u00e4hde: %s]" % KOMPASSI, t)
        self.assertEqual(h, [{"viite": KOMPASSI, "tunnisteet": ["A1116", "26.11."], "tila": "korjattu",
                              "ehdokkaat": [POHDINTA]}])
        # korjattu viite kelpaa myos olemassaolotarkistukselle
        self.assertEqual(chat.tarkista_lahteet(t, TIEDOSTOT)[1], [])

    def test_tunniste_ei_missaan_merkitaan(self):
        v = "P\u00e4\u00e4t\u00f6s A1200 tehtiin eilen [l\u00e4hde: %s]." % KOMPASSI
        t, h = lv.tarkista(v, MUISTI, TIEDOSTOT)
        self.assertIn("[l\u00e4hde: %s] (l\u00e4hde v\u00e4\u00e4r\u00e4: A1200 ei ole tiedostossa eik\u00e4 muualla "
                      "muistissa)" % KOMPASSI, t)
        self.assertEqual(h[0]["tila"], "vaara")
        self.assertEqual(h[0]["ehdokkaat"], [])

    def test_pelkka_luku_ilman_ehdokasta_ei_merkintaa(self):
        v = "Kutsuja on yhteens\u00e4 1200 [l\u00e4hde: %s]." % FAKTAT    # voi olla laskettu
        self.assertEqual(lv.tarkista(v, MUISTI, TIEDOSTOT), (v, []))

    def test_luku_toisessa_tiedostossa_korjataan(self):
        v = "Muistiraja on 300000 tavua [l\u00e4hde: %s]." % KOMPASSI
        t, h = lv.tarkista(v, MUISTI, TIEDOSTOT)
        self.assertIn("[l\u00e4hde: %s]" % FAKTAT, t)
        self.assertEqual(h[0]["tila"], "korjattu")

    def test_tuntematon_lahde_ei_kosketa(self):
        v = "A1116 on tuorein [l\u00e4hde: keksitty.md]."
        self.assertEqual(lv.tarkista(v, MUISTI, TIEDOSTOT), (v, []))
        # chatin jarjestyksessa tarkista_lahteet merkitsee ensin, sisaltotarkistus ei sen jalkeen tee mitaan
        t, tunn = chat.tarkista_lahteet(v, TIEDOSTOT)
        self.assertEqual(tunn, ["keksitty.md"])
        self.assertEqual(chat.lahteiden_sisalto(t, MUISTI, TIEDOSTOT), (t, []))

    def test_useita_viitteita_eri_vaitteille(self):
        v = ("Koe on 7.12. [l\u00e4hde: %s]. Tuorein p\u00e4\u00e4t\u00f6s on A1116 [l\u00e4hde: %s].\n"
             "Edellinen oli A1115 [l\u00e4hde: %s]." % (KOMPASSI, KOMPASSI, POHDINTA))
        t, h = lv.tarkista(v, MUISTI, TIEDOSTOT)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["tunnisteet"], ["A1116"])
        self.assertTrue(t.startswith("Koe on 7.12. [l\u00e4hde: %s]. Tuorein p\u00e4\u00e4t\u00f6s on A1116 [l\u00e4hde: %s] "
                                     "(palvelin korjasi" % (KOMPASSI, POHDINTA)))
        self.assertTrue(t.endswith("Edellinen oli A1115 [l\u00e4hde: %s]." % POHDINTA))

    def test_perakkaiset_viitteet_riittaa_yksi(self):
        v = "A1116 ja koe 7.12. [l\u00e4hde: %s] [l\u00e4hde: %s]." % (KOMPASSI, POHDINTA)
        self.assertEqual(lv.tarkista(v, MUISTI, TIEDOSTOT), (v, []))

    def test_perakkaiset_viitteet_vaarat_merkitaan_ei_korjata(self):
        v = "A1116 tehtiin [l\u00e4hde: %s] [l\u00e4hde: %s]." % (KOMPASSI, FAKTAT)
        t, h = lv.tarkista(v, MUISTI, TIEDOSTOT)
        self.assertEqual(t, v[:-1] + " (l\u00e4hde v\u00e4\u00e4r\u00e4: A1116 ei ole tiedostossa, oikea "
                         "todenn\u00e4k\u00f6isesti %s)." % POHDINTA)
        self.assertEqual(h[0]["viite"], "%s, %s" % (KOMPASSI, FAKTAT))

    def test_useita_ehdokkaita_merkitaan(self):
        muisti = MUISTI + osa("kirjasto.md", "A1116 mainittu my\u00f6s t\u00e4\u00e4ll\u00e4")
        v = "A1116 tehtiin [l\u00e4hde: %s]." % KOMPASSI
        t, h = lv.tarkista(v, muisti, TIEDOSTOT + ["kirjasto.md"])
        self.assertIn("oikea todenn\u00e4k\u00f6isesti %s, kirjasto.md)" % POHDINTA, t)
        self.assertEqual(h[0]["tila"], "vaara")

    def test_ehdokas_vain_kehotteen_tiedostoista(self):
        v = "A1116 tehtiin [l\u00e4hde: %s]." % KOMPASSI
        t, h = lv.tarkista(v, MUISTI, [KOMPASSI, FAKTAT])
        self.assertIn("ei ole tiedostossa eik\u00e4 muualla muistissa", t)

    def test_vaite_rajautuu_riviin(self):
        v = "A1116 on tuorein.\nKoe on 7.12. [l\u00e4hde: %s]." % KOMPASSI
        self.assertEqual(lv.tarkista(v, MUISTI, TIEDOSTOT), (v, []))

    def test_kelvoton_syote(self):
        self.assertEqual(lv.tarkista(None, MUISTI), (None, []))
        self.assertEqual(lv.tarkista("teksti", None), ("teksti", []))
        self.assertEqual(lv.tarkista("A1116 [l\u00e4hde: x.md]", "ei otsikoita"), ("A1116 [l\u00e4hde: x.md]", []))


class OikeaMuisti(unittest.TestCase):
    """Muisti agenttidata_kehote.muodosta-funktiolla, kuten yksityisessa tilassa."""

    def test_tapaus_26_11(self):
        with tempfile.TemporaryDirectory() as d:
            ad = Path(d)
            (ad / ".git").mkdir()
            (ad / "kompassi.md").write_text("# Kompassi\nAivo-koe 7.12.\n", encoding="utf-8")
            (ad / "faktat.md").write_text("# Faktat\nkontti 122\n", encoding="utf-8")
            (ad / "pohdinta-vastaukset.md").write_text(
                "# Pohdinta\n- **A1115** 25.11. jotain\n- **A1116** 26.11. klo 8.41 tuorein\n", encoding="utf-8")
            muisti, tiedostot = ak.muodosta(str(ad), R, 300_000, 120_000, nyt=datetime.now(timezone.utc))
        self.assertIn(POHDINTA, tiedostot)
        v = "Tuorein A-p\u00e4\u00e4t\u00f6s on A1116 (26.11. klo 8.41) [l\u00e4hde: %s]." % KOMPASSI
        v, tunn = chat.tarkista_lahteet(v, tiedostot)
        self.assertEqual(tunn, [])                          # olemassaolo riitti ennen tata muutosta
        t, h = chat.lahteiden_sisalto(v, muisti, tiedostot)
        self.assertIn("[l\u00e4hde: %s]" % POHDINTA, t)
        self.assertEqual(h[0]["tila"], "korjattu")


class TarkastajanOhje(unittest.TestCase):
    def test_ohje_pyytaa_tarkistamaan_viitteen_tiedoston(self):
        self.assertIn("Tarkista my\u00f6s jokainen l\u00e4hdeviite [l\u00e4hde: X]", it.TARKASTAJA_OHJE)
        self.assertIn("v\u00e4ite ei ole tiedostossa X", it.TARKASTAJA_OHJE)


if __name__ == "__main__":
    unittest.main()
