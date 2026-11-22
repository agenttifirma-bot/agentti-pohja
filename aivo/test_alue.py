"""Suorat testit moduulille aivo/alue.py: alikansioiden nimet, polkujen rajaus, symlinkit ja oikeustarkistukset.

Testit kuvaavat nykyista kayttaytymista sellaisenaan. Ne eivat muuta sallittuja polkuja eivatka rajauksia.
Testit kayttavat vain tilapaishakemistoja eika koske oikeaan tilaan.
"""

import dataclasses
import os
import stat
import tempfile
import unittest
from pathlib import Path

from aivo import alue
from aivo.alue import Alue, AlueVirhe, tarkista_erottelu, tarkista_hakemisto, tarkista_tiedostot


class TilapaisTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(os.path.realpath(self._tmp.name))

    def moodi(self, p):
        return stat.S_IMODE(os.lstat(p).st_mode)


class AlikansionNimiTesti(unittest.TestCase):
    def test_kelvolliset_nimet(self):
        for nimi in ("a", "abc", "a-b", "a1", "x" + "y" * 30):
            Alue("t", "/tmp/x", (nimi,))

    def test_kelvottomat_nimet(self):
        for nimi in ("", "A", "1a", "-a", "a_b", "a/b", "..", ".", "a.b", "a b", "x" + "y" * 31, "\u00e4"):
            with self.assertRaises(AlueVirhe, msg=repr(nimi)):
                Alue("t", "/tmp/x", (nimi,))

    def test_nimi_ei_voi_olla_muu_kuin_merkkijono(self):
        for arvo in (1, None, b"abc"):
            with self.assertRaises(AlueVirhe):
                Alue("t", "/tmp/x", (arvo,))


