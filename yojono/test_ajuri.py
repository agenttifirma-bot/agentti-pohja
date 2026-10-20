import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yojono import ajuri

PVM = "2026-10-19"


def jono(tehtavat, katto=3.0):
    return {"paivakatto": katto, "tehtavat": tehtavat}


def t(id_, repo="r", budjetti=1.0):
    return {"id": id_, "tyyppi": "katselmointi", "repo": repo, "budjetti": budjetti}


class Pohja(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.perus = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def kirjoita_jono(self, data):
        (self.perus / "jono.json").write_text(json.dumps(data))

    def tila(self):
        return json.loads((self.perus / "tila.json").read_text())

    def aja(self, suorita, **kw):
        viestit = []
        teksti = ajuri.aja(self.perus, "/ei/kaytossa", laheta=viestit.append, suorita=suorita, pvm=PVM,
                           telegram=kw.pop("telegram", lambda x: None), **kw)
        return teksti, viestit


class TestTarkistus(unittest.TestCase):
    def test_hyvaksyy_kelvollisen(self):
        katto, tehtavat = ajuri.tarkista_jono(jono([t("a-1")]))
        self.assertEqual(katto, 3.0)
        self.assertEqual(len(tehtavat), 1)

    def test_hylkaa_virheelliset(self):
        huonot = [
            [],  # ei objekti
            {"tehtavat": "x"},
            jono([t("A")]),  # iso kirjain id:ssa
            jono([t("a", repo="../x")]),
            jono([t("a", repo="a b")]),
            jono([t("a", repo="..")]),
            jono([t("a", budjetti=0)]),
            jono([t("a", budjetti=-1)]),
            jono([t("a", budjetti=3.5)]),  # yli paivakaton
            jono([t("a", budjetti=True)]),
            jono([t("a"), t("a")]),  # sama id kahdesti
            jono([dict(t("a"), tyyppi="shell")]),
            jono([t("a")], katto=0),
            jono([t("a")], katto=999),
            jono([t("a")], katto=True),
        ]
        for huono in huonot:
            with self.subTest(huono=huono):
                with self.assertRaises(ajuri.JonoVirhe):
                    ajuri.tarkista_jono(huono)


class TestValinta(unittest.TestCase):
    def test_ohittaa_valmiit_ja_rajaa_uudelleenyritykset(self):
        tehtavat = [t("uusi"), t("valmis"), t("kaatui-tanaan"), t("kaatui-eilen"), t("kaatui-kahdesti")]
        tila = {"tehtavat": {
            "valmis": {"tila": "valmis"},
            "kaatui-tanaan": {"tila": "epaonnistui", "yrityksia": 1, "pvm": PVM},
            "kaatui-eilen": {"tila": "epaonnistui", "yrityksia": 1, "pvm": "2026-10-18"},
            "kaatui-kahdesti": {"tila": "epaonnistui", "yrityksia": 2, "pvm": "2026-10-17"},
        }}
        ids = [x["id"] for x in ajuri.valitse_ajettavat(tehtavat, tila, PVM)]
        self.assertEqual(ids, ["uusi", "kaatui-eilen"])


class TestAjo(Pohja):
    def test_ajaa_tehtavat_ja_kirjaa_kulut(self):
        self.kirjoita_jono(jono([t("a", budjetti=1.5), t("b", budjetti=1.0)]))
        kutsut = []

        def suorita(tehtava, pvm, perus, skripti):
            kutsut.append(tehtava["id"])
            return ajuri.Tulos(True, 0.6, f"/r/{tehtava['id']}.md", "ok")

        teksti, viestit = self.aja(suorita)
        self.assertEqual(kutsut, ["a", "b"])
        tila = self.tila()
        self.assertAlmostEqual(tila["kulut"][PVM], 1.2)
        self.assertEqual(tila["tehtavat"]["a"]["tila"], "valmis")
        self.assertIn("kulu tanaan 1.20 / 3.00 USD", teksti)
        self.assertEqual(viestit, [teksti])

    def test_paivakatto_ohittaa_liian_ison_tehtavan_mutta_ajaa_pienemman(self):
        self.kirjoita_jono(jono([t("iso", budjetti=2.0), t("pieni", budjetti=0.5)]))
        (self.perus / "tila.json").write_text(json.dumps({"kulut": {PVM: 1.8}, "tehtavat": {}}))
        kutsut = []

        def suorita(tehtava, *a):
            kutsut.append(tehtava["id"])
            return ajuri.Tulos(True, 0.4, "x.md", "ok")

        teksti, _ = self.aja(suorita)
        self.assertEqual(kutsut, ["pieni"])
        self.assertIn("iso: ohitettu (paivakatto", teksti)

    def test_kulu_ei_ylita_kattoa_useassa_tehtavassa(self):
        self.kirjoita_jono(jono([t(f"t{i}", budjetti=1.0) for i in range(6)], katto=3.0))
        kutsut = []

        def suorita(tehtava, *a):
            kutsut.append(tehtava["id"])
            return ajuri.Tulos(True, 1.0, "x.md", "ok")

        self.aja(suorita)
        self.assertEqual(len(kutsut), 3)  # kolme tehtavaa a 1,00 USD tayttaa 3,00 USD:n katon
        self.assertLessEqual(self.tila()["kulut"][PVM], 3.0)

    def test_epaonnistunut_kirjataan_ja_kulu_lasketaan(self):
        self.kirjoita_jono(jono([t("a", budjetti=1.5)]))
        teksti, _ = self.aja(lambda *a: ajuri.Tulos(False, 1.15, "", "budjetti loppui"))
        s = self.tila()
        self.assertEqual(s["tehtavat"]["a"]["tila"], "epaonnistui")
        self.assertEqual(s["tehtavat"]["a"]["yrityksia"], 1)
        self.assertAlmostEqual(s["kulut"][PVM], 1.15)
        self.assertIn("EPAONNISTUI", teksti)
        self.assertIn("budjetti loppui", teksti)

    def test_tila_tallentuu_heti_vaikka_seuraava_tehtava_kaatuu(self):
        self.kirjoita_jono(jono([t("a"), t("b")]))
        n = {"i": 0}

        def suorita(tehtava, *a):
            n["i"] += 1
            if n["i"] == 2:
                raise RuntimeError("yllatys")
            return ajuri.Tulos(True, 0.7, "x.md", "ok")

        with self.assertRaises(RuntimeError):
            self.aja(suorita)
        self.assertAlmostEqual(self.tila()["kulut"][PVM], 0.7)  # ensimmaisen kulu ei hukkaantunut

    def test_kuiva_ajo_ei_kutsu_eika_kirjoita_tilaa(self):
        self.kirjoita_jono(jono([t("a")]))
        kutsut = []
        teksti, viestit = self.aja(lambda *a: kutsut.append(1), kuiva=True)
        self.assertEqual(kutsut, [])
        self.assertFalse((self.perus / "tila.json").exists())
        self.assertIn("- a: r (budjetti 1.00)", teksti)
        self.assertEqual(viestit, [])

    def test_ilta_aikaraja_ohittaa_loput(self):
        self.kirjoita_jono(jono([t("a"), t("b")]))
        kellot = iter([0, 0, ajuri.ILTA_AIKARAJA_S + 1])  # alku, tarkistus ennen a:ta, tarkistus ennen b:ta
        kutsut = []

        def suorita(tehtava, *a):
            kutsut.append(tehtava["id"])
            return ajuri.Tulos(True, 0.1, "x.md", "ok")

        teksti, _ = self.aja(suorita, nyt=lambda: next(kellot))
        self.assertEqual(kutsut, ["a"])
        self.assertIn("b: ohitettu (yon aikaraja)", teksti)

    def test_lukko_estaa_rinnakkaisajon(self):
        import fcntl
        self.kirjoita_jono(jono([t("a")]))
        with open(self.perus / "lukko", "w") as lukko:
            fcntl.flock(lukko, fcntl.LOCK_EX | fcntl.LOCK_NB)
            kutsut = []
            teksti, _ = self.aja(lambda *a: kutsut.append(1))
        self.assertEqual(kutsut, [])
        self.assertIn("Toinen ajo on kaynnissa", teksti)

    def test_virheellinen_jono_nostaa_jonovirheen_eika_aja_mitaan(self):
        self.kirjoita_jono(jono([t("a", repo="../x")]))
        kutsut = []
        with self.assertRaises(ajuri.JonoVirhe):
            self.aja(lambda *a: kutsut.append(1))
        self.assertEqual(kutsut, [])

    def test_tyhja_jono(self):
        teksti, _ = self.aja(lambda *a: None)
        self.assertIn("Ei ajettavia tehtavia", teksti)

    def test_telegram_kutsutaan_vain_kun_ajettiin_jotain(self):
        self.kirjoita_jono(jono([t("a")]))
        lahetetyt = []
        self.aja(lambda *a: ajuri.Tulos(True, 0.1, "x.md", "ok"), telegram=lahetetyt.append)
        self.assertEqual(len(lahetetyt), 1)
        lahetetyt.clear()
        self.aja(lambda *a: None, telegram=lahetetyt.append)  # "a" on jo valmis
        self.assertEqual(lahetetyt, [])


class TestKatselmointiSkripti(Pohja):
    """Oikea alaprosessi: tekoskripti, joka toimii kuten katselmoi.sh."""

    def skripti(self, runko):
        polku = self.perus / "katselmoi.sh"
        polku.write_text("#!/bin/sh\n" + runko)
        polku.chmod(polku.stat().st_mode | stat.S_IXUSR)
        (self.perus / "raportit").mkdir(exist_ok=True)
        return polku

    def test_onnistunut_ajo_lukee_kulun_json_ista_ja_saa_budjetin_argumenttina(self):
        s = self.skripti(f'echo "$1 $2" > {self.perus}/argumentit\n'
                         f'echo \'{{"total_cost_usd": 0.58, "result": "x"}}\' > "{self.perus}/raportit/{PVM}-$1.json"\n'
                         f'echo raportti > "{self.perus}/raportit/{PVM}-$1.md"\n')
        tulos = ajuri.suorita_katselmointi(t("a", repo="mcp-homelab", budjetti=2.0), PVM, self.perus, s)
        self.assertTrue(tulos.ok)
        self.assertAlmostEqual(tulos.kulu, 0.58)
        self.assertEqual((self.perus / "argumentit").read_text().strip(), "mcp-homelab 2.00")
        self.assertTrue(tulos.raportti.endswith(f"{PVM}-mcp-homelab.md"))

    def test_budjetin_ylitys_json_ssa_mutta_ei_raporttia_on_epaonnistuminen_ja_kulu_tiedossa(self):
        s = self.skripti(f'echo \'{{"total_cost_usd": 1.15, "subtype": "error_max_budget_usd"}}\' > "{self.perus}/raportit/{PVM}-$1.json"\nexit 1\n')
        tulos = ajuri.suorita_katselmointi(t("a", repo="mcp-model-router", budjetti=1.5), PVM, self.perus, s)
        self.assertFalse(tulos.ok)
        self.assertAlmostEqual(tulos.kulu, 1.15)

    def test_kloonaus_epaonnistuu_ennen_claudea_kulu_nolla(self):
        s = self.skripti("echo 'fatal: repository not found' >&2\nexit 128\n")
        tulos = ajuri.suorita_katselmointi(t("a", repo="puuttuu"), PVM, self.perus, s)
        self.assertFalse(tulos.ok)
        self.assertEqual(tulos.kulu, 0.0)
        self.assertIn("repository not found", tulos.viesti)

    def test_lukukelvoton_json_laskutetaan_koko_budjetti(self):
        s = self.skripti(f'echo "ei json" > "{self.perus}/raportit/{PVM}-$1.json"\nexit 1\n')
        tulos = ajuri.suorita_katselmointi(t("a", budjetti=1.7), PVM, self.perus, s)
        self.assertFalse(tulos.ok)
        self.assertAlmostEqual(tulos.kulu, 1.7)

    def test_aikakatkaisu_laskutetaan_koko_budjetti(self):
        s = self.skripti("sleep 5\n")
        tulos = ajuri.suorita_katselmointi(t("a", budjetti=1.2), PVM, self.perus, s, aikaraja=0.2)
        self.assertFalse(tulos.ok)
        self.assertAlmostEqual(tulos.kulu, 1.2)
        self.assertIn("aikakatkaisu", tulos.viesti)

    def test_vanha_raportti_ei_nay_onnistumisena(self):
        s = self.skripti("exit 1\n")
        (self.perus / "raportit" / f"{PVM}-a.json").write_text('{"total_cost_usd": 9}')
        (self.perus / "raportit" / f"{PVM}-a.md").write_text("vanha")
        tulos = ajuri.suorita_katselmointi(t("a", repo="a"), PVM, self.perus, s)
        self.assertFalse(tulos.ok)
        self.assertEqual(tulos.kulu, 0.0)

    def test_poistumiskoodi_nolla_ilman_raporttia_ei_ole_onnistuminen(self):
        s = self.skripti("exit 0\n")
        tulos = ajuri.suorita_katselmointi(t("a", repo="a"), PVM, self.perus, s)
        self.assertFalse(tulos.ok)

    def test_json_paivittyi_mutta_md_puuttuu_ei_ole_onnistuminen(self):
        s = self.skripti(f'echo \'{{"total_cost_usd": 0.3}}\' > "{self.perus}/raportit/{PVM}-$1.json"\n')
        tulos = ajuri.suorita_katselmointi(t("a", repo="a"), PVM, self.perus, s)
        self.assertFalse(tulos.ok)
        self.assertAlmostEqual(tulos.kulu, 0.3)

    def test_totuusarvo_kulukentassa_ei_kelpaa_kuluksi(self):
        s = self.skripti(f'echo \'{{"total_cost_usd": true}}\' > "{self.perus}/raportit/{PVM}-$1.json"\nexit 1\n')
        tulos = ajuri.suorita_katselmointi(t("a", repo="a", budjetti=1.4), PVM, self.perus, s)
        self.assertAlmostEqual(tulos.kulu, 1.4)  # luetaan lukukelvottomaksi, ei 1.0:ksi

    def test_telegram_tunnukset_eivat_kulkeudu_alaprosessille(self):
        s = self.skripti(f'echo "$YOJONO_TELEGRAM_TOKEN|$YOJONO_TELEGRAM_CHAT|$MUU" > {self.perus}/ymparisto\nexit 1\n')
        with mock.patch.dict(os.environ, {"YOJONO_TELEGRAM_TOKEN": "salainen", "YOJONO_TELEGRAM_CHAT": "42", "MUU": "ok"}):
            ajuri.suorita_katselmointi(t("a", repo="a"), PVM, self.perus, s)
        self.assertEqual((self.perus / "ymparisto").read_text().strip(), "||ok")

    def test_puuttuva_skripti(self):
        tulos = ajuri.suorita_katselmointi(t("a"), PVM, self.perus, self.perus / "ei-ole.sh")
        self.assertFalse(tulos.ok)
        self.assertEqual(tulos.kulu, 0.0)


class TestTelegram(unittest.TestCase):
    def test_ei_laheta_ilman_asetuksia(self):
        with mock.patch("urllib.request.urlopen") as u:
            self.assertFalse(ajuri.laheta_telegram("x", env={}))
            u.assert_not_called()

    def test_verkkovirhe_ei_kaada_eika_vuoda_tokenia(self):
        env = {"YOJONO_TELEGRAM_TOKEN": "SALAINEN-TOKEN", "YOJONO_TELEGRAM_CHAT": "1"}
        with mock.patch("urllib.request.urlopen", side_effect=OSError("SALAINEN-TOKEN yhteys")), \
                mock.patch("sys.stderr") as err:
            self.assertFalse(ajuri.laheta_telegram("x", env=env))
        kirjoitettu = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertNotIn("SALAINEN-TOKEN", kirjoitettu)

    def test_teksti_katkaistaan(self):
        env = {"YOJONO_TELEGRAM_TOKEN": "t", "YOJONO_TELEGRAM_CHAT": "1"}
        with mock.patch("urllib.request.urlopen") as u:
            u.return_value.__enter__.return_value.status = 200
            ajuri.laheta_telegram("x" * 10000, env=env)
        pyynto = u.call_args.args[0]
        self.assertLessEqual(len(json.loads(pyynto.data)["text"]), ajuri.TELEGRAM_MAX)
        self.assertTrue(pyynto.full_url.startswith("https://"))


class TestMain(Pohja):
    def test_virheellinen_jono_palauttaa_2(self):
        self.kirjoita_jono(jono([t("a", repo="../x")]))
        with mock.patch.dict(os.environ, {"YOJONO_PERUS": str(self.perus)}), mock.patch("sys.stderr"):
            self.assertEqual(ajuri.main(["ajo"]), 2)

    def test_kuiva_tulostaa(self):
        self.kirjoita_jono(jono([t("a")]))
        with mock.patch.dict(os.environ, {"YOJONO_PERUS": str(self.perus)}), mock.patch("builtins.print") as pr:
            self.assertEqual(ajuri.main(["kuiva"]), 0)
        self.assertIn("- a: r", pr.call_args.args[0])


if __name__ == "__main__":
    unittest.main()


class LokiKirjaus(Pohja):
    def test_kirjaa_tapahtuman_kun_polku_annettu(self):
        from agentti import tapahtumaloki
        polku = str(self.perus / "loki.db")
        self.kirjoita_jono(jono([t("a")]))
        with mock.patch.dict(os.environ, {"YOJONO_LOKI": polku}):
            self.aja(lambda *_: ajuri.Tulos(True, 0.5, "x.md", "ok"))
        yht = tapahtumaloki.avaa(polku)
        try:
            rivit = yht.execute("SELECT lahde, tyyppi, tulos, kulu_usd FROM tapahtuma").fetchall()
        finally:
            yht.close()
        self.assertEqual(rivit, [("yojono", "katselmointi", "ok", 0.5)])

    def test_ilman_polkua_ei_kirjata_ja_virhe_ei_kaada(self):
        self.kirjoita_jono(jono([t("a")]))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOJONO_LOKI", None)
            teksti, _ = self.aja(lambda *_: ajuri.Tulos(True, 0.5, "x.md", "ok"))
        self.assertIn("VALMIS", teksti)
        self.kirjoita_jono(jono([t("a"), t("b")]))
        with mock.patch.dict(os.environ, {"YOJONO_LOKI": "/ei/ole/loki.db"}):
            teksti, _ = self.aja(lambda *_: ajuri.Tulos(False, 0.1, "", "virhe"))
        self.assertIn("b: EPAONNISTUI", teksti)  # loki ei toimi, ajo silti valmistuu
