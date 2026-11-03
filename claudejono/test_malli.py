import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from claudejono import ajuri, kulutus, malli, varaus
from claudejono.test_ajuri import Pohja

TZ = ZoneInfo("Europe/Helsinki")
NYT = datetime(2026, 11, 5, 12, 0, tzinfo=TZ)   # torstai
# Oikean `claude -p --output-format json` -ajon (3.11.2026) olennaiset kentat
OIKEA = {"type": "result", "subtype": "success", "is_error": False, "api_error_status": None, "result": "ok",
         "total_cost_usd": 0.0566142, "duration_ms": 1552,
         "usage": {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 11382, "cache_creation_input_tokens": 13858}}


class Valinta(unittest.TestCase):
    def test_rivi_ratkaisee(self):
        for rivi, reitti, nimi in (("Malli: opus", "claude", "opus"), ("malli:   SONNET ", "claude", "sonnet"),
                                   ("Malli: openrouter:deepseek-flash", "openrouter", "deepseek-flash")):
            v = malli.valitse("2026-11-03-01-x.md", f"# Otsikko\n{rivi}\nteksti")
            self.assertEqual((v.reitti, v.malli, v.lahde), (reitti, nimi, "tehtava"), rivi)

    def test_puuttuva_rivi_paatellaan_tyypista(self):
        self.assertEqual(malli.valitse("2026-11-03-01-korjaa-testit.md", "x").malli, "sonnet")
        self.assertEqual(malli.valitse("2026-11-03-01-arkkitehtuuri-katselmointi.md", "x").malli, "opus")
        v = malli.valitse("2026-11-03-01-uutisten-tiivistelma.md", "x")
        self.assertEqual((v.reitti, v.malli, v.lahde), ("openrouter", "deepseek-flash", "tyyppi"))

    def test_paivamaara_ei_osu_tyyppikarttaan(self):
        self.assertEqual(malli.slug("2026-11-03-05-malli-tyonjako.md"), "malli-tyonjako")

    def test_kielletty_tai_tuntematon_arvo_ei_kelpaa(self):
        for arvo in ("openrouter:posti-zdr", "openrouter:../x", "gpt-5", "haiku", "openrouter:"):
            v = malli.valitse("2026-11-03-01-korjaa.md", f"Malli: {arvo}\n")
            self.assertEqual((v.reitti, v.malli), ("claude", "sonnet"), arvo)
            self.assertIn("ei kelpaa", v.huomautus)

    def test_malli_rivi_vasta_ylhaalla_lasketaan(self):
        teksti = "\n" * 20 + "Malli: opus\n"
        self.assertEqual(malli.valitse("2026-11-03-01-korjaa.md", teksti).malli, "sonnet")

    def test_claude_komento_antaa_mallin(self):
        self.assertEqual(ajuri.claude_komento("k", {}, "opus")[-2:], ["--model", "opus"])
        self.assertNotIn("--model", ajuri.claude_komento("k", {}))
        self.assertNotIn("--model", ajuri.claude_komento("k", {}, "openrouter"))


