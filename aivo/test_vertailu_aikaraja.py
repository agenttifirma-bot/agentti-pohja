"""Mallivertailun kuljettimen aikaraja (#450): sama raja kuin tuotannon chatissa 8 000 tokenin vastausrajalla,
aikakatkaisu omana luokkanaan "aikaraja" (ei "vaarin") ja lista-muotoinen content. Ei verkkoa, ei mallikutsuja."""
from __future__ import annotations

import contextlib
import io
import socket
import unittest
import urllib.error
from unittest import mock

from aivo import itsetuntemus as it, mallivertailu as mv, yksityinen, yksityinen_or as yo
from aivo.test_ajattelevat_mallit import AJATTELEVA, AVAIN, TAVALLINEN, Tilapainen, or_vastaus, tehdas

ZDR_RUNKO = {"provider": {"zdr": True, "data_collection": "deny"}}


def nostaja(virhe):
    def avaa(pyynto, timeout=None):
        nostaja.timeout = timeout
        raise virhe
    return avaa


class VakioTesti(unittest.TestCase):
    def test_vertailun_aikaraja_on_tuotannon_chatin_raja(self):
        self.assertEqual(mv.VERTAILU_AIKARAJA_S, yo.CHAT_AIKARAJA_S)
        self.assertEqual(mv.VERTAILU_AIKARAJA_S, 360)
        self.assertEqual(mv.AJATTELU_MAX_TOKENIA, yo.MAX_TOKENIA)       # sama vastausraja kuin chatissa
        self.assertEqual(yo.VASTAUS_AIKARAJA_S, 120)                     # muiden kayttajien oletus ennallaan

    def test_kuljetin_tehdas_valittaa_aikarajan(self):
        kutsut = []
        with mock.patch.object(yo, "tee_kuljetin", lambda avain, **kw: kutsut.append(kw) or (lambda r: r)):
            laheta = mv.kuljetin_tehdas(AVAIN)()
        self.assertEqual(kutsut, [{"ylaraja_s": mv.VERTAILU_AIKARAJA_S}])
        self.assertTrue(callable(laheta))

    def test_oikea_kuljetin_kayttaa_360_s(self):
        aikarajat = []

        def avaa(pyynto, timeout=None):
            aikarajat.append(timeout)
            raise socket.timeout("salainen-osoite")
        opener = mock.Mock(open=avaa)
        with mock.patch.object(yo.urllib.request, "build_opener", return_value=opener):
            laheta = mv.kuljetin_tehdas(AVAIN)()
            with self.assertRaises(yo.Aikakatkaisu) as k:
                laheta(dict(ZDR_RUNKO))
        self.assertEqual(aikarajat, [360])
        self.assertNotIn("salainen", str(k.exception))

    def test_main_kayttaa_tehdasta_molemmissa_ajoissa(self):
        tehdyt = []
        with mock.patch.object(yo, "lue_avain", return_value=AVAIN), \
                mock.patch.object(mv, "kuljetin_tehdas", lambda a: tehdyt.append(a) or (lambda: None)), \
                mock.patch.object(mv, "aja", return_value={}) as aja, \
                mock.patch.object(mv, "aja_itsetuntemus", return_value={}) as itse, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mv.main(["aja", "--ulos", "/nonexistent/x", "--mallit", TAVALLINEN]), 0)
            self.assertEqual(mv.main(["itse-aja", "--ulos", "/nonexistent/x", "--mallit", TAVALLINEN,
                                      "--vahvista"]), 0)
        self.assertEqual(tehdyt, [AVAIN, AVAIN])
        aja.assert_called_once()
        itse.assert_called_once()


class KuljetinTesti(unittest.TestCase):
    def test_aikakatkaisu_on_oma_aliluokka(self):
        for virhe in (TimeoutError("x"), socket.timeout("x"), urllib.error.URLError(TimeoutError("x"))):
            with self.assertRaises(yo.Aikakatkaisu) as k:
                yo.tee_kuljetin(AVAIN, nostaja(virhe))(dict(ZDR_RUNKO))
            self.assertIsInstance(k.exception, yksityinen.YksityinenVirhe)   # muut kutsujat ennallaan
            self.assertTrue(str(k.exception).startswith("mallipalvelu ei vastannut ("))

    def test_muu_verkkovirhe_ei_ole_aikakatkaisu(self):
        for virhe in (ConnectionRefusedError("x"), urllib.error.URLError(ConnectionRefusedError("x")), ValueError("x")):
            with self.assertRaises(yksityinen.YksityinenVirhe) as k:
                yo.tee_kuljetin(AVAIN, nostaja(virhe))(dict(ZDR_RUNKO))
            self.assertNotIsInstance(k.exception, yo.Aikakatkaisu)


class ListaContentTesti(unittest.TestCase):
    def test_tekstiosat_yhdistetaan_ennen_tyhjyyden_tarkistusta(self):
        osat = [{"type": "text", "text": " Hei"}, {"type": "reasoning", "text": "salaa"}, " maailma. "]
        t = mv.vastauksen_tiedot(or_vastaus(content=osat))
        self.assertEqual((t["vastaus"], t["tyhja"]), ("Hei maailma.", False))

    def test_lista_ilman_tekstia_on_tyhja(self):
        for osat in ([], [{"type": "image_url", "image_url": {"url": "x"}}], [{"type": "text", "text": "  "}],
                     [{"type": "text", "text": None}, 5]):
            t = mv.vastauksen_tiedot(or_vastaus(content=osat, finish="length"))
            self.assertEqual((t["vastaus"], t["tyhja"]), ("", True), osat)

    def test_muu_tyyppi_on_tyhja(self):
        t = mv.vastauksen_tiedot(or_vastaus(content={"text": "x"}))
        self.assertEqual((t["vastaus"], t["tyhja"]), ("", True))


