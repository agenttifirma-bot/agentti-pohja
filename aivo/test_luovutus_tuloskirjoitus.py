"""Luovutuspaketin tuloksen kirjoitus tulosrepoon (aivo/luovutuspaketti.py: jasenna_palan_otsake, kirjoita_tulos,
alikomento kirjoita-tulos). Vain stdlib, ei verkkoa."""
import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path

from aivo import luovutus, luovutuspaketti as lp
from aivo.test_luovutuspaketti import PakettiPohja
from aivo.yksityinen import YksityinenVirhe

T = "0123456789ab"


class JasennysTesti(unittest.TestCase):
    def test_jasennys_ja_palan_teksti_ovat_kaanteiset(self):
        for t, nimi, n, teksti in ((T, "Mittari X", 1, "Rakenna osa A.\n"), ("abcdefabcdef", "N", 99, ""),
                                   (T, "Nimi (v2): a.b,c-d", 10, "rivi 1\nrivi 2\n"),
                                   (T, "\u00c4\u00e4ni\u00f6", 7, "<!-- luovutuspaketti tunnus=%s pala=3 nimi=x -->\n" % T)):
            self.assertEqual(lp.jasenna_palan_otsake(lp.palan_teksti(t, nimi, n, teksti)), (t, n, nimi))
            self.assertEqual(lp.palan_teksti(t, nimi, n, teksti), lp.palan_otsake(t, nimi, n) + teksti)
        # muoto pysyy samana kuin ennen (saapuneet-tiedostot ja muut testit nojaavat siihen)
        self.assertEqual(lp.palan_teksti(T, "Mittari X", 2, "x"), "<!-- luovutuspaketti tunnus=%s pala=2 nimi=Mittari X -->\nx" % T)

    def test_saapunut_tiedosto_kelpaa_sellaisenaan(self):
        sisalto = lp.palan_teksti(T, "N", 3, "teksti\n")
        raaka = luovutus.saapunut_teksti("fedcba987654", "0" * 64, "2026-12-07T08:00:00+00:00", sisalto)
        self.assertEqual(lp.jasenna_palan_otsake(raaka), (T, 3, "N"))

    def test_rikkinainen_otsake_hylataan(self):
        hyva = lp.palan_teksti(T, "N", 3, "x\n")
        for paha in ("", "x", hyva[1:], " " + hyva, hyva.replace("pala=3", "pala=0"), hyva.replace("pala=3", "pala=03"),
                     hyva.replace("pala=3", "pala=100"), hyva.replace("pala=3", "pala=x"), hyva.replace(T, T.upper()),
                     hyva.replace(T, T[:-1]), hyva.replace(T, "../" + T[3:]), hyva.replace(" -->\n", " -->"),
                     hyva.replace("tunnus=", "tunnus = "), "teksti\n" + hyva, None, 5, b"x"):
            with self.assertRaises(YksityinenVirhe, msg=repr(paha)):
                lp.jasenna_palan_otsake(paha)


class KirjoitusTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.juuri = Path(self.tmp.name)
        self.repo = self.juuri / "tulosrepo"
        self.repo.mkdir()
        self.kirjasto = self.juuri / "kirjasto"
        self.kirjasto.mkdir()

    def test_kirjoitus_oikeaan_polkuun_ja_oikeudet(self):
        r = lp.kirjoita_tulos(str(self.repo), T, 2, "Valmis.\n", kielletyt=[str(self.kirjasto)])
        self.assertEqual(r, T + "/pala-2.md")
        self.assertEqual(lp._tulos_polku(str(self.repo), T, 2), self.repo / T / "pala-2.md")
        self.assertEqual((self.repo / r).read_text(encoding="utf-8"), "Valmis.\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.repo / r).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.repo / T).st_mode) & 0o077, 0)
        self.assertEqual(sorted(os.listdir(self.repo / T)), ["pala-2.md"])          # ei valiaikaistiedostoja

    def test_olemassa_olevaa_ei_korvata_ilman_lippua(self):
        lp.kirjoita_tulos(str(self.repo), T, 1, "eka\n")
        with self.assertRaises(YksityinenVirhe):
            lp.kirjoita_tulos(str(self.repo), T, 1, "toka\n")
        self.assertEqual((self.repo / T / "pala-1.md").read_text(), "eka\n")
        lp.kirjoita_tulos(str(self.repo), T, 1, "toka\n", korvaa=True)
        self.assertEqual((self.repo / T / "pala-1.md").read_text(), "toka\n")
        self.assertEqual(sorted(os.listdir(self.repo / T)), ["pala-1.md"])

    def test_liian_suuri_ja_tyhja_hylataan(self):
        lp.kirjoita_tulos(str(self.repo), T, 1, b"a" * lp.TULOS_YLARAJA)
        for paha in (b"a" * (lp.TULOS_YLARAJA + 1), "\u00e4" * (lp.TULOS_YLARAJA // 2 + 1), "", b"", None):
            with self.assertRaises(YksityinenVirhe):
                lp.kirjoita_tulos(str(self.repo), T, 2, paha)
        self.assertFalse((self.repo / T / "pala-2.md").exists())

    def test_symlinkki_hylataan(self):
        ulkona = self.juuri / "ulkona.md"
        ulkona.write_text("ennallaan\n")
        (self.repo / T).mkdir()
        os.symlink(ulkona, self.repo / T / "pala-1.md")
        for korvaa in (False, True):
            with self.assertRaises(YksityinenVirhe):
                lp.kirjoita_tulos(str(self.repo), T, 1, "x\n", korvaa=korvaa)
        self.assertEqual(ulkona.read_text(), "ennallaan\n")
        # symlinkki pakettikansiona ja tulosrepona
        muu = self.juuri / "muu"
        muu.mkdir()
        os.symlink(muu, self.repo / "abcdefabcdef")
        with self.assertRaises(YksityinenVirhe):
            lp.kirjoita_tulos(str(self.repo), "abcdefabcdef", 1, "x\n")
        os.symlink(self.repo, self.juuri / "linkkirepo")
        with self.assertRaises(YksityinenVirhe):
            lp.kirjoita_tulos(str(self.juuri / "linkkirepo"), "abcdefabcdef", 2, "x\n")
        self.assertEqual(os.listdir(muu), [])

    def test_tulosrepo_kirjaston_alueella_hylataan(self):
        sisalla = self.kirjasto / "tulokset"
        sisalla.mkdir()
        for paha in (self.kirjasto, sisalla, self.juuri):
            with self.assertRaises(YksityinenVirhe, msg=str(paha)):
                lp.kirjoita_tulos(str(paha), T, 1, "x\n", kielletyt=[str(self.kirjasto)])
        self.assertEqual(sorted(os.listdir(self.kirjasto)), ["tulokset"])
        for paha in (None, "", str(self.juuri / "puuttuu")):
            with self.assertRaises(YksityinenVirhe):
                lp.kirjoita_tulos(paha, T, 1, "x\n")

    def test_virheellinen_tunnus_tai_numero_hylataan(self):
        for pt, n in (("../" + T[3:], 1), (T.upper(), 1), ("", 1), (T, 0), (T, 100), (T, True), (T, "1")):
            with self.assertRaises(YksityinenVirhe, msg=(pt, n)):
                lp.kirjoita_tulos(str(self.repo), pt, n, "x\n")
        self.assertEqual(os.listdir(self.repo), [])

    def test_ei_lue_eika_listaa_muita_tiedostoja(self):
        # muut tulosrepon tiedostot ovat lukukelvottomia: kirjoitus onnistuu silti eika koske niihin
        (self.repo / T).mkdir()
        muu = self.repo / T / "pala-9.md"
        muu.write_text("toinen\n")
        os.chmod(muu, 0)
        self.addCleanup(os.chmod, muu, 0o600)
        alkuperainen = os.listdir
        kutsut = []

        def vahtii(*a, **k):
            kutsut.append(a)
            return alkuperainen(*a, **k)
        os.listdir = vahtii
        try:
            lp.kirjoita_tulos(str(self.repo), T, 1, "x\n")
        finally:
            os.listdir = alkuperainen
        self.assertEqual(kutsut, [])
        self.assertEqual(stat.S_IMODE(os.lstat(muu).st_mode), 0)


class KomentoTesti(KirjoitusTesti):
    def aja(self, *argv):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            rc = lp.main(list(argv))
        return rc, ulos.getvalue(), virhe.getvalue()

    def tiedostot(self, n=4, tulos="Tulos.\n"):
        pala = self.juuri / "pala.md"
        pala.write_text(lp.palan_teksti(T, "Mittari X", n, "Rakenna.\n"), encoding="utf-8")
        tul = self.juuri / "tulos.md"
        tul.write_text(tulos, encoding="utf-8")
        return str(pala), str(tul)

    def test_komento_tulostaa_vain_suhteellisen_polun(self):
        pala, tul = self.tiedostot()
        rc, ulos, virhe = self.aja("kirjoita-tulos", str(self.repo), pala, tul, "--kirjasto", str(self.kirjasto))
        self.assertEqual((rc, ulos, virhe), (0, T + "/pala-4.md\n", ""))
        self.assertEqual((self.repo / T / "pala-4.md").read_text(), "Tulos.\n")

    def test_komennon_virheesta_vain_tyypin_nimi(self):
        pala, tul = self.tiedostot(tulos="SALAINEN-TULOS-12\n")
        self.aja("kirjoita-tulos", str(self.repo), pala, tul, "--kirjasto", str(self.kirjasto))
        for argv in (("kirjoita-tulos", str(self.repo), pala, tul, "--kirjasto", str(self.kirjasto)),     # olemassa
                     ("kirjoita-tulos", str(self.kirjasto), pala, tul, "--kirjasto", str(self.kirjasto)),  # kirjastossa
                     ("kirjoita-tulos", str(self.repo), tul, tul, "--kirjasto", str(self.kirjasto)),       # ei otsaketta
                     ("kirjoita-tulos", str(self.repo), pala, str(self.juuri / "puuttuu"), "--kirjasto", str(self.kirjasto))):
            rc, ulos, virhe = self.aja(*argv)
            self.assertEqual((rc, ulos), (1, ""), argv)
            self.assertRegex(virhe, r"\A[A-Za-z]+\n\Z")
            self.assertNotIn("SALAINEN", virhe)
        rc, ulos, virhe = self.aja("kirjoita-tulos", str(self.repo), pala, tul, "--kirjasto", str(self.kirjasto), "--korvaa")
        self.assertEqual((rc, ulos), (0, T + "/pala-4.md\n"))

    def test_komento_ei_seuraa_symlinkkia_lahdetiedostossa(self):
        pala, tul = self.tiedostot()
        os.symlink(tul, self.juuri / "linkki.md")
        rc, ulos, virhe = self.aja("kirjoita-tulos", str(self.repo), pala, str(self.juuri / "linkki.md"),
                                   "--kirjasto", str(self.kirjasto))
        self.assertEqual((rc, ulos), (1, ""))

    def test_liian_suuri_tulostiedosto_hylataan(self):
        pala, tul = self.tiedostot(tulos="a" * (lp.TULOS_YLARAJA + 1))
        rc, ulos, virhe = self.aja("kirjoita-tulos", str(self.repo), pala, tul, "--kirjasto", str(self.kirjasto))
        self.assertEqual((rc, ulos), (1, ""))
        self.assertFalse((self.repo / T).exists() and os.listdir(self.repo / T))


class PaluuKetjuTesti(PakettiPohja):
    """Hyvaksytyn paketin saapunut pala -> kirjoita-tulos -> tarkista_paluut ja lue_tulos loytavat tuloksen."""

    def test_kirjoitettu_tulos_loytyy_paluusta_ja_luvusta(self):
        repo = Path(self.tmp.name) / "tulosrepo"
        repo.mkdir()
        kid, t, v = self.paketti()
        self.hyvaksy_p(kid, t, "kyll\u00e4 " + self.hae(kid, t)["sha8"])
        pid = lp.palan_tunnus(t, 2)
        palatiedosto = self.saap / (pid + ".md")
        self.assertEqual(lp.jasenna_palan_otsake(palatiedosto.read_text(encoding="utf-8"))[:2], (t, 2))
        tul = Path(self.tmp.name) / "tulos.md"
        tul.write_text("Valmis: osa B toteutettu.\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as ulos:
            rc = lp.main(["kirjoita-tulos", str(repo), str(palatiedosto), str(tul), "--kirjasto", self.tila.kirjasto])
        self.assertEqual((rc, ulos.getvalue()), (0, "%s/pala-2.md\n" % t))
        uudet = lp.tarkista_paluut(self.tila.luovutukset, str(repo))
        self.assertEqual([(p["tunnus"], p["n"], p["merkinta"]) for p in uudet], [(t, 2, "[Paketin Mittari X pala 2 valmis]")])
        self.assertEqual(lp.lue_tulos(self.tila.luovutukset, str(repo), t, 2), "Valmis: osa B toteutettu.\n")
        # tulosrepo kirjaston sisalla hylataan myos komennolla
        sisalla = Path(self.tila.kirjasto) / "tulokset"
        sisalla.mkdir()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lp.main(["kirjoita-tulos", str(sisalla), str(palatiedosto), str(tul),
                                      "--kirjasto", self.tila.kirjasto]), 1)
        self.assertEqual(os.listdir(sisalla), [])


if __name__ == "__main__":
    unittest.main()
