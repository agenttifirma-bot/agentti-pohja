import json
import unittest

from agentti import skeema, tulos

S = {"type": "object", "required": ["a"], "properties": {
    "a": {"type": "string", "maxLength": 5},
    "n": {"type": "integer"},
    "l": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
    "e": {"type": "string", "enum": ["x", "y"]}}}


class SkeemaTesti(unittest.TestCase):
    def virhe(self, arvo):
        with self.assertRaises(skeema.SkeemaVirhe):
            skeema.tarkista(arvo, S)

    def test_kelvollinen(self):
        skeema.tarkista({"a": "abc", "n": 3, "l": ["q"], "e": "x"}, S)

    def test_puuttuva_pakollinen(self):
        self.virhe({})

    def test_ylimaarainen_kentta(self):
        self.virhe({"a": "x", "muu": 1})

    def test_vaara_tyyppi(self):
        self.virhe({"a": 5})
        self.virhe({"a": "x", "n": "3"})

    def test_bool_ei_ole_kokonaisluku(self):
        self.virhe({"a": "x", "n": True})

    def test_enum_pituus_ja_lista(self):
        self.virhe({"a": "x", "e": "z"})
        self.virhe({"a": "liianpitka"})
        self.virhe({"a": "x", "l": ["a", "b", "c"]})
        self.virhe({"a": "x", "l": [1]})

    def test_tuntematon_tyyppi_skeemassa(self):
        with self.assertRaises(skeema.SkeemaVirhe):
            skeema.tarkista(1, {"type": "foo"})


SIS = {"type": "object", "required": ["t"], "properties": {"t": {"type": "string"}}}


class TulosTesti(unittest.TestCase):
    def test_ok(self):
        t = tulos.lue(json.dumps({"tila": "ok", "sisalto": {"t": "hei"}}), SIS)
        self.assertEqual((t.tila, t.sisalto["t"]), ("ok", "hei"))

    def test_ei_tietoa_on_sallittu(self):
        t = tulos.lue(json.dumps({"tila": "ei_tietoa", "syy": "data puuttuu"}), SIS)
        self.assertEqual((t.tila, t.syy, t.sisalto), ("ei_tietoa", "data puuttuu", None))

    def test_ei_tietoa_vaatii_syyn(self):
        for v in ({"tila": "ei_tietoa"}, {"tila": "ei_tietoa", "syy": "  "}):
            with self.assertRaises(tulos.TulosVirhe) as e:
                tulos.lue(json.dumps(v), SIS)
            self.assertEqual(e.exception.koodi, "llm_skeema")

    def test_ok_vaatii_sisallon(self):
        with self.assertRaises(tulos.TulosVirhe):
            tulos.lue(json.dumps({"tila": "ok"}), SIS)

    def test_vaara_sisalto(self):
        with self.assertRaises(tulos.TulosVirhe) as e:
            tulos.lue(json.dumps({"tila": "ok", "sisalto": {"t": 1}}), SIS)
        self.assertEqual(e.exception.koodi, "llm_skeema")

    def test_ei_json(self):
        with self.assertRaises(tulos.TulosVirhe) as e:
            tulos.lue("Tassa on vastaus.", SIS)
        self.assertEqual(e.exception.koodi, "llm_vastaus_ei_json")

    def test_koodiaita_poistetaan(self):
        teksti = "```json\n" + json.dumps({"tila": "ok", "sisalto": {"t": "a"}}) + "\n```"
        self.assertEqual(tulos.lue(teksti, SIS).sisalto["t"], "a")

    def test_tuntematon_tila(self):
        with self.assertRaises(tulos.TulosVirhe):
            tulos.lue(json.dumps({"tila": "ehka", "sisalto": {"t": "a"}}), SIS)


if __name__ == "__main__":
    unittest.main()
