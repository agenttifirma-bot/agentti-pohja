"""luo.py: uuden agentin luonti pohjasta (nimen tarkistus, ylikirjoituksen esto, maaritys-haara)."""
import json
import os
import shutil
import tempfile
import unittest

import luo
from agentti import maaritys

JUURI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MALLIT = (
    "agentti/agentit/esimerkki.py",
    "test/agentti.test.mall",
    "systemd/agentti.service.mall",
    "systemd/agentti.timer.mall",
)
ESIMERKKI_MAARITYS = os.path.join(JUURI, "maaritys.esimerkki.json")


class LuoTesti(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.juuri = tmp.name
        for p in MALLIT:
            kohde = os.path.join(self.juuri, p)
            os.makedirs(os.path.dirname(kohde), exist_ok=True)
            shutil.copy(os.path.join(JUURI, p), kohde)

    def lue(self, suhteellinen):
        with open(os.path.join(self.juuri, suhteellinen), encoding="utf-8") as f:
            return f.read()

    def tiedostot(self):
        return sorted(
            os.path.relpath(os.path.join(d, f), self.juuri)
            for d, _, fs in os.walk(self.juuri) for f in fs
        )

    def test_luo_nelja_tiedostoa_ja_korvaa_nimen(self):
        luotu = luo.luo("uusi_agentti", self.juuri)
        self.assertEqual(sorted(luotu), sorted([
            os.path.join("agentti", "agentit", "uusi_agentti.py"),
            os.path.join("test", "test_uusi_agentti.py"),
            os.path.join("systemd", "agentti-uusi_agentti.service"),
            os.path.join("systemd", "agentti-uusi_agentti.timer"),
        ]))
        py = self.lue("agentti/agentit/uusi_agentti.py")
        self.assertIn('NIMI = "uusi_agentti"', py)
        self.assertNotIn('NIMI = "esimerkki"', py)
        testi = self.lue("test/test_uusi_agentti.py")
        self.assertNotIn("@NIMI@", testi)
        self.assertIn("from agentti.agentit import uusi_agentti", testi)
        for paate in ("service", "timer"):
            teksti = self.lue("systemd/agentti-uusi_agentti." + paate)
            self.assertNotIn("@NIMI@", teksti)
            self.assertIn("uusi_agentti", teksti)

    def test_mallitiedostot_eivat_muutu(self):
        ennen = {p: self.lue(p) for p in MALLIT}
        luo.luo("uusi_agentti", self.juuri)
        self.assertEqual(ennen, {p: self.lue(p) for p in MALLIT})

    def test_virheelliset_nimet_hylataan_eika_kirjoiteta_mitaan(self):
        ennen = self.tiedostot()
        for nimi in ("", "a", "Iso", "1abc", "on-viiva", chr(246) + "_nimi", "../x", "a b", "x" * 32, "esimerkki"):
            with self.subTest(nimi=nimi):
                with self.assertRaises(ValueError):
                    luo.luo(nimi, self.juuri)
        self.assertEqual(self.tiedostot(), ennen)

    def test_nimen_rajat_kelpaavat(self):
        luo.luo("ab", self.juuri)
        luo.luo("a" + "b" * 30, self.juuri)
        luo.luo("a1_2", self.juuri)

    def test_olemassa_olevaa_ei_ylikirjoiteta(self):
        luo.luo("uusi_agentti", self.juuri)
        ennen = self.tiedostot()
        with self.assertRaises(FileExistsError):
            luo.luo("uusi_agentti", self.juuri)
        self.assertEqual(self.tiedostot(), ennen)

    def test_osittain_olemassa_ei_kirjoita_mitaan(self):
        olemassa = os.path.join(self.juuri, "systemd", "agentti-uusi_agentti.timer")
        with open(olemassa, "w", encoding="utf-8") as f:
            f.write("oma sisalto")
        ennen = self.tiedostot()
        with self.assertRaises(FileExistsError) as ctx:
            luo.luo("uusi_agentti", self.juuri)
        self.assertIn("agentti-uusi_agentti.timer", str(ctx.exception))
        self.assertEqual(self.tiedostot(), ennen)
        self.assertEqual(self.lue("systemd/agentti-uusi_agentti.timer"), "oma sisalto")

    def test_maaritys_luo_lisatiedostot(self):
        luotu = luo.luo("ideointi", self.juuri, ESIMERKKI_MAARITYS)
        m = maaritys.lue(ESIMERKKI_MAARITYS)
        self.assertEqual(len(luotu), 7)
        self.assertEqual(json.loads(self.lue("maaritykset/ideointi.json")), m)
        ohje = self.lue("ohjeet/ideointi.md")
        self.assertIn("# Ohje: ideointi", ohje)
        self.assertIn(m["kuvaus"], ohje)
        eval_runko = json.loads(self.lue("evalit/ideointi.json"))
        self.assertEqual(eval_runko, {"agentti": "ideointi", "mittari": m["mittari"], "tapaukset": []})

    def test_maaritys_nimi_ei_vastaa_agentin_nimea(self):
        ennen = self.tiedostot()
        with self.assertRaises(ValueError) as ctx:
            luo.luo("toinen", self.juuri, ESIMERKKI_MAARITYS)
        self.assertIn("ideointi", str(ctx.exception))
        self.assertEqual(self.tiedostot(), ennen)

    def test_maaritys_viiva_nimessa_vastaa_alaviivaa(self):
        with open(ESIMERKKI_MAARITYS, encoding="utf-8") as f:
            m = json.load(f)
        m["nimi"] = "uusi-agentti"
        m["ohje_tiedosto"] = "ohjeet/uusi_agentti.md"
        polku = os.path.join(self.juuri, "m.json")
        with open(polku, "w", encoding="utf-8") as f:
            json.dump(m, f)
        luo.luo("uusi_agentti", self.juuri, polku)
        self.assertTrue(os.path.exists(os.path.join(self.juuri, "ohjeet", "uusi_agentti.md")))

    def test_virheellinen_maaritys_ei_luo_mitaan(self):
        polku = os.path.join(self.juuri, "rikki.json")
        with open(polku, "w", encoding="utf-8") as f:
            f.write("{ei json")
        ennen = self.tiedostot()
        with self.assertRaises(maaritys.MaaritysVirhe):
            luo.luo("ideointi", self.juuri, polku)
        self.assertEqual(self.tiedostot(), ennen)

    def test_olemassa_oleva_maaritystiedosto_estaa_koko_luonnin(self):
        os.makedirs(os.path.join(self.juuri, "evalit"))
        with open(os.path.join(self.juuri, "evalit", "ideointi.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        ennen = self.tiedostot()
        with self.assertRaises(FileExistsError):
            luo.luo("ideointi", self.juuri, ESIMERKKI_MAARITYS)
        self.assertEqual(self.tiedostot(), ennen)


if __name__ == "__main__":
    unittest.main()
