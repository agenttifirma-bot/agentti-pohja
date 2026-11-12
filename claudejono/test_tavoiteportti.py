"""Tavoiteportin aanekas hylkays (PR #287:n korvaaja) ja tools/tarkista_tehtava.py."""
import tempfile
import unittest
from pathlib import Path

from claudejono import ajuri, tavoite
from tools import tarkista_tehtava

NIMI = "2026-11-12-01-testi.md"


def pystyta(teksti, nimi=NIMI):
    repo = Path(tempfile.mkdtemp()) / "docs"
    teht = repo / "claude-jono" / "tehtavat"
    teht.mkdir(parents=True)
    (teht / nimi).write_text(teksti, encoding="utf-8")
    return repo, repo.parent


def tulos(repo, nimi=NIMI):
    return repo / "claude-jono" / "tulokset" / nimi


class Hylkaystulos(unittest.TestCase):
    def test_virheellinen_ensimmainen_rivi_antaa_epaonnistui_tuloksen(self):
        repo, tila = pystyta("# T\nTavoite: rahaa\n")
        hylatyt = []
        self.assertIsNone(ajuri.varaa_seuraava(repo, tila, 1, hylatyt=hylatyt))
        self.assertEqual(hylatyt, [tulos(repo)])
        t = tulos(repo).read_text(encoding="utf-8")
        self.assertIn("- Tila: EPAONNISTUI", t)
        self.assertIn("rivi 2", t)
        self.assertIn("portfolio, ansainta, Aivo, yllapito", t)

    def test_puuttuva_rivi_antaa_tuloksen(self):
        repo, tila = pystyta("# T\nei rivia\n")
        ajuri.varaa_seuraava(repo, tila, 1)
        self.assertIn("puuttuu", tulos(repo).read_text(encoding="utf-8"))

    def test_toista_kertaa_ei_kirjoiteta(self):
        repo, tila = pystyta("Tavoite: rahaa\n")
        h1, h2 = [], []
        ajuri.varaa_seuraava(repo, tila, 1, hylatyt=h1)
        ensin = tulos(repo).read_text(encoding="utf-8")
        tulos(repo).write_text(ensin + "MUOKATTU\n", encoding="utf-8")
        ajuri.varaa_seuraava(repo, tila, 1, hylatyt=h2)
        ajuri.varaa_seuraava(repo, tila, 2, hylatyt=h2)
        self.assertEqual((len(h1), h2), (1, []))
        self.assertTrue(tulos(repo).read_text(encoding="utf-8").endswith("MUOKATTU\n"))
        self.assertEqual(len((tila / tavoite.HYLKAYSLOKI).read_text().splitlines()), 1)

    def test_olemassa_olevaa_tulosta_ei_ylikirjoiteta(self):
        repo, tila = pystyta("Tavoite: rahaa\n")
        tulos(repo).parent.mkdir(parents=True)
        tulos(repo).write_text("vanha", encoding="utf-8")
        h = []
        self.assertIsNone(ajuri.kirjaa_hylkaystulos(repo, tila, repo / "claude-jono" / "tehtavat" / NIMI, "syy", h))
        self.assertEqual((tulos(repo).read_text(encoding="utf-8"), h), ("vanha", []))

    def test_kelpaava_ei_tulosta(self):
        repo, tila = pystyta("Tavoite: portfolio\n")
        hylatyt = []
        self.assertEqual(ajuri.varaa_seuraava(repo, tila, 1, hylatyt=hylatyt).name, NIMI)
        self.assertEqual(hylatyt, [])
        self.assertFalse(tulos(repo).exists())

    def test_vanha_tehtava_ilman_rivia_ei_hylata(self):
        repo, tila = pystyta("# vanha\n", "2026-11-01-01-vanha.md")
        self.assertEqual(ajuri.varaa_seuraava(repo, tila, 1).name, "2026-11-01-01-vanha.md")
        self.assertFalse(tulos(repo, "2026-11-01-01-vanha.md").exists())

    def test_ensimmainen_rivi_ratkaisee_myos_kun_myohempi_kelpaa(self):
        """Portti ei loysty: virheellinen ensimmainen + kelpaava lainaus myohemmin = hylkays (PR #287:n aukko)."""
        teksti = "Tavoite: rahaa\n\n> Tavoite: portfolio\n\nTavoite: yllapito\n"
        self.assertIsNone(tavoite.tavoite_tekstista(teksti))
        repo, tila = pystyta(teksti)
        self.assertIsNone(ajuri.varaa_seuraava(repo, tila, 1))
        self.assertTrue(tulos(repo).exists())

    def test_julkaisu_kutsutaan_lukon_jalkeen_ja_virhe_ei_kaada(self):
        kutsut = []
        vanha = ajuri.julkaise
        ajuri.julkaise = lambda r, p, v=None: kutsut.append(p) or (_ for _ in ()).throw(ajuri.JonoVirhe("x"))
        try:
            with ajuri._hylkayksen_julkaisu("r", [Path("a")]):
                pass
            with ajuri._hylkayksen_julkaisu("r", []):
                pass
        finally:
            ajuri.julkaise = vanha
        self.assertEqual(kutsut, [[Path("a")]])


class Tyokalu(unittest.TestCase):
    def aja(self, teksti, nimi=NIMI):
        h = Path(tempfile.mkdtemp())
        p = h / nimi
        p.write_text(teksti, encoding="utf-8")
        return tarkista_tehtava.main([str(p)])

    def test_koodit(self):
        self.assertEqual(self.aja("Tavoite: yllapito\n"), 0)
        self.assertEqual(self.aja("Tavoite: rahaa\n"), 1)
        self.assertEqual(self.aja("ei rivia\n"), 1)
        self.assertEqual(self.aja("Tavoite: yllapito\n", "VAARA.md"), 1)
        self.assertEqual(self.aja("ei rivia\n", "2026-11-01-01-vanha.md"), 0)
        self.assertEqual(self.aja("Tavoite: yllapito\n" + "x" * 20001), 1)
        self.assertEqual(tarkista_tehtava.main([]), 2)
        self.assertEqual(tarkista_tehtava.main(["/ei/ole/2026-11-12-01-olematon.md"]), 2)

    def test_ensimmainen_rivi_ratkaisee(self):
        self.assertEqual(self.aja("Tavoite: rahaa\nTavoite: portfolio\n"), 1)
        self.assertEqual(self.aja("Tavoite: portfolio\nTavoite: rahaa\n"), 0)

    def test_monta_tiedostoa_suurin_koodi(self):
        h = Path(tempfile.mkdtemp())
        (h / NIMI).write_text("Tavoite: aivo\n")
        (h / "2026-11-12-02-b.md").write_text("x\n")
        self.assertEqual(tarkista_tehtava.main([str(h / NIMI), str(h / "2026-11-12-02-b.md")]), 1)


if __name__ == "__main__":
    unittest.main()
