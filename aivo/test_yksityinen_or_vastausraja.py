"""Testit A1095: OpenRouter-taustapaan vastausraja 8 000 tokenia, chatin aikaraja ja katkenneen vastauksen huomautus.
Ei verkkoa, ei oikeita avaimia."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aivo import chat, mallivertailu, openrouter_kulut as ok, yhdistelma, yksityinen, yksityinen_or as yo

MALLI = "meta-llama/llama-3.3-70b-instruct"
AVAIN = "sk-testi-" + "x" * 30          # keksitty, ei oikea avain
NYT = datetime(2026, 11, 25, 12, 0, tzinfo=ok.TZ)
HISTORIA = [{"rooli": "tony", "teksti": "moi"}]
SALAINEN = "SALAINEN-SISALTO-123"


class FeikkiVastaus:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def vastaus(teksti=" Hei! ", finish_reason="stop"):
    return {"choices": [{"message": {"content": teksti}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.001}}


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
        self.rungot, self.ajat = [], []

    def avaa(self, data=None):
        def avaa(pyynto, timeout=None):
            self.rungot.append(json.loads(pyynto.data))
            self.ajat.append(timeout)
            return FeikkiVastaus(data or vastaus())
        return avaa

    def yhteiset(self, data=None):
        return dict(avain_tiedosto=str(self.avain), kulutila=str(self.kulut), avaa=self.avaa(data), nyt=lambda: NYT)

    def kysy(self, data=None):
        return yo.kysy_openrouterilta("muisti", HISTORIA, "ohje", malli=MALLI, **self.yhteiset(data))


class RajaTesti(Pohja):
    def test_vakiot(self):
        self.assertEqual(yo.MAX_TOKENIA, 8_000)
        self.assertEqual(yksityinen.MAX_TOKENIA, 700)          # paikallinen loopback-malli ennallaan
        self.assertEqual(mallivertailu.MAX_TOKENIA, 700)       # vertailu ennallaan
        self.assertEqual(ok.PAIVAKATTO_EUR, 10)                # katto ei muutu

    def test_openrouter_chat_pyytaa_8000(self):
        self.kysy()
        [runko] = self.rungot
        self.assertEqual(runko["max_tokens"], 8_000)

    def test_taustatyo_pyytaa_8000(self):
        yo.kysy_taustatyo(MALLI, [{"role": "user", "content": "x"}], aikaraja_s=60, **self.yhteiset())
        self.assertEqual(self.rungot[0]["max_tokens"], 8_000)

    def test_max_tokens_parametri_ei_ylita_rajaa(self):
        yo._kysy_viestit(MALLI, [{"role": "user", "content": "x"}], max_tokens=10**6, **self.yhteiset())
        yo._kysy_viestit(MALLI, [{"role": "user", "content": "x"}], max_tokens=200, **self.yhteiset())
        self.assertEqual([r["max_tokens"] for r in self.rungot], [8_000, 200])

    def test_loopback_pyytaa_700(self):
        rungot = []

        def avaa(pyynto, timeout=None):
            rungot.append(json.loads(pyynto.data))
            return FeikkiVastaus({"choices": [{"message": {"content": "ok"}}]})
        yksityinen.kysy_paikalliselta("muisti", HISTORIA, "", "http://127.0.0.1:8081/v1/chat/completions", avaa=avaa)
        self.assertEqual(rungot[0]["max_tokens"], 700)

    def test_mallivertailu_kayttaa_omaa_rajaa(self):
        lahde = Path(mallivertailu.__file__).read_text(encoding="utf-8")
        self.assertIn("max_tokens=MAX_TOKENIA", lahde)
        self.assertNotIn("max_tokens=yksityinen_or.MAX_TOKENIA", lahde)

    def test_varaus_ei_riipu_max_tokensista(self):
        """Varaus on kiintea VARAUS_USD (0,50 USD); 8 000 tokenin pyynto varaa saman verran kuin ennen."""
        self.kysy()
        varaukset = [json.loads(r) for r in (self.kulut / ok.KULUT).read_text().splitlines()]
        self.assertTrue(any(r.get("varaus") and r["usd"] == float(ok.VARAUS_USD) for r in varaukset))
        self.assertEqual(ok.VARAUS_USD, ok.VARO_USD_KUTSU)


class AikarajaTesti(Pohja):
    def test_chat_kutsun_aikaraja(self):
        self.kysy()
        self.assertEqual(self.ajat, [yo.CHAT_AIKARAJA_S])
        self.assertEqual(yo.CHAT_AIKARAJA_S, 360)

    def test_aikaraja_riittaa_8000_tokenille(self):
        # hidas avoin malli noin 25 tokenia/s + kehotteen kasittely enintaan 30 s
        self.assertGreaterEqual(yo.CHAT_AIKARAJA_S, yo.MAX_TOKENIA / 25 + 30)

    def test_muut_reitit_ennallaan(self):
        self.assertEqual(yo.VASTAUS_AIKARAJA_S, 120)
        yo._kysy_viestit(MALLI, [{"role": "user", "content": "x"}], **self.yhteiset())
        yo.kysy_tiivistys("ohje", "data", malli=MALLI, **self.yhteiset())
        self.assertEqual(self.ajat, [120, 120])

    def test_yhdistelma_ei_saa_chatin_rajaa(self):
        self.assertLess(yhdistelma.AIKARAJA_S, yo.CHAT_AIKARAJA_S)
        yo._kysy_viestit(MALLI, [{"role": "user", "content": "x"}], aikaraja_s=500, **self.yhteiset())
        self.assertEqual(self.ajat, [120])


class KatkeaminenTesti(Pohja):
    def test_length_lisaa_huomautuksen_ja_lokirivin_ilman_sisaltoa(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            v = self.kysy(vastaus(SALAINEN + " kesken", "length"))
        self.assertTrue(v.startswith(SALAINEN))
        self.assertTrue(v.endswith("\n\n" + yo.KATKENNUT_HUOMAUTUS))
        self.assertIn("katkesi pituusrajaan", err.getvalue())
        self.assertNotIn(SALAINEN, err.getvalue())
        self.assertNotIn(AVAIN, err.getvalue())

    def test_stop_ei_huomautusta(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.kysy(vastaus("valmis", "stop")), "valmis")
            self.assertEqual(self.kysy({"choices": [{"message": {"content": "ok"}}]}), "ok")
        self.assertEqual(err.getvalue(), "")

    def test_yhdistelman_osakutsuun_ei_huomautusta(self):
        with contextlib.redirect_stderr(io.StringIO()):
            v = yo._kysy_viestit(MALLI, [{"role": "user", "content": "x"}], max_tokens=200,
                                 **self.yhteiset(vastaus("VAATIVA", "length")))
        self.assertEqual(v, "VAATIVA")

    def test_huomautus_sailyy_chatin_jalkikasittelyssa(self):
        """Chat ajaa vastauksen merkintojen, valintojen ja lahteiden kasittelyn lapi; huomautus jaa nakyviin."""
        v = "Pitk\u00e4 vastaus kesken\n\n" + yo.KATKENNUT_HUOMAUTUS
        v = yksityinen.neutraloi_merkinnat(yksityinen.irrota_ehdotukset(v, lambda n, t: "x"))
        v, _ = chat.erota_valinnat(v)
        v, _ = chat.erota_paatosehdotus(v, [])
        v, tunn = chat.tarkista_lahteet(v, [])
        v = chat.tyhjan_paikka(v, False)
        self.assertTrue(v.endswith(yo.KATKENNUT_HUOMAUTUS))
        self.assertEqual(tunn, [])

    def test_katkesi_pituusrajaan_sietaa_oudon_rungon(self):
        for data in ({}, {"choices": []}, {"choices": ["x"]}, None, {"choices": [{"finish_reason": "stop"}]}):
            self.assertFalse(yo.katkesi_pituusrajaan(data))
        self.assertTrue(yo.katkesi_pituusrajaan({"choices": [{"finish_reason": "length"}]}))


if __name__ == "__main__":
    unittest.main()
