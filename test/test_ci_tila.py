import io
import unittest
import urllib.error
from contextlib import redirect_stdout

from agentti import ci_tila


def tekaise(runit, sha="72f000f1234", virhe=None):
    kutsut = []

    def hae(url):
        kutsut.append(url)
        if virhe:
            raise virhe
        if "/pulls/" in url:
            return {"head": {"sha": sha}}
        return {"check_runs": runit}
    hae.kutsut = kutsut
    return hae


def ajo(nimi, status="completed", conclusion="success"):
    return {"name": nimi, "status": status, "conclusion": conclusion}


class CiTilaTesti(unittest.TestCase):
    def test_vihrea(self):
        hae = tekaise([ajo("a"), ajo("b", conclusion="skipped"), ajo("c")])
        self.assertEqual(ci_tila.tila("agentti-pohja", 285, hae), ("pr=285 sha=72f000f ci=vihrea (3/3)", 0))
        self.assertEqual(len(hae.kutsut), 2)

    def test_punainen(self):
        rivi, koodi = ci_tila.tila("agentti-pohja", 285, tekaise([ajo("lint"), ajo("test", conclusion="failure")]))
        self.assertEqual((rivi, koodi), ("pr=285 sha=72f000f ci=punainen (nimi: test)", 1))

    def test_kesken(self):
        rivi, koodi = ci_tila.tila("agentti-pohja", 285, tekaise([ajo("a"), ajo("b", status="in_progress", conclusion=None)]))
        self.assertEqual((rivi, koodi), ("pr=285 sha=72f000f ci=kesken", 2))

    def test_ei_ajoja(self):
        rivi, koodi = ci_tila.tila("agentti-pohja", 285, tekaise([]))
        self.assertEqual((rivi, koodi), ("pr=285 sha=72f000f ci=ei-ajoja", 2))

    def test_http_403(self):
        virhe = urllib.error.HTTPError("https://x/salainen", 403, "viesti-jossa-salaisuus", {}, None)
        rivi, koodi = ci_tila.tila("agentti-pohja", 285, tekaise([], virhe=virhe))
        self.assertEqual((rivi, koodi), ("pr=285 ci=haku-epaonnistui (HTTPError 403)", 3))
        self.assertNotIn("salai", rivi)

    def test_main_paluukoodi_ja_tuloste(self):
        ulos = io.StringIO()
        with redirect_stdout(ulos):
            koodi = ci_tila.main(["agentti-pohja", "285"], tekaise([ajo("a")]))
        self.assertEqual((koodi, ulos.getvalue().strip()), (0, "pr=285 sha=72f000f ci=vihrea (1/1)"))

    def test_main_vaarat_argumentit(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ci_tila.main(["tuntematon", "1"], tekaise([])), 3)
            self.assertEqual(ci_tila.main(["agentti-pohja", "x"], tekaise([])), 3)


if __name__ == "__main__":
    unittest.main()
