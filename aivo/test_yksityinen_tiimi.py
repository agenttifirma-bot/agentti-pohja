"""Yhdistelma 'tiimi' (A1040, A1041): kevyt luokittelee, keskustelija vastaa tai antaa tehtavan ajattelijalle.

Testit kayttavat korvikemallia (yhdistelma.aja) tai oikeaa kutsupolkua (yksityinen_or + openrouter_kulut), jossa vain
verkkoyhteys on korvattu. Ne kaatuvat ilman tiimi-yhdistelmaa.
"""
from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from aivo import chat, openrouter_kulut as ok, yhdistelma as yh, yksityinen, yksityinen_or as yo

M1 = "qwen/qwen3-235b-a22b-2507"               # keskustelija
M2 = "meta-llama/llama-3.3-70b-instruct"       # ajattelija
M3 = "mistralai/mistral-small-3.1-24b-instruct"  # kevyt
AVAIN = "sk-testi-" + "x" * 30                 # keksitty, ei oikea avain
SALASANA = "oikea-salasana-123"
NYT = datetime(2026, 11, 22, 12, 0, tzinfo=ok.TZ)
PERUS = [{"role": "system", "content": "KEHOTE muisti: salainen-muistio"},
         {"role": "user", "content": "Tee rakennusohje varastolle."}]
ROOLIT = {"keskustelija": M1, "ajattelija": M2, "kevyt": M3}

EHDOTUS = "[[EHDOTUS tyyli.md]]\nKirjoita lyhyesti.\n[[/EHDOTUS]]"
LUOVUTUS = "[[LUOVUTUS]]Suunnitelma jonolle.[[/LUOVUTUS]]"
VALINNAT = "[[VALINNAT: kyll\u00e4 | ei | my\u00f6hemmin]]"
PAATOS = "[[PAATOS 3]]"
KAIKKI = EHDOTUS + "\n" + LUOVUTUS + "\n" + PAATOS + "\n" + VALINNAT
AJATTELIJAN_MERKINNAT = ("Plan: A then B.\n[[EHDOTUS ajattelija.md]]x[[/EHDOTUS]]\n[[LUOVUTUS]]y[[/LUOVUTUS]]\n"
                         "[[PAATOS 9]]\n[[VALINNAT: a | b]]")


def rooli(viestit):
    s = str(viestit[0].get("content", ""))
    if s == yh.LUOKITTELU_OHJE:
        return "kevyt"
    if s == yh.AJATTELIJA_OHJE:
        return "ajattelija"
    if "keskustelija, teht\u00e4v\u00e4nanto." in s:
        return "tehtavananto"
    if "VASTAUKSESSA: keskustelija." in s:
        return "muotoilu"
    return "keskustelija"


class Korvike:
    """Vastaus roolin mukaan; virhe roolin mukaan; `kulu` siirtaa kelloa roolin mukaan."""

    def __init__(self, vastaukset=None, virheet=None, kello=None, kulu=None):
        self.kutsut = []
        self.vastaukset = {"kevyt": "vaativa", **(vastaukset or {})}
        self.virheet = virheet or {}
        self.kello = kello
        self.kulu = kulu or {}

    def __call__(self, malli, viestit, aikaraja_s=None, max_tokens=None):
        r = rooli(viestit)
        self.kutsut.append((malli, viestit, aikaraja_s, max_tokens, r))
        if self.kello is not None:
            self.kello[0] += self.kulu.get(r, 1)
        if r in self.virheet:
            raise self.virheet[r]
        v = self.vastaukset.get(r)
        return v if v is not None else "%s %s" % (r, malli)

    def roolit(self):
        return [k[4] for k in self.kutsut]

    def mallit(self):
        return [k[0] for k in self.kutsut]


def aja(k, kello=None, **kw):
    return yh.aja("tiimi", ROOLIT, M1, PERUS, k, **({"kello": lambda: kello[0]} if kello else {}), **kw)


