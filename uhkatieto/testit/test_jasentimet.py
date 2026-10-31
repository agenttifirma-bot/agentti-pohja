import os
import unittest

from uhkatieto import jasentimet

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def lue(nimi):
    with open(os.path.join(FIX, nimi), encoding="utf-8") as f:
        return f.read()


class KevTesti(unittest.TestCase):
    def test_rivit(self):
        rivit = jasentimet.jasenna_kev(lue("kev.json"))
        self.assertEqual([r["id"] for r in rivit], ["CVE-2026-0001", "CVE-2026-0002"])  # id:ton rivi pudotetaan
        r = rivit[0]
        self.assertEqual((r["lahde"], r["pvm"]), ("kev", "2026-10-30"))
        self.assertEqual(r["otsikko"], "CVE-2026-0001: Acme Gateway RCE Vulnerability")
        self.assertEqual(r["tagit"], ["kev", "acme", "gateway", "ransomware"])
        self.assertEqual(r["url"], "https://nvd.nist.gov/vuln/detail/CVE-2026-0001")

    def test_ohjausmerkit_pois_ja_teksti_pysyy_datana(self):
        r = jasentimet.jasenna_kev(lue("kev.json"))[1]
        self.assertNotIn("\n", r["otsikko"])
        self.assertNotIn("\x07", r["otsikko"])
        self.assertIn("Ignore previous instructions", r["otsikko"])  # tallennetaan sellaisenaan, ei tulkita
        self.assertNotIn("ransomware", r["tagit"])

    def test_tyhja_ja_bytes(self):
        self.assertEqual(jasentimet.jasenna_kev('{"vulnerabilities": []}'), [])
        self.assertEqual(len(jasentimet.jasenna_kev(lue("kev.json").encode("utf-8"))), 2)


class AtlasTesti(unittest.TestCase):
    def setUp(self):
        self.rivit = {r["id"]: r for r in jasentimet.jasenna_atlas(lue("atlas.yaml"))}

    def test_vain_tunnetut_osiot(self):
        self.assertEqual(sorted(self.rivit), ["AML.CS0000", "AML.M0000", "AML.T0000", "AML.T0000.000", "AML.T0051"])

    def test_kentat(self):
        r = self.rivit["AML.T0000"]
        self.assertEqual(r["otsikko"], "AML.T0000: Search Open Technical Databases")
        self.assertEqual((r["lahde"], r["pvm"]), ("atlas", "2021-05-13"))
        self.assertEqual(r["url"], "https://atlas.mitre.org/techniques/AML.T0000")
        self.assertEqual(r["tagit"], ["atlas", "technique"])

    def test_alitekniikka_ja_lajit(self):
        self.assertIn("sub-technique", self.rivit["AML.T0000.000"]["tagit"])
        self.assertIn("mitigation", self.rivit["AML.M0000"]["tagit"])
        self.assertEqual(self.rivit["AML.CS0000"]["url"], "https://atlas.mitre.org/studies/AML.CS0000")

    def test_moniriviarvo_ja_lainausmerkit(self):
        self.assertEqual(self.rivit["AML.T0051"]["otsikko"], "AML.T0051: LLM Prompt Injection: it's a long name")

    def test_kuvauksen_sisainen_avain_ei_ylikirjoita(self):
        self.assertEqual(self.rivit["AML.T0051"]["pvm"], "2023-04-01")

    def test_sisakkainen_title_ei_ole_name(self):
        self.assertEqual(self.rivit["AML.CS0000"]["otsikko"], "AML.CS0000: Evasion of Deep Learning Detector")

    def test_tyhja(self):
        self.assertEqual(jasentimet.jasenna_atlas(""), [])


class NvdTesti(unittest.TestCase):
    def test_rivit(self):
        rivit = jasentimet.jasenna_nvd(lue("nvd.json"), "MCP")
        self.assertEqual([r["id"] for r in rivit], ["CVE-2026-5001", "CVE-2026-5002"])
        r = rivit[0]
        self.assertEqual(r["pvm"], "2026-10-28")
        self.assertEqual(r["otsikko"], "CVE-2026-5001: MCP server allows command injection via tool name.")  # en-kuvaus
        self.assertEqual(r["tagit"], ["nvd", "kw-mcp", "sev-high"])
        self.assertEqual(rivit[1]["tagit"], ["nvd", "kw-mcp"])

    def test_url_vain_http(self):
        self.assertEqual(jasentimet.siisti_url("javascript:alert(1)"), "")
        self.assertEqual(jasentimet.siisti_url("https://a.example/x"), "https://a.example/x")
        self.assertEqual(jasentimet.siisti_url("https://a.example/x y"), "")

    def test_pituusrajat(self):
        r = jasentimet.rivi("x", "id1", "2026-01-01T00:00", "a" * 1000, ["t%d" % i for i in range(50)], "")
        self.assertEqual(len(r["otsikko"]), jasentimet.OTSIKKO_MAX)
        self.assertEqual(len(r["tagit"]), jasentimet.TAGEJA_MAX)
        self.assertEqual(r["pvm"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
