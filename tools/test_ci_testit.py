import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import ci_testit as ct

JUURI = Path(__file__).resolve().parent.parent

KAATUVA = '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        pass
    def test_vaite(self):
        self.assertEqual(1, 2, "SALAINEN-VIESTI-123")
    def test_virhe(self):
        raise KeyError("SALAINEN-AVAIN-456")
    def test_ali(self):
        for i in (1, 2):
            with self.subTest(i=i):
                self.assertNotEqual(i, 2)
'''
OK = '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        pass
'''


def aja(sisalto, nimi="test_koe.py", args=()):
    """Ajaa python -m tools.ci_testit vieraassa hakemistossa kuten CI (cwd = testattava juuri)."""
    with tempfile.TemporaryDirectory() as d:
        if sisalto is not None:
            Path(d, nimi).write_text(sisalto, encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(JUURI))
        p = subprocess.run([sys.executable, "-m", "tools.ci_testit", *args], cwd=d, env=env,
                           capture_output=True, text=True, timeout=120)
        return p


class PaaohjelmaTesti(unittest.TestCase):
    def test_kaatuneet_annotaatioina_ja_paluuarvo_1(self):
        p = aja(KAATUVA)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        rivit = [r for r in p.stdout.splitlines() if r.startswith("::error")]
        self.assertIn("::error file=test_koe.py,line=6,title=test_koe.T.test_vaite::AssertionError", rivit)
        self.assertIn("::error file=test_koe.py,line=8,title=test_koe.T.test_virhe::KeyError", rivit)
        self.assertTrue(any(r == "::error file=test_koe.py,line=12,title=test_koe.T.test_ali (i=2)::AssertionError" for r in rivit), rivit)
        self.assertEqual(len(rivit), 3, rivit)
        # Viestit eivat paady annotaatioihin (traceback nakyy vain unittestin omassa lokissa stderrissa).
        for r in rivit:
            self.assertNotIn("SALAINEN", r)
        self.assertNotIn("SALAINEN", p.stdout)
        # -v-loki sailyy ennallaan.
        self.assertIn("test_ok (test_koe.T", p.stderr)  # 3.10: "(test_koe.T)", 3.11+: "(test_koe.T.test_ok)"
        self.assertIn("FAILED", p.stderr)

    def test_vihrea_ei_annotaatioita_paluuarvo_0(self):
        p = aja(OK)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("::error", p.stdout)
        self.assertIn("Ran 1 test", p.stderr)

    def test_tuontivirhe_nakyy(self):
        p = aja("import ei_ole_olemassa_moduulia\n")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("::error title=unittest.loader._FailedTest.test_koe::ImportError", p.stdout)

    @unittest.skipUnless(sys.version_info >= (3, 12), "unittest palauttaa 5 vasta 3.12:sta")
    def test_ei_testeja_paluuarvo_5(self):
        p = aja(None)
        self.assertEqual(p.returncode, 5, p.stdout + p.stderr)


class YksikkoTesti(unittest.TestCase):
    def test_pako(self):
        self.assertEqual(ct.annotaatio("a.b (x=1, y:2)", "E\n%"), "::error title=a.b (x=1%2C y%3A2)::E%0A%25")

    def test_paikka_annotaatiossa(self):
        self.assertEqual(ct.annotaatio("a.T.t", "KeyError", ("x/test_a.py", 7)),
                         "::error file=x/test_a.py,line=7,title=a.T.t::KeyError")

    def test_sijainti_vain_juuren_alta(self):
        try:
            raise ValueError("x")
        except ValueError:
            tb = sys.exc_info()[2]
        self.assertEqual(ct.sijainti(tb, str(JUURI)), ("tools/test_ci_testit.py", tb.tb_lineno))
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ct.sijainti(tb, d))
        self.assertIsNone(ct.sijainti(None))

    def test_tyypin_nimi(self):
        self.assertEqual(ct.tyypin_nimi(KeyError), "KeyError")
        self.assertEqual(ct.tyypin_nimi(subprocess.CalledProcessError), "subprocess.CalledProcessError")
        self.assertEqual(ct.tyypin_nimi(None), "tuntematon")

    def test_ci_yml_kayttaa_apuohjelmaa(self):
        yml = (JUURI / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertEqual(yml.count("python -m tools.ci_testit"), 2)
        self.assertNotIn("|", "".join(r for r in yml.splitlines() if "ci_testit" in r))


if __name__ == "__main__":
    unittest.main()
