"""Tyokalujen testit ja rakennetesti (suunnitelma kohta 11/2): ei verkkoa eika aliprosesseja."""
import ast
import os
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from aivo.agentti import polut, tyokalut

HAKEMISTO = pathlib.Path(__file__).resolve().parent / "agentti"
KIELLETYT_MODUULIT = {"urllib", "socket", "http", "subprocess", "ssl", "ftplib", "smtplib", "telnetlib",
                      "xmlrpc", "asyncio", "multiprocessing", "ctypes", "importlib", "requests", "pty"}
KIELLETYT_OS = {"system", "popen", "fork", "forkpty", "execv", "execve", "execvp", "execl", "execle",
                "execlp", "spawnl", "spawnv", "spawnlp", "spawnvp", "posix_spawn", "remove", "rmdir",
                "removedirs"}


def _tuodut(puu):
    nimet = []
    for n in ast.walk(puu):
        if isinstance(n, ast.Import):
            nimet += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            nimet.append(("." * n.level) + (n.module or ""))
    return nimet


class RakenneTesti(unittest.TestCase):
    def moduulit(self):
        tiedostot = sorted(HAKEMISTO.glob("*.py"))
        self.assertTrue({"polut.py", "tyokalut.py", "protokolla.py", "silmukka.py"} <= {t.name for t in tiedostot})
        return tiedostot

    def test_ei_verkko_eika_aliprosessituontia(self):
        for t in self.moduulit():
            puu = ast.parse(t.read_text(encoding="utf-8"))
            for nimi in _tuodut(puu):
                paa = nimi.lstrip(".").split(".")[0]
                self.assertNotIn(paa, KIELLETYT_MODUULIT, "%s tuo %s" % (t.name, nimi))

    def test_tuonnit_vain_vakiokirjastosta_ja_omasta_paketista(self):
        sallitut_oma = {"", "polut", "tyokalut", "protokolla", "silmukka"}
        for t in self.moduulit():
            puu = ast.parse(t.read_text(encoding="utf-8"))
            for n in ast.walk(puu):
                if isinstance(n, ast.ImportFrom) and n.level:
                    self.assertEqual(n.level, 1, t.name)
                    self.assertIn((n.module or ""), sallitut_oma, t.name)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    nimi = n.names[0].name if isinstance(n, ast.Import) else n.module
                    self.assertFalse(nimi.startswith("aivo"), "%s tuo muun aivo-moduulin: %s" % (t.name, nimi))

    def test_ei_dynaamista_tuontia_eika_koodin_ajoa(self):
        for t in self.moduulit():
            puu = ast.parse(t.read_text(encoding="utf-8"))
            for n in ast.walk(puu):
                if isinstance(n, ast.Name):
                    self.assertNotIn(n.id, {"__import__", "eval", "exec", "compile"}, t.name)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os":
                    self.assertNotIn(n.attr, KIELLETYT_OS, "%s: os.%s" % (t.name, n.attr))

    def test_tarkistin_tunnistaa_kielletyn_tuonnin(self):
        for koodi in ("import subprocess", "from urllib import request", "import urllib.request",
                      "import socket as s", "from http.client import X"):
            tuodut = _tuodut(ast.parse(koodi))
            self.assertTrue(any(n.split(".")[0] in KIELLETYT_MODUULIT for n in tuodut), koodi)

    def test_tyokalut_ja_nimet_vastaavat_toisiaan(self):
        from aivo.agentti import protokolla
        self.assertEqual(set(tyokalut.TYOKALUT), set(protokolla.NIMET))


class TyokaluTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.juuri = self._tmp.name

    def aja(self, nimi, **arg):
        return tyokalut.suorita(self.juuri, nimi, arg)

    def test_kirjoita_lue_listaa(self):
        self.assertTrue(self.aja("kirjoita", polku="a.md", sisalto="\u00e4\n\u00f6\n").ok)
        self.assertEqual(self.aja("lue", polku="a.md").teksti, "\u00e4\n\u00f6")
        self.assertIn("f a.md", self.aja("listaa").teksti)

    def test_kirjoita_korvaa(self):
        self.aja("kirjoita", polku="a.md", sisalto="vanha")
        self.aja("kirjoita", polku="a.md", sisalto="uusi")
        self.assertEqual(self.aja("lue", polku="a.md").teksti, "uusi")

    def test_tyhja_kansio(self):
        self.assertEqual(self.aja("listaa").teksti, "(tyhja)")

    def test_lue_rivit_ja_jatko(self):
        self.aja("kirjoita", polku="a.txt", sisalto="\n".join("r%d" % i for i in range(10)))
        t = self.aja("lue", polku="a.txt", alku=2, rivit=3)
        self.assertTrue(t.teksti.startswith("r2\nr3\nr4\n"))
        self.assertIn("jatka alku=5", t.teksti)

    def test_lue_katkaisee_64kt(self):
        self.aja("kirjoita", polku="a.txt", sisalto="\n".join("x" * 99 for _ in range(1500)))
        t = self.aja("lue", polku="a.txt", rivit=500)
        self.assertTrue(t.ok)
        self.assertLessEqual(len(t.teksti.encode()), tyokalut.RAJA_LUKU + 200)
        self.assertIn("jatka alku=", t.teksti)

    def test_lue_ohjausmerkit_nakyviksi(self):
        with open(os.path.join(self.juuri, "a.txt"), "wb") as f:
            f.write(b"a\x1b[31mb\x00c\r\nd")
        t = self.aja("lue", polku="a.txt").teksti
        self.assertNotIn("\x1b", t)
        self.assertNotIn("\x00", t)
        self.assertIn("\\x1b", t)
        self.assertIn("\\x00", t)

    def test_lue_ei_utf8(self):
        with open(os.path.join(self.juuri, "a.txt"), "wb") as f:
            f.write(b"\xff\xfe\x00")
        t = self.aja("lue", polku="a.txt")
        self.assertFalse(t.ok)

    def test_lue_puuttuva_tiedosto_ja_kansio(self):
        self.assertFalse(self.aja("lue", polku="ei.md").ok)
        os.mkdir(os.path.join(self.juuri, "k"))
        self.assertFalse(self.aja("lue", polku="k").ok)

    def test_vaarat_argumentit(self):
        self.assertFalse(self.aja("lue", polku="a.md", alku=-1).ok)
        self.assertFalse(self.aja("lue", polku="a.md", alku="1").ok)
        self.assertFalse(self.aja("lue", polku="a.md", rivit=0).ok)
        self.assertFalse(self.aja("lue", polku="a.md", rivit=True).ok)
        self.assertFalse(self.aja("lue", polku="a.md", ylimaarainen=1).ok)
        self.assertFalse(self.aja("kirjoita", polku="a.md", sisalto=5).ok)
        self.assertFalse(self.aja("kirjoita", polku="a.md").ok)
        self.assertFalse(self.aja("kirjoita", polku="a.md", sisalto="a\x00b").ok)
        self.assertFalse(self.aja("kirjoita", polku="a.md", sisalto="\ud800").ok)
        self.assertFalse(self.aja("listaa", polku=5).ok)

    def test_tuntematon_tyokalu_ja_arg(self):
        self.assertFalse(tyokalut.suorita(self.juuri, "poista", {}).ok)
        self.assertFalse(tyokalut.suorita(self.juuri, "lue", "teksti").ok)
        self.assertFalse(tyokalut.suorita(self.juuri, "lue", None).ok)

    def test_poistotyokalua_ei_ole(self):
        self.assertFalse(any("poista" in n or "poisto" in n for n in tyokalut.TYOKALUT))

    def test_valmis(self):
        t = self.aja("valmis", raportti="Tehty.")
        self.assertTrue(t.ok and t.valmis)
        self.assertEqual(t.teksti, "Tehty.")
        self.assertFalse(self.aja("valmis", raportti="").ok)
        self.assertFalse(self.aja("valmis", raportti="  \n").ok)
        self.assertFalse(self.aja("valmis").ok)
        self.assertFalse(self.aja("valmis", raportti="x" * (tyokalut.RAJA_RAPORTTI + 1)).ok)
        self.assertTrue(self.aja("valmis", raportti="x" * tyokalut.RAJA_RAPORTTI).ok)

    def test_muut_tyokalut_eivat_lopeta(self):
        self.assertFalse(self.aja("listaa").valmis)

    def test_listaus_raja(self):
        for i in range(tyokalut.RAJA_RIVIT + 5):
            open(os.path.join(self.juuri, "f%04d.txt" % i), "w").close()
        t = self.aja("listaa").teksti.splitlines()
        self.assertEqual(len(t), tyokalut.RAJA_RIVIT + 1)
        self.assertIn("pois", t[-1])

    def test_listaus_puhdistaa_nimet(self):
        os.mkfifo(os.path.join(self.juuri, "putki\x1bx"))
        self.assertNotIn("\x1b", self.aja("listaa").teksti)

    def test_virhe_ei_vuoda_polkua_eika_poikkeuksen_viestia(self):
        t = self.aja("lue", polku="ei.md")
        self.assertNotIn(self.juuri, t.teksti)

    def test_sisainen_virhe_nayttaa_vain_tyypin(self):
        orig = tyokalut.TYOKALUT["listaa"]
        def rikki(juuri, arg):
            raise RuntimeError("salainen-viesti")
        tyokalut.TYOKALUT["listaa"] = rikki
        try:
            t = self.aja("listaa")
        finally:
            tyokalut.TYOKALUT["listaa"] = orig
        self.assertFalse(t.ok)
        self.assertIn("RuntimeError", t.teksti)
        self.assertNotIn("salainen", t.teksti)

    def test_valiaikaistiedosto_ei_jaa(self):
        self.aja("kirjoita", polku="a.md", sisalto="x")
        self.assertEqual(os.listdir(self.juuri), ["a.md"])

    def test_valiaikaistiedoston_nimessa_satunnainen_osa(self):
        a, b = polut.valiaikainen_nimi(), polut.valiaikainen_nimi()
        self.assertNotEqual(a, b)
        for nimi in (a, b):
            self.assertIsNotNone(polut.VALIAIKAINEN.fullmatch(nimi), nimi)
            self.assertTrue(nimi.startswith(".kirj-%d-%d-" % (os.getpid(), threading.get_ident())), nimi)

    def test_vanhan_ajon_jaannos_samalla_pidilla_ei_esta_kirjoitusta(self):
        with open(os.path.join(self.juuri, ".kirj-%d.tmp" % os.getpid()), "w") as f:
            f.write("jaannos")
        self.assertTrue(self.aja("kirjoita", polku="a.md", sisalto="x").ok)

    def test_rinnakkaiset_saikeet_samaan_kansioon(self):
        tulokset = {}

        def kirjoita(i):
            tulokset[i] = self.aja("kirjoita", polku="k/t%02d.md" % i, sisalto="x" * 1000)

        saikeet = [threading.Thread(target=kirjoita, args=(i,)) for i in range(16)]
        for s in saikeet:
            s.start()
        for s in saikeet:
            s.join()
        self.assertTrue(all(t.ok for t in tulokset.values()), [t.teksti for t in tulokset.values() if not t.ok])
        self.assertEqual(len(tulokset), 16)
        self.assertEqual(sorted(os.listdir(os.path.join(self.juuri, "k"))), ["t%02d.md" % i for i in range(16)])

    def test_valiaikaistiedosto_on_lukittu_kirjoituksen_ajan(self):
        alkuperainen = os.replace
        havainnot = []

        def tarkkaile(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            havainnot.append(polut._lukitsematon(src, src_dir_fd))
            return alkuperainen(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        with mock.patch.object(tyokalut.os, "replace", tarkkaile):
            self.assertTrue(self.aja("kirjoita", polku="a.md", sisalto="x").ok)
        self.assertEqual(havainnot, [False])   # lukittu = ei vapaa

    def test_hylatty_kirjoitus_ei_jata_valikansioita(self):
        for i in range(polut.RAJA_TIEDOSTOT):
            with open(os.path.join(self.juuri, "f%03d.txt" % i), "w") as f:
                f.write("x")
        t = self.aja("kirjoita", polku="a/b/c/uusi.md", sisalto="x")
        self.assertFalse(t.ok)
        self.assertIn("taynna", t.teksti)
        self.assertFalse(os.path.exists(os.path.join(self.juuri, "a")))

    def test_hylatty_kirjoitus_olemassa_olevan_kansion_alle(self):
        os.mkdir(os.path.join(self.juuri, "a"))
        for i in range(polut.RAJA_TIEDOSTOT):
            with open(os.path.join(self.juuri, "f%03d.txt" % i), "w") as f:
                f.write("x")
        self.assertFalse(self.aja("kirjoita", polku="a/b/uusi.md", sisalto="x").ok)
        self.assertEqual(os.listdir(os.path.join(self.juuri, "a")), [])

    def test_ylisuuri_kirjoitus_ei_jata_valikansioita(self):
        t = self.aja("kirjoita", polku="a/b/iso.md", sisalto="a" * (polut.RAJA_TIEDOSTO + 1))
        self.assertFalse(t.ok)
        self.assertFalse(os.path.exists(os.path.join(self.juuri, "a")))

    def test_kirjoitus_uuteen_kansioon_toimii(self):
        self.assertTrue(self.aja("kirjoita", polku="a/b/uusi.md", sisalto="x").ok)
        self.assertEqual(os.listdir(os.path.join(self.juuri, "a", "b")), ["uusi.md"])


if __name__ == "__main__":
    unittest.main()
