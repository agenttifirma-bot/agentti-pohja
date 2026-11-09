"""Testit aivo/openrouter_zdr.py:lle. Ei verkkoa, ei tunnuksia."""
import ast
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

    def test_provider_avaimen_kirjainkoko_ei_ohita(self):
        """Iso tai sekakirjaiminen avain ei saa ohittaa pakotusta."""
        for prov in ({"ZDR": False}, {"Zdr": False}, {"zDr": None}, {" zdr ": False},
                     {"ZDR": True}, {"zdr": True, "ZDR": False}, {"ZDR": False, "zdr": True}):
            with self.subTest(prov=prov), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", MSG, provider=prov)

    def test_lisaparametrin_kirjainkoko(self):
        for k in ("ZDR", "Zdr", "zDR", " zdr"):
            with self.subTest(k=k), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", MSG, **{k: False})

    def test_rungossa_vain_yksi_zdr_avain(self):
        r = oz.rakenna_runko("m/x", MSG, provider={"order": ["a"], "Order2": 1})
        self.assertEqual([k for k in r["provider"] if k.lower() == "zdr"], ["zdr"])

    def test_virheellinen_viesti_nostaa_zdrvirheen(self):
        for viestit in ("hei", b"hei", None, 5, ["hei"], [1], {"role": "user"},
                        [{"role": "user"}, "x"]):
            with self.subTest(viestit=viestit), self.assertRaises(oz.ZdrVirhe):
                oz.rakenna_runko("m/x", viestit)

    def test_virheellinen_viesti_ei_vuoda_sisaltoa(self):
        with self.assertRaises(oz.ZdrVirhe) as e:
            oz.rakenna_runko("m/x", ["salainen"])
        self.assertNotIn("salainen", str(e.exception))

    def test_generaattori_viesteina_toimii(self):
        r = oz.rakenna_runko("m/x", (m for m in MSG))
        self.assertEqual(r["messages"], MSG)

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
        """AST-vartija: tarkistaa tuonnit ja kutsut, ei merkkijonoja (docstring ei kaada)."""
        puu = ast.parse((AIVO / "openrouter_zdr.py").read_text(encoding="utf-8"))
        kielletyt_moduulit = {"urllib", "requests", "httpx", "aiohttp", "socket", "http",
                              "subprocess", "os", "ssl", "ftplib", "smtplib", "importlib"}
        kielletyt_nimet = {"open", "getenv", "environ", "eval", "exec", "__import__"}
        loydot = []
        for n in ast.walk(puu):
            if isinstance(n, ast.Import):
                loydot += [a.name for a in n.names if a.name.split(".")[0] in kielletyt_moduulit]
            elif isinstance(n, ast.ImportFrom):
                if (n.module or "").split(".")[0] in kielletyt_moduulit:
                    loydot.append(n.module)
            elif isinstance(n, ast.Name) and n.id in kielletyt_nimet:
                loydot.append(n.id)
            elif isinstance(n, ast.Attribute) and n.attr in kielletyt_nimet:
                loydot.append(n.attr)
        self.assertEqual(loydot, [])


if __name__ == "__main__":
    unittest.main()
