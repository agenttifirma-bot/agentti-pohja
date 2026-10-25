"""CT118:n snapshot-oikeus isannalla (kohde command=-argumentista) + CT115:n regressiotestit.

test_snapshot.py on koskematon: sen testit todistavat, etta CT115:n nykyinen kayttaytyminen ei muutu. Tama tiedosto kiinnittaa lisaksi
CT115:n tarkat pct-kutsut, lokirivin muodon ja oletuskohteen (authorized_keys-rivi ilman argumenttia)."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from isanta import snapshot_isanta as si

PAIVA = time.strftime("%Y-%m-%d")
LISTAUS = (
    "`-> perus-toimii                2026-10-14 10:20:59     no-description\n"
    " `-> ennen-haiku-malli        2026-10-18 10:46:21     no-description\n"
    "  `-> current                                      You are here!\n"
)


def lvs_ulos(data="8.82", meta="0.79", levyt=(("vm-118-disk-0", "konttilevy", "konttilevy"),), kontti="118"):
    """Oikean lvs-tulosteen muotoinen vastaus (kentat: lv_name,vg_name,lv_attr,pool_lv,data_percent,metadata_percent)."""
    rivit = ["  konttilevy,konttilevy,twi-aotz--,,%s,%s" % (data, meta),
             "  data,pve,twi-aotz--,,0.48,1.15",
             "  snap_vm-%s-disk-0_perus-toimii,konttilevy,Vri---tz-k,konttilevy,," % kontti]
    rivit += ["  %s,%s,Vwi-aotz--,%s,13.79," % l for l in levyt]
    return "\n".join(rivit) + "\n"


def feikki(listaus=LISTAUS, lvs=None, lvs_koodi=0, lvs_poikkeus=None):
    def f(komento, capture_output=True, text=True, timeout=None):
        f.kutsut.append(komento)
        if komento[0] == "lvs":
            if lvs_poikkeus:
                raise lvs_poikkeus
            return subprocess.CompletedProcess(komento, lvs_koodi, lvs_ulos() if lvs is None else lvs, "")
        if komento[:2] == ["pct", "listsnapshot"]:
            return subprocess.CompletedProcess(komento, 0, listaus, "")
        return subprocess.CompletedProcess(komento, 0, "", "")
    f.kutsut = []
    return f


def otot(f):
    return [k for k in f.kutsut if k[:2] == ["pct", "snapshot"]]


class Pohja(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.loki = os.path.join(self.tmp.name, "loki")

    def kirjoita_loki(self, *rivit):
        with open(self.loki, "w") as f:
            f.write("".join(r + "\n" for r in rivit))

    def lokirivit(self):
        with open(self.loki) as f:
            return f.read().splitlines()


class Ct115RegressioTesti(Pohja):
    """CT115:n nykyinen kayttaytyminen (live-skripti 25.10.) ei saa muuttua."""

    def test_asetukset_ennallaan(self):
        a = si.KOHTEET["115"]
        self.assertEqual((a["max_snapshotia"], a["max_paivassa"], a["levy_raja"], a["tila"], a["tarkka_loki"]), (20, 10, None, True, False))
        self.assertEqual((si.MAX_SNAPSHOTIA, si.MAX_PAIVASSA, si.CT, si.OLETUS_KOHDE), (20, 10, "115", "115"))

    def test_ilman_argumenttia_kohde_on_ct115(self):
        self.assertEqual(si.kohde_argumentista(()), "115")
        self.assertEqual(si.kohde_argumentista(["115"]), "115")

    def test_main_ilman_argumenttia_ajaa_ct115(self):
        kutsut = []
        with mock.patch.object(si, "LOKI", self.loki), mock.patch.object(si, "LUKKO", os.path.join(self.tmp.name, "l")), \
                mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "listaa"}), mock.patch("builtins.print"), \
                mock.patch.object(si, "aja", side_effect=lambda komento, kohde: kutsut.append((komento, kohde)) or {"ok": True}):
            self.assertEqual(si.main(), 0)
            self.assertEqual(si.main(()), 0)
        self.assertEqual(kutsut, [("listaa", "115")] * 2)

    def test_snapshot_pct_kutsut_tasmalleen_ennallaan(self):
        f = feikki()
        t = si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki)
        self.assertEqual(t, {"ok": True, "snapshot": "ennen-uusi"})
        self.assertEqual(f.kutsut, [["pct", "listsnapshot", "115"], ["pct", "snapshot", "115", "ennen-uusi", "--description", "CT115-pyynto"]])

    def test_ct115_ei_levytarkistusta_vaikka_allas_olisi_taynna(self):
        f = feikki(lvs=lvs_ulos(data="99.00", meta="99.00", levyt=(("vm-115-disk-0", "konttilevy", "konttilevy"),)))
        self.assertTrue(si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki)["ok"])
        self.assertFalse([k for k in f.kutsut if k[0] == "lvs"])

    def test_ct115_tila_ja_listaa_sallittu(self):
        self.assertEqual(si.aja("listaa", suorita=feikki(), loki=self.loki)["snapshotit"], ["perus-toimii", "ennen-haiku-malli"])
        self.assertTrue(si.aja("tila", suorita=feikki(), loki=self.loki)["ok"])

    def test_ct115_lokirivin_muoto_ennallaan(self):
        si.kirjaa(self.loki, "ok", "snapshot ennen-uusi")
        si.kirjaa(self.loki, "virhe", "listaa; id")
        self.assertEqual(self.lokirivit(), [PAIVA + " snapshot ok snapshot ennen-uusi", PAIVA + " muu virhe listaa; id"])

    def test_ct115_rajavirhe_kirjataan_edelleen_virhe_sanalla(self):
        def raja(komento, kohde):
            raise si.RajaVirhe("raja")
        with mock.patch.object(si, "LOKI", self.loki), mock.patch.object(si, "LUKKO", os.path.join(self.tmp.name, "l")), \
                mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "snapshot ennen-x1"}), mock.patch("builtins.print") as pr, \
                mock.patch.object(si, "aja", raja):
            self.assertEqual(si.main(()), 1)
        self.assertEqual(self.lokirivit(), [PAIVA + " snapshot virhe snapshot ennen-x1"])
        self.assertEqual(json.loads(pr.call_args[0][0]), {"ok": False, "virhe": "raja"})

    def test_ct115_vanhat_lokirivit_lasketaan_paivarajaan(self):
        self.kirjoita_loki(*[PAIVA + " snapshot ok snapshot ennen-a%d" % i for i in range(10)])
        with self.assertRaises(si.RajaVirhe):
            si.aja("snapshot ennen-uusi", suorita=feikki(), loki=self.loki)

    def test_ct115_paivarajaan_ei_lasketa_ct118_rivi(self):
        self.kirjoita_loki(*[PAIVA + " snapshot ok ct=118 snapshot ennen-a%d" % i for i in range(10)])
        self.assertEqual(si.paivan_otot(self.loki, PAIVA, "115"), 0)
        self.assertTrue(si.aja("snapshot ennen-uusi", suorita=feikki(), loki=self.loki)["ok"])


class KohdeArgumenttiTesti(Pohja):
    def test_118_hyvaksytaan(self):
        self.assertEqual(si.kohde_argumentista(["118"]), "118")

    def test_virheelliset_argumentit_hylataan_eika_aja_mitaan(self):
        for argv in (["119"], ["118", "115"], ["118 115"], ["../118"], [""], ["tila"], ["-x"]):
            with self.subTest(argv=argv):
                with mock.patch.object(si, "LOKI", self.loki), mock.patch.object(si, "LUKKO", os.path.join(self.tmp.name, "l")), \
                        mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "snapshot ennen-xy"}), mock.patch("builtins.print") as pr, \
                        mock.patch.object(si, "aja") as aja:
                    self.assertEqual(si.main(argv), 1)
                aja.assert_not_called()
                self.assertFalse(json.loads(pr.call_args[0][0])["ok"])

    def test_vain_ct115_ja_ct118_ovat_kohteita(self):
        self.assertEqual(sorted(si.KOHTEET), ["115", "118"])

    def test_118_asetukset(self):
        a = si.KOHTEET["118"]
        self.assertEqual((a["max_snapshotia"], a["max_paivassa"], a["levy_raja"], a["tila"], a["tarkka_loki"]), (10, 3, 80, False, True))


class Ct118Testi(Pohja):
    def test_snapshot_koskee_vain_ct118(self):
        f = feikki()
        t = si.aja("snapshot ennen-eh-12", suorita=f, loki=self.loki, kohde="118")
        self.assertEqual(t, {"ok": True, "snapshot": "ennen-eh-12"})
        self.assertEqual([k[0] for k in f.kutsut], ["pct", "lvs", "pct"])
        self.assertEqual(f.kutsut[0], ["pct", "listsnapshot", "118"])
        self.assertEqual(f.kutsut[2], ["pct", "snapshot", "118", "ennen-eh-12", "--description", "CT118-pyynto"])
        for k in f.kutsut:
            self.assertNotIn("115", k)

    def test_listaa_koskee_vain_ct118(self):
        f = feikki()
        self.assertEqual(si.aja("listaa", suorita=f, loki=self.loki, kohde="118")["snapshotit"], ["perus-toimii", "ennen-haiku-malli"])
        self.assertEqual(f.kutsut, [["pct", "listsnapshot", "118"]])

    def test_tila_ei_sallittu_ct118_avaimelle_eika_aja_mitaan(self):
        f = feikki()
        with self.assertRaises(si.Virhe):
            si.aja("tila", suorita=f, loki=self.loki, kohde="118")
        self.assertEqual(f.kutsut, [])

    def test_kielletyt_komennot_ct118(self):
        for k in ("", "rollback ennen-xy", "delsnapshot ennen-xy", "snapshot muu-nimi", "snapshot ennen-A", "snapshot ennen-x; id",
                  "snapshot ennen-", "snapshot 115 ennen-xy", "listaa 115", "tila 115", "snapshot ennen-xy 115"):
            with self.subTest(k=k):
                f = feikki()
                with self.assertRaises(si.Virhe):
                    si.aja(k, suorita=f, loki=self.loki, kohde="118")
                self.assertEqual(otot(f), [])

    def test_nimivalidointi_hostilla(self):
        for hyva in ("ennen-eh-12", "ennen-eh-100000"):
            self.assertEqual(si.jasenna("snapshot " + hyva), ("snapshot", hyva))

    def test_olemassa_oleva_nimi_hylataan(self):
        f = feikki()
        with self.assertRaises(si.Virhe):
            si.aja("snapshot ennen-haiku-malli", suorita=f, loki=self.loki, kohde="118")
        self.assertEqual(otot(f), [])

    def test_snapshotien_enimmaismaara_10(self):
        f = feikki(listaus="".join("`-> ennen-x%d  2026-10-11  d\n" % i for i in range(10)))
        with self.assertRaises(si.RajaVirhe):
            si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki, kohde="118")
        self.assertEqual(otot(f), [])
        f9 = feikki(listaus="".join("`-> ennen-x%d  2026-10-11  d\n" % i for i in range(9)))
        self.assertTrue(si.aja("snapshot ennen-uusi", suorita=f9, loki=self.loki, kohde="118")["ok"])

    def test_paivan_raja_3(self):
        self.kirjoita_loki(*[PAIVA + " snapshot ok ct=118 snapshot ennen-a%d" % i for i in range(3)])
        f = feikki()
        with self.assertRaises(si.RajaVirhe):
            si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki, kohde="118")
        self.assertEqual(otot(f), [])

    def test_paivan_raja_2_ottoa_sallii_kolmannen(self):
        self.kirjoita_loki(*[PAIVA + " snapshot ok ct=118 snapshot ennen-a%d" % i for i in range(2)])
        self.assertTrue(si.aja("snapshot ennen-uusi", suorita=feikki(), loki=self.loki, kohde="118")["ok"])

    def test_ct115_rivit_ja_virheet_eivat_kuluta_ct118_rajaa(self):
        self.kirjoita_loki(*[PAIVA + " snapshot ok snapshot ennen-a%d" % i for i in range(10)],
                           *[PAIVA + " snapshot virhe ct=118 snapshot ennen-b%d" % i for i in range(10)],
                           *[PAIVA + " snapshot raja ct=118 snapshot ennen-c%d" % i for i in range(10)],
                           *[PAIVA + " snapshot levy ct=118 snapshot ennen-d%d" % i for i in range(10)],
                           "2000-01-01 snapshot ok ct=118 snapshot ennen-vanha")
        self.assertEqual(si.paivan_otot(self.loki, PAIVA, "118"), 0)
        self.assertTrue(si.aja("snapshot ennen-uusi", suorita=feikki(), loki=self.loki, kohde="118")["ok"])


class LevyTesti(Pohja):
    def yrita(self, **kw):
        f = feikki(**kw)
        try:
            return f, si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki, kohde="118"), None
        except si.Virhe as e:
            return f, None, e

    def test_raja_tasan_80_sallitaan(self):
        f, t, e = self.yrita(lvs=lvs_ulos(data="80.00", meta="80.00"))
        self.assertTrue(t["ok"], e)

    def test_data_yli_80_kieltaytyy_levy_tilalla_ja_ei_ota(self):
        f, t, e = self.yrita(lvs=lvs_ulos(data="80.01"))
        self.assertIsInstance(e, si.LevyVirhe)
        self.assertEqual(e.tila, "levy")
        self.assertIn("80.01", str(e))
        self.assertEqual(otot(f), [])

    def test_metadata_yli_80_kieltaytyy(self):
        f, t, e = self.yrita(lvs=lvs_ulos(meta="80.50"))
        self.assertIsInstance(e, si.LevyVirhe)
        self.assertEqual(otot(f), [])

    def test_epakelvot_arvot_kieltaytyvat_fail_closed(self):
        for data in ("", "abc", "nan", "inf", "-1", "100.5"):
            with self.subTest(data=data):
                f, t, e = self.yrita(lvs=lvs_ulos(data=data))
                self.assertIsInstance(e, si.LevyVirhe)
                self.assertEqual(otot(f), [])

    def test_lvs_epaonnistuu_kieltaytyy(self):
        for kw in ({"lvs_koodi": 5}, {"lvs_poikkeus": OSError("puuttuu")}, {"lvs_poikkeus": subprocess.TimeoutExpired("lvs", 30)}, {"lvs": ""},
                   {"lvs": "rikkinainen rivi\nvain,kolme,kenttaa\n"}):
            with self.subTest(kw=list(kw)):
                f, t, e = self.yrita(**kw)
                self.assertIsInstance(e, si.LevyVirhe)
                self.assertEqual(otot(f), [])

    def test_kontin_levya_ei_loydy_kieltaytyy(self):
        f, t, e = self.yrita(lvs=lvs_ulos(levyt=(("vm-117-disk-0", "konttilevy", "konttilevy"),)))
        self.assertIsInstance(e, si.LevyVirhe)
        self.assertEqual(otot(f), [])

    def test_snapshot_lv_ei_kay_kontin_levyksi(self):
        ulos = "  konttilevy,konttilevy,twi-aotz--,,1.00,1.00\n  vm-118-disk-0_vanha,konttilevy,Vwi-aotz--,konttilevy,1.00,\n"
        f, t, e = self.yrita(lvs=ulos)
        self.assertIsInstance(e, si.LevyVirhe)

    def test_toinen_allas_taynna_ei_estae(self):
        ulos = lvs_ulos().replace("  data,pve,twi-aotz--,,0.48,1.15", "  data,pve,twi-aotz--,,97.00,50.00")
        f, t, e = self.yrita(lvs=ulos)
        self.assertTrue(t["ok"], e)

    def test_kontin_oma_allas_ratkaisee_vaikka_toinen_on_tyhja(self):
        ulos = lvs_ulos(data="91.00", levyt=(("vm-118-disk-0", "konttilevy", "konttilevy"),))
        f, t, e = self.yrita(lvs=ulos)
        self.assertIsInstance(e, si.LevyVirhe)

    def test_usea_levy_kaikkien_altaat_tarkistetaan(self):
        ulos = lvs_ulos(levyt=(("vm-118-disk-0", "konttilevy", "konttilevy"), ("vm-118-disk-1", "pve", "data"))).replace(
            "  data,pve,twi-aotz--,,0.48,1.15", "  data,pve,twi-aotz--,,88.00,1.00")
        f, t, e = self.yrita(lvs=ulos)
        self.assertIsInstance(e, si.LevyVirhe)
        self.assertEqual(otot(f), [])

    def test_levytarkistus_ei_ohita_nimi_ja_rajatarkistuksia(self):
        f = feikki(lvs=lvs_ulos(data="99.00"), listaus="`-> ennen-uusi  2026-10-11  d\n")
        with self.assertRaises(si.Virhe) as e:
            si.aja("snapshot ennen-uusi", suorita=f, loki=self.loki, kohde="118")
        self.assertNotIsInstance(e.exception, si.LevyVirhe)
        self.assertFalse([k for k in f.kutsut if k[0] == "lvs"])

    def test_lvs_kutsu_on_kiintea_eika_sisalla_kayttajan_syotetta(self):
        f = feikki()
        si.aja("snapshot ennen-eh-12", suorita=f, loki=self.loki, kohde="118")
        lvs = [k for k in f.kutsut if k[0] == "lvs"]
        self.assertEqual(lvs, [["lvs", "--noheadings", "--nosuffix", "--separator", ",", "-o", si.LVS_KENTAT]])


class LokiTesti(Pohja):
    def aja_main(self, komento, poikkeus=None, argv=("118",)):
        def aja(k, kohde):
            if poikkeus:
                raise poikkeus
            return {"ok": True}
        with mock.patch.object(si, "LOKI", self.loki), mock.patch.object(si, "LUKKO", os.path.join(self.tmp.name, "l")), \
                mock.patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": komento}), mock.patch("builtins.print"), mock.patch.object(si, "aja", aja):
            return si.main(argv)

    def test_ct118_loki_ok_raja_levy_virhe(self):
        self.assertEqual(self.aja_main("snapshot ennen-eh-1"), 0)
        self.assertEqual(self.aja_main("snapshot ennen-eh-2", si.RajaVirhe("r")), 1)
        self.assertEqual(self.aja_main("snapshot ennen-eh-3", si.LevyVirhe("l")), 1)
        self.assertEqual(self.aja_main("snapshot ennen-eh-4", si.Virhe("v")), 1)
        self.assertEqual(self.aja_main("listaa"), 0)
        self.assertEqual(self.lokirivit(), [
            PAIVA + " snapshot ok ct=118 snapshot ennen-eh-1",
            PAIVA + " snapshot raja ct=118 snapshot ennen-eh-2",
            PAIVA + " snapshot levy ct=118 snapshot ennen-eh-3",
            PAIVA + " snapshot virhe ct=118 snapshot ennen-eh-4",
            PAIVA + " muu ok ct=118 listaa"])

    def test_kirjatut_ok_rivit_lasketaan_takaisin_rajaan(self):
        for i in range(3):
            self.aja_main("snapshot ennen-eh-%d" % i)
        self.assertEqual(si.paivan_otot(self.loki, PAIVA, "118"), 3)
        self.assertEqual(si.paivan_otot(self.loki, PAIVA, "115"), 0)

    def test_rivinvaihto_komennossa_ei_luo_eika_vaarenna_lokiriveja(self):
        vaara = "snapshot ennen-x\n%s snapshot ok ct=118 snapshot ennen-vaarennos\r\n%s snapshot ok snapshot ennen-vaarennos2" % (PAIVA, PAIVA)
        for kohde, argv in (("118", ("118",)), ("115", ())):
            with self.subTest(kohde=kohde):
                if os.path.exists(self.loki):
                    os.remove(self.loki)
                self.assertEqual(self.aja_main(vaara, si.Virhe("x"), argv=argv), 1)
                self.assertEqual(len(self.lokirivit()), 1)
                self.assertEqual(si.paivan_otot(self.loki, PAIVA, kohde), 0)
                with open(self.loki) as f:
                    self.assertTrue(f.read().isascii())

    def test_ohjaus_ja_ei_ascii_merkit_korvataan(self):
        si.kirjaa(self.loki, "virhe", "a\x00b\x1b[0m\xe4\x85x", "118")
        self.assertEqual(self.lokirivit(), [PAIVA + " muu virhe ct=118 a?b?[0m??x"])

    def test_komennon_teksti_ei_voi_esiintya_onnistuneena_otona(self):
        self.kirjoita_loki(PAIVA + " muu virhe x snapshot ok y", PAIVA + " muu virhe ct=118 snapshot ok snapshot ennen-a",
                           PAIVA + " snapshot virhe snapshot ok", PAIVA + " snapshot ok")
        for kohde in ("115", "118"):
            self.assertEqual(si.paivan_otot(self.loki, PAIVA, kohde), 0)

    def test_virheellinen_kohdeasetus_ei_kirjaa_onnistumista(self):
        self.assertEqual(self.aja_main("snapshot ennen-xy", argv=("119",)), 1)
        self.assertNotIn(" ok ", self.lokirivit()[0])


if __name__ == "__main__":
    unittest.main()
