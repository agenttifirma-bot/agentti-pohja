import contextlib
import io
import os
import unittest
from unittest import mock

from tools import gitea_peilit as gp

REPOT = [
    {"name": "a", "clone_url": "https://github.com/u/a.git", "size": 2048, "private": False, "fork": False},
    {"name": "b", "clone_url": "https://github.com/u/b.git", "size": 1024, "private": False, "fork": True},
    {"name": "salainen", "clone_url": "https://github.com/u/s.git", "size": 5, "private": True, "fork": False},
]
TOKEN = "TESTITOKEN-EI-OIKEA"


def feikki(kutsut, olemassa=()):
    def pyynto(url, token=None, data=None, metodi=None):
        kutsut.append((url, token, data, metodi))
        if url.startswith(gp.GITHUB_API):
            return 200, REPOT
        if url.endswith("/api/v1/user"):
            return 200, {"login": "tony"}
        if metodi == "POST":
            return 201, {}
        return (200, {}) if url.rsplit("/", 1)[1] in olemassa else (404, None)
    return pyynto


class PeilitTesti(unittest.TestCase):
    def aja(self, argv, kutsut, olemassa=()):
        ulos, virhe = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"GITEA_TOKEN": TOKEN}), \
                contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            koodi = gp.main(argv, pyynto=feikki(kutsut, olemassa))
        return koodi, ulos.getvalue() + virhe.getvalue()

    def test_kuiva_ajo_ei_kirjoita_giteaan_eika_tulosta_tokenia(self):
        kutsut = []
        koodi, ulos = self.aja(["--gitea", "https://g"], kutsut)
        self.assertEqual(koodi, 0)
        self.assertTrue(all(k[0].startswith(gp.GITHUB_API) for k in kutsut))
        self.assertIn("KUIVA a", ulos)
        self.assertNotIn(TOKEN, ulos)

    def test_forkit_ja_yksityiset_pois_oletuksena(self):
        nimet = [r["name"] for r in gp.github_repot("u", feikki([]))]
        self.assertEqual(nimet, ["a"])
        nimet = [r["name"] for r in gp.github_repot("u", feikki([]), forkit=True)]
        self.assertEqual(nimet, ["a", "b"])

    def test_aja_luo_peilin_tunnin_valilla(self):
        kutsut = []
        koodi, ulos = self.aja(["--gitea", "https://g/", "--aja"], kutsut)
        self.assertEqual(koodi, 0)
        posts = [k for k in kutsut if k[3] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][0], "https://g/api/v1/repos/migrate")
        self.assertTrue(posts[0][2]["mirror"])
        self.assertEqual(posts[0][2]["mirror_interval"], "1h0m0s")
        self.assertNotIn(TOKEN, ulos)

    def test_olemassa_oleva_ohitetaan(self):
        kutsut = []
        koodi, ulos = self.aja(["--gitea", "https://g", "--aja"], kutsut, olemassa=("a",))
        self.assertEqual(koodi, 0)
        self.assertIn("OHITETTU a", ulos)
        self.assertFalse([k for k in kutsut if k[3] == "POST"])

    def test_aja_ilman_tokenia_epaonnistuu(self):
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gp.main(["--gitea", "https://g", "--aja"], pyynto=feikki([])), 2)

    def test_koko_megatavuina(self):
        self.assertEqual(gp.koko_mt(REPOT[:2]), 3.0)


if __name__ == "__main__":
    unittest.main()
