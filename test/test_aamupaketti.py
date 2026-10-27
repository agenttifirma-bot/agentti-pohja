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

    def test_main_tulostaa_ilman_lahetysta(self):
        rc, ulos, _, t = self.ajaa([])
        self.assertEqual(rc, 0)
        self.assertIn("Aamupaketti", ulos)
        t.assert_not_called()

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
