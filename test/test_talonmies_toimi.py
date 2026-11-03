import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from agentti import talonmies as t
from agentti import talonmies_toimi as tt

NYT = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
SEURAAVA = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
FAILED = "\u25cf foo.service loaded failed failed Foo\n"
DF = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 100 %d 20 %d%% /\n"


class Tekoinen(object):
    """Tekoinen subprocess.run: kirjaa kutsut ja vastaa skriptatusti. sudo-kutsut vastaavat JSON-rivilla."""

    def __init__(self, sudo=None, failed=(FAILED,), aktiivinen=("active",), levy=82):
        self.kutsut = []
        self.sudo = sudo or {}
        self.failed = list(failed)
        self.aktiivinen = list(aktiivinen)
        self.levy = levy

    def __call__(self, komento, **kw):
        self.kutsut.append(list(komento))
        if komento[:3] == tt.SUDO:
            vastaus = self.sudo.get(komento[3], {"ok": True})
            if isinstance(vastaus, list):
                vastaus = vastaus.pop(0)
            return subprocess.CompletedProcess(komento, 0, stdout=json.dumps(vastaus) + "\n", stderr="")
        if komento[:2] == ["systemctl", "is-active"]:
            return subprocess.CompletedProcess(komento, 0, stdout=(self.aktiivinen.pop(0) if len(self.aktiivinen) > 1 else self.aktiivinen[0]) + "\n", stderr="")
        if komento[:2] == ["systemctl", "--failed"]:
            return subprocess.CompletedProcess(komento, 0, stdout=(self.failed.pop(0) if len(self.failed) > 1 else self.failed[0]), stderr="")
        if komento[0] == "df":
            return subprocess.CompletedProcess(komento, 0, stdout=DF % (self.levy, self.levy), stderr="")
        return subprocess.CompletedProcess(komento, 0, stdout="", stderr="")

    def sudot(self):
        return [k[3:] for k in self.kutsut if k[:3] == tt.SUDO]


class Halytykset(object):
    def __init__(self):
        self.rivit = []

    def __call__(self, otsikko, teksti):
        self.rivit.append(otsikko)
        return "lahetetty"


class PalveluTesti(unittest.TestCase):
    def setUp(self):
        self.tila = tempfile.mkdtemp()
        self.hal = Halytykset()
        self.odotukset = []

    def odota(self, s):
        self.odotukset.append(s)

    def test_kaynnistaa_kerran_ja_kirjaa(self):
        s = Tekoinen()
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal), "ok")
        self.assertEqual(s.sudot(), [["kaynnista", "foo.service"]])
        self.assertEqual(self.odotukset, [60])
        self.assertEqual(tt.lue_toimet(self.tila)[0]["tulos"], "ok")
        self.assertEqual(self.hal.rivit, [])

    def test_toinen_kaatuminen_samana_paivana_on_halytys_ei_uutta_yritysta(self):
        s = Tekoinen()
        tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal)
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal), "halytys")
        self.assertEqual(len(s.sudot()), 1)      # vain ensimmainen yritys
        self.assertEqual(len(self.hal.rivit), 1)

    def test_halytys_lahetetaan_vain_kerran_paivassa(self):
        s = Tekoinen()
        for _ in range(4):
            tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal)
        self.assertEqual(len(self.hal.rivit), 1)
        self.assertEqual([r["tulos"] for r in tt.lue_toimet(self.tila)], ["ok", "halytys"])

    def test_seuraavana_paivana_uusi_yritys(self):
        s = Tekoinen()
        tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal)
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", SEURAAVA, s, self.odota, self.hal), "ok")

    def test_ei_aktiivinen_jalkeen_on_epaonnistui_ja_halytys(self):
        s = Tekoinen(aktiivinen=("failed",))
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal), "epaonnistui")
        self.assertEqual(len(self.hal.rivit), 1)

    def test_wrapper_kieltaa_ei_ok(self):
        s = Tekoinen(sudo={"kaynnista": {"ok": False, "virhe": "yksikko_ei_sallittu"}})
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal), "epaonnistui")
        self.assertEqual(self.odotukset, [])

    def test_virheellinen_yksikko_ja_kohina_ohitetaan(self):
        s = Tekoinen()
        for y in ("tmp.mount", "foo bar.service", "-x.service", "foo.service; rm", "../x.service", ""):
            self.assertEqual(tt.kaynnista_uudelleen(self.tila, y, NYT, s, self.odota, self.hal), "ohitettu", y)
        self.assertEqual(s.kutsut, [])

    def test_pysaytystiedosto_estaa_kaiken(self):
        open(os.path.join(self.tila, "PYSAYTA"), "w").close()
        s = Tekoinen()
        self.assertEqual(tt.kaynnista_uudelleen(self.tila, "foo.service", NYT, s, self.odota, self.hal), "pysaytetty")
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 85, s, self.hal), "pysaytetty")
        self.assertEqual(tt.paivita_turva(self.tila, NYT, s, self.odota, self.hal, lambda n: {"ok": True}), "pysaytetty")
        self.assertEqual(s.kutsut, [])