class Reitti(unittest.TestCase):
    def test_tiimi_on_yhdistelma_ja_oletus_pysyy_yhtena(self):
        self.assertIn("tiimi", yh.YHDISTELMAT)
        self.assertEqual(yh.ROOLIT["tiimi"], ("keskustelija", "ajattelija", "kevyt"))
        self.assertEqual(yh.OLETUS, "yksi")
        self.assertEqual(yh.tarkista_yhdistelma(None), "yksi")

    def test_arkinen_viesti_vain_keskustelijan_kautta(self):
        k = Korvike({"kevyt": "Arkinen."})
        t = aja(k)
        self.assertEqual(k.roolit(), ["kevyt", "keskustelija"])
        self.assertEqual(k.mallit(), [M3, M1])
        self.assertEqual(k.kutsut[1][1], PERUS)                      # keskustelija saa tavallisen kehotteen
        self.assertEqual(k.kutsut[0][1], [{"role": "system", "content": yh.LUOKITTELU_OHJE},
                                          {"role": "user", "content": PERUS[-1]["content"]}])
        self.assertEqual(k.kutsut[0][3], yh.LUOKITTELU_MAX_TOKENIA)
        self.assertEqual((t.teksti, t.malli, t.kutsuja, t.merkinta, t.luonnos),
                         ("keskustelija " + M1, M1, 2, None, None))
        self.assertNotIn(M2, t.mallit)

    def test_vaativa_viesti_kaikkien_kolmen_kautta(self):
        k = Korvike({"tehtavananto": "Task: design a shed build plan.", "ajattelija": "Step 1: foundation.",
                     "muotoilu": "Vaihe 1: perustus."})
        t = aja(k)
        self.assertEqual(k.roolit(), ["kevyt", "tehtavananto", "ajattelija", "muotoilu"])
        self.assertEqual(k.mallit(), [M3, M1, M2, M1])
        # ajattelija nakee vain tehtavan: ei muistia, ei kehotetta, ei historiaa
        self.assertEqual(k.kutsut[2][1], [{"role": "system", "content": yh.AJATTELIJA_OHJE},
                                          {"role": "user", "content": "Task: design a shed build plan."}])
        self.assertNotIn("salainen-muistio", json.dumps(k.kutsut[2][1]))
        self.assertIn("Step 1: foundation.", k.kutsut[3][1][-1]["content"])
        self.assertTrue(k.kutsut[3][1][-1]["content"].startswith(PERUS[-1]["content"]))
        self.assertEqual((t.teksti, t.malli, t.kutsuja, t.mallit), ("Vaihe 1: perustus.", M1, 4, [M3, M1, M2, M1]))
        self.assertIn("Task: design a shed build plan.", t.luonnos)
        self.assertIn("Step 1: foundation.", t.luonnos)
        self.assertIsNone(t.merkinta)

    def test_epaselva_tai_epaonnistunut_luokittelu_keskustelijalle(self):
        for kw in ({"vastaukset": {"kevyt": "en tied\u00e4"}}, {"virheet": {"kevyt": yksityinen.YksityinenVirhe("x")}}):
            with self.subTest(kw=kw):
                k = Korvike(**kw)
                t = aja(k)
                self.assertEqual(k.roolit(), ["kevyt", "keskustelija"])
                self.assertEqual(t.malli, M1)
                self.assertIsNotNone(t.merkinta)

    def test_tehtavanannon_virhe_keskustelija_vastaa_itse(self):
        k = Korvike(virheet={"tehtavananto": yksityinen.YksityinenVirhe("x")})
        t = aja(k)
        self.assertEqual(k.roolit(), ["kevyt", "tehtavananto", "keskustelija"])
        self.assertEqual((t.teksti, t.malli), ("keskustelija " + M1, M1))
        self.assertIsNotNone(t.merkinta)

    def test_muotoilun_virhe_nayttaa_ajattelijan_vastauksen_ilman_merkintoja(self):
        k = Korvike({"ajattelija": AJATTELIJAN_MERKINNAT}, virheet={"muotoilu": yksityinen.YksityinenVirhe("x")})
        t = aja(k)
        self.assertEqual(t.malli, M2)
        self.assertIn("Plan: A then B.", t.teksti)
        self.assertEqual(yh.merkinnat(t.teksti), [])
        self.assertNotIn("[[", t.teksti)
        self.assertIsNotNone(t.merkinta)


