import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from claudejono import ajuri, aivo_arvio

SALAINEN_SYY = "SALAINENSYYMERKKIJONO"
SALAINEN_NIMI = "SALAINENTEHTAVANIMI"


def aika(pv):
    return datetime(2026, 11, pv, 12, 0, tzinfo=timezone.utc)


class Pohja(unittest.TestCase):
    def setUp(self):
        self.tila = Path(tempfile.mkdtemp())
        self.tulokset = self.tila / "tulokset"
        self.tulokset.mkdir()

    def arvio(self, nimi, kylla, pv=10, tony=None, malli=None):
        aivo_arvio.kirjaa_arvio(self.tila, nimi, kylla, SALAINEN_SYY, aika(pv))
        if malli:   # malli on valinnainen kentta; kirjaa_arvio ei viela kirjoita sita
            rivit = (self.tila / aivo_arvio.TIEDOSTO).read_text().splitlines()
            d = json.loads(rivit[-1])
            d["malli"] = malli
            rivit[-1] = json.dumps(d)
            (self.tila / aivo_arvio.TIEDOSTO).write_text("\n".join(rivit) + "\n")
        if tony is not None:
            aivo_arvio.tarkista(self.tila, nimi, tony, aika(pv))

    def tulos(self, nimi, tila):
        (self.tulokset / nimi).write_text(f"# Tulos: {nimi}\n\n- Tila: {tila}\n- Aika: x\n\nteksti\n")

    def taydenna(self, n, kylla=True, pv=10, alku=0):
        for i in range(alku, alku + n):
            self.arvio(f"t{pv}-{i}-{'k' if kylla else 'e'}.md", kylla, pv)

    def kooste(self):
        return json.loads((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text())


class Sisalto(Pohja):
    def test_ei_syyta_eika_tehtavan_nimea(self):
        self.arvio(SALAINEN_NIMI + ".md", True)
        self.taydenna(12, True, alku=100)
        self.taydenna(12, False, pv=11)
        aivo_arvio.kirjoita_kooste(self.tila, self.tulokset, nyt=aika(20))
        teksti = (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text()
        self.assertNotIn(SALAINEN_SYY, teksti)
        self.assertNotIn(SALAINEN_NIMI, teksti)
        self.assertNotIn("t10-", teksti)
        self.assertNotIn("2026-11-1", teksti)   # ei paivakohtaisia paivamaaria
        for avain in ("syy", "tehtava"):
            self.assertNotIn(f'"{avain}"', teksti)

    def test_luvut(self):
        self.taydenna(12, True, pv=10)
        self.taydenna(7, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (20, 10, 5))   # 19, 12, 7 pyoristettyna
        self.assertEqual(k["viikoittain"], {"2026-V46": 20})   # 10.-11.11.2026 = viikko 46
        self.assertEqual((k["ensimmainen_viikko"], k["viimeinen_viikko"]), ("2026-V46", "2026-V46"))
        self.assertFalse(k["lahtotasoon_riittavasti_arvioita"])
        self.taydenna(1, True, alku=500)
        self.assertTrue(aivo_arvio.laske_kooste(self.tila)["lahtotasoon_riittavasti_arvioita"])

    def test_ei_malli_eika_paivakohtaisia_maaria(self):
        for i in range(6):
            self.arvio(f"a{i}.md", True, malli="sonnet-x")
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertNotIn("mallit", k)
        self.assertNotIn("paivittain", k)
        self.assertNotIn("sonnet-x", json.dumps(k))

    def test_viikkotaso_yhdistaa_paivat(self):
        self.taydenna(6, True, pv=9)    # ma 9.11. = viikko 46
        self.taydenna(6, True, pv=15)   # su 15.11. = viikko 46
        self.taydenna(6, True, pv=16)   # ma 16.11. = viikko 47
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["viikoittain"], {"2026-V46": 10, "2026-V47": 5})

    def test_tyhja_tila(self):
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["arvioita_yhteensa"], "<5")
        self.assertIsNone(k["yhtenevyys_tonyn_kanssa_prosenttia"])
        self.assertIsNone(k["ensimmainen_viikko"])


