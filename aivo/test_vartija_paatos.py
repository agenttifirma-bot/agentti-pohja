"""Vuotovartijan kolme lopputulosta: turvallinen, kysy, esta (Tonyn paatos A1096, 25.11.2026). Vain stdlib.

Avaimen nakoiset merkkijonot kootaan osista (_k), jotta repon skannerit eivat loyda niita kokonaisina."""
import json
import unittest
from pathlib import Path

from aivo import luovutus, luovutuspaketti as lp, vartija, yksityinen
from aivo.test_luovutus import LuovutusPohja
from aivo.test_luovutuspaketti import PakettiPohja, sallii
from aivo.test_vartija import kysy_palauttaa


def _k(*osat):
    return "".join(osat)


def _ip(*osat):
    # sisaverkon osoitteet kootaan osista: test_repo hylkaa ne kirjaimellisina repossa
    return ".".join(map(str, osat))


# (tyyppi, teksti): jokaisen pitaa estaa hyvaksynta
ESTOT = [
    ("SSH-yksityisavain", "avain:\n" + _k("-----BEGIN ", "OPENSSH ", "PRIVATE", " KEY-----") + "\nb3BlbnNz\n"),
    ("SSH-julkisavain", "lisaa " + _k("ssh-ed25519 AAAA", "C3NzaC1lZDI1NTE5AAAAIHq3x9k2Lm8pQ7rT5vW1") + " kone\n"),
    ("API-avain", "arvo " + _k("gh", "p_", "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z00") + ".\n"),
    ("API-avain", "arvo " + _k("sk", "-or-v1-", "0123456789abcdefABCDEF0123") + ".\n"),
    ("avain avainsanan j\u00e4lkeen", "asetus API_KEY=" + _k("Zq8vR2m", "X9pL4tK7wN3bY6cH1") + "\n"),
    ("henkil\u00f6tunnus", "Hetu 131052-308T.\n"),
    ("tilinumero", "Tili FI21 1234 5600 0007 85.\n"),
    ("tailnet-nimi", "Kone " + ".".join(["kone", "tail1a2b3c", "ts", "net"]) + ".\n"),
    ("yksityinen IP-osoite", "Palvelin " + _ip(192, 168, 7, 20) + ".\n"),
    ("yksityinen IP-osoite", "Palvelin " + _ip(10, 20, 30, 40) + ".\n"),
    ("yksityinen IP-osoite", "Palvelin " + _ip(172, 16, 5, 4) + ".\n"),
    ("yksityinen IP-osoite", "Tailscale " + _ip(100, 64, 9, 9) + ".\n"),
    ("yksityinen IP-osoite", "Varakone fd12:3456:789a:1:0:0:0:1.\n"),
]
KYSYT = [
    ("s\u00e4hk\u00f6postiosoite", "Posti maija@example.org.\n"),
    ("puhelinnumero", "Soita 040-7654321.\n"),
    ("IP-osoite", "Dokumentaatio 203.0.113.14.\n"),
    ("IP-osoite", "Julkinen 8.8.8.8.\n"),
]
EI = {"tila": vartija.TILA_TARKISTETTU, "arvio": "ei", "merkinnat": []}


