import contextlib
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


def git(repo, *a):
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t"] + list(a),
                   check=True, capture_output=True)


class SandboxGitTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        self.kirjoita("a.py", "x=1\n")
        self.kirjoita("ali/b.py", "y=2\n")
        os.symlink("/etc/passwd", os.path.join(self.repo, "linkki"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "eka")
        git(self.repo, "checkout", "-q", "-b", "yo/haara")
        self.kirjoita("c.py", "z=3\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "toka")
        git(self.repo, "checkout", "-q", "main")
        self.kirjoita(".env", "SALAINEN=1\n")          # seuraamaton: ei saa lahtea
        self.kirjoita("seen.json", "{}")                # seuraamaton tilatiedosto

    def kirjoita(self, polku, sisalto):
        koko = os.path.join(self.repo, polku)
        os.makedirs(os.path.dirname(koko), exist_ok=True)
        with open(koko, "w") as f:
            f.write(sisalto)

    def nimet(self, data):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            return sorted(t.getnames())

    def aja(self, ref):
        lahetetty = {}

        def feikki(komento_osa, syote=None, aikaraja=900):
            lahetetty["komento"] = komento_osa
            lahetetty["syote"] = syote
            return {"ok": True, "vaihe": "valmis", "loki": []}
        with mock.patch.object(sk, "_suorita", feikki):
            tulos = sk.aja_git(self.repo, ref)
        return tulos, lahetetty

    def test_vain_haaran_seurattavat_tiedostot(self):
        tulos, l = self.aja("yo/haara")
        self.assertIs(tulos["ok"], True)
        self.assertEqual(l["komento"], "luonnos")
        self.assertEqual(self.nimet(l["syote"]), ["a.py", "ali/b.py", "c.py"])

    def test_oletus_head_ja_ei_toisen_haaran_tiedostoja(self):
        _, l = self.aja("HEAD")
        self.assertEqual(self.nimet(l["syote"]), ["a.py", "ali/b.py"])

    def test_seuraamattomat_ja_symlinkit_eivat_lahde(self):
        _, l = self.aja("main")
        nimet = self.nimet(l["syote"])
        for kielletty in (".env", "seen.json", "linkki"):
            self.assertNotIn(kielletty, nimet)

    def test_virheellinen_ref(self):
        for ref in ("a b", "x; ls", "$(id)", ""):
            with self.subTest(ref=ref):
                with self.assertRaises(sk.SandboxVirhe):
                    sk.git_tiedostot(self.repo, ref, self.tmp.name)

    def test_tuntematon_ref(self):
        with self.assertRaises(sk.SandboxVirhe):
            sk.git_tiedostot(self.repo, "ei-ole-olemassa", self.tmp.name)

    def test_ei_git_repo(self):
        with self.assertRaises(sk.SandboxVirhe):
            sk.git_tiedostot(self.tmp.name, "HEAD", self.tmp.name)

    def test_cli_git(self):
        def feikki(komento_osa, syote=None, aikaraja=900):
            return {"ok": False, "vaihe": "testit", "kesto_s": 3, "loki": ["1 failed"]}
        with mock.patch.object(sk, "_suorita", feikki):
            with mock.patch("builtins.print") as pr:
                koodi = sk.main(["git", self.repo, "yo/haara"])
        self.assertEqual(koodi, 1)
        self.assertIn("EI LAPI", pr.call_args[0][0])


def tar_data(jasenet):
    puskuri = io.BytesIO()
    with tarfile.open(fileobj=puskuri, mode="w:") as t:
        for nimi, sisalto in jasenet:
            ti = tarfile.TarInfo(nimi)
            ti.size = len(sisalto)
            t.addfile(ti, io.BytesIO(sisalto))
    return puskuri.getvalue()


class SuorituksenParametritTesti(unittest.TestCase):
    def kutsu(self, fn, *a, **kw):
        tallessa = {}

        def feikki(komento, input=None, capture_output=False, timeout=None):
            tallessa.update(capture_output=capture_output, timeout=timeout)
            return subprocess.CompletedProcess(komento, 0, b'{"ok": true}', b"")
        with mock.patch.object(sk.subprocess, "run", feikki):
            fn(*a, **kw)
        return tallessa

    def test_oletusaikaraja_900_ja_tallennus_paalla(self):
        t = self.kutsu(sk.aja_repo, "https://github.com/o/r")
        self.assertEqual((t["timeout"], t["capture_output"]), (900, True))
        self.assertEqual(self.kutsu(sk._suorita, "luonnos")["timeout"], 900)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.kutsu(sk.aja_luonnos, tmp)["timeout"], 900)

    def test_aikaraja_valittyy(self):
        self.assertEqual(self.kutsu(sk.aja_repo, "https://github.com/o/r", aikaraja=7)["timeout"], 7)

    def test_aja_git_oletusaikaraja(self):
        nahty = {}

        def feikki(komento_osa, syote=None, aikaraja=None):
            nahty["aikaraja"] = aikaraja
            return {"ok": True}
        with mock.patch.object(sk, "git_tiedostot", return_value=1), mock.patch.object(sk, "_suorita", feikki):
            sk.aja_git("/x")
            self.assertEqual(nahty["aikaraja"], 900)
            sk.aja_git("/x", aikaraja=5)
            self.assertEqual(nahty["aikaraja"], 5)

    def test_virheviesti_vain_viimeiset_300_merkkia(self):
        def f(komento, input=None, capture_output=True, timeout=None):
            return subprocess.CompletedProcess(komento, 1, b"", b"A" * 100 + b"B" * 300)
        with mock.patch.object(sk.subprocess, "run", f):
            with self.assertRaises(sk.SandboxVirhe) as e:
                sk._suorita("luonnos")
        viesti = str(e.exception)
        self.assertEqual(viesti.count("B"), 300)
        self.assertNotIn("A", viesti)
        self.assertIn("koodi 1", viesti)

    def test_json_ei_dict(self):
        def f(komento, input=None, capture_output=True, timeout=None):
            return subprocess.CompletedProcess(komento, 0, b"[1]", b"")
        with mock.patch.object(sk.subprocess, "run", f):
            with self.assertRaises(sk.SandboxVirhe):
                sk._suorita("luonnos")


class GitTiedostotYksikkoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        self.ulos = os.path.join(self.tmp.name, "ulos")
        os.makedirs(self.ulos)

    def kayta(self, stdout=b"", koodi=0, stderr=b""):
        tallessa = {}

        def feikki(komento, capture_output=False, timeout=None):
            tallessa["timeout"] = timeout
            return subprocess.CompletedProcess(komento, koodi, stdout, stderr)
        with mock.patch.object(sk.subprocess, "run", feikki):
            try:
                return sk.git_tiedostot(self.repo, "HEAD", self.ulos), tallessa
            except sk.SandboxVirhe as e:
                return e, tallessa

    def test_palauttaa_maaran_ja_aikaraja_120(self):
        data = tar_data([("a.py", b"1"), ("ali/b.py", b"2"), ("ali/syva/c.py", b"3")])
        maara, t = self.kayta(data)
        self.assertEqual(maara, 3)
        self.assertEqual(t["timeout"], 120)
        with open(os.path.join(self.ulos, "ali", "syva", "c.py"), "rb") as f:
            self.assertEqual(f.read(), b"3")

    def test_tyhja_arkisto_on_virhe(self):
        e, _ = self.kayta(tar_data([]))
        self.assertIsInstance(e, sk.SandboxVirhe)
        self.assertIn("ei tuottanut tiedostoja", str(e))

    def test_vaaralliset_polut_ohitetaan(self):
        data = tar_data([("/abs.txt", b"x"), ("../ulos.txt", b"x"), ("a/../../ulos2.txt", b"x"),
                         ("..", b"x"), ("hyva.txt", b"ok")])
        maara, _ = self.kayta(data)
        self.assertEqual(maara, 1)
        self.assertEqual(sorted(os.listdir(self.ulos)), ["hyva.txt"])
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["repo", "ulos"])

    def test_git_virhe_viimeiset_200_merkkia(self):
        e, _ = self.kayta(koodi=128, stderr=b"A" * 100 + b"B" * 200)
        self.assertIsInstance(e, sk.SandboxVirhe)
        self.assertEqual(str(e).count("B"), 200)
        self.assertNotIn("A", str(e))

    def test_git_ei_kaynnisty(self):
        with mock.patch.object(sk.subprocess, "run", side_effect=OSError("ei gitia")):
            with self.assertRaises(sk.SandboxVirhe) as e:
                sk.git_tiedostot(self.repo, "HEAD", self.ulos)
        self.assertIn("ei gitia", str(e.exception))