class SiivousTesti(unittest.TestCase):
    def setUp(self):
        self.tila = tempfile.mkdtemp()
        self.hal = Halytykset()

    def test_siivoaa_kun_80_89(self):
        s = Tekoinen(sudo={"siivoa": {"ok": True, "levy_ennen": 82, "levy_jalkeen": 60, "tiedostoja": 4}})
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 82, s, self.hal), "ok")
        self.assertEqual(s.sudot(), [["siivoa"]])
        self.assertIn("82 % -> 60 %", tt.lue_toimet(self.tila)[0]["huomio"])

    def test_rajat(self):
        s = Tekoinen()
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 79, s, self.hal), "ohitettu")
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 90, s, self.hal), "ohitettu")     # 90 % on halytys (C), ei siivousta
        self.assertEqual(s.kutsut, [])

    def test_kerran_vuorokaudessa(self):
        s = Tekoinen(sudo={"siivoa": {"ok": True, "levy_ennen": 82, "levy_jalkeen": 60, "tiedostoja": 1}})
        tt.siivoa_levy(self.tila, NYT, 82, s, self.hal)
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 82, s, self.hal), "ohitettu")
        self.assertEqual(len(s.sudot()), 1)

    def test_edelleen_taynna_on_halytys(self):
        s = Tekoinen(sudo={"siivoa": {"ok": True, "levy_ennen": 85, "levy_jalkeen": 84, "tiedostoja": 0}})
        self.assertEqual(tt.siivoa_levy(self.tila, NYT, 85, s, self.hal), "halytys")
        self.assertEqual(len(self.hal.rivit), 1)


class PaivitysTesti(unittest.TestCase):
    def setUp(self):
        self.tila = tempfile.mkdtemp()
        self.hal = Halytykset()
        self.snapshotit = []

    def lupa(self):
        with open(os.path.join(self.tila, "ei-kriittiset.txt"), "w") as f:
            f.write("# Tonyn paatos\nct115\n")

    def snap(self, nimi):
        self.snapshotit.append(nimi)
        return {"ok": True, "snapshot": nimi}

    def aja(self, s, ota=None):
        return tt.paivita_turva(self.tila, NYT, s, lambda x: None, self.hal, ota or self.snap)

    def test_ilman_tonyn_listaa_ei_tehda_mitaan(self):
        s = Tekoinen()
        self.assertEqual(self.aja(s), "ei_lupaa")
        self.assertEqual(s.kutsut, [])
        self.assertEqual(self.snapshotit, [])

    def test_onnistunut_paivitys_snapshot_ensin(self):
        self.lupa()
        s = Tekoinen(sudo={"paivita": {"ok": True, "paketit": ["openssl"]}}, failed=("",))
        self.assertEqual(self.aja(s), "ok")
        self.assertEqual(self.snapshotit, ["ennen-paivitys-20261103"])
        self.assertEqual(s.sudot(), [["paivita"]])
        self.assertEqual(tt.lue_toimet(self.tila)[0]["tulos"], "ok")

    def test_snapshot_epaonnistuu_paivitysta_ei_tehda(self):
        self.lupa()
        s = Tekoinen()
        self.assertEqual(self.aja(s, lambda n: {"ok": False, "virhe": "thin pool yli 80 %"}), "ei_tehty")
        self.assertEqual(s.sudot(), [])
        self.assertEqual(len(self.hal.rivit), 1)

    def test_snapshot_poikkeus_kirjaa_vain_tyypin(self):
        self.lupa()

        def rikki(nimi):
            raise RuntimeError("salainen-viesti")
        self.assertEqual(self.aja(Tekoinen(), rikki), "ei_tehty")
        self.assertNotIn("salainen", json.dumps(tt.lue_toimet(self.tila)))
        self.assertIn("RuntimeError", tt.lue_toimet(self.tila)[0]["huomio"])

    def test_terveystarkistus_epaonnistuu_peruutus(self):
        self.lupa()
        # ennen: ei failed-yksikoita; paivityksen jalkeen foo.service failed; peruutuksen jalkeen ei
        s = Tekoinen(sudo={"paivita": {"ok": True, "paketit": ["openssl"]}, "peruuta": {"ok": True}},
                     failed=("", FAILED, ""))
        self.assertEqual(self.aja(s), "peruttu")
        self.assertEqual(s.sudot(), [["paivita"], ["peruuta"]])
        self.assertEqual(tt.lue_toimet(self.tila)[0]["tulos"], "peruttu")
        self.assertEqual(len(self.hal.rivit), 1)

    def test_peruutus_ei_auta_neuvoo_rollbackin(self):
        self.lupa()
        teksti = []
        s = Tekoinen(sudo={"paivita": {"ok": True, "paketit": ["openssl"]}, "peruuta": {"ok": False, "virhe": "x"}},
                     failed=("", FAILED))
        tulos = tt.paivita_turva(self.tila, NYT, s, lambda x: None, lambda o, tx: teksti.append(tx), self.snap)
        self.assertEqual(tulos, "peruutus_epaonnistui")
        self.assertIn("pct rollback 115 ennen-paivitys-20261103", teksti[0])

    def test_terveys_txt_yksikon_pitaa_olla_aktiivinen(self):
        self.lupa()
        with open(os.path.join(self.tila, "terveys.txt"), "w") as f:
            f.write("github-api.service\n")
        s = Tekoinen(sudo={"paivita": {"ok": True, "paketit": ["x"]}, "peruuta": {"ok": True}},
                     failed=("",), aktiivinen=("inactive", "active"))
        self.assertEqual(self.aja(s), "peruttu")

    def test_kerran_vuorokaudessa(self):
        self.lupa()
        s = Tekoinen(sudo={"paivita": {"ok": True, "paketit": ["x"]}}, failed=("",))
        self.aja(s)
        self.assertEqual(self.aja(s), "ohitettu")
        self.assertEqual(len(self.snapshotit), 1)


