"""ZDR-kutsupolkuvartija: lukee aivo-koodin syntaksipuuna (ast), ei pelkkana tekstina.

Taydentaa test_openrouter_zdr.py:n merkkijonovartijaa (A851, ZDR). Merkkijonovartija
ohitetaan pilkkomalla osoite (`"https://openrouter" + ".ai/x"`). Tama vartija vaatii:

  (a) jokainen `provider`-avaimen sisaltava pyyntorunko syntyy funktiossa `rakenna_runko`
      (sanakirjaliteraali, `dict(provider=...)` tai `runko["provider"] = ...`), ja
  (b) merkkijonojen yhdistelmat (`+`, `%`, f-merkkijono) eivat muodosta sanaa `openrouter`
      sallittujen tiedostojen ulkopuolella.

Skannattavat tiedostot: aivo/*.py ja claudejono/aivo_*.py, testitiedostot (test_*.py) pois.
"""
import ast
import unittest
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
RUNKO_FUNKTIO = "rakenna_runko"

# Tiedostot, joissa `openrouter` saa esiintya yhdistelmassa (b). Perustelu: moduuli
# `aivo/openrouter_zdr.py` on ainoa paikka, jonka tehtava on rakentaa OpenRouter-pyynto
# ZDR-pakotuksella. Muut tiedostot eivat saa muodostaa osoitetta.
SALLITUT_YHDISTELMAT = frozenset({"aivo/openrouter_zdr.py"})


def _skannattavat():
    tiedostot = sorted(p for p in (JUURI / "aivo").glob("*.py") if not p.name.startswith("test_"))
    tiedostot += sorted(
        p for p in (JUURI / "claudejono").glob("aivo_*.py") if not p.name.startswith("test_")
    )
    return tiedostot


def _jasenna(lahde):
    # 3.10-yhteensopivuus: ei uudempaa syntaksia kuin 3.10.
    return ast.parse(lahde, feature_version=(3, 10))


def _on_provider(solmu):
    return (
        isinstance(solmu, ast.Constant)
        and isinstance(solmu.value, str)
        and solmu.value.strip().lower() == "provider"
    )


def provider_rikkomukset(puu):
    """Rivinumerot, joilla `provider`-runko rakennetaan `rakenna_runko`-funktion ulkopuolella."""
    sallitut = set()
    for f in ast.walk(puu):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == RUNKO_FUNKTIO:
            sallitut.update(id(n) for n in ast.walk(f))
    rivit = []
    for n in ast.walk(puu):
        if id(n) in sallitut:
            continue
        if isinstance(n, ast.Dict) and any(k is not None and _on_provider(k) for k in n.keys):
            rivit.append(n.lineno)
        elif isinstance(n, ast.Call) and any(
            (k.arg or "").strip().lower() == "provider" for k in n.keywords
        ):
            rivit.append(n.lineno)
        elif isinstance(n, ast.Subscript) and _on_provider(n.slice):
            rivit.append(n.lineno)
    return sorted(set(rivit))


def _vakio_osat(solmu):
    """Yhdistelman merkkijonovakiot lahdekoodin jarjestyksessa (muuttujat ohitetaan)."""
    osat = [
        n for n in ast.walk(solmu) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    osat.sort(key=lambda n: (n.lineno, n.col_offset))
    return "".join(n.value for n in osat)


def yhdistelma_rikkomukset(puu):
    """Rivinumerot, joilla yhdistelma (BinOp, JoinedStr) sisaltaa vakioiden osalta `openrouter`."""
    rivit = []
    for n in ast.walk(puu):
        if isinstance(n, (ast.BinOp, ast.JoinedStr)) and "openrouter" in _vakio_osat(n).lower():
            rivit.append(n.lineno)
    return sorted(set(rivit))


class ZdrKutsupolkuTesti(unittest.TestCase):
    def test_skannattavia_tiedostoja_loytyy(self):
        nimet = [str(p.relative_to(JUURI)) for p in _skannattavat()]
        self.assertIn("aivo/openrouter_zdr.py", nimet)

    def test_provider_runko_vain_rakenna_runko_funktiossa(self):
        osumat = []
        for p in _skannattavat():
            for rivi in provider_rikkomukset(_jasenna(p.read_text(encoding="utf-8"))):
                osumat.append(f"{p.relative_to(JUURI)}:{rivi}")
        self.assertEqual(osumat, [])

    def test_ei_openrouter_yhdistelmia_sallittujen_ulkopuolella(self):
        osumat = []
        for p in _skannattavat():
            rel = str(p.relative_to(JUURI))
            if rel in SALLITUT_YHDISTELMAT:
                continue
            for rivi in yhdistelma_rikkomukset(_jasenna(p.read_text(encoding="utf-8"))):
                osumat.append(f"{rel}:{rivi}")
        self.assertEqual(osumat, [])

    # Skannerin omat testit muistissa olevalla lahteella (ei tilapaistiedostoja).
    def test_skanneri_huomaa_pilkotun_osoitteen(self):
        for lahde in (
            'U = "https://openrouter" + ".ai/x"\n',
            'U = "open" + "router" + ".ai"\n',
            'U = "open" + h + "router"\n',
            'U = f"https://open{x}router.ai/{y}"\n',
            'U = "https://%s.ai" % ("openrouter",) + "/x"\n',
        ):
            with self.subTest(lahde=lahde):
                self.assertTrue(yhdistelma_rikkomukset(_jasenna(lahde)))

    def test_skanneri_huomaa_provider_rungon_ulkopuolelta(self):
        for lahde in (
            'R = {"provider": {"zdr": False}}\n',
            'R = {"Provider": {}}\n',
            "R = dict(model='m', provider={})\n",
            'r = {}\nr["provider"] = {}\n',
            'def muu():\n    return {"provider": {}}\n',
        ):
            with self.subTest(lahde=lahde):
                self.assertTrue(provider_rikkomukset(_jasenna(lahde)))

    def test_skanneri_hyvaksyy_rakenna_runko_ja_viattoman_koodin(self):
        self.assertEqual(
            provider_rikkomukset(_jasenna('def rakenna_runko():\n    return {"provider": {}}\n')), []
        )
        self.assertEqual(yhdistelma_rikkomukset(_jasenna('U = "a" + "b"\nV = f"x{y}"\n')), [])
        self.assertEqual(provider_rikkomukset(_jasenna('R = {"model": "m"}\n')), [])


if __name__ == "__main__":
    unittest.main()