class TiivistaTarkkaTesti(unittest.TestCase):
    def test_viimeiset_15_rivia_oletuksena(self):
        t = sk.tiivista({"ok": True, "loki": ["r%d" % i for i in range(20)]})
        rivit = t.split("\n")
        self.assertEqual(rivit[0], "LAPI (vaihe: ?, ? s)")
        self.assertEqual(rivit[1:], ["r%d" % i for i in range(5, 20)])

    def test_rivimaara_parametri(self):
        t = sk.tiivista({"ok": True, "loki": ["a", "b", "c"]}, rivit=2)
        self.assertTrue(t.endswith("b\nc"))
        self.assertNotIn("a\n", t)


class MainKomennotTesti(unittest.TestCase):
    OK = {"ok": True, "vaihe": "valmis", "kesto_s": 1, "loki": []}

    def aja(self, argv, tulos=None):
        ulos = io.StringIO()
        with mock.patch.object(sk, "aja_luonnos", return_value=tulos or self.OK) as lu, \
                mock.patch.object(sk, "aja_repo", return_value=tulos or self.OK) as re_, \
                mock.patch.object(sk, "aja_git", return_value=tulos or self.OK) as gi, \
                contextlib.redirect_stdout(ulos):
            rc = sk.main(argv)
        return rc, ulos.getvalue(), lu, re_, gi

    def test_luonnos(self):
        rc, ulos, lu, re_, gi = self.aja(["luonnos", "/h"])
        self.assertEqual(rc, 0)
        lu.assert_called_once_with("/h")
        self.assertFalse(re_.called or gi.called)
        self.assertIn("LAPI", ulos)

    def test_repo_ilman_refia_ja_refilla(self):
        _, _, _, re_, _ = self.aja(["repo", "https://github.com/o/r"])
        re_.assert_called_once_with("https://github.com/o/r", "")
        _, _, _, re_, _ = self.aja(["repo", "https://github.com/o/r", "v1"])
        re_.assert_called_once_with("https://github.com/o/r", "v1")

    def test_git_oletus_head_ja_ref(self):
        rc, _, lu, re_, gi = self.aja(["git", "/r"])
        gi.assert_called_once_with("/r", "HEAD")
        self.assertFalse(lu.called or re_.called)
        _, _, _, _, gi = self.aja(["git", "/r", "haara"])
        gi.assert_called_once_with("/r", "haara")

    def test_paluukoodi_epaonnistuessa(self):
        rc, ulos, *_ = self.aja(["git", "/r"], {"ok": False, "vaihe": "testit", "loki": []})
        self.assertEqual(rc, 1)
        self.assertIn("EI LAPI", ulos)

    def test_kayttovirheet(self):
        for argv in ([], ["luonnos"], ["luonnos", "a", "b"], ["repo"], ["repo", "a", "b", "c"],
                     ["git"], ["git", "a", "b", "c"], ["tuntematon", "a"], ["repo", "a", "b", "c", "d"]):
            with self.subTest(argv=argv):
                rc, ulos, lu, re_, gi = self.aja(argv)
                self.assertEqual(rc, 2)
                self.assertIn("kaytto:", ulos)
                self.assertFalse(lu.called or re_.called or gi.called)

    def test_ilman_argumenttia_luetaan_sys_argv(self):
        with mock.patch.object(sk.sys, "argv", ["x", "luonnos", "/s"]):
            rc, _, lu, _, _ = self.aja(None)
        self.assertEqual(rc, 0)
        lu.assert_called_once_with("/s")


if __name__ == "__main__":
    unittest.main()
