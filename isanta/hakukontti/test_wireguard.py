"""Hakukontti WireGuard-VPN:n sisalla (A1119): wg_asetus.py, systemd-jarjestys, isannan taulu ja kahden kerroksen
verkkosimulaatio (isannan nft-taulu + Tailscalen iptables-legacy-saannot + kontin kill switch). Ei verkkoa."""
import io
import ipaddress
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from isanta.hakukontti import wg_asetus as wg
from isanta.hakukontti.test_hakukontti import aktiiviset, ip4, lue, maaritelma, nft_ohjelma

TAMA = os.path.dirname(os.path.abspath(__file__))

# Julkiset esimerkkiosoitteet (eivat VPN-palvelimia); dokumentaatioalueet eivat ole is_global.
JULKINEN = "1.0.0.1"
MULLVAD_TYYPPI = (
    "[Interface]\n"
    "# Device: esimerkki\n"
    "PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n"
    "Address = " + ip4(10, 66, 1, 2) + "/32,fc00:bbbb:bbbb:bb01::3:1/128\n"
    "DNS = " + ip4(10, 64, 0, 1) + "\n"
    "\n"
    "[Peer]\n"
    "PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=\n"
    "AllowedIPs = 0.0.0.0/0,::0/0\n"
    "Endpoint = " + JULKINEN + ":51820\n")
YKSITYINEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def kelvollinen(**muutos):
    rivit = {"PrivateKey": YKSITYINEN, "Address": ip4(10, 66, 1, 2) + "/32", "PublicKey": "B" * 43 + "=",
             "AllowedIPs": "0.0.0.0/0", "Endpoint": JULKINEN + ":51820"}
    rivit.update(muutos)
    iface = "".join("%s = %s\n" % (k, rivit[k]) for k in ("PrivateKey", "Address", "FwMark", "DNS", "PostUp", "Table")
                    if rivit.get(k) is not None)
    peer = "".join("%s = %s\n" % (k, rivit[k]) for k in ("PublicKey", "AllowedIPs", "Endpoint") if rivit.get(k) is not None)
    return "[Interface]\n" + iface + "\n[Peer]\n" + peer