class PaatosTesti(unittest.TestCase):
    def tulos(self, teksti, malli=EI, nimet=(), sanat=()):
        return vartija.paatos(vartija.mekaaniset_tyypit(teksti, nimet, sanat), malli)

    def test_jokainen_estotyyppi_estaa(self):
        for tyyppi, teksti in ESTOT:
            self.assertEqual(self.tulos(teksti), {"tulos": vartija.TULOS_ESTA, "syyt": [tyyppi]}, tyyppi)
            # esto ei riipu mallista: ei mallia, malli "ei" tai "suuri"
            self.assertEqual(self.tulos(teksti, None)["tulos"], vartija.TULOS_ESTA, tyyppi)

    def test_muut_mekaaniset_ja_listat_kysyvat(self):
        for tyyppi, teksti in KYSYT:
            self.assertEqual(self.tulos(teksti), {"tulos": vartija.TULOS_KYSY, "syyt": [tyyppi]}, tyyppi)
        p = self.tulos("Maija asuu Kuvitteelassa.\n", nimet=["Maija"], sanat=["Kuvitteela"])
        self.assertEqual(p, {"tulos": vartija.TULOS_KYSY, "syyt": ["nimi nimilistalta", "avainsana"]})
        self.assertNotIn("Maija", json.dumps(p))                     # syy on tyyppi, ei sisaltoa

    def test_mallin_arvio(self):
        puhdas = "Toteuta mittari X.\n"
        for arvio in ("ei", "pieni"):
            m = dict(EI, arvio=arvio, merkinnat=[{"kohta": "X", "syy": "y"}])
            self.assertEqual(self.tulos(puhdas, m), {"tulos": vartija.TULOS_TURVALLINEN, "syyt": []}, arvio)
        self.assertEqual(self.tulos(puhdas, dict(EI, arvio="suuri")),
                         {"tulos": vartija.TULOS_KYSY, "syyt": ["vartijamallin arvio suuri"]})

    def test_ilman_kelvollista_mallin_tulosta_ei_koskaan_turvallinen(self):
        puhdas = "Toteuta mittari X.\n"
        for m in (None, {}, {"tila": vartija.TILA_KESKEN}, {"tila": vartija.TILA_EI_TARKISTANUT, "arvio": "ei"},
                  {"tila": vartija.TILA_TARKISTETTU}, dict(EI, arvio="EI-TIEDOSSA"), "ei", 0):
            self.assertEqual(self.tulos(puhdas, m)["tulos"], vartija.TULOS_KYSY, m)

    def test_esto_ei_piiloudu_rajan_tai_paallekkaisyyden_taakse(self):
        teksti = " ".join("p%d@example.org" % i for i in range(vartija.MAX_MERKINTOJA + 10)) + " " + ESTOT[2][1]
        self.assertEqual(len(vartija.mekaaninen(teksti)), vartija.MAX_MERKINTOJA)     # naytto rajattu
        self.assertEqual(self.tulos(teksti)["tulos"], vartija.TULOS_ESTA)

    def test_mallin_vastauksen_arvio_tallentuu(self):
        t = vartija.tarkista_mallilla("x", kysy_palauttaa('{"arvio": "Suuri", "merkinnat": []}'))
        self.assertEqual((t["tila"], t["arvio"]), (vartija.TILA_TARKISTETTU, "suuri"))
        t = vartija.tarkista_mallilla("x", kysy_palauttaa('{"merkinnat": []}'))
        self.assertEqual(t["tila"], vartija.TILA_TARKISTETTU)
        self.assertNotIn("arvio", t)
        self.assertEqual(vartija.paatos([], t)["syyt"], ["vartijamallin arvio puuttuu"])

    def test_lisavahvistus_sidottu_shaan(self):
        sha = yksityinen.sha("x")
        self.assertTrue(vartija.lisavahvistus_kelpaa("tarkistin kohdat " + sha[:8], sha))
        for v in (None, "", "tarkistin kohdat " + "0" * 8, "Tarkistin kohdat " + sha[:8], "tarkistin kohdat " + sha[:8] + " ",
                  "kyll\u00e4 " + sha[:8]):
            self.assertFalse(vartija.lisavahvistus_kelpaa(v, sha), v)


