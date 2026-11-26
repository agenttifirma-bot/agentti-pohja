"""Yksityisen tilan kehote kertoo tietojen kulusta oikein (OpenRouter vs. paikallinen) eika saanto 6 kiista saantoa 8.

Testit lukevat seka vakiot etta oikean kutsupolun lahtevan rungon (kysy_paikalliselta, kysy_openrouterilta).
Ei verkkoa eika oikeita avaimia."""
import unittest

from aivo import chat, yksityinen, yksityinen_or as yo
from aivo.test_yksityinen_rehellisyys import Taustapaat, historia

HARHAANJOHTAVA = "ulos l\u00e4htee vain kulloinenkin kehote"
PAIKALLINEN_LAUSE = ("sinua ajetaan Tonyn omalla\nkoneella, eik\u00e4 t\u00e4m\u00e4 keskustelu l\u00e4hde millek\u00e4\u00e4n "
                     "ulkoiselle palvelulle.")
SAANTO6_ALKU = "Sinulla ei ole verkkoa etk\u00e4 voi ajaa ohjelmia itse. Voit ehdottaa agenttiteht\u00e4v\u00e4\u00e4 s\u00e4\u00e4nn\u00f6n 8 mukaisesti."
SAANTO9 = ("Kun kerrot omasta rakenteestasi, malleista, kuluista tai siit\u00e4, mihin tieto kulkee, k\u00e4yt\u00e4 vain t\u00e4m\u00e4n kehotteen\n"
           "   ja agenttidatan faktoja [l\u00e4hde: agenttidata/faktat.md]. Jos tietoa ei ole, sano, ettet tied\u00e4. "
           "Merkitse arvio sanalla 'arvio'.")


def saanto(k, n):
    return k.split("\n%d. " % n, 1)[1].split("\n%d. " % (n + 1), 1)[0]


def yksirivi(s):
    return " ".join(s.split())


class OpenRouterLauseTesti(Taustapaat):
    def test_ei_harhaanjohtavaa_lausetta(self):
        for k in (yo.KEHOTE, yksityinen.YKSITYINEN_KEHOTE, self.openrouter(historia(1))[0]["content"],
                  self.paikallinen(historia(1))[0]["content"]):
            self.assertNotIn(HARHAANJOHTAVA, yksirivi(k))
            self.assertNotIn("vain kulloinenkin kehote", yksirivi(k))

    def test_openrouter_kertoo_mita_lahtee(self):
        k = yksirivi(self.openrouter(historia(1))[0]["content"])
        johdanto = k.split("S\u00e4\u00e4nn\u00f6t:", 1)[0]
        self.assertIn("OpenRouter", johdanto)
        self.assertIn("ZDR", johdanto)
        self.assertIn("(ydinohjeet, muisti, agenttidata ja keskustelu) l\u00e4htee jokaisella viestill\u00e4 OpenRouterille",
                      johdanto)
        self.assertIn("ei tallenneta eik\u00e4 k\u00e4ytet\u00e4 koulutukseen", johdanto)
        self.assertIn("Muisti ja keskustelut tallennetaan Tonyn omalle palvelimelle", johdanto)
        self.assertNotIn("Tonyn omalla koneella", johdanto)
        self.assertNotIn("ei l\u00e4hde mill\u00e4\u00e4n ulkoiselle", johdanto)

    def test_lause_vaihtui_oikeasti(self):
        """replace() ei saa olla hiljaa tyhja: vanha paikallinen lause ei jaa OpenRouter-kehotteeseen."""
        self.assertIn(yo._VANHA_LAUSE, yksityinen.YKSITYINEN_KEHOTE)
        self.assertNotIn(yo._VANHA_LAUSE, yo.KEHOTE)
        self.assertEqual(yo.KEHOTE, yksityinen.YKSITYINEN_KEHOTE.replace(yo._VANHA_LAUSE, yo._UUSI_LAUSE))


class PaikallinenEnnallaanTesti(Taustapaat):
    def test_paikallinen_lause_ennallaan(self):
        self.assertEqual(yo._VANHA_LAUSE, PAIKALLINEN_LAUSE)
        k = self.paikallinen(historia(1))[0]["content"]
        self.assertIn(PAIKALLINEN_LAUSE, k)
        self.assertNotIn("OpenRouter", k.split("S\u00e4\u00e4nn\u00f6t:", 1)[0])


class Saannot6ja8Testi(Taustapaat):
    def test_saanto6_ohjaa_saantoon8(self):
        for k in (self.paikallinen(historia(1))[0]["content"], self.openrouter(historia(1))[0]["content"]):
            s6 = saanto(k, 6)
            self.assertTrue(s6.startswith(SAANTO6_ALKU), s6[:120])
            self.assertNotIn("ty\u00f6kaluja", s6)                 # vanha kiisto: agenttitehtavat ovat kaytossa
            self.assertNotIn("taustaprosesseja", s6)
            self.assertIn("\u00c4l\u00e4 koskaan sano aloittavasi", s6)   # kielto aloittaa itse sailyy
            self.assertIn("[[AGENTTI]]", saanto(k, 8))

    def test_saanto9_epavarmuus(self):
        for k in (self.paikallinen(historia(1))[0]["content"], self.openrouter(historia(1))[0]["content"]):
            self.assertIn(SAANTO9, k)
            self.assertEqual(k.count("\n9. "), 1)

    def test_tyokalutila_ei_muuttunut(self):
        self.assertNotIn(SAANTO6_ALKU, chat.KEHOTE)
        self.assertNotIn(SAANTO9, chat.KEHOTE)


if __name__ == "__main__":
    unittest.main()


class Saanto9LahdeTesti(unittest.TestCase):
    """Tarkastajan loydos #441: saannon 9 lahdenimi on sama kuin muistissa (agenttidata_kehote.ETULIITE), joten
    chat.tarkista_lahteet ei merkitse oikeaa viitetta tuntemattomaksi."""

    def test_lahde_loytyy_muistista(self):
        from aivo import agenttidata_kehote
        nimet = chat.LAHDE_RE.findall(saanto(yksityinen.YKSITYINEN_KEHOTE, 9))
        self.assertEqual(nimet, [agenttidata_kehote.ETULIITE + "faktat.md"])
        tiedostot = [agenttidata_kehote.ETULIITE + n for n in agenttidata_kehote.TIEDOSTOT]
        vastaus = "Konttia 122 kaytetaan [l\u00e4hde: %s]." % nimet[0]
        self.assertEqual(chat.tarkista_lahteet(vastaus, tiedostot), (vastaus, []))
