"""Repon rakenteen tarkistukset: ASCII, systemd-kovennus, luo.py, komentorivi."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import luo
from agentti import __main__ as cli

JUURI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUOJAT = [
    "NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true",
    "PrivateDevices=true", "RestrictNamespaces=true", "LockPersonality=true",
    "MemoryDenyWriteExecute=true", "CapabilityBoundingSet=", "ProtectKernelTunables=true",
    "ProtectKernelModules=true", "ProtectControlGroups=true",
]

# Vuotovahti: yksityiset ja Tailscale-osoitteet seka .ts.net-nimet. Tailnetin nimea ei kirjoiteta tahan.
OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
SISAVERKKO_RE = re.compile(
    r"(?<![0-9.])(?:"
    r"100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])"        # 100.64.0.0/10
    r"|192\.168"                                              # 192.168.0.0/16
    r"|10\.%(o)s"                                             # 10.0.0.0/8
    r"|172\.(?:1[6-9]|2[0-9]|3[01])"                          # 172.16.0.0/12
    r")\.%(o)s\.%(o)s(?![0-9])" % {"o": OCTET})
TSNET_RE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b", re.IGNORECASE)
# Sallitut poikkeukset: testien keksityt osoitteet (tiedosto -> sallitut osoitteet).
# 127.0.0.1 ja 0.0.0.0 eivat kuulu kiellettyihin alueisiin, joten ne eivat tarvitse poikkeusta.
SALLITUT = {
    "test_portti_tyokalut.py": {"192.168.7.7", "10.0.0.5", "100.101.102.103", "100.127.255.255"},
    "test_repo.py": set(),
}


def osoitteet(teksti, polku=""):
    sallitut = SALLITUT.get(os.path.basename(polku), set())
    loydot = [m.group(0) for m in SISAVERKKO_RE.finditer(teksti) if m.group(0) not in sallitut]
    return loydot + [m.group(0) for m in TSNET_RE.finditer(teksti)]


def tiedostot(paate):
    for hakemisto, _, nimet in os.walk(JUURI):
        if any(osa in hakemisto for osa in (".git", "__pycache__", "tila")):
            continue
        for n in nimet:
            if n.endswith(paate):
                yield os.path.join(hakemisto, n)


class RakenneTesti(unittest.TestCase):
    def test_koodi_on_ascii(self):
        """Koodi liitetaan palvelimelle paste-tavalla: umlautit rikkoisivat sen."""
        for polku in list(tiedostot(".py")) + list(tiedostot(".mall")):
            with open(polku, "rb") as f:
                sisalto = f.read()
            try:
                sisalto.decode("ascii")
            except UnicodeDecodeError as e:
                self.fail("%s: ei-ASCII-merkki kohdassa %d" % (os.path.relpath(polku, JUURI), e.start))

    def test_service_pohjassa_kovennus_ja_oikeudet(self):
        with open(os.path.join(JUURI, "systemd", "agentti.service.mall")) as f:
            teksti = f.read()
        for suoja in SUOJAT:
            self.assertIn("\n" + suoja + "\n", "\n" + teksti, suoja)
        self.assertIn("User=agentti", teksti)
        self.assertNotIn("User=root", teksti)
        self.assertIn("ReadWritePaths=/var/lib/agentti/@NIMI@", teksti)
        self.assertIn("--llm --send", teksti)
        self.assertIn("TimeoutStartSec=", teksti)

    def test_timer_pohja(self):
        with open(os.path.join(JUURI, "systemd", "agentti.timer.mall")) as f:
            teksti = f.read()
        for rivi in ("OnCalendar=", "Persistent=true", "RandomizedDelaySec=", "WantedBy=timers.target"):
            self.assertIn(rivi, teksti)

    def test_ei_salaisuuksia_repossa(self):
        # karkea tarkistus: ei avainmaisia merkkijonoja eika infran osoitteita
        epailyttavat = ("sk-or-", "sk-ant-", "api.telegram.org/bot1", "BEGIN PRIVATE KEY")
        for paate in (".py", ".md", ".mall", ".yml"):
            for polku in tiedostot(paate):
                if polku == os.path.abspath(__file__):
                    continue  # tama tiedosto sisaltaa epailyttavat mallit itse
                with open(polku, encoding="utf-8") as f:
                    teksti = f.read()
                for e in epailyttavat:
                    self.assertNotIn(e, teksti, "%s sisaltaa %s" % (polku, e))
                self.assertEqual(osoitteet(teksti, polku), [], "%s sisaltaa sisaverkon osoitteen tai .ts.net-nimen" % polku)


class VuotovahtiTesti(unittest.TestCase):
    def test_kielletyt_alueet_loytyvat(self):
        for o in ("100.64.0.1", "100.127.255.254", "100.87.1.2", "192.168.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.1"):
            self.assertEqual(osoitteet("ssh root@" + o), [o], o)
        self.assertEqual(osoitteet("host.ZZZ.ts.net"), ["host.ZZZ.ts.net"])

    def test_sallitut_ja_ulkopuoliset(self):
        for o in ("127.0.0.1", "0.0.0.0", "100.63.255.255", "100.128.0.1", "172.15.0.1", "172.32.0.1", "8.8.8.8", "1.100.64.1.2x"):
            self.assertEqual(osoitteet(o), [], o)

    def test_testien_keksityt_osoitteet_vain_nimetyssa_tiedostossa(self):
        self.assertEqual(osoitteet("192.168.7.7", "test_portti_tyokalut.py"), [])
        self.assertEqual(osoitteet("192.168.7.7", "muu.py"), ["192.168.7.7"])


class LuoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for osa in ("agentti", "systemd", "test"):
            shutil.copytree(os.path.join(JUURI, osa), os.path.join(self.tmp.name, osa),
                            ignore=shutil.ignore_patterns("__pycache__"))

    def test_luo_agentti(self):
        luodut = luo.luo("uutiset", self.tmp.name)
        self.assertEqual(len(luodut), 4)
        self.assertIn(os.path.join("test", "test_uutiset.py"), luodut)
        with open(os.path.join(self.tmp.name, "agentti", "agentit", "uutiset.py")) as f:
            self.assertIn('NIMI = "uutiset"', f.read())
        with open(os.path.join(self.tmp.name, "systemd", "agentti-uutiset.service")) as f:
            teksti = f.read()
        self.assertIn("--agentti uutiset", teksti)
        self.assertNotIn("@NIMI@", teksti)
        with open(os.path.join(self.tmp.name, "systemd", "agentti-uutiset.timer")) as f:
            self.assertNotIn("@NIMI@", f.read())

    def test_luotu_testi_menee_lapi_ja_kaatuu_rikkinaiselle_agentille(self):
        luo.luo("uutiset", self.tmp.name)
        ymp = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", "test.test_uutiset"], cwd=self.tmp.name,
                           capture_output=True, text=True, env=ymp)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("Ran 4 tests", r.stderr)
        # rikki: agentti ei kayta verkkoa kuivana -> testin pitaa huomata (kerays kaatuu)
        polku = os.path.join(self.tmp.name, "agentti", "agentit", "uutiset.py")
        with open(polku, encoding="utf-8") as f:
            teksti = f.read()
        with open(polku, "w", encoding="utf-8") as f:
            f.write(teksti.replace("def kerays():", "def kerays():\n    raise RuntimeError('rikki')\n\n\ndef _vanha():"))
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", "test.test_uutiset"], cwd=self.tmp.name,
                           capture_output=True, text=True, env=ymp)
        self.assertNotEqual(r.returncode, 0)

    def test_ei_ylikirjoita(self):
        luo.luo("uutiset", self.tmp.name)
        with self.assertRaises(FileExistsError):
            luo.luo("uutiset", self.tmp.name)

    def _maaritys(self, **muutos):
        with open(os.path.join(JUURI, "maaritys.esimerkki.json"), encoding="utf-8") as f:
            m = json.load(f)
        m["nimi"] = "uutiset"
        m["ohje_tiedosto"] = "ohjeet/uutiset.md"
        m.update(muutos)
        polku = os.path.join(self.tmp.name, "m.json")
        with open(polku, "w", encoding="utf-8") as f:
            json.dump(m, f)
        return polku

    def test_luo_maarityksella(self):
        luodut = luo.luo("uutiset", self.tmp.name, maaritys_polku=self._maaritys())
        self.assertEqual(len(luodut), 7)
        for rel in ("maaritykset/uutiset.json", "ohjeet/uutiset.md", "evalit/uutiset.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, rel)), rel)
        with open(os.path.join(self.tmp.name, "evalit", "uutiset.json"), encoding="utf-8") as f:
            self.assertIn("30 %", json.load(f)["mittari"])

    def test_virheellinen_maaritys_ei_luo_mitaan(self):
        polku = self._maaritys(budjetti_usd_paivassa=9999)
        with self.assertRaises(Exception):
            luo.luo("uutiset", self.tmp.name, maaritys_polku=polku)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "agentti", "agentit", "uutiset.py")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "maaritykset")))

    def test_maarityksen_nimi_ei_vastaa(self):
        with self.assertRaises(ValueError):
            luo.luo("uutiset", self.tmp.name, maaritys_polku=self._maaritys(nimi="muu"))

    def test_virheelliset_nimet(self):
        for nimi in ("", "A", "../x", "esimerkki", "x y", "1abc", "a" * 40, "a;rm"):
            with self.assertRaises(ValueError, msg=nimi):
                luo.luo(nimi, self.tmp.name)


class KomentoriviTesti(unittest.TestCase):
    def aja(self, *args):
        ulos, virhe = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(ulos), contextlib.redirect_stderr(virhe):
            koodi = cli.main(list(args))
        return koodi, ulos.getvalue(), virhe.getvalue()

    def test_kuiva_ajo(self):
        with tempfile.TemporaryDirectory() as tila:
            koodi, ulos, _ = self.aja("--tila", tila)
        self.assertEqual(koodi, 0)
        self.assertIn("kuiva-ajo", ulos)

    def test_vaara_nimi(self):
        for nimi in ("../x", "ei_ole_olemassa", "A", "__init__", "esimerkki.x"):
            koodi, _, virhe = self.aja("--agentti", nimi)
            self.assertEqual(koodi, 2, nimi)
            self.assertIn("virhe", virhe)

    def test_env_tiedosto_puuttuu(self):
        koodi, _, _ = self.aja("--env", "/ei/ole/tata.env")
        self.assertEqual(koodi, 2)

    def test_llm_ilman_asetuksia_palauttaa_1(self):
        for avain in ("LLM_BASE_URL", "LLM_API_KEY"):
            os.environ.pop(avain, None)
        with tempfile.TemporaryDirectory() as tila:
            koodi, _, virhe = self.aja("--tila", tila, "--llm")
        self.assertEqual(koodi, 1)
        self.assertIn("llm_asetus", virhe)


if __name__ == "__main__":
    unittest.main()