class PienetRyhmat(Pohja):
    def test_alle_viisi_peitetaan(self):
        self.taydenna(3, True)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["arvioita_yhteensa"], "<5")
        self.assertEqual(k["viikoittain"], {"2026-V46": "<5"})
        self.assertEqual(k["kylla"], "<5")

    def test_tasan_viisi_nakyy(self):
        self.taydenna(5, True)
        self.taydenna(5, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (10, 5, 5))
        self.assertEqual(k["viikoittain"]["2026-V46"], 10)

    def test_pieni_ei_ryhma_peittaa_myos_kylla_luvun(self):
        self.taydenna(9, True)
        self.taydenna(2, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (10, "<5", "<5"))

    def test_tonyn_tarkistukset_alle_viisi(self):
        for i in range(8):
            self.arvio(f"a{i}.md", True, tony=(i != 0) if i < 3 else None)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["tony_tarkistanut"], "<5")
        self.assertIsNone(k["yhtenevyys_tonyn_kanssa_prosenttia"])

    def test_tonyn_rivi_ilman_aivon_arviota_ei_lasketa(self):
        for i in range(6):
            self.arvio(f"a{i}.md", True)
        with open(self.tila / aivo_arvio.TIEDOSTO, "a") as f:
            for i in range(9):
                f.write(json.dumps({"aika": "2026-11-10T12:00:00+00:00", "laji": "tony", "tehtava": f"orpo{i}.md", "kylla": True}) + "\n")
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["tony_tarkistanut"], "<5")

    def test_tonyn_yhtenevyys(self):
        for i in range(8):
            self.arvio(f"a{i}.md", True, tony=(i < 6))   # 6 osumaa, 2 ei
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["tony_tarkistanut"], k["yhtenevyys_tonyn_kanssa_prosenttia"]), (10, 75))

    def test_tulosyhtenevyys(self):
        for i in range(4):   # kylla + VALMIS = osuma
            self.arvio(f"v{i}.md", True)
            self.tulos(f"v{i}.md", "VALMIS")
        for i in range(2):   # kylla + KESKEN = ei osuma
            self.arvio(f"k{i}.md", True)
            self.tulos(f"k{i}.md", "KESKEN")
        for i in range(2):   # ei + HYLATTY = osuma
            self.arvio(f"h{i}.md", False)
            self.tulos(f"h{i}.md", "HYLATTY")
        self.arvio("x.md", True)
        self.tulos("x.md", "EPAONNISTUI")   # ei vertailuun
        self.arvio("ilman.md", True)        # ei tulosta
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual((k["tulokseen_verrattu"], k["yhtenevyys_tuloksen_kanssa_prosenttia"]), (10, 75))

    def test_tulosyhtenevyys_alle_viisi(self):
        self.arvio("a.md", True)
        self.tulos("a.md", "VALMIS")
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual(k["tulokseen_verrattu"], "<5")
        self.assertIsNone(k["yhtenevyys_tuloksen_kanssa_prosenttia"])

    def test_polkuhypyn_nimi_ei_lue_tulosta(self):
        (self.tila / "x.md").write_text("- Tila: VALMIS\n")   # tulokset/../x.md olisi olemassa
        self.assertIsNone(aivo_arvio._tulos_tila(self.tulokset, "../x.md"))
        self.assertEqual(aivo_arvio._tulos_tila(self.tila, "x.md"), "VALMIS")


class Kirjoitus(Pohja):
    def test_oikeudet_0644_vaikka_umask_tiukka(self):
        vanha = os.umask(0o077)
        try:
            p = aivo_arvio.kirjoita_kooste(self.tila)
        finally:
            os.umask(vanha)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)

    def test_kirjanpito_0600_ja_vain_ajurille(self):
        vanha = os.umask(0o000)
        try:
            aivo_arvio.kirjoita_kooste(self.tila)
        finally:
            os.umask(vanha)
        self.assertEqual(stat.S_IMODE((self.tila / aivo_arvio.KOOSTE_TILA_TIEDOSTO).stat().st_mode), 0o600)

    def test_atominen_kirjoitus_rename(self):
        aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(10))
        vanha = (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text()
        self.taydenna(12, True)
        with mock.patch("claudejono.aivo_arvio.os.replace", side_effect=OSError("x")):
            with self.assertRaises(OSError):
                aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(20))
        self.assertEqual((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text(), vanha)   # vanha ehja
        self.assertEqual([p.name for p in self.tila.glob("*.tmp")], [])                 # valiaikaistiedosto siivottu

    def test_replace_kutsutaan_valiaikaistiedostolla(self):
        kutsut = []
        todellinen = os.replace
        with mock.patch("claudejono.aivo_arvio.os.replace", side_effect=lambda a, b: (kutsut.append((a, b)), todellinen(a, b))[1]):
            aivo_arvio.kirjoita_kooste(self.tila)
        nimet = [(Path(a).name, Path(b).name) for a, b in kutsut]
        self.assertEqual(len(nimet), 2)   # kirjanpito + kooste
        kooste = [n for n in nimet if n[1] == aivo_arvio.KOOSTE_TIEDOSTO]
        self.assertEqual(len(kooste), 1)
        self.assertNotEqual(kooste[0][0], aivo_arvio.KOOSTE_TIEDOSTO)

    def test_ylikirjoittaa_vanhan_kun_portti_auki(self):
        self.taydenna(6, True)
        aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(10))
        self.assertEqual(self.kooste()["arvioita_yhteensa"], 5)
        self.taydenna(10, True, alku=50)
        aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(12))
        self.assertEqual(self.kooste()["arvioita_yhteensa"], 15)   # 16 pyoristettyna


