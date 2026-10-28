import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools import changelog_kokoa as ck

PERUS = "# Changelog\n\n## Unreleased\n- vanha 1\n- vanha 2\n\n## [Julkaisematon]\n- x\n"


class LisaaTesti(unittest.TestCase):
    def test_lisaa_listan_loppuun_ennen_seuraavaa_otsikkoa(self):
        s = ck.lisaa_changelogiin(PERUS, ["- uusi a", "- uusi b"])
        self.assertEqual(s, "# Changelog\n\n## Unreleased\n- vanha 1\n- vanha 2\n- uusi a\n- uusi b\n\n## [Julkaisematon]\n- x\n")

    def test_ilman_seuraavaa_otsikkoa_lisataan_tiedoston_loppuun(self):
        s = ck.lisaa_changelogiin("## Unreleased\n- a\n", ["- b"])
        self.assertEqual(s, "## Unreleased\n- a\n- b\n")

    def test_tyhja_unreleased(self):
        s = ck.lisaa_changelogiin("## Unreleased\n\n## Muu\n", ["- b"])
        self.assertEqual(s, "## Unreleased\n- b\n\n## Muu\n")

    def test_seuraava_otsikko_heti_unreleasedin_jalkeen(self):
        s = ck.lisaa_changelogiin("## Unreleased\n## Muu\n- x\n", ["- b"])
        self.assertEqual(s, "## Unreleased\n- b\n## Muu\n- x\n")

    def test_puuttuva_otsikko_nostaa_virheen(self):
        with self.assertRaises(ValueError):
            ck.lisaa_changelogiin("# Changelog\n", ["- b"])


class MainTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.juuri = Path(self._tmp.name)
        (self.juuri / "docs" / "muutokset").mkdir(parents=True)
        (self.juuri / "CHANGELOG.md").write_text(PERUS, encoding="utf-8")

    def frag(self, nimi, sisalto):
        (self.juuri / "docs" / "muutokset" / nimi).write_text(sisalto, encoding="utf-8")

    def aja(self, argv):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = ck.main(argv, juuri=self.juuri)
        return rc, ulos.getvalue(), virhe.getvalue()

    def changelog(self):
        return (self.juuri / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_ei_fragmentteja(self):
        self.frag("README.md", "- ei lasketa\n")
        rc, ulos, _ = self.aja([])
        self.assertEqual((rc, ulos), (0, "Ei fragmentteja.\n"))
        self.assertEqual(self.changelog(), PERUS)

    def test_kokoaa_nimijarjestyksessa_ja_poistaa_fragmentit(self):
        self.frag("b.md", "Otsikko ohitetaan\n- b yksi\n- b kaksi\n")
        self.frag("a.md", "- a yksi\n")
        self.frag("README.md", "- ohitetaan\n")
        rc, ulos, _ = self.aja([])
        self.assertEqual(rc, 0)
        self.assertIn("Lisatty 3 rivia", ulos)
        self.assertIn("- vanha 2\n- a yksi\n- b yksi\n- b kaksi\n", self.changelog())
        self.assertEqual(sorted(p.name for p in (self.juuri / "docs" / "muutokset").iterdir()), ["README.md"])

    def test_kuiva_ei_muuta_mitaan(self):
        self.frag("a.md", "- a yksi\n")
        rc, ulos, _ = self.aja(["--kuiva"])
        self.assertEqual(rc, 0)
        self.assertIn("kuiva-ajo", ulos)
        self.assertEqual(self.changelog(), PERUS)
        self.assertTrue((self.juuri / "docs" / "muutokset" / "a.md").exists())

    def test_puuttuva_otsikko_ei_poista_fragmentteja(self):
        (self.juuri / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        self.frag("a.md", "- a\n")
        rc, _, virhe = self.aja([])
        self.assertEqual(rc, 1)
        self.assertIn("Unreleased", virhe)
        self.assertTrue((self.juuri / "docs" / "muutokset" / "a.md").exists())

    def test_argumentit_luetaan_sys_argvsta_oletuksena(self):
        from unittest import mock
        ulos, virhe = io.StringIO(), io.StringIO()
        with mock.patch.object(ck.sys, "argv", ["changelog_kokoa.py", "--muu"]), contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = ck.main(juuri=self.juuri)
        self.assertEqual(rc, 2)

    def test_tuntematon_argumentti(self):
        rc, ulos, virhe = self.aja(["--muu"])
        self.assertEqual((rc, ulos), (2, ""))
        self.assertIn("kaytto:", virhe)


if __name__ == "__main__":
    unittest.main()
