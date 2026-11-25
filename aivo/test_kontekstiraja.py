"""Testit A1106: OpenRouter-taustapaan kehoteraja mallin kontekstin mukaan (aivo/kontekstiraja.py).

Raja seuraa mallia, vastaukselle varattu tila sailyy, paikallisen taustapaan rajat ovat ennallaan, muisti ei syrjayta
historiaa ja kehotteen koko nakyy lokissa ja kulunakymassa ilman sisaltoa. Ei verkkoa, ei oikeita avaimia."""
import contextlib
import io
import json
import os
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

from aivo import chat, kontekstiraja as kr, openrouter_kulut as ok, yhdistelma, yksityinen, yksityinen_or as yo

ISO = "qwen/qwen3-235b-a22b-2507"          # 262 144 tokenia
PIENI = "qwen/qwen3-14b"                   # 40 960 tokenia
PIKKU = "google/gemma-2-27b-it"            # 8 192 tokenia: vastausvaraus rajautuu
KALLIS = "qwen/qwen3.8-2.4t-a95b"          # 2 USD/Mtok sisaan: hintaraja leikkaa
AVAIN = "sk-testi-" + "x" * 30              # keksitty, ei oikea avain
NYT = datetime(2026, 11, 25, 12, 0, tzinfo=ok.TZ)
SALAINEN = "SALAINEN-SISALTO-123"
VARAUS = float(ok.VARAUS_USD)


def historia(n, pituus=1_000):
    return [{"rooli": "tony" if i % 2 == 0 else "aivo", "teksti": ("v%d " % i) + "x" * pituus} for i in range(n)]


