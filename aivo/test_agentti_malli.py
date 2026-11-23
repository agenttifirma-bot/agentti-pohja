"""Testit aivo/agentti/malli.py:lle (mallikytkenta ja roolit). Korvikemalli: feikkikuljetin, ei verkkoa, ei oikeita avaimia."""
import inspect
import json
import os
import socket
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

from aivo import openrouter_kulut as ok, yksityinen_or
from aivo.agentti import malli as am

MALLI = "meta-llama/llama-3.3-70b-instruct"
MALLI2 = "qwen/qwen3-235b-a22b-2507"
AVAIN = "sk-testi-" + "y" * 30          # keksitty, ei oikea avain
NYT = datetime(2026, 11, 23, 12, 0, tzinfo=ok.TZ)
LOPPU = '[[TYOKALU {"nimi": "valmis", "arg": {"raportti": "Kirjoitin tiedoston tulos.md."}}]]'
KIRJOITA = '[[TYOKALU {"nimi": "kirjoita", "arg": {"polku": "tulos.md", "sisalto": "hei"}}]]'


def _rooli(runko):
    eka = runko["messages"][0]["content"]
    for rooli, kehote in (("suunnittelija", am.SUUNNITTELIJA_KEHOTE), ("tekija", am.TEKIJA_KEHOTE),
                          ("tarkastaja", am.TARKASTAJA_KEHOTE)):
        if eka == kehote:
            return rooli
    raise AssertionError("tuntematon kehote")