class HyvaksyntaKirjastoTesti(LuovutusPohja):
    """luovutus.hyvaksy suoraan: esto lasketaan aina itse, kutsujan tarkistus ei voi loiventaa sita."""

    def test_lepsu_tarkistus_ei_ohita_estoa(self):
        for tyyppi, teksti in ESTOT:
            t, s8 = self.ehdota_luovutus(teksti)
            with self.assertRaises(luovutus.VartijaEsto) as k:
                luovutus.hyvaksy(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto,
                                 julkaise=lambda *a, **kw: "ei-gitissa",
                                 tarkistus=lambda tx, sha: {"tulos": vartija.TULOS_TURVALLINEN, "syyt": []},
                                 lisavahvistus="tarkistin kohdat " + s8)
            self.assertEqual((k.exception.tulos, k.exception.syyt), (vartija.TULOS_ESTA, [tyyppi]))
        self.assertEqual(self.saapuneet_tiedostot(), [])
        self.assertEqual(luovutus.lue_loki(self.tila.luovutukset), [])          # ei lokirivia: mitaan ei lahtenyt

    def test_kaatuva_tai_kelvoton_tarkistus_on_kysy(self):
        def kaatuu(tx, sha):
            raise RuntimeError("x")
        for tarkistus in (kaatuu, lambda tx, sha: None, lambda tx, sha: {"tulos": "ok"}):
            p = luovutus.vartijan_paatos("Toteuta X.\n", yksityinen.sha("Toteuta X.\n"), tarkistus)
            self.assertEqual(p["tulos"], vartija.TULOS_KYSY)

    def test_oletus_ilman_tarkistusta_on_kysy(self):
        t, s8 = self.ehdota_luovutus()
        with self.assertRaises(luovutus.VartijaEsto):
            luovutus.hyvaksy(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto,
                             julkaise=lambda *a, **kw: "ei-gitissa")
        self.assertEqual(luovutus.hyvaksy(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto,
                                          julkaise=lambda *a, **kw: "ei-gitissa", lisavahvistus="tarkistin kohdat " + s8),
                         "ei-gitissa")


