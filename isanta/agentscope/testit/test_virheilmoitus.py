"""Stdlib-testit virheilmoitus.py:lle. Ei verkkoa, ei salaisuuksia."""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import virheilmoitus as v  # noqa: E402

NYT = datetime(2026, 10, 21, 4, 31)
NYT_Y = datetime(2026, 10, 21, 10, 0)  # yojonon ajopaiva vaihtuu klo 09:00


class YksikkoTesti(unittest.TestCase):
    def test_viesti_muodossa_virhe_syy_loki(self):
        show = {"Result": "exit-code", "ExecMainStatus": "1", "ExecMainStartTimestampMonotonic": "1000000", "ExecMainExitTimestampMonotonic": "13500000"}
        rivit = ["[live] lahteita 9/10", "[live] haku epaonnistui", "Traceback (most recent call last):", "ValueError: SALAINEN-viesti sk-abcdef123"]
        t = v.yksikon_viesti("trendit-paiva.service", show, rivit, NYT)
        self.assertEqual(t.splitlines()[0], "trendit-paiva.service 21.10.2026 04:31")
        self.assertIn("Virhe: trendit_paiva_exit_code", t)
        self.assertIn("Syy: prosessi palautti", t)
        self.assertIn("Loki: exit=1 kesto_s=12.5 '[live] lahteita 9/10' '[live] haku epaonnistui' poikkeus=ValueError", t)

    def test_poikkeusviestia_ja_avaimia_ei_viestissa(self):
        rivit = ["[x] token=ABC123 sk-SALAINEN", "RuntimeError: SALAINEN-viesti"]
        t = v.yksikon_viesti("yojono.service", {"Result": "timeout"}, rivit, NYT)
        self.assertNotIn("SALAINEN-viesti", t)
        self.assertNotIn("ABC123", t)
        self.assertNotIn("sk-SALAINEN", t)
        self.assertIn("poikkeus=RuntimeError", t)
        t.encode("ascii")

    def test_virheellinen_yksikon_nimi_hylataan(self):
        with self.assertRaises(ValueError):
            v.yksikon_viesti("a b; rm -rf /", {}, [], NYT)

    def test_pituusraja(self):
        t = v.muotoile("o", ["k"], "s", "x" * 5000)
        self.assertLessEqual(len(t), v.TELEGRAM_MAX)