class Vastaus:
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
        self.tyo = self.d / "tyo"
        self.tyo.mkdir(mode=0o700)
        self.rungot = []           # (rooli, runko)
        self.vastaukset = {"suunnittelija": ["1. Kirjoita tulos.md. Valmis kun tiedosto on olemassa."],
                           "tekija": [KIRJOITA, LOPPU], "tarkastaja": ["ARVIO: hyvaksytty\nRaportti vastaa lokia."]}
        self.kulu_usd = 0.001
        self.aika = [0.0]
        self.askel_s = 0.0
        # ei verkkoa: mika tahansa socket-yritys kaataa testin
        estin = mock.patch.object(socket, "socket", side_effect=AssertionError("verkko kielletty testeissa"))
        estin.start()
        self.addCleanup(estin.stop)

    def avaa(self, pyynto, timeout=None):
        runko = json.loads(pyynto.data)
        rooli = _rooli(runko)
        self.rungot.append((rooli, runko))
        self.aika[0] += self.askel_s
        jono = self.vastaukset[rooli]
        teksti = jono.pop(0) if len(jono) > 1 else jono[0]
        return Vastaus({"choices": [{"message": {"content": teksti}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": self.kulu_usd}})

    def aja(self, roolit=MALLI, **kw):
        arg = dict(avain_tiedosto=str(self.avain), kulutila=str(self.kulut), avaa=self.avaa, nyt=lambda: NYT,
                   kello=lambda: self.aika[0])
        arg.update(kw)
        return am.aja("Kirjoita tiedosto tulos.md.", str(self.tyo), roolit, **arg)

    def kulurivit(self):
        p = self.kulut / ok.KULUT
        return [json.loads(r) for r in p.read_text().splitlines()] if p.exists() else []

    def roolit(self):
        return [r for r, _ in self.rungot]


class KulkuTesti(Pohja):
    def test_roolit_oikeassa_jarjestyksessa_ja_valmis(self):
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.VALMIS, ""))
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija", "tarkastaja"])
        self.assertEqual(t.kutsuja, 4)
        self.assertEqual(t.tarkastus["arvio"], am.HYVAKSYTTY)
        self.assertEqual((self.tyo / "tulos.md").read_text(), "hei")
        self.assertIn("Kirjoita tulos.md", (self.tyo / am.SUUNNITELMA_TIEDOSTO).read_text())

    def test_jokainen_runko_zdr_ja_yksityinen_malli(self):
        self.aja(roolit={"suunnittelija": MALLI2, "tekija": MALLI, "tarkastaja": MALLI2})
        self.assertEqual([r["model"] for _, r in self.rungot], [MALLI2, MALLI, MALLI, MALLI2])
        for _, runko in self.rungot:
            self.assertIs(runko["provider"]["zdr"], True)
            self.assertEqual(runko["provider"]["data_collection"], "deny")

    def test_kutsut_kulkevat_kulut_kutsun_kautta_lipulla(self):
        with mock.patch.object(ok, "kutsu", wraps=ok.kutsu) as m:
            self.aja()
        self.assertEqual(m.call_count, 4)
        for c in m.call_args_list:
            self.assertIs(c.kwargs["yksityinen_chat"], True)

    def test_kulut_kirjataan_yhteiseen_kirjanpitoon_roolin_tunnisteella(self):
        t = self.aja()
        toteutuneet = [r for r in self.kulurivit() if not r.get("varaus")]
        self.assertEqual([r["tehtava"] for r in toteutuneet],
                         ["aivo-agentti:suunnittelija", "aivo-agentti:tekija", "aivo-agentti:tekija",
                          "aivo-agentti:tarkastaja"])
        self.assertAlmostEqual(t.kulu_eur, float(ok.USD_EUR) * 0.004, places=6)
        self.assertFalse(t.kulu_tuntematon)

    def test_oletuskulutila_on_yhteinen_kirjanpito(self):
        self.assertIsNone(inspect.signature(am.aja).parameters["kulutila"].default)

    def test_korjauskierros_kerran(self):
        self.vastaukset["tarkastaja"] = ["ARVIO: korjattava\nLisaa otsikko.", "ARVIO: hyvaksytty\nOk."]
        self.vastaukset["tekija"] = [KIRJOITA, LOPPU, KIRJOITA, LOPPU]
        t = self.aja()
        self.assertEqual(t.tila, am.VALMIS)
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija", "tarkastaja", "tekija", "tekija",
                                         "tarkastaja"])
        korjaus = self.rungot[4][1]["messages"][1]["content"]
        self.assertIn("Lisaa otsikko.", korjaus)

    def test_toinen_korjattava_ei_anna_toista_korjauskierrosta(self):
        self.vastaukset["tarkastaja"] = ["ARVIO: korjattava\nEi viela."]
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEN, "tarkastaja: korjattava"))
        self.assertEqual(self.roolit().count("tarkastaja"), 2)

    def test_hylatty_ja_muodoton_arvio_eivat_ole_valmis(self):
        for teksti in ("ARVIO: hylatty\nVaitteet puuttuvat lokista.", "Hyvalta nayttaa!"):
            with self.subTest(teksti=teksti):
                self.vastaukset["tarkastaja"] = [teksti]
                self.vastaukset["tekija"] = [KIRJOITA, LOPPU]
                t = self.aja()
                self.assertEqual((t.tila, t.syy), (am.KESKEN, "tarkastaja: hylatty"))

    def test_tarkastaja_saa_lokin_ja_tiedostolistan(self):
        self.aja()
        viesti = [r for rooli, r in self.rungot if rooli == "tarkastaja"][0]["messages"][1]["content"]
        self.assertIn("kirjoita ok", viesti)
        self.assertIn("f tulos.md 3", viesti)
        self.assertIn("Kirjoitin tiedoston tulos.md.", viesti)

    def test_tulos_on_json_eika_sisalla_avainta(self):
        d = self.aja().sanakirja()
        teksti = json.dumps(d)
        self.assertNotIn(AVAIN, teksti)
        self.assertEqual(d["rajat"], {"askelraja": 30, "tekija_askelraja": 24, "korjaus_askelraja": 6,
                                      "aikaraja_s": 1200})
        self.assertEqual(d["mallit"], {"suunnittelija": MALLI, "tekija": MALLI, "tarkastaja": MALLI})
        self.assertEqual(d["askelia"], 2)


class KattoTesti(Pohja):
    def _tayta_katto(self):
        rivi = {"aika": NYT.isoformat(), "malli": MALLI, "tehtava": "aivo-yksityinen", "usd": 11.0}
        (self.kulut / ok.KULUT).write_text(json.dumps(rivi) + "\n")

    def test_tysi_katto_estaa_ennen_ensimmaista_kutsua(self):
        self._tayta_katto()
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "paivakatto"))
        self.assertEqual(self.rungot, [])

    def test_katto_tayttyy_kesken_tekijan_silmukan(self):
        self.vastaukset["tekija"] = [KIRJOITA]
        self.kulu_usd = 4.0             # 4 USD * 0.92 = 3.68 EUR per kutsu -> katto (10 EUR) taynna 3 kutsun jalkeen
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "paivakatto"))
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija"])
        self.assertEqual(t.kutsuja, 4)       # neljas yritys estettiin ennen lahetysta

    def test_katon_arvoa_ei_ole_tassa_moduulissa(self):
        lahde = Path(am.__file__).read_text(encoding="utf-8")
        self.assertNotIn("PAIVAKATTO", lahde)
        self.assertNotIn("katto", "".join(inspect.signature(am.aja).parameters).lower())


