import contextlib
import io
import unittest
from unittest import mock

from agentti import aamupaketti as ap


def feikki(prt, tiedostot, ci="success", ci_tila="completed"):
    """prt: {repo: [pr-dictit]}, tiedostot: {numero: [tiedostonimet]}."""
    def hae(url):
        if "/pulls?state=open" in url:
            repo = url.split("/repos/%s/" % ap.OMISTAJA)[1].split("/")[0]
            return prt.get(repo, [])
        if "/check-runs" in url:
            return {"check_runs": [{"status": ci_tila, "conclusion": ci}]}
        if "/files" in url:
            nro = int(url.split("/pulls/")[1].split("/")[0])
            return [{"filename": n} for n in tiedostot[nro]]
        raise AssertionError(url)
    return hae


def pr(nro, otsikko="x", draft=False):
    return {"number": nro, "title": otsikko, "draft": draft, "head": {"sha": "abc"}, "html_url": "https://github.com/o/r/pull/%d" % nro}


class KerausTesti(unittest.TestCase):
    def test_ryhmittely(self):
        hae = feikki({"agentti-pohja": [pr(1), pr(2), pr(3, draft=True)]},
                     {1: ["yojono/ajuri.py", "test/test_a.py"], 2: ["test/test_a.py", "CHANGELOG.md"]})
        r = ap.keraa(hae)
        self.assertEqual([x["numero"] for x in r["tony"]], [1])
        self.assertEqual([x["numero"] for x in r["automerge"]], [2])
        self.assertEqual([(x["numero"], x["syy"]) for x in r["muut"]], [(3, "luonnos")])

    def test_ci_punainen_ja_kesken_menevat_muihin(self):
        r = ap.keraa(feikki({"agentti-pohja": [pr(1)]}, {1: ["test/test_a.py"]}, ci="failure"))
        self.assertEqual([(x["numero"], x["syy"]) for x in r["muut"]], [(1, "CI punainen")])
        r = ap.keraa(feikki({"agentti-pohja": [pr(1)]}, {1: ["test/test_a.py"]}, ci_tila="in_progress"))
        self.assertEqual([(x["numero"], x["syy"]) for x in r["muut"]], [(1, "CI kesken")])

    def test_suojattu_pr_on_tonylle_vaikka_ci_kesken(self):
        r = ap.keraa(feikki({"agentti-pohja": [pr(1)]}, {1: ["tools/mutantit.py"]}, ci_tila="in_progress"))
        self.assertEqual([x["numero"] for x in r["tony"]], [1])

    def test_uudelleennimeaminen_suojatusta_polusta_on_tonylle(self):
        def hae(url):
            if "/pulls?state=open" in url:
                return [pr(1)] if "agentti-pohja" in url else []
            if "/check-runs" in url:
                return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
            return [{"filename": "test/uusi.py", "previous_filename": "tools/vanha.py"}]
        self.assertEqual([x["numero"] for x in ap.keraa(hae)["tony"]], [1])

    def test_hakuvirhe_ei_kaada(self):
        def hae(url):
            raise OSError("verkko")
        self.assertEqual(ap.keraa(hae), {"tony": [], "automerge": [], "muut": []})

    def test_tiedostojen_hakuvirhe_menee_muihin(self):
        def hae(url):
            if "/pulls?state=open" in url:
                return [pr(1)] if "agentti-pohja" in url else []
            if "/check-runs" in url:
                return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
            raise OSError("x")
        self.assertEqual([(x["numero"], x["syy"]) for x in ap.keraa(hae)["muut"]], [(1, "tiedostoja ei saatu")])

    def test_otsikko_lyhennetaan_ja_rivinvaihdot_poistetaan(self):
        r = ap.keraa(feikki({"agentti-pohja": [pr(1, "a\nb " + "x" * 100)]}, {1: ["test/test_a.py"]}))
        otsikko = r["automerge"][0]["otsikko"]
        self.assertEqual(len(otsikko), ap.OTSIKKO_MAX)
        self.assertNotIn("\n", otsikko)