class WgAsetusTesti(unittest.TestCase):
    def virhe(self, teksti):
        with self.assertRaises(wg.AsetusVirhe) as k:
            wg.tarkista(teksti)
        return k.exception.args[0]

    def test_kelvollinen(self):
        self.assertEqual(wg.tarkista(kelvollinen()), (JULKINEN, 51820))
        self.assertEqual(wg.tarkista(kelvollinen(FwMark="51820")), (JULKINEN, 51820))
        self.assertEqual(wg.tarkista(kelvollinen(FwMark="0xca6c")), (JULKINEN, 51820))

    def test_hylkaykset(self):
        self.assertEqual(self.virhe(kelvollinen(DNS=ip4(10, 64, 0, 1))), "dns_rivi")
        self.assertEqual(self.virhe(kelvollinen(PostUp="iptables -F")), "komentokoukku")
        self.assertEqual(self.virhe(kelvollinen(Address="fc00::1/128")), "ipv6_osoite")
        self.assertEqual(self.virhe(kelvollinen(AllowedIPs="0.0.0.0/0, ::/0")), "ipv6_allowedips")
        self.assertEqual(self.virhe(kelvollinen(AllowedIPs="0.0.0.0/1")), "allowedips_ei_kaikki")
        self.assertEqual(self.virhe(kelvollinen(Endpoint="vpn.example.org:51820")), "endpoint_ei_ipv4")
        self.assertEqual(self.virhe(kelvollinen(Endpoint="[2001:db8::1]:51820")), "endpoint_ei_ipv4")
        self.assertEqual(self.virhe(kelvollinen(Endpoint=ip4(192, 168, 1, 1) + ":51820")), "endpoint_ei_julkinen")
        self.assertEqual(self.virhe(kelvollinen(Endpoint="203.0.113.10:51820")), "endpoint_ei_julkinen")
        self.assertEqual(self.virhe(kelvollinen(Endpoint=JULKINEN + ":0")), "endpoint_portti")
        self.assertEqual(self.virhe(kelvollinen(Endpoint=None)), "endpoint_puuttuu")
        self.assertEqual(self.virhe(kelvollinen(FwMark="1234")), "fwmark")
        self.assertEqual(self.virhe(kelvollinen(Table="off")), "table")
        self.assertEqual(self.virhe(kelvollinen() + "\n[Peer]\nPublicKey = x\nEndpoint = 1.0.0.2:1\n"), "peer_maara")
        self.assertEqual(self.virhe(kelvollinen(PrivateKey=None)), "avain_puuttuu")
        self.assertEqual(self.virhe("PrivateKey = x\n"), "rivi_ei_kelpaa")

    def test_esimerkkipohja_ei_kelpaa_sellaisenaan(self):
        teksti = lue("wg0.conf.esimerkki")
        self.assertEqual(self.virhe(teksti), "endpoint_ei_julkinen")
        # Pohjassa ei ole avaimia: vain paikkamerkit (WireGuard-avain on 44 merkin base64-jono).
        self.assertNotRegex(teksti, r"[A-Za-z0-9+/]{42,43}=")
        self.assertIn("@YKSITYINEN_AVAIN@", teksti)
        rivit = aktiiviset(teksti)
        self.assertFalse(any(r.lower().startswith("dns") for r in rivit))
        for r in rivit:
            for osoite in re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", r):
                ip = ipaddress.ip_address(osoite)
                dok = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",
                                                         "0.0.0.0/32")]
                self.assertTrue(any(ip in n for n in dok), osoite)

    def test_siivoa_mullvad_tyyppinen(self):
        puhdas = wg.siivoa(MULLVAD_TYYPPI)
        self.assertEqual(wg.tarkista(puhdas), (JULKINEN, 51820))
        self.assertNotIn("DNS", puhdas)
        self.assertNotIn("fc00", puhdas)
        self.assertNotIn("::", puhdas)
        self.assertIn(YKSITYINEN, puhdas)
        self.assertIn("AllowedIPs = 0.0.0.0/0", puhdas)
        # Keepalive lisataan [Peer]-osioon kerran (kattely heti noston jalkeen), eika toista kertaa uudelleen ajettaessa.
        self.assertEqual(puhdas.count("PersistentKeepalive = 25"), 1)
        self.assertGreater(puhdas.index("PersistentKeepalive"), puhdas.index("[Peer]"))
        self.assertEqual(wg.siivoa(puhdas), puhdas)
        self.assertEqual(self.virhe(MULLVAD_TYYPPI), "dns_rivi")

    def test_cli_ei_tulosta_avainta(self):
        with tempfile.TemporaryDirectory() as d:
            sisaan = os.path.join(d, "mullvad.conf")
            ulos = os.path.join(d, "wg0.conf")
            with open(sisaan, "w", encoding="utf-8") as f:
                f.write(MULLVAD_TYYPPI)
            for argv, odotettu_rc in ((["tarkista", sisaan], 1), (["siivoa", sisaan, ulos], 0),
                                      (["tarkista", ulos], 0), (["nft", ulos], 0), (["siivoa", sisaan, ulos], 1)):
                o, e = io.StringIO(), io.StringIO()
                with redirect_stdout(o), redirect_stderr(e):
                    rc = wg.main(argv)
                self.assertEqual(rc, odotettu_rc, (argv, e.getvalue()))
                kaikki = o.getvalue() + e.getvalue()
                self.assertNotIn(YKSITYINEN, kaikki)
                self.assertNotIn("BBBB", kaikki)
                if argv[0] == "nft":
                    self.assertEqual(o.getvalue(), "define WG_PALVELIN = %s\ndefine WG_PORTTI = 51820\n" % JULKINEN)
            self.assertEqual(stat.S_IMODE(os.stat(ulos).st_mode), 0o600)

    def test_puuttuva_tiedosto_vain_tyyppi(self):
        e = io.StringIO()
        with redirect_stderr(e), redirect_stdout(io.StringIO()):
            rc = wg.main(["tarkista", "/ei/ole/wg0.conf"])
        self.assertEqual(rc, 1)
        self.assertEqual(e.getvalue().strip(), "WG_ASETUS: VIRHE tiedosto FileNotFoundError")


SIM_ASETUKSET = ("SILTA=vmbr0\nTALLENNUS=konttilevy\nSISASILTA=vmbr3\nIP122=198.18.0.2\nIP123=198.18.0.3\n"
                 "LAHIVERKOT=198.51.100.0/24\n")


def isanta_taulu(palvelin="203.0.113.10", portti=51820):
    return wg.tayta_isanta(lue("isanta-nat.nft.mall"), wg.lue_asetukset(SIM_ASETUKSET), palvelin, portti,
                           wg.kielletyt4(lue("nftables.conf")))


