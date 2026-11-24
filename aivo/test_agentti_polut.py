"""Polkusaantojen testit (suunnitelma kohta 11/3): jokainen saanto hylkaa oikean tapauksen."""
import os
import tempfile
import unittest

from aivo.agentti import polut, tyokalut


class PolkuTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.juuri = os.path.join(self._tmp.name, "tyo")
        os.mkdir(self.juuri)
        self.ulko = os.path.join(self._tmp.name, "ulko")
        os.mkdir(self.ulko)
        with open(os.path.join(self.ulko, "salainen.txt"), "w") as f:
            f.write("ulkoinen")

    def kirjoita(self, polku, sisalto="x"):
        return tyokalut.suorita(self.juuri, "kirjoita", {"polku": polku, "sisalto": sisalto})

    def lue(self, polku, **kw):
        return tyokalut.suorita(self.juuri, "lue", dict(polku=polku, **kw))

    # --- jasenna_polku
    def test_hyvat_polut(self):
        self.assertEqual(polut.jasenna_polku("a.md"), ("a.md",))
        self.assertEqual(polut.jasenna_polku("./a//b/c.txt"), ("a", "b", "c.txt"))
        self.assertEqual(polut.jasenna_polku("", salli_tyhja=True), ())

    def test_hylkaa_kaksoispiste(self):
        for p in ("..", "../x.md", "a/../x.md", "a/..", "a/b/../../../x.md"):
            with self.assertRaises(polut.PolkuVirhe, msg=p):
                polut.jasenna_polku(p)

    def test_hylkaa_absoluuttinen(self):
        for p in ("/etc/passwd", "/x.md", "//x.md"):
            with self.assertRaises(polut.PolkuVirhe, msg=p):
                polut.jasenna_polku(p)

    def test_hylkaa_ohjausmerkit_kenoviiva_ja_piilotiedosto(self):
        for p in ("a\x00b.md", "a\nb.md", "a\\b.md", ".piilo.md", "a/.x/b.md", "\x7f.md"):
            with self.assertRaises(polut.PolkuVirhe, msg=repr(p)):
                polut.jasenna_polku(p)

    def test_hylkaa_tyhja_ja_vaara_tyyppi(self):
        for p in ("", ".", "./", None, 5, ["a"]):
            with self.assertRaises(polut.PolkuVirhe, msg=repr(p)):
                polut.jasenna_polku(p)

    def test_hylkaa_liian_pitka_ja_syva(self):
        with self.assertRaises(polut.PolkuVirhe):
            polut.jasenna_polku("a" * (polut.RAJA_NIMI + 1))
        with self.assertRaises(polut.PolkuVirhe):
            polut.jasenna_polku("/".join(["a"] * (polut.RAJA_SYVYYS + 1)))
        polut.jasenna_polku("/".join(["a"] * polut.RAJA_SYVYYS))
        with self.assertRaises(polut.PolkuVirhe):
            polut.jasenna_polku("a/" * 99 + "b")

    # --- paate
    def test_paatteet(self):
        for p in ("a.md", "a.TXT", "x/a.csv", "a.json"):
            polut.tarkista_paate(polut.jasenna_polku(p))
        for p in ("a.py", "a.sh", "a", "a.md.exe", "a.mdx"):
            with self.assertRaises(polut.PolkuVirhe, msg=p):
                polut.tarkista_paate(polut.jasenna_polku(p))
        with self.assertRaises(polut.PolkuVirhe):
            polut.tarkista_paate(())

    def test_kirjoita_hylkaa_kielletyn_paatteen(self):
        t = self.kirjoita("skripti.py", "print(1)")
        self.assertFalse(t.ok)
        self.assertFalse(os.path.exists(os.path.join(self.juuri, "skripti.py")))

    # --- tyokalut hylkaavat ulos paaseen
    def test_tyokalut_hylkaavat_ulos_paasyn(self):
        for p in ("../ulko/salainen.txt", "/etc/passwd"):
            self.assertFalse(self.lue(p).ok, p)
            self.assertFalse(self.kirjoita(p).ok, p)
        self.assertFalse(tyokalut.suorita(self.juuri, "listaa", {"polku": ".."}).ok)
        self.assertFalse(tyokalut.suorita(self.juuri, "listaa", {"polku": "/"}).ok)

    # --- symbolinen linkki: lehti
    def test_lehtilinkki_lukua_vastaan(self):
        os.symlink(os.path.join(self.ulko, "salainen.txt"), os.path.join(self.juuri, "linkki.txt"))
        t = self.lue("linkki.txt")
        self.assertFalse(t.ok)
        self.assertNotIn("ulkoinen", t.teksti)

    def test_lehtilinkki_kirjoitusta_vastaan(self):
        kohde = os.path.join(self.ulko, "salainen.txt")
        os.symlink(kohde, os.path.join(self.juuri, "linkki.txt"))
        self.assertFalse(self.kirjoita("linkki.txt", "ylikirjoitus").ok)
        with open(kohde) as f:
            self.assertEqual(f.read(), "ulkoinen")

    def test_riippuva_lehtilinkki_kirjoitusta_vastaan(self):
        kohde = os.path.join(self.ulko, "uusi.txt")
        os.symlink(kohde, os.path.join(self.juuri, "riippuva.txt"))
        self.assertFalse(self.kirjoita("riippuva.txt", "x").ok)
        self.assertFalse(os.path.exists(kohde))

    # --- symbolinen linkki: valikansio
    def test_valikansiolinkki_lukua_vastaan(self):
        os.symlink(self.ulko, os.path.join(self.juuri, "kansio"))
        t = self.lue("kansio/salainen.txt")
        self.assertFalse(t.ok)
        self.assertNotIn("ulkoinen", t.teksti)
        self.assertFalse(tyokalut.suorita(self.juuri, "listaa", {"polku": "kansio"}).ok)

    def test_valikansiolinkki_kirjoitusta_vastaan(self):
        os.symlink(self.ulko, os.path.join(self.juuri, "kansio"))
        self.assertFalse(self.kirjoita("kansio/uusi.txt").ok)
        self.assertFalse(os.path.exists(os.path.join(self.ulko, "uusi.txt")))

    def test_syvempi_valikansiolinkki(self):
        os.mkdir(os.path.join(self.juuri, "a"))
        os.symlink(self.ulko, os.path.join(self.juuri, "a", "b"))
        self.assertFalse(self.kirjoita("a/b/c/uusi.txt").ok)
        self.assertFalse(os.path.exists(os.path.join(self.ulko, "c")))

    def test_juuri_ei_saa_olla_linkki(self):
        linkki = os.path.join(self._tmp.name, "juurilinkki")
        os.symlink(self.ulko, linkki)
        t = tyokalut.suorita(linkki, "listaa", {})
        self.assertFalse(t.ok)

    def test_listaus_nayttaa_linkin_mutta_ei_seuraa(self):
        os.symlink(self.ulko, os.path.join(self.juuri, "kansio"))
        t = tyokalut.suorita(self.juuri, "listaa", {})
        self.assertTrue(t.ok)
        self.assertIn("l kansio", t.teksti)

    # --- koko
    def test_ylisuuri_kirjoitus_hylataan(self):
        t = self.kirjoita("iso.txt", "a" * (polut.RAJA_TIEDOSTO + 1))
        self.assertFalse(t.ok)
        self.assertFalse(os.path.exists(os.path.join(self.juuri, "iso.txt")))

    def test_rajan_kokoinen_kirjoitus_kelpaa(self):
        self.assertTrue(self.kirjoita("raja.txt", "a" * polut.RAJA_TIEDOSTO).ok)

    def test_ylisuuri_olemassa_oleva_tiedosto_ei_lueta(self):
        with open(os.path.join(self.juuri, "iso.txt"), "wb") as f:
            f.write(b"a" * (polut.RAJA_TIEDOSTO + 1))
        self.assertFalse(self.lue("iso.txt").ok)

    # --- tyokansion tayttyminen
    def test_tiedostomaara_raja(self):
        for i in range(polut.RAJA_TIEDOSTOT):
            with open(os.path.join(self.juuri, "f%03d.txt" % i), "w") as f:
                f.write("x")
        t = self.kirjoita("yksi-liikaa.txt")
        self.assertFalse(t.ok)
        self.assertIn("taynna", t.teksti)
        self.assertTrue(self.kirjoita("f000.txt", "korvaus").ok)   # korvaus ei lisaa tiedostoja

    def test_tiedostomaara_raja_alikansiossa(self):
        os.mkdir(os.path.join(self.juuri, "k"))
        for i in range(polut.RAJA_TIEDOSTOT):
            with open(os.path.join(self.juuri, "k", "f%03d.txt" % i), "w") as f:
                f.write("x")
        self.assertFalse(self.kirjoita("uusi.txt").ok)

    def test_tavuraja(self):
        koko = polut.RAJA_KANSIO_TAVUT
        n = koko // polut.RAJA_TIEDOSTO
        for i in range(n):
            with open(os.path.join(self.juuri, "i%d.txt" % i), "wb") as f:
                f.write(b"a" * polut.RAJA_TIEDOSTO)
        jaljella = koko - n * polut.RAJA_TIEDOSTO
        self.assertFalse(self.kirjoita("yli.txt", "a" * (jaljella + 1)).ok)
        self.assertTrue(self.kirjoita("tasan.txt", "a" * jaljella).ok)
        self.assertFalse(self.kirjoita("viela.txt", "a").ok)

    def test_korvaus_vapauttaa_vanhan_koon(self):
        koko = polut.RAJA_KANSIO_TAVUT
        n = koko // polut.RAJA_TIEDOSTO
        for i in range(n):
            with open(os.path.join(self.juuri, "i%d.txt" % i), "wb") as f:
                f.write(b"a" * polut.RAJA_TIEDOSTO)
        self.assertTrue(self.kirjoita("i0.txt", "pieni").ok)

    def test_epaonnistunut_kirjoitus_ei_jata_valiaikaistiedostoa(self):
        self.kirjoita("a.txt", "x" * (polut.RAJA_TIEDOSTO + 1))
        self.assertEqual(os.listdir(self.juuri), [])

    def test_normaali_kierros(self):
        self.assertTrue(self.kirjoita("a/b/c.md", "# otsikko\nrivi").ok)
        self.assertEqual(self.lue("a/b/c.md").teksti, "# otsikko\nrivi")
        self.assertIn("f c.md 14", tyokalut.suorita(self.juuri, "listaa", {"polku": "a/b"}).teksti)


if __name__ == "__main__":
    unittest.main()