class AlueRakenneTesti(unittest.TestCase):
    def test_juuren_pitaa_olla_absoluuttinen(self):
        for juuri in ("tila", "./tila", "../tila", ""):
            with self.assertRaises(AlueVirhe, msg=repr(juuri)):
                Alue("t", juuri, ("a",))

    def test_alikansiot_eivat_saa_toistua(self):
        with self.assertRaises(AlueVirhe):
            Alue("t", "/tmp/x", ("a", "b", "a"))

    def test_git_alikansioiden_pitaa_kuulua_alikansioihin(self):
        with self.assertRaises(AlueVirhe):
            Alue("t", "/tmp/x", ("a",), git_alikansiot=("b",))
        a = Alue("t", "/tmp/x", ("a", "b"), git_alikansiot=["b"])
        self.assertEqual(a.git_alikansiot, ("b",))

    def test_kentat_normalisoidaan(self):
        a = Alue("t", "/tmp/x", ["a", "b"])
        self.assertEqual(a.alikansiot, ("a", "b"))
        self.assertEqual(a.git_alikansiot, ())
        self.assertIsInstance(a.juuri, Path)

    def test_alue_on_jaadytetty(self):
        a = Alue("t", "/tmp/x", ("a",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.nimi = "u"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.juuri = Path("/tmp/y")

    def test_juuri_sailyy_kirjaimellisena(self):
        # Path ei kutista '..'-osaa: juuri sailyy kirjaimellisena. Realpath tehdaan vasta sisaltaa()-kutsussa.
        a = Alue("t", "/tmp/x/../y", ("a",))
        self.assertEqual(str(a.juuri), "/tmp/x/../y")


class PolkuTesti(unittest.TestCase):
    def setUp(self):
        self.a = Alue("t", "/tmp/juuri", ("yksi", "kaksi"))

    def test_sallittu_alikansio(self):
        self.assertEqual(self.a.polku("yksi"), Path("/tmp/juuri/yksi"))
        self.assertEqual(self.a.polku("kaksi"), Path("/tmp/juuri/kaksi"))

    def test_vieras_ja_vaarat_nimet_hylataan(self):
        for nimi in ("kolme", "..", "../yksi", "yksi/..", "yksi/", "/tmp/juuri/yksi", "/etc", "", "Yksi", "yksi\n",
                     ".", "yksi/x", None, 1):
            with self.assertRaises(AlueVirhe, msg=repr(nimi)):
                self.a.polku(nimi)

    def test_virheviesti_ei_sisalla_polkua(self):
        with self.assertRaises(AlueVirhe) as ctx:
            self.a.polku("/etc/passwd")
        self.assertNotIn("/etc/passwd", str(ctx.exception))
        self.assertIn("t", str(ctx.exception))


class SisaltaaTesti(TilapaisTesti):
    def setUp(self):
        super().setUp()
        self.juuri = self.tmp / "juuri"
        self.juuri.mkdir()
        (self.juuri / "yksi").mkdir()
        self.ulos = self.tmp / "ulos"
        self.ulos.mkdir()
        (self.ulos / "salaisuus.txt").write_text("x")
        self.a = Alue("t", self.juuri, ("yksi",))

    def test_juuri_ja_sen_alapolut(self):
        self.assertIs(self.a.sisaltaa(self.juuri), True)
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi"), True)
        self.assertIs(self.a.sisaltaa(str(self.juuri / "yksi" / "tiedosto.txt")), True)

    def test_olematon_polku_alueen_alla_on_sisalla(self):
        self.assertIs(self.a.sisaltaa(self.juuri / "ei" / "ole" / "olemassa"), True)

    def test_ulkopuoliset_polut(self):
        self.assertIs(self.a.sisaltaa(self.ulos), False)
        self.assertIs(self.a.sisaltaa(self.ulos / "salaisuus.txt"), False)
        self.assertIs(self.a.sisaltaa("/"), False)
        self.assertIs(self.a.sisaltaa(self.tmp), False)

    def test_samanniminen_etuliite_ei_ole_sisalla(self):
        sisar = self.tmp / "juuri2"
        sisar.mkdir()
        self.assertIs(self.a.sisaltaa(sisar), False)
        self.assertIs(self.a.sisaltaa(str(self.juuri) + "x"), False)

    def test_pisteet_normalisoidaan(self):
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / ".." / ".." / "ulos"), False)
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / ".." / "yksi"), True)
        self.assertIs(self.a.sisaltaa(self.juuri / ".." / "ulos" / "salaisuus.txt"), False)
        self.assertIs(self.a.sisaltaa(str(self.juuri) + "/yksi/../../juuri/yksi"), True)

    def test_symlink_alueen_ulkopuolelle(self):
        os.symlink(self.ulos, self.juuri / "yksi" / "linkki")
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "linkki"), False)
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "linkki" / "salaisuus.txt"), False)

    def test_symlink_tiedostoon_alueen_ulkopuolelle(self):
        os.symlink(self.ulos / "salaisuus.txt", self.juuri / "yksi" / "tiedosto")
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "tiedosto"), False)

    def test_riippuva_symlink_ulos(self):
        os.symlink(self.ulos / "ei-ole", self.juuri / "yksi" / "riippuva")
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "riippuva"), False)

    def test_symlink_alueen_sisalla_pysyy_sisalla(self):
        (self.juuri / "yksi" / "oikea").mkdir()
        os.symlink(self.juuri / "yksi" / "oikea", self.juuri / "yksi" / "lyhenne")
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "lyhenne"), True)

    def test_symlink_kautta_tuleva_juuri_avataan(self):
        linkki = self.tmp / "juurilinkki"
        os.symlink(self.juuri, linkki)
        a = Alue("t", linkki, ("yksi",))
        self.assertIs(a.sisaltaa(self.juuri / "yksi"), True)
        self.assertIs(a.sisaltaa(linkki / "yksi"), True)
        self.assertIs(a.sisaltaa(self.ulos), False)

    def test_symlinkkiketju_ulos(self):
        os.symlink(self.ulos, self.juuri / "vali")
        os.symlink(self.juuri / "vali", self.juuri / "yksi" / "ketju")
        self.assertIs(self.a.sisaltaa(self.juuri / "yksi" / "ketju"), False)


