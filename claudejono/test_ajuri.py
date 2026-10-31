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


class GitVirhe(Pohja):
    def test_git_virhe_kertoo_gitin_viestin(self):
        with self.assertRaises(ajuri.JonoVirhe) as cm:
            ajuri.git(self.tmp / "ei-ole", "pull")
        self.assertIn("git pull epaonnistui", str(cm.exception))
        self.assertTrue(len(str(cm.exception)) > len("git pull epaonnistui (128): "))


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
        self.assertEqual(ajuri.aja(self.repo, self.tmp, env={"CLAUDEJONO_ITSESUUNNITTELU": "0"}, suorita=f), "jono tyhja")

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


class Itsesuunnittelu(Pohja):
    PVM = "2026-10-30"

    def nyt(self):
        from datetime import datetime, timezone
        return datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    def malli(self, tulos, kutsut=None):
        def f(kom, **kw):
            if kutsut is not None:
                kutsut.append(kom)
            return subprocess.CompletedProcess(kom, 0, json.dumps({"subtype": "success", "result": tulos}), "")
        return f

    def origin_tiedostot(self):
        t = self.tmp / ("tark" + str(len(list(self.tmp.iterdir()))))
        subprocess.run(["git", "clone", "-q", str(self.origin), str(t)], check=True, capture_output=True)
        return sorted(str(p.relative_to(t)) for p in (t / ajuri.JONO).rglob("*.md")) if (t / ajuri.JONO).exists() else []

    def test_luo_tehtavat_ja_tonylle_rajattuina(self):
        self.lisaa_tehtava("2026-10-30-01-a.md")
        (self.repo / ajuri.JONO / "tulokset").mkdir()
        (self.repo / ajuri.JONO / "tulokset" / "2026-10-30-01-a.md").write_text("ok")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "t"); git(self.repo, "push", "-q", "origin", "main")
        vastaus = json.dumps({"tehtavat": [
            {"nimi": "korjaa-x", "sisalto": "# X\n\nValmis kun: x"},
            {"nimi": "HUONO NIMI", "sisalto": "y"},
            {"nimi": "toinen", "sisalto": "# Y"},
            {"nimi": "kolmas", "sisalto": "# Z"}], "tonylle": "Nosta katto?"})
        v = ajuri.suunnittele(self.repo, self.tmp, {}, self.malli("Tassa:\n" + vastaus), nyt=self.nyt())
        self.assertIn("itsesuunnittelu", v)
        tied = self.origin_tiedostot()
        self.assertIn("claude-jono/tehtavat/2026-10-30-02-auto-korjaa-x.md", tied)
        self.assertIn("claude-jono/tehtavat/2026-10-30-03-auto-toinen.md", tied)
        self.assertNotIn("claude-jono/tehtavat/2026-10-30-04-auto-kolmas.md", tied)   # AUTO_PER_AJO = 2
        self.assertIn("claude-jono/tonylle.md", tied)
        self.assertEqual(ajuri.seuraava_tehtava(self.repo).name, "2026-10-30-02-auto-korjaa-x.md")

    def test_paivaraja_estaa_mallikutsun(self):
        teht = self.repo / ajuri.JONO / "tehtavat"
        teht.mkdir(parents=True)
        for i in range(ajuri.AUTO_MAX_PAIVA):
            (teht / f"2026-10-30-{i + 1:02d}-auto-t{i}.md").write_text("x")
        kutsut = []
        v = ajuri.suunnittele(self.repo, self.tmp, {}, self.malli("{}", kutsut), nyt=self.nyt())
        self.assertIn("paivaraja", v)
        self.assertEqual(kutsut, [])

    def test_virheellinen_json_ei_luo_mitaan(self):
        v = ajuri.suunnittele(self.repo, self.tmp, {}, self.malli("ei jsonia"), nyt=self.nyt())
        self.assertIn("ei tuottanut", v)
        self.assertEqual(self.origin_tiedostot(), [])

    def test_tyhja_lista_ei_committaa(self):
        v = ajuri.suunnittele(self.repo, self.tmp, {}, self.malli('{"tehtavat": [], "tonylle": ""}'), nyt=self.nyt())
        self.assertEqual(v, "jono tyhja (ei uusia tehtavia)")

    def test_sallitut_polut(self):
        self.assertTrue(ajuri.sallittu_polku("claude-jono/tulokset/2026-10-30-01-a.md"))
        self.assertTrue(ajuri.sallittu_polku("claude-jono/tehtavat/2026-10-30-01-auto-a.md"))
        self.assertTrue(ajuri.sallittu_polku("claude-jono/tonylle.md"))
        self.assertFalse(ajuri.sallittu_polku("claude-jono/tehtavat/2026-10-30-01-a.md"))   # vain pilvi-Claude/Tony kirjoittaa muut
        self.assertFalse(ajuri.sallittu_polku("README.md"))
        self.assertFalse(ajuri.sallittu_polku("claude-jono/tulokset/../../x.md"))

    def test_raja_on_laissa(self):
        self.assertLessEqual(ajuri.AUTO_MAX_PAIVA, 30)


class OmaKayttaja(unittest.TestCase):
    """Tonyn paatos 30.10.2026: agentti ajetaan omana kayttajanaan, ajuri jaa rootiksi."""

    def test_runuser_ja_minimiymparisto(self):
        env = {"CLAUDEJONO_KAYTTAJA": "claudejono", "CLAUDEJONO_CLAUDE": "/var/lib/claudejono/.local/bin/claude",
               "GIT_SSH_COMMAND": "ssh -i /etc/claude-jono/deploy_key", "YOJONO_TELEGRAM_TOKEN": "x", "PATH": "/root/bin:/usr/bin"}
        kom, alaenv, cwd = ajuri.lapsen_ajo("k", env, "/opt/agentscope")
        self.assertEqual(kom[:4], ["/usr/sbin/runuser", "-u", "claudejono", "--"])
        # Popen hakee komennon lapsen PATHista: runuserin on oltava absoluuttinen polku
        self.assertTrue(kom[0].startswith("/"))
        self.assertNotIn("/usr/sbin", alaenv["PATH"].split(":"))
        self.assertEqual(kom[4], "/var/lib/claudejono/.local/bin/claude")
        self.assertEqual(cwd, "/opt/agentscope/tyo")
        self.assertEqual(alaenv["HOME"], "/var/lib/claudejono")
        for kielletty in ("GIT_SSH_COMMAND", "YOJONO_TELEGRAM_TOKEN", "CLAUDEJONO_KAYTTAJA"):
            self.assertNotIn(kielletty, alaenv)
        self.assertNotIn("/root", alaenv["PATH"])

    def test_root_ja_virheellinen_nimi_hylataan(self):
        for nimi in ("root", "a b", "../x", "Claude"):
            with self.assertRaises(ajuri.JonoVirhe):
                ajuri.lapsen_ajo("k", {"CLAUDEJONO_KAYTTAJA": nimi}, "/opt/agentscope")

    def test_ilman_kayttajaa_ennallaan_mutta_ilman_ssh_avainta(self):
        kom, alaenv, cwd = ajuri.lapsen_ajo("k", {"GIT_SSH_COMMAND": "ssh -i x", "A": "1"}, "/opt/agentscope")
        self.assertEqual(kom[0], "claude")
        self.assertEqual(cwd, "/opt/agentscope")
        self.assertEqual(alaenv, {"A": "1"})


if __name__ == "__main__":
    unittest.main()
