"""Testit aivo/tiivista.py:n ohjaukselle (stdlib unittest): alue ohjautuu oikeaan moduuliin ja oikeilla argumenteilla.
Alueiden ajo korvataan vaarennetyilla funktioilla: ei mallikutsuja, ei verkkoa, ei tiedostoja."""
import io
import runpy
import sys
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from aivo import tiivista, tiivista_tyokalu, tiivista_yksityinen


def aja(argv, **kw):
    """Ajaa tiivista.main:n ja palauttaa (paluukoodi tai SystemExit-koodi, stdout, stderr)."""
    ulos, virhe = io.StringIO(), io.StringIO()
    with redirect_stdout(ulos), redirect_stderr(virhe):
        try:
            koodi = tiivista.main(argv, **kw)
        except SystemExit as e:
            koodi = e.code
    return koodi, ulos.getvalue(), virhe.getvalue()


class OhjausTestit(unittest.TestCase):
    def setUp(self):
        self.tyokalu = mock.patch.object(tiivista_tyokalu, "main", return_value=11).start()
        self.yksityinen = mock.patch.object(tiivista_yksityinen, "main", return_value=22).start()
        self.addCleanup(mock.patch.stopall)

    def test_tyokalu_ohjautuu_tyokalumoduuliin(self):
        koodi, _, _ = aja(["--alue", "tyokalu"])
        self.assertEqual(koodi, 11)
        self.tyokalu.assert_called_once_with(["--alue", "tyokalu"])
        self.yksityinen.assert_not_called()

    def test_yksityinen_ohjautuu_yksityiseen_moduuliin(self):
        koodi, _, _ = aja(["--alue", "yksityinen"])
        self.assertEqual(koodi, 22)
        self.yksityinen.assert_called_once_with([])
        self.tyokalu.assert_not_called()

    def test_tyokalu_saa_alueen_ja_loput_argumentit_samassa_jarjestyksessa(self):
        aja(["--kuiva", "--alue", "tyokalu", "--juuri", "/x"])
        self.tyokalu.assert_called_once_with(["--alue", "tyokalu", "--kuiva", "--juuri", "/x"])

    def test_yksityinen_saa_loput_argumentit_ilman_aluetta(self):
        aja(["--alue", "yksityinen", "--kuiva", "--taustapaa", "loopback", "--malli-url", "http://x"])
        self.yksityinen.assert_called_once_with(["--kuiva", "--taustapaa", "loopback", "--malli-url", "http://x"])

    def test_tyokalu_valittaa_lisaargumentit_nimetylle_kwargille(self):
        sentinel = object()
        aja(["--alue", "tyokalu"], malli=sentinel)
        self.tyokalu.assert_called_once_with(["--alue", "tyokalu"], malli=sentinel)

    def test_yksityinen_ei_saa_kwargeja(self):
        aja(["--alue", "yksityinen"], malli=object())
        self.yksityinen.assert_called_once_with([])

    def test_paluukoodi_valittyy_sellaisenaan(self):
        self.tyokalu.return_value = 0
        self.yksityinen.return_value = 3
        self.assertEqual(aja(["--alue", "tyokalu"])[0], 0)
        self.assertEqual(aja(["--alue", "yksityinen"])[0], 3)

    def test_tyokalualue_ei_lataa_yksityisen_alueen_moduulia(self):
        nimi = "aivo.tiivista_yksityinen"
        paketti = sys.modules["aivo"]
        vanha = paketti.tiivista_yksityinen
        with mock.patch.dict(sys.modules):
            del sys.modules[nimi]
            del paketti.tiivista_yksityinen
            try:
                aja(["--alue", "tyokalu"])
                self.assertNotIn(nimi, sys.modules)
            finally:
                paketti.tiivista_yksityinen = vanha

    def test_ohjaus_ei_kutsu_kumpaakaan_ennen_aluevalintaa(self):
        for argv in ([], ["--alue"], ["--alue", "x"], ["--kuiva"]):
            aja(argv)
        self.tyokalu.assert_not_called()
        self.yksityinen.assert_not_called()


class VirheTestit(unittest.TestCase):
    def setUp(self):
        self.tyokalu = mock.patch.object(tiivista_tyokalu, "main", return_value=0).start()
        self.yksityinen = mock.patch.object(tiivista_yksityinen, "main", return_value=0).start()
        self.addCleanup(mock.patch.stopall)

    def kaatuu(self, argv):
        koodi, _, virhe = aja(argv)
        self.assertIsInstance(koodi, int)
        self.assertNotEqual(koodi, 0)
        self.tyokalu.assert_not_called()
        self.yksityinen.assert_not_called()
        return virhe

    def test_puuttuva_alue_antaa_virheen(self):
        self.assertIn("--alue", self.kaatuu([]))

    def test_pelkka_muu_argumentti_ilman_aluetta_antaa_virheen(self):
        self.assertIn("--alue", self.kaatuu(["--kuiva"]))

    def test_alueen_arvo_puuttuu(self):
        self.assertIn("--alue", self.kaatuu(["--alue"]))

    def test_tuntematon_alue_antaa_virheen_ja_listaa_vaihtoehdot(self):
        virhe = self.kaatuu(["--alue", "julkinen"])
        self.assertIn("julkinen", virhe)
        self.assertIn("yksityinen", virhe)
        self.assertIn("tyokalu", virhe)

    def test_alueen_nimi_on_kirjainkokoriippuvainen(self):
        self.kaatuu(["--alue", "Yksityinen"])
        self.kaatuu(["--alue", "TYOKALU"])

    def test_tyhja_alue_antaa_virheen(self):
        self.kaatuu(["--alue", ""])

    def test_virheen_kayttoviesti_nimeaa_moduulin(self):
        self.assertIn("aivo.tiivista", self.kaatuu([]))

    def test_virhe_kirjoitetaan_stderriin_eika_stdoutiin(self):
        koodi, ulos, virhe = aja([])
        self.assertEqual(ulos, "")
        self.assertNotEqual(virhe, "")

    def test_ohje_ei_ole_ohjauksen_oma_vaan_kuuluu_alueelle(self):
        # add_help=False: -h kulkee alueen moduulille eika ohjaus tulosta omaa ohjettaan.
        koodi, ulos, _ = aja(["--alue", "yksityinen", "-h"])
        self.assertEqual(koodi, 0)
        self.assertEqual(ulos, "")
        self.yksityinen.assert_called_once_with(["-h"])


class AjoKomentorivilta(unittest.TestCase):
    def test_main_vartija_ajaa_ohjauksen_ja_poistuu_alueen_koodilla(self):
        with mock.patch.object(tiivista_yksityinen, "main", return_value=7) as y, \
                mock.patch.object(sys, "argv", ["tiivista", "--alue", "yksityinen", "--kuiva"]):
            with self.assertRaises(SystemExit) as e, warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                runpy.run_module("aivo.tiivista", run_name="__main__")
        self.assertEqual(e.exception.code, 7)
        y.assert_called_once_with(["--kuiva"])

    def test_tuonti_ei_aja_ohjausta(self):
        with mock.patch.object(tiivista_yksityinen, "main") as y, mock.patch.object(tiivista_tyokalu, "main") as t, \
                mock.patch.object(sys, "argv", ["tiivista"]):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                runpy.run_module("aivo.tiivista", run_name="aivo.tiivista_tuonti")
        y.assert_not_called()
        t.assert_not_called()


if __name__ == "__main__":
    unittest.main()
