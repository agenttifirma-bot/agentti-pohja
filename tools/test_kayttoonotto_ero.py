import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

from tools import kayttoonotto_ero as k

SHA = "a" * 40


class Vastaus(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def avaaja(data):
    def avaa(pyynto, timeout=None):
        avaa.url = pyynto.full_url
        return Vastaus(json.dumps(data).encode())
    return avaa


def git_ok(*a, **k_):
    return subprocess.CompletedProcess(a, 0, stdout=SHA + "\n", stderr="")


def aja(avaa, suorita=git_ok):
    ulos = io.StringIO()
    return k.main(["--hakemisto", "/x"], avaa=avaa, suorita=suorita, tuloste=ulos), ulos.getvalue()


class Testit(unittest.TestCase):
    def test_ajan_tasalla(self):
        koodi, ulos = aja(avaaja({"ahead_by": 0, "behind_by": 0, "commits": []}))
        self.assertEqual(koodi, 0)
        self.assertIn("ajan tasalla", ulos)

    def test_jaljessa_kertoo_maaran_ja_prt(self):
        data = {"ahead_by": 3, "behind_by": 0, "commits": [
            {"commit": {"message": "Tarkastaja: syy lokiin (#214)\n\nviittaa #1"}},
            {"commit": {"message": "Merge pull request #193 from x"}},
            {"commit": {"message": "ilman numeroa"}}]}
        avaa = avaaja(data)
        koodi, ulos = aja(avaa)
        self.assertEqual(koodi, 1)
        self.assertIn("3 committia", ulos)
        self.assertIn("#214, #193", ulos)
        self.assertNotIn("#1,", ulos)
        self.assertTrue(avaa.url.endswith("/agentti-pohja/compare/%s...main" % SHA))

    def test_omat_commitit_eivat_ole_ajan_tasalla(self):
        koodi, ulos = aja(avaaja({"ahead_by": 0, "behind_by": 2, "commits": []}))
        self.assertEqual(koodi, 1)
        self.assertIn("2 committia, joita GitHubissa ei ole", ulos)

    def test_tuntematon_commit_on_tila_ei_selvinnyt(self):
        def avaa(pyynto, timeout=None):
            if "/compare/" in pyynto.full_url:
                raise urllib.error.HTTPError(pyynto.full_url, 404, "x", None, None)
            return Vastaus(b"{}")  # repo nakyy
        koodi, ulos = aja(avaa)
        self.assertEqual(koodi, 2)
        self.assertIn("ei loydy GitHubista", ulos)
        self.assertNotIn("yksityinen", ulos)

    def test_404_kun_repo_ei_nay_ohjaa_reposta_ei_commitista(self):
        def avaa(pyynto, timeout=None):
            raise urllib.error.HTTPError(pyynto.full_url, 404, "x", None, None)
        koodi, ulos = aja(avaa)
        self.assertEqual(koodi, 2)
        self.assertIn("404 myos repolle", ulos)
        self.assertIn("yksityinen", ulos)
        self.assertIn("--repo", ulos)
        self.assertNotIn("omia committeja", ulos)
        self.assertNotIn("nakyvyytta", ulos)

    def test_404_kun_repon_tila_ei_selvia(self):
        def avaa(pyynto, timeout=None):
            if "/compare/" in pyynto.full_url:
                raise urllib.error.HTTPError(pyynto.full_url, 404, "x", None, None)
            raise urllib.error.URLError("x")
        koodi, ulos = aja(avaa)
        self.assertEqual(koodi, 2)
        self.assertIn("syy voi olla commit, yksityinen repo", ulos)

    def test_pr_numerot_vain_yhdistamisotsikoista(self):
        data = {"ahead_by": 4, "behind_by": 0, "commits": [
            {"commit": {"message": "Korjaa vika #7 ja #8"}},
            {"commit": {"message": "Merge pull request #193 from x/y\n\n#5"}},
            {"commit": {"message": "Otsikko (#246)"}},
            {"commit": {"message": "Viittaa (#9) keskella"}}]}
        koodi, ulos = aja(avaaja(data))
        self.assertIn("#193, #246", ulos)
        for ei in ("#7", "#8", "#5", "#9"):
            self.assertNotIn(ei, ulos)

    def test_verkkovirhe_ei_ole_ajan_tasalla(self):
        def avaa(pyynto, timeout=None):
            raise urllib.error.URLError("x")
        self.assertEqual(aja(avaa)[0], 2)

    def test_git_virhe(self):
        def huono(*a, **k_):
            return subprocess.CompletedProcess(a, 128, stdout="", stderr="dubious ownership")
        koodi, ulos = aja(avaaja({}), suorita=huono)
        self.assertEqual(koodi, 2)
        self.assertIn("safe.directory", ulos)


TUNNUS = "x" * 30   # tekaistu, ei oikea


class Lukutunnus(unittest.TestCase):
    """Vain luku -tunnus kaytetaan, jos tiedosto on olemassa (A744); muuten pyynto on tunnistautumaton."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ero-testi-")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.polku = os.path.join(self.tmp, "github-luku.token")

    def ymparisto(self, polku):
        return mock.patch.dict(os.environ, {"GITHUB_LUKU_TUNNUS_POLKU": polku})

    def kirjaaja(self, virhe401=False):
        pyynnot = []

        def avaa(pyynto, timeout=None):
            pyynnot.append(pyynto)
            if virhe401 and pyynto.get_header("Authorization"):
                raise urllib.error.HTTPError(pyynto.full_url, 401, "x", {}, None)
            return Vastaus(json.dumps({"ahead_by": 0, "behind_by": 0, "commits": []}).encode())
        return avaa, pyynnot

    def test_tunnus_lisataan_kun_tiedosto_on(self):
        with open(self.polku, "w") as f:
            f.write(TUNNUS + "\n")
        avaa, pyynnot = self.kirjaaja()
        with self.ymparisto(self.polku):
            k.hae_vertailu("agentti-pohja", SHA, "main", avaa=avaa)
            k.repo_nakyy("agentti-pohja", avaa=avaa)
        self.assertEqual(len(pyynnot), 2)
        for p in pyynnot:
            self.assertEqual(p.get_header("Authorization"), "Bearer " + TUNNUS)
            self.assertTrue(p.full_url.startswith("https://api.github.com/"))

    def test_ilman_tiedostoa_pyynto_on_tunnistautumaton(self):
        avaa, pyynnot = self.kirjaaja()
        with self.ymparisto(os.path.join(self.tmp, "ei-ole")):
            k.hae_vertailu("agentti-pohja", SHA, "main", avaa=avaa)
        self.assertIsNone(pyynnot[0].get_header("Authorization"))

    def test_hylatty_tunnus_toistetaan_ilman_tunnusta(self):
        with open(self.polku, "w") as f:
            f.write(TUNNUS)
        avaa, pyynnot = self.kirjaaja(virhe401=True)
        with self.ymparisto(self.polku):
            self.assertEqual(k.hae_vertailu("agentti-pohja", SHA, "main", avaa=avaa)["ahead_by"], 0)
        self.assertEqual([bool(p.get_header("Authorization")) for p in pyynnot], [True, False])

    def test_tunnus_ei_nay_virheessa(self):
        with open(self.polku, "w") as f:
            f.write(TUNNUS)

        def avaa(pyynto, timeout=None):
            raise urllib.error.HTTPError(pyynto.full_url, 403, "x", {}, None)
        with self.ymparisto(self.polku):
            with self.assertRaises(k.EroVirhe) as e:
                k.hae_vertailu("agentti-pohja", SHA, "main", avaa=avaa)
        self.assertNotIn(TUNNUS, str(e.exception) + e.exception.lyhyt)
        self.assertEqual(e.exception.lyhyt, "GitHub HTTP 403")


class DubiousOwnership(unittest.TestCase):
    """Eri kayttajan omistama kopio: yksi toisto `-c safe.directory=<vain tama polku>`, ei globaalia asetusta."""
    DUBIOUS = "fatal: detected dubious ownership in repository at '/x'"

    def test_toisto_safe_directoryn_kanssa(self):
        kutsut = []

        def suorita(komento, **kw):
            kutsut.append(komento)
            if "safe.directory=" + os.path.realpath("/x") in komento:
                return subprocess.CompletedProcess(komento, 0, stdout=SHA + "\n", stderr="")
            return subprocess.CompletedProcess(komento, 128, stdout="", stderr=self.DUBIOUS)
        self.assertEqual(k.paikallinen_commit("/x", suorita=suorita), SHA)
        self.assertEqual(len(kutsut), 2)
        self.assertNotIn("safe.directory=*", " ".join(kutsut[1]))
        self.assertNotIn("config", kutsut[1])   # ei kirjoiteta gitin asetuksiin

    def test_muu_git_virhe_ei_toisteta(self):
        kutsut = []

        def suorita(komento, **kw):
            kutsut.append(komento)
            return subprocess.CompletedProcess(komento, 128, stdout="", stderr="fatal: not a git repository")
        with self.assertRaises(k.EroVirhe) as e:
            k.paikallinen_commit("/x", suorita=suorita)
        self.assertEqual(len(kutsut), 1)
        self.assertEqual(e.exception.lyhyt, "git: kopio ei ole luettava")

    def test_toisto_epaonnistuu_kertoo_syyn(self):
        def suorita(komento, **kw):
            return subprocess.CompletedProcess(komento, 128, stdout="", stderr=self.DUBIOUS)
        with self.assertRaises(k.EroVirhe) as e:
            k.paikallinen_commit("/x", suorita=suorita)
        self.assertIn("omistaja", e.exception.lyhyt)


if __name__ == "__main__":
    unittest.main()
