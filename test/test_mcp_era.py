"""hiekkalaatikko/mcp_era.py: listan luku, kuiva-ajo, erajo valeajajalla (ei oikeaa konttia, verkkoa eika vierasta koodia)."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
HL = JUURI / "hiekkalaatikko"


def lataa():
    spec = importlib.util.spec_from_file_location("mcp_era_testi", HL / "mcp_era.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


me = lataa()
RAPORTTI = {"palvelin": "x", "loydokset": []}


class ValeAjaja:
    """Kirjaa kutsut. Simuloi git clonen luomalla hakemiston; muut vaiheet palauttavat ohjelmoidun tuloksen."""

    def __init__(self, doctor=(0, json.dumps(RAPORTTI), "", False), pkg=None, epaonnistuu=None):
        self.kutsut = []
        self.doctor = doctor
        self.pkg = {"name": "x", "main": "dist/index.js", "scripts": {"build": "tsc"}} if pkg is None else pkg
        self.epaonnistuu = epaonnistuu or {}

    def __call__(self, kmd, cwd, env, aikaraja):
        self.kutsut.append((list(kmd), cwd, dict(env), aikaraja))
        if kmd[0] == "git":
            if "git" in self.epaonnistuu:
                return 128, "", "fatal: ei loydy", False
            os.makedirs(kmd[-1])
            if self.pkg:
                with open(os.path.join(kmd[-1], "package.json"), "w") as f:
                    json.dump(self.pkg, f)
            return 0, "", "", False
        if kmd[0] in self.epaonnistuu:
            return self.epaonnistuu[kmd[0]]
        if kmd[0] == "npm":
            return 0, "", "", False
        if kmd[0] == "mcp-doctor" and "--version" in kmd:
            return 0, "0.4.0\n", "", False
        if kmd[0] == "mcp-doctor":
            return self.doctor
        raise AssertionError("odottamaton komento %r" % (kmd,))


class ListaTesti(unittest.TestCase):
    def test_kelvolliset_ja_virheelliset_rivit(self):
        r = me.lue_lista(
            "# kommentti\n\nhttps://github.com/a/b\n"
            "https://github.com/c/d node dist/s.js --stdio  # loppukommentti\n"
            "file:///etc/passwd\nssh://git@github.com/a/b\nhttps://github.com/a/b/tree/x\n"
            "https://evil.example/a/b\nhttps://github.com/a/b -rf\nhttps://github.com/a/b 'rikki\n")
        self.assertEqual(r[0], ("https://github.com/a/b", None, None))
        self.assertEqual(r[1], ("https://github.com/c/d", ["node", "dist/s.js", "--stdio"], None))
        self.assertTrue(all(x[2] for x in r[2:]), r)
        self.assertEqual(len(r), 8)

    def test_komento_ei_voi_alkaa_valitsimella(self):
        self.assertTrue(me.lue_lista("https://github.com/a/b --evil")[0][2])


class PaattelyTesti(unittest.TestCase):
    def kokeile(self, pkg):
        with tempfile.TemporaryDirectory() as d:
            if pkg is not None:
                Path(d, "package.json").write_text(json.dumps(pkg))
            return me.paattele_komento(d)

    def test_bin_main_ja_puute(self):
        self.assertEqual(self.kokeile({"bin": "cli.js"}), ["node", "cli.js"])
        self.assertEqual(self.kokeile({"bin": {"a": "b/c.js"}, "main": "x.js"}), ["node", "b/c.js"])
        self.assertEqual(self.kokeile({"main": "./i.js"}), ["node", "i.js"])
        self.assertIsNone(self.kokeile({"name": "x"}))
        self.assertIsNone(self.kokeile(None))
        self.assertIsNone(self.kokeile([1]))

    def test_polku_ei_karkaa_repon_ulkopuolelle(self):
        self.assertIsNone(self.kokeile({"bin": "../../etc/passwd"}))
        self.assertIsNone(self.kokeile({"main": "/etc/passwd"}))


class EraTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ulos = os.path.join(self.tmp, "era.json")
        self.tyo = os.path.join(self.tmp, "tyo")

    def aja(self, lista, ajaja, **kw):
        return me.aja_era(lista, self.ulos, self.tyo, ajaja=ajaja, **kw)

    def test_kuiva_ajo_ei_kutsu_mitaan_eika_luo_tyohakemistoa(self):
        aj = ValeAjaja()
        t = self.aja("https://github.com/a/b\nhttps://github.com/c/d node x.js\nroska\n", aj, kuiva=True)
        self.assertEqual(aj.kutsut, [])
        self.assertFalse(os.path.exists(self.tyo))
        self.assertEqual([r["tila"] for r in t["repot"]], ["kuiva", "kuiva", "virheellinen_rivi"])
        self.assertTrue(t["kuiva"])
        me.tarkista_tiedosto(self.ulos)

    def test_onnistunut_ja_loydoksia(self):
        aj = ValeAjaja()
        t = self.aja("https://github.com/a/b\n", aj)
        r = t["repot"][0]
        self.assertEqual((r["tila"], r["poistumiskoodi"], r["raportti"]), ("ok", 0, RAPORTTI))
        self.assertEqual(r["komento"], ["node", "dist/index.js"])
        self.assertEqual(t["doctor_versio"], "0.4.0")
        nimet = [k[0][0] for k in aj.kutsut]
        self.assertEqual(nimet, ["mcp-doctor", "git", "npm", "npm", "mcp-doctor"])
        doctor = aj.kutsut[-1][0]
        self.assertEqual(doctor[:3], ["mcp-doctor", "--json", "--timeout-ms"])
        self.assertEqual(doctor[-3:], ["--", "node", "dist/index.js"][-3:])
        shutil.rmtree(self.tyo)
        t2 = self.aja("https://github.com/a/b\n", ValeAjaja_koodi(1))
        self.assertEqual(t2["repot"][0]["tila"], "loydoksia")
        self.assertEqual(t2["yhteenveto"], {"repoja": 1, "tilat": {"loydoksia": 1}})

    def test_kloonaus_pelkka_url_valitsimien_jalkeen(self):
        aj = ValeAjaja()
        self.aja("https://github.com/a/b\n", aj)
        git = [k for k in aj.kutsut if k[0][0] == "git"][0][0]
        self.assertEqual(git[:5], ["git", "clone", "--depth", "1", "--no-tags"])
        self.assertEqual(git[5], "--")
        self.assertEqual(git[6], "https://github.com/a/b")
        self.assertTrue(git[7].startswith(self.tyo))

    def test_ymparisto_on_puhdas(self):
        os.environ["LITELLM_API_KEY"] = "ei-pida-vuotaa"
        self.addCleanup(os.environ.pop, "LITELLM_API_KEY", None)
        aj = ValeAjaja()
        self.aja("https://github.com/a/b\n", aj)
        for _, _, env, _ in aj.kutsut:
            self.assertNotIn("LITELLM_API_KEY", env)
            self.assertEqual(env["HTTPS_PROXY"], me.OLETUS_PROXY)
            self.assertFalse([k for k in env if "KEY" in k or "TOKEN" in k or "SECRET" in k])

    def test_vaihevirheet_saavat_oman_tilansa(self):
        taul = [
            ({"git": 1}, "kloonaus_epaonnistui", None),
            ({"npm": (1, "", "ERR", False)}, "asennus_epaonnistui", None),
            ({"mcp-doctor": (None, "", "", True)}, "aikakatkaisu", None),
            ({}, "ei_kaynnistyskomentoa", {"name": "x"}),
        ]
        for epa, tila, pkg in taul:
            with self.subTest(tila):
                aj = ValeAjaja(epaonnistuu=epa if "git" not in epa else {"git": 1}, pkg=pkg)
                if "mcp-doctor" in epa:
                    aj.doctor = epa["mcp-doctor"]
                    aj.epaonnistuu = {}
                shutil.rmtree(self.tyo, ignore_errors=True)
                t = self.aja("https://github.com/a/b\n", aj)
                self.assertEqual(t["repot"][0]["tila"], tila)

    def test_rakennusvirhe(self):
        class A(ValeAjaja):
            def __call__(s, kmd, cwd, env, ar):
                if kmd[:2] == ["npm", "run"]:
                    return 2, "", "tsc kaatui", False
                return ValeAjaja.__call__(s, kmd, cwd, env, ar)
        self.assertEqual(self.aja("https://github.com/a/b\n", A())["repot"][0]["tila"], "rakennus_epaonnistui")

    def test_doctorin_virheellinen_json_ja_kaytto_virhe(self):
        self.assertEqual(self.aja("https://github.com/a/b\n", ValeAjaja(doctor=(0, "ei json", "", False)))["repot"][0]["tila"], "json_virheellinen")
        shutil.rmtree(self.tyo)
        self.assertEqual(self.aja("https://github.com/a/b\n", ValeAjaja(doctor=(2, "", "kayttovirhe", False)))["repot"][0]["tila"], "kaytto_virhe")
        shutil.rmtree(self.tyo)
        self.assertEqual(self.aja("https://github.com/a/b\n", ValeAjaja(doctor=(3, "", "x", False)))["repot"][0]["tila"], "sisainen_virhe")

    def test_iso_raportti_katkaistaan(self):
        iso = json.dumps({"x": "a" * (me.RAPORTTI_MAX + 10)})
        r = self.aja("https://github.com/a/b\n", ValeAjaja(doctor=(0, iso, "", False)))["repot"][0]
        self.assertTrue(r["raportti"]["katkaistu"])

    def test_aikarajat_vain_pienenevat(self):
        t = self.aja("https://github.com/a/b\n", ValeAjaja(), repo_aikaraja=10 ** 6, era_aikaraja=10 ** 6)
        self.assertEqual((t["repo_aikaraja_s"], t["era_aikaraja_s"]), (me.REPO_AIKARAJA_MAX, me.ERA_AIKARAJA_MAX))

    def test_erakatto_ohittaa_loput(self):
        aj = ValeAjaja()
        orig = me.time.monotonic
        kello = iter([0.0] + [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6] + [10 ** 6] * 50)
        me.time.monotonic = lambda: next(kello)
        try:
            t = self.aja("https://github.com/a/b\nhttps://github.com/c/d\n", aj, era_aikaraja=10)
        finally:
            me.time.monotonic = orig
        self.assertEqual(t["repot"][1]["tila"], "ohitettu_aikakatko")

    def test_tyhja_ja_liian_pitka_lista(self):
        with self.assertRaises(me.Virhe):
            self.aja("# vain kommentti\n", ValeAjaja(), kuiva=True)
        with self.assertRaises(me.Virhe):
            self.aja("".join("https://github.com/a/r%d\n" % i for i in range(me.REPOJA_MAX + 1)), ValeAjaja(), kuiva=True)

    def test_tulos_on_ascii_json(self):
        self.aja("https://github.com/a/b\n", ValeAjaja(doctor=(0, json.dumps({"viesti": "k\u00e4\u00e4nt\u00f6"}), "", False)))
        raaka = Path(self.ulos).read_bytes()
        raaka.decode("ascii")
        me.tarkista_tiedosto(self.ulos)
        self.assertFalse(os.path.exists(self.ulos + ".tmp"))

    def test_tarkista_hylkaa_rikkinaisen(self):
        for d in ({}, {"skeema": 1, "repot": "x"}, {"skeema": 1, "repot": [{"repo": "a", "tila": "outo"}], "yhteenveto": {"repoja": 1}},
                  {"skeema": 1, "repot": [], "yhteenveto": {"repoja": 3}}):
            with self.assertRaises(me.Virhe):
                me.tarkista_tulos(d)

    def test_oikea_ajaja_aikakatko_tappaa_ryhman(self):
        koodi, _, _, katko = me.suorita(["sleep", "30"], self.tmp, {"PATH": os.environ["PATH"]}, 1)
        self.assertTrue(katko)
        self.assertIsNone(koodi)
        koodi, ulos, _, katko = me.suorita(["echo", "hei"], self.tmp, {"PATH": os.environ["PATH"]}, 5)
        self.assertEqual((koodi, ulos.strip(), katko), (0, "hei", False))


def ValeAjaja_koodi(koodi):
    return ValeAjaja(doctor=(koodi, json.dumps(RAPORTTI), "", False))


class KomentoriviTesti(unittest.TestCase):
    def test_kuiva_ajo_komentorivilta_ei_koske_verkkoon(self):
        with tempfile.TemporaryDirectory() as d:
            lista, ulos = os.path.join(d, "l.txt"), os.path.join(d, "u.json")
            shutil.copy(HL / "mcp-era-lista.esimerkki.txt", lista)
            p = subprocess.run(["python3", "-I", str(HL / "mcp_era.py"), "aja", "--lista", lista, "--ulos", ulos,
                                "--tyo", os.path.join(d, "tyo"), "--kuiva"], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), {"repoja": 2, "tilat": {"kuiva": 2}})
            self.assertFalse(os.path.exists(os.path.join(d, "tyo")))
            p = subprocess.run(["python3", "-I", str(HL / "mcp_era.py"), "tarkista", ulos], capture_output=True, text=True, timeout=30)
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "ok"))

    def test_virhe_tulostaa_vain_tyypin(self):
        p = subprocess.run(["python3", "-I", str(HL / "mcp_era.py"), "tarkista", "/ei/ole/olemassa"], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr.strip(), "virhe: FileNotFoundError")


class AsennusSkriptiTesti(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash puuttuu")
    def test_syntaksi_ja_ascii_ja_ei_salaisuuksia(self):
        p = HL / "mcp-asenna.sh"
        self.assertEqual(subprocess.run(["bash", "-n", str(p)]).returncode, 0)
        b = p.read_bytes()
        self.assertFalse([x for x in b if x > 127])
        self.assertNotIn(b"\r", b)
        for kuvio in (b"sk-", b"ghp_", b"github_pat_", b"BEGIN "):
            self.assertNotIn(kuvio, b)

    def test_verkkokokeet_kattavat_lan_ja_tailscale(self):
        s = (HL / "mcp-asenna.sh").read_text()
        for osa in ("192.168.1.116", "192.168.1.121", "100.87.110.22", "1.1.1.1", "sha256sum -c"):
            self.assertIn(osa, s)


if __name__ == "__main__":
    unittest.main()
