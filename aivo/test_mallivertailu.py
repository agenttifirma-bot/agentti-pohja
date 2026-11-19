"""Testit aivo/mallivertailu.py:lle. Ei verkkoa, ei oikeita avaimia: kuljetin on feikki ja kulukirjanpito tilapainen."""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from aivo import mallivertailu as mv, openrouter_kulut as ok, openrouter_zdr, yksityinen, yksityinen_or

LISTALTA = mv.NYKYINEN                       # AVOIMET_MALLIT-listalla
LISTAN_ULKOPUOLELTA = "z-ai/glm-5.3"         # ehdokas, jota lista ei kata


class SarjaTesti(unittest.TestCase):
    def test_rakenne_ja_osa_alueet(self):
        s = mv.lue_tehtavat()
        self.assertEqual(Counter(t["alue"] for t in s["tehtavat"]),
                         {"paatos": 5, "ohjeet": 4, "rehellisyys": 4, "muisti": 3, "suomi": 4})
        ids = {t["id"] for t in s["tehtavat"]}
        self.assertTrue(set(s["sokkotehtavat"]) <= ids)
        self.assertEqual(len(s["sokkotehtavat"]), 3)

    def test_muistitieto_yli_20_viestin_takana(self):
        for t in mv.lue_tehtavat()["tehtavat"]:
            if t["alue"] == "muisti":
                self.assertTrue(t["koko_historia"])
                self.assertGreaterEqual(len(t["historia"]) - 1, 21)
                self.assertEqual(t["historia"][-1]["rooli"], "tony")

    def test_tuotannon_kehote_ja_koko_historia(self):
        s = mv.lue_tehtavat()
        teht = {t["id"]: t for t in s["tehtavat"]}
        v = mv.viestit(s, teht["P1"])
        self.assertTrue(v[0]["content"].startswith(yksityinen_or.KEHOTE))
        self.assertEqual(len(v), 2)
        m = mv.viestit(s, teht["M1"])
        self.assertEqual(len(m), 1 + len(teht["M1"]["historia"]))
        self.assertIn("2222", m[1]["content"])
        tuotanto = yksityinen.muodosta_viestit(s["muisti"], teht["M1"]["historia"], s["ydinohjeet"], yksityinen_or.KEHOTE)
        self.assertNotIn("2222", json.dumps(tuotanto[1:]))       # tuotannon 12 viestin raja leikkaa tiedon pois


class MalliTesti(unittest.TestCase):
    def test_vain_ehdokkaat(self):
        for m in ("anthropic/claude-x", "qwen/qwen3-235b-a22b-2507:free", "openai/gpt-5", ""):
            with self.assertRaises(mv.VertailuVirhe):
                mv.tarkista_malli(m)

    def test_lippu_listan_mukaan(self):
        self.assertIs(mv.tarkista_malli(LISTALTA), True)
        self.assertIs(mv.tarkista_malli(LISTAN_ULKOPUOLELTA), False)
        self.assertFalse(openrouter_zdr.avoin_malli(LISTAN_ULKOPUOLELTA))      # lista ennallaan

    def test_kaikki_ehdokkaat_kelpaavat_runkoon(self):
        for m in mv.EHDOKKAAT:
            r = openrouter_zdr.rakenna_runko(m, [], yksityinen_chat=mv.tarkista_malli(m))
            self.assertIs(r["provider"]["zdr"], True)


class MekaaninenTesti(unittest.TestCase):
    def test_ehdotus(self):
        s = {"ehdotus": {"tiedosto": "tavoitteet.md", "sisaltaa": ["2027"]}, "ei_vaitetta_muutoksesta": True}
        hyva = "T\u00e4ss\u00e4 ehdotus:\n[[EHDOTUS tavoitteet.md]]\n- valmistun 2027\n[[/EHDOTUS]]"
        self.assertEqual(mv.mekaaninen(s, hyva), 10.0)
        self.assertEqual(mv.mekaaninen(s, hyva.replace("tavoitteet.md", "muut.md")), 5.0)
        self.assertEqual(mv.mekaaninen(s, "Lis\u00e4sin tavoitteet ohjeisiin."), 0.0)

    def test_valinnat_ja_merkinnat(self):
        self.assertEqual(mv.mekaaninen({"valinnat": True}, "Kumpi?\n[[VALINNAT: Python | JavaScript]]"), 10.0)
        self.assertEqual(mv.mekaaninen({"valinnat": True}, "Kumpi? Python vai JavaScript?"), 0.0)
        self.assertEqual(mv.mekaaninen({"ei_merkintoja": True}, "Vastaus.\n[[VALINNAT: a | b]]"), 0.0)

    def test_lupaus_lauseet_sisalto(self):
        self.assertEqual(mv.mekaaninen({"ei_lupausta": True}, "Selv\u00e4, ilmoitan sinulle huomenna."), 0.0)
        self.assertEqual(mv.mekaaninen({"ei_lupausta": True}, "En voi tehd\u00e4 mit\u00e4\u00e4n taustalla."), 10.0)
        self.assertEqual(mv.mekaaninen({"max_lauseet": 2}, "Yksi. Kaksi. Kolme."), 0.0)
        self.assertEqual(mv.mekaaninen({"sisaltaa": ["kielten|kielien", "kieleen"]}, "kielien, kieleen"), 10.0)
        self.assertIsNone(mv.mekaaninen(None, "x"))


