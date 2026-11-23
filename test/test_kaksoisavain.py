"""Hylkaa sanakirjaliteraalit, joissa sama vakioavain esiintyy kahdesti (Python pitaa hiljaa jalkimmaisen)."""
import ast
import os
import subprocess
import tempfile
import unittest

JUURI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ohita = {".git", "venv", ".venv", "__pycache__", "node_modules"}


def kaksoisavaimet(lahde):
    """Palauttaa listan (rivi, avain) kaksoisavaimista; nostaa SyntaxErrorin, jos lahde ei jasenny."""
    tulos = []
    for solmu in ast.walk(ast.parse(lahde)):
        if not isinstance(solmu, ast.Dict):
            continue
        nahty = set()
        for avain in solmu.keys:
            if not isinstance(avain, ast.Constant):
                continue  # None = **laajennus, muut lausekkeet ohitetaan
            # tyyppi mukaan: 1 ja True ovat sama avain, joten verrataan arvoa (kuten Python)
            if avain.value in nahty:
                tulos.append((avain.lineno, avain.value))
            nahty.add(avain.value)
    return sorted(tulos)


def seuratut_py(juuri=JUURI):
    try:
        ulos = subprocess.run(["git", "ls-files", "*.py"], cwd=juuri, check=True,
                              capture_output=True, text=True).stdout.split("\n")
        tiedostot = [p for p in ulos if p]
    except (OSError, subprocess.CalledProcessError):
        tiedostot = []
        for hak, kansiot, nimet in os.walk(juuri):
            kansiot[:] = [k for k in kansiot if k not in ohita]
            tiedostot += [os.path.relpath(os.path.join(hak, n), juuri) for n in nimet if n.endswith(".py")]
    return sorted(p for p in tiedostot if not ohita & set(p.split("/")))


class KaksoisavainTesti(unittest.TestCase):
    def test_repossa_ei_kaksoisavaimia(self):
        tiedostot = seuratut_py()
        self.assertTrue(tiedostot, "yhtaan .py-tiedostoa ei loytynyt")
        virheet = []
        for polku in tiedostot:
            with open(os.path.join(JUURI, polku), encoding="utf-8") as f:
                lahde = f.read()
            try:
                loydot = kaksoisavaimet(lahde)
            except SyntaxError:
                virheet.append("%s: ei jasenny (SyntaxError)" % polku)
                continue
            virheet += ["%s:%d: kaksoisavain %r" % (polku, rivi, avain) for rivi, avain in loydot]
        self.assertEqual(virheet, [], "sanakirjan kaksoisavaimia:\n" + "\n".join(virheet))

    def test_tilapaistiedoston_kaksoisavain_tunnistetaan(self):
        with tempfile.TemporaryDirectory() as hak:
            polku = os.path.join(hak, "esim.py")
            with open(polku, "w", encoding="utf-8") as f:
                f.write('T = {\n    "aivo/yksityinen.py": ["a"],\n    "x": 1,\n    "aivo/yksityinen.py": ["b"],\n}\n')
            with open(polku, encoding="utf-8") as f:
                self.assertEqual(kaksoisavaimet(f.read()), [(4, "aivo/yksityinen.py")])

    def test_samat_avaimet_eri_sanakirjoissa_eivat_ole_virhe(self):
        lahde = 'a = {"x": 1, "y": 2}\nb = {"x": 3}\nc = {"k": {"x": 1}, "x": 2}\n'
        self.assertEqual(kaksoisavaimet(lahde), [])

    def test_ei_vakioavaimet_ohitetaan(self):
        lahde = "a = {n: 1, n: 2, **p, **p}\n"
        self.assertEqual(kaksoisavaimet(lahde), [])


if __name__ == "__main__":
    unittest.main()
