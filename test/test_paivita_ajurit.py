"""isanta/paivita-ajurit.sh: hiekkalaatikko. Lahde on paikallinen git-repo, kohteet ovat tilapaishakemistoja, systemctl on
tynka. Ei verkkoa, ei oikeaa systemd:ta, ei kosketa /opt-hakemistoihin. Ajetaan vain Linuxilla (bash 4+, GNU-tyokalut)."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
SKRIPTI = JUURI / "isanta" / "paivita-ajurit.sh"
LINUX = sys.platform.startswith("linux") and shutil.which("bash") and shutil.which("git") and shutil.which("flock")
EPA = "EP" + chr(0xC4) + "ONNISTUI"

SYSTEMCTL = r'''#!/usr/bin/env bash
# list-units --type=timer: SIM/timers; --type=service: SIM/busy tulostuu, kunnes SIM_BUSY_KERTAA kutsua on tehty
case "$1" in
  list-units)
    case "$*" in
      *--type=timer*) cat "$SIM/timers" 2>/dev/null ;;
      *--type=service*)
        n=$(cat "$SIM/busy_n" 2>/dev/null || echo 0); echo $((n + 1)) > "$SIM/busy_n"
        if [ "$n" -lt "${SIM_BUSY_KERTAA:-0}" ]; then echo "claude-jono@1.service loaded activating start start Kaista"; fi ;;
    esac ;;
  stop|start) echo "$1 $2" >> "$SIM/systemctl.log" ;;
esac
exit 0
'''

V1 = {
    "claudejono/__init__.py": "", "claudejono/ajuri.py": "VERSIO = 1\n", "claudejono/tarkastaja.py": "", "claudejono/aamukooste.py": "",
    "agentti/__init__.py": "", "agentti/pr_kutsu.py": "", "agentti/viikkoraportti.py": "",
    "yojono/__init__.py": "", "yojono/ajuri.py": "VERSIO = 1\n", "yojono/__main__.py": "import sys\nsys.exit(0)\n",
    "test/__init__.py": "",
    "test/test_ok.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
    ".github/workflows/x.yml": "nimi: x\n", "systemd/a.service": "[Service]\n",
}


def aja(*arg, cwd=None, env=None):
    return subprocess.run(arg, cwd=cwd, env=env, capture_output=True, text=True)


@unittest.skipUnless(LINUX, "vain Linux, bash, git ja flock")
class PaivitaAjuritTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="paivita-testi-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sim = self.tmp / "sim"; self.opt = self.tmp / "opt"
        self.sim.mkdir(); self.opt.mkdir()
        (self.sim / "systemctl").write_text(SYSTEMCTL); (self.sim / "systemctl").chmod(0o755)
        (self.sim / "timers").write_text("claude-jono@1.timer loaded active waiting x\nyojono.timer loaded active waiting y\n")
        self.src = self.tmp / "src"; self.src.mkdir()
        self.git("init", "-q", "-b", "main", cwd=self.src)
        self.git("config", "user.email", "t@example.invalid", cwd=self.src); self.git("config", "user.name", "t", cwd=self.src)
        self.v1 = self.commit(V1, "v1")
        self.pohja = self.opt / "agentti-pohja"; self.yojono = self.opt / "yojono-ajuri"
        self.git("clone", "-q", str(self.src), str(self.pohja), cwd=self.tmp)
        self.yojono.mkdir()
        arch = subprocess.run(["git", "-C", str(self.src), "archive", self.v1], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(self.yojono)], input=arch, check=True)
        shutil.rmtree(self.yojono / ".github")
        self.manifesti(self.yojono, self.v1)
        self.kerta = 0

    def git(self, *arg, cwd):
        r = aja("git", *arg, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, tiedostot, viesti):
        for polku, sisalto in tiedostot.items():
            p = self.src / polku; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(sisalto)
        self.git("add", "-A", cwd=self.src); self.git("commit", "-q", "-m", viesti, cwd=self.src)
        return self.git("rev-parse", "HEAD", cwd=self.src)

    def manifesti(self, kansio, commit):
        sh = "find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > ../m.tmp && mv ../m.tmp .julkaisu-manifesti"
        subprocess.run(["bash", "-c", sh], cwd=kansio, check=True)
        (kansio / ".julkaisu-tieto").write_text("kohde=yojono-ajuri\ncommit=%s\n" % commit)

    def aja(self, *arg, **lisa):
        self.kerta += 1
        env = dict(os.environ, SIM=str(self.sim), PAIVITA_LAHDE=str(self.src), PAIVITA_POHJA=str(self.pohja),
                   PAIVITA_YOJONO=str(self.yojono), PAIVITA_LOKI=str(self.tmp / "loki.log"), PAIVITA_LUKKO=str(self.tmp / "lukko"),
                   PAIVITA_SYSTEMCTL=str(self.sim / "systemctl"), PAIVITA_SALLI_EI_ROOT="1", PAIVITA_VAPAA_MB="1",
                   PAIVITA_SEURANTA_S="0", PAIVITA_TS="20261108-10%02d00" % self.kerta,
                   PAIVITA_TESTI_POHJA="test.test_ok", PAIVITA_TESTI_YOJONO="test.test_ok",
                   PAIVITA_SAVU_POHJA="claudejono.ajuri agentti.pr_kutsu", PAIVITA_SAVU_YOJONO="yojono.ajuri agentti.pr_kutsu")
        env.update(lisa)
        return aja("bash", str(SKRIPTI), *arg, cwd=self.tmp, env=env)

    def loppurivi(self, r):
        return [x for x in r.stdout.splitlines() if x.strip()][-1]

    def pohja_commit(self):
        return self.git("rev-parse", "HEAD", cwd=self.pohja)

    def yojono_commit(self):
        for rivi in (self.yojono / ".julkaisu-tieto").read_text().splitlines():
            if rivi.startswith("commit="):
                return rivi[7:]

    def yojono_eheys(self):
        return aja("sha256sum", "-c", "--quiet", ".julkaisu-manifesti", cwd=self.yojono).returncode == 0

    def ajastinloki(self):
        p = self.sim / "systemctl.log"
        return p.read_text().splitlines() if p.exists() else []

    def jaannokset(self):
        return sorted(p.name for p in self.opt.iterdir() if ".uusi" in p.name or p.name.startswith(".paivita"))

    def assertEnnallaan(self):
        self.assertEqual(self.pohja_commit(), self.v1); self.assertEqual(self.yojono_commit(), self.v1)
        self.assertTrue(self.yojono_eheys()); self.assertEqual(self.jaannokset(), [])

    def assertAjastimetPalautettu(self):
        """Kaikki pysaytetyt ajastimet kaynnistettiin takaisin, ja pysaytettyja oli tasan kaksi."""
        loki = self.ajastinloki()
        pysaytetyt = sorted(x.split(" ", 1)[1] for x in loki if x.startswith("stop "))
        kaynnistetyt = sorted(x.split(" ", 1)[1] for x in loki if x.startswith("start "))
        self.assertEqual(pysaytetyt, ["claude-jono@1.timer", "yojono.timer"])
        self.assertEqual(kaynnistetyt, pysaytetyt)

    # ---- onnistuminen -------------------------------------------------------------
    def test_onnistuminen_vaihtaa_molemmat_ja_tekee_varmuuskopiot(self):
        v2 = self.commit({"claudejono/ajuri.py": "VERSIO = 2\n", "yojono/ajuri.py": "VERSIO = 2\n"}, "v2")
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.loppurivi(r).startswith("OK: "), self.loppurivi(r))
        self.assertEqual(self.pohja_commit(), v2); self.assertEqual(self.yojono_commit(), v2)
        self.assertIn("VERSIO = 2", (self.yojono / "yojono/ajuri.py").read_text())
        self.assertFalse((self.yojono / ".github").exists()); self.assertFalse((self.yojono / ".git").exists())
        self.assertTrue(self.yojono_eheys())
        self.assertEqual(self.git("status", "--porcelain", cwd=self.pohja), "")
        self.assertEqual(self.git("remote", "get-url", "origin", cwd=self.pohja), str(self.src))
        pv = list(self.opt.glob("agentti-pohja.prev-*")); yv = list(self.opt.glob("yojono-ajuri.prev-*"))
        self.assertEqual((len(pv), len(yv)), (1, 1))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=pv[0]), self.v1)
        self.assertIn("VERSIO = 1", (yv[0] / "yojono/ajuri.py").read_text())
        self.assertEqual(self.jaannokset(), [])
        self.assertAjastimetPalautettu(); self.assertEqual(len(self.ajastinloki()), 4)

    def test_idempotentti_toinen_ajo_ei_muuta(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        self.assertEqual(self.aja().returncode, 0)
        ennen = sorted(p.name for p in self.opt.iterdir()); lokia = len(self.ajastinloki())
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ajan tasalla", self.loppurivi(r))
        self.assertEqual(sorted(p.name for p in self.opt.iterdir()), ennen)
        self.assertEqual(len(self.ajastinloki()), lokia)

    def test_vain_toinen_kohde_jaljessa(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        self.assertEqual(self.aja().returncode, 0)
        v3 = self.commit({"claudejono/ajuri.py": "VERSIO = 3\n"}, "v3")
        self.git("pull", "-q", cwd=self.pohja)   # pohja on jo uusimmassa, yojono ei: kopioidaan v3 vain yojonoon
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.yojono_commit(), v3)
        self.assertEqual(len(list(self.opt.glob("agentti-pohja.prev-*"))), 1)   # pohjaa ei vaihdettu uudelleen
        self.assertEqual(len(list(self.opt.glob("yojono-ajuri.prev-*"))), 2)

    def test_kuiva_ei_muuta_mitaan(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        r = self.aja("--kuiva")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("kuiva-ajo", self.loppurivi(r))
        self.assertEnnallaan(); self.assertEqual(self.ajastinloki(), [])
        self.assertEqual(list(self.opt.glob("*.prev-*")), [])

    # ---- virheet ennen vaihtoa ------------------------------------------------------
    def test_testivirhe_estaa_vaihdon(self):
        self.commit({"test/test_ok.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(False)\n"}, "rikki")
        r = self.aja()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertTrue(self.loppurivi(r).startswith(EPA + ": testit kaatuivat"), self.loppurivi(r))
        self.assertEnnallaan(); self.assertEqual(self.ajastinloki(), []); self.assertEqual(list(self.opt.glob("*.prev-*")), [])

    def test_testikomennon_virhe_ei_huku_putkeen(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        r = self.aja(PAIVITA_TESTI_POHJA="test.ei_ole")   # tuontivirhe: unittest palauttaa nollasta poikkeavan
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEnnallaan()

    def test_paikalliset_muutokset_estavat(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        (self.pohja / "claudejono/ajuri.py").write_text("VERSIO = 99\n")
        r = self.aja()
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("paikallisia muutoksia", r.stdout)
        self.assertEqual(self.jaannokset(), []); self.assertEqual(self.pohja_commit(), self.v1)

    def test_lukko_estaa_rinnakkaisen_ajon(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        pito = subprocess.Popen(["flock", str(self.tmp / "lukko"), "sleep", "20"])
        self.addCleanup(pito.kill)
        time.sleep(0.5)
        r = self.aja()
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("lukko", r.stdout); self.assertEnnallaan()

    def test_ei_juurena_estetaan(self):
        r = self.aja(PAIVITA_SALLI_EI_ROOT="0")
        if os.getuid() == 0:
            self.skipTest("testi ajetaan rootina")
        self.assertEqual(r.returncode, 2); self.assertIn("rootina", r.stdout)

    def test_palvelut_kaynnissa_odotetaan_ja_aikaraja_palauttaa_ajastimet(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        r = self.aja(PAIVITA_ODOTA_S="0", SIM_BUSY_KERTAA="1000000")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("yha kaynnissa", r.stdout)
        self.assertEnnallaan(); self.assertAjastimetPalautettu(); self.assertEqual(len(self.ajastinloki()), 4)

    def test_odottaa_kunnes_palvelut_vapautuvat(self):
        v2 = self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        r = self.aja(SIM_BUSY_KERTAA="3")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("odotetaan palveluita", r.stdout); self.assertEqual(self.pohja_commit(), v2)

    # ---- virheet vaihdon jalkeen: automaattinen paluu --------------------------------
    def test_savutestin_virhe_palauttaa_vanhan(self):
        self.commit({"agentti/pr_kutsu.py": "def (:\n"}, "rikki")   # testit (test_ok) menevat lapi, tuonti ei
        r = self.aja()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("vanha koodi palautettu ja savutesti OK", self.loppurivi(r), self.loppurivi(r))
        self.assertTrue(self.loppurivi(r).startswith(EPA))
        self.assertEnnallaan()
        self.assertEqual(len(list(self.opt.glob("agentti-pohja.viallinen-*"))), 1)
        self.assertEqual(len(list(self.opt.glob("yojono-ajuri.viallinen-*"))), 1)
        self.assertAjastimetPalautettu(); self.assertEqual(len(self.ajastinloki()), 4)

    def test_toisen_kohteen_savuvirhe_palauttaa_molemmat(self):
        self.commit({"yojono/ajuri.py": "raise ImportError('x')\n"}, "yojono rikki")   # pohjan savutesti menee lapi
        r = self.aja()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEnnallaan()
        self.assertEqual(self.pohja_commit(), self.v1)

    def test_keskeytys_odotuksessa_ei_muuta_mitaan(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n"}, "v2")
        env = dict(os.environ, SIM=str(self.sim), PAIVITA_LAHDE=str(self.src), PAIVITA_POHJA=str(self.pohja), PAIVITA_YOJONO=str(self.yojono),
                   PAIVITA_LOKI=str(self.tmp / "loki.log"), PAIVITA_LUKKO=str(self.tmp / "lukko"), PAIVITA_SYSTEMCTL=str(self.sim / "systemctl"),
                   PAIVITA_SALLI_EI_ROOT="1", PAIVITA_VAPAA_MB="1", PAIVITA_SEURANTA_S="1", PAIVITA_ODOTA_S="60", SIM_BUSY_KERTAA="1000000",
                   PAIVITA_TESTI_POHJA="test.test_ok", PAIVITA_TESTI_YOJONO="test.test_ok",
                   PAIVITA_SAVU_POHJA="claudejono.ajuri", PAIVITA_SAVU_YOJONO="yojono.ajuri")
        p = subprocess.Popen(["bash", str(SKRIPTI)], cwd=self.tmp, env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.kill)
        for rivi in p.stdout:
            if "odotetaan palveluita" in rivi:
                break
        p.send_signal(signal.SIGTERM)
        ulos = p.stdout.read(); p.wait(timeout=20)
        self.assertEqual(p.returncode, 1, ulos)
        self.assertIn("keskeytetty ennen vaihtoa", ulos)
        self.assertEnnallaan(); self.assertAjastimetPalautettu(); self.assertEqual(len(self.ajastinloki()), 4)

    def test_keskeytys_vaihdon_jalkeen_palauttaa_vanhan(self):
        # uuden yojono-ajurin tuonti kestaa 3 s: signaali tulee savutestin aikana, trap ajetaan heti sen jalkeen
        self.commit({"yojono/ajuri.py": "import time\ntime.sleep(3)\nVERSIO = 2\n"}, "hidas")
        env = dict(os.environ, SIM=str(self.sim), PAIVITA_LAHDE=str(self.src), PAIVITA_POHJA=str(self.pohja), PAIVITA_YOJONO=str(self.yojono),
                   PAIVITA_LOKI=str(self.tmp / "loki.log"), PAIVITA_LUKKO=str(self.tmp / "lukko"), PAIVITA_SYSTEMCTL=str(self.sim / "systemctl"),
                   PAIVITA_SALLI_EI_ROOT="1", PAIVITA_VAPAA_MB="1", PAIVITA_SEURANTA_S="0",
                   PAIVITA_TESTI_POHJA="test.test_ok", PAIVITA_TESTI_YOJONO="test.test_ok",
                   PAIVITA_SAVU_POHJA="claudejono.ajuri", PAIVITA_SAVU_YOJONO="yojono.ajuri")
        p = subprocess.Popen(["bash", str(SKRIPTI)], cwd=self.tmp, env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.kill)
        for rivi in p.stdout:
            if "vaihdettu: yojono-ajuri" in rivi:
                break
        p.send_signal(signal.SIGTERM)
        ulos = p.stdout.read(); p.wait(timeout=30)
        self.assertEqual(p.returncode, 1, ulos)
        self.assertIn("keskeytetty", ulos); self.assertIn("vanha koodi palautettu", ulos)
        self.assertEnnallaan(); self.assertAjastimetPalautettu(); self.assertEqual(len(self.ajastinloki()), 4)

    # ---- peruutus --------------------------------------------------------------------
    def test_peruuta_palauttaa_viimeisimman_ajon_varmuuskopiot(self):
        self.commit({"claudejono/ajuri.py": "VERSIO = 2\n", "yojono/ajuri.py": "VERSIO = 2\n"}, "v2")
        self.assertEqual(self.aja().returncode, 0)
        r = self.aja("--peruuta")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(self.loppurivi(r).startswith("OK: peruutettu"), self.loppurivi(r))
        self.assertEqual(self.pohja_commit(), self.v1); self.assertEqual(self.yojono_commit(), self.v1); self.assertTrue(self.yojono_eheys())
        self.assertEqual(len(list(self.opt.glob("*.peruttu-*"))), 2)

    def test_peruuta_ilman_varmuuskopiota_ei_muuta(self):
        r = self.aja("--peruuta")
        self.assertEqual(r.returncode, 2, r.stdout); self.assertEnnallaan()

    def test_tuntematon_valinta(self):
        self.assertEqual(self.aja("--ihme").returncode, 2)


if __name__ == "__main__":
    unittest.main()
