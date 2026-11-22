import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import changelog_kokoa as ck
from tools import changelog_tarkista as ct

JUURI = Path(__file__).resolve().parent.parent
ALKU = "# Changelog\n\n## Unreleased\n- vanha\n\n## Muu\n- x\n"


def git(k, *args, tarkista=True):
    p = subprocess.run(["git", "-C", str(k), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       capture_output=True, text=True)
    if tarkista and p.returncode != 0:
        raise AssertionError(p.stdout + p.stderr)
    return p


def kirjoita(k, polku, teksti):
    p = Path(k) / polku
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(teksti, encoding="utf-8")


def tee_repo(k):
    git(k, "init", "-q", "-b", "main")
    kirjoita(k, "CHANGELOG.md", ALKU)
    kirjoita(k, "docs/muutokset/README.md", "ohje\n")
    kirjoita(k, "docs/muutokset/vanha.md", "- vanha fragmentti\n")
    git(k, "add", "-A")
    git(k, "commit", "-qm", "alku")


def ajo(k, *argv):
    ulos, virhe = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
        rc = ct.main(list(argv) + [str(k)])
    return rc, ulos.getvalue() + virhe.getvalue()


class ArvioiTesti(unittest.TestCase):
    def test_ilman_changelogia_kunnossa(self):
        self.assertIsNone(ct.arvioi(["a.py", "docs/muutokset/uusi.md"], []))

    def test_suora_muutos_hylataan(self):
        self.assertIn("CHANGELOG.md", ct.arvioi(["CHANGELOG.md", "a.py"], []))

    def test_changelogin_poisto_hylataan(self):
        self.assertIsNotNone(ct.arvioi([], ["CHANGELOG.md"]))

    def test_kokoaja_pr_sallitaan(self):
        self.assertIsNone(ct.arvioi(["CHANGELOG.md"], ["docs/muutokset/a.md", "docs/muutokset/b.md"]))

    def test_readmen_poisto_ei_ole_kokoaja(self):
        self.assertIsNotNone(ct.arvioi(["CHANGELOG.md"], ["docs/muutokset/README.md"]))

    def test_muu_tiedoston_poisto_ei_ole_kokoaja(self):
        self.assertIsNotNone(ct.arvioi(["CHANGELOG.md"], ["docs/muu.md", "docs/muutokset/alikansio/a.md"]))

    def test_vain_fragmentin_poisto_ilman_changelogia_kunnossa(self):
        self.assertIsNone(ct.arvioi([], ["docs/muutokset/a.md"]))


class GitTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.k = Path(self.tmp.name)
        tee_repo(self.k)

    def tearDown(self):
        self.tmp.cleanup()

    def haara(self, nimi):
        git(self.k, "checkout", "-q", "main")
        git(self.k, "checkout", "-q", "-b", nimi)

    def test_fragmentti_riittaa(self):
        self.haara("yo/a")
        kirjoita(self.k, "docs/muutokset/yo-a.md", "- a: uusi\n")
        kirjoita(self.k, "koodi.py", "x = 1\n")
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "a")
        rc, ulos = ajo(self.k, "--pohja", "main")
        self.assertEqual(rc, 0, ulos)

    def test_suora_changelog_muutos_hylataan(self):
        self.haara("yo/b")
        kirjoita(self.k, "CHANGELOG.md", ALKU.replace("- vanha\n", "- uusi\n- vanha\n"))
        git(self.k, "commit", "-qam", "b")
        rc, ulos = ajo(self.k, "--pohja", "main")
        self.assertEqual(rc, 1)
        self.assertIn("docs/muutokset/", ulos)

    def test_kokoaja_pr_sallitaan_ja_tuottaa_oikean_jarjestyksen(self):
        git(self.k, "checkout", "-q", "main")
        for nimi, rivi in (("b-toinen", "- b\n"), ("a-ensimmainen", "- a\n")):
            kirjoita(self.k, "docs/muutokset/%s.md" % nimi, rivi)
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "fragmentit")
        git(self.k, "checkout", "-q", "-b", "yo/koonti")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ck.main([], juuri=self.k), 0)
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "koonti")
        # nimijarjestys: a-ensimmainen, b-toinen, vanha (vanhat rivit ensin, sitten fragmentit)
        teksti = (self.k / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("- vanha\n- a\n- b\n- vanha fragmentti\n", teksti)
        self.assertFalse((self.k / "docs/muutokset/a-ensimmainen.md").exists())
        self.assertTrue((self.k / "docs/muutokset/README.md").exists())
        # vertailu mainiin: koonti on tassa haarassa oma commit, joten pohjaksi se commit jonka paalla koonti tehtiin
        rc, ulos = ajo(self.k, "--pohja", "main")
        self.assertEqual(rc, 0, ulos)

    def test_rinnakkaiset_fragmentti_pr_t_yhdistyvat_ilman_konfliktia(self):
        # Ei .gitattributes-ajuria: tama on GitHubin kayttaytyminen.
        for nimi in ("yo/x", "yo/y"):
            self.haara(nimi)
            kirjoita(self.k, "docs/muutokset/%s.md" % nimi.split("/")[1], "- %s: rivi\n" % nimi)
            git(self.k, "add", "-A")
            git(self.k, "commit", "-qm", nimi)
        git(self.k, "checkout", "-q", "main")
        git(self.k, "merge", "--no-edit", "yo/x")
        p = git(self.k, "merge", "--no-edit", "yo/y", tarkista=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_rinnakkaiset_suorat_changelog_muutokset_konfliktoivat_ilman_ajuria(self):
        # Perustelee tarkistimen: ilman union-ajuria (GitHub) suorat muutokset konfliktoivat.
        for nimi in ("yo/x", "yo/y"):
            self.haara(nimi)
            kirjoita(self.k, "CHANGELOG.md", ALKU.replace("- vanha\n", "- %s\n- vanha\n" % nimi))
            git(self.k, "commit", "-qam", nimi)
        git(self.k, "checkout", "-q", "main")
        git(self.k, "merge", "--no-edit", "yo/x")
        self.assertNotEqual(git(self.k, "merge", "--no-edit", "yo/y", tarkista=False).returncode, 0)

    def test_pohjaa_ei_loydy_ei_oleteta_kunnossa(self):
        rc, ulos = ajo(self.k, "--pohja", "ei-ole-olemassa")
        self.assertEqual(rc, 2)

    def aja_raaka(self, argv):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = ct.main(argv)
        return rc, ulos.getvalue() + virhe.getvalue()

    def test_kayttovirhe(self):
        for argv in (["--pohja"], ["a", "b"]):
            rc, ulos = self.aja_raaka(argv)
            self.assertEqual(rc, 2)
            self.assertIn("kaytto:", ulos)

    def test_pohja_ja_hakemisto_annetaan_yhdessa(self):
        rc, ulos = self.aja_raaka(["--pohja", "main", str(self.k)])
        self.assertEqual((rc, "OK" in ulos), (0, True), ulos)

    def test_ilman_argumentteja_luetaan_sys_argv(self):
        from unittest import mock
        with mock.patch.object(ct.sys, "argv", ["changelog_tarkista.py", "--pohja", "main", str(self.k)]):
            ulos = io.StringIO()
            with contextlib.redirect_stdout(ulos):
                self.assertEqual(ct.main(), 0)

    def test_hakemisto_oletuksena_nykyinen(self):
        vanha = os.getcwd()
        self.addCleanup(os.chdir, vanha)
        os.chdir(self.k)
        rc, ulos = self.aja_raaka(["--pohja", "main"])
        self.assertEqual(rc, 0, ulos)

    def test_oletuspohja_palaa_mainiin_kun_origin_main_puuttuu(self):
        self.haara("yo/c")
        kirjoita(self.k, "docs/muutokset/yo-c.md", "- c: rivi\n")
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "c")
        rc, ulos = self.aja_raaka([str(self.k)])
        self.assertEqual((rc, "OK" in ulos), (0, True), ulos)

    def test_oletuspohja_hylkaa_suoran_muutoksen_myos_ilman_origin_mainia(self):
        self.haara("yo/d")
        kirjoita(self.k, "CHANGELOG.md", ALKU + "- d\n")
        git(self.k, "commit", "-qam", "d")
        self.assertEqual(self.aja_raaka([str(self.k)])[0], 1)

    def test_nimimuutos_ei_piilota_changelogia(self):
        # --no-renames: CHANGELOG.md:n siirto toiseen nimeen nakyy poistona.
        self.haara("yo/e")
        git(self.k, "mv", "CHANGELOG.md", "MUUTOKSET.md")
        git(self.k, "commit", "-qm", "e")
        self.assertEqual(self.aja_raaka(["--pohja", "main", str(self.k)])[0], 1)


class PushSkriptiTesti(unittest.TestCase):
    """tarkista-ja-pushaa.sh ei pushaa suoraa CHANGELOG-muutosta, mutta pushaa fragmentin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.bare = t / "bare.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        self.k = t / "tyo"
        self.k.mkdir()
        tee_repo(self.k)
        (self.k / "tools").mkdir()
        for nimi in ("changelog_tarkista.py", "tarkista-ja-pushaa.sh"):
            shutil.copy(JUURI / "tools" / nimi, self.k / "tools" / nimi)
        kirjoita(self.k, ".tarkistus", "true\n")
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "tyokalut")
        git(self.k, "remote", "add", "origin", str(self.bare))
        git(self.k, "push", "-q", "origin", "main")
        git(self.k, "fetch", "-q", "origin")
        git(self.k, "checkout", "-q", "-b", "yo/p")

    def tearDown(self):
        self.tmp.cleanup()

    def push(self):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_COMMITTER_NAME="t")
        return subprocess.run(["bash", "tools/tarkista-ja-pushaa.sh", "origin", "yo/p"], cwd=self.k,
                              capture_output=True, text=True, env=env)

    def haarat(self):
        return subprocess.run(["git", "-C", str(self.bare), "branch", "--list", "yo/p"],
                              capture_output=True, text=True).stdout.strip()

    def test_suora_changelog_estaa_pushin(self):
        kirjoita(self.k, "CHANGELOG.md", ALKU.replace("- vanha\n", "- uusi\n- vanha\n"))
        git(self.k, "commit", "-qam", "suora")
        p = self.push()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.haarat(), "")

    def test_fragmentti_pushataan(self):
        kirjoita(self.k, "docs/muutokset/yo-p.md", "- p: rivi\n")
        git(self.k, "add", "-A")
        git(self.k, "commit", "-qm", "fragmentti")
        p = self.push()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("yo/p", self.haarat())


class KehoteTesti(unittest.TestCase):
    def test_kehote_ohjaa_fragmenttiin(self):
        teksti = (JUURI / "claudejono" / "kehote.md").read_text(encoding="utf-8")
        self.assertIn("docs/muutokset/", teksti)
        self.assertIn("ala muokkaa CHANGELOG.md", teksti)


if __name__ == "__main__":
    unittest.main()