class IsantaPohjaTesti(unittest.TestCase):
    def test_paikkamerkit_ja_ei_osoitteita(self):
        mall = lue("isanta-nat.nft.mall")
        self.assertEqual(set(re.findall(r"%([A-Z0-9_]+)%", mall)),
                         {"SILTA", "SISASILTA", "IP122", "IP123", "WG_PALVELIN", "WG_PORTTI", "KIELLETYT4"})
        # Ainoa kirjoitettu osoite on asennusaikainen julkinen nimipalvelin.
        self.assertEqual(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", "\n".join(aktiiviset(mall))), ["9.9.9.9"])

    def test_ulos_vain_wireguard_ja_asennusaika(self):
        rivit = aktiiviset(isanta_taulu())
        sallivat = [r for r in rivit if r.startswith('iifname "vmbr3"') and 'oifname "vmbr0"' in r
                    and re.search(r" accept( comment |$)", r)]
        self.assertEqual(len(sallivat), 3, sallivat)
        wg_rivi = [r for r in sallivat if "WireGuard" in r]
        self.assertEqual(len(wg_rivi), 1)
        self.assertIn("ip daddr 203.0.113.10 udp dport 51820", wg_rivi[0])
        muut = [r for r in sallivat if r not in wg_rivi]
        for r in muut:
            self.assertIn("ip saddr @asennus", r)
        self.assertTrue(any("tcp dport { 80, 443 }" in r for r in muut))
        self.assertTrue(any("ip daddr 9.9.9.9 udp dport 53" in r for r in muut))
        # Ei yleista TCP-sallintaa internetiin (v2:n "meta l4proto tcp accept" on poistettu).
        self.assertFalse(any("meta l4proto tcp" in r for r in rivit))
        # Kielletyt alueet estetaan ennen sallintoja, ja lopussa on yleinen esto.
        esto = next(i for i, r in enumerate(rivit) if "ei lahiverkkoon" in r)
        self.assertTrue(all(rivit.index(r) > esto for r in sallivat))
        loppu = next(i for i, r in enumerate(rivit) if "muu sillasta ulos" in r)
        self.assertTrue(all(rivit.index(r) < loppu for r in sallivat))
        self.assertIn("flags timeout", rivit)

    def test_paikkamerkki_jaa_kiinni(self):
        with self.assertRaises(wg.AsetusVirhe):
            wg.tayta_isanta("x %PUUTTUU%", wg.lue_asetukset(SIM_ASETUKSET), JULKINEN, 1, "0.0.0.0/8")
        with self.assertRaises(wg.AsetusVirhe):
            wg.lue_asetukset("SILTA=vmbr0\nSISASILTA=vmbr3; flush ruleset\nIP122=1.0.0.2\nIP123=1.0.0.3\n")
        with self.assertRaises(wg.AsetusVirhe):
            wg.lue_asetukset("SILTA=vmbr0\nSISASILTA=vmbr3\nIP122=1.0.0.2\n")

    def test_cli_isanta(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "wg0.conf")
            env = os.path.join(d, "asetukset.env")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(kelvollinen())
            with open(env, "w", encoding="utf-8") as f:
                f.write(SIM_ASETUKSET)
            o = io.StringIO()
            with redirect_stdout(o), redirect_stderr(io.StringIO()):
                rc = wg.main(["isanta", conf, "--mall", os.path.join(TAMA, "isanta-nat.nft.mall"),
                              "--pohja", os.path.join(TAMA, "nftables.conf"), "--asetukset", env])
        self.assertEqual(rc, 0)
        self.assertIn("ip daddr %s udp dport 51820" % JULKINEN, o.getvalue())
        self.assertNotIn(YKSITYINEN, o.getvalue())
        self.assertNotIn("%", o.getvalue())


def yksikko(nimi):
    rivit = aktiiviset(lue(nimi))
    osat = {}
    for r in rivit:
        if "=" in r and not r.startswith("["):
            k, v = r.split("=", 1)
            osat.setdefault(k, []).extend(v.split())
    return osat


class JarjestysTesti(unittest.TestCase):
    """wg-quick@wg0 palomuurin jalkeen; Tor, SearXNG ja hakuvalittaja vaativat seka palomuurin etta VPN:n."""

    def test_wg_quick_vaatii_palomuurin(self):
        o = yksikko("wg-quick-hakukontti.conf")
        self.assertEqual(o["Requires"], ["nftables.service"])
        self.assertEqual(o["After"], ["nftables.service"])
        self.assertIn("[Unit]", lue("wg-quick-hakukontti.conf"))

    def test_tor_ja_palvelut_vaativat_vpn_ja_palomuurin(self):
        for nimi in ("tor-hakukontti.conf", "searxng.service", "aivo-haku.service"):
            o = yksikko(nimi)
            for vaadittu in ("nftables.service", "wg-quick@wg0.service"):
                self.assertIn(vaadittu, o["Requires"], nimi)
                self.assertIn(vaadittu, o["After"], nimi)

    def test_ohje_asentaa_lisaosat(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(TAMA)), "docs", "aivo-hakukontti.md"),
                  encoding="utf-8") as f:
            ohje = f.read()
        self.assertIn("/etc/systemd/system/wg-quick@wg0.service.d/hakukontti.conf", ohje)
        self.assertIn("/etc/systemd/system/tor@default.service.d/hakukontti.conf", ohje)
        self.assertIn("RAJATTU", ohje)


