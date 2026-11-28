"""Yksityisen tilan muistin enimmaiskoko (Tonyn paatos A1123, AIVO_YKSITYINEN_MUISTI_MAX). Stdlib unittest.

Tarkistetaan: oletus 40 000 merkkia, asetus ja sen rajat (4 000-1 000 000), raja vain pienentaa kontekstirajaa,
muistiosion jarjestys (hakuosumat, korjaukset, agenttidata, kirjasto, tiivistelmat), lokirivi (koko ja raja, ei
sisaltoa), itsetarkistuksen lahteiden raja ja valimuistitokenien kirjaus. Ei verkkoa, ei mallikutsuja.
"""
import contextlib
import io
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from aivo import chat, haku, kontekstiraja as kr, salasana_apu, yhdistelma, yksityinen_alue, yksityinen_or as yo
from aivo.test_haku_kehote import tee_tiivistelma

ISO = "qwen/qwen3-235b-a22b-2507"          # 262 144 tokenia
UUSI = "qwen/qwen3.8-2.4t-a95b"            # 262 144 tokenia, 2,0 USD / Mtok sisaan
PIKKU = "google/gemma-2-27b-it"            # 8 192 tokenia: kontekstiraja on alle oletuksen
H = [{"rooli": "tony", "teksti": "kissa"}]


class AsetusTesti(unittest.TestCase):
    def test_oletus(self):
        self.assertEqual(yo.MUISTI_MAX_OLETUS, 40_000)
        for arvo in (None, "", "  "):
            self.assertEqual(yo.tarkista_muisti_max(arvo), 40_000)

    def test_asetus_ja_rajat(self):
        self.assertEqual(yo.tarkista_muisti_max("12000"), 12_000)
        self.assertEqual(yo.tarkista_muisti_max(" 4000 "), 4_000)
        self.assertEqual(yo.tarkista_muisti_max(1_000_000), 1_000_000)

    def test_virheellinen_estaa(self):
        for arvo in ("3999", "1000001", "0", "-5", "abc", "4e4", "40000.5", True):
            with self.subTest(arvo=arvo), self.assertRaises(chat.ChatVirhe):
                yo.tarkista_muisti_max(arvo)

    def test_tila_ja_valitsin(self):
        with tempfile.TemporaryDirectory() as d:
            def tila(**kw):
                return chat.Tila(salasana_apu.tiiviste("oikea-salasana-123"), d, d, ["localhost"], yks_data=d + "/y",
                                 taustapaa="openrouter", or_malli=ISO, **kw)
            self.assertEqual(tila().muisti_max, 40_000)
            self.assertEqual(tila(muisti_max="8000").muisti_max, 8_000)
            with self.assertRaises(chat.ChatVirhe):
                tila(muisti_max="2000")
        lahde = (Path(chat.__file__)).read_text(encoding="utf-8")
        self.assertIn('"--yksityinen-muisti-max", default=os.environ.get("AIVO_YKSITYINEN_MUISTI_MAX")', lahde)
        self.assertIn("muisti_max=a.yksityinen_muisti_max", lahde)


class RajaTesti(unittest.TestCase):
    def test_raja_on_minimi(self):
        konteksti = yo.muistin_kontekstiraja(ISO, "o", H)
        self.assertGreater(konteksti, 400_000)
        self.assertEqual(yo.muistin_merkkiraja(ISO, "o", H), 40_000)
        self.assertEqual(yo.muistin_merkkiraja(ISO, "o", H, muisti_max=12_000), 12_000)
        self.assertEqual(yo.muistin_merkkiraja(ISO, "o", H, muisti_max=yo.MUISTI_MAX_YLARAJA), konteksti)

    def test_alle_oletuksen_konteksti_ratkaisee(self):
        konteksti = yo.muistin_kontekstiraja(PIKKU, "o", H)
        self.assertLess(konteksti, 40_000)
        self.assertEqual(yo.muistin_merkkiraja(PIKKU, "o", H), konteksti)

    def test_raja_vain_pienentaa(self):
        for malli in (ISO, UUSI, PIKKU, "qwen/qwen3-14b"):
            for m in (4_000, 40_000, 1_000_000):
                with self.subTest(malli=malli, m=m):
                    self.assertLessEqual(yo.muistin_merkkiraja(malli, "o", H, muisti_max=m),
                                         yo.muistin_kontekstiraja(malli, "o", H))


