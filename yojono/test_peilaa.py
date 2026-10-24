"""peilaa.sh: paikallinen bare-repo kohteena (ei verkkoa, ei avainta)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKRIPTI = Path(__file__).resolve().parent / "peilaa.sh"
JUURI = Path(__file__).resolve().parent.parent


def git(*args, cwd=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", *args], cwd=cwd, check=True, capture_output=True, text=True)


class PeilaaTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.bare = self.t / "kohde.git"
        git("init", "-q", "--bare", "-b", "main", str(self.bare))
        siemen = self.t / "siemen"
        siemen.mkdir()
        git("init", "-q", "-b", "main", cwd=siemen)
        (siemen / "README.md").write_text("x\n")
        git("add", "-A", cwd=siemen)
        git("commit", "-q", "-m", "alku", cwd=siemen)
        git("push", "-q", str(self.bare), "main", cwd=siemen)
        self.perus = self.t / "perus"
        (self.perus / "raportit").mkdir(parents=True)
        (self.perus / "raportit" / "a.md").write_text("# A\nsk-" + "x" * 30 + "\n")
        (self.perus / "tila.json").write_text("{}")

    def aja(self, **extra):
        env = dict(os.environ, PEILAA_URL=str(self.bare), PEILAA_AVAIN=str(self.t / "ei-avainta"), PEILAA_PERUS=str(self.perus),
                   PEILAA_PYTHON=sys.executable, YOJONO_AJURI=str(JUURI), PEILAA_TYO=str(self.t / "tyo"))
        env.update(extra)
        return subprocess.run(["sh", str(SKRIPTI)], capture_output=True, text=True, env=env, timeout=60)

    def kohteen_tiedosto(self, polku):
        return subprocess.run(["git", "--git-dir", str(self.bare), "show", "main:" + polku], capture_output=True, text=True)

    def test_pushaa_siivotut_raportit(self):
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stderr)
        t = self.kohteen_tiedosto("raportit-palvelin/raportit/a.md")
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertIn("[poistettu]", t.stdout)
        self.assertNotIn("sk-xxx", t.stdout)
        self.assertEqual(self.kohteen_tiedosto("README.md").stdout, "x\n")  # muu sisalto sailyy

    def test_toinen_ajo_onnistuu(self):
        self.assertEqual(self.aja().returncode, 0)
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_virheellinen_kansio_estetaan(self):
        for kansio in ("/abs", "../x", "a b"):
            r = self.aja(PEILAA_KANSIO=kansio)
            self.assertEqual(r.returncode, 2, kansio)

    def test_virheellinen_url_antaa_virheen(self):
        r = self.aja(PEILAA_URL=str(self.t / "ei-ole.git"))
        self.assertNotEqual(r.returncode, 0)

    def test_skripti_on_ascii(self):
        SKRIPTI.read_bytes().decode("ascii")


if __name__ == "__main__":
    unittest.main()
