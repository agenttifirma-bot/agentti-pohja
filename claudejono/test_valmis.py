import unittest

from claudejono import valmis

TULOS = "# Tulos: a.md\n\n- Tila: VALMIS\n- Aika: 2026-11-05T10:00+02:00\n- Malli: sonnet\n\nTehty.\n"
OK = "- Tarkastaja: opus\n- Toimii k\u00e4yt\u00f6ss\u00e4: kyll\u00e4\n- Todiste: https://example.invalid/log#L12\n"


class Valmis(unittest.TestCase):
    def test_kelvollinen(self):
        self.assertTrue(valmis.kelvollinen(TULOS, OK))
        self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, OK), "VALMIS")

    def test_puuttuva_tai_vajaa_merkinta_on_kesken(self):
        for teksti in (None, "", "- Tarkastaja: opus\n- Toimii k\u00e4yt\u00f6ss\u00e4: kyll\u00e4\n",
                       OK.replace("opus", "sonnet"),          # sama malli kuin tuloksessa
                       OK.replace("kyll\u00e4", "ei"),
                       OK.replace("https://example.invalid/log#L12", "-"),
                       "- Toimii k\u00e4yt\u00f6ss\u00e4: kyll\u00e4\n- Todiste: loki\n"):   # tarkastaja puuttuu
            self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, teksti), "KESKEN", teksti)

    def test_muut_tilat_ennallaan(self):
        for tila in ("KESKEN", "EPAONNISTUI", "HYLATTY"):
            self.assertEqual(valmis.tehokas_tila(tila, TULOS, None), tila)

    def test_toimimaton(self):
        self.assertTrue(valmis.toimimaton(OK.replace("kyll\u00e4", "ei")))
        self.assertFalse(valmis.toimimaton(OK))
        self.assertFalse(valmis.toimimaton("- Toimii k\u00e4yt\u00f6ss\u00e4: ei\n"))   # ilman todistetta ei lasketa

    def test_malliperhe_normalisoi_nimimuodot(self):
        for nimi in ("opus", "Opus", "claude-opus-5-5", "anthropic/claude-opus-5-5", "opus-istunto-7", "`opus`"):
            self.assertEqual(valmis.malliperhe(nimi), "opus", nimi)
        for nimi in ("", None, "-", "5-5", "  "):
            self.assertEqual(valmis.malliperhe(nimi), "", nimi)

    def test_puuttuva_malli_on_epavarma(self):
        self.assertFalse(valmis.kelvollinen("# Tulos: a\n\n- Tila: VALMIS\n", OK))
        self.assertFalse(valmis.kelvollinen("# Tulos: a\n\n- Malli: -\n", OK))

    def test_eri_muotoinen_sama_malli_ei_ole_riippumaton(self):
        tulos = TULOS.replace("sonnet", "claude-opus-5-5")
        self.assertFalse(valmis.kelvollinen(tulos, OK))   # tarkastaja 'opus'
        self.assertTrue(valmis.kelvollinen(tulos, OK.replace("opus", "claude-sonnet-5-5")))

    def test_malliperhe_valilyonnilliset_ja_muut_erottimet(self):
        # Tarkastajan katselmointi 21.11.2026: 'Claude Opus 5.5' normalisoitui aiemmin muotoon 'claude'.
        for nimi in ("Claude Opus 5.5", "claude opus", "Claude  Opus 5.5", "claude_opus_5_5", "Anthropic/Claude Opus 5.5",
                     "claude-3-opus", "CLAUDE-OPUS-5-5"):
            self.assertEqual(valmis.malliperhe(nimi), "opus", nimi)
        self.assertEqual(valmis.malliperhe("Claude Sonnet 5.5"), "sonnet")
        self.assertEqual(valmis.malliperhe("claude-3-5-sonnet"), "sonnet")
        for nimi in ("claude", "Claude 5.5", "anthropic/claude"):   # pelkk\u00e4 valmistaja tai versio ei kerro mallia
            self.assertEqual(valmis.malliperhe(nimi), "", nimi)

    def test_sama_malli_valilyonnillisena_ei_ole_riippumaton(self):
        tulos = TULOS.replace("sonnet", "claude-opus-5-5")
        self.assertFalse(valmis.kelvollinen(tulos, OK.replace("opus", "Claude Opus 5.5")))

    def test_eri_malli_valilyonnillisena_on_riippumaton(self):
        tulos = TULOS.replace("sonnet", "Claude Sonnet")
        self.assertTrue(valmis.kelvollinen(tulos, OK.replace("opus", "Claude Opus")))

    def test_malliperhe_tunnistamaton_nimi_on_epavarma(self):
        # Tarkastajan katselmoinnit 22.-23.11.2026: ensimmainen kirjaintoken hyvaksyttiin perheeksi, vaikka se ei ollut mallin nimi.
        for nimi in ("istunto-7", "tarkastaja", "min\u00e4", "Claude Code", "claude-agent-sdk", "code", "gpt-5",
                     "riippumaton tarkastaja", "ClaudeOpus", "opusx", "op us"):
            self.assertEqual(valmis.malliperhe(nimi), "", nimi)

    def test_malliperhe_tunnettu_perhe_loytyy_muun_tekstin_seasta(self):
        for nimi in ("Claude Code (Opus 5.5)", "riippumaton tarkastaja (opus)", "tarkastaja opus", "istunto 7 opus",
                     "OPUS", "opus5", "opus@v2", "claude-opus-5-5:thinking", "claude-opus-4-1-20250805",
                     "openrouter/anthropic/claude-opus-5-5:beta", "claude-opus-5-5-latest", "\topus\n"):
            self.assertEqual(valmis.malliperhe(nimi), "opus", nimi)
        self.assertEqual(valmis.malliperhe("Claude Code (Sonnet 5.5)"), "sonnet")
        self.assertEqual(valmis.malliperhe("claude-haiku-5-5"), "haiku")
        self.assertEqual(valmis.malliperhe("claude-fable-5-1"), "fable")

    def test_malliperhe_useampi_perhe_tai_kielto_on_epavarma(self):
        for nimi in ("opus/sonnet", "claude-opus-5-5 ja sonnet", "Sonnet vs Opus", "haiku, opus",
                     "ei opus", "not opus", "non-opus", "ei sonnet vaan opus", "anthropic/claude-sonnet-5-5/opus"):
            self.assertEqual(valmis.malliperhe(nimi), "", nimi)

    def test_tunnistamaton_tarkastaja_ei_ole_riippumaton(self):
        for nimi in ("istunto-7", "tarkastaja", "min\u00e4", "Claude Code", "claude-agent-sdk", "gpt-5", "opus/sonnet", "ei opus"):
            self.assertFalse(valmis.kelvollinen(TULOS, OK.replace("opus", nimi)), nimi)
            self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, OK.replace("opus", nimi)), "KESKEN", nimi)

    def test_sama_malli_epastandardina_nimena_ei_ole_riippumaton(self):
        tulos = TULOS.replace("sonnet", "claude-opus-5-5")
        for nimi in ("Claude Code (Opus 5.5)", "riippumaton tarkastaja (opus)", "istunto 7 opus", "claude-opus-5-5:thinking",
                     "openrouter/anthropic/claude-opus-5-5", "OPUS", "opus5"):
            self.assertFalse(valmis.kelvollinen(tulos, OK.replace("opus", nimi)), nimi)

    def test_eri_malli_epastandardina_nimena_on_riippumaton(self):
        self.assertTrue(valmis.kelvollinen(TULOS, OK.replace("opus", "Claude Code (Opus 5.5)")))
        self.assertTrue(valmis.kelvollinen(TULOS.replace("sonnet", "claude-opus-5-5"), OK.replace("opus", "claude-sonnet-5-5:beta")))

    def test_tunnistamaton_tekija_ei_ole_riippumaton(self):
        for malli in ("Claude Code", "istunto-7", "opus/sonnet"):
            self.assertFalse(valmis.kelvollinen(TULOS.replace("sonnet", malli), OK), malli)

    def test_kylla_ei_hyvaksy_sanaa_on(self):
        # Tarkastajan katselmointi 23.11.2026: 'on rikki' luettiin kylla-vastaukseksi.
        for arvo in ("on rikki", "on", "On toimimaton"):
            teksti = OK.replace("kyll\u00e4", arvo)
            self.assertIsNot(valmis.lue(teksti)["toimii"], True, arvo)
            self.assertEqual(valmis.tehokas_tila("VALMIS", TULOS, teksti), "KESKEN", arvo)
        for arvo in ("kyll\u00e4", "Kylla", "ok"):
            self.assertTrue(valmis.kelvollinen(TULOS, OK.replace("kyll\u00e4", arvo)), arvo)

    def test_tulostiedostot_ohittaa_tarkastukset(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.md", "a.tarkastus.md", "b.md", "c.txt"):
                (Path(d) / n).write_text("x", encoding="utf-8")
            self.assertEqual([p.name for p in valmis.tulostiedostot(d)], ["a.md", "b.md"])
        self.assertTrue(valmis.on_tarkastustiedosto("a.tarkastus.md"))
        self.assertFalse(valmis.on_tarkastustiedosto("a.md"))

    def test_polku(self):
        self.assertEqual(valmis.tarkastuspolku("/x", "2026-11-05-17.md").name, "2026-11-05-17.tarkastus.md")


if __name__ == "__main__":
    unittest.main()
