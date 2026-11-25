"""Testit itsetuntemuksen viikkoajolle (mallivertailu.itse_viikko, komento itse-viikko) ja sen systemd-malleille.
Ei verkkoa eika oikeita avaimia: kuljetin on feikki ja kulukirjanpito tilapainen."""
import ast
import datetime as dt
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from aivo import itsetuntemus as it, mallivertailu as mv, openrouter_kulut as ok, yksityinen, yksityinen_or

AIVO = Path(it.__file__).resolve().parent
JUURI = AIVO.parent
PAA = mv.NYKYINEN
TARK = "qwen/qwen3.5-397b-a17b"
N = len(it.lue_kysymykset()["kysymykset"])
SALAINEN = "Vastausteksti-jota-ei-saa-nakya"


def tehdas(teksti=SALAINEN, kulu=0.001, rungot=None, kaytto=None):
    def t():
        def laheta(runko):
            if rungot is not None:
                rungot.append(runko)
            u = {"cost": kulu, "prompt_tokens": 1000, "completion_tokens": 50} if kaytto is None else kaytto
            return {"choices": [{"message": {"content": teksti}}], "usage": u, "provider": "Feikki"}
        return laheta
    return t


def aika(paiva):
    return dt.datetime(2026, 11, paiva, 1, 30, tzinfo=dt.timezone.utc)