class TarkistaHakemistoTesti(TilapaisTesti):
    def test_luo_kansion_oikeuksilla_0700_ilman_korjausta(self):
        # korjaa=False: jos mkdir ei asettaisi 0700:aa itse, tarkistus kaatuisi (umask 022 sallii 0o700:n sellaisenaan).
        p = tarkista_hakemisto(self.tmp / "uusi", luo=True, korjaa=False)
        self.assertEqual(p, self.tmp / "uusi")
        self.assertEqual(self.moodi(p), 0o700)

    def test_luo_ylakansiot(self):
        p = tarkista_hakemisto(self.tmp / "a" / "b" / "c")
        self.assertTrue(p.is_dir())
        self.assertEqual(self.moodi(p), 0o700)

    def test_olemassa_oleva_kansio_kelpaa_uudelleen(self):
        tarkista_hakemisto(self.tmp / "k")
        tarkista_hakemisto(self.tmp / "k")

    def test_luo_oletus_on_tosi(self):
        p = tarkista_hakemisto(self.tmp / "oletus")
        self.assertTrue(p.is_dir())

    def test_luo_epatosi_ei_luo_kansiota(self):
        with self.assertRaises(AlueVirhe):
            tarkista_hakemisto(self.tmp / "puuttuu", luo=False)
        self.assertFalse((self.tmp / "puuttuu").exists())

    def test_luonti_epaonnistuu_siististi(self):
        (self.tmp / "tiedosto").write_text("x")
        with self.assertRaises(AlueVirhe) as ctx:
            tarkista_hakemisto(self.tmp / "tiedosto" / "ala")
        self.assertIn("NotADirectoryError", str(ctx.exception))
        self.assertNotIn(str(self.tmp), str(ctx.exception))

    def test_tavallinen_tiedosto_ei_kelpaa_kansioksi(self):
        t = self.tmp / "tiedosto"
        t.write_text("x")
        t.chmod(0o600)
        with self.assertRaises(AlueVirhe):
            tarkista_hakemisto(t, luo=False)
        with self.assertRaises(AlueVirhe):
            tarkista_hakemisto(t)

    def test_symlink_kansioon_hylataan(self):
        oikea = self.tmp / "oikea"
        oikea.mkdir(mode=0o700)
        linkki = self.tmp / "linkki"
        os.symlink(oikea, linkki)
        for luo in (True, False):
            with self.assertRaises(AlueVirhe):
                tarkista_hakemisto(linkki, luo=luo)

    def test_riippuva_symlink_hylataan(self):
        linkki = self.tmp / "riippuva"
        os.symlink(self.tmp / "ei-ole", linkki)
        with self.assertRaises(AlueVirhe):
            tarkista_hakemisto(linkki, luo=False)

    def test_laajat_oikeudet_korjataan(self):
        for moodi in (0o755, 0o750, 0o705, 0o770, 0o701, 0o777, 0o710, 0o740):
            k = self.tmp / ("k%o" % moodi)
            k.mkdir()
            k.chmod(moodi)
            tarkista_hakemisto(k, luo=False)
            self.assertEqual(self.moodi(k), 0o700, oct(moodi))

    def test_laajat_oikeudet_ilman_korjausta_hylataan(self):
        # Maski 0o077: jokainen ryhma- ja muu-bitti kuuluu rajaan (myos 0o010 ja 0o001, jotka ovat maskin rajabitteja).
        for moodi in (0o755, 0o750, 0o705, 0o701, 0o710, 0o740, 0o704, 0o770, 0o777):
            k = self.tmp / ("n%o" % moodi)
            k.mkdir()
            k.chmod(moodi)
            with self.assertRaises(AlueVirhe, msg=oct(moodi)):
                tarkista_hakemisto(k, luo=False, korjaa=False)
            self.assertEqual(self.moodi(k), moodi)

    def test_omistajan_oikeudet_eivat_aiheuta_virhetta(self):
        for moodi in (0o700, 0o500, 0o300, 0o100):
            k = self.tmp / ("o%o" % moodi)
            k.mkdir()
            k.chmod(moodi)
            tarkista_hakemisto(k, luo=False, korjaa=False)
            k.chmod(0o700)

    def test_korjaa_oletus_on_tosi(self):
        k = self.tmp / "k"
        k.mkdir()
        k.chmod(0o755)
        tarkista_hakemisto(k, luo=False)
        self.assertEqual(self.moodi(k), 0o700)

    def test_vieras_omistaja_hylataan(self):
        from unittest import mock
        k = self.tmp / "k"
        k.mkdir(mode=0o700)
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(AlueVirhe):
                tarkista_hakemisto(k, luo=False)

    def test_chmod_epaonnistuminen_hylataan(self):
        from unittest import mock
        k = self.tmp / "k"
        k.mkdir()
        k.chmod(0o755)
        with mock.patch("aivo.alue.os.chmod", side_effect=PermissionError):
            with self.assertRaises(AlueVirhe):
                tarkista_hakemisto(k, luo=False)

    def test_virheviesteissa_ei_polkua(self):
        with self.assertRaises(AlueVirhe) as ctx:
            tarkista_hakemisto(self.tmp / "puuttuu", luo=False)
        self.assertNotIn(str(self.tmp), str(ctx.exception))


