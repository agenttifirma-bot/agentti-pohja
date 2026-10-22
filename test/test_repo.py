"""Repon rakenteen tarkistukset: ASCII, systemd-kovennus, luo.py, komentorivi."""
import contextlib
import io
import os
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
        # karkea tarkistus: ei avainmaisia merkkijonoja eika oikeita osoitteita
        epailyttavat = ("sk-or-", "sk-ant-", "api.telegram.org/bot1", "BEGIN PRIVATE KEY", "100.64.", "tail956680")
        for paate in (".py", ".md", ".mall", ".yml"):
            for polku in tiedostot(paate):
                if polku == os.path.abspath(__file__):
                    continue  # tama tiedosto sisaltaa epailyttavat mallit itse
                with open(polku, encoding="utf-8") as f:
                    teksti = f.read()
                for e in epailyttavat:
                    self.assertNotIn(e, teksti, "%s sisaltaa %s" % (polku, e))


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
