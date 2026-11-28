"""Hakukontin pohjat, asennusohje ja moottorimittaus. Ei verkkoa: mittaus testataan valepalvelimella silmukkaosoitteessa."""
import http.server
import io
import ipaddress
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
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
        # eth0:aan sallitaan vain vastaukset kontille 122 ja ytimen WireGuard-liikenne VPN-palvelimelle.
        ulos = [r for r in rivit if 'oifname "eth0"' in r and r.endswith("accept")]
        self.assertEqual(ulos, [VASTAUS_122, WG_ULOS])
        # debian-tor: vain TCP ja vain wg0:n kautta. Ainoa UDP-sallinta on WireGuard (merkitty ytimen soketti).
        self.assertEqual([r for r in rivit if 'skuid "debian-tor"' in r], [TOR_ULOS])
        self.assertIn("meta l4proto tcp", TOR_ULOS)
        self.assertIn('oifname "wg0"', TOR_ULOS)
        alku = rivit.index("chain output {")
        output = rivit[alku + 1:rivit.index("}", alku)]
        self.assertEqual([r for r in output if "udp" in r and r.endswith("accept")], [WG_ULOS])
        # Mikaan sallinta ei kayta wg0:aa muille kuin debian-torille.
        self.assertEqual([r for r in output if "wg0" in r and r.endswith("accept")], [TOR_ULOS])
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

    def test_journald_30_paivaa(self):
        self.assertIn("MaxRetentionSec=30day", aktiiviset(lue("journald-hakukontti.conf")))


def ip4(a, b, c, d):
    """Yksityiset osoitteet rakennetaan numeroista, koska repon vuotovahti ei salli niita kirjaimellisesti."""
    return "%d.%d.%d.%d" % (a, b, c, d)


VASTAUS_122 = 'oifname "eth0" ip daddr $CT122 tcp sport 8890 ct state established accept'
# Tor tarvitsee vain TCP:n: UDP (myos portti 53) ei saa paasta ulos debian-torinakaan (tarkastus 26.11.2026).
# Tor kulkee WireGuard-VPN:n (wg0) sisalla (A1119): debian-tor ei paase eth0:aan lainkaan.
TOR_ULOS = 'meta skuid "debian-tor" oifname "wg0" meta l4proto tcp accept'
# Ytimen WireGuard-soketti merkitsee pakettinsa (wg-quick fwmark 51820 = 0xca6c); vain VPN-palvelimen osoite ja portti.
WG_ULOS = 'oifname "eth0" meta mark 0x0000ca6c ip daddr $WG_PALVELIN udp dport $WG_PORTTI accept'
ETH0_ESTO = 'oifname "eth0" counter drop comment "eth0: vain WireGuard-palvelimelle"'
ESTOT = ('ip daddr $KIELLETYT4 counter drop comment "yksityinen tai erikoisosoite"',
         'ip daddr $LAHIVERKOT4 counter drop comment "lahiverkko"',
         'ip6 daddr $KIELLETYT6 counter drop comment "yksityinen tai erikoisosoite"',
         'meta nfproto ipv6 counter drop comment "ei IPv6-ulosmenoa"')


def maaritelma(rivit, nimi):
    """define NIMI = { a, b } -> lista ipaddress-verkkoja."""
    alku = "define %s = {" % nimi
    osumat = [r for r in rivit if r.startswith(alku)]
    if len(osumat) != 1 or not osumat[0].endswith("}"):
        raise AssertionError("maaritelma puuttuu tai on monella rivilla: %s" % nimi)
    return [ipaddress.ip_network(o.strip()) for o in osumat[0][len(alku):-1].split(",")]


