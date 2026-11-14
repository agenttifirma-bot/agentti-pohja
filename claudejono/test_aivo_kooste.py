import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from claudejono import ajuri, aivo_arvio

SALAINEN_SYY = "SALAINENSYYMERKKIJONO"
SALAINEN_NIMI = "SALAINENTEHTAVANIMI"


def aika(pv):
    return datetime(2026, 11, pv, 12, 0, tzinfo=timezone.utc)


class Pohja(unittest.TestCase):
    def setUp(self):
        self.tila = Path(tempfile.mkdtemp())
        self.tulokset = self.tila / "tulokset"
        self.tulokset.mkdir()

    def arvio(self, nimi, kylla, pv=10, tony=None, malli=None):
        aivo_arvio.kirjaa_arvio(self.tila, nimi, kylla, SALAINEN_SYY, aika(pv))
        if malli:   # malli on valinnainen kentta; kirjaa_arvio ei viela kirjoita sita
            rivit = (self.tila / aivo_arvio.TIEDOSTO).read_text().splitlines()
            d = json.loads(rivit[-1])
            d["malli"] = malli
            rivit[-1] = json.dumps(d)
            (self.tila / aivo_arvio.TIEDOSTO).write_text("\n".join(rivit) + "\n")
        if tony is not None:
            aivo_arvio.tarkista(self.tila, nimi, tony, aika(pv))

    def tulos(self, nimi, tila):
        (self.tulokset / nimi).write_text(f"# Tulos: {nimi}\n\n- Tila: {tila}\n- Aika: x\n\nteksti\n")

    def taydenna(self, n, kylla=True, pv=10, alku=0):
        for i in range(alku, alku + n):
            self.arvio(f"t{pv}-{i}-{'k' if kylla else 'e'}.md", kylla, pv)

    def kooste(self):
        return json.loads((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text())


class Sisalto(Pohja):
    def test_ei_syyta_eika_tehtavan_nimea(self):
        self.arvio(SALAINEN_NIMI + ".md", True)
        self.taydenna(12, True, alku=100)
        self.taydenna(12, False, pv=11)
        aivo_arvio.kirjoita_kooste(self.tila, self.tulokset)
        teksti = (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text()
        self.assertNotIn(SALAINEN_SYY, teksti)
        self.assertNotIn(SALAINEN_NIMI, teksti)
        self.assertNotIn("t10-", teksti)
        for avain in ("syy", "tehtava"):
            self.assertNotIn(f'"{avain}"', teksti)

    def test_luvut(self):
        self.taydenna(12, True, pv=10)
        self.taydenna(7, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (19, 12, 7))
        self.assertEqual(k["paivittain"], {"2026-11-10": 12, "2026-11-11": 7})
        self.assertEqual((k["ensimmainen_paiva"], k["viimeinen_paiva"]), ("2026-11-10", "2026-11-11"))
        self.assertFalse(k["lahtotasoon_riittavasti_arvioita"])
        self.taydenna(1, True, alku=500)
        self.assertTrue(aivo_arvio.laske_kooste(self.tila)["lahtotasoon_riittavasti_arvioita"])

    def test_mallijakauma(self):
        for i in range(6):
            self.arvio(f"a{i}.md", True, malli="sonnet")
        self.arvio("b0.md", True, malli="opus")
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["mallit"], {"opus": "<5", "sonnet": 6})

    def test_tyhja_tila(self):
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["arvioita_yhteensa"], "<5")
        self.assertIsNone(k["yhtenevyys_tonyn_kanssa_prosenttia"])
        self.assertIsNone(k["ensimmainen_paiva"])


class PienetRyhmat(Pohja):
    def test_alle_viisi_peitetaan(self):
        self.taydenna(3, True)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["arvioita_yhteensa"], "<5")
        self.assertEqual(k["paivittain"], {"2026-11-10": "<5"})
        self.assertEqual(k["kylla"], "<5")

    def test_tasan_viisi_nakyy(self):
        self.taydenna(5, True)
        self.taydenna(5, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (10, 5, 5))
        self.assertEqual(k["paivittain"]["2026-11-10"], 5)

    def test_pieni_ei_ryhma_peittaa_myos_kylla_luvun(self):
        self.taydenna(9, True)
        self.taydenna(2, False, pv=11)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["arvioita_yhteensa"], k["kylla"], k["ei"]), (11, "<5", "<5"))

    def test_tonyn_tarkistukset_alle_viisi(self):
        for i in range(8):
            self.arvio(f"a{i}.md", True, tony=(i != 0) if i < 3 else None)
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["tony_tarkistanut"], "<5")
        self.assertIsNone(k["yhtenevyys_tonyn_kanssa_prosenttia"])

    def test_tonyn_rivi_ilman_aivon_arviota_ei_lasketa(self):
        for i in range(6):
            self.arvio(f"a{i}.md", True)
        with open(self.tila / aivo_arvio.TIEDOSTO, "a") as f:
            for i in range(9):
                f.write(json.dumps({"aika": "2026-11-10T12:00:00+00:00", "laji": "tony", "tehtava": f"orpo{i}.md", "kylla": True}) + "\n")
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual(k["tony_tarkistanut"], "<5")

    def test_tonyn_yhtenevyys(self):
        for i in range(8):
            self.arvio(f"a{i}.md", True, tony=(i < 6))   # 6 osumaa, 2 ei
        k = aivo_arvio.laske_kooste(self.tila)
        self.assertEqual((k["tony_tarkistanut"], k["yhtenevyys_tonyn_kanssa_prosenttia"]), (8, 75.0))

    def test_tulosyhtenevyys(self):
        for i in range(4):   # kylla + VALMIS = osuma
            self.arvio(f"v{i}.md", True)
            self.tulos(f"v{i}.md", "VALMIS")
        for i in range(2):   # kylla + KESKEN = ei osuma
            self.arvio(f"k{i}.md", True)
            self.tulos(f"k{i}.md", "KESKEN")
        for i in range(2):   # ei + HYLATTY = osuma
            self.arvio(f"h{i}.md", False)
            self.tulos(f"h{i}.md", "HYLATTY")
        self.arvio("x.md", True)
        self.tulos("x.md", "EPAONNISTUI")   # ei vertailuun
        self.arvio("ilman.md", True)        # ei tulosta
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual((k["tulokseen_verrattu"], k["yhtenevyys_tuloksen_kanssa_prosenttia"]), (8, 75.0))

    def test_tulosyhtenevyys_alle_viisi(self):
        self.arvio("a.md", True)
        self.tulos("a.md", "VALMIS")
        k = aivo_arvio.laske_kooste(self.tila, self.tulokset)
        self.assertEqual(k["tulokseen_verrattu"], "<5")
        self.assertIsNone(k["yhtenevyys_tuloksen_kanssa_prosenttia"])

    def test_polkuhypyn_nimi_ei_lue_tulosta(self):
        (self.tila / "x.md").write_text("- Tila: VALMIS\n")   # tulokset/../x.md olisi olemassa
        self.assertIsNone(aivo_arvio._tulos_tila(self.tulokset, "../x.md"))
        self.assertEqual(aivo_arvio._tulos_tila(self.tila, "x.md"), "VALMIS")


