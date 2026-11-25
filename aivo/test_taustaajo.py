"""Testit aivo/taustaajo.py:lle ja chatin /api/tausta-reitille. Ei verkkoa, ei oikeita avaimia."""
import ast
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from aivo import chat, openrouter_kulut as ok, taustaajo as ta, yhdistelma, yksityinen

AIVO = Path(__file__).resolve().parent
MALLI_K = "meta-llama/llama-3.3-70b-instruct"
MALLI_A = "qwen/qwen3-235b-a22b-2507"
ROOLIT = {"keskustelija": MALLI_K, "ajattelija": MALLI_A}
AVAIN = "sk-testi-" + "x" * 30          # keksitty, ei oikea avain
NYT = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
KID = "20261122-100000-0123abcd"
TEHTAVA = "Compare option A and option B for a small home server backup. Context: two disks, weekly copies."


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
        os.chmod(self.d, 0o700)
        self.jono = self.d / "tyot"
        self.chat = self.d / "chat"
        self.chat.mkdir(mode=0o700)
        (self.chat / (KID + ".jsonl")).write_text(
            json.dumps({"aika": NYT.isoformat(), "rooli": "tony", "teksti": "moi", "lahteet": []}) + "\n")
        self.kutsut = []
        self.rivit = []

    def kysy(self, vastaukset=None, virheet=None):
        vastaukset = dict(vastaukset or {})
        virheet = dict(virheet or {})

        def kysy(malli, viestit, aikaraja_s):
            self.kutsut.append((malli, viestit, aikaraja_s))
            if malli in virheet:
                raise virheet[malli]
            return vastaukset.get(malli, "vastaus " + malli)
        return kysy

    def aja(self, kysy=None, **kw):
        return ta.aja(self.jono, self.chat, kysy or self.kysy(), ROOLIT, nyt=kw.pop("nyt", NYT),
                      tulosta=self.rivit.append, **kw)

    def keskustelu(self):
        return [json.loads(r) for r in (self.chat / (KID + ".jsonl")).read_text().splitlines() if r.strip()]

    def tausta(self):
        return [v for v in self.keskustelu() if "tausta" in v]


