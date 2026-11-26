"""Yhdistelman testit (#447 + #450): itse-viikon vastattu-laskenta ohittaa tyhjat vastaukset ja aikakatkaisut,
itse-viikko kayttaa kuljetin_tehdas-funktiota (vertailun aikaraja), ja _itse_kutsu palauttaa seka vastauksen
tiedot etta kulun varaluvun. Ei verkkoa eika mallikutsuja: kuljetin on feikki ja kulukirjanpito tilapainen."""
import io
import math
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from aivo import mallivertailu as mv, openrouter_kulut as ok, yksityinen_or
from aivo.test_itsetuntemus_viikko import PAA, Pohja, tehdas

MALLI = "feikki/malli"


def yv(mallit):
    return {"mallit": mallit, "virheita": 0, "kulut_usd": 0.0, "raja_usd": 1.0, "pysahtyi": None}


def tulos(m):
    return {m: {"yhteensa": 1.0, "lajit": {}, "luokat": {}, "kulu": 0.0, "mediaani_s": 1.0}}


class VastattuTesti(unittest.TestCase):
    def rivi(self, rivit, kysymyksia):
        return mv._itse_viikko_rivi("2026-11-29T01:30:00+00:00", {"paamalli": MALLI}, yv([MALLI]), tulos(MALLI),
                                    kysymyksia, rivit)

    def test_tyhja_ja_aikaraja_eivat_ole_vastattuja(self):
        rivit = [{"malli": MALLI, "vastaus": "Hyva vastaus."},
                 {"malli": MALLI, "vastaus": "", "tyhja": True, "finish_reason": "length"},
                 {"malli": MALLI, "vastaus": "", "aikaraja": True},
                 {"malli": MALLI, "virhe": "Aikakatkaisu", "aikaraja": True}]
        r = self.rivi(rivit, 4)
        self.assertEqual(r["mallit"][MALLI]["vastattu"], 1)
        self.assertTrue(r["kesken"])

    def test_kaikki_vastatut_ei_kesken(self):
        rivit = [{"malli": MALLI, "vastaus": "a", "tyhja": False}, {"malli": MALLI, "vastaus": "b"}]
        r = self.rivi(rivit, 2)
        self.assertEqual(r["mallit"][MALLI]["vastattu"], 2)
        self.assertFalse(r["kesken"])


class ItseViikkoPaastaPaahanTesti(Pohja):
    def test_tyhjat_vastaukset_tekevat_ajosta_kesken(self):
        rivi = self.aja({"AIVO_OPENROUTER_MALLIT": PAA}, tehdas=tehdas(teksti=""))
        self.assertEqual(rivi["mallit"][PAA]["vastattu"], 0)
        self.assertTrue(rivi["kesken"])

    def test_kulun_varaluku_ja_vastauksen_tiedot_samassa_rivissa(self):
        kaytto = {"prompt_tokens": 1000, "completion_tokens": 50}            # usage.cost puuttuu
        tulos_ = mv._itse_kutsu(PAA, [{"role": "user", "content": "x"}], tehdas(teksti=" Vastaus. ", kaytto=kaytto),
                                str(self.kulut), lambda: 0.0)
        self.assertEqual((tulos_["vastaus"], tulos_["tyhja"]), ("Vastaus.", False))
        self.assertIn("finish_reason", tulos_)
        self.assertIn("ajatteli", tulos_)
        odotus = ok.arvioi_usd(PAA, 1000, 50)
        self.assertTrue(math.isfinite(tulos_["kulu_usd"]) and tulos_["kulu_usd"] > 0)
        self.assertAlmostEqual(tulos_["kulu_usd"], float(odotus))


class ItseViikkoKuljetinTesti(Pohja):
    def test_itse_viikko_kayttaa_kuljetin_tehdasta(self):
        tehdyt = []
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(mv, "kuljetin_tehdas", lambda a: tehdyt.append(a) or tehdas()), \
                mock.patch.object(ok, "OLETUS_TILA", str(self.kulut)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = mv.main(["itse-viikko", "--ulos", str(self.ulos), "--tiivistelma", str(self.tiiv)],
                         env={"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual(rc, 0)
        self.assertEqual(tehdyt, ["x" * 20])

    def test_itse_viikon_kuljetin_saa_vertailun_aikarajan(self):
        kw_lista = []

        def tee(avain, **kw):
            kw_lista.append(kw)
            return tehdas()()
        out = io.StringIO()
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(yksityinen_or, "tee_kuljetin", tee), \
                mock.patch.object(ok, "OLETUS_TILA", str(self.kulut)), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = mv.main(["itse-viikko", "--ulos", str(self.ulos), "--tiivistelma", str(self.tiiv)],
                         env={"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual(rc, 0)
        self.assertTrue(kw_lista)
        self.assertTrue(all(kw == {"ylaraja_s": mv.VERTAILU_AIKARAJA_S} for kw in kw_lista), kw_lista)
        self.assertIn('"kesken": false', out.getvalue())


if __name__ == "__main__":
    unittest.main()
