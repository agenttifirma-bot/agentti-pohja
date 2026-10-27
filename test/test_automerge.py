import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import automerge as am

PR = {"draft": False, "head_repo": "o/r", "base_repo": "o/r", "labels": []}


def tied(nimi, status="modified", changes=5, **lisa):
    d = {"filename": nimi, "status": status, "changes": changes}
    d.update(lisa)
    return d


BOTTI_PR = {"draft": False, "head_repo": "agenttifirma-bot/r", "base_repo": "o/r", "labels": [], "author": "agenttifirma-bot",
            "head_ref": "yo/readme-2026-10-22", "base_ref": "main"}

BOTTI_PR_TESTIT = dict(BOTTI_PR, head_ref="yo/testit-2026-10-22")


class BotinForkkiTesti(unittest.TestCase):
    def test_botin_readme_pr_kelpaa(self):
        for nimi in ("README.md", "docs/ohje.md", "CHANGELOG.md"):
            ok, syyt = am.arvioi(BOTTI_PR, [tied(nimi)])
            self.assertTrue(ok, syyt)

    def test_vain_md_forkista(self):
        for nimi in ("test/test_x.py", "agentti/ajo.py", "requirements.txt", "README.txt"):
            self.assertFalse(am.arvioi(BOTTI_PR, [tied(nimi)])[0], nimi)
        self.assertFalse(am.arvioi(BOTTI_PR, [tied("README.md"), tied("test/test_x.py")])[0])

    def test_suojatut_polut_estavat_silti(self):
        for nimi in (".github/workflows/x.md", "tools/automerge.md", "docs/secrets.md", "docs/api_key.md", "isanta/a.md"):
            self.assertFalse(am.arvioi(BOTTI_PR, [tied(nimi)])[0], nimi)

    def test_muu_tekija_forkista_ei_kelpaa(self):
        for kentat in ({"author": "joku-muu"}, {"author": None}, {"author": "agenttifirma-bot-2"}):
            self.assertFalse(am.arvioi(dict(BOTTI_PR, **kentat), [tied("README.md")])[0], kentat)

    def test_vaara_forkki_ei_kelpaa(self):
        for head in ("joku-muu/r", "agenttifirma-bot/muu-repo", "agenttifirma-bot/", None, ""):
            self.assertFalse(am.arvioi(dict(BOTTI_PR, head_repo=head), [tied("README.md")])[0], head)

    def test_vaara_haara_tai_base_ei_kelpaa(self):
        for kentat in ({"head_ref": "main"}, {"head_ref": "yo/riippuvuudet-2026-10-22"}, {"head_ref": "yo/muu-x"}, {"head_ref": "yo/readme-"}, {"head_ref": "yo/readme-A"},
                       {"head_ref": "feature/readme-x"}, {"head_ref": None}, {"base_ref": "kehitys"}, {"base_ref": None}):
            self.assertFalse(am.arvioi(dict(BOTTI_PR, **kentat), [tied("README.md")])[0], kentat)

    def test_muut_ehdot_pitavat_forkissakin(self):
        self.assertFalse(am.arvioi(dict(BOTTI_PR, draft=True), [tied("README.md")])[0])
        self.assertFalse(am.arvioi(dict(BOTTI_PR, labels=["ei-automerge"]), [tied("README.md")])[0])
        self.assertFalse(am.arvioi(BOTTI_PR, [])[0])
        self.assertFalse(am.arvioi(BOTTI_PR, [tied("README.md", status="removed")])[0])
        self.assertFalse(am.arvioi(BOTTI_PR, [tied("README.md", changes=am.MAX_RIVEJA + 1)])[0])
        self.assertFalse(am.arvioi(BOTTI_PR, [tied("a%d.md" % i) for i in range(am.MAX_TIEDOSTOA + 1)])[0])

    def test_saman_repon_pr_ei_tarvitse_tekijaa(self):
        self.assertTrue(am.arvioi(PR, [tied("README.md")])[0])

    def test_hae_pr_palauttaa_tekijan_ja_haarat(self):
        data = {"draft": False, "user": {"login": "agenttifirma-bot"}, "labels": [],
                "head": {"ref": "yo/readme-x", "repo": {"full_name": "agenttifirma-bot/r"}},
                "base": {"ref": "main", "repo": {"full_name": "o/r"}}}
        r = subprocess.CompletedProcess([], 0, stdout=json.dumps(data), stderr="")
        with mock.patch.object(am, "_gh", return_value=r):
            pr = am.hae_pr("o/r", "1")
        self.assertEqual((pr["author"], pr["head_ref"], pr["base_ref"]), ("agenttifirma-bot", "yo/readme-x", "main"))
        self.assertTrue(am.arvioi(pr, [tied("README.md")])[0])


