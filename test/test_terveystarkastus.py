"""hiekkalaatikko/terveystarkastus.py: lomakkeen jasennys, lista, luonnokset. Ei verkkoa, ei vierasta koodia."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

HL = Path(__file__).resolve().parent.parent / "hiekkalaatikko"
spec = importlib.util.spec_from_file_location("terveystarkastus_testi", HL / "terveystarkastus.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def issue(n=1, repo="https://github.com/a/b", komento="node dist/server.js", julkinen=t.JULKINEN, suostumus="- [x] one\n- [x] two"):
    return {"number": n, "user": {"login": "u"}, "body": "### Repository URL\n\n%s\n\n### Start command or server URL\n\n%s\n\n"
            "### Public reply\n\n%s\n\n### Consent\n\n%s\n" % (repo, komento, julkinen, suostumus)}


class Jasennys(unittest.TestCase):
    def test_kelvollinen(self):
        p = t.tulkitse_issue(issue())
        self.assertNotIn("virhe", p)
        self.assertEqual(p["komento"], ["node", "dist/server.js"])
        self.assertTrue(p["julkinen"])

    def test_ei_julkinen(self):
        self.assertFalse(t.tulkitse_issue(issue(julkinen="No, I prefer a short summary only"))["julkinen"])

    def test_huono_url(self):
        for url in ("http://github.com/a/b", "https://github.com/a/b/c", "https://evil.example/a/b", "https://github.com/a/b; rm -rf /"):
            self.assertIn("virhe", t.tulkitse_issue(issue(repo=url)), url)

    def test_suostumus_pakollinen(self):
        self.assertIn("virhe", t.tulkitse_issue(issue(suostumus="- [x] one\n- [ ] two")))
        self.assertIn("virhe", t.tulkitse_issue(issue(suostumus="- [ ] one\n- [ ] two")))

    def test_komento_ei_valitsin(self):
        self.assertIn("virhe", t.tulkitse_issue(issue(komento="--eval x")))

    def test_http_komento_hylataan(self):
        self.assertIn("virhe", t.tulkitse_issue(issue(komento="https://x.example/mcp")))

    def test_tyhja_runko(self):
        self.assertIn("virhe", t.tulkitse_issue({"number": 3, "body": None}))

    def test_ei_komentoa(self):
        self.assertIsNone(t.tulkitse_issue(issue(komento="_No response_"))["komento"])


class Lista(unittest.TestCase):
    def test_lista_ohittaa_virheelliset(self):
        teksti = t.tee_lista([t.tulkitse_issue(issue(1)), t.tulkitse_issue(issue(2, repo="x"))])
        self.assertEqual(teksti, "https://github.com/a/b node dist/server.js  # issue #1\n")

    def test_pr_suodatetaan(self):
        vastaus = json.dumps([{"number": 1}, {"number": 2, "pull_request": {}}]).encode()
        self.assertEqual([i["number"] for i in t.hae_issuet("a/b", avaa=lambda u: vastaus)], [1])

    def test_haku_virhe_vain_tyyppi(self):
        def rikki(u):
            raise OSError("salaisuus")
        with self.assertRaises(t.Virhe) as c:
            t.hae_issuet("a/b", avaa=rikki)
        self.assertNotIn("salaisuus", str(c.exception))

    def test_huono_repo(self):
        with self.assertRaises(t.Virhe):
            t.hae_issuet("a/b?x=1", avaa=lambda u: b"[]")


class AjoRaja(unittest.TestCase):
    def test_kieltaytyy_ilman_hiekkalaatikkoa(self):
        os.environ.pop("MCP_HIEKKALAATIKKO", None)
        kutsuttu = []
        with self.assertRaises(t.Virhe):
            t.aja_era("l", "u", "e.py", ajaja=lambda *a, **k: kutsuttu.append(1))
        self.assertEqual(kutsuttu, [])

    def test_ajaa_hiekkalaatikossa(self):
        os.environ["MCP_HIEKKALAATIKKO"] = "1"
        try:
            kmd = []

            class R:
                returncode = 0
            t.aja_era("l", "u", "e.py", ajaja=lambda c, **k: (kmd.append(c), R())[1])
            self.assertIn("-I", kmd[0])
        finally:
            os.environ.pop("MCP_HIEKKALAATIKKO", None)


class Luonnos(unittest.TestCase):
    def test_esimerkki(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(t.main(["esimerkki", "--ulos", d]), 0)
            a = Path(d, "issue-7.md").read_text()
            self.assertIn("DRAFT for Tony. Not sent", a)
            self.assertIn("TOOL_DESCRIPTION_MISSING", a)
            self.assertIn("could not process the form", Path(d, "issue-8.md").read_text())

    def test_vieras_teksti_siivotaan(self):
        tulos = {"repot": [{"repo": "https://github.com/a/b", "tila": "loydoksia", "raportti": {
            "toolCount": 1, "summary": {"errors": 1, "warnings": 0, "infos": 0},
            "findings": [{"id": "X", "severity": "error", "message": "ping @tony\n```bash\nrm -rf /\n```"}]}}]}
        teksti = t.luonnos(t.tulkitse_issue(issue()), tulos["repot"][0])
        self.assertNotIn("@tony", teksti)
        self.assertNotIn("```", teksti)

    def test_ei_ajettu(self):
        self.assertIn("not been run", t.luonnos(t.tulkitse_issue(issue()), None))

    def test_ei_julkinen_merkinta(self):
        p = t.tulkitse_issue(issue(julkinen="No, I prefer a short summary only"))
        self.assertIn("declined a public reply", t.luonnos(p, None))

    def test_aikakatkaisu(self):
        teksti = t.luonnos(t.tulkitse_issue(issue()), {"tila": "aikakatkaisu", "huomio": "npm install"})
        self.assertIn("could not be completed", teksti)


if __name__ == "__main__":
    unittest.main()