class HyvaksyntaApiTesti(LuovutusPohja):
    """Suora API-kutsu: palvelin laskee lopputuloksen hyvaksyntahetkella samasta tekstista."""

    def setUp(self):
        super().setUp()
        self.tila.vartija_ajo = lambda f: f()
        self.tila.vartija_kysy = kysy_palauttaa('{"arvio": "ei", "merkinnat": []}')

    def ehdota_ja_tarkista(self, teksti):
        t, s8 = self.ehdota_luovutus(teksti)
        self.tila.kaynnista_vartija(t)
        return t, s8

    def test_jokainen_estotyyppi_estaa_suoralla_kutsulla(self):
        kid = self.uusi()
        for tyyppi, teksti in ESTOT:
            t, s8 = self.ehdota_ja_tarkista(teksti)
            s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)                 # myos lisavahvistuksen kanssa
            self.assertEqual(s, 409, tyyppi)
            self.assertEqual(d["vartija"], {"tulos": vartija.TULOS_ESTA, "syyt": [tyyppi]})
            self.assertNotIn(teksti.strip()[-12:-1], json.dumps(d, ensure_ascii=False))   # ei sisaltoa vastaukseen
            k = self.pyynto("GET", "/api/luovutus?keskustelu=%s&tunnus=%s" % (kid, t))[1]["vartija"]
            self.assertEqual((k["tulos"], k["syyt"]), (vartija.TULOS_ESTA, [tyyppi]))
        self.assertEqual(self.saapuneet_tiedostot(), [])
        self.assertEqual(luovutus.lue_loki(self.tila.luovutukset), [])

    def test_esto_poistuu_vasta_muokkauksella_ja_uudella_tarkistuksella(self):
        kid = self.uusi()
        t, s8 = self.ehdota_ja_tarkista("Palvelin " + _ip(192, 168, 7, 20) + " on valmis.\n")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 409)
        s, d = self.pyynto("POST", "/api/luovutus/muokkaa", {"keskustelu": kid, "tunnus": t, "teksti": "Palvelin on valmis.\n"})
        self.assertEqual((s, d["vartija"]["tulos"]), (200, vartija.TULOS_TURVALLINEN))
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)[0], 409)          # vanha sha ei kelpaa
        s, h = self.hyvaksy_l(kid, t, "kyll\u00e4 " + d["sha8"], lisa=False)
        self.assertEqual((s, h.get("tulos")), (200, "ei-gitissa"))
        self.assertEqual(luovutus.lue_saapunut(self.tila.kirjasto, t)["teksti"], "Palvelin on valmis.\n")

    def test_kysy_vaatii_lisavahvistuksen(self):
        kid = self.uusi()
        self.tila.vartija_kysy = kysy_palauttaa('{"arvio": "suuri", "merkinnat": [{"kohta": "Kuvitteelassa", "syy": "paikka"}]}')
        teksti = "Maija asuu Kuvitteelassa, maija@example.org.\n"
        t, s8 = self.ehdota_ja_tarkista(teksti)
        k = self.pyynto("GET", "/api/luovutus?keskustelu=%s&tunnus=%s" % (kid, t))[1]["vartija"]
        self.assertEqual((k["tulos"], k["syyt"]), (vartija.TULOS_KYSY, ["s\u00e4hk\u00f6postiosoite", "vartijamallin arvio suuri"]))
        s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)
        self.assertEqual((s, d["vartija"]["tulos"]), (409, vartija.TULOS_KYSY))
        s, d = self.pyynto("POST", "/api/luovutus/hyvaksy", {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8,
                                                              "lisavahvistus": "tarkistin kohdat 00000000"})
        self.assertEqual(s, 409)                                                        # toisen sha:n lisavahvistus
        s, d = self.pyynto("POST", "/api/luovutus/hyvaksy", {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8,
                                                              "lisavahvistus": "kylla"})
        self.assertEqual(s, 400)                                                        # vaara muoto
        self.assertEqual(self.saapuneet_tiedostot(), [])
        s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8)
        self.assertEqual((s, d.get("tulos")), (200, "ei-gitissa"))

    def test_kesken_oleva_vartija_on_kysy(self):
        jono = []
        self.tila.vartija_ajo = jono.append
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        self.tila.kaynnista_vartija(t)
        s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)
        self.assertEqual((s, d["vartija"]["syyt"]), (409, ["vartijamalli tarkistaa viel\u00e4"]))

    def test_vartijan_virhe_on_kysy(self):
        def kaatuu(_v):
            raise TimeoutError("x")
        self.tila.vartija_kysy = kaatuu
        kid = self.uusi()
        t, s8 = self.ehdota_ja_tarkista("Toteuta mittari X.\n")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)[0], 409)
        self.tila.vartija_kysy = kysy_palauttaa("ei jsonia")
        t, s8 = self.ehdota_ja_tarkista("Toteuta mittari Y.\n")
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)[0], 409)

    def test_turvallinen_kulkee_kuten_ennen(self):
        kid = self.uusi()
        t, s8 = self.ehdota_ja_tarkista("Toteuta mittari X.\n")
        k = self.pyynto("GET", "/api/luovutus?keskustelu=%s&tunnus=%s" % (kid, t))[1]["vartija"]
        self.assertEqual((k["tulos"], k["syyt"]), (vartija.TULOS_TURVALLINEN, []))
        s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)
        self.assertEqual((s, d.get("tulos")), (200, "ei-gitissa"))

    def test_mallin_tulos_toisesta_shasta_ei_kelpaa(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus("Toteuta mittari X.\n")
        vartija.tallenna_tulos(self.tila.luovutukset, t, {"sha": "0" * 64, "tila": vartija.TILA_TARKISTETTU,
                                                          "arvio": "ei", "merkinnat": []})
        self.tila.vartija_kysy = None
        self.assertEqual(self.hyvaksy_l(kid, t, "kyll\u00e4 " + s8, lisa=False)[0], 409)


class PakettiPaatosTesti(PakettiPohja):
    def test_estotyyppi_estaa_palan_vaikka_vartija_sallisi(self):
        for tyyppi, teksti in ESTOT[:3] + ESTOT[-2:]:
            t = lp.tallenna_paketti(self.tila.luovutukset, "V", [(1, "ok\n"), (2, teksti)], vartija=sallii)
            d = lp.lue_paketti(self.tila.luovutukset, t)
            with self.assertRaises(luovutus.VartijaEsto) as k:
                lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                                   julkaise=lambda *a, **kw: "ei-gitissa", vartija=sallii,
                                   lisavahvistus="tarkistin kohdat " + d["sha"][:8])
            self.assertEqual((k.exception.tulos, k.exception.syyt), (vartija.TULOS_ESTA, ["pala 2"]), tyyppi)
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_oletuskoukku_estaa_api_kutsussa(self):
        kid = self.uusi()
        self.vastaus = ("[[LUOVUTUSPAKETTI P]]\n[[PALA 1]]\nok\n[[/PALA]]\n[[PALA 2]]\nPalvelin " + _ip(10, 0, 0, 5) + ".\n[[/PALA]]\n"
                        "[[/LUOVUTUSPAKETTI]]")
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "x"})
        [t] = v["paketit"]
        e = self.hae(kid, t)
        self.assertEqual([p["vartija"]["sallittu"] for p in e["palat"]], [None, False])
        s, d = self.hyvaksy_p(kid, t, "kyll\u00e4 " + e["sha8"])
        self.assertEqual((s, d["vartija"]["tulos"]), (409, vartija.TULOS_ESTA))
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_kysy_pala_vaatii_lisavahvistuksen(self):
        kid, t, v = self.paketti()
        e = self.hae(kid, t)
        s, d = self.hyvaksy_p(kid, t, "kyll\u00e4 " + e["sha8"], lisa=False)
        self.assertEqual((s, d["vartija"]["tulos"]), (409, vartija.TULOS_KYSY))
        self.assertEqual(self.saapuneet_tiedostot(), [])
        s, d = self.hyvaksy_p(kid, t, "kyll\u00e4 " + e["sha8"])
        self.assertEqual((s, d.get("tulos")), (200, "ei-gitissa"))

    def test_vartijan_hyvaksyma_paketti_ei_vaadi_lisavahvistusta(self):
        t = lp.tallenna_paketti(self.tila.luovutukset, "V", [(1, "ok\n")], vartija=sallii)
        d = lp.lue_paketti(self.tila.luovutukset, t)
        self.assertEqual(lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                                            julkaise=lambda *a, **kw: "ei-gitissa", vartija=sallii), "ei-gitissa")

    def test_nimilista_tekee_palasta_kysyn(self):
        lista = Path(self.tila.luovutukset) / vartija.KANSIO
        lista.mkdir(mode=0o700, exist_ok=True)
        (lista / vartija.NIMET).write_text("Maija\n", encoding="utf-8")
        t = lp.tallenna_paketti(self.tila.luovutukset, "V", [(1, "Maija soittaa.\n")], vartija=sallii)
        d = lp.lue_paketti(self.tila.luovutukset, t)
        with self.assertRaises(luovutus.VartijaEsto) as k:
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                               julkaise=lambda *a, **kw: "ei-gitissa", vartija=sallii)
        self.assertEqual(k.exception.tulos, vartija.TULOS_KYSY)


class SivuTesti(unittest.TestCase):
    def test_kortti_nayttaa_tuloksen_ja_lisavahvistuksen(self):
        from aivo import chat
        h = chat.sivu_html("openrouter")
        for osa in ("e.tulos==='esta'", "lisa.lisavahvistus='tarkistin kohdat '+e.sha8", "'Estetty: '+sy",
                    "'Kysy: '+(sy||", "l.disabled=e.tulos==='esta'", "if(e.tulos==='esta')l.disabled=ta.value===e.teksti"):
            self.assertIn(osa, h)
        # JS-merkkijonon rivinvaihto pitaa olla \\n sivulla; Pythonin \\n ilman kahdennusta rikkoisi koko skriptin
        self.assertIn("join('\\n')", h)
        self.assertNotIn("join('\n')", h)


if __name__ == "__main__":
    unittest.main()
