"""Hakumittarin testit: tunnettu pieni esimerkki ja riippuvuuksien AST-tarkistus."""
import ast
import io
import json
import tempfile
import unittest
from pathlib import Path

from aivo import hakumittari as hm

KIELLETYT = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "anthropic", "openai",
             "litellm", "subprocess", "ssl", "smtplib", "ftplib", "websockets"}


def kirjoita(hak, tunniste, tony, aivo):
    rivit = [{"aika": "2030-01-01T00:00:00", "rooli": "tony", "teksti": tony, "lahteet": []},
             {"aika": "2030-01-01T00:00:01", "rooli": "aivo", "teksti": aivo, "lahteet": []}]
    (hak / (tunniste + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rivit), encoding="utf-8")


class RecallTesti(unittest.TestCase):
    def test_tunnettu_esimerkki(self):
        tulokset = [("a", ["a", "x", "y"]), ("b", ["x", "y", "b"]), ("c", ["x", "y", "z", "c"]), ("d", [])]
        self.assertEqual(hm.recall_at_k(tulokset, 1), 0.25)
        self.assertEqual(hm.recall_at_k(tulokset, 3), 0.5)
        self.assertEqual(hm.recall_at_k(tulokset, 4), 0.75)
        self.assertEqual(hm.recall_at_k([], 5), 0.0)

    def test_mittaa_vaihdettavalla_haulla(self):
        with tempfile.TemporaryDirectory() as d:
            hak = Path(d)
            kirjoita(hak, "k1", "kala", "keitto")
            kirjoita(hak, "k2", "auto", "renkaat")
            (hak / "kysymykset.jsonl").write_text(
                json.dumps({"kysymys": "kala?", "oikea": "k1", "tyyppi": "suora"}) + "\n"
                + json.dumps({"kysymys": "auto?", "oikea": "k2", "tyyppi": "suora"}) + "\n", encoding="utf-8")
            aina_k1 = lambda kysymys, kirjasto: ["k1", "k2"]
            kaanteinen = lambda kysymys, kirjasto: ["k2", "k1"]
            self.assertEqual(hm.mittaa(aina_k1, hak, k=1)["recall"], 0.5)
            self.assertEqual(hm.mittaa(kaanteinen, hak, k=1)["recall"], 0.5)
            t = hm.mittaa(aina_k1, hak, k=1)
            self.assertEqual([v["oikea"] for v in t["epaonnistuneet"]], ["k2"])
            self.assertEqual(t["epaonnistuneet"][0]["sija"], 2)
            self.assertEqual(hm.mittaa(aina_k1, hak, k=2)["recall"], 1.0)

    def test_haku_saa_kirjaston_md_tiedostot(self):
        nahty = []
        with tempfile.TemporaryDirectory() as d:
            hak = Path(d)
            kirjoita(hak, "k1", "kala", "keitto")
            (hak / "kysymykset.jsonl").write_text(
                json.dumps({"kysymys": "kala?", "oikea": "k1"}) + "\n", encoding="utf-8")
            hm.mittaa(lambda q, kirj: nahty.extend(p.name for p in Path(kirj).iterdir()) or ["k1"], hak)
        self.assertEqual(nahty, ["k1.md"])

    def test_nykyinen_haku_loytaa_sananosuman(self):
        with tempfile.TemporaryDirectory() as d:
            kirj = Path(d)
            (kirj / "a.md").write_text("Tony: sorsapata\n", encoding="utf-8")
            (kirj / "b.md").write_text("Tony: kuntosali penkkipunnerrus\n", encoding="utf-8")
            self.assertEqual(hm.nykyinen_haku("penkkipunnerrus ohjelma", d)[0], "b")

    def test_oma_aineisto_latautuu_ja_nykyhaku_ajaa(self):
        keskustelut, kysymykset = hm.lataa_aineisto()
        self.assertGreaterEqual(len(keskustelut), 25)
        self.assertEqual(len(kysymykset), 20)
        self.assertTrue(all(q["oikea"] in keskustelut for q in kysymykset))
        t = hm.mittaa()
        self.assertEqual(t["kysymyksia"], 20)
        self.assertTrue(0.0 <= t["recall"] <= 1.0)
        self.assertTrue(t["epaonnistuneet"], "aineistossa pitaa olla kysymyksia, joissa sanahaku epaonnistuu")

    def test_tuloste_ja_main(self):
        ulos = io.StringIO()
        hm.tulosta(hm.mittaa(lambda q, k: [], hm.OLETUS_AINEISTO), ulos)
        self.assertIn("recall@5 = 0.000", ulos.getvalue())
        self.assertEqual(hm.main(["--haku", "ei_ole_olemassa:x"]), 2)


class RiippuvuusTesti(unittest.TestCase):
    def test_ei_verkko_eika_mallikirjastoja(self):
        puu = ast.parse(Path(hm.__file__).read_text(encoding="utf-8"))
        tuodut = set()
        for n in ast.walk(puu):
            if isinstance(n, ast.Import):
                tuodut |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                tuodut.add(n.module.split(".")[0])
        self.assertEqual(tuodut & KIELLETYT, set())


if __name__ == "__main__":
    unittest.main()