class Aikaraja(unittest.TestCase):
    def test_asetus_rajaa_ajattelijan_kutsun(self):
        k = Korvike()
        aja(k, ajattelija_aika_s=30)
        self.assertEqual(k.kutsut[2][2], 30)

    def test_kokonaisraja_ja_keskustelijan_varaus_voittavat_asetuksen(self):
        kello = [0.0]
        k = Korvike(kello=kello, kulu={"kevyt": 5, "tehtavananto": 15})
        aja(k, kello, ajattelija_aika_s=300)
        self.assertEqual(round(k.kutsut[2][2]), yh.AIKARAJA_S - 20 - yh.AJATTELIJA_VARAUS_S)
        self.assertLess(k.kutsut[2][2], 300)

    def test_ajattelija_ei_ehdi_keskustelija_vastaa_itse(self):
        kello = [0.0]
        k = Korvike({"keskustelija": "Oma vastaus.\n" + KAIKKI}, kello=kello, kulu={"ajattelija": 30},
                    virheet={"ajattelija": yksityinen.YksityinenVirhe("mallipalvelu ei vastannut (TimeoutError)")})
        t = aja(k, kello, ajattelija_aika_s=30)
        self.assertEqual(k.roolit(), ["kevyt", "tehtavananto", "ajattelija", "keskustelija"])
        self.assertEqual(k.kutsut[3][1], PERUS)
        self.assertGreaterEqual(k.kutsut[3][2], yh.AJATTELIJA_VARAUS_S - 1)     # keskustelijalle jai aikaa
        self.assertEqual((t.malli, t.kutsuja, t.merkinta), (M1, 4, yh.AJATTELIJA_EI_EHTINYT))
        self.assertTrue(t.teksti.startswith("Oma vastaus."))
        self.assertIn(yh.AJATTELIJA_EI_EHTINYT, t.teksti)
        # keskustelijan omat merkinnat sailyvat sanasta sanaan, VALINNAT viimeisena
        self.assertEqual(yh.merkinnat(t.teksti), [EHDOTUS, LUOVUTUS, PAATOS, VALINNAT])
        self.assertTrue(t.teksti.endswith(VALINNAT))

    def test_aika_lopussa_ajattelijaa_ei_kutsuta(self):
        kello = [0.0]
        k = Korvike(kello=kello, kulu={"tehtavananto": yh.AIKARAJA_S - yh.AJATTELIJA_VARAUS_S})
        t = aja(k, kello)
        self.assertEqual(k.roolit(), ["kevyt", "tehtavananto", "keskustelija"])
        self.assertEqual(t.merkinta, yh.AJATTELIJA_EI_EHTINYT)

    def test_muu_virhe_kertoo_ettei_onnistunut(self):
        k = Korvike(virheet={"ajattelija": yksityinen.YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP 500)")})
        t = aja(k)
        self.assertEqual(k.roolit()[-1], "keskustelija")
        self.assertEqual(t.merkinta, yh.AJATTELIJA_EPAONNISTUI)

    def test_osakutsun_aikaraja_ei_voi_pidentaa(self):
        k = Korvike()
        ajo = yh._Ajo(k, lambda: 0.0, 100)
        ajo.kutsu(M1, PERUS, aikaraja_s=1000)
        ajo.kutsu(M1, PERUS, aikaraja_s=20)
        self.assertEqual([x[2] for x in k.kutsut], [100, 20])

    def test_asetuksen_tarkistus(self):
        self.assertEqual(yh.tarkista_ajattelijan_aika(None), 300.0)
        self.assertEqual(yh.tarkista_ajattelijan_aika(""), 300.0)
        self.assertEqual(yh.tarkista_ajattelijan_aika("120"), 120.0)
        for arvo in ("0", "9", "3601", "abc", "1.5", True, -5):
            with self.subTest(arvo=arvo), self.assertRaises(yksityinen.YksityinenVirhe):
                yh.tarkista_ajattelijan_aika(arvo)


class Kutsuraja(unittest.TestCase):
    def test_tiimi_ei_ylita_neljaa_kutsua(self):
        x = yksityinen.YksityinenVirhe("x")
        for virheet in ({}, {"kevyt": x}, {"tehtavananto": x}, {"ajattelija": x}, {"muotoilu": x},
                        {"ajattelija": x, "keskustelija": x}):
            with self.subTest(virheet=virheet):
                k = Korvike(virheet=virheet)
                try:
                    t = aja(k)
                    self.assertEqual(t.kutsuja, len(k.kutsut))
                except yksityinen.YksityinenVirhe:
                    pass
                self.assertLessEqual(len(k.kutsut), yh.MAX_KUTSUT_VIESTI)

    def test_laskuri_estaa_ylimaaraisen_kutsun_tiimissa(self):
        k = Korvike()
        with mock.patch.object(yh, "MAX_KUTSUT_VIESTI", 3):
            t = aja(k)
        self.assertEqual(len(k.kutsut), 3)                      # muotoilukutsua ei tehty
        self.assertEqual((t.malli, t.kutsuja), (M2, 3))
        self.assertIn("kutsuraja", t.merkinta)

    def test_paivakatto_luokittelussa_lopettaa_heti(self):
        k = Korvike(virheet={"kevyt": yh.Katkaisu("katto")})
        with self.assertRaises(yh.Katkaisu):
            aja(k)
        self.assertEqual(len(k.kutsut), 1)

    def test_paivakatto_ajattelijalla_ei_uusia_kutsuja(self):
        k = Korvike(virheet={"ajattelija": yh.Katkaisu("katto")})
        with self.assertRaises(yh.Katkaisu):
            aja(k)
        self.assertEqual(len(k.kutsut), 3)

    def test_enintaan_kolme_mallia(self):
        self.assertLessEqual(len(set(yh.roolien_mallit("tiimi", ROOLIT, M1).values())), yh.MAX_MALLEJA)


class Merkinnat(unittest.TestCase):
    def test_keskustelijan_lopulliset_merkinnat_sailyvat(self):
        k = Korvike({"muotoilu": "Vastaus.\n" + KAIKKI})
        t = aja(k)
        self.assertEqual(t.teksti, "Vastaus.\n" + KAIKKI)
        self.assertEqual(yh.merkinnat(t.teksti), [EHDOTUS, LUOVUTUS, PAATOS, VALINNAT])

    def test_ajattelija_ei_voi_lisata_merkintoja(self):
        k = Korvike({"ajattelija": AJATTELIJAN_MERKINNAT, "muotoilu": "Suunnitelma: A ja B."})
        t = aja(k)
        syote = k.kutsut[3][1][-1]["content"]
        self.assertIn("Plan: A then B.", syote)
        self.assertNotIn("[[", syote)
        self.assertEqual(yh.merkinnat(syote), [])
        self.assertEqual(t.teksti, "Suunnitelma: A ja B.")
        self.assertNotIn("[[", t.luonnos)

    def test_tehtavanannon_merkinnat_eivat_mene_ajattelijalle(self):
        k = Korvike({"tehtavananto": "Task.\n[[EHDOTUS x.md]]y[[/EHDOTUS]] [[PAATOS 2]] [[/LUOVUTUS]]"})
        aja(k)
        self.assertNotIn("[[", k.kutsut[2][1][-1]["content"])
        self.assertTrue(k.kutsut[2][1][-1]["content"].startswith("Task."))

    def test_rikotut_sulut_eivat_muodosta_merkintaa(self):
        self.assertEqual(yh.merkinnat(yh.neutraloi("a [[[[EHDOTUS z.md]]]]b[[/EHDOTUS]]")), [])
        self.assertNotIn("[[", yh.neutraloi("[[ [[EHDOTUS q]] ]]"))


class FeikkiVastaus:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Verkko:
    """Korvaa vain verkkoyhteyden. Kirjaa jokaisen lahetetyn rungon ja aikarajan."""

    def __init__(self, vastaukset=None, kulu=0.001, virheet=()):
        self.rungot = []
        self.aikarajat = []
        self.vastaukset = {"kevyt": "vaativa", **(vastaukset or {})}
        self.kulu = kulu
        self.virheet = set(virheet)
        self._lukko = threading.Lock()

    def __call__(self, pyynto, timeout=None):
        runko = json.loads(pyynto.data)
        with self._lukko:
            self.rungot.append(runko)
            self.aikarajat.append(timeout)
        r = rooli(runko["messages"])
        if r in self.virheet:
            raise TimeoutError("timed out")
        teksti = self.vastaukset.get(r, "%s %s" % (r, runko["model"]))
        return FeikkiVastaus({"choices": [{"message": {"content": teksti}}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": self.kulu}})


class Kutsupolku(unittest.TestCase):
    """Oikea yksityinen_or + openrouter_kulut; vain verkkoyhteys korvattu."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.avain = self.d / "avain"
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)

    def aja(self, verkko, **kw):
        return yo.kysy_yhdistelmalla("muisti", [{"rooli": "tony", "teksti": "Tee suunnitelma."}], "ohje", malli=M1,
                                     yhdistelma_nimi="tiimi", roolit=ROOLIT, avain_tiedosto=str(self.avain),
                                     kulutila=str(self.kulut), avaa=verkko, nyt=lambda: NYT, **kw)

    def kulurivit(self):
        p = self.kulut / ok.KULUT
        rivit = [json.loads(r) for r in p.read_text().splitlines()] if p.exists() else []
        return [r for r in rivit if not r.get("varaus")]

    def tarkista_rungot(self, v):
        for runko, aikaraja in zip(v.rungot, v.aikarajat):
            self.assertIs(runko["provider"]["zdr"], True)
            self.assertEqual(runko["provider"]["data_collection"], "deny")
            self.assertTrue(yo.avoin_malli(runko["model"]))
            self.assertLessEqual(runko["max_tokens"], yo.MAX_TOKENIA)
            self.assertLessEqual(aikaraja, yo.VASTAUS_AIKARAJA_S)

    def test_zdr_runko_ja_kulukirjaus_jokaisessa_kutsussa(self):
        for luokka, odotettu in (("arkinen", 2), ("vaativa", 4)):
            with self.subTest(luokka=luokka):
                v = Verkko({"kevyt": luokka})
                ennen = len(self.kulurivit())
                t = self.aja(v)
                self.assertEqual((len(v.rungot), t.kutsuja), (odotettu, odotettu))
                self.tarkista_rungot(v)
                self.assertEqual(len(self.kulurivit()) - ennen, odotettu)
                self.assertEqual({r["tehtava"] for r in self.kulurivit()}, {yo.TEHTAVA})
        self.assertEqual([r["model"] for r in v.rungot], [M3, M1, M2, M1])
        self.assertEqual(len(v.rungot[2]["messages"]), 2)          # ajattelija: vain ohje ja tehtava
        self.assertNotIn("ZDR", v.rungot[2]["messages"][0]["content"])

    def test_aikakatkaisu_kutsupolussa_palaa_keskustelijaan(self):
        v = Verkko(virheet={"ajattelija"})
        t = self.aja(v)
        self.assertEqual(len(v.rungot), 4)
        self.tarkista_rungot(v)
        self.assertEqual(rooli(v.rungot[3]["messages"]), "keskustelija")
        self.assertEqual(t.merkinta, yh.AJATTELIJA_EI_EHTINYT)

    def test_ajattelijan_aika_valittyy_kuljettimelle(self):
        v = Verkko()
        self.aja(v, ajattelija_aika_s=15)
        self.assertEqual(v.aikarajat[2], 15)

    def test_paivakatto_taynna_ei_yhtaan_kutsua(self):
        ok.kirjaa(M1, "muu", {"usage": {"cost": 20.0}}, NYT, str(self.kulut))
        v = Verkko()
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.aja(v)
        self.assertEqual(v.rungot, [])


class Asetukset(unittest.TestCase):
    def test_tila_lukee_ajattelijan_ajan_ja_hylkaa_virheellisen(self):
        with tempfile.TemporaryDirectory() as d:
            perus = dict(yks_data=d + "/y", taustapaa="openrouter", or_mallit=[M1, M2, M3])
            t = chat.Tila(chat.tiivista_salasana(SALASANA), d, d, ["localhost"], **perus)
            self.assertEqual((t.ajattelija_aika, t.yhdistelma_oletus), (300.0, "yksi"))
            t = chat.Tila(chat.tiivista_salasana(SALASANA), d, d, ["localhost"], yhdistelma_oletus="tiimi",
                          roolit="keskustelija:%s,ajattelija:%s,kevyt:%s" % (M1, M2, M3), ajattelija_aika="90", **perus)
            self.assertEqual((t.ajattelija_aika, t.yhdistelma_oletus, t.roolit), (90.0, "tiimi", ROOLIT))
            with self.assertRaises(chat.ChatVirhe):
                chat.Tila(chat.tiivista_salasana(SALASANA), d, d, ["localhost"], ajattelija_aika="5", **perus)

    def test_main_lukee_ymparistomuuttujat(self):
        saatu = {}

        def tila(*a, **kw):
            saatu.update(kw)
            raise chat.ChatVirhe("pysaytetty testissa")
        pois = {k: v for k, v in os.environ.items() if not k.startswith("AIVO_")}
        ymp = {"AIVO_YKSITYINEN_YHDISTELMA": "tiimi", "AIVO_YKSITYINEN_AJATTELIJA_AIKA": "200",
               "AIVO_YKSITYINEN_ROOLIT": "keskustelija:" + M1}
        with mock.patch.dict(os.environ, {**pois, **ymp}, clear=True), \
                mock.patch.object(chat, "lue_tiiviste", return_value="x"), mock.patch.object(chat, "Tila", tila), \
                mock.patch("sys.stderr"):
            self.assertEqual(chat.main(["palvele"]), 1)
        self.assertEqual((saatu["yhdistelma_oletus"], saatu["ajattelija_aika"], saatu["roolit"]),
                         ("tiimi", "200", "keskustelija:" + M1))


class Palvelin(unittest.TestCase):
    """HTTP: tiimi valitaan kuten muut yhdistelmat; merkinnat vain keskustelijan lopullisesta vastauksesta."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        r = self.r = Path(self._t.name)
        (r / "kirjasto").mkdir()
        (r / "avain").write_text(AVAIN + "\n")
        os.chmod(r / "avain", 0o600)
        (r / "kulut").mkdir(mode=0o700)
        self.verkko = Verkko()
        alkup = yo.tee_kuljetin
        p = mock.patch.object(yo, "tee_kuljetin", lambda avain, avaa=None, aikaraja_s=None: alkup(avain, self.verkko, aikaraja_s))
        p.start()
        self.addCleanup(p.stop)

    def kaynnista(self, **kw):
        r = self.r
        self.tila = chat.Tila(chat.tiivista_salasana(SALASANA), str(r / "kirjasto"), str(r / "data"), ["localhost"],
                              kysy=lambda m, h: "pilvi", yks_data=str(r / "yks"), yks_muisti=str(r / "yksm"),
                              ydinohjeet=str(r / "ydin"), ehdotukset=str(r / "ehd"), or_avain=str(r / "avain"),
                              or_kulutila=str(r / "kulut"), taustapaa="openrouter", or_mallit=[M1, M2, M3],
                              roolit="keskustelija:%s,ajattelija:%s,kevyt:%s" % (M1, M2, M3), **kw)
        srv = chat.kaynnista("127.0.0.1", 0, self.tila)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.portti = srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SALASANA,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        x = c.getresponse()
        x.read()
        self.ev = x.getheader("Set-Cookie").split(";")[0]

    def api(self, polku, olio=None, metodi="POST"):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=20)
        c.request(metodi, polku, body=None if olio is None else json.dumps(olio),
                  headers={"Cookie": self.ev, "X-Aivo": "1", "Content-Type": "application/json"})
        x = c.getresponse()
        return x.status, json.loads(x.read())

    def test_tiimi_valittavissa_ja_oletus_yksi(self):
        self.kaynnista()
        _, m = self.api("/api/mallit", metodi="GET")
        self.assertIn("tiimi", m["yhdistelmat"])
        self.assertEqual(m["yhdistelma"], "yksi")

    def test_oletus_tiimi_asetuksesta_ja_tieto_vastauksessa(self):
        self.kaynnista(yhdistelma_oletus="tiimi")
        _, j = self.api("/api/uusi", {"tila": "yksityinen"})
        s, v = self.api("/api/viesti", {"keskustelu": j["id"], "teksti": "Tee suunnitelma."})
        self.assertEqual(s, 200)
        self.assertEqual((v["yhdistelma"], v["mallit"], v["kutsuja"], v["malli"]), ("tiimi", [M3, M1, M2, M1], 4, M1))
        self.assertIn("AJATTELIJAN VASTAUS", v["luonnos"])
        self.assertNotIn("luonnos", self.tila.yks.lue(j["id"])[-1])

    def test_merkinnat_vain_keskustelijalta_chatissa(self):
        self.verkko.vastaukset.update({"ajattelija": AJATTELIJAN_MERKINNAT, "muotoilu": "Suunnitelma.\n" + EHDOTUS + "\n" + VALINNAT})
        self.kaynnista()
        _, j = self.api("/api/uusi", {"tila": "yksityinen", "yhdistelma": "tiimi"})
        s, v = self.api("/api/viesti", {"keskustelu": j["id"], "teksti": "Tee suunnitelma."})
        self.assertEqual(s, 200)
        self.assertEqual(v["valinnat"], ["kyll\u00e4", "ei", "my\u00f6hemmin"])
        self.assertEqual(len(v["ehdotukset"]), 1)
        tallennettu = json.loads(next((self.r / "ehd").glob("*.json")).read_text())
        self.assertEqual(tallennettu["tiedosto"], "tyyli.md")
        self.assertNotIn("paatosehdotus", v)
        self.assertNotIn("ajattelija.md", v["vastaus"])


if __name__ == "__main__":
    unittest.main()