class Muisti(unittest.TestCase):
    """Iso kirjasto (320 000 merkkia), agenttidata, Tonyn korjaus ja yksityisen alueen tiivistelma hakuosumaksi."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        r = self.r = Path(self._t.name)
        self.kirjasto = r / "muisti"
        self.kirjasto.mkdir()
        for i in range(40):
            p = self.kirjasto / ("muistio-%02d.md" % i)
            p.write_text("muistio %d " % i + "y" * 8_000, encoding="utf-8")
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        ad = r / "agenttidata"
        (ad / ".git").mkdir(parents=True)
        (ad / "kompassi.md").write_text("# Kompassi\nKOMPASSI-SISALTO\n" + "k" * 30_000)
        (ad / "faktat.md").write_text("# Faktat\nFAKTA-SISALTO\n" + "f" * 30_000)
        self.ad = str(ad)
        self.alue = yksityinen_alue.yksityinen_alue(r / "yks")
        self.alue.valmista()
        self.osuma = tee_tiivistelma(self.alue.polku("tiivistelmat"), 1,
                                     [("muuttokuorma lauantaina", "HAKU-KANARIA: Tony muuttaa lauantaina.")])
        tee_tiivistelma(self.alue.polku("tiivistelmat"), 2, [("kahvi ja pulla", "TIIV-KANARIA: muu tiivistelma.")])
        haku.rakenna(self.alue)

    def tila(self, **kw):
        tila = types.SimpleNamespace(agenttidata=self.ad, yks_muisti=str(self.kirjasto),
                                     yks_tiivistelmat=str(self.alue.polku("tiivistelmat")), roolit={},
                                     korjaukset=chat.korjaukset.valmistele(str(self.r / "korjaukset")),
                                     odottavat_ehdotustiedostot=lambda: [], **kw)
        chat.korjaukset.tallenna(tila.korjaukset, "k1", 1, "vanha vastaus", "vaarin",
                                 next(iter(chat.korjaukset.LUOKAT)), "KORJAUS-KANARIA muuttokuorma perjantaina")
        return tila

    def muisti(self, tila, malli=ISO, kysymys="muuttokuorma?"):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            muisti, tiedostot = chat.yksityinen_muisti(tila, kysymys, H, "o", malli, yhdistelma.OLETUS)
        return muisti, tiedostot, err.getvalue()


class MuistiRajaTesti(Muisti):
    def test_oletusraja_pitaa(self):
        muisti, _, _ = self.muisti(self.tila())
        self.assertLessEqual(len(muisti), 40_000)
        self.assertGreater(len(muisti), 30_000)        # raja kaytetaan, ei tyhjenneta

    def test_asetus_pienentaa(self):
        for m in (4_000, 12_000):
            with self.subTest(m=m):
                muisti, tiedostot, _ = self.muisti(self.tila(muisti_max=m))
                self.assertLessEqual(len(muisti), m)
                self.assertEqual(tiedostot[0], "tiivistelmat/%s.json" % self.osuma)

    def test_ylaraja_palauttaa_kontekstirajan(self):
        muisti, _, _ = self.muisti(self.tila(muisti_max=yo.MUISTI_MAX_YLARAJA))
        self.assertGreater(len(muisti), 300_000)

    def test_lokirivi_kertoo_koon_ja_rajan(self):
        muisti, _, err = self.muisti(self.tila())
        konteksti = yo.muistin_kontekstiraja(ISO, "o", H)
        self.assertIn("yksityinen muisti: %d merkkia, raja 40000 (kontekstiraja %d, asetus 40000)"
                      % (len(muisti), konteksti), err)
        for kanaria in ("KANARIA", "muistio-", "kompassi", "muuttokuorma"):
            self.assertNotIn(kanaria, err)

    def test_paikallinen_ei_kayta_asetusta_eika_lokia(self):
        muisti, _, err = self.muisti(self.tila(muisti_max=4_000), malli=None)
        self.assertNotIn("yksityinen muisti:", err)
        self.assertGreater(len(muisti), 4_000)          # paikallinen raja yksityinen.MUISTI_YLARAJA ennallaan


class JarjestysTesti(Muisti):
    def test_jarjestys(self):
        """Hakuosumat, Tonyn korjaukset, agenttidata (paatokset), kirjasto, tiivistelmat (A1123)."""
        for m in (12_000, 40_000):
            with self.subTest(m=m):
                muisti, tiedostot, _ = self.muisti(self.tila(muisti_max=m))
                paikat = [muisti.index(k) for k in ("HAKU-KANARIA", "KORJAUS-KANARIA", "KOMPASSI-SISALTO",
                                                    "muistio 39 ")]
                self.assertEqual(paikat, sorted(paikat), m)
                self.assertEqual(tiedostot[0], "tiivistelmat/%s.json" % self.osuma)
                self.assertEqual(tiedostot[1], chat.korjaukset.LAHDE_NIMI)
                self.assertTrue(tiedostot[2].startswith("agenttidata/"), tiedostot[:4])

    def test_tiivistelmat_lopussa(self):
        muisti, _, _ = self.muisti(self.tila())          # kahvi-tiivistelma ei ole hakuosuma
        self.assertIn("TIIV-KANARIA", muisti)
        self.assertGreater(muisti.index("TIIV-KANARIA"), muisti.index("muistio 39 "))

    def test_korjaus_sailyy_pienella_rajalla(self):
        """Iso agenttidata ei syrjayta Tonyn korjausta, kun raja on pieni."""
        muisti, _, _ = self.muisti(self.tila(muisti_max=4_000))
        self.assertIn("KORJAUS-KANARIA", muisti)


class ItsetarkistusTesti(Muisti):
    def test_lahderaja_rajattu(self):
        taysi = yo.tarkastajan_lahderaja(ISO)
        raja = yo.tarkastajan_lahderaja(ISO, 40_000, "ohje")
        self.assertGreater(taysi, 500_000)
        self.assertEqual(raja, 40_000 + len(yo.KEHOTE) + len("ohje") + kr.JARJESTELMA_LISA + yo.LAHTEET_KESKUSTELU_MAX)
        self.assertLess(raja, 100_000)
        pieni = "qwen/qwen3-14b"
        self.assertLessEqual(yo.tarkastajan_lahderaja(pieni, yo.MUISTI_MAX_YLARAJA, "o"), yo.tarkastajan_lahderaja(pieni))

    def kutsut(self, muisti_max):
        tila = self.tila(muisti_max=muisti_max)
        muisti, _, _ = self.muisti(tila)
        kutsut = []

        def kysy(m, v, **kw):
            kutsut.append(v)
            return json.dumps([{"kohta": "2026", "syy": "ei tukea"}]) if len(kutsut) == 1 else "korjattu"
        with mock.patch.object(yo, "_kysy_viestit", kysy):
            yo.tarkista_vastaus(muisti, H, "o", "Vuonna 2026 asia on niin.", vastaaja=ISO, tarkastaja=ISO,
                                muisti_max=muisti_max)
        return muisti, kutsut

    def test_tarkastaja_ja_korjaus_rajassa(self):
        muisti, kutsut = self.kutsut(12_000)
        self.assertEqual(len(kutsut), 2)
        lahteet = kutsut[0][1]["content"]
        self.assertLessEqual(len(lahteet), yo.tarkastajan_lahderaja(ISO, 12_000, "o") + 20_000)   # + vastaus ja otsikot
        self.assertIn("HAKU-KANARIA", lahteet)
        jarjestelma = kutsut[1][0]["content"]                  # korjauskutsu: sama muisti, enintaan asetus
        self.assertTrue(jarjestelma.split(chat.itsetarkistus.MUISTI_OTSIKKO, 1)[1].startswith(muisti))
        self.assertNotIn("muistio-", jarjestelma.split(muisti, 1)[1])         # ei lisamuistia korjausrooliin
        self.assertLessEqual(len(muisti), 12_000)

    def test_tila_valittaa_asetuksen(self):
        with tempfile.TemporaryDirectory() as d:
            tila = chat.Tila(salasana_apu.tiiviste("oikea-salasana-123"), d, d, ["localhost"], yks_data=d + "/y",
                             taustapaa="openrouter", or_malli=ISO, itsetarkistus="paalla", muisti_max="9000")
            with mock.patch.object(yo, "tarkista_vastaus", lambda *a, **kw: kw) as _:
                kw = tila.tarkista_yks("m", H, "o", "vastaus", ISO, 1)
        self.assertEqual(kw["muisti_max"], 9_000)


class ValimuistiLokiTesti(unittest.TestCase):
    def test_cached_tokens_lokiin(self):
        err = io.StringIO()
        data = {"usage": {"prompt_tokens": 20_000, "completion_tokens": 500, "cost": 0.04,
                          "prompt_tokens_details": {"cached_tokens": 1_200, "cache_write_tokens": 0}}}
        with contextlib.redirect_stderr(err):
            yo.loki_toteutunut(ISO, data)
        self.assertIn("prompt_tokens=20000, completion_tokens=500, cached_tokens=1200, cache_write_tokens=0", err.getvalue())

    def test_ilman_tietoa_ei_kenttaa(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            yo.loki_toteutunut(ISO, {"usage": {"prompt_tokens": 5, "prompt_tokens_details": {"cached_tokens": True}}})
        self.assertNotIn("cached_tokens", err.getvalue())


if __name__ == "__main__":
    unittest.main()
