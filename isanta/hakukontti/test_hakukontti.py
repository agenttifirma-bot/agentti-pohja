"""Hakukontin pohjat, asennusohje ja moottorimittaus. Ei verkkoa: mittaus testataan valepalvelimella silmukkaosoitteessa."""
import http.server
import io
import json
import os
import random
import re
import threading
import unittest
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout

from isanta.hakukontti import mittaa_moottorit as mm

TAMA = os.path.dirname(os.path.abspath(__file__))
JUURI = os.path.dirname(os.path.dirname(TAMA))
OHJE = os.path.join(JUURI, "docs", "aivo-hakukontti.md")


def lue(nimi):
    with open(os.path.join(TAMA, nimi), encoding="utf-8") as f:
        return f.read()


def aktiiviset(teksti, kommentti="#"):
    """Rivit ilman kommentteja ja tyhjia riveja."""
    return [r.strip() for r in teksti.splitlines() if r.strip() and not r.strip().startswith(kommentti)]


class PohjaTesti(unittest.TestCase):
    def test_searxng_vain_silmukka_ja_tor(self):
        s = lue("searxng-settings.yml")
        self.assertIn('bind_address: "127.0.0.1"', s)
        self.assertIn("- socks5h://127.0.0.1:9050", s)        # socks5h: myos DNS Torin kautta
        self.assertNotIn("socks5://", s)
        self.assertIn("using_tor_proxy: true", s)
        self.assertIn('autocomplete: ""', s)
        self.assertIn("image_proxy: false", s)
        self.assertIn("limiter: false", s)
        self.assertIn("public_instance: false", s)
        self.assertIn("debug: false", s)
        self.assertRegex(s, r"formats:\s*\n\s*- json\s*\n")
        self.assertNotRegex(s, r"formats:\s*\n(\s*- \w+\s*\n)*\s*- html")

    def test_searxng_avain_on_paikkamerkki(self):
        s = lue("searxng-settings.yml")
        self.assertIn('secret_key: "@SALAINEN_AVAIN@"', s)
        self.assertEqual(len(re.findall(r"secret_key:", s)), 1)

    def test_torrc_pelkka_asiakas(self):
        rivit = aktiiviset(lue("torrc"))
        self.assertIn("SocksPort 127.0.0.1:9050 IsolateSOCKSAuth IsolateDestAddr", rivit)
        for r in ("SocksPolicy reject *", "DNSPort 0", "TransPort 0", "ControlPort 0", "ClientOnly 1",
                  "ExitRelay 0", "ORPort 0", "SafeLogging 1"):
            self.assertIn(r, rivit)
        # SOCKS-portti ei saa kuunnella muualla kuin silmukassa.
        for r in rivit:
            if r.startswith("SocksPort"):
                self.assertTrue(r.split()[1].startswith("127.0.0.1:"), r)
        self.assertFalse(any(r.startswith("ControlPort ") and r != "ControlPort 0" for r in rivit))

    def test_nftables_kill_switch(self):
        rivit = aktiiviset(lue("nftables.conf"))
        teksti = "\n".join(rivit)
        for ketju in ("input", "forward", "output"):
            self.assertRegex(teksti, r"type filter hook %s priority filter; policy drop;" % ketju)
        self.assertIn('oif "lo" meta skuid "searxng" tcp dport 9050 accept', rivit)
        self.assertIn('oif "lo" meta skuid "aivo-haku" tcp dport { 8888, 9050 } accept', rivit)
        self.assertIn('oif "lo" meta skuid "_apt" tcp dport 9050 accept', rivit)
        self.assertIn('iifname "eth0" ip saddr $CT122 tcp dport 8890 ct state new accept', rivit)
        # Sovelluskayttajilla ei ole yhtaan muuta sallivaa saantoa.
        for kayttaja in ("searxng", "aivo-haku", "_apt"):
            omat = [r for r in rivit if 'skuid "%s"' % kayttaja in r]
            self.assertEqual(len(omat), 1, kayttaja)
            self.assertTrue(omat[0].startswith('oif "lo"'), omat[0])
        # Nimipalvelua ei sallita kenellekaan.
        self.assertNotRegex(teksti, r"dport\s+(\{[^}]*\b53\b|53\b)")
        # Lahiverkkojen esto tulee ennen Torin yleista sallintaa.
        esto = rivit.index('meta skuid "debian-tor" ip daddr $LAHIVERKOT4 counter drop')
        esto6 = rivit.index('meta skuid "debian-tor" ip6 daddr { fc00::/7, fe80::/10 } counter drop')
        salli = rivit.index('meta skuid "debian-tor" oifname "eth0" accept')
        self.assertLess(esto, salli)
        self.assertLess(esto6, salli)
        # Ainoa ehdoton ulos-sallinta eth0:aan on debian-torilla.
        ulos = [r for r in rivit if 'oifname "eth0"' in r and r.endswith("accept")]
        self.assertEqual(ulos, ['meta skuid "debian-tor" oifname "eth0" accept'])
        self.assertIn('include "/etc/nftables.d/hakukontti-osoitteet.nft"', rivit)

    def test_systemd_yksikko(self):
        s = lue("searxng.service")
        for r in ("User=searxng", "NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true",
                  "PrivateTmp=true", "CapabilityBoundingSet=", "--host 127.0.0.1"):
            self.assertIn(r, s)
        self.assertNotIn("User=root", s)
        self.assertNotIn("--access-log", s)

    def test_searxng_vaatii_palomuurin(self):
        # Ilman kill switchia (nftables) palvelu ei saa kaynnistya.
        rivit = aktiiviset(lue("searxng.service"))
        unit = rivit[rivit.index("[Unit]") + 1:rivit.index("[Service]")]
        vaatii = [r.split("=", 1)[1].split() for r in unit if r.startswith(("Requires=", "BindsTo="))]
        self.assertIn("nftables.service", sum(vaatii, []))
        jalkeen = sum([r.split("=", 1)[1].split() for r in unit if r.startswith("After=")], [])
        self.assertIn("nftables.service", jalkeen)
        self.assertFalse(any(r.startswith("Requires=-") for r in unit))

    def test_journald_30_paivaa(self):
        self.assertIn("MaxRetentionSec=30day", aktiiviset(lue("journald-hakukontti.conf")))


class OhjeTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(OHJE, encoding="utf-8") as f:
            cls.teksti = f.read()
        cls.lohkot = re.findall(r"```bash\n(.*?)```\n([^\n]*)", cls.teksti, re.DOTALL)

    def test_jokaisella_komennolla_odotettu_rivi(self):
        self.assertGreater(len(self.lohkot), 30)
        for koodi, seuraava in self.lohkot:
            self.assertTrue(seuraava.startswith("Odotettu:"), "ei Odotettu-rivia: %s" % koodi.strip()[:80])
            self.assertEqual(len(aktiiviset(koodi)), 1, "yksi komento kerrallaan: %s" % koodi.strip()[:80])

    def test_ei_paikkamerkkeja(self):
        for koodi, _ in self.lohkot:
            self.assertNotRegex(koodi, r"<[A-Za-z_-]+>", koodi.strip()[:80])
            self.assertNotIn("x.x.x.x", koodi)

    def test_pohjat_mainittu_ja_olemassa(self):
        for nimi in ("torrc", "nftables.conf", "searxng-settings.yml", "searxng.service",
                     "journald-hakukontti.conf", "mittaa_moottorit.py"):
            self.assertIn("`%s`" % nimi, self.teksti)
            self.assertTrue(os.path.exists(os.path.join(TAMA, nimi)), nimi)

    def test_kontti_ja_resurssit(self):
        luonti = [k for k, _ in self.lohkot if k.startswith("pct create 123 ")]
        self.assertEqual(len(luonti), 1)
        for osa in ("--unprivileged 1", "--cores 1", "--memory 1024", '"$TALLENNUS:8"', "firewall=1"):
            self.assertIn(osa, luonti[0])
        self.assertIn("pct status 123", self.teksti)
        self.assertIn("pct list", self.teksti)

    def test_avaimia_ei_tulosteta(self):
        for koodi, _ in self.lohkot:
            if "secrets." in koodi:
                # Avain ohjataan tiedostoon tai muuttujaan, ei paatteelle.
                self.assertTrue("> /etc/aivo-haku/avain" in koodi or "k=$(" in koodi, koodi[:80])
                self.assertNotIn("cat /etc/aivo-haku/avain", koodi)
        self.assertNotIn("echo \"$k\"", self.teksti)

    def test_palomuuri_tarkistetaan_ennen_kaynnistysta(self):
        komennot = [k.strip() for k, _ in self.lohkot]
        tarkistus = komennot.index("pct exec 123 -- systemctl is-enabled nftables")
        kaynnistys = komennot.index("pct exec 123 -- systemctl enable --now searxng")
        self.assertLess(tarkistus, kaynnistys)
        self.assertTrue(self.lohkot[tarkistus][1].startswith("Odotettu: `enabled`"))

    def test_rajattu_merkinta(self):
        self.assertIn("RAJATTU", self.teksti)


class Valepalvelin(http.server.BaseHTTPRequestHandler):
    vastaukset = {}

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        moottori = q.get("engines", [""])[0]
        if q.get("format") != ["json"] or moottori not in self.vastaukset:
            self.send_response(403)
            self.end_headers()
            return
        runko = json.dumps(self.vastaukset[moottori]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(runko)))
        self.end_headers()
        self.wfile.write(runko)

    def log_message(self, *a):
        pass


def tulokset(moottori, n):
    return [{"engine": moottori, "url": "https://example.org/%d" % i, "title": "t"} for i in range(n)]