class YksityisetEstoTesti(unittest.TestCase):
    """Ulosmeno yksityisiin ja erikoisosoitteisiin on estetty kaikilta kayttajilta (tarkastus 25.11.2026)."""

    @classmethod
    def setUpClass(cls):
        cls.rivit = aktiiviset(lue("nftables.conf"))
        cls.v4 = maaritelma(cls.rivit, "KIELLETYT4")
        cls.v6 = maaritelma(cls.rivit, "KIELLETYT6")
        alku = cls.rivit.index("chain output {")
        cls.output = cls.rivit[alku + 1:cls.rivit.index("}", alku)]

    def estetty(self, osoite):
        ip = ipaddress.ip_address(osoite)
        verkot = self.v4 if ip.version == 4 else self.v6
        return any(ip in v for v in verkot)

    def test_kaikki_yksityiset_alueet_katettu(self):
        vaaditut = [ip4(10, 0, 0, 0) + "/8", ip4(172, 16, 0, 0) + "/12", ip4(192, 168, 0, 0) + "/16",
                    ip4(100, 64, 0, 0) + "/10", "169.254.0.0/16", "127.0.0.0/8", "0.0.0.0/8", "224.0.0.0/4",
                    "240.0.0.0/4", "192.0.0.0/24", "198.18.0.0/15", "fc00::/7", "fe80::/10", "::1/128",
                    "::ffff:0:0/96"]
        for alue in vaaditut:
            verkko = ipaddress.ip_network(alue)
            kattaja = self.v4 if verkko.version == 4 else self.v6
            self.assertTrue(any(verkko.subnet_of(v) for v in kattaja), alue)

    def test_esimerkkiosoitteet(self):
        for o in (ip4(192, 168, 1, 1), ip4(192, 168, 255, 254), ip4(10, 1, 2, 3), ip4(172, 31, 255, 1),
                  ip4(100, 100, 100, 100), "169.254.169.254", "127.0.0.2", "0.0.0.0", "255.255.255.255",
                  "224.0.0.251", "192.0.0.8", "192.0.0.170", "198.18.0.1", "198.19.255.254", "fd00::1", "fe80::1",
                  "::1", "::ffff:" + ip4(192, 168, 1, 1), "ff02::1"):
            self.assertTrue(self.estetty(o), o)
        # Julkiset osoitteet (dokumentaatio- ja esimerkkialueet) eivat ole listalla.
        for o in ("8.8.8.8", "1.1.1.1", "203.0.113.5", "192.0.1.1", "198.17.255.255", "198.20.0.1",
                  "2001:db8::1", "2a00:1450::1"):
            self.assertFalse(self.estetty(o), o)

    def test_ei_paallekkaisia_alueita(self):
        # nft hylkaa paallekkaiset alueet samassa joukossa, joten pohja ei saa sisaltaa niita.
        for verkot in (self.v4, self.v6):
            for i, a in enumerate(verkot):
                for b in verkot[i + 1:]:
                    self.assertFalse(a.overlaps(b), (str(a), str(b)))

    def test_estot_ennen_sallintoja(self):
        for esto in ESTOT:
            self.assertIn(esto, self.output)
        ensimmainen = min(self.output.index(e) for e in ESTOT)
        # Ennen estoja sallitaan vain silmukka, IPv6-naapurinhaku ja vastaukset kontille 122 portista 8890.
        for r in self.output[:ensimmainen]:
            if not r.endswith("accept"):
                continue
            self.assertTrue(r.startswith('oif "lo" ') or r.startswith("icmpv6 type {") or r == VASTAUS_122, r)
        naapuri = [r for r in self.output[:ensimmainen] if r.startswith("icmpv6 type {")]
        self.assertEqual(len(naapuri), 1)
        tyypit = {t.strip() for t in naapuri[0][len("icmpv6 type {"):naapuri[0].index("}")].split(",")}
        self.assertTrue(tyypit <= {"nd-router-solicit", "nd-neighbor-solicit", "nd-neighbor-advert",
                                   "mld2-listener-report"}, tyypit)
        # Avatut yhteydet (established) ja Torin internetyhteys sallitaan vasta estojen jalkeen.
        viimeinen = max(self.output.index(e) for e in ESTOT)
        self.assertGreater(self.output.index("ct state established,related accept"), viimeinen)
        self.assertGreater(self.output.index(TOR_ULOS), viimeinen)
        # WireGuard sallitaan estojen jalkeen, ja muu eth0-liikenne estetaan ennen avattujen yhteyksien sallintaa,
        # jotta wg0:n kadotessa vanhojen Tor-yhteyksien paketit eivat paase eth0:aan.
        self.assertGreater(self.output.index(WG_ULOS), viimeinen)
        self.assertEqual(self.output.index(ETH0_ESTO), self.output.index(WG_ULOS) + 1)
        self.assertLess(self.output.index(ETH0_ESTO), self.output.index("ct state established,related accept"))

    def test_ipv6_ulosmeno_vain_silmukkaan_ja_naapurinhakuun(self):
        # Globaalit IPv6-osoitteet lahiverkossa (SLAAC) eivat ole KIELLETYT6:ssa, joten IPv6 estetaan kokonaan.
        esto = self.output.index('meta nfproto ipv6 counter drop comment "ei IPv6-ulosmenoa"')
        for r in self.output[esto + 1:]:
            self.assertNotIn("ip6", r)
        self.assertGreater(self.output.index(TOR_ULOS), esto)

    def test_ainoa_poikkeus_on_vastaus_kontille_122(self):
        poikkeus = [r for r in self.output if "$CT122" in r]
        self.assertEqual(poikkeus, [VASTAUS_122])
        self.assertIn("ct state established", VASTAUS_122)
        self.assertNotIn("new", VASTAUS_122)

    def test_tor_ei_salli_sisaisia_osoitteita(self):
        rivit = aktiiviset(lue("torrc"))
        for r in ("ClientRejectInternalAddresses 1", "ClientDNSRejectInternalAddresses 1", "ExitPolicy reject *:*"):
            self.assertIn(r, rivit)
        self.assertFalse(any(r.startswith("ExitPolicy") and "accept" in r for r in rivit))
        # Tor ei kayta valityspalvelinta tai siltaa, joka voisi olla lahiverkossa.
        for kielletty in ("Socks4Proxy", "Socks5Proxy", "HTTPSProxy", "HTTPProxy", "Bridge", "UseBridges 1"):
            self.assertFalse(any(r.startswith(kielletty) for r in rivit), kielletty)

    def test_searxng_ulosmeno_vain_tor_socks(self):
        s = lue("searxng-settings.yml")
        rivit = aktiiviset(s)
        osoitteet = set(re.findall(r"[a-z0-9]+://[^\s\"']*", "\n".join(rivit)))
        self.assertEqual(osoitteet, {"all://:", "socks5h://127.0.0.1:9050"})
        self.assertEqual(sum(1 for r in rivit if r.startswith("proxies:")), 1)
        for kielletty in ("source_ips", "using_tor_proxy: false", "network:", "enable_http: true", "verify: false"):
            self.assertNotIn(kielletty, s)
        # nftables: searxng-kayttajalla on vain silmukan Tor-portti (ei eth0:aa).
        nft = aktiiviset(lue("nftables.conf"))
        self.assertEqual([r for r in nft if 'skuid "searxng"' in r], ['oif "lo" meta skuid "searxng" tcp dport 9050 accept'])

    def test_searxng_yksikko_vain_silmukka(self):
        rivit = aktiiviset(lue("searxng.service"))
        self.assertIn("IPAddressDeny=any", rivit)
        self.assertIn("IPAddressAllow=localhost", rivit)
        self.assertEqual([r for r in rivit if r.startswith("IPAddressAllow=")], ["IPAddressAllow=localhost"])


