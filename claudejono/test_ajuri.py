import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from claudejono import ajuri


def git(hak, *a):
    subprocess.run(["git", "-C", str(hak), *a], check=True, capture_output=True, text=True)


class Pohja(unittest.TestCase):
    """Oikea git-repo: paikallinen bare-origin + klooni, jotta pull/push testataan aidosti."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo = self.tmp / "docs"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "checkout", "-q", "-b", "main")
        (self.repo / "README.md").write_text("x\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-q", "-m", "alku")
        git(self.repo, "push", "-q", "origin", "main")

    def lisaa_tehtava(self, nimi, teksti="tee jotain"):
        p = self.repo / ajuri.JONO / "tehtavat" / nimi
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(teksti)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "t")
        git(self.repo, "push", "-q", "origin", "main")
        return p


class Nimi(unittest.TestCase):
    def test_kelvolliset_ja_kelvottomat(self):
        self.assertTrue(ajuri.kelvollinen_nimi("2026-10-30-01-ideoi-korjaus.md"))
        for n in ("../x.md", "2026-10-30-01-X.md", "2026-10-30-1-a.md", "a.md", "2026-10-30-01-a.txt", "2026-10-30-01-a b.md"):
            self.assertFalse(ajuri.kelvollinen_nimi(n), n)


class Valinta(Pohja):
    def test_tyhja_jono(self):
        self.assertIsNone(ajuri.seuraava_tehtava(self.repo))

    def test_vanhin_ilman_tulosta_ja_kelvoton_ohitetaan(self):
        self.lisaa_tehtava("2026-10-30-02-b.md")
        self.lisaa_tehtava("2026-10-30-01-a.md")
        self.lisaa_tehtava("2026-10-29-01-HUONO.md")
        (self.repo / ajuri.JONO / "tulokset").mkdir()
        (self.repo / ajuri.JONO / "tulokset" / "2026-10-30-01-a.md").write_text("tehty")
        self.assertEqual(ajuri.seuraava_tehtava(self.repo).name, "2026-10-30-02-b.md")

    def test_liian_iso_tehtava_hylataan(self):
        p = self.lisaa_tehtava("2026-10-30-01-a.md", "x" * (ajuri.TEHTAVA_MAX_TAVUA + 1))
        with self.assertRaises(ajuri.JonoVirhe):
            ajuri.rakenna_kehote(p)


class Tulkinta(unittest.TestCase):
    def test_onnistui(self):
        self.assertEqual(ajuri.tulkitse(json.dumps({"subtype": "success", "result": "ok"}), 0), (True, "ok"))

    def test_virhe_ja_lukukelvoton(self):
        self.assertFalse(ajuri.tulkitse(json.dumps({"subtype": "error_max_turns", "is_error": True}), 1)[0])
        self.assertFalse(ajuri.tulkitse("ei json", 0)[0])
        self.assertFalse(ajuri.tulkitse(json.dumps({"subtype": "success", "result": "x"}), 2)[0])


class Komento(unittest.TestCase):
    def test_lupatila_vain_jos_asetettu(self):
        self.assertNotIn("--permission-mode", ajuri.claude_komento("k", {}))
        k = ajuri.claude_komento("k", {"CLAUDEJONO_LUPATILA": "auto", "CLAUDEJONO_MAX_KIERROKSET": "5"})
        self.assertEqual(k[k.index("--permission-mode") + 1], "auto")
        self.assertEqual(k[k.index("--max-turns") + 1], "5")


class Ajo(Pohja):
    def suorita(self, palaute, koodi=0, sivuvaikutus=None):
        kutsut = []

        def f(kom, **kw):
            kutsut.append((kom, kw))
            if sivuvaikutus:
                sivuvaikutus()
            return subprocess.CompletedProcess(kom, koodi, json.dumps(palaute), "")
        return f, kutsut

    def test_ajo_pushaa_vain_tuloksen(self):
        self.lisaa_tehtava("2026-10-30-01-a.md")
        f, kutsut = self.suorita({"subtype": "success", "result": "raportti"})
        viesti = ajuri.aja(self.repo, self.tmp, env={"YOJONO_TELEGRAM_TOKEN": "salainen"}, suorita=f)
        self.assertIn("VALMIS", viesti)
        self.assertNotIn("YOJONO_TELEGRAM_TOKEN", kutsut[0][1]["env"])
        tarkistus = self.tmp / "tarkistus"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(tarkistus)], check=True, capture_output=True)
        tulos = tarkistus / ajuri.JONO / "tulokset" / "2026-10-30-01-a.md"
        self.assertIn("VALMIS", tulos.read_text())
        self.assertIn("raportti", tulos.read_text())
        self.assertEqual(ajuri.aja(self.repo, self.tmp, env={}, suorita=f), "jono tyhja")

    def test_agentin_muut_muutokset_estavat_commitin(self):
        self.lisaa_tehtava("2026-10-30-01-a.md")
        f, _ = self.suorita({"subtype": "success", "result": "x"},
                            sivuvaikutus=lambda: ((self.repo / "README.md").write_text("muutettu\n"), git(self.repo, "add", "README.md")))
        with self.assertRaises(ajuri.JonoVirhe):
            ajuri.aja(self.repo, self.tmp, env={}, suorita=f)

    def test_aikakatkaisu_kirjataan_epaonnistuneeksi(self):
        self.lisaa_tehtava("2026-10-30-01-a.md")

        def f(kom, **kw):
            raise subprocess.TimeoutExpired(kom, 1)
        self.assertIn("EPAONNISTUI", ajuri.aja(self.repo, self.tmp, env={}, suorita=f))

    def test_julkaise_kieltaa_muun_polun(self):
        with self.assertRaises(ajuri.JonoVirhe):
            ajuri.julkaise(self.repo, self.repo / "README.md")


if __name__ == "__main__":
    unittest.main()