class AjorivinKoodiTesti(unittest.TestCase):
    SHOW = {"Result": "exit-code", "ExecMainStatus": "1"}
    LOKI = ("2026-10-19T08:30:04+03:00 tila=send vaihe=laheta tokenit=12508/2269 kesto_s=12.14 finish=stop virhekoodi=-\n"
            "2026-10-21T07:30:04+03:00 tila=send vaihe=laheta tokenit=12510/5000 kesto_s=15.62 finish=length http=200 virhekoodi=llm_vastaus_katkaistu\n"
            "2026-10-21T07:31:24+03:00 komennot tapahtuma=tyhja kesto_s=0.18\n")

    def viesti(self, loki, nyt=NYT, **kw):
        polku = "/x/paivakatsaus.log"
        orig = v.ajorivin_tiedot
        v.ajorivin_tiedot = lambda p, pvm, lue=None: orig(p, pvm, lue=lambda _: loki if loki is not None else (_ for _ in ()).throw(OSError()))
        try:
            return v.yksikon_viesti("paivakatsaus.service", self.SHOW, [], nyt, ajolokit={"paivakatsaus": polku},
                                    syy_haku=lambda k: {"llm_vastaus_katkaistu": "mallin vastaus saavutti max_tokens-rajan"}.get(k, ""), **kw)
        finally:
            v.ajorivin_tiedot = orig

    def test_virhekoodi_lokista_virhe_riville_ja_tarkka_syy(self):
        t = self.viesti(self.LOKI)
        self.assertIn("Virhe: llm_vastaus_katkaistu\n", t)
        self.assertNotIn("paivakatsaus_exit_code", t)
        self.assertIn("Syy: mallin vastaus saavutti max_tokens-rajan", t)
        self.assertIn("tokenit=12510/5000 finish=length http=200", t)

    def test_komennot_rivit_ohitetaan_viimeisena_ajorivina(self):
        self.assertIn("Virhe: llm_vastaus_katkaistu", self.viesti(self.LOKI))

    def test_monta_koodia(self):
        t = self.viesti("2026-10-21T07:30:04+03:00 tila=send vaihe=laheta virhekoodi=collector_virhe,laheta_virhe\n")
        self.assertIn("Virhe: collector_virhe, laheta_virhe", t)

    def test_tyhja_kentta_kayttaa_varakoodia(self):
        t = self.viesti("2026-10-21T07:30:04+03:00 tila=send vaihe=laheta virhekoodi=-\n")
        self.assertIn("Virhe: paivakatsaus_exit_code", t)
        self.assertIn("Syy: prosessi palautti", t)

    def test_vanhentunut_rivi_kayttaa_varakoodia(self):
        t = self.viesti(self.LOKI, nyt=datetime(2026, 10, 22, 7, 31))
        self.assertIn("Virhe: paivakatsaus_exit_code", t)

    def test_puuttuva_tai_lukukelvoton_loki_kayttaa_varakoodia(self):
        self.assertIn("Virhe: paivakatsaus_exit_code", self.viesti(None))
        self.assertIn("Virhe: paivakatsaus_exit_code", self.viesti("ei ajoriveja\n"))

    def test_virheellinen_koodi_hylataan_eika_vuoda(self):
        t = self.viesti("2026-10-21T07:30:04+03:00 tila=send virhekoodi=SALAINEN-avain,Y;rm\n")
        self.assertIn("Virhe: paivakatsaus_exit_code", t)
        self.assertNotIn("SALAINEN", t)

    def test_yksikko_ilman_ajolokia_kayttaa_varakoodia(self):
        t = v.yksikon_viesti("trendit-paiva.service", {"Result": "exit-code"}, [], NYT, ajolokit={"paivakatsaus": "/x"})
        self.assertIn("Virhe: trendit_paiva_exit_code", t)

    def test_oikea_tiedosto_luetaan(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "loki.log"
            p.write_text(self.LOKI, encoding="utf-8")
            self.assertEqual(v.ajorivin_tiedot(p, "2026-10-21"), (["llm_vastaus_katkaistu"], ["tokenit=12510/5000", "finish=length", "http=200"]))
            self.assertEqual(v.ajorivin_tiedot(Path(d) / "puuttuu.log", "2026-10-21"), ([], []))


class YojonoTesti(unittest.TestCase):
    TILA = {"tehtavat": {
        "a": {"tila": "epaonnistui", "pvm": "2026-10-21", "kulu": 1.5, "yrityksia": 1, "viesti": "aikakatkaisu 1800 s jalkeen SALAINEN"},
        "b": {"tila": "valmis", "pvm": "2026-10-21", "kulu": 0.5, "yrityksia": 0, "viesti": "ok"},
        "c": {"tila": "epaonnistui", "pvm": "2026-10-20", "kulu": 0.0, "yrityksia": 1, "viesti": "poistumiskoodi 1"},
        "d": {"tila": "epaonnistui", "pvm": "2026-10-21", "kulu": 0.0, "yrityksia": 2, "viesti": "git clone: fatal SALAINEN"}}}

    def test_nahdyt_ilmoittaa_vain_uudet(self):
        import copy
        n = set()
        t1 = v.yojono_viesti(self.TILA, nyt=NYT_Y, nahdyt=n)
        self.assertIn("a(aikakatkaisu,1.50USD,yr=1)", t1)
        self.assertEqual(v.yojono_viesti(self.TILA, nyt=NYT_Y, nahdyt=n), "")
        tila = copy.deepcopy(self.TILA)
        tila["tehtavat"]["a"]["yrityksia"] = 2
        t3 = v.yojono_viesti(tila, nyt=NYT_Y, nahdyt=n)
        self.assertIn("a(aikakatkaisu,1.50USD,yr=2)", t3)
        self.assertNotIn("d(", t3)

    def test_ajopaiva_vaihtuu_klo_yhdeksan(self):
        self.assertEqual(v._ajopaiva(datetime(2026, 10, 21, 8, 59)), "2026-10-20")
        self.assertEqual(v._ajopaiva(datetime(2026, 10, 21, 9, 0)), "2026-10-21")

    def test_oletusaika_on_helsingin_aikaa(self):
        import sys
        from datetime import timedelta, timezone
        from unittest import mock
        n = v.helsinki_nyt()
        self.assertIn(n.utcoffset(), (timedelta(hours=2), timedelta(hours=3)))
        with mock.patch.dict(sys.modules, {"zoneinfo": None}):          # ei tzdataa: palvelimen oma aika, ei kaatumista
            self.assertIsNone(v.helsinki_nyt().tzinfo)
        # palvelin UTC:ssa: 07:30 UTC = 10:30 Helsingissa on jo uusi ajopaiva, 05:30 UTC = 08:30 Helsingissa vielä vanha
        hki = timezone(timedelta(hours=3))
        with mock.patch.object(v, "helsinki_nyt", return_value=datetime(2026, 10, 21, 7, 30, tzinfo=timezone.utc).astimezone(hki)):
            self.assertEqual(v._ajopaiva(), "2026-10-21")
        with mock.patch.object(v, "helsinki_nyt", return_value=datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc).astimezone(hki)):
            self.assertEqual(v._ajopaiva(), "2026-10-20")

    def test_viestin_otsikon_aika_on_helsingin_aikaa_kun_nyt_puuttuu(self):
        from datetime import timedelta, timezone
        from unittest import mock
        hki = datetime(2026, 10, 21, 10, 30, tzinfo=timezone(timedelta(hours=3)))
        with mock.patch.object(v, "helsinki_nyt", return_value=hki):
            t = v.yksikon_viesti("trendit.service", show={"Result": "exit-code"}, rivit=[], ajolokit={})
        self.assertIn("trendit.service 21.10.2026 10:30", t)

    def test_vain_tanaan_epaonnistuneet_luokiteltuina(self):
        t = v.yojono_viesti(self.TILA, nyt=NYT_Y)
        self.assertIn("Virhe: yojono_tehtava_epaonnistui", t)
        self.assertIn("a(aikakatkaisu,1.50USD,yr=1)", t)
        self.assertIn("d(muu,0.00USD,yr=2)", t)
        self.assertNotIn("b(", t)
        self.assertNotIn("c(", t)
        self.assertNotIn("SALAINEN", t)

    def test_ei_epaonnistuneita_ei_viestia(self):
        self.assertEqual(v.yojono_viesti({"tehtavat": {"b": self.TILA["tehtavat"]["b"]}}, nyt=NYT_Y), "")
        self.assertEqual(v.yojono_viesti({}, nyt=NYT_Y), "")


class LahetysTesti(unittest.TestCase):
    def test_ilman_tunnuksia_ei_lahteta(self):
        self.assertFalse(v.laheta("x", env={}))


if __name__ == "__main__":
    unittest.main()
