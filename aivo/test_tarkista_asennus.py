"""Testit aivo/tarkista_asennus.py:lle. Vaarennetty komentoajuri ja HTTP, ei verkkoa eika oikeaa systemd:ta."""
import builtins
import http.client
import io
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from aivo import tarkista_asennus as t, tiivista_tyokalu, tiivista_yksityinen, tiivistelma

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
        kw.setdefault("alueet", ())
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
        with mock.patch.object(t, "tarkista_moduulit", return_value=(True, "3 moduulia")):
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
                mock.patch.object(os, "open", side_effect=AssertionError("os.open")), \
                mock.patch.object(t, "tarkista_moduulit", return_value=(True, "3 moduulia")):
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

    def test_ei_oikeutta_tarkistaa_ei_kaada(self):
        with mock.patch.object(t.os, "stat", side_effect=PermissionError("salaisuus")):
            self.assertEqual(t.tarkista_avain(self.avain),
                             (False, "ei oikeutta tarkistaa (PermissionError)"))

    def test_ei_oikeutta_main_tulostaa_rivin(self):
        rivit = []
        with mock.patch.object(t.os, "stat", side_effect=PermissionError("salaisuus")), \
                mock.patch.object(t, "tarkista_moduulit", return_value=(True, "ok")):
            rc = t.main([SHA], ajuri=ajuri_ok, hae=http_ok, avaimet=("/etc/aivo/x",), alueet=(),
                        tulosta=rivit.append)
        self.assertEqual(rc, 1)
        self.assertIn("VIKA avain /etc/aivo/x: ei oikeutta tarkistaa (PermissionError)", rivit)
        self.assertNotIn("salaisuus", "\n".join(rivit))