class VertailuAikarajaTesti(Tilapainen):
    def test_aikakatkaisu_on_oma_luokka_ja_sarake(self):
        def vastaa(r):
            if r["model"] == AJATTELEVA:
                raise yo.Aikakatkaisu("mallipalvelu ei vastannut (TimeoutError)")
            return or_vastaus("Vastaus.")
        yv = mv.aja([TAVALLINEN, AJATTELEVA], self.ulos, tehdas([], vastaa), toistot=1,
                    kulutila=str(self.kulut), loki=self.loki.append)
        self.assertEqual((yv["aikaraja"], yv["virheita"]), (2, 2))      # 2 perakkain ohittaa mallin kuten ennen
        rivit = [r for r in mv.lue_vastaukset(self.ulos) if r["malli"] == AJATTELEVA]
        self.assertEqual([(r["virhe"], r["aikaraja"]) for r in rivit], [("Aikakatkaisu", True)] * 2)
        self.assertTrue(any("aikaraja (360 s)" in l for l in self.loki))
        tulos = mv.pisteet(self.ulos)
        self.assertEqual(tulos[AJATTELEVA]["aikaraja"], 2)
        self.assertIsNone(tulos[AJATTELEVA]["yhteensa"])                  # ei 0 pistetta
        self.assertEqual(tulos[TAVALLINEN]["aikaraja"], 0)
        taulu = mv.taulukko(tulos).splitlines()
        self.assertIn("| Aikaraja |", taulu[0])
        rivi = [x for x in taulu if x.startswith("| " + AJATTELEVA)][0]
        self.assertIn("| 0/2 | 2/2 |", rivi)

    def test_muu_virhe_on_edelleen_nolla(self):
        def vastaa(r):
            raise yksityinen.YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP 500)")
        mv.aja([TAVALLINEN], self.ulos, tehdas([], vastaa), toistot=1, kulutila=str(self.kulut), loki=self.loki.append)
        rivit = mv.lue_vastaukset(self.ulos)
        self.assertTrue(rivit and all("aikaraja" not in r for r in rivit))
        tulos = mv.pisteet(self.ulos)[TAVALLINEN]
        self.assertEqual((tulos["aikaraja"], tulos["yhteensa"]), (0, 0.0))


class ItseAikarajaTesti(Tilapainen):
    def aja(self, mallit, vastaa, **kw):
        yv = mv.aja_itsetuntemus(mallit, self.ulos, tehdas([], vastaa), kulutila=str(self.kulut),
                                 loki=self.loki.append, **kw)
        return yv, it.lue_vastaukset(self.ulos)

    def test_aikakatkaisu_ei_ole_vaarin(self):
        def vastaa(r):
            raise TimeoutError("salainen-osoite")
        yv, rivit = self.aja([AJATTELEVA], vastaa)
        self.assertEqual(len(rivit), 2)                                    # 2 perakkain: malli ohitetaan
        self.assertEqual(yv["aikaraja"], 2)
        t = it.pisteet(rivit)[AJATTELEVA]
        self.assertEqual((t["luokat"]["aikaraja"], t["luokat"]["vaarin"], t["yhteensa"]), (2, 0, None))
        taulu = it.taulukko({AJATTELEVA: t})
        self.assertIn("| Ei vastausta | Aikaraja |", taulu)
        self.assertNotIn("salainen", (self.ulos / "vastaukset.jsonl").read_text(encoding="utf-8"))

    def test_muu_virhe_on_vaarin(self):
        def vastaa(r):
            raise yksityinen.YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP 500)")
        _, rivit = self.aja([AJATTELEVA], vastaa)
        t = it.pisteet(rivit)[AJATTELEVA]
        self.assertEqual((t["luokat"]["aikaraja"], t["luokat"]["vaarin"]), (0, 2))

    def test_yhdistelma_kaikki_jasenet_aikarajaan(self):
        jasenet = [TAVALLINEN, AJATTELEVA, "deepseek/deepseek-chat-v3.1"]

        def vastaa(r):
            raise yo.Aikakatkaisu("mallipalvelu ei vastannut (TimeoutError)")
        yv, rivit = self.aja(jasenet, vastaa, kokoaja=AJATTELEVA)
        self.assertTrue(rivit and all(r.get("aikaraja") is True and r["virhe"] == "ei vastauksia" for r in rivit))
        self.assertEqual(yv["jasenten_aikarajat"], 3 * len(rivit))
        t = it.pisteet(rivit)[mv.itse_yhdistelman_nimi(jasenet, AJATTELEVA)]
        self.assertEqual((t["luokat"]["aikaraja"], t["luokat"]["vaarin"]), (len(rivit), 0))

    def test_yhdistelma_jasenen_aikaraja_ja_muu_virhe_on_vaarin(self):
        jasenet = [TAVALLINEN, AJATTELEVA, "deepseek/deepseek-chat-v3.1"]

        def vastaa(r):
            if r["model"] == TAVALLINEN:
                raise yo.Aikakatkaisu("mallipalvelu ei vastannut (TimeoutError)")
            raise yksityinen.YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP 500)")
        _, rivit = self.aja(jasenet, vastaa, kokoaja=AJATTELEVA)
        self.assertTrue(rivit and all("aikaraja" not in r for r in rivit))
        self.assertTrue(all(o.get("aikaraja") is True for r in rivit for o in r["osat"] if o["malli"] == TAVALLINEN))


if __name__ == "__main__":
    unittest.main()
