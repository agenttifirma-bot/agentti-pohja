"""Testit tools/ci_testit.py:lle: ajetaan aliprosessina valekansiota vasten (ei rekursiota repon omaan sarjaan)."""
import os
import subprocess
import sys
import tempfile
import unittest

SKRIPTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ci_testit.py")


def _aja(tiedostot):
    with tempfile.TemporaryDirectory() as hak:
        for nimi, sisalto in tiedostot.items():
            with open(os.path.join(hak, nimi), "w", encoding="utf-8") as f:
                f.write(sisalto)
        p = subprocess.run([sys.executable, "-I", SKRIPTI, "-s", hak, "-t", hak],
                           capture_output=True, text=True, cwd=hak)
    return p


def _virheet(p):
    return [r for r in p.stdout.splitlines() if r.startswith("::error")]


KAATUVA = ("import unittest\n"
           "class Luokka(unittest.TestCase):\n"
           "    def test_y(self):\n"
           "        raise ValueError('SALAINEN-viesti')\n"
           "    def test_ok(self):\n"
           "        pass\n"
           "    def test_vaite(self):\n"
           "        self.assertEqual(1, 2, 'SALAINEN-vaite')\n")


class CiTestitTesti(unittest.TestCase):
    def test_kaatuva_testi_antaa_annotaation_ja_paluuarvon_1(self):
        p = _aja({"test_x.py": KAATUVA})
        self.assertEqual(p.returncode, 1)
        self.assertEqual(_virheet(p), [
            "::error title=Kaatunut testi::test_x.Luokka.test_vaite (AssertionError)",
            "::error title=Kaatunut testi::test_x.Luokka.test_y (ValueError)",
        ])

    def test_onnistuva_sarja_antaa_0_ilman_error_rivia(self):
        p = _aja({"test_x.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(_virheet(p), [])

    def test_viesti_ei_paady_annotaatioon(self):
        p = _aja({"test_x.py": KAATUVA})
        self.assertNotIn("SALAINEN", "\n".join(_virheet(p)))

    def test_verbose_tuloste_sailyy(self):
        p = _aja({"test_x.py": KAATUVA})
        self.assertIn("test_ok (test_x.Luokka", p.stderr)
        self.assertIn("... ok", p.stderr)

    def test_yli_30_kaatunutta_rajautuu(self):
        lahde = "import unittest\nclass T(unittest.TestCase):\n" + "".join(
            "    def test_%02d(self):\n        self.fail('x')\n" % i for i in range(35))
        p = _aja({"test_x.py": lahde})
        rivit = _virheet(p)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(rivit), 31)
        self.assertIn("ja 5 muuta", rivit[-1])

    def test_tuontivirhe_on_virhe(self):
        p = _aja({"test_x.py": "import olematon_moduuli_xyz\n"})
        self.assertEqual(p.returncode, 1)
        rivit = _virheet(p)
        self.assertEqual(len(rivit), 1)
        self.assertIn("(ImportError)", rivit[0])

    def test_testin_tunnuksen_erikoismerkit_eivat_riko_annotaatiota(self):
        lahde = ("import unittest\nclass T(unittest.TestCase):\n"
                 "    def test_a(self):\n"
                 "        with self.subTest(x='a::b\\n::error x=%0A'):\n"
                 "            self.fail('x')\n")
        p = _aja({"test_x.py": lahde})
        rivit = _virheet(p)
        self.assertEqual(len(rivit), 1)
        self.assertNotIn("\n", rivit[0])
        self.assertEqual(rivit[0].count("::"), 2)


if __name__ == "__main__":
    unittest.main()