class AjoTesti(unittest.TestCase):
    def setUp(self):
        self.tila = tempfile.mkdtemp()
        self.hal = Halytykset()

    def aja(self, s):
        return tt.ajo(self.tila, NYT, s, lambda x: None, self.hal, lambda n: {"ok": True}, hae_isanta=lambda: None)

    def test_ilman_sallitut_txt_vain_ehdotukset(self):
        s = Tekoinen()
        teksti, toimet = self.aja(s)
        self.assertEqual(toimet, {})
        self.assertEqual(s.sudot(), [])
        self.assertIn("kaatunut-palvelu", teksti)

    def test_sallittu_kaatunut_palvelu_kaynnistetaan(self):
        with open(os.path.join(self.tila, "sallitut.txt"), "w") as f:
            f.write("kaatunut-palvelu\n")
        s = Tekoinen(levy=50)
        _, toimet = self.aja(s)
        self.assertEqual(list(toimet.values()), ["ok"])
        self.assertEqual(s.sudot(), [["kaynnista", "foo.service"]])

    def test_sallittu_levy_siivoa_mutta_ei_kaatunutta(self):
        with open(os.path.join(self.tila, "sallitut.txt"), "w") as f:
            f.write("levy-taynna\n")
        s = Tekoinen(sudo={"siivoa": {"ok": True, "levy_ennen": 82, "levy_jalkeen": 50, "tiedostoja": 2}}, levy=82)
        _, toimet = self.aja(s)
        self.assertEqual(list(toimet.values()), ["ok"])
        self.assertEqual(s.sudot(), [["siivoa"]])

    def test_tuntematon_toimenpide_sallituissa_ei_vaikuta(self):
        with open(os.path.join(self.tila, "sallitut.txt"), "w") as f:
            f.write("poista-kaikki\n")
        self.assertEqual(tt.sallitut(self.tila), set())

    def test_levy_90_ei_siivousta(self):
        with open(os.path.join(self.tila, "sallitut.txt"), "w") as f:
            f.write("levy-taynna\n")
        s = Tekoinen(levy=92, failed=("",))
        _, toimet = self.aja(s)
        self.assertEqual(toimet, {})
        self.assertEqual(s.sudot(), [])

    def test_ajo_pysaytetty(self):
        open(os.path.join(self.tila, "PYSAYTA"), "w").close()
        teksti, toimet = self.aja(Tekoinen())
        self.assertEqual(toimet, {})
        self.assertIn("pys\u00e4ytetty", teksti)

    def test_aamurivi(self):
        self.assertIsNone(tt.aamurivi(self.tila, NYT))
        tt.kirjaa(self.tila, NYT, "kaatunut-palvelu", "foo.service", "ok")
        rivi = tt.aamurivi(self.tila, datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(rivi, "Talonmies: kaatunut-palvelu foo.service: ok")
        self.assertIsNone(tt.aamurivi(self.tila, datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