class OpenRouterKutsu(unittest.TestCase):
    def kutsu(self, vastaus, otsakkeet=None, env=None):
        nahty = {}

        def hae(url, avain, payload, aikaraja):
            nahty.update(url=url, avain=avain, payload=payload)
            return vastaus, otsakkeet or {}
        env = {"LITELLM_API_KEY": "testiavain"} if env is None else env
        return malli.openrouter_kutsu("deepseek-flash", "kysymys", env, hae), nahty

    def test_onnistuu_ja_lukee_kulun_otsakkeesta(self):
        v = {"choices": [{"message": {"content": "vastaus"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
        tulos, nahty = self.kutsu(v, {"X-LiteLLM-Response-Cost": "0.0004"})
        self.assertEqual(tulos, {"teksti": "vastaus", "input": 10, "output": 3, "usd": 0.0004})
        self.assertNotIn("tools", nahty["payload"])
        self.assertEqual(nahty["payload"]["model"], "deepseek-flash")
        self.assertEqual(nahty["payload"]["max_tokens"], malli.OPENROUTER_MAX_TOKENS)
        self.assertTrue(nahty["url"].endswith("/chat/completions"))

    def test_kulu_puuttuu_otsakkeesta(self):
        tulos, _ = self.kutsu({"choices": [{"message": {"content": "x"}}]})
        self.assertIsNone(tulos["usd"])

    def test_virheet_ovat_koodeja(self):
        for vastaus, env in (({"choices": []}, None), ({"choices": [{"message": {"content": " "}}]}, None),
                             ({"choices": [{"message": {"content": "x"}}]}, {})):
            with self.assertRaises(malli.OpenRouterVirhe):
                self.kutsu(vastaus, env=env)
        with self.assertRaises(malli.OpenRouterVirhe) as c:
            malli.openrouter_kutsu("posti-zdr", "x", {"LITELLM_API_KEY": "a"}, lambda *a: ({}, {}))
        self.assertEqual(c.exception.koodi, "or_asetus")


class Kulutusmittari(unittest.TestCase):
    def setUp(self):
        self.tila = Path(tempfile.mkdtemp())

    def rivi(self, malli_, pv, usd=1.0, ok=True, reitti="claude", tunti=10, **kw):
        r = {"aika": (NYT.replace(hour=tunti) - timedelta(days=pv)).isoformat(), "tehtava": "t", "malli": malli_, "reitti": reitti,
             "ok": ok, "input": 1, "output": 2, "cache_luku": 3, "cache_luonti": 4, "kesto_s": 1.0, "usd": usd, "rate_limit": False}
        r.update(kw)
        return r

    def test_rivi_claude_oikeasta_json_muodosta(self):
        r = kulutus.rivi_claude("t.md", "sonnet", OIKEA, 9.0, True, NYT)
        self.assertEqual((r["input"], r["output"], r["cache_luku"], r["cache_luonti"]), (2, 4, 11382, 13858))
        self.assertEqual((r["usd"], r["kesto_s"], r["malli"], r["reitti"]), (0.0566142, 1.6, "sonnet", "claude"))

    def test_rivi_claude_lukukelvottomasta_tulosteesta(self):
        r = kulutus.rivi_claude("t.md", "opus", None, 7.26, False, NYT)
        self.assertEqual((r["input"], r["usd"], r["kesto_s"], r["ok"]), (0, None, 7.3, False))

    def test_kirjaa_ja_lue_ohittaa_rikkinaiset(self):
        kulutus.kirjaa(self.tila, self.rivi("sonnet", 0))
        with open(self.tila / "kulutus.jsonl", "a") as f:
            f.write("roskaa\n{\"aika\": \"ei-aika\"}\n")
        kulutus.kirjaa(self.tila, self.rivi("opus", 0))
        self.assertEqual([r["malli"] for r in kulutus.lue(self.tila)], ["sonnet", "opus"])

    def test_kirjaus_ei_kaada(self):
        self.assertFalse(kulutus.kirjaa("/proc/ei/ole/olemassa", {"a": 1}))

    def test_koonti_eilen_ja_viikko_malleittain(self):
        rivit = [self.rivi("sonnet", 1, 2.0), self.rivi("sonnet", 1, 3.0), self.rivi("opus", 1, 5.0),
                 self.rivi("sonnet", 0, 1.0), self.rivi("sonnet", 10, 99.0)]
        for r in rivit:
            r["_aika"] = datetime.fromisoformat(r["aika"])
        k = kulutus.koonti(rivit, NYT)
        self.assertEqual({m: (a["ajoja"], a["usd"]) for m, a in k["eilen"].items()}, {"sonnet": (2, 5.0), "opus": (1, 5.0)})
        self.assertEqual(k["viikko"]["sonnet"]["usd"], 6.0)    # ma-to, ei 10 pv sitten
        teksti = kulutus.kulutusrivi(k)
        self.assertIn("opus 1 ajo 5,00 USD", teksti)
        self.assertIn("sonnet 2 ajoa 5,00 USD", teksti)
        self.assertIn("viikko:", teksti)

    def test_koonti_tyhja(self):
        self.assertIn("eilen: ei ajoja; viikko: ei ajoja", kulutus.kulutusrivi(kulutus.koonti([], NYT)))

    def test_hinta_puuttuu_merkitaan(self):
        r = self.rivi("sonnet", 1, usd=None)
        r["_aika"] = datetime.fromisoformat(r["aika"])
        self.assertIn("*", kulutus.kulutusrivi(kulutus.koonti([r], NYT)))

    def test_laatu_ehdotus_vain_selvasta_erosta(self):
        def ajot(malli_, n, ok):
            return [self.rivi(malli_, 1, ok=i < ok) for i in range(n)]
        halpa = "openrouter:deepseek-flash"
        tulos, ehd = kulutus.laatu(ajot("sonnet", 10, 10) + ajot(halpa, 10, 5))
        self.assertEqual(tulos[halpa]["virhe_osuus"], 0.5)
        self.assertEqual(len(ehd), 1)
        self.assertIn("Sonnetille", ehd[0])
        _, ehd = kulutus.laatu(ajot("sonnet", 10, 9) + ajot(halpa, 10, 8))        # ero 10 %-yks.
        self.assertEqual(ehd, [])
        _, ehd = kulutus.laatu(ajot("sonnet", 10, 10) + ajot(halpa, 4, 0))        # liian vahan dataa
        self.assertEqual(ehd, [])

    def test_laatu_ohittaa_kayttorajapysaytyksen(self):
        tulos, _ = kulutus.laatu([self.rivi("sonnet", 1, ok=False, rate_limit=True), self.rivi("sonnet", 1)])
        self.assertEqual(tulos["sonnet"]["ajoja"], 1)

    def test_kalibroi_validoi(self):
        self.assertEqual(kulutus.kalibroi(self.tila, "37,5 %", NYT), 37.5)
        for huono in ("101", "-1", "abc"):
            with self.assertRaises(ValueError):
                kulutus.kalibroi(self.tila, huono, NYT)
        self.assertEqual(len(kulutus.lue(self.tila, "kalibrointi.jsonl")), 1)

    def test_litellm_kulut(self):
        eilen = (NYT - timedelta(days=1)).astimezone(ZoneInfo("UTC")).isoformat()
        data = [{"model": "deepseek-flash", "spend": 0.25, "startTime": eilen}, {"model": "deepseek-flash", "spend": 0.5, "startTime": eilen},
                {"model": "x", "spend": 9, "startTime": (NYT - timedelta(days=4)).isoformat()}, {"spend": "huono"}, "roska"]
        self.assertEqual(kulutus.litellm_kulut({"LITELLM_API_KEY": "a"}, NYT, lambda url, avain: data), {"deepseek-flash": 0.75})
        self.assertIsNone(kulutus.litellm_kulut({}, NYT, lambda *a: data))               # ei avainta
        def rikki(*a):
            raise OSError("x")
        self.assertIsNone(kulutus.litellm_kulut({"LITELLM_API_KEY": "a"}, NYT, rikki))
        self.assertIn("ei saatu", kulutus.litellmrivi(None))


class ViikkoLaatu(unittest.TestCase):
    def test_viikkoehdotus_nostaa_siirtoehdotuksen(self):
        from claudejono import viikkoehdotus
        tila = Path(tempfile.mkdtemp())
        repo = tila / "docs"
        repo.mkdir()
        for m, n, ok in (("sonnet", 10, 10), ("openrouter:qwen-coder", 10, 4)):
            for i in range(n):
                kulutus.kirjaa(tila, {"aika": NYT.isoformat(), "tehtava": "t", "malli": m, "reitti": "x", "ok": i < ok, "usd": 0.1})
        _, teksti, _ = viikkoehdotus.rakenna(repo, NYT, tila)
        self.assertIn("Mallien laatu", teksti)
        self.assertIn("openrouter:qwen-coder", teksti)
        self.assertNotIn("Mallien laatu", viikkoehdotus.rakenna(repo, NYT)[1])


class Varausraja(unittest.TestCase):
    def setUp(self):
        self.tila = Path(tempfile.mkdtemp())

    def claude_usd(self, usd, pv=1):
        kulutus.kirjaa(self.tila, {"aika": (NYT - timedelta(days=pv)).isoformat(), "tehtava": "t", "malli": "sonnet",
                                   "reitti": "claude", "ok": True, "usd": usd})

    def kalibroi(self, pros, pv):
        kulutus.kalibroi(self.tila, pros, NYT - timedelta(days=pv, hours=-1))

    def test_osuus_asetuksesta(self):
        self.assertEqual(varaus.agenttiosuus({}), 60.0)
        self.assertEqual(varaus.agenttiosuus({"CLAUDEJONO_AGENTTIOSUUS": "40"}), 40.0)
        for huono in ("0", "101", "x", "-5"):
            self.assertEqual(varaus.agenttiosuus({"CLAUDEJONO_AGENTTIOSUUS": huono}), 60.0, huono)

    def test_ilman_kalibrointia_ei_rajoiteta_mutta_kerrotaan(self):
        self.claude_usd(500)
        self.assertEqual(varaus.arvio(self.tila, {}, NYT)["taso"], "ei_kalibroitu")
        self.assertEqual(varaus.lupa(self.tila, {}, NYT, 3)[:2], (True, "ei_kalibroitu"))
        self.assertIn("kalibroi", varaus.kalibrointikysymys(self.tila, NYT))

    def test_kerroin_on_tiukin_ylaraja_kalibrointiväleilta(self):
        # vali 1: +10 % / 10 usd = 1,0 %/usd; vali 2: +4 % / 20 usd = 0,2 %/usd (Tony kaytti vahan -> tiukin raja = 0,2)
        self.kalibroi(10, 3)
        self.claude_usd(10, 2)
        self.kalibroi(20, 2)
        self.claude_usd(20, 1)
        self.kalibroi(24, 1)
        k, laatu = varaus.kerroin(kulutus.lue(self.tila), kulutus.lue(self.tila, "kalibrointi.jsonl"), NYT)
        self.assertEqual(laatu, "vali")
        self.assertAlmostEqual(k, 0.2)

    def test_yksi_kalibrointi_antaa_karkean_arvion(self):
        self.claude_usd(50, 2)
        self.kalibroi(30, 1)
        k, laatu = varaus.kerroin(kulutus.lue(self.tila), kulutus.lue(self.tila, "kalibrointi.jsonl"), NYT)
        self.assertEqual((laatu, round(k, 3)), ("karkea", 0.6))

    def test_nollautuminen_ja_kohina_ohitetaan(self):
        self.kalibroi(50, 3)
        self.claude_usd(5, 2)
        self.kalibroi(5, 2)           # luku laski: viikko vaihtui
        self.assertEqual(varaus.kerroin(kulutus.lue(self.tila), kulutus.lue(self.tila, "kalibrointi.jsonl"), NYT)[1], "data_ei_riita")

    def rakenna(self, kerroin_pros_per_usd, usd):
        # yksi kalibrointi 2 pv sitten, johon asti agentit kuluttivat usd
        self.claude_usd(usd, 3)
        kulutus.kalibroi(self.tila, kerroin_pros_per_usd * usd, NYT - timedelta(days=2))

    def test_tasot_normaali_hidastettu_pysaytetty(self):
        self.rakenna(1.0, 40)                                   # osuus 40 % < 48 %
        self.assertEqual(varaus.lupa(self.tila, {}, NYT, 2), (True, "normaali", ""))
        self.claude_usd(10, 0)                                  # 50 %: >= 0,8 * 60
        saa1, taso1, _ = varaus.lupa(self.tila, {}, NYT, 1)
        saa2, taso2, syy2 = varaus.lupa(self.tila, {}, NYT, 2)
        self.assertEqual((saa1, taso1, saa2, taso2), (True, "hidastettu", False, "hidastettu"))
        self.assertIn("kaista 1", syy2)
        self.claude_usd(10, 0)                                  # 60 % = raja
        self.assertEqual(varaus.lupa(self.tila, {}, NYT, 1)[:2], (False, "pysaytetty"))
        self.assertEqual(varaus.lupa(self.tila, {"CLAUDEJONO_AGENTTIOSUUS": "90"}, NYT, 1)[:2], (True, "normaali"))   # Tony nostaa rajan 90 %:iin

    def test_rate_limit_tunnistus(self):
        self.assertTrue(varaus.on_rate_limit({"api_error_status": 429}))
        self.assertTrue(varaus.on_rate_limit({"is_error": True, "result": "Claude usage limit reached"}))
        self.assertFalse(varaus.on_rate_limit({"is_error": False, "result": "tehtava kasitteli rate limit -kayttoa"}))
        self.assertFalse(varaus.on_rate_limit(OIKEA))
        self.assertTrue(varaus.on_rate_limit(None, "", "Error: 429 Too Many Requests"))
        self.assertFalse(varaus.on_rate_limit(None, "", "Error: jokin muu"))

    def test_rate_limit_tauko_ja_vanheneminen(self):
        varaus.aseta_rate_limit(self.tila, NYT.timestamp(), 3600)
        self.assertEqual(varaus.lupa(self.tila, {}, NYT, 1)[:2], (False, "rate_limit"))
        self.assertTrue(varaus.lupa(self.tila, {}, NYT + timedelta(minutes=61), 1)[0])

    def test_ilmoitus_vain_tason_muuttuessa(self):
        viestit = []
        for taso, odotus in (("normaali", False), ("pysaytetty", True), ("pysaytetty", False), ("normaali", True), ("normaali", False)):
            self.assertIs(varaus.ilmoita_tason_muutos(self.tila, taso, "syy" if taso == "pysaytetty" else "", viestit.append), odotus, taso)
        self.assertEqual(len(viestit), 2)
        self.assertIn("rajoitus purkautui", viestit[1])

    def test_kalibrointikysymys_vain_kun_vanha(self):
        self.kalibroi(10, 1)
        self.assertEqual(varaus.kalibrointikysymys(self.tila, NYT), "")
        self.assertNotEqual(varaus.kalibrointikysymys(self.tila, NYT + timedelta(days=4)), "")


def valekomento(vastaus, kutsut):
    def f(kom, **kw):
        kutsut.append(kom)
        return subprocess.CompletedProcess(kom, 0, json.dumps(vastaus), "")
    return f


class AjoReiteilla(Pohja):
    """Ajuri kokonaisuutena oikean git-repon kanssa: jokainen reitti, kirjaus ja pysaytykset."""

    def aja(self, vastaus=OIKEA, env=None, nyt=NYT):
        kutsut, viestit = [], []
        v = ajuri.aja(self.repo, self.tmp, env={"CLAUDEJONO_ITSESUUNNITTELU": "0", **(env or {})},
                      suorita=valekomento(vastaus, kutsut), laheta=viestit.append, nyt=nyt)
        return v, kutsut, viestit

    def tulos(self, nimi):
        return (self.repo / ajuri.JONO / "tulokset" / nimi).read_text()

    def rivit(self):
        return kulutus.lue(self.tmp)

    def test_oletus_sonnet_kirjaa_kulutuksen_ja_mallin(self):
        self.lisaa_tehtava("2026-11-05-01-korjaa.md")
        v, kutsut, _ = self.aja()
        self.assertEqual(v, "claude-jono: 2026-11-05-01-korjaa.md VALMIS")
        self.assertEqual(kutsut[0][kutsut[0].index("--model") + 1], "sonnet")
        self.assertIn("- Malli: sonnet", self.tulos("2026-11-05-01-korjaa.md"))
        r = self.rivit()[0]
        self.assertEqual((r["malli"], r["reitti"], r["cache_luonti"], r["usd"], r["ok"]), ("sonnet", "claude", 13858, 0.0566142, True))

    def test_opus_tehtavarivilla(self):
        self.lisaa_tehtava("2026-11-05-01-korjaa.md", "Malli: opus\ntee")
        _, kutsut, _ = self.aja()
        self.assertEqual(kutsut[0][kutsut[0].index("--model") + 1], "opus")
        self.assertEqual(self.rivit()[0]["malli"], "opus")

    def test_openrouter_ei_kutsu_claudea(self):
        self.lisaa_tehtava("2026-11-05-01-yhteenveto.md", "Malli: openrouter:deepseek-flash\ntiivista tama")
        vastaus = ({"choices": [{"message": {"content": "tiivistelma"}}], "usage": {"prompt_tokens": 50, "completion_tokens": 7}},
                   {"x-litellm-response-cost": "0.0002"})
        with mock.patch.object(malli, "_http_post", return_value=vastaus):
            v, kutsut, _ = self.aja(env={"LITELLM_API_KEY": "a"})
        self.assertEqual((v, kutsut), ("claude-jono: 2026-11-05-01-yhteenveto.md VALMIS", []))
        t = self.tulos("2026-11-05-01-yhteenveto.md")
        self.assertIn("- Malli: openrouter:deepseek-flash", t)
        self.assertIn("tiivistelma", t)
        r = self.rivit()[0]
        self.assertEqual((r["reitti"], r["input"], r["output"], r["usd"]), ("openrouter", 50, 7, 0.0002))

    def test_openrouter_virhe_epaonnistuu_vain_koodilla(self):
        self.lisaa_tehtava("2026-11-05-01-yhteenveto.md", "Malli: openrouter:deepseek-flash\nx")
        v, _, _ = self.aja(env={})          # avain puuttuu
        self.assertIn("EPAONNISTUI", v)
        self.assertIn("or_asetus", self.tulos("2026-11-05-01-yhteenveto.md"))
        self.assertFalse(self.rivit()[0]["ok"])

    def test_rate_limit_pysayttaa_eika_kirjaa_tulosta_eika_toista(self):
        self.lisaa_tehtava("2026-11-05-01-a.md")
        self.lisaa_tehtava("2026-11-05-02-b.md")
        raja = {"type": "result", "subtype": "error_during_execution", "is_error": True, "api_error_status": 429, "result": "limit"}
        v, kutsut, viestit = self.aja(raja)
        self.assertIn("jai odottamaan", v)
        self.assertFalse((self.repo / ajuri.JONO / "tulokset").exists() and list((self.repo / ajuri.JONO / "tulokset").iterdir()))
        self.assertEqual(len(kutsut), 1)
        self.assertTrue(self.rivit()[0]["rate_limit"])
        self.assertTrue(any("rate_limit" in m for m in viestit))
        v2, kutsut2, _ = self.aja(raja, nyt=NYT + timedelta(minutes=30))       # taukoa jaljella: ei uutta kutsua
        self.assertTrue(v2.startswith("jono odottaa"))
        self.assertEqual(kutsut2, [])
        v3, kutsut3, _ = self.aja(OIKEA, nyt=NYT + timedelta(minutes=61))      # tauko ohi: yksi yritys
        self.assertEqual(len(kutsut3), 1)
        self.assertIn("VALMIS", v3)

    def test_rate_limit_ei_estaa_openrouteria(self):
        varaus.aseta_rate_limit(self.tmp, NYT.timestamp())
        self.lisaa_tehtava("2026-11-05-01-claude.md")
        self.lisaa_tehtava("2026-11-05-02-halpa.md", "Malli: openrouter:qwen-coder\nx")
        vastaus = ({"choices": [{"message": {"content": "ok"}}]}, {})
        with mock.patch.object(malli, "_http_post", return_value=vastaus):
            v, kutsut, _ = self.aja(env={"LITELLM_API_KEY": "a"})
        self.assertIn("02-halpa", v)
        self.assertEqual(kutsut, [])

    def test_varausraja_pysayttaa_clauden_ja_itsesuunnittelun(self):
        kulutus.kirjaa(self.tmp, {"aika": (NYT - timedelta(days=2)).isoformat(), "tehtava": "t", "malli": "sonnet", "reitti": "claude", "ok": True, "usd": 10})
        kulutus.kalibroi(self.tmp, 70, NYT - timedelta(days=1))      # 7 %/usd * 10 usd = 70 % > 60 %
        self.lisaa_tehtava("2026-11-05-01-a.md")
        v, kutsut, viestit = self.aja()
        self.assertTrue(v.startswith("jono odottaa"))
        self.assertEqual(kutsut, [])
        self.assertTrue(any("pysaytetty" in m for m in viestit))
        # itsesuunnittelu paalla: tehtava odottaa edelleen, ja suunnittelukaan ei kutsu Claudea
        kutsut2 = []
        ajuri.aja(self.repo, self.tmp, env={}, suorita=valekomento(OIKEA, kutsut2), nyt=NYT)
        self.assertEqual(kutsut2, [])

    def test_hidastus_kaista_2_odottaa_kaista_1_ajaa(self):
        kulutus.kirjaa(self.tmp, {"aika": (NYT - timedelta(days=2)).isoformat(), "tehtava": "t", "malli": "sonnet", "reitti": "claude", "ok": True, "usd": 10})
        kulutus.kalibroi(self.tmp, 50, NYT - timedelta(days=1))      # 50 % : 80 % * 60 = 48
        self.lisaa_tehtava("2026-11-05-01-a.md")
        v2, k2, _ = self.aja(env={"CLAUDEJONO_KAISTA": "2"})
        self.assertTrue(v2.startswith("jono odottaa") and k2 == [])
        v1, k1, _ = self.aja(env={"CLAUDEJONO_KAISTA": "1"})
        self.assertIn("VALMIS", v1)


if __name__ == "__main__":
    unittest.main()
