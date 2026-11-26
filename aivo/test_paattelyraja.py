"""Paattelyn ylaraja (reasoning.max_tokens) ja yksi uusinta ilman paattelya, kun vastaus katkeaa ennen tekstia.
Stdlib unittest. Ei verkkoa, ei mallikutsuja, ei oikeita avaimia: kuljetin on feikki ja kulukirjanpito tilapainen."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from aivo import chat, openrouter_kulut as ok, openrouter_zdr, salasana_apu, yhdistelma, yksityinen_or as yo

UUSI = "qwen/qwen3.8-2.4t-a95b"            # paattely pakollinen, tasot xhigh/medium/low (oletus xhigh)
QWEN35 = "qwen/qwen3.5-397b-a17b"          # paattely valinnainen, tasoja ei kerrota
Q27 = "qwen/qwen3.8-27b"                   # paattely valinnainen, taso "none" tuettu
R1 = "deepseek/deepseek-r1-0528"           # paattely pakollinen, tasoja ei kerrota
MAVERICK = "meta-llama/llama-4-maverick"   # ei reasoning-parametria
AVAIN = "sk-testi-" + "x" * 30             # keksitty, ei oikea avain
NYT = datetime(2026, 11, 26, 19, 43, tzinfo=ok.TZ)
H = [{"rooli": "tony", "teksti": "Mit\u00e4 tied\u00e4t minusta?"}]


def vastaus(teksti="Hei!", finish="stop", kulu=0.001):
    return {"choices": [{"message": {"content": teksti}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": kulu}}


TYHJA = vastaus("", "length", 0.0834)       # loki 26.11.: koko raja paattelyyn, ei tekstia


class FeikkiVastaus:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Pohja(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.avain = self.d / "avain"
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.rungot = []
        self.err = io.StringIO()

    def avaa(self, *vastaukset):
        jono = list(vastaukset)

        def avaa(pyynto, timeout=None):
            self.rungot.append(json.loads(pyynto.data))
            return FeikkiVastaus(jono.pop(0) if len(jono) > 1 else jono[0])
        return avaa

    def yhteiset(self, *vastaukset):
        return dict(avain_tiedosto=str(self.avain), kulutila=str(self.kulut), avaa=self.avaa(*vastaukset),
                    nyt=lambda: NYT)

    def kysy(self, malli, *vastaukset, **kw):
        with contextlib.redirect_stderr(self.err):
            return yo.kysy_openrouterilta("muisti", H, "ohje", malli=malli, **self.yhteiset(*vastaukset), **kw)


class AsetusTesti(unittest.TestCase):
    def test_oletus(self):
        self.assertEqual(yo.PAATTELY_MAX_OLETUS, 2_000)
        for arvo in (None, "", "  "):
            self.assertEqual(yo.tarkista_paattely_max(arvo), 2_000)

    def test_asetus_ja_rajat(self):
        self.assertEqual(yo.tarkista_paattely_max("0"), 0)
        self.assertEqual(yo.tarkista_paattely_max(" 6000 "), 6_000)
        self.assertEqual(yo.tarkista_paattely_max(1500), 1_500)

    def test_virheellinen_estaa(self):
        for arvo in ("-1", "6001", "abc", "2e3", "1.5", True):
            with self.subTest(arvo=arvo), self.assertRaises(chat.ChatVirhe):
                yo.tarkista_paattely_max(arvo)

    def test_tila_ja_valitsin(self):
        with tempfile.TemporaryDirectory() as d:
            def tila(**kw):
                return chat.Tila(salasana_apu.tiiviste("oikea-salasana-123"), d, d, ["localhost"], yks_data=d + "/y",
                                 taustapaa="openrouter", or_malli=UUSI, **kw)
            self.assertEqual(tila().paattely_max, 2_000)
            self.assertEqual(tila(paattely_max="0").paattely_max, 0)
            with self.assertRaises(chat.ChatVirhe):
                tila(paattely_max="7000")
        lahde = Path(chat.__file__).read_text(encoding="utf-8")
        self.assertIn('"--yksityinen-paattely-max", default=os.environ.get("AIVO_YKSITYINEN_PAATTELY_MAX")', lahde)
        self.assertIn("paattely_max=a.yksityinen_paattely_max", lahde)
        # itsetarkistus saa chatin todellisen kutsumaaran (uusinta mukaan lukien)
        self.assertIn('getattr(vastaus, "kutsuja", 1)', lahde)

    def test_tila_valittaa_asetuksen_tarkistukselle(self):
        with tempfile.TemporaryDirectory() as d:
            tila = chat.Tila(salasana_apu.tiiviste("oikea-salasana-123"), d, d, ["localhost"], yks_data=d + "/y",
                             taustapaa="openrouter", or_malli=UUSI, itsetarkistus="paalla", paattely_max="1200")
            with mock.patch.object(yo, "tarkista_vastaus", lambda *a, **kw: kw):
                kw = tila.tarkista_yks("m", H, "o", "vastaus", UUSI, 1)
        self.assertEqual(kw["paattely_max"], 1_200)


class RajaTesti(unittest.TestCase):
    def test_tukitaulu_vain_sallittuja_malleja(self):
        for m in yo.PAATTELY_TUKI:
            self.assertTrue(openrouter_zdr.avoin_malli(m), m)
        self.assertNotIn(MAVERICK, yo.PAATTELY_TUKI)

    def test_raja_aina_alle_max_tokens(self):
        for max_tokens in (1, 2, 200, 800, 1_500, 2_000, 4_000, 8_000):
            for asetus in (1, 2_000, 6_000):
                raja = yo.paattelyraja(UUSI, max_tokens, asetus)
                self.assertLess(raja, max_tokens)
                self.assertGreaterEqual(max_tokens - raja, max(1, min(yo.PAATTELY_VASTAUSVARA, max_tokens // 2)))

    def test_raja_arvot(self):
        self.assertEqual(yo.paattelyraja(UUSI, 8_000), 2_000)
        self.assertEqual(yo.paattelyraja(UUSI, 8_000, 6_000), 6_000)       # vastaukselle jaa 2 000
        self.assertEqual(yo.paattelyraja(UUSI, 1_500), 750)                # tarkastaja: puolet
        self.assertEqual(yo.paattelyraja(UUSI, 8_000, 0), 0)
        self.assertEqual(yo.paattelyraja(MAVERICK, 8_000), 0)


class ChatTesti(Pohja):
    def test_oletus_lahettaa_rajan(self):
        teksti = self.kysy(UUSI, vastaus())
        [runko] = self.rungot
        self.assertEqual(runko["max_tokens"], 8_000)
        self.assertEqual(runko["reasoning"], {"max_tokens": 2_000, "exclude": True})
        self.assertLess(runko["reasoning"]["max_tokens"], runko["max_tokens"])
        self.assertEqual(runko["provider"]["zdr"], True)                  # ZDR ennallaan
        self.assertEqual(runko["provider"]["data_collection"], "deny")
        self.assertEqual(teksti, "Hei!")
        self.assertEqual(teksti.kutsuja, 1)
        self.assertIn("vastaus enintaan 8000, paattely enintaan 2000", self.err.getvalue())

    def test_asetus_nolla_ei_parametria(self):
        self.kysy(UUSI, vastaus(), paattely_max=0)
        [runko] = self.rungot
        self.assertNotIn("reasoning", runko)
        self.assertIn("paattely enintaan 0", self.err.getvalue())

    def test_ei_tuettu_malli_ilman_parametria(self):
        self.assertEqual(self.kysy(MAVERICK, vastaus()), "Hei!")
        [runko] = self.rungot
        self.assertNotIn("reasoning", runko)

    def test_uusinta_kerran_pakollinen_malli(self):
        teksti = self.kysy(UUSI, TYHJA, vastaus("Vastaus."))
        self.assertEqual(len(self.rungot), 2)
        self.assertEqual(self.rungot[1]["reasoning"], {"effort": "low", "exclude": True})
        self.assertEqual(self.rungot[1]["max_tokens"], 8_000)
        self.assertEqual(teksti, "Vastaus.")
        self.assertEqual(teksti.kutsuja, 2)
        loki = self.err.getvalue()
        self.assertIn("uusinta kerran ilman paattelya (reasoning effort=low)", loki)
        self.assertNotIn("Vastaus.", loki)                                # ei sisaltoa journaliin
        self.assertNotIn("Mit\u00e4 tied\u00e4t", loki)

    def test_uusinta_valinnainen_malli(self):
        self.kysy(QWEN35, TYHJA, vastaus())
        self.assertEqual(self.rungot[1]["reasoning"], {"enabled": False})
        self.rungot.clear()
        self.kysy(Q27, TYHJA, vastaus())
        self.assertEqual(self.rungot[1]["reasoning"], {"effort": "none", "exclude": True})

    def test_uusinta_vain_kerran(self):
        with self.assertRaises(yo.VastausKatkesi):
            self.kysy(UUSI, TYHJA)                    # aina tyhja
        self.assertEqual(len(self.rungot), 2)
        self.assertIn("uusintakin katkesi", self.err.getvalue())

    def test_ei_uusintaa_ilman_hyotya(self):
        for malli, kw in ((R1, {}), (MAVERICK, {}), (UUSI, {"paattely_max": 0})):
            with self.subTest(malli=malli, **kw):
                self.rungot.clear()
                with self.assertRaises(yo.VastausKatkesi):
                    self.kysy(malli, TYHJA, **kw)
                self.assertEqual(len(self.rungot), 1)

    def test_kutsuraja_estaa_uusinnan(self):
        with mock.patch.object(yhdistelma, "MAX_KUTSUT_VIESTI", 1), self.assertRaises(yo.VastausKatkesi):
            self.kysy(UUSI, TYHJA)
        self.assertEqual(len(self.rungot), 1)
        self.assertIn("uusintaa ei tehty (kutsuraja)", self.err.getvalue())

    def test_paivakatto_estaa_uusinnan(self):
        kallis = vastaus("", "length", 50.0)          # yli 10 EUR/vrk katon: seuraava kutsu estetaan
        with self.assertRaises(yhdistelma.Katkaisu):
            self.kysy(UUSI, kallis, vastaus())
        self.assertEqual(len(self.rungot), 1)
        self.assertEqual(ok.PAIVAKATTO_EUR, 10)

    def test_osakutsu_ei_uusi(self):
        with contextlib.redirect_stderr(self.err), self.assertRaises(yo.VastausKatkesi):
            yo._kysy_viestit(UUSI, [{"role": "user", "content": "x"}], **self.yhteiset(TYHJA, vastaus()))
        self.assertEqual(len(self.rungot), 1)
        self.assertEqual(self.rungot[0]["reasoning"]["max_tokens"], 2_000)


class TarkistusTesti(Pohja):
    def test_tarkastaja_ja_korjaus_saavat_rajan(self):
        tarkastaja = vastaus(json.dumps({"kohdat": [{"kohta": "x", "syy": "y"}]}))
        with contextlib.redirect_stderr(self.err):
            tulos = yo.tarkista_vastaus("muisti", H, "ohje", "Tony asuu Espoossa vuodesta 2020.", vastaaja=UUSI,
                                        **self.yhteiset(tarkastaja, vastaus("Korjattu.")))
        self.assertEqual(len(self.rungot), 2, tulos.merkinta)
        tark, korj = self.rungot
        self.assertEqual(tark["reasoning"], {"max_tokens": tark["max_tokens"] // 2, "exclude": True})
        self.assertLess(tark["reasoning"]["max_tokens"], tark["max_tokens"])
        self.assertEqual(korj["reasoning"], {"max_tokens": 2_000, "exclude": True})

    def test_tarkastaja_ei_uusi(self):
        with contextlib.redirect_stderr(self.err):
            tulos = yo.tarkista_vastaus("muisti", H, "ohje", "Tony asuu Espoossa vuodesta 2020.", vastaaja=UUSI,
                                        **self.yhteiset(TYHJA))
        self.assertEqual(len(self.rungot), 1, tulos.merkinta)


if __name__ == "__main__":
    unittest.main()