@unittest.skipUnless(nft_ohjelma(), "nft tai unshare -rn ei kaytettavissa")
class IsantaNftSyntaksiTesti(unittest.TestCase):
    def test_nft_c_hyvaksyy_isannan_taulun(self):
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "isanta.nft")
            with open(polku, "w", encoding="utf-8") as f:
                f.write(isanta_taulu())
            r = subprocess.run(["unshare", "-rn", nft_ohjelma(), "-c", "-f", polku], capture_output=True, text=True,
                               timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])


def iptables_legacy():
    """iptables-legacy-komento listana tai None. IPTABLES_LEGACY voi antaa komennon (esim. purettu paketti)."""
    oma = os.environ.get("IPTABLES_LEGACY")
    if oma:
        return shlex.split(oma)
    for p in (shutil.which("iptables-legacy"), "/usr/sbin/iptables-legacy", "/sbin/iptables-legacy"):
        if p and os.access(p, os.X_OK):
            return [p]
    return None


def kontin_saannot(polku_osoitteet):
    teksti = lue("nftables.conf").replace("/etc/nftables.d/hakukontti-osoitteet.nft", polku_osoitteet)
    # Nimiavaruudessa on vain uid 0: debian-tor simuloidaan rootina, muut kayttajat saavat kayttamattomat numerot.
    for i, kayttaja in enumerate(("searxng", "aivo-haku", "_apt")):
        teksti = teksti.replace('skuid "%s"' % kayttaja, "skuid %d" % (2000 + i))
    teksti = teksti.replace('skuid "debian-tor"', "skuid 0").replace('skuid "root"', "skuid 0")
    assert 'skuid "' not in teksti
    return teksti


@unittest.skipUnless(nft_ohjelma() and iptables_legacy() and shutil.which("nsenter"),
                     "nft, unshare -rn, nsenter tai iptables-legacy ei kaytettavissa")
