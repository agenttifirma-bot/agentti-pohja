"""Testit aivo/tarkista_asennus.py:lle. Vaarennetty komentoajuri ja HTTP, ei verkkoa eika oikeaa systemd:ta."""
import builtins
import os
import tempfile
import unittest
from unittest import mock

from aivo import tarkista_asennus as t

SHA = "a" * 40


def ajuri_ok(komento):
    if komento[0] == "git":
        return 0, SHA
    return 0, "active"


def http_ok(portti, polku):
    return 200, '{"tila": "ok"}'


class AvainFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avain = os.path.join(self.tmp.name, "avain")
        with open(self.avain, "w") as f:
            f.write("KANARIA-EI-SAA-NAKYA")
        os.chmod(self.avain, 0o600)

    def aja_main(self, argv, **kw):
        rivit = []
        kw.setdefault("ajuri", ajuri_ok)
        kw.setdefault("hae", http_ok)
        kw.setdefault("avaimet", (self.avain,))
        rc = t.main(argv, tulosta=rivit.append, **kw)
        return rc, rivit


class TestMain(AvainFixture):
    def test_kaikki_ok(self):
        with mock.patch.object(t, "tarkista_moduulit", return_value=(True, "3 moduulia")):
            rc, rivit = self.aja_main([SHA])
        self.assertEqual(rc, 0)
        self.assertEqual(len(rivit), 6)
        self.assertTrue(all(r.startswith("OK ") for r in rivit))

    def test_vika_antaa_1_ja_yksi_rivi_per_tarkistus(self):
        def ajuri(komento):
            if komento[0] == "systemctl":
                return 3, "inactive"
            return 0, SHA
        rc, rivit = self.aja_main([SHA], ajuri=ajuri)
        self.assertEqual(rc, 1)
        self.assertEqual(sum(r.startswith("VIKA") for r in rivit), 2)
        self.assertIn("inactive", "\n".join(rivit))

    def test_vaara_commit(self):
        rc, rivit = self.aja_main(["b" * 40])
        self.assertEqual(rc, 1)
        self.assertTrue(rivit[0].startswith("VIKA commit"))

    def test_lyhyt_commit_kelpaa(self):
        rc, rivit = self.aja_main([SHA[:8]])
        self.assertTrue(rivit[0].startswith("OK   commit"))

    def test_http_virhe_ei_kaada(self):
        def hae(portti, polku):
            raise ConnectionRefusedError("salaisuus")
        rc, rivit = self.aja_main([SHA], hae=hae)
        self.assertEqual(rc, 1)
        teksti = "\n".join(rivit)
        self.assertIn("ConnectionRefusedError", teksti)
        self.assertNotIn("salaisuus", teksti)

    def test_http_500(self):
        rc, rivit = self.aja_main([SHA], hae=lambda p, u: (500, ""))
        self.assertIn("VIKA terve /terve: HTTP 500", rivit)

    def test_poikkeus_tarkistuksessa_antaa_vian(self):
        def ajuri(komento):
            raise RuntimeError("salaisuus")
        rc, rivit = self.aja_main([SHA], ajuri=ajuri)
        self.assertEqual(rc, 1)
        self.assertNotIn("salaisuus", "\n".join(rivit))

    def test_avainta_ei_avata(self):
        avatut = []
        oikea_open = builtins.open

        def seuraava_open(polku, *a, **k):
            avatut.append(str(polku))
            return oikea_open(polku, *a, **k)
        with mock.patch.object(builtins, "open", seuraava_open), \
                mock.patch("io.open", seuraava_open), \
                mock.patch.object(os, "open", side_effect=AssertionError("os.open")):
            rc, rivit = self.aja_main([SHA])
        self.assertNotIn(self.avain, avatut)
        self.assertNotIn("KANARIA", "\n".join(rivit))


class TestAvain(AvainFixture):
    def test_oikeudet_liian_laajat(self):
        os.chmod(self.avain, 0o644)
        ok, syy = t.tarkista_avain(self.avain)
        self.assertFalse(ok)
        self.assertIn("644", syy)

    def test_puuttuu(self):
        self.assertEqual(t.tarkista_avain(self.avain + "x"), (False, "puuttuu"))

    def test_ok(self):
        self.assertTrue(t.tarkista_avain(self.avain)[0])


class TestModuulit(unittest.TestCase):
    def test_puuttuva_polku_antaa_vian_vain_tyyppi(self):
        with mock.patch.object(t, "MODUULIT", ("aivo.ei_ole_olemassa",)):
            ok, syy = t.tarkista_moduulit("/tmp")
        self.assertFalse(ok)
        self.assertIn("ModuleNotFoundError", syy)


if __name__ == "__main__":
    unittest.main()
