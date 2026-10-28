import contextlib
import io
import unittest
from unittest import mock
from datetime import datetime, timezone

from agentti import pr_laatu as pl

NYT = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def pr(nro, otsikko, tila="open", merged=False, luotu="2026-10-27T10:00:00Z", kirjoittaja="agenttifirma-bot"):
    return {"number": nro, "title": otsikko, "state": tila, "merged_at": "2026-10-27T12:00:00Z" if merged else None,
            "created_at": luotu, "user": {"login": kirjoittaja}}


def feikki(data):
    def hae(url):
        repo = url.split("/repos/%s/" % pl.OMISTAJA)[1].split("/")[0]
        return data.get(repo, [])
    return hae


class KerausTesti(unittest.TestCase):
    def test_laskee_tilat_repoittain_ja_aiheittain(self):
        hae = feikki({
            "llm-stopcheck": [pr(1, "[yojono] yojono: testit llm-stopcheck", "closed", merged=True),
                              pr(2, "yojono: readme llm-stopcheck", "closed"),
                              pr(3, "yojono: riippuvuudet llm-stopcheck", "open")],
            "mcp-model-router": [pr(4, "yojono: testit mcp-model-router", "closed", merged=True), pr(5, "jokin muu", "open")],
        })
        t = pl.keraa(hae, 30, NYT)
        self.assertEqual(t["yht"], {"mergattu": 2, "suljettu": 1, "auki": 2})
        self.assertEqual(t["repoittain"]["llm-stopcheck"], {"mergattu": 1, "suljettu": 1, "auki": 1})
        self.assertEqual(t["aiheittain"]["testit"], {"mergattu": 2, "suljettu": 0, "auki": 0})
        self.assertEqual(t["aiheittain"]["muu"], {"mergattu": 0, "suljettu": 0, "auki": 1})

    def test_vain_botin_prt_ja_vain_ikkunan_sisalta(self):
        hae = feikki({"llm-stopcheck": [pr(1, "yojono: testit x", "open", kirjoittaja="tonyweckstrom1987"),
                                        pr(2, "yojono: testit x", "open", luotu="2026-09-01T00:00:00Z"),
                                        pr(3, "yojono: testit x", "open", luotu="roska"),
                                        pr(4, "yojono: testit x", "open", kirjoittaja="AgenttiFirma-Bot")]})
        t = pl.keraa(hae, 30, NYT)
        self.assertEqual(t["yht"], {"mergattu": 0, "suljettu": 0, "auki": 1})

    def test_ikkunan_raja_paivissa(self):
        hae = feikki({"llm-stopcheck": [pr(1, "yojono: testit x", "open", luotu="2026-10-20T00:00:00Z")]})
        self.assertEqual(pl.keraa(hae, 7, NYT)["yht"]["auki"], 0)
        self.assertEqual(pl.keraa(hae, 9, NYT)["yht"]["auki"], 1)

    def test_hakuvirhe_ei_kaada(self):
        def hae(url):
            raise OSError("verkko")
        self.assertEqual(pl.keraa(hae, 30, NYT)["yht"], {"mergattu": 0, "suljettu": 0, "auki": 0})

    def test_aihe_otsikosta(self):
        for otsikko, odotus in (("yojono: testit a", "testit"), ("[yojono] yojono: README b", "readme"), ("yojono: riippuvuudet c", "riippuvuudet"),
                                ("yojono: ominaisuus d", "ominaisuus"), ("yojono: katselmointi e", "muu"), (None, "muu")):
            self.assertEqual(pl.aihe(otsikko), odotus)


class MuotoiluJaMainTesti(unittest.TestCase):
    def test_muotoilu(self):
        hae = feikki({"llm-stopcheck": [pr(1, "yojono: testit x", "closed", merged=True), pr(2, "yojono: readme x", "closed"), pr(3, "yojono: readme x", "open")]})
        teksti = pl.muotoile(pl.keraa(hae, 30, NYT), 30)
        self.assertIn("Yojono-PR:t 30 vrk: 1 mergattu, 1 suljettu, 1 auki (mergausprosentti 50 %)", teksti)
        self.assertIn("repoittain (mergattu/kaikki): llm-stopcheck 1/3", teksti)
        self.assertIn("aiheittain (mergattu/kaikki): readme 0/2, testit 1/1", teksti)

    def test_mergausprosentti_pyoristyy(self):
        t = {"mergattu": 2, "suljettu": 1, "auki": 0}
        self.assertEqual(pl._osuus(t), "67 %")
        self.assertEqual(pl._osuus({"mergattu": 1, "suljettu": 2, "auki": 5}), "33 %")

    def test_oletushaku_lukee_json_ja_pyytaa_user_agentin(self):
        class V:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'[{"number": 1}]'
        with mock.patch.object(pl.urllib.request, "urlopen", return_value=V()) as u:
            self.assertEqual(pl._oletushaku("https://api.github.com/x"), [{"number": 1}])
        pyynto = u.call_args[0][0]
        self.assertEqual(pyynto.full_url, "https://api.github.com/x")
        self.assertEqual(pyynto.get_header("User-agent"), "agenttifirma-pr-laatu")
        self.assertEqual(u.call_args[1]["timeout"], 20)

    def test_main_lukee_sys_argvn(self):
        ulos = io.StringIO()
        with mock.patch.object(pl.sys, "argv", ["pr_laatu", "7"]), mock.patch.object(pl, "_oletushaku", return_value=[]), contextlib.redirect_stdout(ulos):
            self.assertEqual(pl.main(), 0)
        self.assertIn("7 vrk", ulos.getvalue())

    def test_tyhja_ei_jaa_nollalla(self):
        teksti = pl.muotoile({"yht": {"mergattu": 0, "suljettu": 0, "auki": 0}, "repoittain": {}, "aiheittain": {}}, 7)
        self.assertEqual(teksti, "Yojono-PR:t 7 vrk: 0 mergattu, 0 suljettu, 0 auki (mergausprosentti -)")

    def ajaa(self, argv):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = pl.main(argv, hae=feikki({}))
        return rc, ulos.getvalue(), virhe.getvalue()

    def test_main_oletus_ja_paivat(self):
        rc, ulos, _ = self.ajaa([])
        self.assertEqual(rc, 0)
        self.assertIn("30 vrk", ulos)
        self.assertIn("7 vrk", self.ajaa(["7"])[1])

    def test_main_virheellinen_argumentti(self):
        for a in (["x"], ["1", "2"]):
            rc, ulos, virhe = self.ajaa(a)
            self.assertEqual((rc, ulos), (2, ""))
            self.assertIn("kaytto:", virhe)


if __name__ == "__main__":
    unittest.main()