class TarkistaTiedostotTesti(TilapaisTesti):
    def setUp(self):
        super().setUp()
        self.k = self.tmp / "k"
        self.k.mkdir(mode=0o700)

    def test_tyhja_kansio_kelpaa(self):
        tarkista_tiedostot(self.k)

    def test_tavalliset_tiedostot_kelpaavat_ja_oikeudet_korjataan(self):
        for moodi in (0o644, 0o640, 0o604, 0o666, 0o660, 0o606, 0o610, 0o601):
            t = self.k / ("t%o" % moodi)
            t.write_text("x")
            t.chmod(moodi)
        tarkista_tiedostot(self.k)
        for t in self.k.iterdir():
            self.assertEqual(self.moodi(t), 0o600, t.name)

    def test_omistajan_oikeudet_eivat_muutu(self):
        t = self.k / "t"
        t.write_text("x")
        t.chmod(0o400)
        tarkista_tiedostot(self.k)
        self.assertEqual(self.moodi(t), 0o400)

    def test_symlink_tiedostoon_hylataan(self):
        (self.tmp / "ulos.txt").write_text("x")
        os.symlink(self.tmp / "ulos.txt", self.k / "linkki")
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)

    def test_riippuva_symlink_hylataan(self):
        os.symlink(self.tmp / "ei-ole", self.k / "linkki")
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)

    def test_alikansio_hylataan(self):
        (self.k / "ala").mkdir()
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)

    def test_fifo_hylataan(self):
        os.mkfifo(self.k / "putki")
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)

    def test_puuttuva_kansio(self):
        with self.assertRaises(AlueVirhe) as ctx:
            tarkista_tiedostot(self.tmp / "ei-ole")
        self.assertIn("FileNotFoundError", str(ctx.exception))
        self.assertNotIn(str(self.tmp), str(ctx.exception))

    def test_git_kansio_hylataan_oletuksena(self):
        (self.k / ".git").mkdir()
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k, salli_git=False)

    def test_git_kansio_sallitaan_vain_pyydettaessa(self):
        (self.k / ".git").mkdir(mode=0o755)
        (self.k / ".git" / "HEAD").write_text("x")
        tarkista_tiedostot(self.k, salli_git=True)
        # .git:n oikeuksia ja sisaltoa ei kosketa
        self.assertEqual(self.moodi(self.k / ".git"), 0o755)

    def test_git_symlink_hylataan_vaikka_salli_git(self):
        (self.tmp / "oikea-git").mkdir()
        os.symlink(self.tmp / "oikea-git", self.k / ".git")
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k, salli_git=True)

    def test_git_tiedosto_kasitellaan_tavallisena_tiedostona(self):
        # .git tiedostona (gitdir-osoitin) ei ole kansio, joten se kay tavallisesta tiedostosta.
        (self.k / ".git").write_text("gitdir: /muu")
        tarkista_tiedostot(self.k, salli_git=True)

    def test_muu_alikansio_hylataan_vaikka_salli_git(self):
        (self.k / ".git").mkdir()
        (self.k / "muu").mkdir()
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k, salli_git=True)

    def test_vieras_omistaja_hylataan(self):
        from unittest import mock
        (self.k / "t").write_text("x")
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(AlueVirhe):
                tarkista_tiedostot(self.k)

    def test_vieras_omistaja_git_kansio_hylataan(self):
        from unittest import mock
        (self.k / ".git").mkdir()
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(AlueVirhe):
                tarkista_tiedostot(self.k, salli_git=True)

    def test_chmod_epaonnistuminen_hylataan(self):
        from unittest import mock
        t = self.k / "t"
        t.write_text("x")
        t.chmod(0o644)
        with mock.patch("aivo.alue.os.chmod", side_effect=PermissionError):
            with self.assertRaises(AlueVirhe):
                tarkista_tiedostot(self.k)

    def test_tiedostot_kaydaan_nimijarjestyksessa(self):
        # Ensimmainen virheellinen nimi (aakkosjarjestyksessa) ratkaisee, mutta virhe nousee joka tapauksessa.
        (self.k / "a").write_text("x")
        (self.k / "z").mkdir()
        with self.assertRaises(AlueVirhe):
            tarkista_tiedostot(self.k)


