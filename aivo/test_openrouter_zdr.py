"""Testit aivo/openrouter_zdr.py:lle. Ei verkkoa, ei tunnuksia."""
import unittest
from pathlib import Path

from aivo import openrouter_zdr as oz

MSG = [{"role": "user", "content": "x"}]
AIVO = Path(oz.__file__).resolve().parent


class ZdrTesti(unittest.TestCase):
    def test_zdr_aina_true(self):
        self.assertIs(oz.rakenna_runko("m/x", MSG)["provider"]["zdr"], True)
        r = oz.rakenna_runko("m/x", MSG, provider={"order": ["a"]}, temperature=0)
        self.assertIs(r["provider"]["zdr"], True)
        self.assertEqual(r["provider"]["order"], ["a"])
        self.assertEqual((r["model"], r["temperature"]), ("m/x", 0))
        self.assertIs(oz.rakenna_runko("m/x", MSG, provider={"zdr": True})["provider"]["zdr"], True)

    def test_syotteita_ei_muuteta(self):
        prov = {"order": ["a"]}
        oz.rakenna_runko("m/x", MSG, provider=prov)
        self.assertNotIn("zdr", prov)

    def test_ohitusyritys_kaatuu(self):
        for kw in ({"zdr": False}, {"zdr": True}, {"ZDR": False},
                   {"provider": {"zdr": False}}, {"provider": {"zdr": None}},
                   {"provider": {"zdr": 1}}, {"provider": "zdr"}):
            with self.subTest(kw=kw), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", MSG, **kw)

    def test_varatut_avaimet_kaatuvat(self):
        for k in ("model", "messages"):
            with self.subTest(k=k), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", MSG, **{k: "y"})

    def test_yksityinen_chat_kaatuu(self):
        for arvo in (True, 1, "kylla"):
            with self.subTest(arvo=arvo), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", MSG, yksityinen_chat=arvo)

    def test_tyhja_malli_kaatuu(self):
        with self.assertRaises(oz.ZdrVirhe):
            oz.rakenna_runko("", MSG)

    def test_virhe_ei_vuoda_sisaltoa(self):
        with self.assertRaises(oz.ZdrVirhe) as e:
            oz.rakenna_runko("m/x", [{"role": "user", "content": "salainen"}], yksityinen_chat=True)
        self.assertNotIn("salainen", str(e.exception))

    def test_ei_openrouter_ai_viittausta_moduulin_ulkopuolella(self):
        """Staattinen vartija: osoite saa olla vain tassa moduulissa, ei muualla aivo/-kansiossa."""
        haettu = "openrouter" + ".ai"
        osumat = []
        for p in sorted(AIVO.rglob("*")):
            if not p.is_file() or p.name == "openrouter_zdr.py" or p.name.startswith("test_"):
                continue
            if p.suffix in (".pyc", ".pyo"):
                continue
            try:
                teksti = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if haettu in teksti.lower():
                osumat.append(str(p.relative_to(AIVO)))
        self.assertEqual(osumat, [])

    def test_moduuli_ei_tee_verkkokutsua_eika_lue_avaimia(self):
        koodi = (AIVO / "openrouter_zdr.py").read_text(encoding="utf-8")
        for kielletty in ("urllib", "requests", "socket", "http.client", "os.environ", "getenv", "open("):
            self.assertNotIn(kielletty, koodi)


if __name__ == "__main__":
    unittest.main()