class Erotushyokkays(Pohja):
    """Kahden perakkaisen koosteen erotus ei saa paljastaa yksittaista arviota."""

    def julkaise(self, pv, tunti=12):
        return aivo_arvio.kirjoita_kooste(self.tila, self.tulokset, nyt=datetime(2026, 11, pv, tunti, 0, tzinfo=timezone.utc))

    def luku(self):
        return (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_bytes() if (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).exists() else None

    def pohja(self):
        self.taydenna(12, True, pv=9)
        self.taydenna(12, False, pv=9)
        self.assertIsNotNone(self.julkaise(10))
        return self.luku()

    def test_yksi_uusi_arvio_ei_muuta_koostetta(self):
        ennen = self.pohja()
        for kylla in (True, False):   # kumpi tahansa tulos: kooste ei muutu lainkaan
            self.arvio(f"uusi-{kylla}.md", kylla, pv=12)
            self.assertIsNone(self.julkaise(14))   # yli vuorokausi, mutta vain 1 uutta
            self.assertEqual(self.luku(), ennen)

    def test_yhdeksan_uutta_ei_riita(self):
        ennen = self.pohja()
        self.taydenna(9, True, pv=12, alku=200)
        self.assertIsNone(self.julkaise(14))
        self.assertEqual(self.luku(), ennen)

    def test_kymmenen_uutta_ei_riita_jos_vuorokausi_ei_ole_kulunut(self):
        ennen = self.pohja()
        self.taydenna(10, True, pv=10, alku=300)
        self.assertIsNone(self.julkaise(10, tunti=23))   # 11 h edellisesta
        self.assertEqual(self.luku(), ennen)

    def test_kymmenen_uutta_ja_vuorokausi_julkaisee(self):
        ennen = self.pohja()
        self.taydenna(10, True, pv=10, alku=300)
        self.assertIsNotNone(self.julkaise(11))   # tasan 24 h, 10 uutta
        self.assertNotEqual(self.luku(), ennen)

    def test_tonyn_tarkistus_ja_tulos_lasketaan_muutokseen(self):
        ennen = self.pohja()
        for i in range(5):                        # 5 Tonin tarkistusta + 5 tulosta (eri tehtavissa) = 10 muuttunutta kohdetta
            aivo_arvio.tarkista(self.tila, f"t9-{i}-k.md", True, aika(12))
            self.tulos(f"t9-{i + 5}-k.md", "VALMIS")
        self.assertIsNotNone(self.julkaise(12))
        self.assertNotEqual(self.luku(), ennen)

    def test_yksi_tonyn_tarkistus_ei_paljastu_erotuksesta(self):
        ennen = self.pohja()
        aivo_arvio.tarkista(self.tila, "t9-0-k.md", False, aika(12))
        self.assertIsNone(self.julkaise(14))
        self.assertEqual(self.luku(), ennen)

    def test_julkaistu_erotus_on_pyoristetty(self):
        self.taydenna(10, True, pv=9)
        self.taydenna(10, False, pv=9)
        self.julkaise(10)
        a = self.kooste()
        self.taydenna(10, True, pv=11, alku=500)
        self.julkaise(12)
        b = self.kooste()
        for kentta in ("arvioita_yhteensa", "kylla", "ei"):
            self.assertEqual(b[kentta] % 5, 0)
        self.assertEqual((b["kylla"] - a["kylla"], b["ei"] - a["ei"]), (10, 0))   # vain koko era nakyy

    def test_laskettu_on_vain_paiva_ja_prosentit_kokonaislukuja(self):
        for i in range(7):
            self.arvio(f"a{i}.md", i < 4, tony=(i < 5))
        self.arvio("b.md", True, tony=True)
        k = aivo_arvio.laske_kooste(self.tila, nyt=datetime(2026, 11, 10, 12, 34, 56, tzinfo=timezone.utc))
        self.assertEqual(k["laskettu"], "2026-11-10")
        p = k["yhtenevyys_tonyn_kanssa_prosenttia"]
        self.assertIs(type(p), int)
        self.assertEqual(p, 88)   # 7/8

    def test_kellon_meno_taaksepain_ei_avaa_porttia(self):
        self.pohja()
        self.taydenna(20, True, pv=10, alku=700)
        self.assertIsNone(self.julkaise(9))

    def test_kirjanpito_ei_vuoda_tarkkoja_lukuja_koosteeseen(self):
        self.taydenna(13, True, pv=9)
        self.taydenna(8, False, pv=9)
        self.julkaise(10)
        teksti = (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text()
        self.assertNotIn("lukema", teksti)
        self.assertNotIn("21", teksti.replace("2026", ""))   # 13 + 8 = 21 ei nay
        self.assertEqual(self.kooste()["arvioita_yhteensa"], 20)


    # Tarkastajan 15.11. loydokset: portti ei aukea virhetilanteessa; muutosmittari huomaa korvauksen ja tilanvaihdon.

    def test_puuttuva_kooste_ei_avaa_porttia(self):
        ennen = self.pohja()
        (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).unlink()
        self.assertIsNone(self.julkaise(10, tunti=13))   # vain 1 h edellisesta, ei uusia
        self.assertFalse((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).exists())

    def test_puuttuva_kirjanpito_ei_avaa_porttia(self):
        ennen = self.pohja()
        (self.tila / aivo_arvio.KOOSTE_TILA_TIEDOSTO).unlink()
        self.assertIsNone(self.julkaise(11))
        self.assertEqual(self.luku(), ennen)

    def test_rikkinainen_kirjanpito_ei_avaa_porttia(self):
        ennen = self.pohja()
        for sisalto in ("ei json", "[]", "{}", '{"aika": "x", "kohteet": {}}', '{"aika": "2026-11-10T12:00:00+00:00"}'):
            (self.tila / aivo_arvio.KOOSTE_TILA_TIEDOSTO).write_text(sisalto)
            self.assertIsNone(self.julkaise(14), sisalto)
            self.assertEqual(self.luku(), ennen)

    def test_kooste_poistettu_mutta_kirjanpito_kunnossa_odottaa_porttia(self):
        self.pohja()
        (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).unlink()
        self.taydenna(10, True, pv=10, alku=900)
        self.assertIsNotNone(self.julkaise(11))   # portti aukeaa normaalisti: >= 24 h ja >= 10 uutta
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())

    def test_ensijulkaisu_toimii_kun_kumpaakaan_ei_ole(self):
        self.taydenna(6, True)
        self.assertIsNotNone(self.julkaise(10))

    def test_arvion_korvaus_lasketaan_muutokseksi(self):
        ennen = self.pohja()
        for i in range(10):   # 10 olemassa olevan tehtavan arvio kaantyy kylla -> ei
            aivo_arvio.kirjaa_arvio(self.tila, f"t9-{i}-k.md", False, "uusi", aika(12))
        self.assertIsNotNone(self.julkaise(12))
        self.assertNotEqual(self.luku(), ennen)

    def test_yksi_korvaus_ei_avaa_porttia(self):
        ennen = self.pohja()
        aivo_arvio.kirjaa_arvio(self.tila, "t9-0-k.md", False, "uusi", aika(12))
        self.assertIsNone(self.julkaise(14))
        self.assertEqual(self.luku(), ennen)

    def test_tuloksen_tilan_vaihto_lasketaan_muutokseksi(self):
        for i in range(10):
            self.tulos(f"t9-{i}-k.md", "KESKEN")
        self.taydenna(12, True, pv=9)
        self.taydenna(12, False, pv=9)
        self.assertIsNotNone(self.julkaise(10))
        for i in range(10):
            self.tulos(f"t9-{i}-k.md", "VALMIS")   # KESKEN -> VALMIS: vertailtujen maara ei muutu
        self.assertIsNotNone(self.julkaise(12))

    def test_tonyn_tarkistuksen_kaantaminen_lasketaan_muutokseksi(self):
        for i in range(10):
            self.arvio(f"x{i}.md", True, pv=9, tony=True)
        self.taydenna(12, False, pv=9)
        self.assertIsNotNone(self.julkaise(10))
        for i in range(10):
            aivo_arvio.tarkista(self.tila, f"x{i}.md", False, aika(12))
        self.assertIsNotNone(self.julkaise(12))

    def test_kirjanpito_ei_sisalla_tehtavien_nimia(self):
        self.arvio(SALAINEN_NIMI + ".md", True)
        self.taydenna(12, True, alku=100)
        self.julkaise(10)
        self.assertNotIn(SALAINEN_NIMI, (self.tila / aivo_arvio.KOOSTE_TILA_TIEDOSTO).read_text())


class Symlinkki(Pohja):
    """Oikeudet asetetaan tiedostokahvalla: polun kautta tehty chmod seuraisi symlinkkia (rootin kilpa)."""

    def test_ei_chmod_polun_kautta(self):
        with mock.patch("claudejono.aivo_arvio.os.chmod", side_effect=AssertionError("chmod polun kautta")):
            aivo_arvio.kirjoita_kooste(self.tila)
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())

    def test_fchmod_kutsutaan_kahvalla_ennen_rename(self):
        jarjestys = []
        fchmod, replace = os.fchmod, os.replace
        with mock.patch("claudejono.aivo_arvio.os.fchmod", side_effect=lambda fd, m: (jarjestys.append(("fchmod", m)), fchmod(fd, m))[1]), \
                mock.patch("claudejono.aivo_arvio.os.replace", side_effect=lambda a, b: (jarjestys.append(("replace", Path(b).name)), replace(a, b))[1]):
            aivo_arvio.kirjoita_kooste(self.tila)
        self.assertEqual(jarjestys, [("fchmod", 0o600), ("replace", aivo_arvio.KOOSTE_TILA_TIEDOSTO),
                                     ("fchmod", 0o644), ("replace", aivo_arvio.KOOSTE_TIEDOSTO)])

    def test_symlinkki_kohteessa_ei_muuta_symlinkin_kohteen_oikeuksia(self):
        uhri = self.tila / "uhri.txt"
        uhri.write_text("x")
        os.chmod(uhri, 0o600)
        self.taydenna(6, True, pv=9)
        aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(10))
        kohde = self.tila / aivo_arvio.KOOSTE_TIEDOSTO
        kohde.unlink()
        kohde.symlink_to(uhri)
        self.taydenna(10, True, pv=10, alku=50)
        self.assertIsNotNone(aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(12)))
        self.assertEqual(stat.S_IMODE(uhri.stat().st_mode), 0o600)
        self.assertEqual(uhri.read_text(), "x")
        self.assertFalse(kohde.is_symlink())   # symlink korvattu, ei seurattu
        self.assertEqual(stat.S_IMODE(kohde.stat().st_mode), 0o644)

    def test_symlinkki_valiaikaispolulla_ei_muuta_kohteen_oikeuksia(self):
        uhri = self.tila / "uhri2.txt"
        uhri.write_text("x")
        os.chmod(uhri, 0o600)
        todellinen = tempfile.mkstemp

        def kilpa(*a, **kw):
            fd, polku = todellinen(*a, **kw)
            os.unlink(polku)             # hyokkaaja vaihtaa valiaikaispolun symlinkiksi kahvan avaamisen jalkeen
            os.symlink(uhri, polku)
            return fd, polku

        with mock.patch("claudejono.aivo_arvio.tempfile.mkstemp", side_effect=kilpa):
            try:
                aivo_arvio.kirjoita_kooste(self.tila)
            except OSError:
                pass
        self.assertEqual(stat.S_IMODE(uhri.stat().st_mode), 0o600)
        self.assertEqual(uhri.read_text(), "x")


class Virheet(Pohja):
    def test_varma_kirjoitus_ei_nosta_virhetta_ja_kirjaa_tyypin(self):
        err = io.StringIO()
        with mock.patch("claudejono.aivo_arvio._muodosta", side_effect=ValueError("SALAISUUS")), contextlib.redirect_stderr(err):
            self.assertFalse(aivo_arvio.kirjoita_kooste_varmasti(self.tila))
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("SALAISUUS", err.getvalue())

    def test_varma_kirjoitus_onnistuu(self):
        self.assertTrue(aivo_arvio.kirjoita_kooste_varmasti(self.tila))

    def test_ajuri_ei_kaadu_laskentavirheeseen(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", return_value="jono tyhja"), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                mock.patch("claudejono.aivo_arvio._muodosta", side_effect=RuntimeError("SALAISUUS")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 0)
        self.assertIn("RuntimeError", err.getvalue())

    def test_ajuri_kirjoittaa_koosteen_kierroksella(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", return_value="jono tyhja"), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 0)
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())

    def test_koosteen_kirjoitus_myos_kun_aja_kaatuu(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", side_effect=RuntimeError("x")), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                mock.patch.object(ajuri, "halyta"), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 1)
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())


if __name__ == "__main__":
    unittest.main()
