"""Vuotovartijan synteettinen aineisto ja mittaus (aivo/vartija_aineisto.py, aivo/vartija_mittaus.py).

Vain stdlib, ei verkkoa eika mallikutsuja. Kaikki tiedot ovat keksittyja tai varatuilta alueilta."""
import contextlib
import io
import ipaddress
import json
import os
import socket
import tempfile
import unittest
from unittest import mock

from aivo import vartija, vartija_aineisto as va, vartija_mittaus as vm

AINEISTO = va.generoi()


class AineistoTesti(unittest.TestCase):
    def test_toistettava_siemenella(self):
        self.assertEqual(va.generoi(), AINEISTO)
        self.assertNotEqual(va.generoi(1)[0]["teksti"], AINEISTO[0]["teksti"])

    def test_maarat_ja_sanamaarat(self):
        luokat = [t["luokka"] for t in AINEISTO]
        self.assertEqual(luokat.count(va.TURVALLINEN), 50)
        self.assertEqual(luokat.count(va.ARKALUONTEINEN), 50 + va.ESTOTEKSTEJA)
        self.assertEqual(luokat.count(va.VAIKEA), 10)
        self.assertEqual(len({t["tunnus"] for t in AINEISTO}), 110 + va.ESTOTEKSTEJA)
        for t in AINEISTO:
            self.assertTrue(va.SANAT_MIN <= len(t["teksti"].split()) <= va.SANAT_MAX, t["tunnus"])
            self.assertEqual(t["sanoja"], len(t["teksti"].split()))

    def test_totuus_osoittaa_oikeaan_kohtaan(self):
        for t in AINEISTO:
            for e in t["elementit"]:
                self.assertIn(e["tyyppi"], va.TYYPIT)
                self.assertEqual(t["teksti"][e["alku"]:e["loppu"]], e["kohta"], t["tunnus"])

    def test_turvallisissa_ei_elementteja_muissa_on(self):
        for t in AINEISTO:
            if t["luokka"] == va.TURVALLINEN:
                self.assertEqual(t["elementit"], [], t["tunnus"])
            else:
                self.assertTrue(t["elementit"], t["tunnus"])
        vaikeat = [t for t in AINEISTO if t["luokka"] == va.VAIKEA]
        self.assertTrue(all(len(t["elementit"]) == 1 for t in vaikeat))
        muodot = {t["elementit"][0]["muoto"] for t in vaikeat}
        self.assertEqual(muodot, {"kiertoilmaus", "pilkottu", "aakkoset"})

    def test_vain_varattuja_ja_keksittyja_tietoja(self):
        sallitut_verkot = [ipaddress.ip_network(v) for v in
                           ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]
        tyypit = set()
        for t in AINEISTO:
            for e in t["elementit"]:
                k, muoto = e["kohta"], e["muoto"]
                tyypit.add(e["tyyppi"])
                if e["tyyppi"] == "sahkoposti" and muoto in ("tavallinen", "aakkoset"):
                    self.assertIn(k.rsplit("@", 1)[1], va.DOMAINIT)
                if e["tyyppi"] == "sahkoposti" and muoto != "tavallinen":
                    self.assertTrue(any(d.split(".")[0] in k.replace(" ", "") for d in va.DOMAINIT), k)
                if e["tyyppi"] == "ip":
                    osoite = k.replace(" piste ", ".").replace(" ", "")
                    ip = ipaddress.ip_address(osoite)
                    self.assertTrue(any(ip in v for v in sallitut_verkot), k)
                if e["tyyppi"] == "yksityinen-ip":
                    self.assertIn(vartija.ip_luokka(k), vartija.ESTO_IP_LUOKAT, k)
                    ip = vartija._ip(k)
                    ip4 = ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip
                    if ip4.version == 4:          # tunnetut kotiverkon ja tailnetin aliverkot eivat ole aineistossa
                        self.assertNotIn(str(ip4).rsplit(".", 1)[0], (".".join(["192", "168", "0"]), ".".join(["192", "168", "1"])), k)
                        self.assertFalse(str(ip4).startswith(".".join(["100", "87", ""])), k)
                if e["tyyppi"] == "tailnet":
                    self.assertTrue(k.endswith(".".join(["", "example-tailnet", "ts", "net"])), k)
                if e["tyyppi"] == "hetu":
                    h = k.replace(" ", "").upper()
                    self.assertEqual(h[6], "+", k)          # 1800-luku
                    self.assertEqual(va.HETU_TARKISTE[int(h[:6] + h[7:10]) % 31], h[10])
                if e["tyyppi"] in ("nimi", "paikka"):
                    self.assertIn(k, ("[ETUNIMI]", "[SUKUNIMI]", "[KAUPUNKI]"))
        self.assertEqual(tyypit, set(va.TYYPIT))

    def test_iban_tarkiste_on_oikein(self):
        for t in AINEISTO:
            for e in t["elementit"]:
                if e["tyyppi"] == "iban":
                    s = e["kohta"].replace(" ", "").upper()
                    luku = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
                    self.assertEqual(int(luku) % 97, 1, e["kohta"])

    def test_kirjoitus_ja_luku(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(va.main(["--ulos", d, "--siemen", "7"]), 0)
            self.assertEqual(len([n for n in os.listdir(d) if n.endswith(".totuus.json")]), 110 + va.ESTOTEKSTEJA)
            with open(os.path.join(d, "a001.totuus.json"), encoding="utf-8") as f:
                self.assertEqual(set(json.load(f)), {"tunnus", "luokka", "sanoja", "elementit"})
            self.assertEqual(va.lue(d), va.generoi(7))


class MittausTesti(unittest.TestCase):
    def test_laskenta_kasin_tehdylla_aineistolla(self):
        teksti = "posti anna@example.org, kone 127.0.0.1 ja tili DE05 6092 4244 9565 5989 59 sek\u00e4 [ETUNIMI]."
        el = []
        for kohta, tyyppi in (("anna@example.org", "sahkoposti"), ("DE05 6092 4244 9565 5989 59", "iban"),
                              ("[ETUNIMI]", "nimi")):
            i = teksti.index(kohta)
            el.append({"tyyppi": tyyppi, "muoto": "m", "alku": i, "loppu": i + len(kohta), "kohta": kohta})
        tulos = vm.mittaa([{"tunnus": "x1", "luokka": va.ARKALUONTEINEN, "teksti": teksti, "elementit": el}])
        r = tulos["rivit"]
        self.assertEqual((r["sahkoposti"]["osumat"], r["sahkoposti"]["ohitukset"]), (1, 0))
        self.assertEqual((r["iban"]["osumat"], r["iban"]["ohitukset"]), (1, 0))     # kaikkien maiden IBAN
        self.assertEqual((r["ip"]["vaarat"], r["ip"]["vaarat_erilaiset"]), (1, 1))
        self.assertEqual(r["nimi"]["ohitukset"], 1)
        self.assertEqual(tulos["arkaluonteiset_kaikki_loytyi"], 0)
        tulos = vm.mittaa([{"tunnus": "x1", "luokka": va.ARKALUONTEINEN, "teksti": teksti, "elementit": el}],
                          nimet=["[ETUNIMI]"])
        self.assertEqual(tulos["rivit"]["nimi"]["osumat"], 1)

    def test_ristiosuma_ei_ole_osuma_eika_vaara(self):
        teksti = "numero +358 40 123 4567 loppu"
        i = teksti.index("+358")
        el = [{"tyyppi": "iban", "muoto": "m", "alku": i, "loppu": i + 16, "kohta": teksti[i:i + 16]}]
        tulos = vm.mittaa([{"tunnus": "x", "luokka": va.ARKALUONTEINEN, "teksti": teksti, "elementit": el}])
        self.assertEqual(tulos["ristiosumat"], 1)
        self.assertEqual(tulos["rivit"]["iban"]["ohitukset"], 1)
        self.assertEqual(sum(v["vaarat"] for v in tulos["rivit"].values()), 0)

    def test_avaimet_loytyvat_aineistosta(self):
        tulos = vm.mittaa(AINEISTO)
        for muoto in ("api-avain / etuliite", "avainsana-arvo / satunnainen", "ssh-yksityisavain / otsikko",
                      "ssh-julkisavain / tavallinen", "sahkoposti / tavallinen", "ip / ipv4", "iban / fi",
                      "hetu / 1800-luku"):
            self.assertEqual(tulos["muodot"][muoto]["ohitukset"], 0, muoto)
            self.assertGreater(tulos["muodot"][muoto]["osumat"], 0, muoto)
        for rivi in ("ssh-yksityisavain", "ssh-julkisavain", "api-avain", "avainsana-arvo"):
            self.assertEqual(tulos["rivit"][rivi]["vaarat"], 0, rivi)

    def test_kaikki_estotyypit_mitataan_eika_ohituksia(self):
        tulos = vm.mittaa(AINEISTO)
        muodot = {m.split(" / ")[0] for m in tulos["muodot"]}
        self.assertLessEqual({"yksityinen-ip", "tailnet", "hetu", "iban", "ssh-yksityisavain", "yksityisavain",
                              "ssh-julkisavain", "api-avain", "avainsana-arvo"}, muodot)
        for muoto in ("yksityinen-ip / ipv4", "yksityinen-ip / ipv4-nollat", "yksityinen-ip / ipv6-lyhyt",
                      "yksityinen-ip / ipv6-tailnet", "yksityinen-ip / ipv6-link-local", "yksityinen-ip / ipv6-upotettu",
                      "tailnet / ts-net", "yksityisavain / otsikko", "iban / ulkomaa", "iban / pienet", "hetu / pienet",
                      "ip / ipv6-lyhyt", "api-avain / tskey", "api-avain / google", "api-avain / stripe",
                      "api-avain / gitlab", "api-avain / huggingface", "api-avain / jwt"):
            self.assertGreater(tulos["muodot"][muoto]["osumat"], 0, muoto)
            self.assertEqual(tulos["muodot"][muoto]["ohitukset"], 0, muoto)
        for rivi in ("yksityinen-ip", "tailnet", "iban", "yksityisavain", "api-avain"):
            self.assertEqual(tulos["rivit"][rivi]["vaarat"], 0, rivi)

    def test_turvallisten_vaarat_halytykset_ovat_tunnetut(self):
        # Tunnetut vaarat halytykset (raportoitu PR #413:ssa): silmukka- ja kuunteluosoite seka MAC-osoite.
        tunnetut = {"127.0.0.1", "0.0.0.0", "00:1A:2B:3C:4D:5E"}
        for t in AINEISTO:
            if t["luokka"] == va.TURVALLINEN:
                kohdat = {m["kohta"] for m in vartija.mekaaninen(t["teksti"])}
                self.assertLessEqual(kohdat, tunnetut, t["tunnus"])

    def test_ei_verkkoa_eika_tekstin_muutosta(self):
        alkuperaiset = [t["teksti"] for t in AINEISTO]
        with mock.patch.object(socket, "socket", side_effect=AssertionError("verkko")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("verkko")):
            aineisto = va.generoi()
            vm.mittaa(aineisto)
        self.assertEqual([t["teksti"] for t in aineisto], alkuperaiset)

    def test_komentorivi_tulostaa_taulukon(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(vm.main(["--siemen", "413", "--esimerkit"]), 0)
        s = out.getvalue()
        self.assertIn("| Tyyppi | Osumat | Ohitukset | V\u00e4\u00e4r\u00e4t h\u00e4lytykset | Eri kohtia |", s)
        self.assertIn("| api-avain |", s)
        self.assertIn("Ohitukset:", s)


if __name__ == "__main__":
    unittest.main()
