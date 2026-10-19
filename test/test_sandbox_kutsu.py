import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from agentti import sandbox_kutsu as sk


def vastaus(tulos, koodi=0, virhe=""):
    def feikki(komento, input=None, capture_output=True, timeout=None):
        feikki.kutsut.append((komento, input))
        return subprocess.CompletedProcess(komento, koodi, json.dumps(tulos).encode(), virhe.encode())
    feikki.kutsut = []
    return feikki


class SandboxKutsuTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hak = self.tmp.name

    def kirjoita(self, polku, sisalto):
        koko = os.path.join(self.hak, polku)
        os.makedirs(os.path.dirname(koko), exist_ok=True)
        with open(koko, "w") as f:
            f.write(sisalto)

    def test_repo_lahettaa_oikean_komennon(self):
        f = vastaus({"ok": True, "vaihe": "valmis", "loki": ["1 passed"]})
        with mock.patch.object(sk.subprocess, "run", f):
            t = sk.aja_repo("https://github.com/o/r", ref="v1.0")
        self.assertIs(t["ok"], True)
        komento, syote = f.kutsut[0]
        self.assertEqual(komento[-1], "repo https://github.com/o/r v1.0")
        self.assertIsNone(syote)
        self.assertIn("BatchMode=yes", komento)

    def test_repo_hylkaa_muut_osoitteet(self):
        for url in ["http://github.com/o/r", "https://evil.com/o/r",
                    "https://github.com/o/r; rm -rf /", "https://github.com/o"]:
            with self.subTest(url=url):
                with self.assertRaises(sk.SandboxVirhe):
                    sk.aja_repo(url)

    def test_repo_hylkaa_huonon_refin(self):
        with self.assertRaises(sk.SandboxVirhe):
            sk.aja_repo("https://github.com/o/r", ref="a b; ls")

    def test_luonnos_tar_sisaltaa_vain_tiedostot(self):
        self.kirjoita("a.py", "x=1")
        self.kirjoita("node_modules/p.js", "zzz")
        self.kirjoita("alikansio/b.py", "y=2")
        os.symlink("/etc/passwd", os.path.join(self.hak, "linkki"))
        data = sk.luonnos_tar(self.hak)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            nimet = sorted(t.getnames())
        self.assertEqual(nimet, ["a.py", "alikansio/b.py"])

    def test_luonnos_liian_suuri(self):
        self.kirjoita("a.txt", "x" * 1000)
        with mock.patch.object(sk, "LUONNOS_RAJA", 10):
            with self.assertRaises(sk.SandboxVirhe):
                sk.luonnos_tar(self.hak)

    def test_luonnos_puuttuva_hakemisto(self):
        with self.assertRaises(sk.SandboxVirhe):
            sk.luonnos_tar("/ei/ole/olemassa")

    def test_luonnos_lahettaa_tarin_stdiniin(self):
        self.kirjoita("a.py", "x=1")
        f = vastaus({"ok": True, "vaihe": "valmis", "loki": []})
        with mock.patch.object(sk.subprocess, "run", f):
            sk.aja_luonnos(self.hak)
        komento, syote = f.kutsut[0]
        self.assertEqual(komento[-1], "luonnos")
        self.assertEqual(syote[:2], b"\x1f\x8b")

    def test_ei_json_vastausta(self):
        def f(komento, input=None, capture_output=True, timeout=None):
            return subprocess.CompletedProcess(komento, 255, b"", b"Permission denied")
        with mock.patch.object(sk.subprocess, "run", f):
            with self.assertRaises(sk.SandboxVirhe) as e:
                sk.aja_repo("https://github.com/o/r")
        self.assertIn("Permission denied", str(e.exception))

    def test_aikakatko(self):
        def f(komento, input=None, capture_output=True, timeout=None):
            raise subprocess.TimeoutExpired(komento, timeout)
        with mock.patch.object(sk.subprocess, "run", f):
            with self.assertRaises(sk.SandboxVirhe):
                sk.aja_repo("https://github.com/o/r", aikaraja=1)

    def test_known_hosts_ymparistomuuttuja(self):
        with mock.patch.dict(os.environ, {"SANDBOX_KNOWN_HOSTS": "/etc/agentti/sandbox_kh"}):
            k = sk._ssh_perus()
        self.assertIn("UserKnownHostsFile=/etc/agentti/sandbox_kh", k)
        self.assertIn("StrictHostKeyChecking=yes", k)

    def test_tiivista(self):
        t = sk.tiivista({"ok": False, "vaihe": "testit", "kesto_s": 12, "virhe": "x", "loki": ["a", "b"]})
        self.assertTrue(t.startswith("EI LAPI"))
        self.assertIn("virhe: x", t)
        self.assertTrue(t.endswith("a\nb"))


if __name__ == "__main__":
    unittest.main()
