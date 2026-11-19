"""aivo_arvio osumat --luokittain ja miksi-kirjaus. Synteettinen data tilapaishakemistossa, ei oikeaa arviotiedostoa."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from claudejono import aivo_arvio


def rivi(laji, tehtava, kylla=None, **muu):
    d = {"aika": "2026-11-10T08:00:00+00:00", "laji": laji, "tehtava": tehtava, **muu}
    if kylla is not None:
        d["kylla"] = kylla
    return json.dumps(d)


def aja(argv, rivit):
    with tempfile.TemporaryDirectory() as hak:
        p = Path(hak) / "a.jsonl"
        p.write_text("\n".join(rivit) + "\n", encoding="utf-8")
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = aivo_arvio.main(["osumat", "--polku", str(p)] + argv)
        return rc, o.getvalue(), e.getvalue()


def taulurivi(ulos, nayttonimi):
    return [r for r in ulos.splitlines() if r.startswith(f"| {nayttonimi} |")]


class LuokkaNimesta(unittest.TestCase):
    def test_paivays_ja_tavoite(self):
        self.assertEqual(aivo_arvio.luokka_nimesta("2026-11-18-aivo-osumat.md"), "aivo")
        self.assertEqual(aivo_arvio.luokka_nimesta("2026-11-18-yllapito_x.md"), "yllapito")
        self.assertEqual(aivo_arvio.luokka_nimesta("portfolio.md"), "portfolio")

    def test_muu_sana_tuntematon(self):
        for n in ("2026-11-18-korjaa-aivo.md", "salainen-nimi.md", "", None, "2026-11-18-.md"):
            self.assertEqual(aivo_arvio.luokka_nimesta(n), "tuntematon", n)


class Luokittain(unittest.TestCase):
    RIVIT = [
        rivi("aivo", "2026-11-01-x1.md", True, luokka="aivo", tulos="VALMIS"),
        rivi("aivo", "2026-11-01-x2.md", True, luokka="aivo", tulos="HYLATTY"),
        rivi("aivo", "2026-11-01-x3.md", False, luokka="aivo", tulos="HYLATTY"),
        rivi("aivo", "2026-11-01-x4.md", True, luokka="aivo"),
        rivi("aivo", "2026-11-01-portfolio-salainen.md", True, tulos="VALMIS"),
        rivi("aivo", "2026-11-01-y1.md", False, luokka="ansainta", tulos="EPAONNISTUI"),
        rivi("aivo", "2026-11-01-salainennimi.md", True, tulos="KESKEN"),
        rivi("miksi", "2026-11-01-x2.md", miksi="testit puuttuivat"),
    ]

    def test_luvut_luokittain(self):
        l = aivo_arvio.laske_osumat(self.RIVIT)
        self.assertEqual(l["luokat"]["aivo"], {"arvioita": 4, "vertailtavia": 3, "osumia": 2, "vaaria": 1,
                                               "miksi_kirjattu": 1, "prosentti": 66.7})
        self.assertEqual(l["luokat"]["portfolio"]["prosentti"], 100.0)
        self.assertEqual(l["luokat"]["ansainta"]["vertailtavia"], 0)
        self.assertIsNone(l["luokat"]["ansainta"]["prosentti"])
        self.assertEqual(l["luokat"]["tuntematon"]["vaaria"], 1)
        self.assertEqual(l["luokat"]["tuntematon"]["miksi_kirjattu"], 0)
        self.assertEqual((l["arvioita"], l["vertailtavia"], l["osumia"]), (7, 5, 3))

    def test_miksi_rivi_ei_muuta_kokonaislukuja(self):
        ilman = aivo_arvio.laske_osumat(self.RIVIT[:-1])
        kanssa = aivo_arvio.laske_osumat(self.RIVIT)
        for k in ("arvioita", "vertailtavia", "osumia", "prosentti", "rikkinaisia"):
            self.assertEqual(ilman[k], kanssa[k], k)

    def test_tuoreempi_luokka_korvaa(self):
        l = aivo_arvio.laske_osumat([rivi("aivo", "a", True, luokka="aivo"), rivi("aivo", "a", True, luokka="portfolio")])
        self.assertEqual(list(l["luokat"]), ["portfolio"])

    def test_kelvoton_luokka_nimesta(self):
        l = aivo_arvio.laske_osumat([rivi("aivo", "2026-11-01-ansainta-z.md", True, luokka="hassu"),
                                     rivi("aivo", "b", True, luokka=5)])
        self.assertEqual(sorted(l["luokat"]), ["ansainta", "tuntematon"])

    def test_tuloste_ei_nimia_eika_selityksia(self):
        rc, ulos, _ = aja(["--luokittain"], self.RIVIT)
        self.assertEqual(rc, 0)
        for kielletty in ("salainen", "x1", "x2", "testit puuttuivat", ".md"):
            self.assertNotIn(kielletty, ulos)
        self.assertEqual(taulurivi(ulos, "Aivo"), ["| Aivo | 4 | 3 | 2 | 66.7 % | 1 (1) | ei |"])
        self.assertEqual(taulurivi(ulos, "ansainta"), ["| ansainta | 1 | 0 | 0 | - | 0 (0) | ei |"])
        self.assertIn("raja: v\xe4hint\xe4\xe4n 90 % ja 100 vertailtavaa", ulos)

    def test_ilman_valintaa_ei_taulukkoa(self):
        _, ulos, _ = aja([], self.RIVIT)
        self.assertNotIn("Luokittain", ulos)
        self.assertIn("Vertailtavia: 5, osumia: 3", ulos)

    def test_raja_taynna_reunoilla(self):
        rivit = [rivi("aivo", f"t{i}", True, luokka="aivo", tulos="VALMIS") for i in range(9)]
        rivit.append(rivi("aivo", "t9", True, luokka="aivo", tulos="HYLATTY"))   # 9/10 = 90.0 %
        _, ulos, _ = aja(["--luokittain", "--raja-prosentti", "90", "--raja-vertailtavat", "10"], rivit)
        self.assertEqual(taulurivi(ulos, "Aivo"), ["| Aivo | 10 | 10 | 9 | 90.0 % | 1 (0) | kyll\xe4 |"])
        _, ulos, _ = aja(["--luokittain", "--raja-prosentti", "90.1", "--raja-vertailtavat", "10"], rivit)
        self.assertTrue(taulurivi(ulos, "Aivo")[0].endswith("| ei |"))
        _, ulos, _ = aja(["--luokittain", "--raja-prosentti", "90", "--raja-vertailtavat", "11"], rivit)
        self.assertTrue(taulurivi(ulos, "Aivo")[0].endswith("| ei |"))

    def test_oletusrajalla_sata_tayttaa(self):
        rivit = [rivi("aivo", f"t{i}", True, luokka="yllapito", tulos="VALMIS") for i in range(100)]
        _, ulos, _ = aja(["--luokittain"], rivit)
        self.assertTrue(taulurivi(ulos, "yll\xe4pito")[0].endswith("| kyll\xe4 |"))
        _, ulos, _ = aja(["--luokittain"], rivit[:99])
        self.assertTrue(taulurivi(ulos, "yll\xe4pito")[0].endswith("| ei |"))

    def test_jarjestys_ja_tyhja(self):
        _, ulos, _ = aja(["--luokittain"], [rivi("aivo", "zz", True), rivi("aivo", "a", True, luokka="aivo"),
                                            rivi("aivo", "b", True, luokka="portfolio")])
        luokat = [r.split("|")[1].strip() for r in ulos.splitlines() if r.startswith("| ") and "Luokka" not in r]
        self.assertEqual(luokat, ["TO-paikka/portfolio", "Aivo", "tuntematon"])
        _, ulos, _ = aja(["--luokittain"], [])
        self.assertIn("| - | 0 | 0 | 0 | - | 0 (0) | ei |", ulos)


class Kirjaus(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tila = self._t.name

    def tearDown(self):
        self._t.cleanup()

    def rivit(self):
        return [json.loads(r) for r in (Path(self.tila) / aivo_arvio.TIEDOSTO).read_text().splitlines()]

    def test_arvioi_varjossa_kirjaa_luokan(self):
        p = Path(self.tila) / "2026-11-18-x.md"
        p.write_text("# x\nTavoite: Aivo\n", encoding="utf-8")
        self.assertTrue(aivo_arvio.arvioi_varjossa(self.tila, p, lambda t: (True, "s")))
        self.assertEqual(self.rivit()[0]["luokka"], "aivo")

    def test_ilman_tavoiterivia_ei_luokkaa(self):
        p = Path(self.tila) / "x.md"
        p.write_text("Tavoite: jokin muu\n", encoding="utf-8")
        aivo_arvio.arvioi_varjossa(self.tila, p, lambda t: (False, "s"))
        self.assertNotIn("luokka", self.rivit()[0])

    def miksi(self, *argv):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = aivo_arvio.main(["--tila", self.tila, "miksi", *argv])
        return rc, o.getvalue(), e.getvalue()

    def test_miksi_vaaralle_ennusteelle(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "s")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "HYLATTY")
        rc, ulos, _ = self.miksi("a.md", "rivi1\nrivi2\t" + "x" * 500)
        self.assertEqual(rc, 0)
        d = self.rivit()[-1]
        self.assertEqual((d["laji"], d["tehtava"]), ("miksi", "a.md"))
        self.assertTrue(d["miksi"].startswith("rivi1 rivi2 x"))
        self.assertEqual(len(d["miksi"]), 200)
        self.assertNotIn("\n", d["miksi"])
        l = aivo_arvio.laske_osumat((Path(self.tila) / aivo_arvio.TIEDOSTO).read_text().splitlines())
        self.assertEqual(l["luokat"]["tuntematon"]["miksi_kirjattu"], 1)

    def test_tonyn_tuomio_tekee_vaaraksi(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "s")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS")
        aivo_arvio.tarkista(self.tila, "a.md", False)
        self.assertEqual(self.miksi("a.md", "syy")[0], 0)

    def test_miksi_hylataan(self):
        aivo_arvio.kirjaa_arvio(self.tila, "oikea.md", True, "s")
        aivo_arvio.kirjaa_tulos(self.tila, "oikea.md", "VALMIS")
        aivo_arvio.kirjaa_arvio(self.tila, "auki.md", True, "s")
        aivo_arvio.kirjaa_arvio(self.tila, "kaatui.md", True, "s")
        aivo_arvio.kirjaa_tulos(self.tila, "kaatui.md", "EPAONNISTUI")
        aivo_arvio.kirjaa_arvio(self.tila, "v.md", True, "s")
        aivo_arvio.kirjaa_tulos(self.tila, "v.md", "KESKEN")
        n = len(self.rivit())
        for nimi, teksti in (("oikea.md", "x"), ("auki.md", "x"), ("kaatui.md", "x"), ("puuttuu.md", "x"), ("v.md", " \n\t ")):
            rc, _, e = self.miksi(nimi, teksti)
            self.assertEqual(rc, 1, nimi)
            self.assertTrue(e.startswith("virhe: "), nimi)
        self.assertEqual(len(self.rivit()), n)

    def test_ilman_aivon_arviota_keyerror(self):
        # tulosrivi ilman Aivon arviota (kasin kirjoitettu) ei kelpaa selitykselle
        with open(Path(self.tila) / aivo_arvio.TIEDOSTO, "a") as f:
            f.write(rivi("tulos", "orpo.md", tulos="HYLATTY") + "\n")
        with self.assertRaises(KeyError):
            aivo_arvio.kirjaa_miksi(self.tila, "orpo.md", "syy")

    def test_lukukelvoton_tilatiedosto_ei_kaada(self):
        # tiedosto ei ole luettavissa (OSError): selkea virhe ja paluukoodi 1, ei tracebackia
        for tyyppi in (PermissionError, OSError):
            with mock.patch.object(aivo_arvio, "lue", side_effect=tyyppi("salainen/polku")):
                rc, ulos, e = self.miksi("a.md", "syy")
            self.assertEqual(rc, 1)
            self.assertEqual(ulos, "")
            self.assertTrue(e.startswith("virhe: "))
            self.assertIn(tyyppi.__name__, e)
            self.assertNotIn("salainen", e)
            self.assertNotIn("Traceback", e)

    def test_puuttuva_arviotiedosto_osumat(self):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = aivo_arvio.main(["osumat", "--luokittain", "--polku", str(Path(self.tila) / "ei-ole.jsonl")])
        self.assertEqual((rc, o.getvalue()), (1, ""))
        self.assertTrue(e.getvalue().startswith("virhe: "))
        self.assertNotIn("Traceback", e.getvalue())


if __name__ == "__main__":
    unittest.main()