class BotinKoodiTesti(unittest.TestCase):
    def pr(self, haara="yo/ominaisuus-2026-10-24-a"):
        return dict(BOTTI_PR, head_ref=haara)

    def test_ominaisuus_ja_testit_koodi_kelpaa(self):
        for haara in ("yo/ominaisuus-2026-10-24-a", "yo/testit-2026-10-24"):
            for nimi in ("src/llm_stopcheck/cli.py", "tests/test_cli.py", "src/index.ts", "lib/a.mjs", "README.md"):
                ok, syyt = am.arvioi(self.pr(haara), [tied(nimi)])
                self.assertTrue(ok, (haara, nimi, syyt))

    def test_suojatut_ja_asetustiedostot_eivat_kelpaa(self):
        for nimi in (".github/workflows/ci.yml", "yojono/kehitys.sh", "yojono/ajuri.py", "agentti/portti.py", "agentti/ehdotukset.py",
                     "agentti/maaritys.py", "package.json", "package-lock.json", "requirements.txt", "pyproject.toml", "Dockerfile",
                     "tools/automerge.py", "src/api_key.py", "config.json", "run.sh", "a b.py", "../x.py"):
            ok, _ = am.arvioi(self.pr(), [tied(nimi)])
            self.assertFalse(ok, nimi)

    def test_master_base_kelpaa_ja_action_suojattu(self):
        self.assertTrue(am.arvioi(dict(self.pr(), base_ref="master"), [tied("src/a.ts")])[0])
        self.assertFalse(am.arvioi(dict(self.pr(), base_ref="kehitys"), [tied("src/a.ts")])[0])
        for nimi in ("action.yml", "action.yaml", "dist/index.js"):
            self.assertFalse(am.arvioi(self.pr(), [tied(nimi)])[0], nimi)

    def test_readme_haarasta_edelleen_vain_md(self):
        self.assertFalse(am.arvioi(self.pr("yo/readme-x"), [tied("src/a.py")])[0])

    def test_koodin_rajat(self):
        self.assertTrue(am.arvioi(self.pr(), [tied("a.py", changes=am.MAX_RIVEJA_KOODI)])[0])
        self.assertFalse(am.arvioi(self.pr(), [tied("a.py", changes=am.MAX_RIVEJA_KOODI + 1)])[0])
        self.assertFalse(am.arvioi(self.pr(), [tied("a.py", status="removed")])[0])
        self.assertFalse(am.arvioi(self.pr(), [tied("b.py", status="renamed", previous_filename="yojono/x.py")])[0])

    def test_muu_tekija_koodiforkista_ei_kelpaa(self):
        self.assertFalse(am.arvioi(dict(self.pr(), author="joku-muu"), [tied("a.py")])[0])
        self.assertFalse(am.arvioi(dict(self.pr(), head_repo="joku-muu/r"), [tied("a.py")])[0])


class WorkflowTesti(unittest.TestCase):
    def test_workflow_ei_lataa_pr_koodia_ja_rajaa_botin(self):
        import pathlib
        teksti = (pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "automerge.yml").read_text()
        self.assertIn("pull_request_target", teksti)
        self.assertIn("github.event.pull_request.user.login == 'agenttifirma-bot'", teksti)
        self.assertIn("head.repo.owner.login == 'agenttifirma-bot'", teksti)
        # PR:n omaa koodia ei saa checkoutata (ei ref/repository head-arvoihin)
        self.assertNotIn("pull_request.head.sha", teksti)
        self.assertNotIn("head.ref", teksti.replace("head.repo.owner.login", ""))