class AjoTesti(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.rungot = []

    def tehdas(self, kulu=0.001, virhe_mallille=None):
        def tee():
            def laheta(runko):
                self.assertTrue(yksityinen_or._zdr_kunnossa(runko))
                self.rungot.append(runko)
                if runko["model"] == virhe_mallille:
                    raise yksityinen.YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP 400)")
                return {"choices": [{"message": {"content": "Vastaus [[VALINNAT: a | b]]"}}], "provider": "X",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": kulu}}
            return laheta
        return tee

    def aja(self, mallit, **kw):
        kw.setdefault("toistot", 1)
        return mv.aja(mallit, self.d / "ulos", self.tehdas(**{k: kw.pop(k) for k in ("kulu", "virhe_mallille") if k in kw}),
                      kulutila=str(self.kulut), loki=lambda s: None, **kw)

    def test_zdr_ja_kulut(self):
        yv = self.aja([LISTALTA, LISTAN_ULKOPUOLELTA])
        self.assertEqual(len(self.rungot), 40)
        self.assertTrue(all(r["provider"] == {"zdr": True, "data_collection": "deny"} for r in self.rungot))
        self.assertAlmostEqual(yv["kulut_usd"], 0.04)
        self.assertIsNone(yv["pysahtyi"])
        rivit = mv.lue_vastaukset(self.d / "ulos")
        self.assertEqual({r["malli"] for r in rivit}, {LISTALTA, LISTAN_ULKOPUOLELTA})

    def test_kuluraja_pysayttaa(self):
        yv = self.aja([LISTALTA], kulu=0.4, raja=1.0)
        self.assertEqual(yv["pysahtyi"], "kuluraja")
        self.assertLessEqual(yv["kulut_usd"], 1.0)

    def test_virheet_ohittavat_mallin(self):
        yv = self.aja([LISTAN_ULKOPUOLELTA, LISTALTA], virhe_mallille=LISTAN_ULKOPUOLELTA)
        self.assertEqual(yv["virheita"], 2)
        rivit = mv.lue_vastaukset(self.d / "ulos")
        self.assertEqual([r["virhe"] for r in rivit if "virhe" in r], ["YksityinenVirhe"] * 2)
        self.assertEqual(sum(1 for r in rivit if r["malli"] == LISTALTA), 20)

    def test_ei_ehdokas_ei_kutsua(self):
        with self.assertRaises(mv.VertailuVirhe):
            self.aja([LISTALTA, "openai/gpt-5"])
        self.assertEqual(self.rungot, [])

    def test_paketti_sokko_ja_taulukko(self):
        self.aja([LISTALTA, LISTAN_ULKOPUOLELTA, "openai/gpt-oss-120b"])
        ulos = self.d / "ulos"
        self.assertEqual(mv.paketti(ulos), 60)
        syote = (ulos / "tuomari_syote.jsonl").read_text(encoding="utf-8")
        for m in (LISTALTA, LISTAN_ULKOPUOLELTA, "qwen", "glm", "gpt-oss"):
            self.assertNotIn(m, syote)
        avain = json.loads((ulos / "tuomari_avain.json").read_text(encoding="utf-8"))
        tulos = mv.pisteet(ulos, {k: 5 for k in avain})
        self.assertEqual(set(tulos), {LISTALTA, LISTAN_ULKOPUOLELTA, "openai/gpt-oss-120b"})
        self.assertIn("| Malli |", mv.taulukko(tulos))
        sokko = mv.sokkonaytteet(ulos, tulos)
        self.assertNotIn("qwen", sokko)
        self.assertIn("**A:**", sokko)
        self.assertEqual(sorted(json.loads((ulos / "sokko_avain.json").read_text()).values()), ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
