import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from claudejono import ajuri, vahti

NYT = 1_800_000_000.0


def aika(ika_s):
    return datetime.fromtimestamp(NYT - ika_s).astimezone().isoformat(timespec="seconds")


class Pohja(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tila = Path(self._t.name) / "tila"
        self.repo = Path(self._t.name) / "docs"
        self.tyohak = Path(self._t.name) / "tyohak"
        for p in (self.tila, self.tyohak, self.repo / "claude-jono" / "tehtavat", self.repo / "claude-jono" / "tulokset"):
            p.mkdir(parents=True)
        self.env = {}
        self.viestit, self.korjaukset, self.pingit = [], [], []

    def loki(self, *rivit):
        with open(self.tila / ajuri.KAISTALOKI, "w", encoding="utf-8") as f:
            for ika_s, laji, ok in rivit:
                f.write(json.dumps({"aika": aika(ika_s), "kaista": 1, "laji": laji, "tehtava": "x", "ok": ok}) + "\n")

    def avoin_tehtava(self):
        (self.repo / "claude-jono" / "tehtavat" / "2026-11-04-01-testi.md").write_text("x", encoding="utf-8")

    def aja(self, nyt=NYT, **kw):
        return vahti.kasittele(str(self.tila), str(self.repo), str(self.tyohak), self.env, nyt_s=nyt,
                               laheta=self.viestit.append, korjaaja=lambda: self.korjaukset.append(1) or True,
                               ping=lambda env: self.pingit.append(1) or True, **kw)


class Tarkistus(Pohja):
    def test_tuore_valmis_ajo_on_terve_ja_pingaa(self):
        self.loki((600, "tehtava", True))
        t, _ = self.aja()
        self.assertEqual(t["tila"], "terve")
        self.assertEqual((self.viestit, self.korjaukset, len(self.pingit)), ([], [], 1))

    def test_suunnitteluajo_riittaa_terveeksi(self):
        self.loki((3 * 3600, "tehtava", True), (900, "suunnittelu", True))
        self.assertEqual(self.aja()[0]["tila"], "terve")

    def test_epaonnistunut_ajo_ei_ole_valmis(self):
        self.avoin_tehtava()
        self.loki((3 * 3600, "tehtava", True), (60, "tehtava", False))
        self.assertEqual(self.aja()[0]["tila"], "pysahtynyt")

    def test_yli_2h_vanha_ajo_halyttaa_ja_kaynnistaa_korjaajan_kerran(self):
        self.avoin_tehtava()
        self.loki((2 * 3600 + 60, "tehtava", True))
        t, rivi = self.aja()
        self.assertEqual(t["tila"], "pysahtynyt")
        self.assertEqual(len(self.viestit), 1)
        self.assertTrue(self.viestit[0].startswith("HALYTYS"))   # ohittaa CLAUDEJONO_ILMOITUKSET=kooste-rajauksen
        self.assertEqual(len(self.korjaukset), 1)
        self.assertEqual(self.pingit, [])   # pysahtyneena ei pingata
        # toisto 1 h 59 min myohemmin: ei uutta viestia eika korjaajaa
        self.aja(nyt=NYT + 2 * 3600 - 60)
        self.assertEqual((len(self.viestit), len(self.korjaukset)), (1, 1))
        # 2 h jalkeen: uusi halytys
        self.aja(nyt=NYT + 2 * 3600 + 1)
        self.assertEqual((len(self.viestit), len(self.korjaukset)), (2, 2))

    def test_kuiva_ajo_ei_tee_mitaan(self):
        self.avoin_tehtava()
        self.loki((5 * 3600, "tehtava", True))
        t, _ = self.aja(kuiva=True)
        self.assertEqual(t["tila"], "pysahtynyt")
        self.assertEqual((self.viestit, self.korjaukset, self.pingit), ([], [], []))
        self.assertFalse((self.tila / vahti.TILA_TIEDOSTO).exists())

    def test_pysaytystiedosto_on_tauko(self):
        self.avoin_tehtava()
        self.loki((9 * 3600, "tehtava", True))
        (self.tila / vahti.PYSAYTYS_TIEDOSTO).write_text("", encoding="utf-8")
        t, _ = self.aja()
        self.assertEqual((t["tila"], t["syy"]), ("tauolla", "pysaytystiedosto"))
        self.assertEqual((self.viestit, self.korjaukset, len(self.pingit)), ([], [], 1))

    def test_kayttorajan_tauko_on_tauko(self):
        self.avoin_tehtava()
        self.loki((9 * 3600, "tehtava", True))
        (self.tila / "raja-pysaytys.json").write_text(json.dumps({"asti": NYT + 1800}), encoding="utf-8")
        self.assertEqual(self.aja()[0]["syy"], "kayttorajan tauko")

    def test_tyhja_jono_ilman_suunnittelua_on_tauko(self):
        self.loki((9 * 3600, "tehtava", True))
        self.env = {"CLAUDEJONO_ITSESUUNNITTELU": "0"}
        self.assertEqual(self.aja()[0]["syy"], "jono tyhja")

    def test_tyhja_jono_suunnittelutauolla_on_tauko(self):
        self.loki((9 * 3600, "suunnittelu", True))
        (self.tyohak / ajuri.SUUNNITTELU_TILA).write_text(
            json.dumps({"aika": NYT - 3600, "tehtavia": 0, "tuloksia": 0}), encoding="utf-8")
        self.assertEqual(self.aja()[0]["tila"], "tauolla")

    def test_tyhja_jono_ilman_suunnittelutaukoa_on_pysahtynyt(self):
        # itsesuunnittelun pitaisi ajaa; ei ole ajanut 9 h
        self.loki((9 * 3600, "suunnittelu", True))
        self.assertEqual(self.aja()[0]["tila"], "pysahtynyt")

    def test_ajastimet_pois_on_tauko(self):
        self.avoin_tehtava()
        self.loki((9 * 3600, "tehtava", True))
        self.assertEqual(self.aja(ajastin_aktiivinen=lambda n: False)[0]["tila"], "tauolla")
        self.assertEqual(self.aja(ajastin_aktiivinen=lambda n: n.endswith("2.timer"))[0]["tila"], "pysahtynyt")

    def test_ei_lokia_ei_halytysta_eika_pingia(self):
        self.avoin_tehtava()
        t, _ = self.aja()
        self.assertEqual(t["tila"], "ei_dataa")
        self.assertEqual((self.viestit, self.korjaukset, self.pingit), ([], [], []))

    def test_rikkinainen_rivi_ja_tulevaisuuden_aika_eivat_peita_pysahdysta(self):
        self.avoin_tehtava()
        self.loki((5 * 3600, "tehtava", True))
        with open(self.tila / ajuri.KAISTALOKI, "a", encoding="utf-8") as f:
            f.write("{rikki\n")
            f.write(json.dumps({"aika": aika(-86400), "laji": "tehtava", "ok": True}) + "\n")
        self.assertEqual(self.aja()[0]["tila"], "pysahtynyt")


class Kuma(unittest.TestCase):
    def test_osoite_vain_http(self):
        self.assertIsNone(vahti.kuman_osoite({}))
        self.assertIsNone(vahti.kuman_osoite({"CLAUDEJONO_KUMA_PUSH_URL": "file:///etc/passwd"}))
        self.assertEqual(vahti.kuman_osoite({"CLAUDEJONO_KUMA_PUSH_URL": "http://kuma.invalid/api/push/abc"}),
                         "http://kuma.invalid/api/push/abc")

    def test_ping_virhe_ei_vuoda_osoitetta(self):
        import contextlib
        import io
        salainen = "http://kuma.invalid/api/push/SALAINEN"

        def rikki(*a, **k):
            raise OSError(salainen)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tulos = vahti.pingaa_kuma({"CLAUDEJONO_KUMA_PUSH_URL": salainen}, avaa=rikki)
        self.assertFalse(tulos)
        self.assertNotIn("SALAINEN", err.getvalue())
        self.assertIn("OSError", err.getvalue())

    def test_korjaajan_yksikko_on_valvottu(self):
        from claudejono import korjaaja
        self.assertIsNone(korjaaja.tarkista_yksikko(vahti.KORJAAJA_YKSIKKO.split("@", 1)[1].rsplit(".service", 1)[0]))


class AjastinIlmanSeuraavaa(Pohja):
    """22.11.2026: kaista 3-4 oli paalla, mutta NEXT puuttui kuusi tuntia."""
    JUMISSA = {"ActiveState": "active", "NextElapseUSecMonotonic": "infinity", "NextElapseUSecRealtime": ""}

    def test_tunnistus(self):
        self.assertTrue(vahti.ilman_seuraavaa_ajoa(self.JUMISSA, "inactive"))
        self.assertTrue(vahti.ilman_seuraavaa_ajoa(self.JUMISSA, "failed"))
        # Ajo kaynnissa: NEXT puuttuu luonnostaan
        self.assertFalse(vahti.ilman_seuraavaa_ajoa(self.JUMISSA, "activating"))
        self.assertFalse(vahti.ilman_seuraavaa_ajoa(self.JUMISSA, "active"))
        # Ajastin pois paalta: tarkoituksellinen
        self.assertFalse(vahti.ilman_seuraavaa_ajoa(dict(self.JUMISSA, ActiveState="inactive"), "inactive"))
        self.assertFalse(vahti.ilman_seuraavaa_ajoa(dict(self.JUMISSA, NextElapseUSecMonotonic="1month 1w 19h 56min"), "inactive"))
        self.assertFalse(vahti.ilman_seuraavaa_ajoa(dict(self.JUMISSA, NextElapseUSecRealtime="Sun 2026-11-22 14:20:19 EET"), "inactive"))

    def test_systemctl_luku(self):
        class R:
            def __init__(self, out, rc=0):
                self.stdout, self.returncode = out, rc
        vastaukset = {
            "claude-jono@1.timer": "ActiveState=active\nNextElapseUSecMonotonic=infinity\nNextElapseUSecRealtime=\n",
            "claude-jono@1.service": "ActiveState=activating\n",
            "claude-jono@2.timer": "ActiveState=active\nNextElapseUSecMonotonic=2d 3h\nNextElapseUSecRealtime=\n",
            "claude-jono@2.service": "ActiveState=inactive\n",
            "claude-jono@3.timer": "ActiveState=active\nNextElapseUSecMonotonic=infinity\nNextElapseUSecRealtime=\n",
            "claude-jono@3.service": "ActiveState=inactive\n",
        }
        kutsut = []

        def suorita(cmd, **kw):
            kutsut.append(cmd)
            self.assertEqual(cmd[:2], ["systemctl", "show"])
            return R(vastaukset.get(cmd[2], "ActiveState=inactive\n"))
        self.assertEqual(vahti.ajastimet_ilman_seuraavaa(suorita), ["claude-jono@3.timer"])
        self.assertIn(["systemctl", "show", "claude-jono@4.timer", "-p",
                       "ActiveState,NextElapseUSecMonotonic,NextElapseUSecRealtime"], kutsut)

    def test_systemctl_virhe_ei_kaada(self):
        def suorita(cmd, **kw):
            raise OSError("ei systemctl")
        self.assertEqual(vahti.ajastimet_ilman_seuraavaa(suorita), [])

    def test_varoitus_kerran_ja_halytystila_sailyy(self):
        self.loki((600, "tehtava", True))
        t, rivi = self.aja(ilman_seuraavaa=lambda: ["claude-jono@3.timer"])
        self.assertEqual(t["tila"], "terve")
        self.assertEqual(len(self.viestit), 1)
        self.assertIn("claude-jono@3.timer", self.viestit[0])
        self.assertIn("systemctl restart claude-jono@3.timer", self.viestit[0])
        self.assertIn("ilman seuraavaa ajoa", rivi)
        self.aja(nyt=NYT + 900, ilman_seuraavaa=lambda: ["claude-jono@3.timer"])
        self.assertEqual(len(self.viestit), 1)
        self.aja(nyt=NYT + vahti.TOISTOESTE_S + 1, ilman_seuraavaa=lambda: ["claude-jono@3.timer"])
        self.assertEqual(sum("kaista-ajastimella" in v for v in self.viestit), 2)

    def test_varoitus_ei_kumoa_pysahdyksen_toistoestetta(self):
        self.avoin_tehtava()
        self.loki((3 * 3600, "tehtava", True))
        self.aja()
        self.assertEqual((len(self.viestit), len(self.korjaukset)), (1, 1))
        self.aja(nyt=NYT + 60, ilman_seuraavaa=lambda: ["claude-jono@4.timer"])
        self.assertEqual(len(self.korjaukset), 1)   # halytyksen toistoeste sailyi
        self.assertEqual(len(self.viestit), 2)      # vain ajastinvaroitus lisaksi

    def test_kuiva_ajo_ei_laheta(self):
        self.loki((600, "tehtava", True))
        _, rivi = self.aja(kuiva=True, ilman_seuraavaa=lambda: ["claude-jono@3.timer"])
        self.assertEqual(self.viestit, [])
        self.assertIn("claude-jono@3.timer", rivi)

    def test_ei_jumissa_ei_viestia(self):
        self.loki((600, "tehtava", True))
        self.aja(ilman_seuraavaa=lambda: [])
        self.assertEqual(self.viestit, [])


if __name__ == "__main__":
    unittest.main()