class ArvioiTesti(unittest.TestCase):
    def test_dokumentit_ja_testit_kelpaavat(self):
        for nimi in ("README.md", "CHANGELOG.md", "docs/ohje.md", "test/test_x.py", "test/ali/test_y.py"):
            with self.subTest(nimi=nimi):
                ok, syyt = am.arvioi(PR, [tied(nimi)])
                self.assertTrue(ok, syyt)

    def test_koodi_ei_kelpaa(self):
        for nimi in ("agentti/ajo.py", "luo.py", "requirements.txt", "agentti/llm.py"):
            with self.subTest(nimi=nimi):
                self.assertFalse(am.arvioi(PR, [tied(nimi)])[0])

    def test_suojatut_polut(self):
        for nimi in (".github/workflows/ci.yml", ".github/dependabot.yml", "tools/automerge.py", "isanta/asenna.sh",
                     "isanta/snapshot_isanta.py", "systemd/x.service.mall", "yojono/systemd/y.timer.mall",
                     "agentti/config.py", "agentti/rajat.py", ".env", "docs/.env.md", "docs/secrets.md",
                     "test/test_token_esimerkki.py", "docs/api_key.md", "test/../agentti/ajo.py"):
            with self.subTest(nimi=nimi):
                self.assertFalse(am.arvioi(PR, [tied(nimi)])[0])

    def test_suojattu_voittaa_sallitun(self):
        ok, syyt = am.arvioi(PR, [tied("README.md"), tied(".github/workflows/x.md")])
        self.assertFalse(ok)
        self.assertTrue(any("suojattu" in s for s in syyt))

    def test_uudelleennimeaminen_suojatusta_polusta(self):
        t = tied("docs/uusi.md", status="renamed", previous_filename="isanta/asenna.sh")
        self.assertFalse(am.arvioi(PR, [t])[0])

    def test_poisto_ei_kelpaa(self):
        self.assertFalse(am.arvioi(PR, [tied("README.md", status="removed")])[0])

    def test_pelkat_testit_saavat_suuremman_rajan(self):
        self.assertTrue(am.arvioi(PR, [tied("test/test_a.py", changes=am.MAX_RIVEJA_TESTIT)])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_a.py", changes=am.MAX_RIVEJA_TESTIT + 1)])[0])
        self.assertTrue(am.arvioi(PR, [tied("test/test_a.py", changes=500), tied("CHANGELOG.md", changes=2)])[0])
        self.assertTrue(am.arvioi(PR, [tied("test/test_a.py", changes=500), tied("docs/a.md", changes=2)])[0])

    def test_suuri_raja_vain_testeille_ja_dokumenteille(self):
        self.assertFalse(am.arvioi(PR, [tied("README.md", changes=am.MAX_RIVEJA + 1)])[0])
        self.assertFalse(am.arvioi(PR, [tied("docs/a.md", changes=am.MAX_RIVEJA + 1)])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_a.py", changes=500), tied("src/a.py", changes=2)])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_a.py", changes=500), tied("tools/x.py", changes=2)])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_a.py", changes=500), tied("agentti/portti.py", changes=2)])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_a.py", changes=500, status="removed")])[0])
        self.assertFalse(am.arvioi(PR, [tied("test/test_b.py", changes=500, status="renamed", previous_filename="src/b.py")])[0])

    def test_botin_forkin_testit_pysyvat_400_rajassa(self):
        self.assertFalse(am.arvioi(BOTTI_PR_TESTIT, [tied("test/test_a.py", changes=am.MAX_RIVEJA_KOODI + 1)])[0])

    def test_koon_rajat(self):
        self.assertTrue(am.arvioi(PR, [tied("README.md", changes=am.MAX_RIVEJA)])[0])
        self.assertFalse(am.arvioi(PR, [tied("README.md", changes=am.MAX_RIVEJA + 1)])[0])
        paljon = [tied("docs/a%d.md" % i, changes=1) for i in range(am.MAX_TIEDOSTOA + 1)]
        self.assertFalse(am.arvioi(PR, paljon)[0])

    def test_pr_ehdot(self):
        self.assertFalse(am.arvioi(dict(PR, draft=True), [tied("README.md")])[0])
        self.assertFalse(am.arvioi(dict(PR, head_repo="fork/r"), [tied("README.md")])[0])
        self.assertFalse(am.arvioi(dict(PR, labels=["ei-automerge"]), [tied("README.md")])[0])
        self.assertFalse(am.arvioi(PR, [])[0])
        self.assertFalse(am.arvioi(dict(PR, head_repo=None), [tied("README.md")])[0])


def gh_feikki(pr, tiedostot, kutsut):
    def f(args, **kw):
        kutsut.append(args)
        osat = args[1:]
        if osat[0] == "api" and "--paginate" in osat:
            ulos = "\n".join(json.dumps(t) for t in tiedostot)
        elif osat[0] == "api":
            ulos = json.dumps({"draft": pr["draft"], "head": {"repo": {"full_name": pr["head_repo"]}},
                               "base": {"repo": {"full_name": pr["base_repo"]}},
                               "labels": [{"name": n} for n in pr["labels"]]})
        else:
            ulos = ""
        return subprocess.CompletedProcess(args, 0, ulos, "")
    return f


