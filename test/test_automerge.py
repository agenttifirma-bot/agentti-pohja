import json
import subprocess
import unittest
from unittest import mock

from tools import automerge as am

PR = {"draft": False, "head_repo": "o/r", "base_repo": "o/r", "labels": []}


def tied(nimi, status="modified", changes=5, **lisa):
    d = {"filename": nimi, "status": status, "changes": changes}
    d.update(lisa)
    return d


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


if __name__ == "__main__":
    unittest.main()
