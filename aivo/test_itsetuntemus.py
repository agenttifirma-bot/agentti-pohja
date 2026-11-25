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
        self.assertEqual(it.luokittele(r03, ""), "vaarin")

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

    def test_pisteet_ja_taulukko(self):
        sarja = it.lue_kysymykset()
        rivit = [{"malli": "a/b", "kysymys": "R03", "vastaus": "Toimin Claude-mallilla.", "kulu_usd": 0.01},
                 {"malli": "a/b", "kysymys": "U01", "vastaus": "En tied\u00e4.", "kulu_usd": 0.01},
                 {"malli": "a/b", "kysymys": "R04", "virhe": "TimeoutError"},
                 {"malli": "a/b", "kysymys": "R05", "vastaus": "En tied\u00e4."},
                 {"malli": "a/b", "kysymys": "XX", "vastaus": "ohitetaan"}]
        t = it.pisteet(rivit, sarja)["a/b"]
        self.assertEqual(t["luokat"], {"oikein": 0, "vaarin": 1, "en_tieda_oikein": 1, "arvaus_faktana": 1,
                                       "en_tieda": 1})
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
        self.assertEqual(a["tokenit_ulos_enintaan_per_malli"], n * mv.ITSE_MAX_TOKENIA)
        merkit = sum(sum(len(v["content"]) for v in mv.itse_viestit(k)) for k in it.lue_kysymykset()["kysymykset"])
        self.assertGreaterEqual(a["tokenit_sisaan_per_malli"], merkit // 4)   # vahintaan 4 merkkia/token -arvio
        for usd in a["ylaraja_usd_per_malli"].values():
            self.assertEqual(usd, float(ok.arvioi_usd(LISTALTA, a["tokenit_sisaan_per_malli"],
                                                      a["tokenit_ulos_enintaan_per_malli"])))
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
        f = funktiot["aja_itsetuntemus"]
        kutsut = [n for n in ast.walk(f) if isinstance(n, ast.Call)]
        self.assertFalse([n for n in kutsut if isinstance(n.func, ast.Name) and n.func.id == "laheta"])
        lahetyt = [n for n in kutsut if any(isinstance(a, ast.Name) and a.id == "laheta" for a in n.args)]
        self.assertEqual(len(lahetyt), 1)
        k = lahetyt[0]
        self.assertTrue(isinstance(k.func, ast.Attribute) and k.func.attr == "kutsu"
                        and isinstance(k.func.value, ast.Name) and k.func.value.id == "openrouter_kulut")
        lippu = [kw for kw in k.keywords if kw.arg == "yksityinen_chat"]
        self.assertTrue(len(lippu) == 1 and isinstance(lippu[0].value, ast.Constant) and lippu[0].value.value is True)

    def test_koodi_on_ascii(self):
        for nimi in ("itsetuntemus.py", "test_itsetuntemus.py", "mallivertailu.py"):
            self.assertIsNone(re.search(r"[^\x00-\x7f]", (AIVO / nimi).read_text(encoding="utf-8")), nimi)


if __name__ == "__main__":
    unittest.main()