class TestModuulit(unittest.TestCase):
    """Moduulit tarkistetaan lahdekoodista (compile), ei tuomalla: --koodi ratkaisee, ei sys.modules."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.koodi = self.tmp.name
        self.merkki = os.path.join(self.koodi, "ajettu.txt")

    def kirjoita(self, nimi, teksti):
        polku = os.path.join(self.koodi, *nimi.split(".")) + ".py"
        os.makedirs(os.path.dirname(polku), exist_ok=True)
        with open(polku, "w") as f:
            f.write(teksti)

    def puu(self, **poikkeukset):
        self.kirjoita("aivo.__init__", "")
        for nimi in t.MODUULIT:
            self.kirjoita(nimi, poikkeukset.get(nimi, "X = 1\n"))

    def test_kunnollinen_puu_ok(self):
        self.puu()
        self.assertEqual(t.tarkista_moduulit(self.koodi), (True, "3 moduulia"))

    def test_rikkinainen_chat_koodi_polussa_antaa_vian(self):
        # aivo on jo sys.modules-sanakirjassa (testi tuo sen), mutta --koodi ratkaisee silti.
        self.assertIn("aivo", sys.modules)
        self.puu(**{"aivo.chat": "def rikki(:\n"})
        ok, syy = t.tarkista_moduulit(self.koodi)
        self.assertFalse(ok)
        self.assertIn("aivo.chat (SyntaxError)", syy)

    def test_puuttuva_moduuli_koodi_polussa(self):
        self.puu()
        os.remove(os.path.join(self.koodi, "aivo", "tiivista.py"))
        ok, syy = t.tarkista_moduulit(self.koodi)
        self.assertFalse(ok)
        self.assertIn("aivo.tiivista (puuttuu)", syy)

    def test_tuontiaikaista_koodia_ei_ajeta(self):
        self.puu(**{"aivo.chat": "open(%r, 'w').write('x')\n" % self.merkki})
        self.assertTrue(t.tarkista_moduulit(self.koodi)[0])
        self.assertFalse(os.path.exists(self.merkki))

    def test_main_valittaa_koodi_polun_moduulitarkistukseen(self):
        self.puu(**{"aivo.tiivistelma": "def rikki(:\n"})
        rivit = []
        rc = t.main([SHA, "--koodi", self.koodi], ajuri=ajuri_ok, hae=http_ok,
                    avaimet=(), alueet=(), tulosta=rivit.append)
        self.assertEqual(rc, 1)
        self.assertTrue(any(r.startswith("VIKA moduulit") and "SyntaxError" in r for r in rivit))

    def test_sys_path_ei_muutu(self):
        self.puu()
        ennen = list(sys.path)
        t.tarkista_moduulit(self.koodi)
        self.assertEqual(sys.path, ennen)


class TestAja(unittest.TestCase):
    """Oletusajuri: subprocess.run korvataan, ei oikeaa aliprosessia."""

    def test_palauttaa_koodin_ja_siistityn_tulosteen(self):
        vastaus = mock.Mock(returncode=3, stdout="  inactive\n")
        with mock.patch.object(t.subprocess, "run", return_value=vastaus) as run:
            self.assertEqual(t.aja(["systemctl", "is-active", "x"]), (3, "inactive"))
        args, kw = run.call_args
        self.assertEqual(args[0], ["systemctl", "is-active", "x"])
        self.assertIs(kw["capture_output"], True)
        self.assertIs(kw["text"], True)
        self.assertEqual(kw["timeout"], t.AIKARAJA)

    def test_oskerror_antaa_127_ja_tyypin(self):
        with mock.patch.object(t.subprocess, "run", side_effect=FileNotFoundError("salaisuus")):
            self.assertEqual(t.aja(["x"]), (127, "FileNotFoundError"))

    def test_aikakatkaisu_antaa_127_ja_tyypin(self):
        with mock.patch.object(t.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(t.aja(["x"]), (127, "TimeoutExpired"))


class TestHttpGet(unittest.TestCase):
    """Oletus-HTTP: HTTPConnection korvataan, ei verkkoa."""

    def yhteys(self, tila=200, runko=b"{}"):
        vastaus = mock.Mock(status=tila)
        vastaus.read.return_value = runko
        yhteys = mock.Mock()
        yhteys.getresponse.return_value = vastaus
        return yhteys, vastaus

    def test_palauttaa_tilan_ja_rungon_200_tavuun_asti(self):
        yhteys, vastaus = self.yhteys(204, b"ok \xff")
        with mock.patch.object(t.http.client, "HTTPConnection", return_value=yhteys) as luo:
            tulos = t.http_get(8780, "/terve")
        self.assertEqual(tulos, (204, "ok \ufffd"))
        luo.assert_called_once_with("127.0.0.1", 8780, timeout=t.AIKARAJA)
        yhteys.request.assert_called_once_with("GET", "/terve")
        vastaus.read.assert_called_once_with(200)
        yhteys.close.assert_called_once_with()

    def test_yhteys_suljetaan_virheessakin(self):
        yhteys, _ = self.yhteys()
        yhteys.request.side_effect = ConnectionRefusedError("x")
        with mock.patch.object(t.http.client, "HTTPConnection", return_value=yhteys):
            with self.assertRaises(ConnectionRefusedError):
                t.http_get(1, "/")
        yhteys.close.assert_called_once_with()


class TestCommit(unittest.TestCase):
    def test_ajurin_virhe_antaa_vian_ja_polun(self):
        self.assertEqual(t.tarkista_commit(SHA, "/koodi", lambda k: (128, "")),
                         (False, "commitia ei saatu (/koodi)"))

    def test_ajurille_annetaan_git_rev_parse(self):
        kutsut = []

        def ajuri(komento):
            kutsut.append(komento)
            return 0, SHA
        t.tarkista_commit(SHA, "/koodi", ajuri)
        self.assertEqual(kutsut, [["git", "-C", "/koodi", "rev-parse", "HEAD"]])

    def test_tasan_seitseman_merkin_etuliite_kelpaa(self):
        self.assertEqual(t.tarkista_commit(SHA[:7], "k", lambda k: (0, SHA)), (True, SHA[:12]))

    def test_kuuden_merkin_etuliite_ei_kelpaa(self):
        self.assertFalse(t.tarkista_commit(SHA[:6], "k", lambda k: (0, SHA))[0])

    def test_onnistuessa_nayttaa_12_merkkia(self):
        ok, syy = t.tarkista_commit("abcdef1", "k", lambda k: (0, "abcdef1" + "2" * 33))
        self.assertTrue(ok)
        self.assertEqual(syy, "abcdef1" + "2" * 5)

    def test_vaara_commit_nayttaa_molemmat_12_merkkia(self):
        asennettu = "1" * 40
        odotettu = "2" * 40
        self.assertEqual(t.tarkista_commit(odotettu, "k", lambda k: (0, asennettu)),
                         (False, "asennettu %s, odotettu %s" % ("1" * 12, "2" * 12)))


class TestPalvelu(unittest.TestCase):
    def test_active_ja_koodi_nolla_on_ok(self):
        self.assertEqual(t.tarkista_palvelu("x", lambda k: (0, "active")), (True, "active"))

    def test_koodi_nolla_mutta_tila_ei_active_on_vika(self):
        self.assertEqual(t.tarkista_palvelu("x", lambda k: (0, "activating")),
                         (False, "activating"))

    def test_nollasta_poikkeava_koodi_vaikka_tila_active_on_vika(self):
        self.assertEqual(t.tarkista_palvelu("x", lambda k: (3, "active")), (False, "active"))

    def test_tyhja_tuloste_on_tuntematon(self):
        self.assertEqual(t.tarkista_palvelu("x", lambda k: (0, "")), (False, "tuntematon"))

    def test_kysyy_systemctl_is_active(self):
        kutsut = []
        t.tarkista_palvelu("aivo-chat", lambda k: kutsut.append(k) or (0, "active"))
        self.assertEqual(kutsut, [["systemctl", "is-active", "aivo-chat"]])


class TestAvainPolut(AvainFixture):
    def test_hakemisto_ei_ole_tavallinen_tiedosto(self):
        self.assertEqual(t.tarkista_avain(self.tmp.name), (False, "ei tavallinen tiedosto"))

    def test_muu_oserror_antaa_vain_tyypin(self):
        with mock.patch.object(t.os, "stat", side_effect=NotADirectoryError("salaisuus")):
            self.assertEqual(t.tarkista_avain(self.avain), (False, "NotADirectoryError"))

    def test_ok_nayttaa_oikeudet(self):
        self.assertEqual(t.tarkista_avain(self.avain), (True, "oikeudet 600"))


class TestTiivistysKansiot(unittest.TestCase):
    """Tilapaishakemisto: molemmat alueet, kansiot TIIVISTYS_ALIKANSIOT-vakiosta. Mitaan ei luoda eika muuteta."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.yks = os.path.join(self.tmp.name, "aivo-yksityinen")
        self.tyo = os.path.join(self.tmp.name, "aivo")
        for juuri in (self.yks, self.tyo):
            os.mkdir(juuri, 0o700)
            for k in tiivistelma.TIIVISTYS_ALIKANSIOT:
                os.mkdir(os.path.join(juuri, k), 0o700)
        self.omistaja = pwd.getpwuid(os.geteuid()).pw_name
        self.alueet = t.oletusalueet(self.yks, self.tyo)

    def aja(self, alueet=None):
        rivit = []
        with mock.patch.object(t, "tarkista_moduulit", return_value=(True, "3 moduulia")):
            rc = t.main([SHA], ajuri=ajuri_ok, hae=http_ok, avaimet=(), tulosta=rivit.append,
                        alueet=self.alueet if alueet is None else alueet)
        return rc, [r for r in rivit if " kansio " in r]

    def test_nimet_tulevat_tiivistysmoduulien_yhteisesta_vakiosta(self):
        self.assertIs(tiivista_tyokalu.KAYTETYT_ALIKANSIOT, tiivistelma.TIIVISTYS_ALIKANSIOT)
        self.assertIs(tiivista_yksityinen.KAYTETYT_ALIKANSIOT, tiivistelma.TIIVISTYS_ALIKANSIOT)
        self.assertEqual([a.nimi for a in self.alueet], ["yksityinen", "tyokalu"])

    def test_kaikki_kunnossa(self):
        rc, rivit = self.aja()
        self.assertEqual(rc, 0)
        self.assertEqual(len(rivit), 2 * len(tiivistelma.TIIVISTYS_ALIKANSIOT))
        self.assertTrue(all(r.startswith("OK   kansio ") and "oikeudet 700" in r for r in rivit), rivit)
        self.assertIn("OK   kansio yksityinen/chat: hakemisto, oikeudet 700 (%s/chat)" % self.yks, rivit)

    def test_kansio_puuttuu_antaa_vihjeen_eika_luo_mitaan(self):
        polku = os.path.join(self.tyo, "indeksi")
        os.rmdir(polku)
        rc, rivit = self.aja()
        self.assertEqual(rc, 1)
        odotettu = "VIKA kansio tyokalu/indeksi: puuttuu; korjaus: install -d -m 700 -o %s -g %s %s" % (
            self.omistaja, self.omistaja, polku)
        self.assertIn(odotettu, rivit)
        self.assertEqual(sum(r.startswith("VIKA") for r in rivit), 1)
        self.assertFalse(os.path.exists(polku))

    def test_tiedosto_kansion_paikalla(self):
        polku = os.path.join(self.yks, "tiivistelmat")
        os.rmdir(polku)
        with open(polku, "w") as f:
            f.write("x")
        ok, syy = t.tarkista_kansio(self.alueet[0], "tiivistelmat")
        self.assertFalse(ok)
        self.assertIn("ei ole hakemisto", syy)

    def test_linkki_kansion_paikalla(self):
        polku = os.path.join(self.yks, "chat")
        os.rmdir(polku)
        os.symlink(self.tmp.name, polku)
        ok, syy = t.tarkista_kansio(self.alueet[0], "chat")
        self.assertFalse(ok)
        self.assertIn("linkki", syy)

    def test_liian_avoimet_oikeudet_eivat_muutu(self):
        polku = os.path.join(self.tyo, "chat")
        for tila in (0o750, 0o701, 0o710, 0o777):
            os.chmod(polku, tila)
            ok, syy = t.tarkista_kansio(self.alueet[1], "chat")
            self.assertFalse(ok, oct(tila))
            self.assertIn("oikeudet %o" % tila, syy)
            self.assertIn("chmod 700 %s" % polku, syy)
            self.assertEqual(stat.S_IMODE(os.lstat(polku).st_mode), tila)

    def test_tiukempi_kuin_700_kelpaa(self):
        os.chmod(os.path.join(self.tyo, "chat"), 0o500)
        self.addCleanup(os.chmod, os.path.join(self.tyo, "chat"), 0o700)
        self.assertTrue(t.tarkista_kansio(self.alueet[1], "chat")[0])

    def test_juuri_puuttuu(self):
        juuri = os.path.join(self.tmp.name, "ei-ole")
        alueet = t.oletusalueet(juuri, self.tyo)
        rc, rivit = self.aja(alueet)
        self.assertEqual(rc, 1)
        yks = [r for r in rivit if "yksityinen/" in r]
        self.assertEqual(len(yks), len(tiivistelma.TIIVISTYS_ALIKANSIOT))
        for r in yks:
            self.assertTrue(r.startswith("VIKA"), r)
            self.assertIn("alueen juuri %s puuttuu" % juuri, r)
            self.assertIn("install -d -m 700 -o <omistaja> -g <omistaja> %s/" % juuri, r)
            self.assertIn("avoin paatos", r)
        self.assertFalse(os.path.exists(juuri))

    def test_tuntematon_uid_numerona(self):
        os.rmdir(os.path.join(self.yks, "chat"))
        with mock.patch.object(t.pwd, "getpwuid", side_effect=KeyError("x")):
            ok, syy = t.tarkista_kansio(self.alueet[0], "chat")
        self.assertFalse(ok)
        self.assertIn("-o %d -g %d " % (os.geteuid(), os.geteuid()), syy)

    def test_ei_oikeutta_ei_kaada(self):
        with mock.patch.object(t.os, "lstat", side_effect=PermissionError("salaisuus")):
            ok, syy = t.tarkista_kansio(self.alueet[0], "chat")
        self.assertFalse(ok)
        self.assertIn("PermissionError", syy)
        self.assertNotIn("salaisuus", syy)

    def test_kansioiden_sisaltoa_ei_lueta(self):
        with open(os.path.join(self.yks, "chat", "k.jsonl"), "w") as f:
            f.write("KANARIA-EI-SAA-NAKYA")
        kielto = AssertionError("sisaltoa ei saa lukea")
        with mock.patch.object(builtins, "open", side_effect=kielto), \
                mock.patch.object(os, "open", side_effect=kielto), \
                mock.patch.object(os, "listdir", side_effect=kielto), \
                mock.patch.object(os, "scandir", side_effect=kielto):
            tulokset = [t.tarkista_kansio(a, k) for a in self.alueet for k in tiivistelma.TIIVISTYS_ALIKANSIOT]
        self.assertTrue(all(ok for ok, _ in tulokset), tulokset)
        self.assertNotIn("KANARIA", repr(tulokset))

    def test_komentorivin_juuret(self):
        os.rmdir(os.path.join(self.yks, "indeksi"))
        rivit = []
        with mock.patch.object(t, "tarkista_moduulit", return_value=(True, "3 moduulia")):
            rc = t.main([SHA, "--yksityinen-juuri", self.yks, "--tyokalu-juuri", self.tyo], ajuri=ajuri_ok,
                        hae=http_ok, avaimet=(), tulosta=rivit.append)
        self.assertEqual(rc, 1)
        viat = [r for r in rivit if r.startswith("VIKA")]
        self.assertEqual(len(viat), 1)
        self.assertTrue(viat[0].startswith("VIKA kansio yksityinen/indeksi: puuttuu; korjaus: install -d"), viat)


class TestOhje(unittest.TestCase):
    def test_help_nayttaa_docstringin_ensimmainen_rivi(self):
        ulos = io.StringIO()
        with mock.patch.object(sys, "stdout", ulos), self.assertRaises(SystemExit) as e:
            t.main(["--help"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("Aivon asennuksen tilatarkistus (vain luku). Stdlib.", ulos.getvalue())
        self.assertNotIn("Kaytto:", ulos.getvalue())


if __name__ == "__main__":
    unittest.main()