class FeikkiVastaus:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def vastaus(teksti="Hei"):
    return {"choices": [{"message": {"content": teksti}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1234, "completion_tokens": 56, "cost": 0.002}}


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

    def avaa(self, pyynto, timeout=None):
        self.rungot.append(json.loads(pyynto.data))
        return FeikkiVastaus(vastaus())

    def yhteiset(self):
        return dict(avain_tiedosto=str(self.avain), kulutila=str(self.kulut), avaa=self.avaa, nyt=lambda: NYT)

    def kysy(self, malli, muisti, hist, ohjeet="ohje"):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            yo.kysy_openrouterilta(muisti, hist, ohjeet, malli=malli, **self.yhteiset())
        return self.rungot[-1], err.getvalue()


class TaulukkoTesti(unittest.TestCase):
    def test_taulukko_kattaa_avoimet_mallit(self):
        puuttuu = {"meta-llama/llama-3.2-1b-instruct", "qwen/qwen3.5-122b-a10b"}   # ei ZDR-endpointtia 25.11.2026
        self.assertLessEqual(set(kr.KONTEKSTIT), set(ok.AVOIMET_MALLIT))
        self.assertEqual(set(ok.AVOIMET_MALLIT) - set(kr.KONTEKSTIT), puuttuu)

    def test_tuntematon_saa_varovaisen_oletuksen(self):
        for m in ("meta-llama/llama-3.2-1b-instruct", "ei/olemassa", ""):
            self.assertEqual(kr.konteksti(m), kr.OLETUS_KONTEKSTI)
            self.assertEqual(kr.hinta(m), kr.OLETUSHINTA_USD_MTOK)
        self.assertLessEqual(kr.OLETUS_KONTEKSTI, min(k for k, _, _ in kr.KONTEKSTIT.values() if k >= 32_768))

    def test_katto(self):
        self.assertTrue(all(kr.konteksti(m) <= kr.KONTEKSTI_KATTO for m in ok.AVOIMET_MALLIT))
        self.assertEqual(kr.konteksti(ISO), 262_144)

    def test_moduuli_ei_tuo_openrouter_moduuleja(self):
        teksti = Path(kr.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import openrouter", teksti)
        self.assertNotIn("from . import", teksti)


class RajaSeuraaMalliaTesti(unittest.TestCase):
    def test_suurempi_konteksti_suurempi_raja(self):
        iso, pieni = kr.syote_merkit(ISO, yo.MAX_TOKENIA, VARAUS), kr.syote_merkit(PIENI, yo.MAX_TOKENIA, VARAUS)
        self.assertGreater(iso, 4 * pieni)
        self.assertGreater(iso, 500_000)          # noin 228 000 tokenia * 2,5 merkkia
        self.assertGreater(iso, yksityinen.MUISTI_YLARAJA + yksityinen.HISTORIA_MERKIT_YLARAJA)

    def test_yhdistelma_pienimman_mukaan(self):
        self.assertEqual(kr.syote_merkit([ISO, PIENI], yo.MAX_TOKENIA, VARAUS),
                         kr.syote_merkit(PIENI, yo.MAX_TOKENIA, VARAUS))
        self.assertEqual(yo.yhdistelman_mallit(ISO, {"tarkastaja": PIENI, "vastaaja": ISO}), [ISO, PIENI])
        self.assertEqual(yo.yhdistelman_lisavaraus(yhdistelma.OLETUS), 0)
        self.assertGreaterEqual(yo.yhdistelman_lisavaraus("rinnakkais"), 2 * yhdistelma.VASTAUS_MAX_MERKKIA)


class VastausvarausTesti(Pohja):
    def test_vastaukselle_ja_marginaalille_jaa_tila(self):
        for m in list(ok.AVOIMET_MALLIT) + ["ei/olemassa"]:
            k = kr.konteksti(m)
            v = kr.vastausvaraus(m, yo.MAX_TOKENIA)
            s = kr.syote_tokenit(m, yo.MAX_TOKENIA, VARAUS)
            self.assertLessEqual(s + v, int(k * (1 - kr.MARGINAALI)), m)
            self.assertGreater(s, 0, m)

    def test_iso_malli_saa_taydet_8000(self):
        self.assertEqual(kr.vastausvaraus(ISO, yo.MAX_TOKENIA), 8_000)
        self.assertEqual(kr.vastausvaraus(PIKKU, yo.MAX_TOKENIA), 8_192 // 4)

    def test_pieni_malli_max_tokens_rajautuu_rungossa(self):
        self.kysy(PIKKU, "m", historia(1, 10))
        self.assertEqual(self.rungot[-1]["max_tokens"], 2_048)
        self.kysy(ISO, "m", historia(1, 10))
        self.assertEqual(self.rungot[-1]["max_tokens"], 8_000)

    def test_hinta_mahtuu_varaukseen(self):
        for m in ok.AVOIMET_MALLIT:
            s = kr.syote_tokenit(m, yo.MAX_TOKENIA, VARAUS)
            self.assertLessEqual(kr.arvioi_usd(m, s, kr.vastausvaraus(m, yo.MAX_TOKENIA)), VARAUS + 1e-9, m)
        self.assertLess(kr.syote_tokenit(KALLIS, yo.MAX_TOKENIA, VARAUS), kr.syote_tokenit(KALLIS, yo.MAX_TOKENIA))
        self.assertEqual(yo.VARAUS_USD_ARVIO, VARAUS)


class HistoriaTesti(Pohja):
    def test_iso_malli_vie_pitkan_historian_kokonaan(self):
        h = historia(150, 3_000)                 # 450 000 merkkia: vanha 80 000 raja olisi lyhentanyt
        runko, _ = self.kysy(ISO, "muisti", h)
        sisallot = [v["content"] for v in runko["messages"][1:]]
        self.assertEqual(len(sisallot), 150)
        self.assertFalse(any("lyhennetty" in t for t in sisallot))

    def test_pieni_malli_mahtuu_kontekstiin(self):
        h = historia(150, 3_000)
        runko, _ = self.kysy(PIENI, "muisti", h)
        merkit = kr.viestien_merkit(runko["messages"])
        self.assertLessEqual(merkit, kr.syote_merkit(PIENI, yo.MAX_TOKENIA, VARAUS))
        self.assertTrue(runko["messages"][-1]["content"].startswith("v149 "))      # uusin viesti kokonaan
        self.assertEqual(len(runko["messages"][-1]["content"]), len(h[-1]["teksti"]))

    def test_viestimaara_rajataan(self):
        runko, _ = self.kysy(ISO, "m", historia(yo.HISTORIA_YLARAJA + 30, 10))
        self.assertEqual(len(runko["messages"]), 1 + yo.HISTORIA_YLARAJA)

    def test_yhdistelma_varaa_roolisyotteen(self):
        h = historia(150, 3_000)
        raja_yksi = yo.historian_merkkiraja(ISO, "m", "o", h)
        raja_yhd = yo.historian_merkkiraja(yo.yhdistelman_mallit(ISO, {"tarkastaja": PIENI}), "m", "o", h,
                                           yo.YHDISTELMA_LISAVARAUS)
        self.assertLess(raja_yhd, raja_yksi)
        self.assertLessEqual(raja_yhd + yo.YHDISTELMA_LISAVARAUS, kr.syote_merkit(PIENI, yo.MAX_TOKENIA, VARAUS))


class MuistiEiSyrjaytaHistoriaaTesti(unittest.TestCase):
    def test_historialle_jaa_vahimmaisosuus(self):
        h = historia(150, 3_000)
        tarve = sum(len(v["teksti"]) + kr.VIESTI_LISA for v in h)
        raja = yo.muistin_merkkiraja(PIENI, "o", h)
        kaikki = kr.syote_merkit(PIENI, yo.MAX_TOKENIA, VARAUS) - len(yo.KEHOTE) - len("o") - kr.JARJESTELMA_LISA
        self.assertGreater(tarve, kaikki)
        self.assertGreaterEqual(kaikki - raja, int(kaikki * kr.HISTORIA_VAHIMMAISOSUUS))
        self.assertGreater(raja, 0)

    def test_lyhyt_historia_ei_vie_muistin_tilaa(self):
        h = historia(1, 10)
        raja = yo.muistin_merkkiraja(ISO, "o", h)
        kaikki = kr.syote_merkit(ISO, yo.MAX_TOKENIA, VARAUS) - len(yo.KEHOTE) - len("o") - kr.JARJESTELMA_LISA
        per_viesti = kr.VIESTI_LISA + len(yksityinen.LYHENNETTY % 10 ** 7)     # sama kuin historian_merkkiraja
        self.assertEqual(kaikki - raja, len(h[0]["teksti"]) + per_viesti)

    def test_liian_pieni_tila_ei_negatiivinen(self):
        self.assertEqual(kr.muistiraja(PIKKU, yo.MAX_TOKENIA, 10 ** 7, 0), 0)
        self.assertEqual(kr.historiaraja(PIKKU, yo.MAX_TOKENIA, 10 ** 7), 0)


class SuojattuViestiTesti(unittest.TestCase):
    """Katselmoinnin havainto: uusin Tonyn viesti (enintaan 16 000 merkkia) sailyy aina kokonaan, joten sen pitaa
    mahtua historian osuuteen myos pienella mallilla, kun muisti on taynna."""

    def koko(self, malli, ohjeet):
        h = historia(9, 2_000) + [{"rooli": "tony", "teksti": "u" * 16_000}]
        muisti = "m" * yo.muistin_merkkiraja(malli, ohjeet, h)
        v = yksityinen.muodosta_viestit(muisti, h, ohjeet, yo.KEHOTE, yo.HISTORIA_YLARAJA,
                                        yo.historian_merkkiraja(malli, muisti, ohjeet, h))
        self.assertEqual(v[-1]["content"], "u" * 16_000)
        return kr.viestien_merkit(v)            # otsikot ovat jo jarjestelmaviestin sisallossa

    def test_mahtuu_kontekstiin(self):
        for m in ("mistralai/mistral-small-24b-instruct-2501", "qwen/qwen3-32b", "ei/olemassa", PIENI, ISO):
            self.assertLessEqual(self.koko(m, "o" * 20_000), kr.syote_merkit(m, yo.MAX_TOKENIA, VARAUS), m)

    def test_ei_mahdu_muisti_nolla(self):
        h = [{"rooli": "tony", "teksti": "u" * 16_000}]
        self.assertEqual(yo.muistin_merkkiraja(PIKKU, "o" * 20_000, h), 0)


class ChatMuistiTesti(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.kirjasto = Path(self._t.name) / "muisti"
        self.kirjasto.mkdir()
        for i in range(40):                      # 40 x 8 000 = 320 000 merkkia
            p = self.kirjasto / ("muistio-%02d.md" % i)
            p.write_text("muistio %d " % i + "y" * 8_000, encoding="utf-8")
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        (self.kirjasto / "osuma.md").write_text("kissa " + "z" * 100, encoding="utf-8")
        os.utime(self.kirjasto / "osuma.md", (1_600_000_000, 1_600_000_000))     # vanhin, mutta osuu

    def tila(self):
        return types.SimpleNamespace(agenttidata=None, yks_muisti=str(self.kirjasto), yks_tiivistelmat=None, roolit={})

    def test_paikallinen_raja_ennallaan(self):
        self.assertEqual((yksityinen.MUISTI_YLARAJA, yksityinen.HISTORIA_YLARAJA, yksityinen.HISTORIA_MERKIT_YLARAJA,
                          yksityinen.MAX_TOKENIA), (16_000, 12, 24_000, 700))
        muisti, tiedostot = chat.yksityinen_muisti(self.tila(), "kissa", historia(1, 10), "o", None, yhdistelma.OLETUS)
        self.assertLessEqual(len(muisti), yksityinen.MUISTI_YLARAJA + 1_000)
        self.assertEqual(tiedostot[0], "osuma.md")

    def test_openrouter_vie_koko_muistin(self):
        muisti, tiedostot = chat.yksityinen_muisti(self.tila(), "kissa", historia(1, 10), "o", ISO, yhdistelma.OLETUS)
        self.assertEqual(len(tiedostot), 41)
        self.assertGreater(len(muisti), 320_000)
        self.assertEqual(tiedostot[0], "osuma.md")                    # muistihaun osuma ensin
        self.assertEqual(tiedostot[1:4], ["muistio-39.md", "muistio-38.md", "muistio-37.md"])   # sitten tuoreimmat

    def test_otsikot_lasketaan_rajaan(self):
        for i in range(300):
            (self.kirjasto / ("pieni-%03d.md" % i)).write_text("p", encoding="utf-8")
        raja = yo.muistin_merkkiraja(PIENI, "o", historia(1, 10))
        muisti, _ = chat.yksityinen_muisti(self.tila(), "kissa", historia(1, 10), "o", PIENI, yhdistelma.OLETUS)
        self.assertLessEqual(len(muisti), raja)

    def test_pieni_malli_leikkaa_vanhimmat(self):
        muisti, tiedostot = chat.yksityinen_muisti(self.tila(), "kissa", historia(1, 10), "o", PIENI, yhdistelma.OLETUS)
        raja = yo.muistin_merkkiraja(PIENI, "o", historia(1, 10))
        self.assertLessEqual(len(muisti), raja + 1_000)
        self.assertIn("muistio-39.md", tiedostot)
        self.assertNotIn("muistio-00.md", tiedostot)
        self.assertEqual(tiedostot[0], "osuma.md")


class LokiTesti(Pohja):
    def test_loki_kertoo_koon_ja_hinnan_ilman_sisaltoa(self):
        _, err = self.kysy(ISO, SALAINEN, [{"rooli": "tony", "teksti": SALAINEN}], SALAINEN)
        self.assertIn("yksityinen_or: kehote ", err)
        self.assertIn("tokenia", err)
        self.assertIn("arvioitu hinta enintaan", err)
        self.assertIn("toteutunut prompt_tokens=1234", err)
        self.assertIn("cost=0.0020 USD", err)
        self.assertNotIn(SALAINEN, err)
        self.assertNotIn(AVAIN, err)

    def test_loki_kehote_arvio(self):
        with contextlib.redirect_stderr(io.StringIO()):
            t = yo.loki_kehote(ISO, [{"role": "user", "content": "x" * 2_500}], 8_000)
        self.assertEqual(t["tokenit_arvio"], kr.arvioi_tokenit(2_500 + kr.VIESTI_LISA))
        self.assertAlmostEqual(t["usd_arvio"], kr.arvioi_usd(ISO, t["tokenit_arvio"], 8_000))


class KulunakymaTesti(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        rivit = [{"aika": NYT.isoformat(timespec="seconds"), "malli": ISO, "tehtava": yo.TEHTAVA, "usd": 0.01,
                  "tokenit_in": t, "tokenit_out": 10} for t in (1_000, 3_000)]
        rivit.append({"aika": NYT.isoformat(timespec="seconds"), "malli": ISO, "tehtava": yo.TIIVISTYS_TEHTAVA,
                      "usd": 0.5, "tokenit_in": 99_999, "tokenit_out": 10})
        (Path(self._t.name) / ok.KULUT).write_text("".join(json.dumps(r) + "\n" for r in rivit), encoding="utf-8")

    def test_chatin_kehotteen_koko(self):
        y = chat.kulut_yhteenveto(self._t.name, NYT, chat.lue_kulukerroin("0.92"))
        k = y["tanaan"]["kehote"]
        self.assertEqual((k["kutsuja"], k["tokenit_in_ka"], k["tokenit_in_max"]), (2, 2_000, 3_000))
        self.assertEqual(k["per_kutsu"]["usd"], 0.01)

    def test_kehoterajat(self):
        r = chat.kehoterajat((ISO, PIKKU), chat.lue_kulukerroin("0.92"))
        self.assertEqual(r[ISO]["konteksti"], 262_144)
        self.assertEqual(r[ISO]["kehote_tokenit_max"], kr.syote_tokenit(ISO, yo.MAX_TOKENIA, VARAUS))
        self.assertEqual(r[PIKKU]["vastaus_tokenit_max"], 2_048)
        self.assertLessEqual(r[ISO]["taysi_kehote"]["usd"], VARAUS)
        self.assertEqual(chat.kehoterajat((), chat.lue_kulukerroin("0.92")), {})


if __name__ == "__main__":
    unittest.main()