class KerrosSimulaatioTesti(unittest.TestCase):
    """Isannan nft-taulu ja Tailscalen legacy-saannot yhta aikaa, seka kontin kill switch WireGuardin kanssa."""

    @classmethod
    def setUpClass(cls):
        lan, ts_isanta, ts_vertainen = ip4(192, 168, 77, 1), ip4(100, 100, 0, 1), ip4(100, 100, 0, 2)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "isanta.nft"), "w", encoding="utf-8") as f:
                f.write(isanta_taulu())
            osoitteet = os.path.join(d, "osoitteet.nft")
            with open(osoitteet, "w", encoding="utf-8") as f:
                f.write("define CT122 = 198.18.0.2\ndefine LAHIVERKOT4 = { 198.51.100.0/24 }\n"
                        + wg.nft_maaritykset("203.0.113.10", 51820))
            with open(os.path.join(d, "kontti.nft"), "w", encoding="utf-8") as f:
                f.write(kontin_saannot(osoitteet))
            shutil.copy(os.path.join(TAMA, "sim_apu.py"), d)
            env = dict(os.environ, IPT=shlex.join(iptables_legacy()), LAN_IP=lan, TS_ISANTA=ts_isanta,
                       TS_VERTAINEN=ts_vertainen, TS_VERKKO=ip4(100, 100, 0, 0) + "/24",
                       PATH=os.environ.get("PATH", "") + ":/usr/sbin:/sbin")
            r = subprocess.run(["unshare", "-rn", "bash", os.path.join(TAMA, "sim_kerrokset.sh"), d],
                               capture_output=True, text=True, timeout=240, env=env)
        cls.stderr = r.stderr
        cls.tulokset = {}
        for rivi in r.stdout.splitlines():
            if rivi.startswith("TULOS "):
                _, nimi, arvo = (rivi.split(" ", 2) + [""])[:3]
                cls.tulokset[nimi] = arvo.strip()

    def tulos(self, nimi):
        self.assertIn(nimi, self.tulokset, "puuttuu %s; stderr: %s" % (nimi, self.stderr[-1500:]))
        return self.tulokset[nimi]

    def test_simulaatio_ajettiin_loppuun(self):
        for nimi in ("legacy_ladattu", "isanta_nft_ladattu", "B_kontti_nft_ladattu", "valmis"):
            self.assertEqual(self.tulos(nimi), "0", nimi)

    def test_isanta_vain_wireguard_ulos(self):
        self.assertEqual(self.tulos("A_wg_udp"), "OK")
        self.assertEqual(self.tulos("A_wg_lahettaja_isanta"), "1")        # NAT: palvelin nakee vain isannan
        self.assertEqual(self.tulos("A_wg_vaara_portti_perilla"), "0")
        self.assertEqual(self.tulos("A_tcp_443_ilman_asennusta"), "ESTO timeout")
        self.assertEqual(self.tulos("A_tcp_443_asennus_poistettu"), "ESTO timeout")

    def test_asennusaika_vain_80_443_ei_lahiverkkoon(self):
        self.assertEqual(self.tulos("A_tcp_443_asennus"), "OK")
        self.assertEqual(self.tulos("A_tcp_22_asennus"), "ESTO timeout")
        self.assertEqual(self.tulos("A_lan_asennus"), "ESTO timeout")
        self.assertEqual(self.tulos("A_tailnet_asennus"), "ESTO timeout")
        self.assertEqual(self.tulos("A_isanta"), "ESTO timeout")
        self.assertNotEqual(self.tulos("A_laskuri_lahiverkko"), "0")
        self.assertNotEqual(self.tulos("A_laskuri_isanta"), "0")

    def test_tailscalen_reititys_ja_nat_toimivat_rinnalla(self):
        self.assertEqual(self.tulos("A_ts_nat_ennen"), "0")               # kontin liikenne ei osu Tailscalen NAT:iin
        self.assertEqual(self.tulos("A_tailnet_internetiin"), "OK")
        self.assertEqual(self.tulos("A_ts_nat_jalkeen"), "1")
        self.assertEqual(self.tulos("A_tailnet_lahettaja_isanta"), "2")   # asennuskoe + tailnet-vertainen
        self.assertEqual(self.tulos("A_tailnet_konttiin"), "ESTO timeout")
        self.assertEqual(self.tulos("A_kotiverkko_tailnetiin"), "ESTO timeout")
        self.assertEqual(self.tulos("A_kotiverkko_konttiin"), "ESTO timeout")

    def test_kontti_wireguard_vain_merkittyna(self):
        self.assertEqual(self.tulos("B_udp_ilman_merkkia"), "ESTO PermissionError")
        self.assertEqual(self.tulos("B_wg_merkitty"), "OK")
        self.assertEqual(self.tulos("B_wg_merkitty_vaara_portti"), "ESTO PermissionError")
        self.assertEqual(self.tulos("B_wg_merkitty_vaara_osoite"), "ESTO PermissionError")

    def test_tor_vain_wg0_ja_tcp(self):
        self.assertEqual(self.tulos("B_tor_wg0"), "OK")
        self.assertEqual(self.tulos("B_tunnelin_lahettaja"), "1")
        self.assertEqual(self.tulos("B_tor_udp_wg0"), "ESTO PermissionError")
        # TCP:n paikallinen esto nakyy aikakatkaisuna (ydin yrittaa SYN:ia uudelleen); ilman estoa kuuntelija vastaisi.
        self.assertEqual(self.tulos("B_tor_lan"), "ESTO timeout")

    def test_wg0_alhaalla_mitaan_ei_lahde(self):
        # Vanhan yhteyden paketit eivat paase eth0:aan, kun wg0 katoaa.
        self.assertEqual(self.tulos("B_vuoto"), "LAHETETTY")
        self.assertEqual(self.tulos("B_vuoto_esto_kasvoi"), "kylla")
        self.assertEqual(self.tulos("B_vuoto_data_perilla"), "0")
        self.assertEqual(self.tulos("B_vuoto_isannalle"), "0")              # mitaan ei lahtenyt kontista
        # Uudet yhteydet estyvat kontissa, vaikka isanta sallisi asennusaikaisen liikenteen.
        self.assertEqual(self.tulos("B_wg0_alhaalla_tcp"), "ESTO timeout")
        self.assertEqual(self.tulos("B_wg0_alhaalla_dns"), "ESTO PermissionError")


if __name__ == "__main__":
    unittest.main()