class MainTesti(unittest.TestCase):
    def aja(self, pr, tiedostot):
        kutsut = []
        env = {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7"}
        with mock.patch.dict("os.environ", env, clear=False), \
                mock.patch.object(am.subprocess, "run", gh_feikki(pr, tiedostot, kutsut)), \
                mock.patch("builtins.print"):
            koodi = am.main()
        return koodi, kutsut

    def merge_kutsut(self, kutsut):
        return [k for k in kutsut if k[1:3] == ["pr", "merge"]]

    def test_kelpaava_kytkee_automergen(self):
        koodi, kutsut = self.aja(PR, [tied("README.md")])
        self.assertEqual(koodi, 0)
        m = self.merge_kutsut(kutsut)
        self.assertEqual(len(m), 1)
        self.assertIn("--auto", m[0])
        self.assertIn("--squash", m[0])
        self.assertNotIn("--disable-auto", m[0])

    def test_kelpaamaton_poistaa_automergen(self):
        koodi, kutsut = self.aja(PR, [tied("agentti/ajo.py")])
        self.assertEqual(koodi, 0)
        m = self.merge_kutsut(kutsut)
        self.assertEqual(len(m), 1)
        self.assertIn("--disable-auto", m[0])
        self.assertNotIn("--auto", m[0])

    def test_virheelliset_ymparistomuuttujat(self):
        for env in ({"GITHUB_REPOSITORY": "x", "PR_NUMBER": "7"},
                    {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7; ls"},
                    {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": ""}):
            with self.subTest(env=env):
                with mock.patch.dict("os.environ", env, clear=False), mock.patch("builtins.print"):
                    self.assertEqual(am.main(), 2)

    def test_api_virhe_ei_kytke_mitaan(self):
        def f(args, **kw):
            return subprocess.CompletedProcess(args, 1, "", "boom")
        with mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7"}, clear=False), \
                mock.patch.object(am.subprocess, "run", f), mock.patch("builtins.print"):
            self.assertEqual(am.main(), 1)


class AutomergeTarkkaTesti(unittest.TestCase):
    def test_tyhja_polku(self):
        self.assertEqual(am.polku_ok(""), (False, "tyhja polku"))
        self.assertEqual(am.polku_ok(None), (False, "tyhja polku"))

    def test_base_repon_nimi_otetaan_ensimmaisen_kautoviivan_jalkeen(self):
        pr = dict(BOTTI_PR, base_repo="o/a/b", head_repo="agenttifirma-bot/a/b")
        self.assertEqual(am.botin_forkki_syyt(pr), [])

    def test_readme_haarassa_md_tiedoston_syy_tulee_vain_kerran_ja_oikealla_tekstilla(self):
        ok, syyt = am.arvioi(BOTTI_PR, [tied("a b.md")])
        self.assertFalse(ok)
        self.assertEqual(syyt, ["ei sallittu tyyppi: a b.md"])

    def test_puuttuva_changes_kentta_on_nolla(self):
        ok, syyt = am.arvioi(PR, [tied("a.md", changes=am.MAX_RIVEJA), {"filename": "b.md", "status": "added"}])
        self.assertTrue(ok, syyt)

    def test_gh_kutsun_parametrit(self):
        nahty = {}

        def f(args, **kw):
            nahty["args"], nahty["kw"] = args, kw
            return subprocess.CompletedProcess(args, 0, "", "")
        with mock.patch.object(am.subprocess, "run", f):
            am._gh("pr", "view")
        self.assertEqual(nahty["args"], ["gh", "pr", "view"])
        self.assertEqual(nahty["kw"], {"capture_output": True, "text": True, "timeout": 120})

    def test_virheviestit_rajataan_200_merkkiin(self):
        def f(args, **kw):
            return subprocess.CompletedProcess(args, 1, "", "A" * 100 + "B" * 200)
        with mock.patch.object(am.subprocess, "run", f):
            for fn, alku in ((am.hae_pr, "PR:n haku epaonnistui: "), (am.hae_tiedostot, "tiedostojen haku epaonnistui: ")):
                with self.assertRaises(RuntimeError) as e:
                    fn("o/r", "7")
                self.assertEqual(str(e.exception), alku + "B" * 200)

    def test_automergen_kytkenta_epaonnistuu(self):
        pr, tiedostot = PR, [tied("README.md")]

        def f(args, **kw):
            if args[1:3] == ["pr", "merge"]:
                return subprocess.CompletedProcess(args, 1, "", "A" * 100 + "B" * 200)
            return gh_feikki(pr, tiedostot, [])(args, **kw)
        with mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7"}, clear=False), \
                mock.patch.object(am.subprocess, "run", f), mock.patch("builtins.print") as pr_:
            self.assertEqual(am.main(), 1)
        self.assertEqual(pr_.call_args[0][0], "Automerge: kytkenta epaonnistui: " + "B" * 200)

    def test_yhteenveto_kirjoittaa_tiedostoon_rivinvaihdolla(self):
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "yhteenveto.md")
            with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": polku}), mock.patch("builtins.print") as pr_:
                am.yhteenveto("eka")
                am.yhteenveto("toka")
            with open(polku) as f:
                self.assertEqual(f.read(), "eka\ntoka\n")
            self.assertEqual([c[0][0] for c in pr_.call_args_list], ["eka", "toka"])

    def test_yhteenveto_ei_kaadu_kirjoitusvirheeseen(self):
        with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": "/ei/ole/hakemistoa/y.md"}), mock.patch("builtins.print") as pr_:
            am.yhteenveto("x")
        pr_.assert_called_once_with("x")


if __name__ == "__main__":
    unittest.main()
