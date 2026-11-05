import subprocess
import json
"""Tehtavan `Kaista: N` -kiinnitys: jasennys, valinta ja kilpa-ajo oikeilla prosesseilla (kaistat 1-3)."""
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from claudejono import ajuri
from claudejono.test_ajuri import Pohja
from claudejono.test_kaistat import _kaista_tyontekija


def kirjoita(hak, nimi, teksti):
    p = Path(hak) / nimi
    p.write_text(teksti)
    return p


class Jasennys(unittest.TestCase):
    def setUp(self):
        self.hak = tempfile.mkdtemp()

    def kaista(self, teksti, kaistoja=3):
        return ajuri.tehtavan_kaista(kirjoita(self.hak, "t.md", teksti), kaistoja)

    def test_rivi_tunnistetaan_missa_tahansa_rivilla(self):
        self.assertEqual(self.kaista("# Otsikko\n\nKaista: 3\nMuu teksti"), 3)
        self.assertEqual(self.kaista("Kaista:2"), 2)
        self.assertEqual(self.kaista("Kaista: 1  \n"), 1)

    def test_ilman_rivia_tai_virheellinen_on_vapaa(self):
        for teksti in ("ei rivia", "Kaista: x", "Kaista: 0", "Kaista: 4", "Kaista: -1", "kaista: 2",
                       "Kaista: 2 ja muuta", "  Kaista: 2", "teksti Kaista: 2", "Kaista: 99999999999999999999"):
            self.assertIsNone(self.kaista(teksti), teksti)

    def test_kaista_yli_kaistojen_maaran_on_vapaa(self):
        self.assertIsNone(self.kaista("Kaista: 3", kaistoja=2))
        self.assertEqual(self.kaista("Kaista: 2", kaistoja=2), 2)

    def test_ensimmainen_rivi_ratkaisee(self):
        self.assertEqual(self.kaista("Kaista: 2\nKaista: 3"), 2)

    def test_puuttuva_tiedosto_on_vapaa(self):
        self.assertIsNone(ajuri.tehtavan_kaista(Path(self.hak) / "ei-ole.md"))


class Valinta(Pohja):
    def teht(self, n, kaista=None):
        nimi = f"2026-11-03-{n:02d}-t.md"
        self.lisaa_tehtava(nimi, f"TEHTAVA-{nimi}\n" + (f"Kaista: {kaista}\n" if kaista else ""))
        return nimi

    def valitse(self, kaista, kaistoja=3):
        t = ajuri.varaa_seuraava(self.repo, self.tmp, kaista, kaistoja=kaistoja)
        return t.name if t else None

    def test_muut_kaistat_ohittavat_kiinnitetyn(self):
        a = self.teht(1, kaista=3)
        b = self.teht(2)
        self.assertEqual(self.valitse(1), b)
        self.assertIsNone(self.valitse(2))   # a kuuluu kaistalle 3, b on varattu
        self.assertEqual(self.valitse(3), a)

    def test_kiinnitetty_kaista_ottaa_ensin_omat_sitten_vapaat(self):
        vapaa1 = self.teht(1)
        oma = self.teht(2, kaista=2)
        vapaa2 = self.teht(3)
        toisen = self.teht(4, kaista=1)
        self.assertEqual(self.valitse(2), oma)        # oma ohittaa vanhemman vapaan
        self.assertEqual(self.valitse(2), vapaa1)
        self.assertEqual(self.valitse(2), vapaa2)
        self.assertIsNone(self.valitse(2))            # toisen kiinnittamaan ei koskaan koske
        self.assertEqual(self.valitse(1), toisen)

    def test_poissa_oleva_kaista_ei_jumita_tehtavaa(self):
        t = self.teht(1, kaista=3)
        self.assertEqual(self.valitse(1, kaistoja=2), t)

    def test_aja_ei_ota_toisen_kaistan_tehtavaa_vaan_suunnittelee_ennakoiden(self):
        # Ennakoiva suunnittelu (#175): vapaa kaista suunnittelee, vaikka toisen kaistan kiinnittama tehtava odottaa,
        # kun avoimia on alle 2 x kaistat. Kiinnitettyyn tehtavaan se ei koske.
        t = self.teht(1, kaista=2)
        kutsut = []

        def suorita(kom, **k):
            kutsut.append(kom)
            self.assertNotIn("TEHTAVA-" + t, " ".join(map(str, kom)))
            return subprocess.CompletedProcess(kom, 0, json.dumps({"subtype": "success", "result": '{"tehtavat": [], "tonylle": ""}'}), "")
        ajuri.aja(self.repo, self.tmp, env={"CLAUDEJONO_KAISTOJA": "3", "CLAUDEJONO_ITSESUUNNITTELU": "1"}, suorita=suorita, kaista=1)
        self.assertEqual(len(kutsut), 1)   # yksi suunnittelukutsu, ei tehtavan ajoa
        self.assertFalse((self.repo / ajuri.JONO / "tulokset" / t).exists())

    def test_kilpa_ajo_kolme_kaistaa_kiinnitetyt_ja_vapaat(self):
        kiinnitys = {1: 3, 3: 2, 5: 3, 7: 1, 8: 2}
        for n in range(1, 10):
            self.teht(n, kaista=kiinnitys.get(n))
        loki = str(self.tmp / "ajot.log")
        env = {"CLAUDEJONO_ITSESUUNNITTELU": "0", "CLAUDEJONO_KAISTOJA": "3"}
        ctx = multiprocessing.get_context("fork")
        ps = [ctx.Process(target=_kaista_tyontekija, args=(self.repo, self.tmp, k, loki, 0.2, env)) for k in (1, 2, 3)]
        [p.start() for p in ps]
        [p.join(120) for p in ps]
        self.assertEqual([p.exitcode for p in ps], [0, 0, 0])
        alut = [r.split() for r in Path(loki).read_text().splitlines() if r.startswith("alku")]
        self.assertEqual(len({r[1] for r in alut}), 9)   # jokainen tehtava tasmalleen kerran
        self.assertEqual(len(alut), 9)
        for n, k in kiinnitys.items():
            rivi = [r for r in alut if r[1] == f"2026-11-03-{n:02d}-t.md"]
            self.assertEqual([r[2] for r in rivi], [str(k)], f"tehtava {n} ajettiin vaarella kaistalla")
        self.assertEqual(ajuri.aktiiviset_varaukset(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
