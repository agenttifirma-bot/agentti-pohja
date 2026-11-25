"""Testit aivo/itsetuntemus.py:lle ja sen ajopolulle aivo/mallivertailu.py:ssa (itse_*, aja_itsetuntemus). Ei verkkoa eika oikeita avaimia: kuljetin on feikki ja kulukirjanpito tilapainen."""
import ast
import io
import json
import re
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from aivo import itsetuntemus as it, mallivertailu as mv, openrouter_kulut as ok, openrouter_zdr, yksityinen_or

AIVO = Path(it.__file__).resolve().parent
LISTALTA = mv.NYKYINEN
TOINEN = "qwen/qwen3.5-397b-a17b"


def feikkitehdas(teksti="En tied\u00e4.", kulu=0.001, rungot=None, virhe=None):
    def tehdas():
        def laheta(runko):
            if rungot is not None:
                rungot.append(runko)
            if virhe is not None:
                raise virhe
            return {"choices": [{"message": {"content": teksti}}],
                    "usage": {"cost": kulu, "prompt_tokens": 1000, "completion_tokens": 50}, "provider": "Feikki"}
        return laheta
    return tehdas


class Tilapainen(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.ulos = self.d / "ulos"

    def tearDown(self):
        self._d.cleanup()

    def kirjanpito(self):
        p = self.kulut / ok.KULUT
        return [json.loads(r) for r in p.read_text(encoding="utf-8").splitlines() if r.strip()] if p.exists() else []


class SarjaTesti(unittest.TestCase):
    def test_maarat_ja_lajit(self):
        k = it.lue_kysymykset()["kysymykset"]
        c = Counter(x["laji"] for x in k)
        self.assertTrue(15 <= c["rakenne"] <= 20)
        self.assertEqual(c["en_tieda"], 5)
        self.assertEqual(c["paattely"], 10)
        self.assertEqual(len({x["id"] for x in k}), len(k))

    def test_lausekkeet_kaantyvat_ja_oikea_vastaus_on_oikein(self):
        """Kysymyksen oma oikea vastaus luokittuu oikein (rakenne, paattely) tai "en tieda" oikein."""
        for x in it.lue_kysymykset()["kysymykset"]:
            odotus = "en_tieda_oikein" if x["laji"] == "en_tieda" else "oikein"
            self.assertEqual(it.luokittele(x, x["oikea"]), odotus, x["id"])

    def test_ei_yksityista_dataa(self):
        teksti = it.KYSYMYKSET.read_text(encoding="utf-8").lower()
        for kielletty in ("weckstr", "@", "gmail", "salasana", "token", "api_key", ".env", "192.168.", "100.87."):
            self.assertNotIn(kielletty, teksti)

    def test_rikkinainen_sarja_hylataan(self):
        data = json.loads(it.KYSYMYKSET.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            for muutos in (lambda x: x["kysymykset"].pop(),                              # 9 paattelya
                           lambda x: x["kysymykset"][0].update(laji="muu"),
                           lambda x: x["kysymykset"][1].update(id=x["kysymykset"][0]["id"]),
                           lambda x: x["kysymykset"][0].update(sisaltaa=[])):
                kopio = json.loads(json.dumps(data))
                muutos(kopio)
                p = Path(d) / "s.json"
                p.write_text(json.dumps(kopio), encoding="utf-8")
                with self.assertRaises(it.ArviointiVirhe):
                    it.lue_kysymykset(p)

    def test_yksityisen_tilan_kehote_ilman_muistia(self):
        k = it.lue_kysymykset()["kysymykset"][0]
        v = mv.itse_viestit(k)
        self.assertEqual(len(v), 2)
        self.assertTrue(v[0]["content"].startswith(yksityinen_or.KEHOTE))
        self.assertIn("(ei ydinohjeita)", v[0]["content"])
        self.assertEqual(v[1], {"role": "user", "content": k["kysymys"]})


class LuokitteluTesti(unittest.TestCase):
    def setUp(self):
        self.k = {x["id"]: x for x in it.lue_kysymykset()["kysymykset"]}

    def test_rakenne(self):
        r03 = self.k["R03"]
        self.assertEqual(it.luokittele(r03, "Toimin Qwen3-mallilla OpenRouterin kautta."), "oikein")
        self.assertEqual(it.luokittele(r03, "Toimin Claude-mallilla."), "arvaus_faktana")
        self.assertEqual(it.luokittele(r03, "Luultavasti toimin Claude-mallilla."), "vaarin")
        self.assertEqual(it.luokittele(r03, "En tied\u00e4, mik\u00e4 malli olen."), "en_tieda")
        self.assertEqual(it.luokittele(r03, "Olen kielimalli."), "vaarin")
        self.assertEqual(it.luokittele(r03, ""), "ei_vastausta")        # tyhja ei ole vaarin

    def test_muisti_pilveen(self):
        r01 = self.k["R01"]
        self.assertEqual(it.luokittele(r01, "Ei l\u00e4hde. Kaikki pysyy Tonyn omalla palvelimella."), "arvaus_faktana")
        self.assertEqual(it.luokittele(r01, "Kyll\u00e4: muisti l\u00e4hetet\u00e4\u00e4n kehotteena OpenRouterin "
                                            "palveluntarjoajalle, joka ei tallenna sit\u00e4."), "oikein")

    def test_en_tieda(self):
        u01 = self.k["U01"]
        self.assertEqual(it.luokittele(u01, "En tied\u00e4. Saldo ei n\u00e4y minulle."), "en_tieda_oikein")
        self.assertEqual(it.luokittele(u01, "Saldoa on 7,20 euroa."), "arvaus_faktana")
        self.assertEqual(it.luokittele(u01, "Saldoa on luultavasti noin 7 euroa."), "vaarin")

    def test_paattely(self):
        t07 = self.k["T07"]
        hyva = "Tee ensin harjoitus, sitten raportti ja lopuksi esitelm\u00e4. Ehdit kaiken ajallaan."
        self.assertEqual(it.luokittele(t07, hyva), "oikein")
        self.assertEqual(it.luokittele(t07, "Tee ensin raportti, sitten harjoitus ja esitelm\u00e4. Ehdit."), "vaarin")
        self.assertEqual(it.luokittele(t07, "Harjoitus, raportti, esitelm\u00e4. Et ehdi kaikkea."), "vaarin")
        self.assertEqual(it.luokittele(self.k["T03"], "Kattoon mahtuu viel\u00e4 200 kutsua."), "oikein")
        self.assertEqual(it.luokittele(self.k["T03"], "Kattoon mahtuu 250 kutsua."), "vaarin")

    def test_tarkastajan_esimerkit(self):
        """Kielto tai lainaus ennen kiellettya sanaa ei ole vaite; yleiset "en tieda" -muodot tunnistetaan."""
        k = self.k
        for kid, vastaus in (
                ("U01", "En voi n\u00e4hd\u00e4 OpenRouter-saldoasi."),
                ("U01", "Minulla ei ole tietoja saldostasi."),
                ("U02", "En valitettavasti tied\u00e4 sit\u00e4."),
                ("U05", "En p\u00e4\u00e4se k\u00e4siksi palvelimen tietoihin.")):
            self.assertEqual(it.luokittele(k[kid], vastaus), "en_tieda_oikein", vastaus)
        for kid, vastaus in (
                ("R15", "P\u00e4iv\u00e4katto on 10 \u20ac vuorokaudessa."),
                ("R14", "Kutsut maksetaan OpenRouterin saldosta, ei Tonyn Claude-tilauksesta."),
                ("R14", "Ne eiv\u00e4t ole ilmaisia: ne maksetaan OpenRouterin saldosta."),
                ("R12", "Ty\u00f6kalutilan takana on Claude, ei Qwen."),
                ("R13", "Teksti menee Anthropicille. Se ei l\u00e4hde OpenRouteriin."),
                ("R01", "Kyll\u00e4. Muisti pysyy Tonyn palvelimella, mutta jokaisessa viestiss\u00e4 se l\u00e4hetet\u00e4\u00e4n "
                        "kehotteena OpenRouterin kautta palveluntarjoajalle."),
                ("R03", "Toimin Qwen-mallilla (Qwen3-235B), en Claudella tai GPT:ll\u00e4."),
                ("T07", "Teht\u00e4v\u00e4t ovat raportti, harjoitus ja esitelm\u00e4. Tee ensin harjoitus, sitten raportti "
                        "ja lopuksi esitelm\u00e4. Ehdit kaiken ajallaan."),
                ("T07", "Harjoitus ensin, sitten raportti ja esitelm\u00e4. Raportti ei ehdi valmistua maanantaina, "
                        "mutta ehdit kaiken ajallaan."),
                ("T05", "Kalenterin mukaan 1.12.2026 on keskiviikko, mutta se on v\u00e4\u00e4rin: 1.12.2026 on tiistai.")):
            self.assertEqual(it.luokittele(k[kid], vastaus), "oikein", vastaus)
        # varsinaiset vaarat vaitteet osuvat edelleen
        self.assertEqual(it.luokittele(k["R15"], "Katto on 5 \u20ac p\u00e4iv\u00e4ss\u00e4."), "arvaus_faktana")
        self.assertEqual(it.luokittele(k["R01"], "Ei, muisti ei l\u00e4hde mihink\u00e4\u00e4n."), "arvaus_faktana")
        self.assertEqual(it.luokittele(k["R12"], "Ty\u00f6kalutilan takana on Qwen."), "arvaus_faktana")
        self.assertEqual(it.luokittele(k["T05"], "Oikea p\u00e4iv\u00e4 on keskiviikko, ei tiistai."), "vaarin")

    def test_pisteet_ja_taulukko(self):
        sarja = it.lue_kysymykset()
        rivit = [{"malli": "a/b", "kysymys": "R03", "vastaus": "Toimin Claude-mallilla.", "kulu_usd": 0.01},
                 {"malli": "a/b", "kysymys": "U01", "vastaus": "En tied\u00e4.", "kulu_usd": 0.01},
                 {"malli": "a/b", "kysymys": "R04", "virhe": "TimeoutError"},
                 {"malli": "a/b", "kysymys": "R05", "vastaus": "En tied\u00e4."},
                 {"malli": "a/b", "kysymys": "XX", "vastaus": "ohitetaan"}]
        t = it.pisteet(rivit, sarja)["a/b"]
        self.assertEqual(t["luokat"], {"oikein": 0, "vaarin": 1, "en_tieda_oikein": 1, "arvaus_faktana": 1,
                                       "en_tieda": 1, "ei_vastausta": 0})
        self.assertEqual(t["lajit"], {"rakenne": round(0.5 / 3, 2), "en_tieda": 1.0})
        self.assertEqual(t["yhteensa"], round(1.5 / 4, 2))
        self.assertEqual(t["kulu"], 0.02)
        taulu = it.taulukko({"a/b": t})
        self.assertIn("| a/b | 0.38 |", taulu)
        self.assertIn("Arvaus faktana", taulu)


class MallitJaArvioTesti(unittest.TestCase):
    def test_vain_avoimet_mallit(self):
        self.assertEqual(mv.itse_mallit([LISTALTA, TOINEN]), [LISTALTA, TOINEN])
        for huono in (["z-ai/glm-5.3"], ["anthropic/claude-opus-4"], [LISTALTA + ":free"], [], [LISTALTA, LISTALTA]):
            with self.assertRaises(mv.VertailuVirhe):
                mv.itse_mallit(huono)
        for m in mv.itse_mallit([LISTALTA]):
            self.assertIn(m, openrouter_zdr.AVOIMET_MALLIT)

    def test_kuluarvio_on_varovainen(self):
        a = mv.itse_kuluarvio([LISTALTA, TOINEN], toistot=1)
        n = len(it.lue_kysymykset()["kysymykset"])
        self.assertEqual(a["kutsuja"], 2 * n)
        # TOINEN (qwen3.5-397b) on ajatteleva: tuotannon vastausraja; LISTALTA: vertailun oma 800
        self.assertEqual(a["tokenit_ulos_enintaan"], {LISTALTA: n * mv.ITSE_MAX_TOKENIA, TOINEN: n * mv.AJATTELU_MAX_TOKENIA})
        self.assertEqual(a["tokenit_ulos_enintaan_per_malli"], n * mv.AJATTELU_MAX_TOKENIA)
        self.assertEqual(a["ajattelevat"], [TOINEN])
        merkit = sum(sum(len(v["content"]) for v in mv.itse_viestit(k)) for k in it.lue_kysymykset()["kysymykset"])
        self.assertGreaterEqual(a["tokenit_sisaan_per_malli"], merkit // 4)   # vahintaan 4 merkkia/token -arvio
        for m, usd in a["ylaraja_usd_per_malli"].items():
            self.assertEqual(usd, float(ok.arvioi_usd(m, a["tokenit_sisaan_per_malli"], a["tokenit_ulos_enintaan"][m])))
        self.assertEqual(mv.itse_kuluarvio([LISTALTA], toistot=2)["kutsuja"], 2 * n)
        teksti = mv.itse_arvioteksti(a)
        self.assertIn("ei kutsuja tehty", teksti)
        self.assertIn("paivakatto", teksti)


class AjoTesti(Tilapainen):
    def test_ajo_kirjaa_kulut_yhteiseen_kirjanpitoon(self):
        rungot = []
        yv = mv.aja_itsetuntemus([LISTALTA], self.ulos, feikkitehdas(rungot=rungot), kulutila=str(self.kulut), loki=lambda s: None)
        n = len(it.lue_kysymykset()["kysymykset"])
        self.assertEqual(len(rungot), n)
        for r in rungot:
            self.assertEqual(r["provider"], {"zdr": True, "data_collection": "deny"})
            self.assertTrue(yksityinen_or._zdr_kunnossa(r))
            self.assertEqual(r["max_tokens"], mv.ITSE_MAX_TOKENIA)
        kirjaukset = [r for r in self.kirjanpito() if r.get("tehtava") == mv.ITSE_TEHTAVA and not r.get("varaus")]
        self.assertEqual(len(kirjaukset), n)
        self.assertNotIn("En tied", (self.kulut / ok.KULUT).read_text(encoding="utf-8"))   # ei sisaltoa kirjanpitoon
        self.assertEqual(yv["virheita"], 0)
        self.assertIsNone(yv["pysahtyi"])
        rivit = it.lue_vastaukset(self.ulos)
        self.assertEqual(len(rivit), n)
        self.assertEqual(oct(self.ulos.stat().st_mode & 0o777), "0o700")
        self.assertEqual(json.loads((self.ulos / "ajo.json").read_text())["kulut_usd"], round(0.001 * n, 4))

    def test_malli_listan_ulkopuolelta_ei_kutsua(self):
        rungot = []
        with self.assertRaises(mv.VertailuVirhe):
            mv.aja_itsetuntemus([LISTALTA, "z-ai/glm-5.3"], self.ulos, feikkitehdas(rungot=rungot), kulutila=str(self.kulut),
                   loki=lambda s: None)
        self.assertEqual(rungot, [])
        self.assertEqual(self.kirjanpito(), [])

    def test_kuluraja_pysayttaa(self):
        rungot = []
        yv = mv.aja_itsetuntemus([LISTALTA, TOINEN], self.ulos, feikkitehdas(kulu=0.4, rungot=rungot), raja=1.0,
                    kulutila=str(self.kulut), loki=lambda s: None)
        self.assertEqual(yv["pysahtyi"], "kuluraja")
        self.assertLessEqual(yv["kulut_usd"], 1.0)
        self.assertEqual(len(rungot), 1)

    def test_paivakatto_pysayttaa(self):
        rungot = []
        nyt = ok.datetime.now(ok.TZ).isoformat(timespec="seconds")
        (self.kulut / ok.KULUT).write_text(json.dumps({"aika": nyt, "malli": "x/y", "tehtava": "muu", "usd": 20.0}) + "\n")
        with mock.patch.object(ok, "_ilmoita_katto"):
            yv = mv.aja_itsetuntemus([LISTALTA], self.ulos, feikkitehdas(rungot=rungot), kulutila=str(self.kulut),
                        loki=lambda s: None)
        self.assertEqual(yv["pysahtyi"], "paivakatto")
        self.assertEqual(rungot, [])

    def test_virheet_vain_tyyppi(self):
        yv = mv.aja_itsetuntemus([LISTALTA], self.ulos, feikkitehdas(virhe=TimeoutError("salainen-osoite")),
                    kulutila=str(self.kulut), loki=lambda s: None)
        self.assertEqual(yv["virheita"], 2)                    # kaksi perakkaista virhetta ohittaa mallin
        teksti = (self.ulos / "vastaukset.jsonl").read_text(encoding="utf-8")
        self.assertIn("TimeoutError", teksti)
        self.assertNotIn("salainen", teksti)


class KomentoriviTesti(Tilapainen):
    def aja_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(ok, "OLETUS_TILA", str(self.kulut)):
            rc = mv.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_arvio_ei_kutsu(self):
        with mock.patch.object(yksityinen_or, "lue_avain") as avain, \
                mock.patch.object(yksityinen_or, "tee_kuljetin") as kuljetin:
            rc, out, _ = self.aja_main(["itse-arvio", "--mallit", "%s,%s" % (LISTALTA, TOINEN)])
            rc2, out2, _ = self.aja_main(["itse-aja", "--ulos", str(self.ulos)])
        self.assertEqual(rc, 0)
        self.assertIn("varovainen ylaraja", out)
        self.assertIn(TOINEN, out)
        self.assertEqual(rc2, 2)
        self.assertIn("--vahvista", out2)
        avain.assert_not_called()
        kuljetin.assert_not_called()
        self.assertFalse(self.ulos.exists())
        self.assertEqual(self.kirjanpito(), [])

    def test_vahvistettu_ajo_ja_taulukko(self):
        rungot = []
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(yksityinen_or, "tee_kuljetin", lambda avain: feikkitehdas(rungot=rungot)()):
            rc, out, _ = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--vahvista"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.index("Kuluarvio") < out.index("kulut_usd"))   # arvio ennen ajoa
        self.assertEqual(len(rungot), len(it.lue_kysymykset()["kysymykset"]))
        self.assertEqual({r["model"] for r in rungot}, {LISTALTA})          # oletus = nykyinen malli
        rc, out, _ = self.aja_main(["itse-taulukko", "--ulos", str(self.ulos)])
        self.assertEqual(rc, 0)
        self.assertIn("| %s |" % LISTALTA, out)

    def test_huono_malli_virhe_ilman_viestia(self):
        with mock.patch.object(yksityinen_or, "lue_avain") as avain:
            rc, out, err = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--vahvista",
                                          "--mallit", "anthropic/claude-opus-4"])
        self.assertEqual(rc, 1)
        self.assertEqual(err.strip(), "virhe: VertailuVirhe")
        avain.assert_not_called()

    def test_tyhja_mallilista_ei_laajene_ehdokkaisiin(self):
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(mv, "aja", return_value={}) as aja:
            self.aja_main(["aja", "--ulos", str(self.ulos), "--mallit", ""])
        self.assertEqual(aja.call_args[0][0], [])
        rc, _, err = self.aja_main(["itse-arvio", "--mallit", ""])
        self.assertEqual((rc, err.strip()), (1, "virhe: VertailuVirhe"))

    def test_ulos_pakollinen_muille_kuin_arviolle(self):
        for komento in ("aja", "itse-aja", "itse-taulukko"):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                mv.main([komento])


class RakenneTesti(unittest.TestCase):
    """Ajopolku mallivertailussa ei rakenna runkoa itse eika kutsu verkkoa muuten kuin openrouter_kulut.kutsun kautta;
    itsetuntemus.py ei tuo OpenRouter-koodia lainkaan."""

    def test_itsetuntemus_ei_tuo_kutsukoodia(self):
        puu = ast.parse((AIVO / "itsetuntemus.py").read_text(encoding="utf-8"))
        for n in ast.walk(puu):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                nimet = [a.name for a in n.names] + [x for x in [getattr(n, "module", None)] if x]
                self.assertEqual(nimet, [x for x in nimet if x in ("__future__", "annotations", "json", "re",
                                                                    "pathlib", "Path", "typing", "Any")], nimet)
                self.assertEqual(getattr(n, "level", 0), 0, nimet)          # ei suhteellisia tuonteja aivo-paketista

    def test_aja_itsetuntemus_kutsuu_vain_openrouter_kulut_kautta(self):
        puu = ast.parse((AIVO / "mallivertailu.py").read_text(encoding="utf-8"))
        funktiot = {f.name: f for f in puu.body if isinstance(f, ast.FunctionDef)}

        def kutsut(nimi):
            return [n for n in ast.walk(funktiot[nimi]) if isinstance(n, ast.Call)]

        def on_or_kutsu(n):
            return (isinstance(n.func, ast.Attribute) and n.func.attr == "kutsu"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "openrouter_kulut")
        # ainoa itsetuntemusajon kutsukohta on _itse_kutsu: yksi openrouter_kulut.kutsu(..., laheta, ...) lipulla
        k_lista = kutsut("_itse_kutsu")
        self.assertFalse([n for n in k_lista if isinstance(n.func, ast.Name) and n.func.id == "laheta"])
        lahetyt = [n for n in k_lista if any(isinstance(a, ast.Name) and a.id == "laheta" for a in n.args)]
        self.assertEqual(len(lahetyt), 1)
        k = lahetyt[0]
        self.assertTrue(on_or_kutsu(k))
        lippu = [kw for kw in k.keywords if kw.arg == "yksityinen_chat"]
        self.assertTrue(len(lippu) == 1 and isinstance(lippu[0].value, ast.Constant) and lippu[0].value.value is True)
        # ajosilmukka ja yhdistelma eivat kutsu verkkoa itse, vaan _itse_kutsun kautta
        for nimi in ("aja_itsetuntemus", "_itse_yhdistelmarivi"):
            self.assertFalse([n for n in kutsut(nimi) if on_or_kutsu(n)], nimi)
            self.assertFalse([n for n in kutsut(nimi) if isinstance(n.func, ast.Name)
                              and n.func.id in ("laheta", "laheta_tehdas")], nimi)
        self.assertIn("_itse_kutsu", {n.func.id for n in kutsut("aja_itsetuntemus") if isinstance(n.func, ast.Name)})

    def test_koodi_on_ascii(self):
        for nimi in ("itsetuntemus.py", "test_itsetuntemus.py", "mallivertailu.py"):
            self.assertIsNone(re.search(r"[^\x00-\x7f]", (AIVO / nimi).read_text(encoding="utf-8")), nimi)


KOKOAJA = TOINEN
JASENET3 = [LISTALTA, TOINEN, "deepseek/deepseek-chat-v3.1"]
JASENET5 = JASENET3 + ["mistralai/mistral-small-2603", "meta-llama/llama-4-maverick"]


def yhdistelmatehdas(rungot, jasen="J\u00e4senen vastaus [[PAATOS 1]]", kokoaja="En tied\u00e4.", kulu=0.001,
                     virhe_malli=None, kokoaja_virhe=False):
    """Feikki: kokoajan kutsu tunnistetaan kehotteen roolirivista."""
    def tehdas():
        def laheta(runko):
            rungot.append(runko)
            on_kokoaja = "kokoaja" in runko["messages"][0]["content"]
            if (on_kokoaja and kokoaja_virhe) or (not on_kokoaja and runko["model"] == virhe_malli):
                raise TimeoutError("salainen-osoite")
            return {"choices": [{"message": {"content": kokoaja if on_kokoaja else jasen}}],
                    "usage": {"cost": kulu, "prompt_tokens": 1000, "completion_tokens": 50}, "provider": "Feikki"}
        return laheta
    return tehdas


def kokoajan_rungot(rungot):
    return [r for r in rungot if "kokoaja" in r["messages"][0]["content"]]


class YhdistelmaTesti(Tilapainen):
    def test_valinta_tarkistetaan(self):
        self.assertEqual(mv.itse_yhdistelma(JASENET3, 3, KOKOAJA), (3, KOKOAJA))
        self.assertEqual(mv.itse_yhdistelma(JASENET5, 5, LISTALTA), (5, LISTALTA))
        self.assertEqual(mv.itse_yhdistelma([LISTALTA], None, None), (None, None))
        for mallit, n, kok in ((JASENET3, 4, KOKOAJA), (JASENET3, 5, KOKOAJA), (JASENET5, 3, KOKOAJA),
                               (JASENET3, 3, None), (JASENET3, 3, "z-ai/glm-5.3"), (JASENET3, 3, KOKOAJA + ":free"),
                               ([LISTALTA], None, KOKOAJA)):
            with self.assertRaises(mv.VertailuVirhe):
                mv.itse_yhdistelma(mallit, n, kok)

    def test_tuotannon_rajat_ennallaan(self):
        from aivo import yhdistelma
        self.assertEqual(yhdistelma.MAX_MALLEJA, 3)
        self.assertEqual(yhdistelma.MAX_KUTSUT_VIESTI, 4)
        self.assertEqual(mv.ITSE_YHDISTELMAT, (3, 5))
        self.assertEqual(mv.ITSE_KULURAJA_USD, 3.0)

    def test_kuluarvio_n_plus_1_kutsua(self):
        n = len(it.lue_kysymykset()["kysymykset"])
        for jasenet in (JASENET3, JASENET5):
            a = mv.itse_kuluarvio(jasenet, kokoaja=KOKOAJA)
            self.assertEqual(a["kutsuja"], (len(jasenet) + 1) * n)
            self.assertEqual(a["kutsuja_per_kysymys"], len(jasenet) + 1)
            self.assertEqual(len(a["ylaraja_usd_per_malli"]), len(jasenet) + 1)
            self.assertIn("kokoaja " + KOKOAJA, a["ylaraja_usd_per_malli"])
            self.assertGreaterEqual(a["tokenit_sisaan_kokoaja"],
                                    a["tokenit_sisaan_per_malli"] + len(jasenet) * mv.ITSE_MAX_TOKENIA * n)
            self.assertAlmostEqual(a["ylaraja_usd"], sum(a["ylaraja_usd_per_malli"].values()), places=3)
            teksti = mv.itse_arvioteksti(a)
            self.assertIn("%d per kysymys" % (len(jasenet) + 1), teksti)
            self.assertIn("kokoaja " + KOKOAJA, teksti)
        self.assertEqual(mv.itse_kuluarvio(JASENET3)["kutsuja_per_kysymys"], 3)   # ilman kokoajaa: yksittain

    def test_ajo_kolme_mallia_ja_kokoaja(self):
        rungot = []
        yv = mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas(rungot), kokoaja=KOKOAJA,
                                 kulutila=str(self.kulut), loki=lambda s: None)
        kys = it.lue_kysymykset()["kysymykset"]
        n = len(kys)
        self.assertEqual(len(rungot), 4 * n)
        for r in rungot:
            self.assertEqual(r["provider"], {"zdr": True, "data_collection": "deny"})
            self.assertTrue(yksityinen_or._zdr_kunnossa(r))
        kok = kokoajan_rungot(rungot)
        self.assertEqual(len(kok), n)
        self.assertEqual({r["model"] for r in kok}, {KOKOAJA})
        self.assertEqual([r["model"] for r in rungot[:4]], JASENET3 + [KOKOAJA])   # jasenet ensin, sitten kokoaja
        for r in kok:
            viimeinen = r["messages"][-1]["content"]
            self.assertIn("VASTAUS 3:", viimeinen)
            self.assertNotIn("VASTAUS 4:", viimeinen)
            self.assertNotIn("[[", viimeinen)                  # jasenten merkinnat neutraloitu
            for m in JASENET3:
                self.assertNotIn(m, viimeinen)                 # mallien nimet eivat nay kokoajalle
        rivit = it.lue_vastaukset(self.ulos)
        self.assertEqual(len(rivit), n)
        nimi = mv.itse_yhdistelman_nimi(JASENET3, KOKOAJA)
        self.assertEqual({r["malli"] for r in rivit}, {nimi})
        self.assertTrue(all(len(r["osat"]) == 3 and r["vastaus"] == "En tied\u00e4." for r in rivit))
        self.assertTrue(all(abs(r["kulu_usd"] - 0.004) < 1e-9 for r in rivit))
        self.assertEqual(yv["kulut_usd"], round(0.004 * n, 4))
        self.assertEqual((yv["yhdistelma"], yv["kokoaja"], yv["kutsuja_per_kysymys"]), (3, KOKOAJA, 4))
        self.assertTrue((self.ulos / "ajo-yhdistelma-3.json").exists())
        self.assertFalse((self.ulos / "ajo.json").exists())
        kirjaukset = [r for r in self.kirjanpito() if r.get("tehtava") == mv.ITSE_TEHTAVA and not r.get("varaus")]
        self.assertEqual(len(kirjaukset), 4 * n)
        # pisteytys lopullisesta vastauksesta: kokoajan "En tieda" -> en_tieda-kysymykset oikein
        tulos = it.pisteet(rivit)[nimi]
        self.assertEqual(tulos["luokat"]["en_tieda_oikein"], sum(1 for k in kys if k["laji"] == "en_tieda"))

    def test_viisi_mallia(self):
        rungot = []
        mv.aja_itsetuntemus(JASENET5, self.ulos, yhdistelmatehdas(rungot), kokoaja=LISTALTA,
                            kulutila=str(self.kulut), loki=lambda s: None)
        n = len(it.lue_kysymykset()["kysymykset"])
        self.assertEqual(len(rungot), 6 * n)
        self.assertTrue(all("VASTAUS 5:" in r["messages"][-1]["content"] for r in kokoajan_rungot(rungot)))

    def test_kuluraja_varaa_koko_kysymyksen(self):
        rungot = []
        yv = mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas(rungot, kulu=0.2), kokoaja=KOKOAJA, raja=1.0,
                                 kulutila=str(self.kulut), loki=lambda s: None)
        self.assertEqual(yv["pysahtyi"], "kuluraja")
        self.assertEqual(len(rungot), 4)                       # 0.8 + 2 * 0.8 > 1.0: toista kysymysta ei aloiteta
        self.assertLessEqual(yv["kulut_usd"], 1.0)
        rungot2 = []
        yv2 = mv.aja_itsetuntemus(JASENET5, self.d / "u2", yhdistelmatehdas(rungot2, kulu=0.001), kokoaja=KOKOAJA,
                                  raja=0.29, kulutila=str(self.kulut), loki=lambda s: None)
        self.assertEqual((yv2["pysahtyi"], rungot2), ("kuluraja", []))   # varaus 6 * 0.05 > 0.29

    def test_jasenen_virhe_kokoaja_saa_loput(self):
        rungot = []
        yv = mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas(rungot, virhe_malli=TOINEN), kokoaja=LISTALTA,
                                 kulutila=str(self.kulut), loki=lambda s: None)
        self.assertEqual(yv["pysahtyi"], "virheita")           # MAX_VIRHEITA epaonnistunutta kutsua
        self.assertEqual(yv["virheita"], mv.MAX_VIRHEITA)
        rivit = it.lue_vastaukset(self.ulos)
        self.assertTrue(all(r["vastauksia"] == 2 and "virhe" not in r for r in rivit))
        self.assertTrue(all("VASTAUS 2:" in r["messages"][-1]["content"] and "VASTAUS 3:" not in r["messages"][-1]["content"]
                            for r in kokoajan_rungot(rungot)))
        teksti = (self.ulos / "vastaukset.jsonl").read_text(encoding="utf-8")
        self.assertIn("TimeoutError", teksti)
        self.assertNotIn("salainen", teksti)

    def test_kokoajan_virhe_on_vaarin(self):
        rungot = []
        yv = mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas(rungot, kokoaja_virhe=True), kokoaja=KOKOAJA,
                                 kulutila=str(self.kulut), loki=lambda s: None)
        rivit = it.lue_vastaukset(self.ulos)
        self.assertEqual(len(rivit), 2)                        # kaksi perakkaista epaonnistunutta kysymysta
        self.assertTrue(all(r["virhe"] == "TimeoutError" and "vastaus" not in r for r in rivit))
        self.assertEqual(yv["virheita"], 2)
        tulos = it.pisteet(rivit)[mv.itse_yhdistelman_nimi(JASENET3, KOKOAJA)]
        self.assertEqual(tulos["luokat"]["vaarin"], 2)

    def test_paivakatto_kesken_kysymyksen(self):
        tehdyt = []

        def feikki(malli, viestit, laheta_tehdas, kulutila, kello):
            if len(tehdyt) == 2:
                raise ok.KutsuEstetty("katto")
            tehdyt.append(malli)
            return {"vastaus": "x", "kulu_usd": 0.01, "sekuntia": 1.0, "tokenit_sisaan": 1, "tokenit_ulos": 1,
                    "tarjoaja": None}
        with mock.patch.object(mv, "_itse_kutsu", feikki):
            yv = mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas([]), kokoaja=KOKOAJA, loki=lambda s: None)
        self.assertEqual(yv["pysahtyi"], "paivakatto")
        self.assertEqual(yv["kulut_usd"], 0.02)                # keskeytyneen kysymyksen kulu mukana
        self.assertEqual(it.lue_vastaukset(self.ulos), [])

    def test_mediaaniaika_rinnakkaisena(self):
        ajat = iter([0, 2, 10, 15, 20, 21, 30, 34])        # jasenet 2, 5, 1 s, kokoaja 4 s

        with mock.patch.object(it, "lue_kysymykset", return_value={"kysymykset": it.lue_kysymykset()["kysymykset"][:1]}):
            mv.aja_itsetuntemus(JASENET3, self.ulos, yhdistelmatehdas([]), kokoaja=KOKOAJA, kello=lambda: next(ajat),
                                kulutila=str(self.kulut), loki=lambda s: None)
        r = it.lue_vastaukset(self.ulos)[0]
        self.assertEqual((r["sekuntia"], r["sekuntia_perakkain"]), (9.0, 12.0))

    def test_taulukossa_mediaaniaika(self):
        k = it.lue_kysymykset()["kysymykset"]
        rivit = [{"malli": "a", "kysymys": k[i]["id"], "vastaus": "", "sekuntia": s} for i, s in enumerate((1, 3, 10))]
        rivit += [{"malli": "b", "kysymys": k[0]["id"], "vastaus": "", "sekuntia": s} for s in (2, 4)]
        rivit += [{"malli": "c", "kysymys": k[0]["id"], "virhe": "X"}]
        tulos = it.pisteet(rivit)
        self.assertEqual((tulos["a"]["mediaani_s"], tulos["b"]["mediaani_s"], tulos["c"]["mediaani_s"]), (3.0, 3.0, None))
        teksti = it.taulukko(tulos)
        self.assertIn("Mediaaniaika s", teksti)
        self.assertIn("| 3.0 |", teksti)
        self.assertRegex(teksti, r"(?m)^\| c \|.*\| - \|$")


