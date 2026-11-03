import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone

from agentti import talonmies as t

NYT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
PVM = "2026-11-02"
ISANTA = """## Kontit (pct list)
VMID Status Lock Name
115 running agentscope

## Viimeisimmat varmuuskopiot
total 12
-rw-r--r-- 1 root root 1234 Nov  2 03:00 vzdump-lxc-115-2026_11_02-03_00_01.tar.zst
-rw-r--r-- 1 root root  100 Nov  2 03:00 vzdump-lxc-115-2026_11_02-03_00_01.log
-rw-r--r-- 1 root root 1234 Oct 30 03:00 vzdump-lxc-115-2026_10_30-03_00_01.tar.zst

## CT116 epaonnistuneet palvelut
foo.service loaded failed failed Foo

## CT117 epaonnistuneet palvelut
(ei epaonnistuneita palveluita)
"""


def tekoinen(vastaukset):
    kutsut = []

    def suorita(komento, **kw):
        kutsut.append(list(komento))
        return subprocess.CompletedProcess(komento, 0, stdout=vastaukset.get(komento[0], ""), stderr="")
    suorita.kutsut = kutsut
    return suorita


class AnalyysiTesti(unittest.TestCase):
    def test_kaatunut_palvelu_ja_kohina(self):
        teksti = "* foo.service loaded failed failed Foo\n  tmp.mount loaded failed failed Tmp\n"
        e = t.ehdota_kaatuneet(teksti, PVM)
        self.assertEqual([x["kohde"] for x in e], ["foo.service"])
        self.assertEqual(e[0]["taso"], "A")

    def test_levy_rajat(self):
        df = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 100 %d 10 %d%% /\n"
        self.assertEqual(t.ehdota_levy(df % (79, 79), PVM), [])
        self.assertEqual(t.ehdota_levy(df % (80, 80), PVM)[0]["taso"], "A")
        self.assertEqual(t.ehdota_levy(df % (95, 95), PVM)[0]["taso"], "C")

    def test_varmuuskopio_tuore_ja_vanha(self):
        self.assertAlmostEqual(t.uusin_varmuuskopio_ika(ISANTA, NYT), 9.0, places=1)
        vanha = ISANTA.replace("Nov  2 03:00 vzdump-lxc-115-2026_11_02", "Oct 20 03:00 vzdump-lxc-115-2026_11_02")
        e = t.ehdota_varmuuskopiot(vanha, PVM, NYT, date(2026, 10, 25))
        self.assertEqual([x["toimenpide"] for x in e], ["varmuuskopio-tuoreus"])
        self.assertEqual(t.ehdota_varmuuskopiot(ISANTA, PVM, NYT, date(2026, 10, 25)), [])

    def test_loki_ei_lasketa_varmuuskopioksi_ja_tyhja_halyttaa(self):
        vain_loki = "## Viimeisimmat varmuuskopiot\n-rw-r--r-- 1 root root 1 Nov  2 03:00 vzdump-x.log\n"
        self.assertIsNone(t.uusin_varmuuskopio_ika(vain_loki, NYT))
        e = t.ehdota_varmuuskopiot(vain_loki, PVM, NYT, date(2026, 10, 25))
        self.assertEqual(e[0]["toimenpide"], "varmuuskopio-tuoreus")

    def test_isanta_puuttuu_ja_palautustesti_vanha(self):
        e = t.ehdota_varmuuskopiot(None, PVM, NYT, None)
        self.assertEqual({x["toimenpide"] for x in e}, {"varmuuskopio-tuoreus", "palautustesti"})

    def test_paivitykset(self):
        apt = ("Listing...\nlibssl3/stable-security 3.5 amd64 [upgradable from: 3.4]\n"
               "bash/stable 5.2 amd64 [upgradable from: 5.1]\n")
        e = {x["toimenpide"]: x for x in t.ehdota_paivitykset(apt, PVM)}
        self.assertEqual(e["tietoturvapaivitys"]["taso"], "B")
        self.assertIn("libssl3", e["tietoturvapaivitys"]["syy"])
        self.assertEqual(e["muut-paivitykset"]["taso"], "C")
        self.assertEqual(t.ehdota_paivitykset("Listing...\n", PVM), [])


class AjoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tila = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.suorita = tekoinen({
            "systemctl": "* a.service loaded failed failed A\n",
            "df": "F 1 2 3 Capacity M\n/dev/x 100 85 15 85% /\n",
            "apt": "Listing...\n"})

    def aja(self, isanta=ISANTA):
        return t.ajo(self.tila, NYT, self.suorita, lambda: isanta)

    def test_ajo_kirjoittaa_raportin_ja_kirjanpidon_ei_tuplaa(self):
        teksti, ehd = self.aja()
        kohteet = {e["kohde"] for e in ehd}
        self.assertIn("a.service", kohteet)
        self.assertIn("ct116:foo.service", kohteet)
        self.assertIn("/", kohteet)
        self.assertTrue(os.path.exists(os.path.join(self.tila, "raportit", PVM + ".md")))
        n = len(t._lue_jsonl(os.path.join(self.tila, t.EHDOTUKSET)))
        self.aja()
        self.assertEqual(len(t._lue_jsonl(os.path.join(self.tila, t.EHDOTUKSET))), n)
        self.assertIn("mit\u00e4\u00e4n ei ole tehty", teksti)

    def test_vain_kiinteat_vain_luku_komennot(self):
        self.aja()
        sallitut = [k for k in t.KOMENNOT.values()]
        for k in self.suorita.kutsut:
            self.assertIn(k, sallitut)
        for k in sallitut:
            self.assertNotIn(k[0], ("rm", "kill", "reboot", "sudo"))
            self.assertFalse({"restart", "start", "stop", "install", "upgrade", "remove"} & set(k[1:2]))

    def test_pysaytystiedosto_estaa_kaiken(self):
        open(os.path.join(self.tila, t.PYSAYTUS), "w").close()
        teksti, ehd = self.aja()
        self.assertEqual(ehd, [])
        self.assertEqual(self.suorita.kutsut, [])
        self.assertFalse(os.path.exists(os.path.join(self.tila, "raportit")))

    def test_isannan_virhe_ei_kaada_ajoa(self):
        def rikki():
            raise RuntimeError("salainen-viesti")
        teksti, ehd = t.ajo(self.tila, NYT, self.suorita, rikki)
        self.assertIn("RuntimeError", teksti)
        self.assertNotIn("salainen-viesti", teksti)


class KirjanpitoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tila = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.ids = []
        for i in range(4):
            pvm = "2026-11-%02d" % (i + 1)
            e = t.ehdotus(pvm, "kaatunut-palvelu", "x.service", "s", "e", taso="A")
            t._liita(os.path.join(self.tila, t.EHDOTUKSET), e)
            self.ids.append(e["tunniste"])

    def test_paatokset_ja_osuus(self):
        t.paata(self.tila, self.ids[0], "kylla")
        t.paata(self.tila, self.ids[1], "kylla")
        t.paata(self.tila, self.ids[2], "ei", "ei tarpeen\nrivi")
        m = t.mittari(self.tila)["kaatunut-palvelu"]
        self.assertEqual((m["ehdotettu"], m["kylla"], m["ei"], m["vastaamatta"]), (4, 2, 1, 1))
        self.assertAlmostEqual(m["osuus"], 0.667, places=3)
        self.assertFalse(m["kypsa"])    # raja puuttuu: Tony paattaa

    def test_myohempi_paatos_korvaa_ja_kypsyys_vaatii_maaran(self):
        t.paata(self.tila, self.ids[0], "ei")
        t.paata(self.tila, self.ids[0], "kylla")
        for i in (1, 2, 3):
            t.paata(self.tila, self.ids[i], "kylla")
        m = t.mittari(self.tila, raja=0.8, vahintaan=10)["kaatunut-palvelu"]
        self.assertEqual(m["osuus"], 1.0)
        self.assertFalse(m["kypsa"])    # vain 4 paatosta
        self.assertTrue(t.mittari(self.tila, raja=0.8, vahintaan=4)["kaatunut-palvelu"]["kypsa"])

    def test_virheelliset_paatokset(self):
        for tunn, v in (("../x", "kylla"), (self.ids[0], "ehka"), ("20261101-tuntematon-abcdef", "kylla")):
            with self.assertRaises(t.TalonmiesVirhe):
                t.paata(self.tila, tunn, v)


if __name__ == "__main__":
    unittest.main()
