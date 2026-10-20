import json
import os
import tempfile
import unittest

from agentti import ilmoita


class MuodostaTest(unittest.TestCase):
    def test_muoto(self):
        self.assertEqual(ilmoita.muodosta("valmis", "Deploy", "ok"), "[VALMIS] Deploy\nok")
        self.assertEqual(ilmoita.muodosta("virhe", "X"), "[VIRHE] X")

    def test_virheet(self):
        with self.assertRaises(ValueError):
            ilmoita.muodosta("muu", "x")
        with self.assertRaises(ValueError):
            ilmoita.muodosta("valmis", "  ")

    def test_puhdistus_ja_rajat(self):
        v = ilmoita.muodosta("valmis", "a\x1b[31m\nb", "t\x00\x07x" + "z" * 5000)
        self.assertNotIn("\x1b", v)
        self.assertNotIn("\x00", v)
        self.assertEqual(v.splitlines()[0], "[VALMIS] a[31m b")
        self.assertLessEqual(len(v), 20 + ilmoita.OTSIKKO_MAX + ilmoita.TEKSTI_MAX)


class LahetysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = os.path.join(self.tmp.name, "t.env")
        self.tila = os.path.join(self.tmp.name, "tila.json")
        with open(self.env, "w") as f:
            f.write("# kommentti\nYOJONO_TELEGRAM_TOKEN=tok\nYOJONO_TELEGRAM_CHAT='123'\n")
        self.lahetetyt = []

    def hae(self, token, chat, teksti):
        self.lahetetyt.append((token, chat, teksti))
        return True

    def aja(self, **kw):
        return ilmoita.ilmoita("valmis", "T", "x", env_polku=self.env, tila_polku=self.tila, hae=self.hae, **kw)

    def test_lahettaa_tunnuksilla_tiedostosta(self):
        self.assertEqual(self.aja(), "lahetetty")
        self.assertEqual(self.lahetetyt, [("tok", "123", "[VALMIS] T\nx")])

    def test_ei_tunnuksia(self):
        tulos = ilmoita.ilmoita("valmis", "T", env_polku="/ei/ole", tila_polku=self.tila, hae=self.hae)
        self.assertEqual(tulos, "ei_tunnuksia")
        self.assertEqual(self.lahetetyt, [])

    def test_epaonnistunut_lahetys(self):
        tulos = ilmoita.ilmoita("valmis", "T", env_polku=self.env, tila_polku=self.tila, hae=lambda *a: False)
        self.assertEqual(tulos, "epaonnistui")

    def test_tuntiraja(self):
        for _ in range(ilmoita.RAJA_TUNNISSA):
            self.assertEqual(self.aja(nyt=1000), "lahetetty")
        self.assertEqual(self.aja(nyt=1100), "raja")
        self.assertEqual(self.aja(nyt=1000 + 3601), "lahetetty")  # vanhat kirjaukset vanhenevat

    def test_rikkinainen_tilatiedosto_ei_estaa(self):
        with open(self.tila, "w") as f:
            f.write("ei jsonia")
        self.assertEqual(self.aja(), "lahetetty")
        with open(self.tila) as f:
            self.assertEqual(len(json.load(f)), 1)

    def test_vastaanottaja_ei_tule_viestista(self):
        ilmoita.ilmoita("valmis", "chat_id=999", env_polku=self.env, tila_polku=self.tila, hae=self.hae)
        self.assertEqual(self.lahetetyt[0][1], "123")

    def test_main_kaytto(self):
        self.assertEqual(ilmoita.main([]), 2)
        self.assertEqual(ilmoita.main(["muu", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
