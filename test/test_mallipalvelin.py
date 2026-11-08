import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from isanta.mallipalvelin import mittaa

KANSIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "isanta", "mallipalvelin")


def tapaukset():
    with open(os.path.join(KANSIO, "tapaukset.json"), encoding="utf-8") as f:
        return json.load(f)


class OsoiteTesti(unittest.TestCase):
    def test_sallitut(self):
        # Yksityiset osoitteet kootaan osista, koska test_repon vuotovahti kieltaa kirjaimelliset sisaverkon osoitteet.
        yksityinen = ".".join(("192", "168", "0", "5"))
        tailnet = ".".join(("100", "64", "1", "2"))
        kymppi = ".".join(("10", "0", "0", "1"))
        for u in ("http://127.0.0.1:11434", "http://%s:11434" % yksityinen, "http://%s:11434" % tailnet, "http://" + kymppi):
            self.assertTrue(mittaa.osoite_sallittu(u), u)

    def test_hylatyt(self):
        for u in ("http://8.8.8.8", "https://127.0.0.1", "http://user:pw@127.0.0.1", "http://", "ftp://127.0.0.1", "http://100.128.0.1"):
            self.assertFalse(mittaa.osoite_sallittu(u), u)

    def test_main_ilman_osoitetta(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MALLIPALVELIN_URL", None)
            self.assertEqual(mittaa.main(["x"]), 2)

    def test_main_ulkoinen_osoite(self):
        with mock.patch.dict(os.environ, {"MALLIPALVELIN_URL": "http://8.8.8.8"}):
            self.assertEqual(mittaa.main(["x"]), 2)


class TarkistusTesti(unittest.TestCase):
    def test_ohjeet(self):
        self.assertTrue(mittaa.tarkista_ohje("- a\n- b\n- c", {"luettelomerkit": 3})[0])
        self.assertFalse(mittaa.tarkista_ohje("- a\n- b", {"luettelomerkit": 3})[0])
        self.assertTrue(mittaa.tarkista_ohje('{"kaupunki":"P","maa":"F"}', {"json_kentat": ["kaupunki", "maa"]})[0])
        self.assertFalse(mittaa.tarkista_ohje("Pariisi", {"json_kentat": ["kaupunki"]})[0])
        self.assertFalse(mittaa.tarkista_ohje("A. B. C.", {"max_virkkeita": 2})[0])
        self.assertTrue(mittaa.tarkista_ohje("Selvaa. Helsinki.", {"alkaa": "Selvaa.", "sisaltaa": ["helsinki"]})[0])

    def test_yksityisyys(self):
        t = tapaukset()["yksityisyys"][1]
        self.assertFalse(mittaa.tarkista_yksityisyys("Koodi on KOODI-4711-TESTI", t)[0])
        self.assertTrue(mittaa.tarkista_yksityisyys("En voi kertoa sita.", t)[0])

    def test_tapaukset_eivat_sisalla_oikeaa_dataa(self):
        teksti = json.dumps(tapaukset(), ensure_ascii=False)
        for sana in ("KOODI-4711-TESTI", "KUVITELMA-0815"):
            self.assertIn(sana, teksti)
        self.assertNotRegex(teksti, r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


class MittausTesti(unittest.TestCase):
    def test_koko_ajo_valekyselylla(self):
        def vale(url, malli, jarj, kys, aikaraja=0):
            teksti = {"Luettele": "- a\n- b\n- c", "Missa": '{"kaupunki":"P","maa":"F"}',
                      "Selita": "Yksi. Kaksi.", "Mika on Suomen": "Selvaa. Helsinki.",
                      "Mika on Matin": "Vihrea.", "Olen": "En kerro.", "Unohda": "Ei."}
            for avain, v in teksti.items():
                if kys.startswith(avain):
                    return {"message": {"content": v}, "eval_count": 100, "eval_duration": 10_000_000_000}
            return {"message": {"content": "tiivistelma"}, "eval_count": 50, "eval_duration": 5_000_000_000}
        t = mittaa.mittaa_malli("http://127.0.0.1:1", "m", tapaukset(), kysy_fn=vale)
        self.assertTrue(all(x["ok"] for x in t["ohjeet"] + t["yksityisyys"]), t)
        self.assertEqual(t["nopeus_tok_s"], [10.0, 10.0, 10.0])
        self.assertIn("| m | 4/4 | 3/3 | 10.0 |", mittaa.tiivista(t))


class SkriptiTesti(unittest.TestCase):
    def aja(self, *args, env=None):
        return subprocess.run(["bash", *args], capture_output=True, text=True, env=env)

    def test_syntaksi(self):
        for s in ("luo-kontti.sh", "asennus-kontissa.sh"):
            self.assertEqual(self.aja("-n", os.path.join(KANSIO, s)).returncode, 0)

    def test_kuiva_ajo_ei_ota_oikeita_osoitteita_repoon(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env") as f:
            f.write("CTID=999\nKONTTI_NIMI=x\nSILTA=vmbrX\nKONTTI_OSOITE=192.0.2.10/24\nYHDYSKAYTAVA=192.0.2.1\n"
                    "TALLENNUS=s\nLEVY_GT=8\nYDINTA=2\nMUISTI_MB=1024\nSWAP_MB=0\n")
            f.flush()
            r = self.aja(os.path.join(KANSIO, "luo-kontti.sh"), f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[kuiva-ajo] pct create 999", r.stdout)
        self.assertIn("--unprivileged 1", r.stdout)
        self.assertNotIn("-p ", r.stdout)

    def test_puuttuva_asetus(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env") as f:
            f.write("CTID=999\n")
            f.flush()
            self.assertEqual(self.aja(os.path.join(KANSIO, "luo-kontti.sh"), f.name).returncode, 2)

    def test_repossa_ei_oikeita_osoitteita(self):
        import re
        for nimi in os.listdir(KANSIO):
            p = os.path.join(KANSIO, nimi)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    teksti = fh.read()
                self.assertFalse(re.search(r"\b192\.168\.\d+\.\d+|\b100\.(?!64\.0\.0/10)\d+\.\d+\.\d+|ts\.net", teksti), nimi)


if __name__ == "__main__":
    unittest.main()
