"""Lisatestit Aivon kulunakymalle (chat.kulut_yhteenveto, kayttotarkoitus, lue_kulukerroin): pyoristys, jarjestys,
nimen leikkaus, kuukauden (30 vrk) raja ja virheelliset rivit. Ei verkkoa, ei tunnuksia; kirjanpito on
tilapaishakemistossa ja kello kiintea. Taydentaa test_kulunakyma.py:ta."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aivo import chat, openrouter_kulut as ok

NYT = datetime(2026, 11, 19, 12, 0, tzinfo=ok.TZ)


def rivi(paivia_sitten, usd=None, malli="m/a", tehtava="aivo-yksityinen", **lisa):
    d = {"aika": (NYT - timedelta(days=paivia_sitten)).isoformat(timespec="seconds"), "malli": malli, "tehtava": tehtava}
    if usd is not None:
        d["usd"] = usd
    d.update(lisa)
    return d


class KulutTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = self._tmp.name

    def kirjoita(self, rivit):
        (Path(self.d) / ok.KULUT).write_text("".join(json.dumps(r) + "\n" for r in rivit), encoding="utf-8")

    def yv(self, kerroin="0.92", nyt=NYT):
        return chat.kulut_yhteenveto(self.d, nyt, chat.lue_kulukerroin(kerroin))

    # tyhja loki
    def test_tyhja_loki_kaikki_jaksot_nollina(self):
        y = self.yv()
        self.assertTrue(y["luettavissa"])
        for k in ("tanaan", "paivat_7", "paivat_30"):
            self.assertEqual(y[k], {"usd": 0.0, "eur": 0.0, "mallit": {}, "tarkoitukset": {}})
        self.assertEqual((y["katosta_kaytetty"], y["varoitus"], y["katto_taynna"]), (0.0, False, False))

    # yksi ja useampi paiva
    def test_yksi_rivi_kaikissa_jaksoissa_samana(self):
        self.kirjoita([rivi(0, 2.0)])
        y = self.yv()
        for k in ("tanaan", "paivat_7", "paivat_30"):
            self.assertEqual((y[k]["usd"], y[k]["eur"]), (2.0, 1.84))
        self.assertEqual(y["katosta_kaytetty"], 0.184)

    def test_useampi_paiva_jaksoittain(self):
        self.kirjoita([rivi(0, 1.0), rivi(1, 2.0), rivi(6, 4.0), rivi(7, 8.0), rivi(29, 16.0)])
        y = self.yv()
        self.assertEqual([y[k]["usd"] for k in ("tanaan", "paivat_7", "paivat_30")], [1.0, 7.0, 31.0])

    def test_ennen_tanaan_ei_kuulu_tanaan(self):
        self.kirjoita([rivi(1, 5.0)])
        y = self.yv()
        self.assertEqual((y["tanaan"]["usd"], y["paivat_7"]["usd"]), (0.0, 5.0))

    # kuukauden raja
    def test_kuukauden_raja_29_sisalla_30_ulkona(self):
        self.kirjoita([rivi(29, 3.0), rivi(30, 5.0), rivi(-1, 7.0)])
        y = self.yv()
        self.assertEqual(y["paivat_30"]["usd"], 3.0)
        self.assertEqual(y["paivat_7"]["usd"], 0.0)

    def test_tuleva_paiva_ei_kuulu_mihinkaan(self):
        self.kirjoita([rivi(-1, 9.0)])
        self.assertEqual(self.yv()["paivat_30"]["usd"], 0.0)

    # pyoristys
    def test_usd_pyoristyy_neljaan_ja_eur_kahteen_desimaaliin(self):
        self.kirjoita([rivi(0, 0.123456)])
        y = self.yv("1")
        self.assertEqual((y["tanaan"]["usd"], y["tanaan"]["eur"]), (0.1235, 0.12))

    def test_eur_pyoristys_kaksi_desimaalia_ei_kahden_kerrannaisia(self):
        self.kirjoita([rivi(0, 1.01)])                 # 0.9292 -> 0.93 (pariton sentti)
        self.assertEqual(self.yv()["tanaan"]["eur"], 0.93)

    def test_pyoristys_puolesta_ylos(self):
        self.kirjoita([rivi(0, 0.00005)])
        self.assertEqual(self.yv("1")["tanaan"]["usd"], 0.0001)   # ei puolesta parilliseen (0.0000)
        self.kirjoita([rivi(0, 0.125)])
        self.assertEqual(self.yv("1")["tanaan"]["eur"], 0.13)

    def test_summaa_ei_pyoristeta_rivi_kerrallaan(self):
        self.kirjoita([rivi(0, 0.004), rivi(0, 0.004)])
        self.assertEqual(self.yv("1")["tanaan"]["eur"], 0.01)       # 0.008 -> 0.01, rivikohtaisesti olisi 0.00

    def test_kerroin_vaikuttaa_vain_euroihin(self):
        self.kirjoita([rivi(0, 3.0)])
        y = self.yv("2")
        self.assertEqual((y["tanaan"]["usd"], y["tanaan"]["eur"], y["kerroin_usd_eur"]), (3.0, 6.0, 2.0))

    # jarjestys ja nimet
    def test_mallit_kalleimmasta_ja_tasatilanteessa_nimen_mukaan(self):
        self.kirjoita([rivi(0, 1.0, malli="m/c"), rivi(0, 3.0, malli="m/z"), rivi(0, 1.0, malli="m/a"),
                       rivi(0, 1.0, malli="m/b")])
        self.assertEqual(list(self.yv()["tanaan"]["mallit"]), ["m/z", "m/a", "m/b", "m/c"])

    def test_sama_tarkoitus_summataan(self):
        self.kirjoita([rivi(0, 1.5), rivi(0, 2.5), rivi(0, 1.0, tehtava="aivo-tiivistys")])
        self.assertEqual(self.yv()["tanaan"]["tarkoitukset"],
                         {"chat": {"usd": 4.0, "eur": 3.68}, "tiivistys": {"usd": 1.0, "eur": 0.92}})

    def test_tarkoitukset_aakkosjarjestyksessa(self):
        self.kirjoita([rivi(0, 1.0, tehtava="aivo-tiivistys"), rivi(0, 1.0), rivi(0, 1.0, tehtava="x")])
        self.assertEqual(list(self.yv()["tanaan"]["tarkoitukset"]), ["chat", "muu", "tiivistys"])

    def test_mallin_nimi_leikataan_60_merkkiin(self):
        self.kirjoita([rivi(0, 1.0, malli="a" * 61)])
        self.assertEqual(list(self.yv()["tanaan"]["mallit"]), ["a" * 60])

    def test_puuttuva_malli_on_kysymysmerkki(self):
        r = rivi(0, 1.0)
        del r["malli"]
        self.kirjoita([r])
        self.assertEqual(list(self.yv()["tanaan"]["mallit"]), ["?"])

    def test_tasan_raja_mallia_ei_tee_muut_rivia(self):
        self.kirjoita([rivi(0, 1.0, malli="m/%02d" % i) for i in range(chat.KULUT_MALLEJA)])
        mallit = self.yv()["tanaan"]["mallit"]
        self.assertEqual(len(mallit), chat.KULUT_MALLEJA)
        self.assertNotIn("muut", mallit)

    def test_muut_ovat_halvimmat_ja_viimeisena(self):
        self.kirjoita([rivi(0, 10.0 + i, malli="m/%02d" % i) for i in range(chat.KULUT_MALLEJA + 2)])
        mallit = self.yv()["tanaan"]["mallit"]
        self.assertEqual(list(mallit)[-1], "muut")
        self.assertEqual(mallit["muut"]["usd"], 10.0 + 11.0)
        self.assertNotIn("m/00", mallit)

    def test_samat_mallit_summataan(self):
        self.kirjoita([rivi(0, 1.5), rivi(0, 2.5)])
        self.assertEqual(self.yv()["tanaan"]["mallit"], {"m/a": {"usd": 4.0, "eur": 3.68}})

    # kayttotarkoitus
    def test_kayttotarkoitus(self):
        self.assertEqual(chat.kayttotarkoitus(ok_tehtava()), "chat")
        self.assertEqual(chat.kayttotarkoitus("Aivo-TIIVISTYS"), "tiivistys")
        for muu in (None, "", "2026-11-19-55-tehtava"):
            self.assertEqual(chat.kayttotarkoitus(muu), "muu")

    # virheelliset rivit
    def test_virheelliset_rivit_nollaavat_ja_varoittavat(self):
        for huono in ('ei-jsonia', '{"aika": "2026-11-19T10:00:00"}', '{"usd": 1}', '[1]',
                      '{"aika": "2026-11-19T10:00:00+02:00", "usd": -1}',
                      '{"aika": "2026-11-19T10:00:00+02:00", "usd": "yksi"}'):
            with self.subTest(huono=huono):
                (Path(self.d) / ok.KULUT).write_text(json.dumps(rivi(0, 1.0)) + "\n" + huono + "\n", encoding="utf-8")
                y = self.yv()
                self.assertFalse(y["luettavissa"])
                self.assertTrue(y["varoitus"])
                self.assertFalse(y["katto_taynna"])
                for k in ("tanaan", "paivat_7", "paivat_30"):
                    self.assertEqual((y[k]["usd"], y[k]["mallit"], y[k]["tarkoitukset"]), (0.0, {}, {}))

    def test_virheen_sisaltoa_ei_palauteta(self):
        (Path(self.d) / ok.KULUT).write_text("salainen-roska\n", encoding="utf-8")
        self.assertNotIn("salainen", json.dumps(self.yv()))

    def test_kulutila_none_kayttaa_oletustilaa(self):
        with unittest_patch(ok, "OLETUS_TILA", self.d):
            self.kirjoita([rivi(0, 1.0)])
            y = chat.kulut_yhteenveto(None, NYT, Decimal("0.92"))
        self.assertEqual(y["tanaan"]["usd"], 1.0)

    # varoitus ja katto
    def test_varoitus_ja_katto_rajat(self):
        self.kirjoita([rivi(0, 8.69)])
        y = self.yv()
        self.assertEqual((y["varoitus"], y["katto_taynna"], y["katosta_kaytetty"]), (False, False, 0.7995))
        self.kirjoita([rivi(0, 8.70)])
        self.assertEqual((self.yv()["varoitus"], self.yv()["katto_taynna"]), (True, False))
        self.kirjoita([rivi(0, 10.87)])
        self.assertEqual((self.yv()["varoitus"], self.yv()["katto_taynna"]), (True, True))

    def test_vain_tanaan_lasketaan_kattoon(self):
        self.kirjoita([rivi(1, 50.0)])
        y = self.yv()
        self.assertEqual((y["katosta_kaytetty"], y["varoitus"], y["katto_taynna"]), (0.0, False, False))

    def test_vastauksen_vakiokentat(self):
        y = self.yv()
        self.assertEqual((y["paivakatto_eur"], y["kerroin_usd_eur"], y["eur_on_arvio"]), (10.0, 0.92, True))

    # kerroin
    def test_kerroin_rajat(self):
        self.assertEqual(chat.lue_kulukerroin("10"), Decimal(10))
        self.assertEqual(chat.lue_kulukerroin("0.0001"), Decimal("0.0001"))
        for huono in ("0", "10.01", "-0.5", "Infinity", "NaN", "x", None):
            with self.subTest(huono=huono), self.assertRaises(chat.ChatVirhe):
                chat.lue_kulukerroin(huono)


def ok_tehtava():
    return chat.yksityinen_or.TEHTAVA


class unittest_patch:
    """Pieni kontekstihallinta: asettaa moduulin attribuutin ja palauttaa sen."""
    def __init__(self, kohde, nimi, arvo):
        self.kohde, self.nimi, self.arvo = kohde, nimi, arvo

    def __enter__(self):
        self.vanha = getattr(self.kohde, self.nimi)
        setattr(self.kohde, self.nimi, self.arvo)

    def __exit__(self, *a):
        setattr(self.kohde, self.nimi, self.vanha)


if __name__ == "__main__":
    unittest.main()
