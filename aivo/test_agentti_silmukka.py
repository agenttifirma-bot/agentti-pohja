"""Silmukan testit (suunnitelma kohdat 11/4, 11/7): korvikemalli, ei verkkoa, ei kuluja.

Korvikemalli on aina aarellinen lista vastauksia. Kun lista loppuu, malli nostaa virheen, joten
raja pois -mutaatio ei jaa ikuiseen silmukkaan vaan kaataa testin.
"""
import json
import os
import fcntl
import tempfile
import time
import unittest

from aivo.agentti import polut, silmukka


def lohko(nimi, **arg):
    return "[[TYOKALU %s]]" % json.dumps({"nimi": nimi, "arg": arg})


class Korvikemalli:
    def __init__(self, vastaukset):
        self.vastaukset = list(vastaukset)
        self.kutsut = []

    def __call__(self, viestit):
        self.kutsut.append(viestit)
        if not self.vastaukset:
            raise AssertionError("korvikemallin vastaukset loppuivat")
        return self.vastaukset.pop(0)


class Kello:
    def __init__(self, askel=0.0):
        self.t = 0.0
        self.askel = askel

    def __call__(self):
        arvo = self.t
        self.t += self.askel
        return arvo


class SilmukkaTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.juuri = self._tmp.name

    def aja(self, vastaukset, **kw):
        malli = Korvikemalli(vastaukset)
        return silmukka.aja(malli, "tee tehtava", self.juuri, **kw), malli

    def test_kulku_lue_kirjoita_valmis(self):
        with open(os.path.join(self.juuri, "syote.md"), "w", encoding="utf-8") as f:
            f.write("alku\n")
        t, malli = self.aja([
            lohko("lue", polku="syote.md"),
            "Kirjoitan tuloksen.\n" + lohko("kirjoita", polku="ulos.md", sisalto="tulos\n"),
            lohko("valmis", raportti="Valmis, tulos tiedostossa ulos.md"),
        ])
        self.assertEqual(t.tila, silmukka.VALMIS)
        self.assertEqual(t.raportti, "Valmis, tulos tiedostossa ulos.md")
        self.assertEqual(t.askelia, 3)
        self.assertEqual([r.nimi for r in t.loki], ["lue", "kirjoita", "valmis"])
        self.assertTrue(all(r.ok for r in t.loki))
        with open(os.path.join(self.juuri, "ulos.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "tulos\n")
        # tyokalun tulos palautuu mallille datakehyksessa
        viimeinen = malli.kutsut[1][-1]["content"]
        self.assertTrue(viimeinen.startswith("<<<DATA tunnus="))
        self.assertIn("alku", viimeinen)

    def test_loki_ei_sisalla_tiedoston_sisaltoa(self):
        with open(os.path.join(self.juuri, "s.md"), "w", encoding="utf-8") as f:
            f.write("SALAINEN-SISALTO")
        t, _ = self.aja([lohko("lue", polku="s.md"), lohko("valmis", raportti="x")])
        self.assertNotIn("SALAINEN", repr(t.loki))

    def test_askelraja(self):
        vastaukset = [lohko("listaa", polku="a%d" % i) for i in range(10)]
        t, malli = self.aja(vastaukset, askelraja=4)
        self.assertEqual((t.tila, t.syy, t.askelia), (silmukka.RAJA, "askelraja", 4))
        self.assertEqual(len(malli.kutsut), 4)

    def test_virheellinen_lohko_lasketaan_askeleeksi_ja_palautetaan_virheena(self):
        roskaa = ["[[TYOKALU {rikki}]]", "pelkkaa tekstia", lohko("tuntematon"), "[[TYOKALU {}]]", "x"]
        t, malli = self.aja(roskaa, askelraja=3)
        self.assertEqual((t.tila, t.syy, t.askelia), (silmukka.RAJA, "askelraja", 3))
        self.assertEqual(len(t.loki), 3)
        self.assertFalse(any(r.ok for r in t.loki))
        self.assertIn("virhe:", malli.kutsut[1][-1]["content"])

    def test_virheen_jalkeen_voi_jatkaa(self):
        t, _ = self.aja(["[[TYOKALU {rikki}]]", lohko("valmis", raportti="ok")])
        self.assertEqual((t.tila, t.askelia), (silmukka.VALMIS, 2))
        self.assertFalse(t.loki[0].ok)

    def test_aikaraja(self):
        kello = Kello(askel=10.0)
        vastaukset = [lohko("listaa", polku="a%d" % i) for i in range(20)]
        t, malli = self.aja(vastaukset, aikaraja_s=35, nyt=kello)
        self.assertEqual((t.tila, t.syy), (silmukka.RAJA, "aikaraja"))
        self.assertLess(len(malli.kutsut), 20)
        self.assertGreater(t.kesto_s, 0)

    def test_aikaraja_ei_lauennut_ennen_aikaa(self):
        kello = Kello(askel=1.0)
        t, _ = self.aja([lohko("valmis", raportti="ok")], aikaraja_s=1000, nyt=kello)
        self.assertEqual(t.tila, silmukka.VALMIS)

    def test_toisto_keskeyttaa_kolmannella_samalla_kutsulla(self):
        t, malli = self.aja([lohko("listaa")] * 6, askelraja=30)
        self.assertEqual((t.tila, t.syy, t.askelia), (silmukka.RAJA, "toisto", 3))
        self.assertEqual(len(malli.kutsut), 3)
        self.assertEqual(sum(1 for r in t.loki if r.ok), 2)     # kolmatta ei ajettu

    def test_eri_argumentit_eivat_ole_toistoa(self):
        vastaukset = [lohko("listaa", polku="a"), lohko("listaa", polku="b"), lohko("listaa", polku="a"),
                      lohko("valmis", raportti="ok")]
        t, _ = self.aja(vastaukset)
        self.assertEqual(t.tila, silmukka.VALMIS)

    def test_toiston_juoksu_katkeaa_valissa_olevasta_eri_kutsusta(self):
        vastaukset = [lohko("listaa"), lohko("listaa"), lohko("listaa", polku="x"), lohko("listaa"),
                      lohko("listaa"), lohko("valmis", raportti="ok")]
        t, _ = self.aja(vastaukset)
        self.assertEqual(t.tila, silmukka.VALMIS)

    def test_argumenttien_jarjestys_ei_peita_toistoa(self):
        v = [lohko("lue", polku="a.md", alku=0), '[[TYOKALU {"nimi": "lue", "arg": {"alku": 0, "polku": "a.md"}}]]',
             lohko("lue", polku="a.md", alku=0)]
        t, _ = self.aja(v)
        self.assertEqual((t.tila, t.syy), (silmukka.RAJA, "toisto"))

    def test_mallin_virhe_antaa_virhetilan_vain_tyypin_nimella(self):
        def huono(viestit):
            raise ValueError("avain sk-salainen")
        t = silmukka.aja(huono, "x", self.juuri)
        self.assertEqual(t.tila, silmukka.VIRHE)
        self.assertIn("ValueError", t.syy)
        self.assertNotIn("salainen", t.syy)

    def test_malli_palauttaa_ei_tekstia(self):
        t, _ = self.aja([None, lohko("valmis", raportti="ok")])
        self.assertEqual((t.tila, t.askelia), (silmukka.VALMIS, 2))

    def test_tyokalun_virhe_palautuu_mallille_eika_kaada(self):
        t, malli = self.aja([lohko("lue", polku="../x.md"), lohko("valmis", raportti="ok")])
        self.assertEqual(t.tila, silmukka.VALMIS)
        self.assertFalse(t.loki[0].ok)
        self.assertIn("virhe:", malli.kutsut[1][-1]["content"])

    def test_tyokansio_puuttuu(self):
        t = silmukka.aja(Korvikemalli([]), "x", os.path.join(self.juuri, "ei-ole"))
        self.assertEqual((t.tila, t.askelia), (silmukka.VIRHE, 0))

    def test_malli_ei_voi_muuttaa_silmukan_viestihistoriaa(self):
        def pahantahtoinen(viestit):
            viestit.clear()
            return lohko("valmis", raportti="ok")
        self.assertEqual(silmukka.aja(pahantahtoinen, "x", self.juuri).tila, silmukka.VALMIS)

    def test_valiaikaistiedostot_eivat_laske_tiedostorajaa(self):
        os.mkdir(os.path.join(self.juuri, "ala"))
        for i in range(polut.RAJA_TIEDOSTOT + 5):
            nimi = ".kirj-%d.tmp" % (1000 + i)
            polku = os.path.join(self.juuri, nimi if i % 2 else "ala/" + nimi)
            with open(polku, "w") as f:
                f.write("x")
            vanha = time.time() - polut.VALIAIKAINEN_ARMO_S - 60    # kaatuneen ajon jaannos (ei lukkoa)
            os.utime(polku, (vanha, vanha))
        # ilman siivousta kansio on "taynna"
        self.assertGreater(polut.mittaa_kansio(self.juuri)[0], polut.RAJA_TIEDOSTOT)
        t, _ = self.aja([lohko("kirjoita", polku="uusi.md", sisalto="a"), lohko("valmis", raportti="ok")])
        self.assertEqual(t.tila, silmukka.VALMIS)
        self.assertTrue(t.loki[0].ok, t.loki[0].selite)
        self.assertEqual(polut.mittaa_kansio(self.juuri)[0], 1)

    def test_siivous_ei_koske_muihin_tiedostoihin_eika_linkkeihin(self):
        for nimi in ("oma.md", ".kirj-1.tmp.md", ".kirj-x.tmp", "kirj-1.tmp"):
            with open(os.path.join(self.juuri, nimi), "w") as f:
                f.write("x")
        os.symlink("oma.md", os.path.join(self.juuri, ".kirj-7.tmp"))
        self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 0)
        self.assertEqual(len(os.listdir(self.juuri)), 5)

    def test_siivous_ei_seuraa_kansiolinkkia(self):
        with tempfile.TemporaryDirectory() as muu:
            kohde = os.path.join(muu, ".kirj-1.tmp")
            with open(kohde, "w") as f:
                f.write("x")
            os.symlink(muu, os.path.join(self.juuri, "linkki"))
            self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 0)
            self.assertTrue(os.path.exists(kohde))

    def _valiaik(self, nimi, ika_s=0):
        polku = os.path.join(self.juuri, nimi)
        with open(polku, "w") as f:
            f.write("x")
        if ika_s:
            t = time.time() - ika_s
            os.utime(polku, (t, t))
        return polku

    def test_siivous_jattaa_lukitun_ja_tuoreen_tiedoston(self):
        armo_yli = polut.VALIAIKAINEN_ARMO_S + 60
        lukittu = self._valiaik(".kirj-1-2-%s.tmp" % ("ab" * 8), ika_s=armo_yli)
        tuore = self._valiaik(".kirj-3-4-%s.tmp" % ("cd" * 8))
        tuore_vanha_muoto = self._valiaik(".kirj-5.tmp")
        with open(lukittu, "rb") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)    # rinnakkainen kirjoitus kesken
            self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 0)
        for polku in (lukittu, tuore, tuore_vanha_muoto):
            self.assertTrue(os.path.exists(polku), polku)
        self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 1)   # lukko vapautui
        self.assertFalse(os.path.exists(lukittu))

    def test_siivous_poistaa_lukitsemattomat_jaannokset(self):
        armo_yli = polut.VALIAIKAINEN_ARMO_S + 60
        uusi = self._valiaik(".kirj-1-2-%s.tmp" % ("ab" * 8), ika_s=armo_yli)
        vanha_muoto = self._valiaik(".kirj-7.tmp", ika_s=armo_yli)
        tulevaisuus = self._valiaik(".kirj-3-4-%s.tmp" % ("ef" * 8), ika_s=-armo_yli)
        self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 3)
        for polku in (uusi, vanha_muoto, tulevaisuus):
            self.assertFalse(os.path.exists(polku), polku)

    def test_siivous_poistaa_yli_tunnin_vanhan_lukosta_huolimatta(self):
        vanha = self._valiaik(".kirj-1-2-%s.tmp" % ("ab" * 8), ika_s=polut.VALIAIKAINEN_IKA_S + 60)
        alle = self._valiaik(".kirj-3-4-%s.tmp" % ("cd" * 8), ika_s=polut.VALIAIKAINEN_IKA_S - 60)
        with open(vanha, "rb") as f1, open(alle, "rb") as f2:
            fcntl.flock(f1.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(polut.siivoa_valiaikaiset(self.juuri), 1)
        self.assertFalse(os.path.exists(vanha))
        self.assertTrue(os.path.exists(alle))

if __name__ == "__main__":
    unittest.main()