class RajaTesti(Pohja):
    def test_vakiot(self):
        self.assertEqual((am.ASKELRAJA, am.TEKIJA_ASKELRAJA, am.KORJAUS_ASKELRAJA, am.AIKARAJA_S), (30, 24, 6, 1200))
        lahde = Path(am.__file__).read_text(encoding="utf-8")
        self.assertNotIn("environ", lahde)
        self.assertNotIn("getenv", lahde)
        self.assertFalse([p for p in inspect.signature(am.aja).parameters if "raja" in p.lower()])

    def test_tekijan_askelraja(self):
        self.vastaukset["tekija"] = ["ei lohkoa"]
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "askelraja"))
        self.assertEqual(self.roolit().count("tekija"), am.TEKIJA_ASKELRAJA)
        self.assertEqual(t.kutsuja, 1 + am.TEKIJA_ASKELRAJA)

    def test_kokonaisaskelraja_rajaa_korjauskierroksen(self):
        # 1 + 24 + 1 = 26 kutsua; korjaukselle jaa 30 - 26 - 1 = 3 (ei 6), ja viimeinen kutsu jaa tarkastajalle
        self.vastaukset["tekija"] = ["ei lohkoa"] * 23 + [LOPPU, "ei lohkoa"]
        self.vastaukset["tarkastaja"] = ["ARVIO: korjattava\nx"]
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "askelraja"))
        self.assertLessEqual(t.kutsuja, am.ASKELRAJA)
        self.assertEqual(self.roolit().count("tekija"), 24 + 3)

    def test_korjauskierroksen_askelraja(self):
        self.vastaukset["tekija"] = [KIRJOITA, LOPPU, "ei lohkoa"]
        self.vastaukset["tarkastaja"] = ["ARVIO: korjattava\nx"]
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "askelraja"))
        self.assertEqual(self.roolit().count("tekija"), 2 + am.KORJAUS_ASKELRAJA)

    def test_kokonaisaskelraja_estaa_kutsun_ennen_lahetysta(self):
        k = am._Kutsuja({r: MALLI for r in am.ROOLIT}, AVAIN, str(self.kulut), self.avaa, lambda: NYT, None,
                        lambda: 0.0, am.AIKARAJA_S)
        k.tila.kutsuja = am.ASKELRAJA
        with self.assertRaises(am._Keskeytys):
            k.kysy("tarkastaja", [{"role": "system", "content": am.TARKASTAJA_KEHOTE}])
        self.assertEqual((k.tila.keskeytys, self.rungot, self.kulurivit()), ("askelraja", [], []))

    def test_aikaraja(self):
        self.vastaukset["tekija"] = ["ei lohkoa"]
        self.askel_s = 100.0
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "aikaraja"))
        self.assertEqual(len(self.rungot), am.AIKARAJA_S // 100)

    def test_aikaraja_ennen_tarkastajaa(self):
        self.vastaukset["tekija"] = [LOPPU]
        self.askel_s = 600.0            # suunnittelija 600 s + tekija 600 s = 1200 s
        t = self.aja()
        self.assertEqual((t.tila, t.syy), (am.KESKEYTETTY, "aikaraja"))
        self.assertNotIn("tarkastaja", self.roolit())

    def test_kuljettimen_aikaraja_on_jaljella_oleva_aika(self):
        ajat = []
        self.askel_s = 550.0           # kolmannella kutsulla aikaa on jaljella 1200 - 2 * 550 = 100 s

        def avaa(pyynto, timeout=None):
            ajat.append(timeout)
            return self.avaa(pyynto, timeout)
        self.aja(avaa=avaa)
        self.assertEqual(ajat[0], yksityinen_or.VASTAUS_AIKARAJA_S)
        self.assertEqual(ajat[2], 100.0)


class AvainTesti(Pohja):
    def tarkista_virhe(self, t, osa):
        self.assertEqual(t.tila, am.VIRHE)
        self.assertIn(osa, t.syy)
        self.assertNotIn(AVAIN, t.syy)
        self.assertEqual(self.rungot, [])
        self.assertEqual(self.kulurivit(), [])        # ei varausta kirjanpitoon

    def test_puuttuva_avain(self):
        self.tarkista_virhe(self.aja(avain_tiedosto=str(self.d / "ei-ole")), "avain puuttuu")

    def test_tyhja_avain(self):
        self.avain.write_text("")
        self.tarkista_virhe(self.aja(), "tyhja")

    def test_liian_laajat_oikeudet(self):
        os.chmod(self.avain, 0o644)
        self.tarkista_virhe(self.aja(), "0600")

    def test_vaaran_nakoinen_avain(self):
        self.avain.write_text("lyhyt\n")
        self.tarkista_virhe(self.aja(), "avaimen nakoinen")

    def test_linkki_hylataan(self):
        linkki = self.d / "linkki"
        linkki.symlink_to(self.avain)
        self.tarkista_virhe(self.aja(avain_tiedosto=str(linkki)), "linkki")

    def test_chatin_avainta_ei_kayteta(self):
        with mock.patch.object(yksityinen_or, "OLETUS_AVAIN", str(self.avain)):
            self.tarkista_virhe(self.aja(), "chatin avainta")

    def test_oletuspolku_on_agenttien_oma(self):
        self.assertEqual(am.OLETUS_AVAIN, "/var/lib/aivo-agentit/openrouter-avain")
        self.assertNotEqual(am.OLETUS_AVAIN, yksityinen_or.OLETUS_AVAIN)
        self.assertEqual(inspect.signature(am.aja).parameters["avain_tiedosto"].default, am.OLETUS_AVAIN)

    def test_hylatty_avain_http_virhe_ei_vuoda_avainta(self):
        def avaa(pyynto, timeout=None):
            raise urllib.error.HTTPError(pyynto.full_url, 401, "Unauthorized " + AVAIN, {}, None)
        t = self.aja(avaa=avaa)
        self.assertEqual(t.tila, am.VIRHE)
        self.assertIn("HTTP 401", t.syy)
        self.assertNotIn(AVAIN, json.dumps(t.sanakirja()))


class RoolitTesti(unittest.TestCase):
    def test_yksi_malli_kaikille(self):
        self.assertEqual(am.tarkista_roolit(MALLI), {r: MALLI for r in am.ROOLIT})

    def test_roolimuoto(self):
        r = am.tarkista_roolit("suunnittelija:%s, tekija:%s, tarkastaja:%s" % (MALLI2, MALLI, MALLI2))
        self.assertEqual(r, {"suunnittelija": MALLI2, "tekija": MALLI, "tarkastaja": MALLI2})

    def test_hylatyt_asetukset(self):
        for asetus in ("", None, "qwen/qwen3.7-max", MALLI + ":free", "openai/gpt-4o",
                       "suunnittelija:%s" % MALLI,
                       "suunnittelija:%s,tekija:%s,tarkastaja:%s,tekija:%s" % ((MALLI,) * 4),
                       "suunnittelija:%s,tekija:%s,arvioija:%s" % ((MALLI,) * 3)):
            with self.subTest(asetus=asetus):
                with self.assertRaises(am.AgenttiVirhe):
                    am.tarkista_roolit(asetus)

    def test_arvion_jasennys(self):
        self.assertEqual(am._arvio("ARVIO: hyv\u00e4ksytty\nok")[0], am.HYVAKSYTTY)
        self.assertEqual(am._arvio("\n**Arvio: korjattava**\nx"), (am.KORJATTAVA, "x"))
        for teksti in ("", "ARVIO: hyvaksytty, mutta", "Raportti on hyva.\nARVIO: hyvaksytty"):
            self.assertEqual(am._arvio(teksti)[0], am.HYLATTY, teksti)

    def test_virheellinen_rooliasetus_ei_kutsu(self):
        with mock.patch.object(ok, "kutsu", side_effect=AssertionError("ei saa kutsua")):
            t = am.aja("x", "/ei-ole", "openai/gpt-4o")
        self.assertEqual(t.tila, am.VIRHE)


if __name__ == "__main__":
    unittest.main()
