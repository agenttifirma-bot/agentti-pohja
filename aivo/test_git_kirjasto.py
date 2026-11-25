"""Git-klooni kirjastona: tyokalualueen `kirjasto/.git` sallitaan, muut alikansiot ja muut alueet eivat (kontin 122 virhe)."""

import io
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from aivo import alue, haku, tiivista, tyokalualue, yksityinen_alue


def _git_init(kansio):
    subprocess.run(["git", "init", "-q", str(kansio)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class GitKirjastoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.juuri = Path(self.tmp.name) / "aivo"
        self.alue = tyokalualue.tyokalualue(self.juuri)
        self.alue.valmista()
        _git_init(self.alue.polku("kirjasto"))

    def aja(self, moduuli, argv):
        ulos, virhe = io.StringIO(), io.StringIO()
        with redirect_stdout(ulos), redirect_stderr(virhe):
            rc = moduuli.main(argv)
        return rc, ulos.getvalue(), virhe.getvalue()

    def test_valmista_hyvaksyy_git_kloonin_kirjaston(self):
        self.assertIn("kirjasto", self.alue.valmista())

    def test_tiivista_kuiva_toimii_git_kirjastolla(self):
        rc, ulos, virhe = self.aja(tiivista, ["--alue", "tyokalu", "--juuri", str(self.juuri), "--kuiva"])
        self.assertEqual((rc, virhe), (0, ""))

    def test_haku_rakenna_ja_hae_toimivat_git_kirjastolla(self):
        for argv in (["rakenna"], ["hae", "testi"]):
            rc, _, virhe = self.aja(haku, argv + ["--alue", "tyokalu", "--juuri", str(self.juuri)])
            self.assertEqual((rc, virhe), (0, ""), argv)

    def test_git_kansion_oikeuksia_ei_muuteta(self):
        g = self.alue.polku("kirjasto") / ".git"
        os.chmod(g, 0o755)
        self.alue.valmista()
        self.assertEqual(stat.S_IMODE(g.stat().st_mode), 0o755)

    def test_git_kansion_sisaltoon_ei_kosketa(self):
        t = self.alue.polku("kirjasto") / ".git" / "HEAD"
        os.chmod(t, 0o644)
        self.alue.valmista()
        self.assertEqual(stat.S_IMODE(t.stat().st_mode), 0o644)

    def test_muu_alikansio_kirjastossa_hylataan_edelleen(self):
        (self.alue.polku("kirjasto") / "muu").mkdir()
        with self.assertRaises(alue.AlueVirhe):
            self.alue.valmista()

    def test_git_linkkina_hylataan(self):
        k = self.alue.polku("kirjasto")
        (Path(self.tmp.name) / "muualle").mkdir()
        os.rename(k / ".git", Path(self.tmp.name) / "vanha-git")
        os.symlink(Path(self.tmp.name) / "muualle", k / ".git")
        with self.assertRaises(alue.AlueVirhe):
            self.alue.valmista()

    def test_git_vieraan_omistajan_hylataan(self):
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            self.assertFalse(alue._git_kansio_ok(os.lstat(self.alue.polku("kirjasto") / ".git")))

    def test_git_kansio_ei_kelpaa_muissa_alikansioissa(self):
        for nimi in ("chat", "tiivistelmat", "indeksi"):
            with self.subTest(nimi=nimi):
                a = tyokalualue.tyokalualue(Path(self.tmp.name) / ("t-" + nimi))
                a.valmista()
                (a.polku(nimi) / ".git").mkdir()
                with self.assertRaises(alue.AlueVirhe):
                    a.valmista()

    def test_git_kansio_ei_kelpaa_yksityisella_alueella(self):
        y = yksityinen_alue.yksityinen_alue(Path(self.tmp.name) / "yks")
        y.valmista()
        for nimi in y.alikansiot:
            with self.subTest(nimi=nimi):
                (y.polku(nimi) / ".git").mkdir()
                with self.assertRaises(alue.AlueVirhe):
                    y.valmista()
                (y.polku(nimi) / ".git").rmdir()

    def test_oletusalue_sallii_gitin_vain_kirjastolle(self):
        self.assertEqual(tyokalualue.tyokalualue().git_alikansiot, ("kirjasto",))
        self.assertEqual(yksityinen_alue.yksityinen_alue().git_alikansiot, ())

    def test_git_alikansion_pitaa_kuulua_alueeseen(self):
        with self.assertRaises(alue.AlueVirhe):
            alue.Alue("x", Path(self.tmp.name) / "x", ("chat",), git_alikansiot=("kirjasto",))

    def test_tavallinen_tarkista_tiedostot_hylkaa_gitin_oletuksena(self):
        k = self.alue.polku("kirjasto")
        with self.assertRaises(alue.AlueVirhe):
            alue.tarkista_tiedostot(k)
        alue.tarkista_tiedostot(k, salli_git=True)


if __name__ == "__main__":
    unittest.main()