class Pohja(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.ulos = self.d / "vastaukset"
        self.tiiv = self.d / "tiivistelma"

    def tearDown(self):
        self._d.cleanup()

    def aja(self, env, paiva=29, **kw):
        kw.setdefault("loki", lambda s: None)
        tehdas_ = kw.pop("tehdas", None) or tehdas()
        return mv.itse_viikko(env, self.ulos, self.tiiv, tehdas_, nyt=aika(paiva), kulutila=str(self.kulut), **kw)


class TuotannonMallitTesti(unittest.TestCase):
    def test_vain_mallilista_tarkastaja_on_paamalli(self):
        self.assertEqual(mv.itse_tuotannon_mallit({"AIVO_OPENROUTER_MALLIT": "%s,%s" % (PAA, TARK)}),
                         {"paamalli": PAA, "tarkastaja": PAA})
        self.assertEqual(mv.itse_tuotannon_mallit({"AIVO_OPENROUTER_MALLI": PAA}), {"paamalli": PAA, "tarkastaja": PAA})

    def test_tarkastaja_roolista(self):
        env = {"AIVO_OPENROUTER_MALLIT": "%s,%s" % (PAA, TARK), "AIVO_YKSITYINEN_ROOLIT": "vastaaja:%s,tarkastaja:%s" % (PAA, TARK)}
        self.assertEqual(mv.itse_tuotannon_mallit(env), {"paamalli": PAA, "tarkastaja": TARK})

    def test_virheelliset_asetukset_hylataan(self):
        for env in ({}, {"AIVO_OPENROUTER_MALLIT": "anthropic/claude-opus-4"},
                    {"AIVO_OPENROUTER_MALLIT": PAA, "AIVO_YKSITYINEN_ROOLIT": "tarkastaja:%s" % TARK},
                    {"AIVO_OPENROUTER_MALLIT": PAA, "AIVO_YKSITYINEN_ROOLIT": "tuntematon:%s" % PAA}):
            with self.assertRaises(yksityinen.YksityinenVirhe, msg=env):
                mv.itse_tuotannon_mallit(env)


class ViikkoajoTesti(Pohja):
    def test_ajo_tuottaa_tiivistelman_ilman_vastauksia(self):
        rungot = []
        rivi = self.aja({"AIVO_OPENROUTER_MALLIT": PAA}, tehdas=tehdas(rungot=rungot))
        self.assertEqual(len(rungot), N)                                  # sama malli ajetaan kerran
        self.assertEqual({r["model"] for r in rungot}, {PAA})
        self.assertFalse(rivi["kesken"])
        self.assertEqual(rivi["raja_usd"], mv.ITSE_VIIKKO_RAJA_USD)
        self.assertEqual(rivi["mallit"][PAA]["vastattu"], N)
        self.assertTrue((self.ulos / "2026-11-29T013000Z" / "vastaukset.jsonl").exists())
        for nimi in (mv.ITSE_VIIKKO_TIIVISTELMA, mv.ITSE_VIIKKO_JSON, mv.ITSE_VIIKKO_HISTORIA):
            teksti = (self.tiiv / nimi).read_text(encoding="utf-8")
            self.assertNotIn(SALAINEN, teksti, nimi)                      # tiivistelmassa vain luvut
        md = (self.tiiv / mv.ITSE_VIIKKO_TIIVISTELMA).read_text(encoding="utf-8")
        self.assertIn("(uusi)", md)
        self.assertIn("| %s |" % PAA, md)
        for laji in it.LAJIT:
            self.assertIn(laji, md)
        self.assertEqual(oct(self.tiiv.stat().st_mode & 0o777), "0o700")
        kirjaukset = [r for r in (json.loads(x) for x in (self.kulut / ok.KULUT).read_text().splitlines())
                      if r.get("tehtava") == mv.ITSE_TEHTAVA and not r.get("varaus")]
        self.assertEqual(len(kirjaukset), N)                               # yhteinen kulukirjanpito

    def test_muutos_edelliseen_viikkoon(self):
        env = {"AIVO_OPENROUTER_MALLIT": PAA}
        self.aja(env, paiva=22, tehdas=tehdas(teksti="En tied\u00e4."))
        rivi = self.aja(env, paiva=29, tehdas=tehdas(teksti="Kyll\u00e4 varmasti."))
        historia = mv._lue_historia(self.tiiv / mv.ITSE_VIIKKO_HISTORIA)
        self.assertEqual([h["aika"][:10] for h in historia], ["2026-11-22", "2026-11-29"])
        ennen = historia[0]["mallit"][PAA]["yhteensa"]
        self.assertNotEqual(ennen, rivi["mallit"][PAA]["yhteensa"])
        md = (self.tiiv / mv.ITSE_VIIKKO_TIIVISTELMA).read_text(encoding="utf-8")
        self.assertIn("(%+.2f)" % (rivi["mallit"][PAA]["yhteensa"] - ennen), md)
        self.assertNotIn("(uusi)", md.split("| %s |" % PAA)[1].split("\n")[0])

    def test_paamalli_ja_tarkastaja_samassa_rajassa(self):
        rungot = []
        env = {"AIVO_OPENROUTER_MALLIT": "%s,%s" % (PAA, TARK), "AIVO_YKSITYINEN_ROOLIT": "tarkastaja:%s" % TARK}
        rivi = self.aja(env, tehdas=tehdas(rungot=rungot))
        self.assertEqual(len(rungot), 2 * N)
        self.assertEqual(set(rivi["mallit"]), {PAA, TARK})
        self.assertEqual(rivi["roolit"], {"paamalli": PAA, "tarkastaja": TARK})

    def test_raja_enintaan_yksi_dollari(self):
        rungot = []
        for raja in (1.01, 3.0, 0, -1, True):
            with self.assertRaises(mv.VertailuVirhe):
                self.aja({"AIVO_OPENROUTER_MALLIT": PAA}, raja=raja, tehdas=tehdas(rungot=rungot))
        self.assertEqual(rungot, [])
        self.assertFalse(self.ulos.exists())

    def test_kuluraja_pysayttaa_ja_kesken_ei_ole_vertailukohta(self):
        env = {"AIVO_OPENROUTER_MALLIT": PAA}
        self.aja(env, paiva=15, tehdas=tehdas(teksti="En tied\u00e4."))
        rungot = []
        rivi = self.aja(env, paiva=22, tehdas=tehdas(kulu=0.3, rungot=rungot))
        self.assertEqual(rivi["pysahtyi"], "kuluraja")
        self.assertTrue(rivi["kesken"])
        self.assertLessEqual(rivi["kulut_usd"], 1.0)
        self.assertLess(len(rungot), N)
        self.assertIn("HUOM: ajo jai kesken", (self.tiiv / mv.ITSE_VIIKKO_TIIVISTELMA).read_text(encoding="utf-8"))
        historia = mv._lue_historia(self.tiiv / mv.ITSE_VIIKKO_HISTORIA)
        self.assertEqual(mv._edellinen(historia, PAA), historia[0]["mallit"][PAA])   # kesken-ajo ohitetaan

    def test_puuttuva_kulu_lasketaan_arviona(self):
        rungot = []
        rivi = self.aja({"AIVO_OPENROUTER_MALLIT": PAA},
                        tehdas=tehdas(rungot=rungot, kaytto={"prompt_tokens": 1500, "completion_tokens": 800}))
        arvio = float(ok.arvioi_usd(PAA, 1500, 800))
        self.assertGreater(arvio, 0)
        # kulu puuttuu: ajo laskee varovaisen arvion (tuntematon hinta = korkea) ja pysahtyy ennen 1 USD:a
        self.assertEqual(rivi["pysahtyi"], "kuluraja")
        self.assertAlmostEqual(rivi["kulut_usd"], round(arvio * len(rungot), 4), places=4)
        self.assertLessEqual(rivi["kulut_usd"], 1.0)
        self.assertTrue(rivi["kesken"])

    def test_yksittainen_virhe_tekee_ajosta_kesken(self):
        laskuri = []

        def t():
            perus = tehdas()()

            def laheta(runko):
                laskuri.append(1)
                if len(laskuri) == 3:
                    raise TimeoutError("x")
                return perus(runko)
            return laheta
        env = {"AIVO_OPENROUTER_MALLIT": PAA}
        self.aja(env, paiva=15)
        rivi = self.aja(env, paiva=22, tehdas=t)
        self.assertIsNone(rivi["pysahtyi"])
        self.assertEqual(rivi["virheita"], 1)
        self.assertEqual(rivi["mallit"][PAA]["vastattu"], N - 1)
        self.assertTrue(rivi["kesken"])
        historia = mv._lue_historia(self.tiiv / mv.ITSE_VIIKKO_HISTORIA)
        self.assertEqual(mv._edellinen(historia, PAA), historia[0]["mallit"][PAA])

    def test_nan_kulu_ei_ohita_rajaa(self):
        rungot = []
        rivi = self.aja({"AIVO_OPENROUTER_MALLIT": PAA}, tehdas=tehdas(
            rungot=rungot, kaytto={"cost": float("nan"), "prompt_tokens": 1500, "completion_tokens": 800}))
        self.assertEqual(rivi["pysahtyi"], "kuluraja")
        self.assertLessEqual(rivi["kulut_usd"], 1.0)
        self.assertLess(len(rungot), N)

    def test_sama_aika_kahdesti_hylataan(self):
        env = {"AIVO_OPENROUTER_MALLIT": PAA}
        self.aja(env)
        rungot = []
        with self.assertRaises(mv.VertailuVirhe):
            self.aja(env, tehdas=tehdas(rungot=rungot))
        self.assertEqual(rungot, [])

    def test_rikkinainen_historia_ei_kaada(self):
        self.tiiv.mkdir(mode=0o700)
        (self.tiiv / mv.ITSE_VIIKKO_HISTORIA).write_text("ei json\n[1]\n", encoding="utf-8")
        self.aja({"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual(len(mv._lue_historia(self.tiiv / mv.ITSE_VIIKKO_HISTORIA)), 1)

    def test_historia_rajattu(self):
        self.tiiv.mkdir(mode=0o700)
        vanha = json.dumps({"aika": "x", "kesken": False, "mallit": {}})
        (self.tiiv / mv.ITSE_VIIKKO_HISTORIA).write_text((vanha + "\n") * (mv.ITSE_VIIKKO_HISTORIA_MAX + 5))
        self.aja({"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual(len(mv._lue_historia(self.tiiv / mv.ITSE_VIIKKO_HISTORIA)), mv.ITSE_VIIKKO_HISTORIA_MAX)


class ViikkoKomentoriviTesti(Pohja):
    def main(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(ok, "OLETUS_TILA", str(self.kulut)):
            rc = mv.main(argv, env=env)
        return rc, out.getvalue(), err.getvalue()

    def argv(self, *lisa):
        return ["itse-viikko", "--ulos", str(self.ulos), "--tiivistelma", str(self.tiiv), *lisa]

    def test_ajo_komentorivilta(self):
        rungot = []
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(yksityinen_or, "tee_kuljetin", lambda avain: tehdas(rungot=rungot)()):
            rc, out, err = self.main(self.argv(), {"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(len(rungot), N)
        self.assertNotIn(SALAINEN, out)
        self.assertIn('"kesken": false', out)

    def test_suuri_raja_ja_mallivalitsin_hylataan_ennen_kutsuja(self):
        with mock.patch.object(yksityinen_or, "tee_kuljetin") as kuljetin, \
                mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20):
            rc, _, err = self.main(self.argv("--raja", "3"), {"AIVO_OPENROUTER_MALLIT": PAA})
            self.assertEqual((rc, err.strip()), (1, "virhe: VertailuVirhe"))
            rc, _, err = self.main(self.argv(), {"AIVO_OPENROUTER_MALLIT": "anthropic/claude-opus-4"})
            self.assertEqual((rc, err.strip()), (1, "virhe: YksityinenVirhe"))
            for lisa in (["--mallit", PAA], ["--toistot", "2"]):
                with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                    mv.main(self.argv(*lisa), env={"AIVO_OPENROUTER_MALLIT": PAA})
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                mv.main(["itse-viikko", "--ulos", str(self.ulos)], env={"AIVO_OPENROUTER_MALLIT": PAA})
        kuljetin.assert_not_called()
        self.assertFalse(self.ulos.exists())

    def test_kesken_paluuarvo_1(self):
        with mock.patch.object(yksityinen_or, "lue_avain", return_value="x" * 20), \
                mock.patch.object(yksityinen_or, "tee_kuljetin", lambda avain: tehdas(kulu=0.4)()):
            rc, _, _ = self.main(self.argv(), {"AIVO_OPENROUTER_MALLIT": PAA})
        self.assertEqual(rc, 1)


class RakenneJaYksikkoTesti(unittest.TestCase):
    def test_itse_viikko_ei_kutsu_verkkoa_itse(self):
        puu = ast.parse((AIVO / "mallivertailu.py").read_text(encoding="utf-8"))
        f = {x.name: x for x in puu.body if isinstance(x, ast.FunctionDef)}["itse_viikko"]
        kutsut = [n for n in ast.walk(f) if isinstance(n, ast.Call)]
        self.assertFalse([n for n in kutsut if isinstance(n.func, ast.Attribute) and n.func.attr == "kutsu"])
        self.assertIn("aja_itsetuntemus", {n.func.id for n in kutsut if isinstance(n.func, ast.Name)})

    def test_raja_vakio_ei_ylita_ajon_rajaa(self):
        self.assertLessEqual(mv.ITSE_VIIKKO_RAJA_USD, 1.0)
        self.assertLessEqual(mv.ITSE_VIIKKO_RAJA_USD, mv.ITSE_KULURAJA_USD)
        self.assertEqual(ok.PAIVAKATTO_EUR, 10)

    def yksikko(self, nimi):
        return (JUURI / "systemd" / nimi).read_text(encoding="utf-8")

    def test_palvelumalli(self):
        s = self.yksikko("aivo-itsetuntemus.service.mall")
        self.assertIn("\nUser=aivo\n", s)
        self.assertIn("\nType=oneshot\n", s)
        exec_ = [r for r in s.splitlines() if r.startswith("ExecStart=")]
        self.assertEqual(len(exec_), 1)
        osat = exec_[0].split()
        self.assertIn("itse-viikko", osat)
        self.assertLessEqual(float(osat[osat.index("--raja") + 1]), mv.ITSE_VIIKKO_RAJA_USD)
        rw = [r for r in s.splitlines() if r.startswith("ReadWritePaths=")]
        self.assertEqual(len(rw), 1)
        polut = rw[0].split("=", 1)[1].split()
        self.assertIn(ok.OLETUS_TILA, polut)                           # kulukirjanpito on kirjoitettava
        for valitsin in ("--ulos", "--tiivistelma"):
            p = osat[osat.index(valitsin) + 1]
            self.assertTrue(any(p == q or p.startswith(q + "/") for q in polut), p)
        self.assertNotIn("TemporaryFileSystem", s)                    # 25.11.2026: tmpfs esti kirjanpidon
        self.assertNotRegex(s, r"(?m)^Environment=.*AIVO_OPENROUTER_AVAIN")
        env = dict(x.split("=", 1) for r in s.splitlines() if r.startswith("Environment=")
                   for x in r.split("=", 1)[1].split())
        self.assertEqual(mv.itse_tuotannon_mallit(env)["paamalli"], PAA)  # malliarvo kelpaa

    def test_ajastinmalli_sunnuntaiyona(self):
        s = self.yksikko("aivo-itsetuntemus.timer.mall")
        m = re.search(r"(?m)^OnCalendar=Sun \*-\*-\* (\d\d):\d\d:\d\d Europe/Helsinki$", s)
        self.assertIsNotNone(m)
        self.assertLess(int(m.group(1)), 6)
        self.assertIn("\nPersistent=true\n", s)
        self.assertIn("\nUnit=aivo-itsetuntemus.service\n", s)

    def test_koodi_on_ascii(self):
        for nimi in ("test_itsetuntemus_viikko.py",):
            self.assertIsNone(re.search(r"[^\x00-\x7f]", (AIVO / nimi).read_text(encoding="utf-8")), nimi)
        for nimi in ("aivo-itsetuntemus.service.mall", "aivo-itsetuntemus.timer.mall"):
            self.assertIsNone(re.search(r"[^\x00-\x7f]", self.yksikko(nimi)), nimi)


if __name__ == "__main__":
    unittest.main()