class MuotoiluJaMainTesti(unittest.TestCase):
    def test_muotoilu_nayttaa_ryhmat_ja_linkit(self):
        hae = feikki({"agentti-pohja": [pr(1, "suojattu"), pr(2, "tavallinen")]}, {1: ["yojono/a.py"], 2: ["test/test_a.py"]})
        teksti = ap.muotoile(ap.keraa(hae))
        self.assertIn("Sinun mergattavat (suojatut polut): 1", teksti)
        self.assertIn("Automerge hoitaa (CI vihrea): 1", teksti)
        self.assertIn("- agentti-pohja #1 suojattu (CI vihrea)\n  https://github.com/o/r/pull/1", teksti)

    def test_tyhja(self):
        self.assertIn("Ei avoimia PR:ita.", ap.muotoile({"tony": [], "automerge": [], "muut": []}))

    def ajaa(self, argv, env=None, laheta=True):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe), mock.patch.object(ap.telegram, "laheta", return_value=laheta) as t:
            rc = ap.main(argv, hae=feikki({}, {}), env=env or {})
        return rc, ulos.getvalue(), virhe.getvalue(), t

    def test_oletushaku_lukee_json_ja_pyytaa_user_agentin(self):
        class V:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'[{"number": 1}]'
        with mock.patch.object(ap.urllib.request, "urlopen", return_value=V()) as u:
            self.assertEqual(ap._oletushaku("https://api.github.com/x"), [{"number": 1}])
        pyynto = u.call_args[0][0]
        self.assertEqual(pyynto.get_header("User-agent"), "agenttifirma-aamupaketti")
        self.assertEqual(u.call_args[1]["timeout"], 20)

    def test_ci_tila_kesken_kun_runeja_ei_tai_haku_kaatuu(self):
        self.assertEqual(ap._ci(lambda u: {"check_runs": []}, "r", "abc"), "kesken")

        def kaatuu(url):
            raise OSError("x")
        self.assertEqual(ap._ci(kaatuu, "r", "abc"), "kesken")
        self.assertEqual(ap._ci(lambda u: {"check_runs": [{"status": "completed", "conclusion": "success"}]}, "r", "abc"), "vihrea")
        self.assertEqual(ap._ci(lambda u: {"check_runs": [{"status": "completed", "conclusion": "failure"}]}, "r", "abc"), "punainen")

    def test_pr_ilman_head_kenttaa_ei_kaada(self):
        p = {"number": 1, "title": "x", "draft": False, "html_url": "https://github.com/o/r/pull/1", "head": None}
        seen = []

        def hae(url):
            if "/pulls?state=open" in url:
                return [p] if "agentti-pohja" in url else []
            seen.append(url)
            if "/check-runs" in url:
                return {"check_runs": []}
            return [{"filename": "test/test_a.py"}]
        self.assertEqual(len(ap.keraa(hae)["muut"]), 1)
        self.assertIn("/commits//check-runs", seen[0])

    def test_main_lukee_sys_argvn_oletuksena(self):
        ulos, virhe = io.StringIO(), io.StringIO()
        with mock.patch.object(ap.sys, "argv", ["aamupaketti", "--muu"]), contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            self.assertEqual(ap.main(hae=feikki({}, {}), env={}), 2)

    def test_main_tulostaa_ilman_lahetysta(self):
        rc, ulos, _, t = self.ajaa([])
        self.assertEqual(rc, 0)
        self.assertIn("Aamupaketti", ulos)
        t.assert_not_called()

    def test_main_liittaa_yojono_pr_laatumittarin(self):
        _, ulos, _, _ = self.ajaa([])
        self.assertIn("Yojono-PR:t 30 vrk: 0 mergattu, 0 suljettu, 0 auki", ulos)

    def test_main_nostoehdot_vain_kulutiedon_kanssa(self):
        import json, os, tempfile
        _, ilman, _, _ = self.ajaa([], env={"YOJONO_PERUS": "/ei/ole/olemassa"})
        self.assertNotIn("Paivakaton nosto", ilman)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "tila.json"), "w") as f:
                json.dump({"kulut": {"2999-01-01": 1.0}}, f)
            _, ulos, _, _ = self.ajaa([], env={"YOJONO_PERUS": d})
        self.assertIn("Paivakaton nosto (30 vrk)", ulos)
        self.assertIn("ei viela:", ulos)

    def test_main_laatumittarin_virhe_ei_esta_aamupakettia(self):
        with mock.patch.object(ap.pr_laatu, "keraa", side_effect=RuntimeError("x")):
            rc, ulos, _, _ = self.ajaa([])
        self.assertEqual(rc, 0)
        self.assertIn("Aamupaketti", ulos)
        self.assertNotIn("Yojono-PR:t", ulos)

    def test_main_laheta_kayttaa_yojonon_telegram_ymparistoa(self):
        rc, _, _, t = self.ajaa(["--laheta"], env={"YOJONO_TELEGRAM_TOKEN": "tok", "YOJONO_TELEGRAM_CHAT": "42"})
        self.assertEqual(rc, 0)
        self.assertEqual(t.call_args[0][1], {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"})

    def test_main_lahetysvirhe_palauttaa_1(self):
        rc, _, virhe, _ = self.ajaa(["--laheta"], laheta=False)
        self.assertEqual(rc, 1)
        self.assertIn("epaonnistui", virhe)

    def test_main_tuntematon_argumentti_palauttaa_2(self):
        rc, ulos, virhe, _ = self.ajaa(["--muu"])
        self.assertEqual((rc, ulos), (2, ""))
        self.assertIn("kaytto:", virhe)


if __name__ == "__main__":
    unittest.main()