class LuokitteluTesti(unittest.TestCase):
    def test_luokat(self):
        self.assertEqual(mm.luokittele({"results": tulokset("brave", 5)}, "brave"), ("ok", 5))
        self.assertEqual(mm.luokittele({"results": tulokset("brave", 2)}, "brave"), ("vahan", 2))
        self.assertEqual(mm.luokittele({"results": []}, "brave"), ("tyhja", 0))
        self.assertEqual(mm.luokittele({"results": [], "unresponsive_engines": [["brave", "CAPTCHA"]]}, "brave"), ("esto", 0))
        self.assertEqual(mm.luokittele({"results": [], "unresponsive_engines": [["bing", "too many requests"]]}, "bing"),
                         ("esto", 0))
        self.assertEqual(mm.luokittele({"results": [], "unresponsive_engines": [["bing", "HTTP error 403"]]}, "bing"),
                         ("esto", 0))
        self.assertEqual(mm.luokittele({"results": [], "unresponsive_engines": [["bing", "timeout"]]}, "bing"), ("virhe", 0))

    def test_vain_oman_moottorin_tulokset(self):
        v = {"results": tulokset("bing", 5) + [{"engines": ["brave", "bing"]}]}
        self.assertEqual(mm.luokittele(v, "brave"), ("vahan", 1))

    def test_rikkinainen_vastaus_ei_kaada(self):
        self.assertEqual(mm.luokittele({"results": None, "unresponsive_engines": ["x", None]}, "brave"), ("tyhja", 0))

    def test_yhteenveto(self):
        rivit = [("a", "ok", 3, 1.0), ("a", "esto", 0, 2.0), ("a", "vahan", 1, 3.0), ("a", "ok", 4, 4.0)]
        y = mm.yhteenveto(rivit)["a"]
        self.assertEqual((y["kyselyja"], y["ok"], y["esto"], y["vahan"]), (4, 2, 1, 1))
        self.assertEqual(y["esto_pros"], 25.0)
        self.assertEqual(y["alle3_pros"], 50.0)
        self.assertEqual(y["mediaani_s"], 2.5)


class MittausTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Valepalvelin.vastaukset = {
            "hyva": {"results": tulokset("hyva", 8), "unresponsive_engines": []},
            "estetty": {"results": [], "unresponsive_engines": [["estetty", "CAPTCHA"]]},
        }
        cls.palvelin = http.server.HTTPServer(("127.0.0.1", 0), Valepalvelin)
        cls.osoite = "http://127.0.0.1:%d" % cls.palvelin.server_address[1]
        cls.saie = threading.Thread(target=cls.palvelin.serve_forever, daemon=True)
        cls.saie.start()

    @classmethod
    def tearDownClass(cls):
        cls.palvelin.shutdown()
        cls.palvelin.server_close()

    def test_mittaus_valepalvelimella(self):
        unet = []
        y, http_ok = mm.mittaa(self.osoite, ["hyva", "estetty", "puuttuu"], 3, 1.0, 2.0, 5,
                               nuku=unet.append, satunnainen=random.Random(1))
        self.assertEqual(y["hyva"]["ok"], 3)
        self.assertEqual(y["hyva"]["esto_pros"], 0.0)
        self.assertEqual(y["estetty"]["esto"], 3)
        self.assertEqual(y["estetty"]["esto_pros"], 100.0)
        self.assertEqual(y["puuttuu"]["virhe"], 3)          # HTTP 403 SearXNG:lta
        self.assertEqual(http_ok, 6)
        self.assertEqual(len(unet), 8)                      # 9 kyselya, vali niiden valissa
        self.assertTrue(all(1.0 <= u <= 2.0 for u in unet))

    def test_main_ja_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "m.json")
            ulos = io.StringIO()
            with redirect_stdout(ulos):
                rc = mm.main(["--osoite", self.osoite, "--moottorit", "hyva,estetty", "--kyselyja", "2",
                              "--vali-min", "0", "--vali-max", "0", "--json", polku])
            self.assertEqual(rc, 0)
            self.assertIn("estetty", ulos.getvalue())
            with open(polku, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["moottorit"]["estetty"]["esto"], 2)
            # Tulostiedostossa ei ole hakulausekkeita.
            for lauseke in mm.TESTILAUSEKKEET:
                self.assertNotIn(lauseke, json.dumps(data))

    def test_ei_vastausta_paluukoodi_2(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = mm.main(["--osoite", "http://127.0.0.1:9", "--moottorit", "hyva", "--kyselyja", "1",
                          "--vali-min", "0", "--vali-max", "0", "--aikaraja", "2"])
        self.assertEqual(rc, 2)
        self.assertIn("ei vastannut", err.getvalue())

    def test_osoite_vain_silmukka(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                mm.jasenna(["--osoite", "http://example.org:8888"])
            with self.assertRaises(SystemExit):
                mm.jasenna(["--moottorit", "bing;rm"])
            with self.assertRaises(SystemExit):
                mm.jasenna(["--kyselyja", "0"])
            with self.assertRaises(SystemExit):
                mm.jasenna(["--vali-min", "5", "--vali-max", "1"])


if __name__ == "__main__":
    unittest.main()