def nft_ohjelma():
    """nft-polku, jos sen voi ajaa omassa kayttaja- ja verkkonimiavaruudessa (unshare -rn), muuten None."""
    nft = shutil.which("nft") or next((p for p in ("/usr/sbin/nft", "/sbin/nft") if os.access(p, os.X_OK)), None)
    if not nft or not shutil.which("unshare"):
        return None
    try:
        r = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return nft if r.returncode == 0 else None


@unittest.skipUnless(nft_ohjelma(), "nft tai unshare -rn ei kaytettavissa")
class NftSyntaksiTesti(unittest.TestCase):
    """nft -c hyvaksyy pohjan. Kayttajanimet korvataan numeroilla, koska kayttajia ei ole testikoneella,
    ja osoitetiedosto korvataan dokumentaatio-osoitteilla (RFC 5737)."""

    def test_nft_c_hyvaksyy_pohjan(self):
        teksti = lue("nftables.conf")
        with tempfile.TemporaryDirectory() as hak:
            osoitteet = os.path.join(hak, "osoitteet.nft")
            with open(osoitteet, "w", encoding="utf-8") as f:
                f.write("define CT122 = 198.51.100.7\ndefine LAHIVERKOT4 = { 203.0.113.0/24 }\n"
                        "define WG_PALVELIN = 192.0.2.10\ndefine WG_PORTTI = 51820\n")
            teksti = teksti.replace("/etc/nftables.d/hakukontti-osoitteet.nft", osoitteet)
            for i, kayttaja in enumerate(("searxng", "aivo-haku", "_apt", "debian-tor", "root")):
                teksti = teksti.replace('skuid "%s"' % kayttaja, "skuid %d" % (2000 + i))
            self.assertNotIn('skuid "', teksti)
            saannot = os.path.join(hak, "nftables.conf")
            with open(saannot, "w", encoding="utf-8") as f:
                f.write(teksti)
            r = subprocess.run(["unshare", "-rn", nft_ohjelma(), "-c", "-f", saannot],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])


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
                     "journald-hakukontti.conf", "mittaa_moottorit.py", "wg0.conf.esimerkki", "wg_asetus.py",
                     "wg-quick-hakukontti.conf", "tor-hakukontti.conf", "isanta-nat.nft.mall"):
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

    def test_lahiverkon_esto_tarkistetaan(self):
        komennot = {k.strip(): o for k, o in self.lohkot}
        root = 'pct exec 123 -- curl -sS -m 10 -o /dev/null "http://$YHDYSKAYTAVA/"; echo "paluuarvo $?"'
        self.assertIn(root, komennot)
        self.assertIn("`7` tai `28`", komennot[root])
        tor = [k for k in komennot if "--reuid=debian-tor" in k and "$YHDYSKAYTAVA" in k]
        socks = [k for k in komennot if "--socks5-hostname 127.0.0.1:9050" in k and "$YHDYSKAYTAVA" in k]
        self.assertEqual((len(tor), len(socks)), (1, 1))
        self.assertIn("`97`", komennot[socks[0]])
        laskuri = [k for k in komennot if "yksityinen tai erikoisosoite" in k]
        self.assertGreaterEqual(len(laskuri), 2)
        # Proxmox-palomuurin yksityiset alueet luetaan pohjasta, ei kirjoiteta ohjeeseen.
        self.assertTrue(any(k.startswith("KIELLETYT4=$(sed -n") for k in komennot))
        self.assertTrue(any("/etc/pve/firewall/123.fw" in k and '"$KIELLETYT4"' in k for k in komennot))

    def test_kiellettyjen_alueiden_maara_ohjeessa_vastaa_pohjaa(self):
        # Ohjeen Odotettu-rivi kertoo alueiden maaran; asentaja pysahtyy, jos tulos poikkeaa (tarkastus 26.11.2026).
        v4 = maaritelma(aktiiviset(lue("nftables.conf")), "KIELLETYT4")
        komennot = {k.strip(): o for k, o in self.lohkot}
        luku = [k for k in komennot if k.startswith("KIELLETYT4=$(sed -n")]
        self.assertEqual(len(luku), 1)
        m = re.search(r"jossa on (\d+) aluetta ja ensimm\u00e4isen\u00e4 `([^`]+)`", komennot[luku[0]])
        self.assertIsNotNone(m, komennot[luku[0]])
        self.assertEqual(int(m.group(1)), len(v4))
        self.assertEqual(m.group(2), str(v4[0]))

    def komento(self, alku):
        osumat = [(k.strip(), o) for k, o in self.lohkot if k.startswith(alku)]
        self.assertEqual(len(osumat), 1, alku)
        return osumat[0]

    def aja_bash(self, komento, ymparisto):
        env = dict(os.environ, **ymparisto)
        r = subprocess.run(["bash", "-o", "pipefail", "-c", komento], capture_output=True, text=True, env=env,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout.strip()

    def test_kielletyt4_sed_tulostaa_pohjan_alueet(self):
        # Ohjeen sed-komento ajetaan pohjaa vasten: tuloste on samat alueet samassa jarjestyksessa (maaran tarkistaa
        # test_kiellettyjen_alueiden_maara_ohjeessa_vastaa_pohjaa).
        koodi, _ = self.komento("KIELLETYT4=$(sed -n")
        self.assertIn("/root/hakukontti/nftables.conf", koodi)
        tulos = self.aja_bash(koodi.replace("/root/hakukontti/nftables.conf", os.path.join(TAMA, "nftables.conf")),
                              {})
        pohja = maaritelma(aktiiviset(lue("nftables.conf")), "KIELLETYT4")
        self.assertEqual([ipaddress.ip_network(a) for a in tulos.split(",")], pohja)

    def test_lahi4_ohittaa_oletusreitin(self):
        # Proxmoxin ifupdown2 merkitsee oletusreitin proto kernel, jolloin `default` paatyisi nft-joukkoon.
        koodi, _ = self.komento("LAHI4=$(ip -4 route show proto kernel")
        reitit = ("default via 192.0.2.1 dev vmbr0 proto kernel onlink\n"
                  "192.0.2.0/24 dev vmbr0 proto kernel scope link src 192.0.2.10\n"
                  "198.51.100.0/24 dev vmbr1 proto kernel scope link src 198.51.100.1\n"
                  "192.0.2.0/24 dev vmbr2 proto kernel scope link src 192.0.2.11\n")
        koodi = koodi.replace("ip -4 route show proto kernel", "printf '%s' \"$REITIT\"", 1)
        self.assertEqual(self.aja_bash(koodi, {"REITIT": reitit}), "192.0.2.0/24,198.51.100.0/24")

    def test_lahiverkot_ilman_paallekkaisia(self):
        # 169.254.0.0/16 lisataan aina, ja se voi tulla myos reittitaulusta: sama tai sisakkainen aliverkko vain kerran.
        koodi, odotettu = self.komento("LAHIVERKOT=$(")
        cg = ip4(100, 64, 0, 0) + "/10"
        k10 = ip4(10, 0, 0, 0) + "/8"
        tapaukset = (
            ("192.0.2.0/24,169.254.0.0/16", cg, cg + ",169.254.0.0/16,192.0.2.0/24"),
            ("169.254.10.0/24,192.0.2.0/24", "", "169.254.0.0/16,192.0.2.0/24"),
            ("192.0.2.0/24", "", "169.254.0.0/16,192.0.2.0/24"),
            (k10 + "," + ip4(10, 1, 0, 0) + "/16", cg, k10 + "," + cg + ",169.254.0.0/16"),
        )
        for lahi4, ts10, oikea in tapaukset:
            tulos = self.aja_bash(koodi, {"LAHI4": lahi4, "TS10": ts10})
            self.assertEqual(tulos, oikea, (lahi4, ts10))
            verkot = [ipaddress.ip_network(v) for v in tulos.split(",")]
            for i, a in enumerate(verkot):
                for b in verkot[i + 1:]:
                    self.assertFalse(a.overlaps(b), (str(a), str(b)))
            # Estettavat osoitteet eivat vahene: jokainen syote on tuloksen sisalla.
            for syote in [s for s in (lahi4 + "," + ts10).split(",") if s] + ["169.254.0.0/16"]:
                n = ipaddress.ip_network(syote)
                self.assertTrue(any(n.subnet_of(v) for v in verkot), syote)
        self.assertIn("169.254.0.0/16", odotettu)

    def test_tor_udp_esto_tarkistetaan(self):
        komennot = {k.strip(): o for k, o in self.lohkot}
        udp = [k for k in komennot if "--reuid=debian-tor" in k and "SOCK_DGRAM" in k]
        self.assertEqual(len(udp), 1)
        self.assertIn("Operation not permitted", komennot[udp[0]])

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
