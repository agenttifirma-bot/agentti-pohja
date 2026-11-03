"""Skeemavirheen diagnostiikka: lokiin kiintea kentan polku ja syykoodi, ei mallin tekstia. Hyvaksymissaannot ennallaan."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import llm  # noqa: E402
import run  # noqa: E402
import test_llm as tl  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


def syy_ja_koodi(d):
    syy = []
    tulos, koodi = llm.luokittele_vastaus(d if isinstance(d, str) else json.dumps(d), syy)
    return koodi, (syy[0] if syy else None)


def vast(**lisa):
    d = json.loads(json.dumps(tl.HYVA))
    d.update(lisa)
    return d


class SyyTesti(unittest.TestCase):
    def test_hyva_ei_syyta(self):
        self.assertEqual(syy_ja_koodi(vast()), (None, None))

    def test_top3_tyhja_ilman_ei_tietoa(self):
        self.assertEqual(syy_ja_koodi(vast(top3=[])), ("llm_skeema", "top3:lkm_0_ilman_ei_tietoa"))

    def test_ei_tietoa_null(self):
        self.assertEqual(syy_ja_koodi(vast(ei_tietoa=None)), ("llm_skeema", "ei_tietoa:tyyppi_null"))

    def test_puuttuva_avain(self):
        d = vast()
        del d["ehdotukset"]
        self.assertEqual(syy_ja_koodi(d), ("llm_skeema", "juuri:puuttuu_ehdotukset"))

    def test_asia_liian_pitka_ei_sisaltoa(self):
        d = vast()
        d["top3"][1]["asia"] = "salainen" * 20
        koodi, syy = syy_ja_koodi(d)
        self.assertEqual((koodi, syy), ("llm_skeema", "top3[1].asia:liian_pitka_160_yli_80"))
        self.assertNotIn("salainen", syy)

    def test_pelkka_linkki_ehdotus(self):
        self.assertEqual(syy_ja_koodi(vast(ehdotukset=["https://evil.test"])), ("llm_skeema", "ehdotukset[0]:tyhja_siivouksen_jalkeen"))

    def test_tyhja_merkkijono_ehdotus(self):
        self.assertEqual(syy_ja_koodi(vast(ehdotukset=[""])), ("llm_skeema", "ehdotukset[0]:tyhja"))

    def test_liikaa_ehdotuksia(self):
        self.assertEqual(syy_ja_koodi(vast(ehdotukset=["a"] * 4)), ("llm_skeema", "ehdotukset:lkm_4_yli_3"))

    def test_uutta_ei_lista(self):
        self.assertEqual(syy_ja_koodi(vast(uutta="x")), ("llm_skeema", "uutta:tyyppi_str"))

    def test_juuri_lista(self):
        self.assertEqual(syy_ja_koodi("[]"), ("llm_skeema", "juuri:tyyppi_list"))

    def test_tarkista_vastaus_toimii_ilman_syy_listaa(self):
        self.assertIsNone(llm.tarkista_vastaus(json.dumps(vast(top3=[]))))


class KysyTesti(tl.Pohja):
    def test_kaytto_saa_skeema_syyn(self):
        kaytto = {}
        self.assertIsNone(self.kysy(tl.Mock(tl.vastaus(vast(top3=[]))), kaytto=kaytto))
        self.assertEqual((kaytto["virhekoodi"], kaytto["skeema_syy"]), ("llm_skeema", "top3:lkm_0_ilman_ei_tietoa"))

    def test_rakennevirhe_saa_syyn(self):
        kaytto = {}
        self.assertIsNone(self.kysy(tl.Mock({"choices": []}), kaytto=kaytto))
        self.assertEqual(kaytto["skeema_syy"], "vastaus:rakenne_ei_chat_completion")

    def test_hyva_vastaus_ei_syyta(self):
        kaytto = {}
        self.assertIsNotNone(self.kysy(tl.Mock(tl.vastaus(vast())), kaytto=kaytto))
        self.assertNotIn("skeema_syy", kaytto)


class LokiTesti(unittest.TestCase):
    def rivi(self, kaytto):
        return run._lokirivi(datetime(2026, 11, 3, 7, 30, tzinfo=timezone.utc), "send", kaytto, None, ["llm_skeema"], [], 0, "laheta")

    def test_syy_loki_riville(self):
        self.assertIn(" skeema_syy=top3[1].asia:liian_pitka_160_yli_80 ", self.rivi({"skeema_syy": "top3[1].asia:liian_pitka_160_yli_80"}))

    def test_epakelpo_syy_ei_lokiin(self):
        self.assertNotIn("skeema_syy", self.rivi({"skeema_syy": "rivi\nvaara sisalto"}))


if __name__ == "__main__":
    unittest.main()
