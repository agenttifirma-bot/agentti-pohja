"""Testit isanta/varmuuskopio-drive.sh: rclone-valejaljitelma (aina) ja oikea rclone crypt (jos asennettu)."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Skripti kayttaa Linux-tyokaluja (flock, stat -c, find -printf, bash 4): macOS-ajossa ohitetaan.
LINUX = sys.platform.startswith("linux") and all(shutil.which(x) for x in ("bash", "flock"))

SKRIPTI = Path(__file__).resolve().parent.parent / "isanta" / "varmuuskopio-drive.sh"

VALE = """#!/bin/bash
# rclone-vale: kirjaa argumentit; sync/delete tallentaa suodatintiedoston; copyto kopioi $VALE_KOHDE:sta.
if [ "$1" = listremotes ]; then echo "${VALE_TYYPPI-drive-crypt: crypt}"; exit 0; fi
echo "$*" >> "$VALE_LOKI"
komento=""; prev=""
for a in "$@"; do
  case "$a" in sync|delete|copyto) [ -z "$komento" ] && komento=$a ;; esac
  if [ "$prev" = "--exclude-from" ] || [ "$prev" = "--include-from" ]; then cat "$a" > "$VALE_LOKI.$komento"; fi
  prev=$a
done
if [ "$komento" = copyto ]; then
  nimi=$(basename "${@: -2:1}")
  cp "$VALE_KOHDE/$nimi" "${@: -1}"