class ValmistaTesti(TilapaisTesti):
    def setUp(self):
        super().setUp()
        self.juuri = self.tmp / "juuri"
        self.a = Alue("t", self.juuri, ("yksi", "kaksi"), git_alikansiot=("kaksi",))

    def test_luo_juuren_ja_kaikki_alikansiot(self):
        tulos = self.a.valmista()
        self.assertEqual(set(tulos), {"yksi", "kaksi"})
        self.assertEqual(tulos["yksi"], self.juuri / "yksi")
        for p in tulos.values():
            self.assertEqual(self.moodi(p), 0o700)
        self.assertEqual(self.moodi(self.juuri), 0o700)

    def test_osajoukko_luo_vain_annetut(self):
        tulos = self.a.valmista(alikansiot=["yksi"])
        self.assertEqual(set(tulos), {"yksi"})
        self.assertFalse((self.juuri / "kaksi").exists())

    def test_tyhja_tai_vieras_osajoukko_hylataan(self):
        for osa in ([], (), ["kolme"], ["yksi", "kolme"], ["..", "yksi"]):
            with self.assertRaises(AlueVirhe, msg=repr(osa)):
                self.a.valmista(alikansiot=osa)
        self.assertFalse(self.juuri.exists())

    def test_luo_epatosi_vaatii_olemassa_olevat(self):
        with self.assertRaises(AlueVirhe):
            self.a.valmista(luo=False)
        self.a.valmista()
        self.a.valmista(luo=False)

    def test_laajat_oikeudet_korjataan(self):
        self.a.valmista()
        (self.juuri / "yksi").chmod(0o755)
        t = self.juuri / "yksi" / "t"
        t.write_text("x")
        t.chmod(0o644)
        self.a.valmista(luo=False)
        self.assertEqual(self.moodi(self.juuri / "yksi"), 0o700)
        self.assertEqual(self.moodi(t), 0o600)

    def test_symlink_alikansiona_hylataan(self):
        self.juuri.mkdir(mode=0o700)
        (self.tmp / "ulos").mkdir(mode=0o700)
        os.symlink(self.tmp / "ulos", self.juuri / "yksi")
        with self.assertRaises(AlueVirhe):
            self.a.valmista()

    def test_symlink_juurena_hylataan(self):
        (self.tmp / "oikea").mkdir(mode=0o700)
        os.symlink(self.tmp / "oikea", self.juuri)
        with self.assertRaises(AlueVirhe):
            self.a.valmista()

    def test_git_sallitaan_vain_git_alikansiossa(self):
        self.a.valmista()
        (self.juuri / "kaksi" / ".git").mkdir()
        self.a.valmista(luo=False, alikansiot=["kaksi"])
        (self.juuri / "yksi" / ".git").mkdir()
        with self.assertRaises(AlueVirhe):
            self.a.valmista(luo=False, alikansiot=["yksi"])

    def test_osajoukko_ei_tarkista_muita(self):
        self.a.valmista()
        os.symlink(self.tmp, self.juuri / "yksi" / "linkki")
        self.a.valmista(luo=False, alikansiot=["kaksi"])
        with self.assertRaises(AlueVirhe):
            self.a.valmista(luo=False, alikansiot=["yksi"])


class ErotteluTesti(TilapaisTesti):
    def alue_polulla(self, nimi, *osat):
        return Alue(nimi, self.tmp.joinpath(*osat), ("a",))

    def test_erilliset_alueet_kelpaavat(self):
        tarkista_erottelu(self.alue_polulla("x", "yksi"), self.alue_polulla("y", "kaksi"))

    def test_samanniminen_etuliite_ei_ole_paallekkainen(self):
        tarkista_erottelu(self.alue_polulla("x", "yksi"), self.alue_polulla("y", "yksi2"))

    def test_sama_kansio_hylataan(self):
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(self.alue_polulla("x", "yksi"), self.alue_polulla("y", "yksi"))

    def test_sisakkaiset_hylataan_molempiin_suuntiin(self):
        ulko = self.alue_polulla("x", "yksi")
        sisa = self.alue_polulla("y", "yksi", "ala")
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(ulko, sisa)
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(sisa, ulko)

    def test_symlink_avataan(self):
        (self.tmp / "oikea").mkdir()
        os.symlink(self.tmp / "oikea", self.tmp / "linkki")
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(self.alue_polulla("x", "oikea"), self.alue_polulla("y", "linkki"))
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(self.alue_polulla("x", "oikea"), self.alue_polulla("y", "linkki", "ala"))

    def test_pisteet_avataan(self):
        with self.assertRaises(AlueVirhe):
            tarkista_erottelu(self.alue_polulla("x", "yksi"), self.alue_polulla("y", "kaksi", "..", "yksi"))

    def test_virheviesti_nimeaa_alueet_mutta_ei_polkuja(self):
        with self.assertRaises(AlueVirhe) as ctx:
            tarkista_erottelu(self.alue_polulla("alfa", "yksi"), self.alue_polulla("beeta", "yksi"))
        self.assertIn("alfa", str(ctx.exception))
        self.assertIn("beeta", str(ctx.exception))
        self.assertNotIn(str(self.tmp), str(ctx.exception))


class AlikansioReTesti(unittest.TestCase):
    def test_vakio(self):
        self.assertEqual(alue.GIT_KANSIO, ".git")
        self.assertIsNotNone(alue.ALIKANSIO_RE.match("abc"))


if __name__ == "__main__":
    unittest.main()