class KirjoitusTesti(Pohja):
    def test_tyo_kirjoitetaan_jonoon_0600_ja_kansio_0700(self):
        t = ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=NYT)
        p = self.jono / (t + ".json")
        self.assertEqual(os.stat(self.jono).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        d = ta.lue_tyo(p)
        self.assertEqual((d["keskustelu"], d["tehtava"], d["sha"]), (KID, TEHTAVA, ta.sha(TEHTAVA)))
        self.assertRegex(t, ta.TUNNUS_RE)

    def test_vaara_keskustelu_tyhja_tai_liian_pitka_tehtava_hylataan(self):
        for kid, teht in (("../x", TEHTAVA), (KID, "  "), (KID, "x" * (ta.TEHTAVA_YLARAJA + 1)), (KID, None)):
            with self.assertRaises(ta.TaustaVirhe):
                ta.kirjoita_tyo(self.jono, kid, teht)
        self.assertFalse(list(self.jono.glob("*.json")) if self.jono.exists() else [])

    def test_liian_laaja_tai_linkattu_jono_hylataan(self):
        self.jono.mkdir(mode=0o755)
        os.chmod(self.jono, 0o755)
        with self.assertRaises(ta.TaustaVirhe):
            ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        linkki = self.d / "linkki"
        os.symlink(self.jono, linkki)
        with self.assertRaises(ta.TaustaVirhe):
            ta.kirjoita_tyo(linkki, KID, TEHTAVA)

    def test_muutettu_tehtava_ei_tasmaa_shahan(self):
        t = ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        p = self.jono / (t + ".json")
        d = json.loads(p.read_text())
        d["tehtava"] += " and also something else"
        p.write_text(json.dumps(d))
        with self.assertRaises(ta.TaustaVirhe):
            ta.lue_tyo(p)


class AjoTesti(Pohja):
    def test_ajattelija_ja_keskustelija_tulos_keskusteluun(self):
        t = ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=NYT)
        r = self.aja(self.kysy({MALLI_A: "Option A is better because...", MALLI_K: "Vaihtoehto A on parempi."}))
        self.assertEqual((r["valmis"], r["epaonnistui"], r["kutsuja"]), (1, 0, 2))
        self.assertEqual([k[0] for k in self.kutsut], [MALLI_A, MALLI_K])
        self.assertIn(TEHTAVA, self.kutsut[0][1][-1]["content"])
        self.assertIn("Option A is better", self.kutsut[1][1][-1]["content"])
        v = self.tausta()
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["rooli"], "aivo")
        self.assertEqual(v[0]["tausta"], t)
        self.assertTrue(v[0]["teksti"].startswith(ta.VALMIS_MERKINTA))
        self.assertIn("Vaihtoehto A on parempi.", v[0]["teksti"])
        self.assertEqual(v[0]["mallit"], [MALLI_A, MALLI_K])
        self.assertTrue((self.jono / ta.VALMIIT / (t + ".json")).exists())
        self.assertEqual(ta.odottavat(self.jono), [])
        self.assertEqual(self.aja()["valmis"], 0)                  # sama tyo ei aja kahdesti

    def test_keskusteluhistoria_sailyy_ja_chat_lukee_rivin(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.aja()
        h = chat.Keskustelut(self.chat).lue(KID)
        self.assertEqual([v["rooli"] for v in h], ["tony", "aivo"])
        viestit = yksityinen.muodosta_viestit("", h, "")
        self.assertEqual(viestit[-1]["role"], "assistant")

    def test_merkinnat_poistetaan_ajattelijalta_ja_keskustelijalta(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.aja(self.kysy({MALLI_A: "x [[PAATOS 0]]", MALLI_K: "Hei [[EHDOTUS saannot.md]]a[[/EHDOTUS]] [[VALINNAT: a | b]]"}))
        t = self.tausta()[0]["teksti"]
        self.assertNotIn("[[", t)
        self.assertNotIn("[[PAATOS", self.kutsut[1][1][-1]["content"])

    def test_kesken_jaanyt_tyo_merkitaan_epaonnistuneeksi(self):
        t = ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        (self.jono / ta.KESKEN).mkdir(mode=0o700)
        os.replace(self.jono / (t + ".json"), self.jono / ta.KESKEN / (t + ".json"))
        r = self.aja()
        self.assertEqual(r["epaonnistui"], 1)
        self.assertEqual(self.kutsut, [])
        self.assertIn(ta.SYYT["keskeytyi"], self.tausta()[0]["teksti"])

    def test_kuiva_ajo_ei_kutsu_mallia(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(kuiva=True)
        self.assertEqual((r["odottaa"], self.kutsut, self.tausta()), (1, [], []))

    def test_lukko_estaa_paallekkaisen_ajon(self):
        import fcntl
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        fd = os.open(self.jono / ta.LUKKO_TIEDOSTO, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertEqual(self.aja()["valmis"], 0)
        self.assertEqual(self.kutsut, [])

    def test_loki_ei_sisalla_tehtavaa_eika_vastausta(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.aja(self.kysy({MALLI_K: "SALAINEN-VASTAUS"}))
        loki = (self.jono / ta.LOKI_TIEDOSTO).read_text()
        for sana in ("option A", "SALAINEN", "backup"):
            self.assertNotIn(sana, loki)
            self.assertNotIn(sana, "\n".join(self.rivit))


class AikarajaTesti(Pohja):
    def test_aikaraja_ennen_ajattelijaa_merkitaan_epaonnistuneeksi(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        aika = iter([0.0, 1000.0])
        r = self.aja(kello=lambda: next(aika))
        self.assertEqual(r["epaonnistui"], 1)
        self.assertEqual(self.kutsut, [])
        self.assertIn(ta.SYYT["aikaraja"], self.tausta()[0]["teksti"])
        self.assertTrue(list((self.jono / ta.EPAONNISTUNEET).glob("*.json")))

    def test_kutsu_saa_vain_jaljella_olevan_ajan_ja_asetus_ei_nosta_ylarajaa(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        aika = iter([0.0, 0.0, 500.0])
        self.aja(kello=lambda: next(aika), aikaraja_s=99_999)
        self.assertEqual(self.kutsut[0][2], ta.AIKARAJA_MAX_S)
        self.assertEqual(self.kutsut[1][2], ta.AIKARAJA_MAX_S - 500)
        self.assertEqual(ta.rajaa("99999", ta.AIKARAJA_S, ta.AIKARAJA_MAX_S), ta.AIKARAJA_MAX_S)

    def test_aika_loppuu_ennen_keskustelijaa_ajattelijan_vastaus_nakyy(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        aika = iter([0.0, 0.0, 1000.0])
        r = self.aja(self.kysy({MALLI_A: "English analysis"}), kello=lambda: next(aika))
        self.assertEqual(r["valmis"], 1)
        self.assertEqual(len(self.kutsut), 1)
        self.assertIn("English analysis", self.tausta()[0]["teksti"])


class PaivarajaTesti(Pohja):
    def test_paivaraja_estaa_ylimenevat_tyot(self):
        for _ in range(3):
            ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(paivaraja=2)
        self.assertEqual((r["valmis"], r["epaonnistui"]), (2, 1))
        self.assertEqual(len(self.kutsut), 4)
        self.assertIn(ta.SYYT["paivaraja"], self.tausta()[-1]["teksti"])

    def test_laskuri_nollautuu_seuraavana_paivana_ja_sailyy_ajojen_valilla(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.aja(paivaraja=1)
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.assertEqual(self.aja(paivaraja=1)["epaonnistui"], 1)
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.assertEqual(self.aja(paivaraja=1, nyt=NYT + timedelta(days=1))["valmis"], 1)

    def test_asetus_ei_voi_nostaa_paivarajaa(self):
        self.assertEqual(ta.rajaa("1000", ta.PAIVARAJA, ta.PAIVARAJA_MAX), ta.PAIVARAJA_MAX)
        for arvo in ("0", "-1", "x"):
            with self.assertRaises(ta.TaustaVirhe):
                ta.rajaa(arvo, ta.PAIVARAJA, ta.PAIVARAJA_MAX)
        tila = {"versio": 1, "paiva": ta._paiva(NYT), "ajettu": ta.PAIVARAJA_MAX}
        self.jono.mkdir(mode=0o700)
        ta.kirjoita_tila(self.jono, tila)
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.assertEqual(self.aja(paivaraja=10_000)["epaonnistui"], 1)
        self.assertEqual(self.kutsut, [])

    def test_rikkinainen_tila_pysayttaa_ajon(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        (self.jono / ta.TILA_TIEDOSTO).write_text("{rikki")
        with self.assertRaises(ta.TaustaVirhe):
            self.aja()
        self.assertEqual(self.kutsut, [])


class PuoliyoTesti(Pohja):
    """Ajo alkaa klo 23.55 (Europe/Helsinki) ja jatkuu yli puolenyon: jokainen mallikutsu vie 3 min seinakelloa."""
    ALKU = datetime(2026, 11, 22, 21, 55, tzinfo=timezone.utc)      # 23.55 Helsingissa (UTC+2)

    def setUp(self):
        super().setUp()
        self.seina = self.ALKU

    def kello_kysy(self):
        sisempi = self.kysy()

        def kysy(malli, viestit, aikaraja_s):
            self.seina += timedelta(minutes=3)
            return sisempi(malli, viestit, aikaraja_s)
        return kysy

    def aja_kellolla(self, **kw):
        return ta.aja(self.jono, self.chat, self.kello_kysy(), ROOLIT, aika=lambda: self.seina,
                      tulosta=self.rivit.append, **kw)

    def tila(self):
        return json.loads((self.jono / ta.TILA_TIEDOSTO).read_text())

    def test_tyot_kirjautuvat_alkamispaivalle_eika_raja_tuplaannu(self):
        self.assertEqual((ta._paiva(self.ALKU), ta._paiva(self.ALKU + timedelta(minutes=6))),
                         ("2026-11-22", "2026-11-23"))
        for _ in range(4):
            ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=self.ALKU)
        r = self.aja_kellolla(paivaraja=2)
        # tyo 1 alkaa 23.55 (22.11.), tyo 2 alkaa 00.01 (23.11.); ajo on aloittanut paivarajan verran toita
        self.assertEqual((r["valmis"], r["epaonnistui"]), (2, 0))
        self.assertEqual(self.tila(), {"versio": 1, "paiva": "2026-11-23", "ajettu": 1})
        self.assertEqual(len(ta.odottavat(self.jono)), 2)
        # seuraava ajo 23.11.: tyo 3 kayttaa paivan toisen paikan, tyo 4 ylittaa rajan
        r = self.aja_kellolla(paivaraja=2)
        self.assertEqual((r["valmis"], r["epaonnistui"]), (1, 1))
        self.assertEqual(self.tila(), {"versio": 1, "paiva": "2026-11-23", "ajettu": 2})
        self.assertIn(ta.SYYT["paivaraja"], self.tausta()[-1]["teksti"])
        self.assertEqual(len(self.kutsut), 2 * 3)
        # Seuraava ajo samana kalenteripaivana ei saa uutta kiintiota: raja ei tuplaannu.
        self.kutsut.clear()
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=self.seina)
        r = self.aja_kellolla(paivaraja=2)
        self.assertEqual((r["valmis"], r["epaonnistui"]), (0, 1))
        self.assertEqual(self.kutsut, [])

    def test_epaonnistuneen_tyon_jalkeen_seuraava_kirjataan_uudelle_paivalle(self):
        for _ in range(2):
            ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=self.ALKU)
        kerrat = []

        def kysy(malli, viestit, aikaraja_s):
            self.seina += timedelta(minutes=6)
            kerrat.append(malli)
            if len(kerrat) == 1:
                raise yksityinen.YksityinenVirhe("testi")
            return "vastaus"
        r = ta.aja(self.jono, self.chat, kysy, ROOLIT, aika=lambda: self.seina, paivaraja=2,
                   tulosta=self.rivit.append)
        # tyo 1 alkaa 23.55 ja epaonnistuu 00.01; tyo 2 alkaa 00.01 ja kuuluu 23.11. kiintioon
        self.assertEqual((r["valmis"], r["epaonnistui"]), (1, 1))
        self.assertEqual(self.tila(), {"versio": 1, "paiva": "2026-11-23", "ajettu": 1})

    def test_valmis_rivi_saa_valmistumisajan(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=self.ALKU)
        self.aja_kellolla(paivaraja=1)
        self.assertEqual(self.tausta()[-1]["aika"], (self.ALKU + timedelta(minutes=6)).isoformat(timespec="seconds"))

    def test_yksi_ajo_aloittaa_enintaan_paivarajan_verran_toita(self):
        for _ in range(3):
            ta.kirjoita_tyo(self.jono, KID, TEHTAVA, nyt=self.ALKU)
        r = self.aja_kellolla(paivaraja=1)
        # tyo 1 kuluttaa 22.11. paikan; 23.11. olisi tilaa, mutta ajo on jo aloittanut paivarajan verran toita
        self.assertEqual((r["valmis"], r["epaonnistui"]), (1, 0))
        self.assertEqual(len(ta.odottavat(self.jono)), 2)
        self.assertEqual(self.tila(), {"versio": 1, "paiva": "2026-11-22", "ajettu": 1})
        self.assertTrue(any("ajon tyoraja taynna, 2 tyota jaa jonoon" in x for x in self.rivit))
        r = self.aja_kellolla(paivaraja=1)                       # seuraava ajo 23.11.: yksi ajetaan, yksi yli rajan
        self.assertEqual((r["valmis"], r["epaonnistui"]), (1, 1))
        self.assertEqual(self.tila(), {"versio": 1, "paiva": "2026-11-23", "ajettu": 1})

    def test_kiintea_nyt_toimii_kuten_ennen(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.assertEqual(self.aja(paivaraja=1)["valmis"], 1)
        self.assertEqual(self.tila()["paiva"], ta._paiva(NYT))


class YksikkoAikarajaTesti(unittest.TestCase):
    """docs/aivo-taustaajo.md: systemd ei saa katkaista pisinta mahdollista ajoa (paivaraja x aikaraja)."""

    def yksikko(self):
        teksti = (AIVO.parent / "docs" / "aivo-taustaajo.md").read_text(encoding="utf-8")
        alku = teksti.index("aivo-taustaajo.service")
        lohko = teksti[alku:teksti.index("```", teksti.index("[Service]", alku))]
        asetukset = {}
        for rivi in lohko.splitlines():
            avain, sep, arvo = rivi.strip().partition("=")
            if sep and avain == "Environment":
                avain, _, arvo = arvo.partition("=")
            if sep:
                asetukset[avain] = arvo
        return asetukset

    @staticmethod
    def sekunteina(arvo):
        import re
        m = re.fullmatch(r"([0-9]+)(min|s|h)?", arvo)
        assert m, arvo
        return int(m.group(1)) * {"min": 60, "h": 3600, "s": 1, None: 1}[m.group(2)]

    def test_timeoutstartsec_kattaa_koodin_ylarajat(self):
        a = self.yksikko()
        aikaraja = self.sekunteina(a["TimeoutStartSec"])
        pisin = ta.PAIVARAJA_MAX * ta.AIKARAJA_MAX_S
        self.assertGreaterEqual(aikaraja, pisin + 5 * 60)            # pelivara tiedostoille ja lukolle

    def test_yksikon_asetukset_ovat_koodin_rajoissa(self):
        a = self.yksikko()
        self.assertLessEqual(int(a["AIVO_TAUSTA_PAIVARAJA"]), ta.PAIVARAJA_MAX)
        self.assertLessEqual(int(a["AIVO_TAUSTA_AIKARAJA_S"]), ta.AIKARAJA_MAX_S)
        self.assertEqual((int(a["AIVO_TAUSTA_PAIVARAJA"]), int(a["AIVO_TAUSTA_AIKARAJA_S"])),
                         (ta.PAIVARAJA, ta.AIKARAJA_S))

    def test_ajo_ei_ylita_yksikon_aikarajaa_puolenyon_yli(self):
        """Pahin tapaus: ajo alkaa paivan viimeisella minuutilla, jokainen tyo kayttaa koko aikarajansa."""
        aikaraja = self.sekunteina(self.yksikko()["TimeoutStartSec"])
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            os.chmod(d, 0o700)
            jono, chat_ = d / "tyot", d / "chat"
            chat_.mkdir(mode=0o700)
            (chat_ / (KID + ".jsonl")).write_text("")
            for _ in range(2 * ta.PAIVARAJA_MAX + 1):
                ta.kirjoita_tyo(jono, KID, TEHTAVA, nyt=NYT)
            alku = datetime(2026, 11, 22, 21, 59, tzinfo=timezone.utc)
            tila = {"seina": alku, "mono": 0.0}

            def kysy(malli, viestit, aikaraja_s):
                tila["seina"] += timedelta(seconds=aikaraja_s)       # kutsu kayttaa kaiken jaljella olevan ajan
                tila["mono"] += aikaraja_s
                return "ok"
            r = ta.aja(jono, chat_, kysy, ROOLIT, paivaraja=10_000, aikaraja_s=10_000, aika=lambda: tila["seina"],
                       kello=lambda: tila["mono"], tulosta=lambda *_: None)
            self.assertEqual(r["valmis"], ta.PAIVARAJA_MAX)
            self.assertLessEqual((tila["seina"] - alku).total_seconds(), ta.PAIVARAJA_MAX * ta.AIKARAJA_MAX_S)
            self.assertLess((tila["seina"] - alku).total_seconds(), aikaraja)


class EpaonnistuminenTesti(Pohja):
    def test_ajattelijan_virhe_merkitaan_keskusteluun(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(self.kysy(virheet={MALLI_A: yksityinen.YksityinenVirhe("mallipalvelu ei vastannut")}))
        self.assertEqual(r["epaonnistui"], 1)
        v = self.tausta()
        self.assertTrue(v[0]["teksti"].startswith(ta.EPAONNISTUI_MERKINTA))
        self.assertIn(ta.SYYT["malli"], v[0]["teksti"])

    def test_kulukatto_merkitaan_eika_keskustelijaa_kutsuta(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.aja(self.kysy(virheet={MALLI_A: yhdistelma.Katkaisu("katto")}))
        self.assertEqual(len(self.kutsut), 1)
        self.assertIn(ta.SYYT["kulukatto"], self.tausta()[0]["teksti"])

    def test_keskustelijan_virhe_nayttaa_ajattelijan_vastauksen(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(self.kysy({MALLI_A: "English analysis"}, {MALLI_K: yksityinen.YksityinenVirhe("x")}))
        self.assertEqual(r["valmis"], 1)
        self.assertIn("English analysis", self.tausta()[0]["teksti"])

    def test_virheellinen_tyo_siirretaan_eika_poisteta(self):
        self.jono.mkdir(mode=0o700)
        p = self.jono / "20261122-100000-0123456789ab.json"
        p.write_text(json.dumps({"versio": 1, "keskustelu": KID}))
        r = self.aja()
        self.assertEqual(r["epaonnistui"], 1)
        self.assertTrue((self.jono / ta.EPAONNISTUNEET / p.name).exists())
        self.assertIn(ta.SYYT["virheellinen"], self.tausta()[0]["teksti"])

    def test_puuttuva_keskustelu_ei_luo_uutta(self):
        ta.kirjoita_tyo(self.jono, "20261122-100000-ffffffff", TEHTAVA)
        r = self.aja()
        self.assertEqual(r["epaonnistui"], 1)
        self.assertFalse((self.chat / "20261122-100000-ffffffff.jsonl").exists())

    def test_main_tulostaa_vain_virheen_tyypin(self):
        with mock.patch("sys.stderr") as err:
            rc = ta.main(["--jono", str(self.jono), "--chat", str(self.chat)],
                         env={"AIVO_OPENROUTER_MALLIT": "openai/gpt-4o"})
        self.assertEqual(rc, 1)
        tulostettu = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("YksityinenVirhe", tulostettu)
        self.assertNotIn("gpt-4o", tulostettu)

    def test_main_hylkaa_loopback_taustapaan(self):
        with mock.patch("sys.stderr"):
            rc = ta.main(["--jono", str(self.jono), "--chat", str(self.chat)],
                         env={"AIVO_YKSITYINEN_TAUSTAPAA": "loopback", "AIVO_OPENROUTER_MALLI": MALLI_K})
        self.assertEqual(rc, 1)


class SiirtovirheTesti(Pohja):
    """Tyotiedoston siirto (kesken/, valmiit/, epaonnistuneet/) voi nostaa OSErrorin (esim. levy taynna, oikeudet).
    Yksi siirtovirhe ei saa kaataa koko ajoa: loput jonon tyot ajetaan ja virhe kirjataan lokiin."""

    def setUp(self):
        super().setUp()
        self.t1 = ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        self.t2 = ta.kirjoita_tyo(self.jono, KID, TEHTAVA + " Second.")
        self.ensimmainen = ta.odottavat(self.jono)[0].stem

    def _siirto_kaatuu_kerran(self, kansio):
        alkup = ta._siirra
        tila = {"kaatui": False}

        def siirra(jono, polku, k):
            if k == kansio and not tila["kaatui"]:
                tila["kaatui"] = True
                raise OSError("levy taynna")
            return alkup(jono, polku, k)
        return mock.patch.object(ta, "_siirra", side_effect=siirra)

    def loki(self):
        return (self.jono / ta.LOKI_TIEDOSTO).read_text()

    def test_valmiit_siirron_virhe_ei_kaada_ajoa(self):
        with self._siirto_kaatuu_kerran(ta.VALMIIT):
            r = self.aja()
        self.assertEqual(r["valmis"], 2)
        self.assertEqual(len(self.kutsut), 4)
        self.assertEqual(len(self.tausta()), 2)
        self.assertIn("siirto epaonnistui: %s (OSError, valmiit)" % self.ensimmainen, self.loki())
        self.assertNotIn("levy taynna", self.loki())
        self.assertEqual(len(list((self.jono / ta.VALMIIT).glob("*.json"))), 1)

    def test_epaonnistuneet_siirron_virhe_ei_kaada_ajoa(self):
        alkup = ta.lisaa_keskusteluun
        tila = {"n": 0}

        def lisaa(*a, **kw):
            tila["n"] += 1
            if tila["n"] == 1:
                raise ta.TaustaVirhe("keskustelu ei kirjoitettavissa")
            return alkup(*a, **kw)
        with mock.patch.object(ta, "lisaa_keskusteluun", side_effect=lisaa), \
                self._siirto_kaatuu_kerran(ta.EPAONNISTUNEET):
            r = self.aja()
        self.assertEqual(r["epaonnistui"], 1)
        self.assertEqual(r["valmis"], 1)
        self.assertEqual(len(self.kutsut), 4)
        self.assertIn("tulosta ei voitu lisata: %s (TaustaVirhe)" % self.ensimmainen, self.loki())
        self.assertIn("siirto epaonnistui: %s (OSError, epaonnistuneet)" % self.ensimmainen, self.loki())

    def test_kesken_siirron_virhe_ei_aja_eika_kuluta_paivapaikkaa(self):
        with self._siirto_kaatuu_kerran(ta.KESKEN):
            r = self.aja()
        self.assertEqual(r["valmis"], 1)
        self.assertEqual(len(self.kutsut), 2)                       # vain toinen tyo ajettiin
        self.assertEqual(r["ohitettu"], 1)
        self.assertIn("siirto epaonnistui: %s (OSError, kesken)" % self.ensimmainen, self.loki())
        self.assertTrue((self.jono / (self.ensimmainen + ".json")).exists())   # jaa jonoon, ei kadonnut
        tila = json.loads((self.jono / ta.TILA_TIEDOSTO).read_text())
        self.assertEqual(tila["ajettu"], 1)                         # paikka varattiin vain ajetulle tyolle
        r2 = self.aja()                                             # seuraava ajo ajaa jaaneen tyon kerran
        self.assertEqual(r2["valmis"], 1)
        self.assertEqual(len(self.kutsut), 4)
        self.assertEqual(ta.odottavat(self.jono), [])

    def test_pysyva_epaonnistuneet_siirron_virhe_ei_toista_merkintaa(self):
        p = self.jono / (self.ensimmainen + ".json")
        ta._siirra(self.jono, p, ta.KESKEN)                         # edellisen ajon jaannos kesken/:ssa
        alkup = ta._siirra

        def siirra(jono, polku, k):
            if k == ta.EPAONNISTUNEET and Path(polku).stem == self.ensimmainen:
                raise PermissionError("ei oikeutta")
            return alkup(jono, polku, k)
        with mock.patch.object(ta, "_siirra", side_effect=siirra):
            for _ in range(3):
                self.aja()
        self.assertEqual([v for v in self.tausta() if ta.SYYT["keskeytyi"] in v["teksti"]], [])
        self.assertTrue((self.jono / ta.KESKEN / (self.ensimmainen + ".json")).exists())
        self.assertEqual(self.loki().count("siirto epaonnistui: %s (PermissionError, epaonnistuneet)"
                                           % self.ensimmainen), 3)
        self.aja()                                                  # siirto onnistuu: merkinta tasan kerran
        self.assertEqual(len([v for v in self.tausta() if ta.SYYT["keskeytyi"] in v["teksti"]]), 1)
        self.assertFalse((self.jono / ta.KESKEN / (self.ensimmainen + ".json")).exists())


class RoolitTesti(unittest.TestCase):
    def test_roolit_asetuksesta_ja_oletus(self):
        mallit = (MALLI_K, MALLI_A)
        self.assertEqual(ta.valitse_roolit("", mallit), {"keskustelija": MALLI_K, "ajattelija": MALLI_K})
        self.assertEqual(ta.valitse_roolit("ajattelija:%s,kevyt:%s" % (MALLI_A, MALLI_K), mallit),
                         {"keskustelija": MALLI_K, "ajattelija": MALLI_A})
        with self.assertRaises(ta.TaustaVirhe):
            ta.valitse_roolit("ajattelija:openai/gpt-4o", mallit)


class ZdrTesti(Pohja):
    """Tuotannon kysyja: jokainen kutsu kulkee yksityinen_or.kysy_taustatyo -> openrouter_kulut.kutsu (ZDR)."""

    def setUp(self):
        super().setUp()
        self.avain = self.d / "avain"
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.pyynnot = []

    def avaa(self, pyynto, timeout=None):
        self.pyynnot.append((json.loads(pyynto.data), timeout, pyynto.full_url))
        return FeikkiVastaus({"choices": [{"message": {"content": "ok"}}], "usage": {"cost": 0.001}})

    def tuotanto(self):
        return ta.tee_kysyja(str(self.avain), kulutila=str(self.kulut), avaa=self.avaa,
                             nyt=lambda: NYT.astimezone(ok.TZ))

    def test_zdr_runko_jokaisessa_kutsussa(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(self.tuotanto())
        self.assertEqual(r["valmis"], 1)
        self.assertEqual(len(self.pyynnot), 2)
        for runko, timeout, url in self.pyynnot:
            self.assertIs(runko["provider"]["zdr"], True)
            self.assertEqual(runko["provider"]["data_collection"], "deny")
            self.assertTrue(ok.avoin_malli(runko["model"]))
            self.assertEqual(url, ok.OSOITE)
            self.assertLessEqual(runko["max_tokens"], yksityinen.MAX_TOKENIA)
            self.assertLessEqual(timeout, ta.AIKARAJA_S)
        self.assertEqual([p[0]["model"] for p in self.pyynnot], [MALLI_A, MALLI_K])
        kirjatut = [json.loads(x) for x in (self.kulut / ok.KULUT).read_text().splitlines()]
        self.assertTrue(kirjatut)
        self.assertTrue(all(k.get("tehtava") == "aivo-yksityinen-tausta" for k in kirjatut))

    def test_paivakatto_estaa_kutsun_ja_merkitaan(self):
        with open(self.kulut / ok.KULUT, "w") as f:
            f.write(json.dumps({"aika": NYT.isoformat(), "malli": "m/x", "tehtava": "t", "usd": 50.0}) + "\n")
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = self.aja(self.tuotanto())
        self.assertEqual(r["epaonnistui"], 1)
        self.assertEqual(self.pyynnot, [])
        self.assertIn(ta.SYYT["kulukatto"], self.tausta()[0]["teksti"])

    def test_suljettu_malli_ei_lahde(self):
        ta.kirjoita_tyo(self.jono, KID, TEHTAVA)
        r = ta.aja(self.jono, self.chat, self.tuotanto(), {"keskustelija": MALLI_K, "ajattelija": "openai/gpt-4o"},
                   nyt=NYT, tulosta=lambda *_: None)
        self.assertEqual(r["epaonnistui"], 1)
        self.assertEqual(self.pyynnot, [])

    def test_kuljettimen_aikaraja_ei_ylita_taustan_ylarajaa(self):
        from aivo import yksityinen_or as yo
        laheta = yo.tee_kuljetin(AVAIN, self.avaa, 10_000, ylaraja_s=yo.TAUSTA_AIKARAJA_S)
        laheta({"provider": {"zdr": True, "data_collection": "deny"}})
        self.assertEqual(self.pyynnot[-1][1], yo.TAUSTA_AIKARAJA_S)
        yo.tee_kuljetin(AVAIN, self.avaa, 10_000)({"provider": {"zdr": True, "data_collection": "deny"}})
        self.assertEqual(self.pyynnot[-1][1], yo.VASTAUS_AIKARAJA_S)    # chatin raja ennallaan


class ChatReittiTesti(unittest.TestCase):
    """/api/tausta: vain yksityinen keskustelu; tyokalutila ei nae taustaviesteja (404)."""
    SAL = "oikea-salasana-123"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = Path(cls.tmp.name)
        (r / "kirjasto").mkdir()
        cls.r = r
        cls.tila = chat.Tila(chat.tiivista_salasana(cls.SAL), str(r / "kirjasto"), str(r / "data"), [".ts.net"],
                             kysy=lambda m, h: "pilvi", yks_data=str(r / "yks" / "chat"),
                             yks_muisti=str(r / "yks" / "muisti"), ydinohjeet=str(r / "yks" / "ydin"),
                             ehdotukset=str(r / "yks" / "ehd"), kysy_yks=lambda m, h, o: "paikallinen")
        cls.srv = chat.kaynnista("127.0.0.1", 0, cls.tila)
        cls.portti = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def pyynto(self, metodi, polku, olio=None, ev=None):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        h = {"X-Aivo": "1", "Content-Type": "application/json"}
        if ev:
            h["Cookie"] = ev
        c.request(metodi, polku, body=json.dumps(olio) if olio is not None else None, headers=h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def kirjaudu(self):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + self.SAL,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        return r.getheader("Set-Cookie").split(";")[0]

    def test_yksityinen_keskustelu_nayttaa_taustaviestin_seuraavassa_haussa(self):
        ev = self.kirjaudu()
        _, j = self.pyynto("POST", "/api/uusi", {"tila": "yksityinen"}, ev)
        kid = j["id"]
        self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "moi"}, ev)
        tila, j = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=0" % kid, ev=ev)
        self.assertEqual((tila, j["viestit"]), (200, []))
        ta.lisaa_keskusteluun(self.r / "yks" / "chat", kid, ta.valmis_teksti("Valmis vastaus."), "t1", NYT)
        tila, j = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=0" % kid, ev=ev)
        self.assertEqual(tila, 200)
        self.assertEqual(len(j["viestit"]), 1)
        self.assertEqual(j["viestit"][0]["indeksi"], 2)
        self.assertTrue(j["viestit"][0]["teksti"].startswith(ta.VALMIS_MERKINTA))
        tila, j = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=3" % kid, ev=ev)
        self.assertEqual(j["viestit"], [])
        self.assertEqual(self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=-1" % kid, ev=ev)[0], 400)

    def test_tyokalutilan_keskustelu_saa_404(self):
        ev = self.kirjaudu()
        _, j = self.pyynto("POST", "/api/uusi", {"tila": "tyokalu"}, ev)
        kid = j["id"]
        tila, _ = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=0" % kid, ev=ev)
        self.assertEqual(tila, 404)

    def test_ilman_kirjautumista_401(self):
        self.assertEqual(self.pyynto("GET", "/api/tausta?keskustelu=x&alkaen=0")[0], 401)

    def test_sivu_pollaa_taustareittia(self):
        html = chat.sivu_html("openrouter")
        self.assertIn("/api/tausta?keskustelu=", html)
        self.assertIn("setInterval", html)

    @unittest.skipUnless(shutil.which("node"), "node puuttuu")
    def test_sivun_js_nayttaa_taustarivin_kerran_myos_keskustelun_vaihdon_jalkeen(self):
        """Sivun oma JS Nodella oikeaa palvelinta vasten. Sivulle uuden keskustelun alkukohta on palvelimen pituus
        (historian taustarivia ei lisata uudelleen); jo nahdyn keskustelun haku jatkuu sen omasta kohdasta."""
        ev = self.kirjaudu()
        js = re.search(r"<script>(.*)</script>", chat.sivu_html("loopback"), re.S).group(1)
        f = self.r / "sivu_ajo.js"
        f.write_text(NODE_RUNKO.replace("/*SIVU*/", js), encoding="utf-8")
        env = dict(os.environ, PORTTI=str(self.portti), EV=ev, CHAT=str(self.r / "yks" / "chat"),
                   REPO=str(AIVO.parent), PY=sys.executable)
        p = subprocess.run(["node", str(f)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"A_kaksi_hakua": 1, "A_vaihdon_jalkeen": 0, "C_uusi_rivi_vaihdon_jalkeen": 1,
                          "B_toinen_keskustelu": 1, "A_toisessa": 0})


# Minimaalinen DOM ja fetch Nodelle; /*SIVU*/ korvataan chat-sivun omalla JS:lla. Taustarivit kirjoitetaan
# taustaajon omalla funktiolla (lisaa_keskusteluun), kuten tuotannossa.
NODE_RUNKO = r"""
const http=require('http');const {execFileSync}=require('child_process');
function el(id){return {id,children:[],hidden:false,disabled:false,value:id==='tila'?'yksityinen':'',textContent:'',className:'',style:{},
 appendChild(c){this.children.push(c);return c;},append(...c){c.forEach(x=>{if(typeof x!=='string')this.children.push(x);});},
 get lastElementChild(){return this.children[this.children.length-1];},
 addEventListener(){},setAttribute(){},remove(){},querySelectorAll(){return [];},scrollIntoView(){},focus(){}};}
const els={};const viestit=el('viestit');
Object.defineProperty(viestit,'textContent',{get(){return '';},set(v){if(v==='')viestit.children.length=0;}});
global.document={hidden:false,getElementById(i){return i==='viestit'?viestit:(els[i]=els[i]||el(i));},
 querySelector(){return el('header');},querySelectorAll(){return [];},createElement(t){return el(t);}};
global.location={href:''};global.confirm=()=>true;global.setInterval=()=>0;
global.fetch=(url,o={})=>new Promise((res,rej)=>{const q=http.request({host:'127.0.0.1',port:+process.env.PORTTI,path:url,
 method:o.method||'GET',headers:Object.assign({},o.headers||{},{Cookie:process.env.EV})},r=>{let b='';r.on('data',d=>b+=d);
 r.on('end',()=>res({status:r.statusCode,ok:r.statusCode<300,json:async()=>JSON.parse(b)}));});q.on('error',rej);
 if(o.body)q.write(o.body);q.end();});
/*SIVU*/
const kirjoita=(k,t)=>execFileSync(process.env.PY,['-c',
 'import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from datetime import datetime,timezone;'+
 'from aivo import taustaajo as ta;ta.lisaa_keskusteluun(Path(sys.argv[2]),sys.argv[3],ta.valmis_teksti(sys.argv[4]),"t1",'+
 'datetime.now(timezone.utc))',process.env.REPO,process.env.CHAT,k,t]);
const n=t=>viestit.children.filter(d=>typeof d.textContent==='string'&&d.textContent.includes(t)).length;
(async()=>{for(let i=0;i<50&&!kid;i++)await new Promise(r=>setTimeout(r,50));
 await new Promise(r=>setTimeout(r,100));if(!kid)throw new Error('ei keskustelua');
 const tulos={};await laheta('moi');const k1=kid;kirjoita(k1,'TULOS-A');
 await tausta();await tausta();tulos.A_kaksi_hakua=n('TULOS-A');
 await aloita();const k2=kid;await tausta();
 kid=k1;await tausta();await tausta();tulos.A_vaihdon_jalkeen=n('TULOS-A');
 kirjoita(k1,'TULOS-C');await tausta();await tausta();tulos.C_uusi_rivi_vaihdon_jalkeen=n('TULOS-C');
 viestit.children.length=0;kid=k2;await laheta('toinen');kirjoita(k2,'TULOS-B');
 await tausta();await tausta();tulos.B_toinen_keskustelu=n('TULOS-B');tulos.A_toisessa=n('TULOS-A');
 console.log(JSON.stringify(tulos));
})().catch(e=>{console.error('VIRHE',e.constructor.name);process.exit(1);});
"""


class RakenneTesti(unittest.TestCase):
    def test_taustaajo_ei_tuo_openrouter_moduuleja_moduulitasolla(self):
        puu = ast.parse((AIVO / "taustaajo.py").read_text(encoding="utf-8"))
        for n in puu.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                nimet = [a.name for a in n.names] + [getattr(n, "module", "") or ""]
                self.assertFalse([x for x in nimet if "openrouter" in x or "yksityinen_or" in x], nimet)
        lahde = (AIVO / "taustaajo.py").read_text(encoding="utf-8")
        for kielletty in ("urllib", "subprocess", "socket", "openrouter.ai", "http.client"):
            self.assertNotIn(kielletty, lahde)

    def test_tyokalutila_ei_tunne_jonoa(self):
        tyokalu = ("alue.py", "tyokalualue.py", "tyokalu_kaares.py", "tiivista_tyokalu.py", "tiivistelmat_kehote.py")
        for n in tyokalu:
            lahde = (AIVO / n).read_text(encoding="utf-8")
            self.assertNotIn("taustaajo", lahde, n)
            self.assertNotIn("/tyot", lahde, n)
        puu = ast.parse((AIVO / "chat.py").read_text(encoding="utf-8"))
        funktiot = {n.name: n for n in ast.walk(puu) if isinstance(n, ast.FunctionDef)}
        for nimi in ("kysy_claudelta", "_kysy_socketista", "muodosta_syote", "_viesti"):
            nimet = {x.id for x in ast.walk(funktiot[nimi]) if isinstance(x, ast.Name)}
            attr = {x.attr for x in ast.walk(funktiot[nimi]) if isinstance(x, ast.Attribute)}
            self.assertFalse({"taustaajo", "_tausta"} & (nimet | attr), nimi)
        from aivo import tyokalualue, yksityinen_alue
        self.assertTrue(ta.OLETUS_JONO.startswith(str(yksityinen_alue.OLETUS_JUURI) + "/"))
        self.assertFalse(ta.OLETUS_JONO.startswith(str(tyokalualue.OLETUS_JUURI) + "/"))

    def test_tyokalutilan_syote_ei_sisalla_taustaviestia(self):
        historia = [{"rooli": "tony", "teksti": "moi"}]
        self.assertNotIn(ta.VALMIS_MERKINTA, chat.muodosta_syote("", historia))


if __name__ == "__main__":
    unittest.main()