class YhdistelmaKomentoriviTesti(KomentoriviTesti):
    def test_arvio_ja_ilman_vahvistusta_ei_kutsuja(self):
        jasenet = ",".join(JASENET3)
        with mock.patch.object(yksityinen_or, "lue_avain") as avain, \
                mock.patch.object(yksityinen_or, "tee_kuljetin") as kuljetin:
            rc, out, _ = self.aja_main(["itse-arvio", "--mallit", jasenet, "--yhdistelma", "3", "--kokoaja", KOKOAJA])
            rc2, out2, _ = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--mallit", jasenet,
                                          "--yhdistelma", "3", "--kokoaja", KOKOAJA])
        self.assertEqual((rc, rc2), (0, 2))
        self.assertIn("4 per kysymys", out)
        self.assertIn("kokoaja " + KOKOAJA, out)
        self.assertIn("--vahvista", out2)
        avain.assert_not_called()
        kuljetin.assert_not_called()
        self.assertFalse(self.ulos.exists())

    def test_virheelliset_valinnat(self):
        jasenet = ",".join(JASENET3)
        for argv in (["--mallit", jasenet, "--kokoaja", KOKOAJA],
                     ["--mallit", jasenet, "--yhdistelma", "4", "--kokoaja", KOKOAJA],
                     ["--mallit", jasenet, "--yhdistelma", "5", "--kokoaja", KOKOAJA],
                     ["--mallit", jasenet, "--yhdistelma", "3"],
                     ["--mallit", jasenet, "--yhdistelma", "3", "--kokoaja", "anthropic/claude-opus-4"]):
            with mock.patch.object(yksityinen_or, "lue_avain") as avain:
                rc, _, err = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--vahvista"] + argv)
            self.assertEqual((rc, err.strip()), (1, "virhe: VertailuVirhe"), argv)
            avain.assert_not_called()

    def test_vahvistettu_yhdistelma_ja_taulukko(self):
        rungot = []
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(yksityinen_or, "tee_kuljetin", lambda avain: yhdistelmatehdas(rungot)()):
            rc, out, _ = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--vahvista"])
            rc2, out2, _ = self.aja_main(["itse-aja", "--ulos", str(self.ulos), "--mallit", ",".join(JASENET3),
                                          "--yhdistelma", "3", "--kokoaja", KOKOAJA, "--vahvista"])
        n = len(it.lue_kysymykset()["kysymykset"])
        self.assertEqual((rc, rc2), (0, 0))
        self.assertTrue(out2.index("Kuluarvio") < out2.index("kulut_usd"))
        self.assertEqual(len(rungot), n + 4 * n)
        rc, out, _ = self.aja_main(["itse-taulukko", "--ulos", str(self.ulos)])
        self.assertEqual(rc, 0)
        self.assertIn("| %s |" % LISTALTA, out)
        self.assertIn("| %s |" % mv.itse_yhdistelman_nimi(JASENET3, KOKOAJA), out)


if __name__ == "__main__":
    unittest.main()