class Kirjoitus(Pohja):
    def test_oikeudet_0644_vaikka_umask_tiukka(self):
        vanha = os.umask(0o077)
        try:
            p = aivo_arvio.kirjoita_kooste(self.tila)
        finally:
            os.umask(vanha)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)

    def test_atominen_kirjoitus_rename(self):
        aivo_arvio.kirjoita_kooste(self.tila)
        vanha = (self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text()
        with mock.patch("claudejono.aivo_arvio.os.replace", side_effect=OSError("x")):
            with self.assertRaises(OSError):
                aivo_arvio.kirjoita_kooste(self.tila, nyt=aika(20))
        self.assertEqual((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).read_text(), vanha)   # vanha ehja
        self.assertEqual([p.name for p in self.tila.glob("*.tmp")], [])                 # valiaikaistiedosto siivottu

    def test_replace_kutsutaan_valiaikaistiedostolla(self):
        kutsut = []
        todellinen = os.replace
        with mock.patch("claudejono.aivo_arvio.os.replace", side_effect=lambda a, b: (kutsut.append((a, b)), todellinen(a, b))[1]):
            aivo_arvio.kirjoita_kooste(self.tila)
        self.assertEqual(len(kutsut), 1)
        self.assertNotEqual(Path(kutsut[0][0]).name, aivo_arvio.KOOSTE_TIEDOSTO)
        self.assertEqual(Path(kutsut[0][1]).name, aivo_arvio.KOOSTE_TIEDOSTO)

    def test_ylikirjoittaa_vanhan(self):
        self.taydenna(6, True)
        aivo_arvio.kirjoita_kooste(self.tila)
        self.assertEqual(self.kooste()["arvioita_yhteensa"], 6)
        self.taydenna(6, True, alku=50)
        aivo_arvio.kirjoita_kooste(self.tila)
        self.assertEqual(self.kooste()["arvioita_yhteensa"], 12)


class Virheet(Pohja):
    def test_varma_kirjoitus_ei_nosta_virhetta_ja_kirjaa_tyypin(self):
        err = io.StringIO()
        with mock.patch("claudejono.aivo_arvio.laske_kooste", side_effect=ValueError("SALAISUUS")), contextlib.redirect_stderr(err):
            self.assertFalse(aivo_arvio.kirjoita_kooste_varmasti(self.tila))
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("SALAISUUS", err.getvalue())

    def test_varma_kirjoitus_onnistuu(self):
        self.assertTrue(aivo_arvio.kirjoita_kooste_varmasti(self.tila))

    def test_ajuri_ei_kaadu_laskentavirheeseen(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", return_value="jono tyhja"), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                mock.patch("claudejono.aivo_arvio.laske_kooste", side_effect=RuntimeError("SALAISUUS")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 0)
        self.assertIn("RuntimeError", err.getvalue())

    def test_ajuri_kirjoittaa_koosteen_kierroksella(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", return_value="jono tyhja"), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 0)
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())

    def test_koosteen_kirjoitus_myos_kun_aja_kaatuu(self):
        repo = self.tila / "docs"
        repo.mkdir()
        env = {"CLAUDEJONO_REPO": str(repo), "CLAUDEJONO_TYOHAK": str(self.tila)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ajuri, "aja", side_effect=RuntimeError("x")), \
                mock.patch.object(ajuri, "aivo_arvioija", return_value=None), \
                mock.patch.object(ajuri, "halyta"), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ajuri.main(["ajo"]), 1)
        self.assertTrue((self.tila / aivo_arvio.KOOSTE_TIEDOSTO).is_file())


if __name__ == "__main__":
    unittest.main()
