import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from agentti import oppimittari as om
from agentti import viikkoraportti as vr

NYT = date(2030, 6, 15)     # kiinteä "nyt" annetaan parametrina: mittari ei lue kelloa


def rivi(ika_pv, syy, tarkastaja=False, tunniste=""):
    p = (NYT - timedelta(days=ika_pv)).isoformat()
    return "- %s%s: jotain tapahtui. Syy: %s. Saanto: x.%s" % (p, " (tarkastaja, tulos 1)" if tarkastaja else "", syy, tunniste)


def loki(*rivit):
    return "# Virheloki\n\n" + "\n".join(rivit) + "\n"


class JasennysTesti(unittest.TestCase):
    def test_syy_ja_luokka(self):
        mm = om.jasenna(loki(rivi(1, "testi käytti oikeaa kelloa")))
        self.assertEqual(mm[0]["luokka"], "aikapommi")
        self.assertEqual(mm[0]["paiva"], NYT - timedelta(days=1))

    def test_tunniste_ohittaa_saannot(self):
        mm = om.jasenna(loki(rivi(1, "oikeaa kelloa", tunniste=" [juurisyy: oma_luokka]")))
        self.assertEqual(mm[0]["luokka"], "oma_luokka")

    def test_tuntematon_syy_ei_luokkaa(self):
        self.assertIsNone(om.jasenna(loki(rivi(1, "aivan uusi asia")))[0]["luokka"])

    def test_otsikkomerkinta_miksi_rivi(self):
        t = "## 14.6.2030: git stash\n- Mitä: x\n- Miksi: yksi työpuu, kaksi samanaikaista työtä\n- Sääntö: y\n"
        mm = om.jasenna(t)
        self.assertEqual(mm[0]["paiva"], date(2030, 6, 14))
        self.assertEqual(mm[0]["luokka"], "ymparisto")

    def test_tarkastajan_merkinta(self):
        self.assertTrue(om.jasenna(loki(rivi(1, "x", tarkastaja=True)))[0]["tarkastaja"])


class LaskentaTesti(unittest.TestCase):
    def test_toisto_vaatii_aiemman_samaluokkaisen(self):
        teksti = loki(rivi(20, "kiinteä päivä testissä"), rivi(2, "aikapommi taas"), rivi(1, "ajettiin vain käsin"))
        v = om.mittari(teksti, NYT)
        self.assertEqual((v["nyt"]["n"], v["nyt"]["toistoja"]), (2, 1))
        self.assertEqual(v["nyt"]["luokat"], {"aikapommi": 1})

    def test_ensimmainen_esiintyma_ei_ole_toisto(self):
        v = om.mittari(loki(rivi(2, "aikapommi")), NYT)
        self.assertEqual(v["nyt"]["toistoja"], 0)

    def test_edellinen_viikko_ja_suunta_paremmin(self):
        teksti = loki(rivi(30, "aikapommi"), rivi(12, "aikapommi"), rivi(11, "aikapommi"), rivi(3, "ajettiin vain käsin"), rivi(2, "uusi"))
        v = om.mittari(teksti, NYT)
        self.assertEqual((v["ed"]["n"], v["ed"]["toistoja"]), (2, 2))
        self.assertEqual((v["nyt"]["n"], v["nyt"]["toistoja"]), (2, 0))
        self.assertEqual(om.suunta(v["nyt"], v["ed"]), "parempi")

    def test_suunta_huonompi_ja_ei_muutosta(self):
        a = {"n": 4, "toistoja": 2}
        self.assertEqual(om.suunta(a, {"n": 4, "toistoja": 1}), "huonompi")
        self.assertEqual(om.suunta(a, {"n": 2, "toistoja": 1}), "ei muutosta")

    def test_ei_dataa_ei_vaiteta_suuntaa(self):
        self.assertIn("data ei riit", om.suunta({"n": 3, "toistoja": 1}, {"n": 0, "toistoja": 0}))

    def test_ikkunan_rajat(self):
        # täsmälleen 7 pv sitten kuuluu edelliseen viikkoon (alku, loppu], tänään nykyiseen
        v = om.mittari(loki(rivi(7, "uusi"), rivi(0, "uusi2")), NYT)
        self.assertEqual((v["ed"]["n"], v["nyt"]["n"]), (1, 1))

    def test_tarkastajan_luku(self):
        v = om.mittari(loki(rivi(1, "uusi", tarkastaja=True), rivi(2, "x")), NYT)
        self.assertEqual(v["nyt"]["tarkastajan"], 1)


class RiviTesti(unittest.TestCase):
    def test_rivi_sisaltaa_luvut(self):
        teksti = loki(rivi(20, "aikapommi"), rivi(2, "aikapommi"), rivi(1, "x"))
        r = om.rivi(teksti, NYT)
        self.assertTrue(r.startswith("Oppiminen:"))
        self.assertIn("toistoja 1", r)
        self.assertIn("aikapommi x1", r)
        self.assertIn("luokittelematta 1", r)
        self.assertLessEqual(len(r), 300)

    def test_puuttuva_loki(self):
        self.assertIn("ei saatu luettua", om.rivi(None, NYT))

    def test_tyhja_loki(self):
        self.assertIn("data ei riit", om.rivi("# Virheloki\n", NYT))

    def test_main_ilman_tiedostoa_ei_kaadu(self):
        self.assertEqual(om.main(["/ei/ole/olemassa.md"]), 2)


class ViikkoraporttiLiitosTesti(unittest.TestCase):
    TIEDOT = {"paivaa": 7, "tapahtumia": 0, "virheita": 0, "virhekoodit": {}, "ohitettuja": 0, "ohituskoodit": {},
              "kulu_usd": 0.0, "kulu_agentti": {}, "hyvaksymis_pros": None, "paatettyja": 0}

    def test_rivi_mukana_ennen_vihjeita(self):
        t = vr.muodosta(self.TIEDOT, {}, "Oppiminen: testirivi.")
        self.assertIn("Oppiminen: testirivi.", t)
        self.assertLess(t.index("Oppiminen"), t.index("Vihjeet"))

    def test_ilman_riviä_ennallaan(self):
        self.assertNotIn("Oppiminen", vr.muodosta(self.TIEDOT, {}))

    def test_oppimisrivi_lukee_ympariston_polun(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "virheloki.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(loki(rivi(1, "uusi")))
            with mock.patch.dict(os.environ, {"VIRHELOKI": p}):
                self.assertIn("Oppiminen:", vr.oppimisrivi(NYT))
            with mock.patch.dict(os.environ, {"VIRHELOKI": os.path.join(d, "puuttuu.md")}):
                self.assertIsNone(vr.oppimisrivi(NYT))


if __name__ == "__main__":
    unittest.main()
