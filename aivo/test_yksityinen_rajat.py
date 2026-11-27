"""Rajatestit yksityisen tilan turvasuojille (mutaatiokartoituksen selviytyjat, tulos 2026-11-22-63).

Kattaa: ehdotuksen hylkaamisen (tunnuksen tarkistus, tiedostotyypit, siirto), kansion ja avaintiedoston
linkkitarkistuksen seka kehotteen valinnan ja roolisuodatuksen. Vain stdlib, ei verkkoa, ei oikeita avaimia.
Testit eivat muuta tuotantokoodia."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from aivo import yksityinen, yksityinen_or

EID = "0123456789ab"
SISALTO = '{"tiedosto": "a.md", "teksti": "x\\n", "sha": "y"}'
AVAIN = "sk-testi-" + "x" * 30          # keksitty, ei oikea avain


class TilapaisTesti(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.juuri = Path(self._td.name)
        self.ehd = self.juuri / "ehdotukset"
        self.ehd.mkdir(mode=0o700)

    def ehdotus(self, eid=EID, sisalto=SISALTO):
        p = self.ehd / (eid + ".json")
        p.write_text(sisalto, encoding="utf-8")
        return p


class HylkaaTunnusTesti(TilapaisTesti):
    def test_ei_merkkijono_tunnus_hylataan_oikealla_virheella(self):
        self.ehdotus()
        for huono in (None, 123, b"0123456789ab", [EID], 1.5):
            with self.subTest(tunnus=huono):
                # TypeError tai muu poikkeus olisi vuoto: suojan pitaa nostaa YksityinenVirhe
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.hylkaa_ehdotus(self.ehd, huono)
        self.assertTrue((self.ehd / (EID + ".json")).is_file())
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_vaaranmuotoinen_tunnus_hylataan_eika_tiedostoa_siirreta(self):
        # Jokaiselle huonolle tunnukselle on olemassa tiedosto, jonka heikko tarkistus siirtaisi.
        vaarat = ["abc", "0123456789AB", "0123456789abc", "0123456789ag", "", "0123456789a ", "x" * 12]
        for v in vaarat:
            if v:
                (self.ehd / (v + ".json")).write_text(SISALTO, encoding="utf-8")
        for v in vaarat:
            with self.subTest(tunnus=v):
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.hylkaa_ehdotus(self.ehd, v)
        for v in vaarat:
            if v:
                self.assertTrue((self.ehd / (v + ".json")).is_file(), v)
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_polun_ohitus_tunnuksessa_hylataan(self):
        ulko = self.juuri / "ulko"
        ulko.mkdir()
        (ulko / "x.json").write_text(SISALTO, encoding="utf-8")
        (self.ehd / "alikansio").mkdir()
        for v in ("../ulko/x", "alikansio/../../ulko/x", "/etc/passwd"):
            with self.subTest(tunnus=v):
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.hylkaa_ehdotus(self.ehd, v)
        self.assertTrue((ulko / "x.json").is_file())
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_puuttuva_ehdotus_antaa_virheen(self):
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertFalse((self.ehd / "hylatyt").exists())


class HylkaaTiedostotyyppiTesti(TilapaisTesti):
    def test_hakemisto_ehdotustiedoston_paikalla_hylataan(self):
        (self.ehd / (EID + ".json")).mkdir()
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertTrue((self.ehd / (EID + ".json")).is_dir())
        # Tyyppi tarkistetaan ennen kohdekansion luontia: kohdetta ei saa syntya.
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_symlinkki_tiedostoon_hylataan(self):
        oikea = self.juuri / "oikea.json"
        oikea.write_text(SISALTO, encoding="utf-8")
        os.symlink(oikea, self.ehd / (EID + ".json"))
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertTrue((self.ehd / (EID + ".json")).is_symlink())
        self.assertTrue(oikea.is_file())
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_symlinkki_hakemistoon_hylataan(self):
        kohde = self.juuri / "kansio"
        kohde.mkdir()
        os.symlink(kohde, self.ehd / (EID + ".json"))
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertTrue((self.ehd / (EID + ".json")).is_symlink())
        self.assertFalse((self.ehd / "hylatyt").exists())

    def test_rikkinainen_symlinkki_hylataan(self):
        os.symlink(self.juuri / "ei-ole", self.ehd / (EID + ".json"))
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertFalse((self.ehd / "hylatyt").exists())


class HylkaaOnnistuuTesti(TilapaisTesti):
    def test_tiedosto_siirtyy_hylatyt_kansioon_sisalto_ennallaan(self):
        self.ehdotus()
        tulos = yksityinen.hylkaa_ehdotus(self.ehd, EID)
        kohde = self.ehd / "hylatyt" / (EID + ".json")
        self.assertEqual(tulos, str(kohde))
        self.assertEqual(kohde.read_text(encoding="utf-8"), SISALTO)
        self.assertFalse((self.ehd / (EID + ".json")).exists())
        self.assertEqual(stat.S_IMODE(os.lstat(self.ehd / "hylatyt").st_mode), 0o700)
        self.assertEqual(yksityinen.listaa_ehdotukset(self.ehd), [])

    def test_muut_ehdotukset_jaavat_paikalleen(self):
        muu = "ba9876543210"
        self.ehdotus()
        self.ehdotus(muu, "muu")
        yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertEqual(yksityinen.listaa_ehdotukset(self.ehd), [muu])
        self.assertEqual((self.ehd / (muu + ".json")).read_text(encoding="utf-8"), "muu")

    def test_aiempaa_hylattya_ei_korvata(self):
        self.ehdotus()
        yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.ehdotus(sisalto="uusi")
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.hylkaa_ehdotus(self.ehd, EID)
        self.assertEqual((self.ehd / "hylatyt" / (EID + ".json")).read_text(encoding="utf-8"), SISALTO)
        self.assertEqual((self.ehd / (EID + ".json")).read_text(encoding="utf-8"), "uusi")


class HakemistoLinkkiTesti(TilapaisTesti):
    """tarkista_yksityinen_hakemisto: luo=False, jolloin mkdir ei peita tyyppitarkistusta."""

    def test_tavallinen_tiedosto_hylataan_ilman_luontia(self):
        f = self.juuri / "tiedosto"
        f.write_text("x")
        with self.assertRaisesRegex(yksityinen.YksityinenVirhe, "oikea kansio"):
            yksityinen.tarkista_yksityinen_hakemisto(f, luo=False)

    def test_symlinkki_kansioon_ja_tiedostoon_hylataan(self):
        (self.juuri / "kansio").mkdir(mode=0o700)
        (self.juuri / "tiedosto").write_text("x")
        os.symlink(self.juuri / "kansio", self.juuri / "linkki-kansioon")
        os.symlink(self.juuri / "tiedosto", self.juuri / "linkki-tiedostoon")
        for nimi in ("linkki-kansioon", "linkki-tiedostoon"):
            for luo in (False, True):
                with self.subTest(nimi=nimi, luo=luo):
                    with self.assertRaises(yksityinen.YksityinenVirhe):
                        yksityinen.tarkista_yksityinen_hakemisto(self.juuri / nimi, luo=luo)

    def test_oikea_kansio_hyvaksytaan(self):
        k = self.juuri / "kansio"
        k.mkdir(mode=0o700)
        self.assertEqual(yksityinen.tarkista_yksityinen_hakemisto(k, luo=False), k)


class AvainLinkkiTesti(TilapaisTesti):
    """yksityinen_or.lue_avain: viesti kertoo, mika tarkistus kaatoi (muut tarkistukset antavat eri viestin)."""

    def avaintiedosto(self, nimi="avain.txt"):
        p = self.juuri / nimi
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(AVAIN + "\n")
        return p

    def test_tavallinen_avaintiedosto_luetaan(self):
        self.assertEqual(yksityinen_or.lue_avain(self.avaintiedosto()), AVAIN)

    def test_symlinkki_avaintiedostoon_hylataan(self):
        oikea = self.avaintiedosto()
        os.symlink(oikea, self.juuri / "linkki.txt")
        with self.assertRaisesRegex(yksityinen.YksityinenVirhe, "tavallinen tiedosto"):
            yksityinen_or.lue_avain(self.juuri / "linkki.txt")

    def test_hakemisto_avaintiedoston_paikalla_hylataan_tyypin_takia(self):
        k = self.juuri / "kansio"
        k.mkdir(mode=0o700)
        with self.assertRaisesRegex(yksityinen.YksityinenVirhe, "tavallinen tiedosto"):
            yksityinen_or.lue_avain(k)

    def test_virheviestissa_ei_ole_avainta(self):
        oikea = self.avaintiedosto()
        os.symlink(oikea, self.juuri / "linkki.txt")
        try:
            yksityinen_or.lue_avain(self.juuri / "linkki.txt")
        except yksityinen.YksityinenVirhe as e:
            self.assertNotIn(AVAIN, str(e))
        else:
            self.fail("linkin pitaa antaa virhe")


class KehoteValintaTesti(unittest.TestCase):
    def sys_viesti(self, **kw):
        return yksityinen.muodosta_viestit("MUISTI", [{"rooli": "tony", "teksti": "moi"}], "OHJE", **kw)[0]["content"]

    def test_oletuskehote_kun_kehotetta_ei_anneta_tai_se_on_tyhja(self):
        for kehote in (None, ""):
            with self.subTest(kehote=kehote):
                s = self.sys_viesti(kehote=kehote)
                self.assertTrue(s.startswith(yksityinen.YKSITYINEN_KEHOTE + "\n"))

    def test_annettu_kehote_korvaa_oletuksen(self):
        s = self.sys_viesti(kehote="OMA KEHOTE")
        self.assertTrue(s.startswith("OMA KEHOTE\n"))
        self.assertNotIn(yksityinen.YKSITYINEN_KEHOTE, s)

    def test_ydinohjeet_ja_muisti_mukana_ja_tyhjalle_ohjeelle_oletusteksti(self):
        s = self.sys_viesti()
        self.assertIn("OHJE", s)
        self.assertIn("MUISTI", s)
        tyhja = yksityinen.muodosta_viestit("", [{"rooli": "tony", "teksti": "moi"}], "")[0]["content"]
        self.assertIn("(ei ydinohjeita)", tyhja)


class RooliSuodatusTesti(unittest.TestCase):
    def test_jarjestelmamerkinta_ei_ole_oma_viesti_vaan_liitetaan_seuraavaan_tonyn_viestiin(self):
        h = [{"rooli": "tony", "teksti": "a"}, {"rooli": "aivo", "teksti": "b"},
             {"rooli": yksityinen.JARJESTELMA_ROOLI, "teksti": "[Jarjestelma: x]"},
             {"rooli": "tony", "teksti": "c"}]
        v = yksityinen.muodosta_viestit("", h, "")
        self.assertEqual([(x["role"], x["content"]) for x in v[1:]],
                         [("user", "a"), ("assistant", "b"), ("user", "[Jarjestelma: x]\nc")])

    def test_viimeinen_jarjestelmamerkinta_ilman_tonyn_viestia_tulee_user_viestina(self):
        h = [{"rooli": "tony", "teksti": "a"}, {"rooli": "aivo", "teksti": "b"},
             {"rooli": yksityinen.JARJESTELMA_ROOLI, "teksti": "[Jarjestelma: loppu]"}]
        v = yksityinen.muodosta_viestit("", h, "")
        self.assertEqual([(x["role"], x["content"]) for x in v[1:]],
                         [("user", "a"), ("assistant", "b"), ("user", "[Jarjestelma: loppu]")])

    def test_jarjestelmarooli_ei_koskaan_tule_assistant_viestina(self):
        h = [{"rooli": yksityinen.JARJESTELMA_ROOLI, "teksti": "M1"}, {"rooli": "tony", "teksti": "a"},
             {"rooli": yksityinen.JARJESTELMA_ROOLI, "teksti": "M2"}, {"rooli": "aivo", "teksti": "b"}]
        v = yksityinen.muodosta_viestit("", h, "")
        assistant = [x["content"] for x in v if x["role"] == "assistant"]
        self.assertEqual(assistant, ["b"])
        self.assertEqual(v[1]["content"], "M1\na")
        self.assertEqual(v[-1]["role"], "user")
        self.assertEqual(v[-2]["content"], "b")

    def test_tuntematon_rooli_kasitellaan_avustajana_ei_kayttajana(self):
        v = yksityinen.muodosta_viestit("", [{"rooli": "tony", "teksti": "a"}, {"rooli": "muu", "teksti": "z"}], "")
        self.assertEqual([x["role"] for x in v], ["system", "user", "assistant"])


if __name__ == "__main__":
    unittest.main()
