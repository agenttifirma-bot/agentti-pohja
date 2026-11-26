import datetime
import tempfile
import unittest
from pathlib import Path

from tools import virhemittari as vm

LOKI = """# Virheloki

- 2026-11-01: tekstitykset tulivat videoihin.
- 2026-11-02: Jokin tuntematon virhe ilman syyta.
- 2026-11-03: Claude lupasi ja lopetti; mitaan ei tapahtunut 70 minuuttiin.

## 4.11.2026: git stash kesken testien
- Mita: x
- Saanto: y

## 9.11.2026: tuleva viikko (2)
- Mita: vanha tapaus (juurisyy 1)
"""


def tulos(tila, aika, runko=""):
    return "# Tulos: x\n\n- Tila: %s\n- Aika: %sT10:00+02:00\n\n%s\n" % (tila, aika, runko)


class LokiTesti(unittest.TestCase):
    def test_lukee_rivit_ja_osiot(self):
        m = vm.lue_loki(LOKI)
        self.assertEqual([p.isoformat() for p, _ in m],
                         ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-09"])
        self.assertIn("Saanto: y", m[3][1])

    def test_osion_perassa_luettelomerkinta_on_oma_merkinta(self):
        loki = ("## 10.11.2026 \u2013 otsikko\n- Mit\u00e4: a\n- Miksi: b\n\n"
                "- 11.11.2026 klo 6.50 \u2014 uusi (juurisyy 2)\n  - sisennetty alakohta\n"
                "- 13.11.2026 \u2014 toinen\n")
        m = vm.lue_loki(loki)
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-10", "2026-11-11", "2026-11-13"])
        self.assertNotIn("uusi", m[0][1])
        self.assertIn("sisennetty alakohta", m[1][1])
        self.assertEqual(vm.luokittele_loki(m[0][1]), "?")
        self.assertEqual(vm.luokittele_loki(m[1][1]), "2")

    def test_kenttarivit_pysyvat_osion_sisalla(self):
        m = vm.lue_loki("## 9.11.2026 \u2013 x\n- Mit\u00e4: a\n- Miksi: b\n- S\u00e4\u00e4nt\u00f6: c\n")
        self.assertEqual(len(m), 1)
        self.assertIn("S\u00e4\u00e4nt\u00f6: c", m[0][1])

    def test_vanha_muoto_toimii_viela(self):
        m = vm.lue_loki("- 2026-11-01: a\n- 2026-11-02 klo 10.00: b\n")
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-01", "2026-11-02"])

    def test_luettelorivin_pkvvvv_kulkee_paivamaaramuunnoksen_lapi(self):
        loki = ("- 3.11.2026 klo 6.50 \u2014 ensimm\u00e4inen\n"
                "- 12.11.2026 \u2014 kaksinumeroinen p\u00e4iv\u00e4\n"
                "- 1.12.2026: yksinumeroinen\n")
        m = vm.lue_loki(loki)
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-03", "2026-11-12", "2026-12-01"])
        self.assertTrue(m[0][1].startswith("- 3.11.2026"))

    def test_mahdoton_paivamaara_ohitetaan_eika_kaada(self):
        self.assertIsNone(vm.parse_paiva("31.2.2026"))
        self.assertIsNone(vm.parse_paiva("2026-02-30"))
        m = vm.lue_loki("- 31.2.2026 \u2014 virheellinen\n- 12.11.2026 \u2014 ok\n")
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-12"])

    def test_mahdoton_paivamaara_ei_vuoda_runkoa_edelliseen_merkintaan(self):
        loki = ("- 2026-11-01: ensimm\u00e4inen\n"
                "- 31.2.2026 \u2014 virheellinen\n  virheellisen runkorivi\n"
                "## 30.2.2026 \u2013 mahdoton osio\n- Mit\u00e4: x\n"
                "- 12.11.2026 \u2014 ok\n")
        m = vm.lue_loki(loki)
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-01", "2026-11-12"])
        self.assertNotIn("runkorivi", m[0][1])
        self.assertNotIn("mahdoton", m[1][1])

    def test_luokittelematon_ei_arvaa(self):
        self.assertEqual(vm.luokittele_loki("- 2026-11-02: Jokin tuntematon virhe"), "?")

    def test_saantotaulu_ja_oma_tunniste(self):
        self.assertEqual(vm.luokittele_loki("x tekstitykset y"), "1")
        self.assertEqual(vm.luokittele_loki("tuntematon (juurisyy 3)"), "3")


class AjoTesti(unittest.TestCase):
    def test_kesken_on_aina_luokka_1(self):
        self.assertEqual(vm.luokittele_ajo("KESKEN", "raportti"), "1")
        self.assertEqual(vm.luokittele_ajo("KESKEN", "Todennettu k\u00e4yt\u00f6ss\u00e4: -"), "1")

    def test_epaonnistui_raja_on_4_muuten_luokittelematon(self):
        self.assertEqual(vm.luokittele_ajo("EPAONNISTUI", "aikakatkaisu"), "4")
        self.assertEqual(vm.luokittele_ajo("EPAONNISTUI", "outo"), "?")

    def test_valmis_ei_ole_virhe(self):
        self.assertIsNone(vm.luokittele_ajo("VALMIS", "x"))

    def test_tulos_ilman_aikaa_ohitetaan(self):
        self.assertIsNone(vm.lue_tulos("- Tila: KESKEN\n"))


class LaskeTesti(unittest.TestCase):
    def test_viikkotaulukko_ja_toisto(self):
        nyt = datetime.date(2026, 11, 5)
        tulokset = [tulos("KESKEN", "2026-10-30"), tulos("VALMIS", "2026-11-02"),
                    tulos("EPAONNISTUI", "2026-11-03", "aikakatkaisu")]
        rivit, t = vm.laske(LOKI, tulokset, nyt)
        d = dict(rivit)
        v44, v45 = d[(2026, 44)], d[(2026, 45)]
        self.assertEqual((v44["yht"], v44["loki"], v44["ajot"]), (2, 1, 1))
        self.assertEqual(v44["luokat"]["1"], 2)
        self.assertEqual(v45["luokat"], {"0": 0, "1": 0, "2": 0, "3": 2, "4": 1, "?": 1})
        self.assertEqual(sum(v45["luokat"].values()), v45["yht"])
        self.assertEqual(v44["toisto"], "ei")
        self.assertEqual(t["ajot"], 2)
        self.assertEqual(t["tulostiedostoa"], 3)

    def test_toistuminen_kaksi_ja_kolme_viikkoa(self):
        nyt = datetime.date(2026, 11, 20)
        loki = "- 2026-11-02: tekstitykset\n- 2026-11-09: tekstitykset\n- 2026-11-16: tekstitykset\n"
        rivit, _ = vm.laske(loki, [], nyt)
        self.assertEqual([r["toisto"][:5] for _, r in rivit], ["ei", "kyll\u00e4", "kolma"])

    def test_tyhjat_viikot_mukana(self):
        rivit, _ = vm.laske("- 2026-11-02: tekstitykset\n", [], datetime.date(2026, 11, 20))
        self.assertEqual([v[1] for v, _ in rivit], [45, 46, 47])


class ValmisRikkiTesti(unittest.TestCase):
    TULOS = "# Tulos: %s\n\n- Tila: VALMIS\n- Aika: 2026-11-04T10:00+02:00\n\nTehty.\n"
    RIKKI = "- Tarkastaja: opus\n- Toimii k\u00e4yt\u00f6ss\u00e4: ei\n- Todiste: journalctl: Traceback\n"

    def test_valmis_joka_todettiin_toimimattomaksi_lasketaan(self):
        nyt = datetime.date(2026, 11, 5)
        tulokset = [("2026-11-02-01-a.md", self.TULOS % "a"), ("2026-11-02-02-b.md", self.TULOS % "b")]
        rivit, t = vm.laske("", tulokset, nyt, tarkastukset={"2026-11-02-01-a.md": self.RIKKI,
                                                                "2026-11-02-02-b.md": self.RIKKI.replace(": ei", ": kyll\u00e4")})
        self.assertEqual(t["valmis_rikki"], 1)
        self.assertEqual(sum(r["valmis_rikki"] for _, r in rivit), 1)
        self.assertEqual(sum(r["luokat"]["1"] for _, r in rivit), 1)

    def test_ilman_tarkastuksia_ei_muutosta(self):
        _, t = vm.laske("", [("2026-11-02-01-a.md", self.TULOS % "a")], datetime.date(2026, 11, 5))
        self.assertEqual((t["valmis_rikki"], t["ajot"]), (0, 0))

    def test_osiossa_sarake(self):
        rivit, t = vm.laske("", [("2026-11-02-01-a.md", self.TULOS % "a")], datetime.date(2026, 11, 5),
                            tarkastukset={"2026-11-02-01-a.md": self.RIKKI})
        self.assertIn("VALMIS, my\u00f6hemmin toimimaton", "\n".join(vm.muodosta_osio(rivit, t, datetime.date(2026, 11, 5))))

    def test_main_polku_tiedostonimi_ja_otsikko_eroavat(self):
        """Oikea data: tiedosto 2026-11-02-01-a.md, otsikko '# Tulos: a'. main() ei saa hukata tarkastusta."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tulokset").mkdir()
            (d / "virheloki.md").write_text(LOKI, encoding="utf-8")
            (d / "tulokset" / "2026-11-02-01-a.md").write_text(self.TULOS % "a", encoding="utf-8")
            (d / "tulokset" / "2026-11-02-01-a.tarkastus.md").write_text(self.RIKKI, encoding="utf-8")
            (d / "tulostaulu.md").write_text("# T\n\n## Virhemittari\nvanha\n", encoding="utf-8")
            ulos = d / "ulos.md"
            self.assertEqual(vm.main(["--docs", tmp, "--nyt", "2026-11-05", "--ulos", str(ulos)]), 0)
            osio = ulos.read_text(encoding="utf-8")
            self.assertIn("n\u00e4ist\u00e4 VALMIS: 1)", osio)

    def test_main_tarkastustiedosto_ei_ole_tulos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tulokset").mkdir()
            (d / "virheloki.md").write_text(LOKI, encoding="utf-8")
            (d / "tulokset" / "2026-11-02-01-a.md").write_text(self.TULOS % "a", encoding="utf-8")
            # Tarkastustiedosto, jossa on (virheellisesti) myos Tila-rivi: ei saa laskea omaksi tuloksekseen.
            (d / "tulokset" / "2026-11-02-01-a.tarkastus.md").write_text(self.TULOS % "a" + self.RIKKI, encoding="utf-8")
            (d / "tulostaulu.md").write_text("# T\n\n## Virhemittari\nvanha\n", encoding="utf-8")
            ulos = d / "ulos.md"
            self.assertEqual(vm.main(["--docs", tmp, "--nyt", "2026-11-05", "--ulos", str(ulos)]), 0)
            self.assertIn("1 tulostiedostoa", ulos.read_text(encoding="utf-8"))


class OsioTesti(unittest.TestCase):
    def test_korvaa_vain_osion_rungon(self):
        taulu = "# T\n\n## Muu\na\n\n## Virhemittari (x)\nvanha\n| a |\n\n## Kirjaukset\nb\n"
        uusi = vm.korvaa_osio(taulu, ["UUSI"])
        self.assertEqual(uusi, "# T\n\n## Muu\na\n\n## Virhemittari (x)\n\nUUSI\n\n## Kirjaukset\nb\n")

    def test_puuttuva_osio_nostaa_virheen(self):
        with self.assertRaises(ValueError):
            vm.korvaa_osio("# T\n", ["x"])

    def test_osio_sisaltaa_todennettu_rivin_ja_kaksi_viikkoa(self):
        nyt = datetime.date(2026, 11, 5)
        rivit, t = vm.laske(LOKI, [], nyt)
        osio = "\n".join(vm.muodosta_osio(rivit, t, nyt))
        self.assertIn("Todennettu k\u00e4yt\u00f6ss\u00e4:", osio)
        self.assertIn("44 (", osio)
        self.assertIn("45 (", osio)

    def test_oppimittari_sarake_ja_syyt(self):
        uusi_loki = (LOKI + "\n## 10.11.2026 \u2013 toisto\n- Mit\u00e4: x\n- Juurisyy: 2\n- Vakava: ei\n- Ehk\u00e4isy: ohje\n"
                     "- Toisto: kyll\u00e4 \u2013 ohje ei estanyt, koska sita ei luettu\n"
                     "\n## 11.11.2026 \u2013 toinen\n- Mit\u00e4: y\n- Juurisyy: 4\n- Vakava: ei\n- Ehk\u00e4isy: testi\n- Toisto: ei\n")
        nyt = datetime.date(2026, 11, 12)
        rivit, t = vm.laske(uusi_loki, [], nyt)
        self.assertEqual(dict(rivit)[(2026, 46)]["luokat"]["2"], 1)   # Juurisyy-kentta luokittelee
        self.assertEqual(dict(rivit)[(2026, 46)]["luokat"]["4"], 1)
        oppi = vm.virheopit.toistotilasto(vm.virheopit.jasenna(uusi_loki))
        osio = "\n".join(vm.muodosta_osio(rivit, t, nyt, oppi))
        self.assertIn("Oli jo lokissa (toisto/uusia)", osio)
        self.assertIn("| 1/2 |", osio)
        self.assertIn("- 2026-11-10 (vk 46): ohje ei estanyt, koska sita ei luettu", osio)
        self.assertIn("ei kirjattu", osio)   # vk 44-45: vanhoista ei tiedeta
        vanha = "\n".join(vm.muodosta_osio(rivit, t, nyt))
        self.assertIn("Ei toistoja kirjattu", vanha)

    def test_kirjoita_ja_ulos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tulokset").mkdir()
            (d / "virheloki.md").write_text(LOKI, encoding="utf-8")
            (d / "tulostaulu.md").write_text("# T\n\n## Virhemittari\nvanha\n", encoding="utf-8")
            self.assertEqual(vm.main(["--docs", tmp, "--nyt", "2026-11-05", "--kirjoita"]), 0)
            self.assertIn("| Viikko |", (d / "tulostaulu.md").read_text(encoding="utf-8"))
            self.assertEqual(vm.main(["--docs", str(d / "ei-ole")]), 1)


class KeskenSyyTesti(unittest.TestCase):
    def kesken(self, syy=None, aika="2026-11-03"):
        rivi = "- KESKEN-syy: %s\n" % syy if syy else ""
        return "# Tulos: x\n\n- Tila: KESKEN\n%s- Aika: %sT10:00+02:00\n\nraportti\n" % (rivi, aika)

    def test_virhesyyt_ja_vanha_tulos_ovat_luokka_1(self):
        for syy in ("rivi-puuttuu", "ei-todennettu", "outo-koodi"):
            self.assertEqual(vm.luokittele_ajo("KESKEN", self.kesken(syy)), "1", syy)
        self.assertEqual(vm.luokittele_ajo("KESKEN", self.kesken()), "1")   # vanha tulos ilman syykoodia

    def test_odottavat_eivat_ole_virheita(self):
        for syy in ("odottaa-yhdistamista", "odottaa-kayttoonottoa"):
            self.assertEqual(vm.luokittele_ajo("KESKEN", self.kesken(syy)), "O")

    def test_laske_erottaa_odottavat_omaan_sarakkeeseen(self):
        nyt = datetime.date(2026, 11, 5)
        tulokset = [self.kesken("rivi-puuttuu"), self.kesken("ei-todennettu"), self.kesken(),
                    self.kesken("odottaa-yhdistamista"), self.kesken("odottaa-kayttoonottoa")]
        rivit, t = vm.laske("", tulokset, nyt)
        v45 = dict(rivit)[(2026, 45)]
        self.assertEqual((v45["yht"], v45["ajot"], v45["odottaa"], v45["luokat"]["1"]), (3, 3, 2, 3))
        self.assertEqual(t["ajot"], 3)
        self.assertEqual(t["tulostiedostoa"], 5)
        osio = "\n".join(vm.muodosta_osio(rivit, t, nyt))
        self.assertIn("Odottaa (ei virhe)", osio)
        self.assertIn("| 45 (2.11.\u20138.11.), kesken | 3 | 0 | 3 | 0 | 0 | 2 | 3 |", osio)


class KeskenSyyRunkoTesti(unittest.TestCase):
    def test_rungon_rivi_ei_ratkaise_syyta(self):
        vanha = "# Tulos: x\n\n- Tila: KESKEN\n- Aika: 2026-11-01T10:00\n\nRaportti\n- KESKEN-syy: odottaa-yhdistamista\n"
        self.assertIsNone(vm.lue_kesken_syy(vanha))
        self.assertEqual(vm.luokittele_ajo("KESKEN", vanha), "1")

    def test_otsikon_rivi_ratkaisee(self):
        uusi = "# Tulos: x\n\n- Tila: KESKEN\n- KESKEN-syy: odottaa-yhdistamista\n- Aika: 2026-11-01T10:00\n\nRunko\n"
        self.assertEqual(vm.lue_kesken_syy(uusi), "odottaa-yhdistamista")
        self.assertEqual(vm.luokittele_ajo("KESKEN", uusi), "O")


class LokiOtsikkoTesti(unittest.TestCase):
    LOKI2 = (
        "# Virheloki\n\n"
        "## 5.\u20136.11.2026 \u2013 V\u00e4ite oli v\u00e4\u00e4r\u00e4\n- Mit\u00e4: x\n- Vakavuus: vakava\n\n"
        "## 5.11.2026 klo 14.03 \u2013 V\u00e4\u00e4r\u00e4 palvelu\n- Mit\u00e4: y\n\n"
        "## 6.11.2026 \u2013 Tiivistevertailu\n- Mit\u00e4: z\n- Vakavuus: tavallinen\n"
    )

    def test_valin_otsikko_luetaan(self):
        m = vm.lue_loki(self.LOKI2)
        self.assertEqual([p.isoformat() for p, _ in m], ["2026-11-05", "2026-11-05", "2026-11-06"])
        self.assertEqual(vm.osio_paiva("30.10.\u20132.11.2026 \u2013 x").isoformat(), "2026-10-30")
        self.assertEqual(vm.osio_paiva("5.-6.11.2026: x").isoformat(), "2026-11-05")
        self.assertIsNone(vm.osio_paiva("31.2.2026: mahdoton"))

    def test_vuodenvaihteen_yli_menevan_valin_alku_on_edellista_vuotta(self):
        self.assertEqual(vm.osio_paiva("30.12.\u20132.1.2027 \u2013 x").isoformat(), "2026-12-30")
        self.assertEqual(vm.viikko(vm.osio_paiva("30.12.-2.1.2027: x")), (2026, 53))
        self.assertEqual(vm.osio_paiva("30.11.-2.12.2026: x").isoformat(), "2026-11-30")

    def test_mahdoton_paiva_ja_numeroitu_otsikko_eivat_kaada_laskea(self):
        loki = ("## 1. Yhteenveto\nteksti\n\n## 31.2.2026: mahdoton\nrunko\n\n## 5.11.2026: oikea\n- Mit\u00e4: y\n")
        self.assertEqual([p.isoformat() for p, _ in vm.lue_loki(loki)], ["2026-11-05"])
        rivit, _ = vm.laske(loki, [], datetime.date(2026, 11, 6))
        self.assertEqual([(v, r["loki"]) for v, r in rivit], [((2026, 45), 1)])

    def test_vakavuus_lasketaan_vain_kirjatusta_rivista(self):
        rivit, _ = vm.laske(self.LOKI2, [], datetime.date(2026, 11, 6))
        v45 = dict(rivit)[(2026, 45)]
        self.assertEqual((v45["loki"], v45["vakavia"]), (3, 1))
        osio = "\n".join(vm.muodosta_osio(rivit, {"loki": 3, "ajot": 0, "valmis_rikki": 0, "tulostiedostoa": 0}, datetime.date(2026, 11, 6)))
        self.assertIn("Vakavia (lokissa)", osio)


LOKI_KENTAT = """# Virheloki

- 2026-11-02: tekstitykset. Tapahtui: 2026-11-02 08:00. Havaittu: 2026-11-02 20:00. Havaitsija: Tony. Ehk\u00e4isy: koodi
- 2026-11-03: tekstitykset (juurisyy 1)
  Tapahtui: 3.11.2026 klo 10.00
  Havaittu: 3.11.2026 klo 12.00
  Havaitsija: tarkastaja-agentti
  Ehk\u00e4isy: ohje
- 2026-11-04: tekstitykset (juurisyy 1)
  Tapahtui: 2026-11-04 10:00
  Havaittu: 2026-11-04 10:30
  Havaitsija: testi/CI
  Ehk\u00e4isy: ei viel\u00e4
- 2026-11-05: tekstitykset, ei vakiokentt\u00e4j\u00e4. Ehk\u00e4isy: A-numero lasketaan uudelleen.
- 2026-11-09: tekstitykset (juurisyy 1). Havaitsija: agentti itse. Tapahtui: 2026-11-09 10:00. Havaittu: 2026-11-08 10:00.
"""


class LisamittariTesti(unittest.TestCase):
    def test_kentat_ja_puuttuvat_kentat(self):
        t = [x for _, x in vm.lue_loki(LOKI_KENTAT)]
        self.assertEqual([vm.havaitsija(x) for x in t],
                         ["Tony", "tarkastaja", "testi/CI", "tuntematon", "agentti itse"])
        self.assertEqual([vm.ehkaisy(x) for x in t],
                         ["koodi", "ohje", "ei viel\u00e4", "tuntematon", "tuntematon"])
        self.assertEqual([vm.havaitsemisaika_h(x) for x in t], [12.0, 2.0, 0.5, None, None])

    def test_aika_vaatii_kellonajan(self):
        self.assertIsNone(vm.parse_aika("2026-11-02"))
        self.assertIsNone(vm.parse_aika("2026-13-45 10:00"))
        self.assertEqual(vm.parse_aika("9.11.2026 klo 12.30"), datetime.datetime(2026, 11, 9, 12, 30))

    def test_mediaani(self):
        self.assertIsNone(vm.mediaani([]))
        self.assertEqual(vm.mediaani([5.0, 1.0, 2.0]), 2.0)
        self.assertEqual(vm.mediaani([1.0, 2.0, 3.0, 10.0]), 2.5)

    def test_viikkorivin_lisamittarit(self):
        nyt = datetime.date(2026, 11, 11)
        tehtavat = [datetime.date(2026, 11, 2)] * 4 + [datetime.date(2026, 11, 9)] * 2
        rivit, _ = vm.laske(LOKI_KENTAT, [tulos("KESKEN", "2026-11-03")], nyt, tehtavat)
        d = dict(rivit)
        v45, v46 = d[(2026, 45)], d[(2026, 46)]
        self.assertEqual(v45["mediaani_h"], 2.0)
        self.assertEqual(v45["kuka"], {"Tony": 1, "tarkastaja": 1, "testi/CI": 1, "agentti itse": 0, "tuntematon": 2})
        self.assertEqual((v45["tehtavia"], v45["yht"]), (4, 5))
        self.assertAlmostEqual(v45["per10"], 12.5)
        # luokka 1 toistuu viikoilla 45 ja 46: ehk\u00e4isy lasketaan vain silloin
        self.assertEqual(v45["ehkaisy"], {"koodi": 0, "ohje": 0, "ei viel\u00e4": 0, "tuntematon": 0})
        self.assertEqual(v46["ehkaisy"], {"koodi": 0, "ohje": 0, "ei viel\u00e4": 0, "tuntematon": 1})
        self.assertIsNone(v46["mediaani_h"])  # havaittu ennen tapahtumaa -> ei lasketa
        self.assertEqual(v46["per10"], 5.0)

    def test_toistuneiden_ehkaisy(self):
        loki = ("- 2026-11-02: tekstitykset. Ehk\u00e4isy: koodi\n- 2026-11-03: tekstitykset. Ehk\u00e4isy: ohje\n"
                "- 2026-11-09: tekstitykset. Ehk\u00e4isy: ohje\n- 2026-11-10: tekstitykset (juurisyy 1)\n")
        rivit, _ = vm.laske(loki, [], datetime.date(2026, 11, 11))
        d = dict(rivit)
        self.assertEqual(d[(2026, 45)]["ehkaisy"], {"koodi": 0, "ohje": 0, "ei viel\u00e4": 0, "tuntematon": 0})
        self.assertEqual(d[(2026, 46)]["ehkaisy"], {"koodi": 0, "ohje": 1, "ei viel\u00e4": 0, "tuntematon": 1})

    def test_ilman_tehtavatietoa_per10_on_tuntematon(self):
        rivit, _ = vm.laske(LOKI, [], datetime.date(2026, 11, 5))
        self.assertIsNone(rivit[0][1]["tehtavia"])
        self.assertIsNone(rivit[0][1]["per10"])
        self.assertEqual(vm.luku(None), "tuntematon")
        self.assertEqual(vm.luku(2.25), "2,2")

    def test_lue_tehtavat_ohittaa_muut_tiedostot(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("2026-11-02-01-a.md", "2026-11-09-03-KIIRE-b.md", "README.md", "2026-11-09-x.txt"):
                (Path(tmp) / n).write_text("x", encoding="utf-8")
            self.assertEqual([p.isoformat() for p in vm.lue_tehtavat(tmp)], ["2026-11-02", "2026-11-09"])

    def test_taulukon_sarakkeet_ja_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tulokset").mkdir()
            (d / "tehtavat").mkdir()
            (d / "tehtavat" / "2026-11-02-01-a.md").write_text("x", encoding="utf-8")
            (d / "virheloki.md").write_text(LOKI_KENTAT, encoding="utf-8")
            (d / "tulostaulu.md").write_text("# T\n\n## Virhemittari\nvanha\n", encoding="utf-8")
            self.assertEqual(vm.main(["--docs", tmp, "--nyt", "2026-11-11", "--kirjoita"]), 0)
            teksti = (d / "tulostaulu.md").read_text(encoding="utf-8")
            otsikko = next(r for r in teksti.splitlines() if r.startswith("| Viikko"))
            for osa in ("Havaitsemisaika, mediaani (h)", "Havaitsija: Tony", "Toistuneet: ehk\u00e4isy koodi",
                        "Virheit\u00e4 / 10 teht\u00e4v\u00e4\u00e4"):
                self.assertIn(osa, otsikko)
            rivit = [r for r in teksti.splitlines() if r.startswith("| 4")]
            self.assertTrue(rivit)
            for r in rivit:
                self.assertEqual(r.count("|"), otsikko.count("|"))


class TodennusMahdotonTesti(unittest.TestCase):
    def luokka(self, runko):
        return vm.luokittele_ajo("KESKEN", runko)

    def test_kolme_sanamuotoa_tunnistetaan(self):
        self.assertEqual(self.luokka("Ei todennettu palvelimella (se oli rajattu pois)."), "0")
        self.assertEqual(self.luokka("Todennus ei ollut mahdollinen, koska ajo oli kielletty."), "0")
        self.assertEqual(self.luokka("Ymp\u00e4rist\u00f6 ei salli kirjoitusta isannalle."), "0")

    def test_tavallinen_kesken_pysyy_luokassa_1(self):
        self.assertEqual(self.luokka("Raportti ilman todennusta."), "1")
        self.assertEqual(self.luokka("Ei todennettu k\u00e4yt\u00f6ss\u00e4."), "1")

    def test_kielteinen_tai_lainaus_ei_muuta_luokkaa(self):
        self.assertEqual(self.luokka("Todennus oli mahdollinen ja se ajettiin."), "1")
        self.assertEqual(self.luokka("Ymp\u00e4rist\u00f6 salli ajon."), "1")
        self.assertEqual(self.luokka('Ehdotus: tunnista "todennus ei ollut mahdollinen".'), "1")
        self.assertEqual(self.luokka("Regex `ei todennettu x rajattu pois` on koodia."), "1")
        self.assertEqual(self.luokka("> Todennus ei ollut mahdollinen (lainaus)"), "1")
        self.assertEqual(self.luokka("```\nei todennettu, rajattu pois\n```"), "1")

    def test_vain_kesken_saa_uuden_luokan(self):
        self.assertIsNone(vm.luokittele_ajo("VALMIS", "todennus ei ollut mahdollinen"))
        self.assertEqual(vm.luokittele_ajo("EPAONNISTUI", "todennus ei ollut mahdollinen"), "?")

    def test_oma_sarake_ei_virheisiin_eika_toistoon(self):
        tulokset = [tulos("KESKEN", d, "todennus ei ollut mahdollinen") for d in ("2026-11-02", "2026-11-09")]
        tulokset.append(tulos("KESKEN", "2026-11-09", "ei todennusta"))
        rivit, tilasto = vm.laske("# Virheloki\n", tulokset, datetime.date(2026, 11, 12))
        v = dict(rivit)
        self.assertEqual(v[(2026, 45)]["ajot"], 1)
        self.assertEqual(v[(2026, 45)]["yht"], 0)
        self.assertEqual(v[(2026, 45)]["luokat"]["0"], 1)
        self.assertEqual(v[(2026, 45)]["luokat"]["1"], 0)
        self.assertEqual(v[(2026, 45)]["kuka"][vm.TUNTEMATON], 0)
        self.assertEqual(v[(2026, 46)]["yht"], 1)
        self.assertEqual(v[(2026, 46)]["ajot"], 2)
        self.assertEqual(v[(2026, 46)]["luokat"]["0"], 1)
        self.assertEqual(v[(2026, 46)]["toisto"], "ei")
        osio = "\n".join(vm.muodosta_osio(rivit, tilasto, datetime.date(2026, 11, 12)))
        self.assertIn("KESKEN: todennus mahdoton", osio)


class AsciiTesti(unittest.TestCase):
    def test_koodi_on_ascii(self):
        for p in (Path(vm.__file__), Path(__file__)):
            p.read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