fi
exit ${VALE_KOODI:-0}
"""

DUMPIT = [
    "vzdump-lxc-110-2026_10_28-02_00_01.tar.zst", "vzdump-lxc-110-2026_10_28-02_00_01.log",
    "vzdump-lxc-110-2026_10_29-02_00_01.tar.zst", "vzdump-lxc-110-2026_10_30-02_00_01.tar.zst",
    "vzdump-lxc-110-2026_10_31-02_00_01.tar.zst", "vzdump-lxc-111-2026_10_31-02_00_01.tar.zst",
    "vzdump-qemu-200-2026_10_31-02_30_00.vma.zst",
]


@unittest.skipUnless(LINUX, "vaatii Linuxin ja flockin")
class Pohja(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.dump = t / "dump"; self.dump.mkdir()
        self.kohde = t / "kohde"; self.kohde.mkdir()
        for n in DUMPIT:
            (self.dump / n).write_bytes(n.encode() * 3)
        self.vale = t / "rclone"
        self.vale.write_text(VALE); self.vale.chmod(self.vale.stat().st_mode | stat.S_IXUSR)
        self.valeloki = t / "vale.log"
        self.loki = t / "ajo.log"
        self.env = {
            "PATH": os.environ["PATH"], "DUMP_DIR": str(self.dump), "REMOTE": "drive-crypt:proxmox",
            "RCLONE": str(self.vale), "LOKI": str(self.loki), "LUKKO": str(t / "lukko"),
            "VALE_LOKI": str(self.valeloki), "VALE_KOHDE": str(self.kohde),
            "ASETUS_TIEDOSTO": str(t / "ei-ole.env"), "SAILYTA": "2", "VAADITUT_KONTIT": "",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def aja(self, *args, **env):
        e = dict(self.env); e.update(env)
        return subprocess.run(["bash", str(SKRIPTI), *args], env=e, capture_output=True, text=True, timeout=60)


class ValeTesti(Pohja):
    def test_sync_rajaa_kopiot_ja_poistaa_vanhat(self):
        r = self.aja()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rivit = self.valeloki.read_text().splitlines()
        self.assertTrue(any(" sync " in " " + x + " " and "--bwlimit 8M" in x for x in rivit))
        self.assertTrue(any(" delete " in " " + x + " " for x in rivit))
        vanhat = Path(str(self.valeloki) + ".sync").read_text().splitlines()
        # kontti 110: 4 dumppia, SAILYTA=2 -> kaksi vanhinta pois (myos .log)
        self.assertEqual(sorted(vanhat), ["/vzdump-lxc-110-2026_10_28-02_00_01.*", "/vzdump-lxc-110-2026_10_29-02_00_01.*"])
        self.assertIn("valmis", self.loki.read_text())

    def test_kuiva_ajo_ei_pingaa_ja_antaa_dry_run(self):
        r = self.aja("--kuiva", KUMA_PUSH_URL="http://127.0.0.1:9/push/x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rivi in self.valeloki.read_text().splitlines():
            self.assertIn("--dry-run", rivi)
        self.assertNotIn("Kuma", r.stdout)

    def test_ei_crypt_kohdetta_ei_siirreta_mitaan(self):
        for tyyppi in ("drive: drive", "muu-crypt: crypt", ""):
            self.valeloki.unlink(missing_ok=True)
            r = self.aja(VALE_TYYPPI=tyyppi)
            self.assertEqual(r.returncode, 1, tyyppi)
            self.assertIn("ei ole crypt-tyyppinen", r.stdout)
            self.assertFalse(self.valeloki.exists(), "rclone sync/delete ei saa kaynnistya")

    def test_vaadittu_kontti_puuttuu_siirtaa_muut_mutta_epaonnistuu(self):
        r = self.aja(VAADITUT_KONTIT="113")
        self.assertEqual(r.returncode, 1)
        self.assertIn("puuttuu lahteesta, tunnus: 113", r.stdout)
        self.assertTrue(any(" sync " in " " + x + " " for x in self.valeloki.read_text().splitlines()))
        self.assertIn("EPAONNISTUI", self.loki.read_text())

    def test_vaadittu_kontti_loytyy(self):
        (self.dump / "vzdump-lxc-113-2026_10_31-02_00_01.tar.zst").write_bytes(b"gitea")
        r = self.aja(VAADITUT_KONTIT="110 113")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("valmis", self.loki.read_text())

    def test_luettelo_ilmoittaa_puuttuvan_vaaditun_kontin(self):
        r = self.aja("--luettelo", VAADITUT_KONTIT="113")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PUUTTUU vaadittu dump, tunnus: 113", r.stdout)

    def test_oletuksena_gitea_113_on_vaadittu(self):
        env = {k: v for k, v in self.env.items() if k != "VAADITUT_KONTIT"}
        r = subprocess.run(["bash", str(SKRIPTI), "--luettelo"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("tunnus: 113", r.stdout)

    def test_virheellinen_vaadittu_tunnus(self):
        self.assertEqual(self.aja(VAADITUT_KONTIT="abc").returncode, 1)

    def test_tyhja_lahde_ei_synkronoida(self):
        for f in self.dump.iterdir():
            f.unlink()
        r = self.aja()
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.valeloki.exists())

    def test_rclone_virhe_antaa_paluukoodin_1(self):
        r = self.aja(VALE_KOODI="3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("EPAONNISTUI", self.loki.read_text())

    def test_lukko_estaa_rinnakkaisen_ajon(self):
        lukko = self.env["LUKKO"]
        p = subprocess.Popen(["flock", lukko, "sleep", "5"])
        try:
            import time; time.sleep(0.5)
            r = self.aja()
            self.assertEqual(r.returncode, 0)
            self.assertIn("toinen ajo kaynnissa", r.stdout)
            self.assertFalse(self.valeloki.exists())
        finally:
            p.kill(); p.wait()

    def test_luettelo_ei_tarvitse_rclonea_eika_tunnuksia(self):
        r = self.aja("--luettelo", RCLONE="/ei/ole/rclonea")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.valeloki.exists())
        rivit = r.stdout.splitlines()
        self.assertIn("OHITETAAN (yli 2 uusinta) vzdump-lxc-110-2026_10_28-02_00_01.tar.zst", rivit)
        self.assertIn("OHITETAAN (yli 2 uusinta) vzdump-lxc-110-2026_10_28-02_00_01.log", rivit)
        self.assertTrue(any(x.startswith("KOPIOIDAAN vzdump-lxc-110-2026_10_31-02_00_01.tar.zst (") for x in rivit))
        self.assertTrue(any(x.startswith("KOPIOIDAAN vzdump-qemu-200-") for x in rivit))
        self.assertEqual(len([x for x in rivit if x.startswith("KOPIOIDAAN")]), 4)
        self.assertEqual(len([x for x in rivit if x.startswith("OHITETAAN")]), 3)

    def test_rclone_conf_ryhmaluettava_hylataan(self):
        conf = Path(self.tmp.name) / "rclone.conf"; conf.write_text("[x]\ntype = local\n")
        conf.chmod(0o644)
        r = self.aja(RCLONE_CONFIG=str(conf))
        self.assertEqual(r.returncode, 1)
        self.assertIn("pitaa olla 600", r.stdout)
        self.assertFalse(self.valeloki.exists())
        conf.chmod(0o600)
        self.assertEqual(self.aja(RCLONE_CONFIG=str(conf)).returncode, 0)

    def test_virheellinen_sailyta(self):
        self.assertEqual(self.aja(SAILYTA="0").returncode, 1)
        self.assertEqual(self.aja(SAILYTA="x").returncode, 1)

    def test_tuntematon_valitsin(self):
        self.assertEqual(self.aja("--poista-kaikki").returncode, 2)

    def test_asetustiedosto_ryhmakirjoitettava_hylataan(self):
        p = Path(self.tmp.name) / "a.env"; p.write_text("SAILYTA=5\n"); p.chmod(0o664)
        self.assertEqual(self.aja(ASETUS_TIEDOSTO=str(p)).returncode, 1)

    def test_kuma_ping_onnistuessa_ja_epaonnistuessa(self):
        curl = Path(self.tmp.name) / "bin"; curl.mkdir()
        c = curl / "curl"; c.write_text('#!/bin/bash\necho "$*" >> "$CURL_LOKI"\n'); c.chmod(0o755)
        cl = Path(self.tmp.name) / "curl.log"
        env = dict(KUMA_PUSH_URL="https://kuma.example/api/push/abc", CURL_LOKI=str(cl),
                   PATH=f"{curl}:{os.environ['PATH']}")
        self.assertEqual(self.aja(**env).returncode, 0)
        self.assertIn("status=up", cl.read_text())
        cl.unlink()
        self.assertEqual(self.aja(VALE_KOODI="1", **env).returncode, 1)
        self.assertIn("status=down", cl.read_text())

    def test_palautustesti_tasmaa_ja_havaitsee_eron(self):
        # pienin uusimmista: kaikki samankokoisia nimen mukaan -> haetaan jokin; kopioidaan vastaava kohteeseen
        r = self.aja("--palautustesti", VALE_KOHDE=str(self.dump))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("palautustesti OK", r.stdout)
        kopio = self.kohde
        for n in DUMPIT:
            (kopio / n).write_bytes(b"rikki")
        r = self.aja("--palautustesti")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ei tasmaa", r.stdout)


@unittest.skipUnless(shutil.which("rclone"), "rclone ei ole asennettu")
class OikeaCryptTesti(Pohja):
    """Paikallinen local + crypt -kohde: synkronointi, salattu sisalto ja purku tiivisteineen."""

    def test_salattu_kopio_purkautuu_ja_tiivisteet_tasmaavat(self):
        t = Path(self.tmp.name)
        levy = t / "levy"; levy.mkdir()
        conf = t / "rclone.conf"
        obs = lambda s: subprocess.run(["rclone", "obscure", s], capture_output=True, text=True, check=True).stdout.strip()
        conf.write_text(
            f"[paikallinen]\ntype = local\n\n[drive-crypt]\ntype = crypt\nremote = paikallinen:{levy}\n"
            f"password = {obs('testisalasana-yksi')}\npassword2 = {obs('testisuola-kaksi')}\n"
            "filename_encryption = standard\n")
        conf.chmod(0o600)
        env = {"RCLONE_CONFIG": str(conf), "RCLONE": shutil.which("rclone"), "REMOTE": "drive-crypt:proxmox"}
        r = self.aja(**env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # levylla ei saa nakya selkeita nimia
        nimet = " ".join(str(p) for p in levy.rglob("*"))
        self.assertNotIn("vzdump", nimet)
        r = self.aja("--palautustesti", **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("palautustesti OK", r.stdout)
        # purku kokonaisuudessaan: vain SAILYTA uusinta per kontti
        ulos = t / "ulos"
        subprocess.run(["rclone", "--config", str(conf), "copy", "drive-crypt:proxmox", str(ulos)], check=True)
        nimet = sorted(p.name for p in ulos.iterdir())
        self.assertNotIn("vzdump-lxc-110-2026_10_28-02_00_01.tar.zst", nimet)
        self.assertIn("vzdump-lxc-110-2026_10_31-02_00_01.tar.zst", nimet)
        for n in nimet:
            self.assertEqual((ulos / n).read_bytes(), (self.dump / n).read_bytes())


if __name__ == "__main__":
    unittest.main()
