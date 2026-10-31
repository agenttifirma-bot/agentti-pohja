import datetime
import gzip
import os
import sqlite3
import tempfile
import unittest

from uhkatieto import haku, keraa, tietokanta

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
NYT = datetime.datetime(2026, 10, 31, 6, 0, tzinfo=datetime.timezone.utc)


def lue(nimi):
    with open(os.path.join(FIX, nimi), "rb") as f:
        return f.read()


class FiktiivinenHaku:
    """Korvaa verkon: palauttaa fixturet ja kirjaa haetut osoitteet. Testit eivat kayta verkkoa."""

    def __init__(self, virheet=()):
        self.osoitteet, self.virheet = [], virheet

    def __call__(self, url):
        self.osoitteet.append(url)
        if any(v in url for v in self.virheet):
            raise haku.HakuVirhe("HTTPError 503")
        if url.endswith("ATLAS-latest.yaml"):
            return b"ATLAS-2026.10.yaml"
        if url.endswith("ATLAS-2026.10.yaml"):
            return lue("atlas.yaml")
        if "cisa.gov" in url:
            return lue("kev.json")
        if "nvd.nist.gov" in url:
            return lue("nvd.json")
        raise AssertionError("odottamaton osoite")


class KeraaTesti(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tila = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.rivit = []

    def aja(self, hae, **kw):
        return keraa.aja(self.tila, hae=hae, nyt=NYT, uni=lambda s: None, tulosta=self.rivit.append, **kw)

    def laske(self, sql="SELECT COUNT(*) FROM uhkat"):
        y = sqlite3.connect(os.path.join(self.tila, "uhkatieto.sqlite"))
        try:
            return y.execute(sql).fetchone()[0]
        finally:
            y.close()

    def test_kokoajo_ja_duplikaatinesto(self):
        ok, virheet = self.aja(FiktiivinenHaku())
        self.assertEqual(virheet, {})
        self.assertEqual(ok["kev"], 2)
        self.assertEqual(ok["atlas"], 5)
        self.assertEqual(ok["nvd"], 2)  # 4 hakusanaa palauttaa samat 2 CVE:ta -> ei duplikaatteja
        self.assertEqual(self.laske(), 9)
        ok2, _ = self.aja(FiktiivinenHaku())
        self.assertEqual(ok2, {"kev": 0, "atlas": 0, "nvd": 0})
        self.assertEqual(self.laske(), 9)

    def test_nvd_tagit_yhdistyvat(self):
        self.aja(FiktiivinenHaku(), lahteet=("nvd",))
        y = sqlite3.connect(os.path.join(self.tila, "uhkatieto.sqlite"))
        tagit = y.execute("SELECT tagit FROM uhkat WHERE id='CVE-2026-5001'").fetchone()[0].split(",")
        y.close()
        for sana in ("kw-llm", "kw-ai", "kw-agent", "kw-mcp", "sev-high"):
            self.assertIn(sana, tagit)

    def test_raakatiedosto_gzip_ja_ohitus_kun_sama(self):
        self.aja(FiktiivinenHaku(), lahteet=("kev",))
        polku = os.path.join(self.tila, "raaka", "2026-10-31", "kev.json.gz")
        with gzip.open(polku, "rb") as f:
            self.assertEqual(f.read(), lue("kev.json"))
        self.assertEqual(self.laske("SELECT COUNT(*) FROM raaka"), 1)
        self.aja(FiktiivinenHaku(), lahteet=("kev",))
        self.assertEqual(self.laske("SELECT COUNT(*) FROM raaka"), 1)  # sama sisalto -> ei uutta raakaa

    def test_yksi_lahde_kaatuu_muut_jatkavat(self):
        ok, virheet = self.aja(FiktiivinenHaku(virheet=("cisa.gov",)))
        self.assertEqual(virheet, {"kev": "HTTPError 503"})
        self.assertIn("atlas", ok)
        self.assertIn("nvd", ok)
        self.assertEqual(self.laske("SELECT COUNT(*) FROM ajot WHERE tila='virhe'"), 1)

    def test_atlas_osoitin_validoidaan(self):
        def paha(url):
            return b"../../etc/passwd"
        ok, virheet = self.aja(paha, lahteet=("atlas",))
        self.assertEqual(virheet, {"atlas": "ValueError"})  # vain tyyppi, ei sisaltoa

    def test_nvd_kysely_ja_ikkuna(self):
        h = FiktiivinenHaku()
        self.aja(h, lahteet=("nvd",), nvd_paivia=500)
        self.assertEqual(len(h.osoitteet), 4)
        self.assertIn("keywordSearch=MCP", h.osoitteet[3])
        self.assertIn("pubStartDate=2026-07-03T06%3A00%3A00.000", h.osoitteet[0])  # rajattu 120 paivaan
        self.assertTrue(all(u.startswith("https://") for u in h.osoitteet))

    def test_haku_hylkaa_ei_https(self):
        with self.assertRaises(haku.HakuVirhe):
            haku.hae("http://example.com/x")


class TietokantaTesti(unittest.TestCase):
    def test_tallenna_palauttaa_uudet(self):
        y = tietokanta.avaa(":memory:")
        r = {"lahde": "kev", "id": "A", "pvm": "2026-01-01", "otsikko": "t", "tagit": ["a"], "url": ""}
        self.assertEqual(tietokanta.tallenna(y, [r, dict(r)], "x"), 1)
        self.assertEqual(tietokanta.tallenna(y, [r], "x"), 0)
        r2 = dict(r, lahde="nvd")
        self.assertEqual(tietokanta.tallenna(y, [r2], "x"), 1)  # sama id eri lahteesta on eri rivi


if __name__ == "__main__":
    unittest.main()
