"""Yksityisen tilan kehotteen saannot on numeroitu 1..N ilman aukkoja ja kaksoisnumeroita (kokooma #441 #442 #444 #445).

Rinnakkaiset PR:t lisasivat kukin oman saannon numerolla 9. Testi lukee oikean kutsupolun lahtevan rungon
kummallekin taustapaalle (kysy_paikalliselta, kysy_openrouterilta) ja varmistaa, etta saannot 9-11 ovat
rakenne, Syvenna ja korjaukset, kukin kerran. Ei verkkoa eika oikeita avaimia."""
import re
import unittest

from aivo import yksityinen, yksityinen_or as yo
from aivo.test_yksityinen_rehellisyys import Taustapaat, historia

SAANNOT_OTSIKKO = "S\u00e4\u00e4nn\u00f6t:\n"
YDINOHJEET_ALKU = "\nYDINOHJEET ("
NUMERO_RE = re.compile(r"^(\d+)\. ", re.M)
# saannon numero -> tunnusteksti, joka on vain siina saannossa
TUNNUS = {
    9: "Kun kerrot omasta rakenteestasi",
    10: "[[SYVENNA]]",
    11: "tonyn-korjaukset",
}


def saantoosa(k):
    """Kehotteen saantoosa: otsikosta YDINOHJEET-osioon (muisti ja ydinohjeet voivat sisaltaa omia numeroitaan)."""
    alku = k.index(SAANNOT_OTSIKKO) + len(SAANNOT_OTSIKKO)
    loppu = k.find(YDINOHJEET_ALKU, alku)
    return k[alku:] if loppu < 0 else k[alku:loppu]


def saannot(osa):
    """(numerot jarjestyksessa, {numero: ensimmaisen saannon teksti}). Kaksoisnumero nakyy numerolistassa."""
    osumat = list(NUMERO_RE.finditer(osa))
    numerot = [int(m.group(1)) for m in osumat]
    tekstit = {}
    for i, m in enumerate(osumat):
        loppu = osumat[i + 1].start() if i + 1 < len(osumat) else len(osa)
        tekstit.setdefault(int(m.group(1)), osa[m.start():loppu])
    return numerot, tekstit


class SaantonumerotTesti(Taustapaat):
    def kehotteet(self):
        return {"paikallinen": self.paikallinen(historia(1))[0]["content"],
                "openrouter": self.openrouter(historia(1))[0]["content"],
                "vakio-paikallinen": yksityinen.YKSITYINEN_KEHOTE,
                "vakio-openrouter": yo.KEHOTE}

    def test_numerointi_yhtenainen(self):
        for nimi, k in self.kehotteet().items():
            with self.subTest(nimi):
                numerot, _ = saannot(saantoosa(k))
                self.assertEqual(numerot, list(range(1, len(numerot) + 1)), numerot)
                self.assertGreaterEqual(len(numerot), 11)

    def test_saannot_9_10_11(self):
        for nimi, k in self.kehotteet().items():
            with self.subTest(nimi):
                _, tekstit = saannot(saantoosa(k))
                for n, tunnus in TUNNUS.items():
                    self.assertIn(tunnus, tekstit[n], (n, tekstit[n][:80]))
                    muut = [m for m, t in tekstit.items() if m != n and tunnus in t]
                    self.assertEqual(muut, [], (n, tunnus))
                    self.assertEqual(saantoosa(k).count("\n%d. " % n), 1)

    def test_tunnistaa_kaksoisnumeron(self):
        """Testin oma tarkistus: kaksi saantoa numerolla 9 ei mene lapi."""
        numerot, _ = saannot("1. a\n2. b\n9. c\n9. d\n")
        self.assertNotEqual(numerot, list(range(1, len(numerot) + 1)))

    def test_saantoosa_ei_lue_muistia(self):
        k = yksityinen.muodosta_viestit("12. muistin rivi", historia(1), "13. ohje")[0]["content"]
        numerot, _ = saannot(saantoosa(k))
        self.assertNotIn(12, numerot)
        self.assertNotIn(13, numerot)


if __name__ == "__main__":
    unittest.main()
