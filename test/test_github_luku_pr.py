import json
import os
import stat
import tempfile
import unittest
import urllib.error

from agentti import github_luku as g

TUNNUS = "testi_" + "y" * 30   # keksitty, ei oikea


class Vast:
    def __init__(self, data, otsakkeet):
        self.data, self.headers = data, otsakkeet

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


def raja_otsakkeet(jaljella, etag=None):
    o = {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": str(jaljella), "X-RateLimit-Reset": "1800000000"}
    if etag:
        o["ETag"] = etag
    return o


PR = {"state": "open", "merged": False, "draft": False, "head": {"ref": "yo/x", "sha": "a" * 40}}
KATS = [{"state": "COMMENTED", "commit_id": "b" * 40}, {"state": "APPROVED", "commit_id": "a" * 40}]
AJOT = {"check_runs": [{"status": "completed", "conclusion": "success"},
                       {"status": "completed", "conclusion": "success"},
                       {"status": "in_progress", "conclusion": None}]}


class Tynka:
    """urlopen-tynka: palauttaa vastaukset polun mukaan, tukee If-None-Match -> 304."""

    def __init__(self, jaljella=50):
        self.pyynnot = []
        self.jaljella = jaljella

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.pyynnot.append(req)
        if url.endswith("/rate_limit"):
            return Vast(json.dumps({"resources": {"core": {"limit": 60, "remaining": self.jaljella,
                                                           "reset": 1800000000}}}).encode(), {})
        etag = '"e%d"' % (hash(url.split("?")[0]) % 1000)
        if req.get_header("If-none-match") == etag:
            raise urllib.error.HTTPError(url, 304, "", raja_otsakkeet(self.jaljella), None)
        self.jaljella -= 1
        if "/reviews" in url:
            d = KATS
        elif "/check-runs" in url:
            d = AJOT
        else:
            d = PR
        return Vast(json.dumps(d).encode(), raja_otsakkeet(self.jaljella, etag))

    def datahaut(self):
        return [r for r in self.pyynnot if not r.full_url.endswith("/rate_limit")]


class PrTilaTesti(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.hak = os.path.join(t.name, "valimuisti")
        self.polku = os.path.join(t.name, "luku.token")

    def aja(self, tynka, **kw):
        return g.pr_tila("o/r", 22, hak=self.hak, avaa=tynka, polku=self.polku, **kw)

    def test_tiivis_tulostus(self):
        rivit, tilat = self.aja(Tynka())
        teksti = "\n".join(rivit)
        self.assertIn("PR o/r#22: open", teksti)
        self.assertIn("head: yo/x @ aaaaaaa", teksti)
        self.assertIn("katselmointi: APPROVED (commit aaaaaaa)", teksti)
        self.assertIn("checkit: 3 yhteensa: 1 in_progress, 2 success", teksti)
        self.assertRegex(rivit[-1], r"^raja: jaljella 47 / 60, nollaus \d\d:\d\d UTC$")
        self.assertEqual(tilat, ["UUSI"] * 3)

    def test_toinen_haku_kayttaa_304_eika_kuluta_rajaa(self):
        t = Tynka()
        self.aja(t)
        jaljella = t.jaljella
        rivit, tilat = self.aja(t)
        self.assertEqual(tilat, ["VALIMUISTI"] * 3)
        self.assertEqual(t.jaljella, jaljella)
        self.assertIn("jaljella 47 /", rivit[-1])

    def test_vartija_estaa_pyynnon_ja_nayttaa_vanhan(self):
        t = Tynka()
        self.aja(t)
        t2 = Tynka(jaljella=3)
        rivit, tilat = self.aja(t2)
        self.assertEqual(tilat, ["VANHA"] * 3)
        self.assertEqual(t2.datahaut(), [])
        self.assertTrue(any(r.startswith("VANHA") for r in rivit))

    def test_vartija_ilman_valimuistia_nostaa_poikkeuksen(self):
        t = Tynka(jaljella=4)
        with self.assertRaises(g.RajaTaynna):
            self.aja(t)
        self.assertEqual(t.datahaut(), [])

    def test_main_palauttaa_3_kun_raja_taynna(self):
        vanha = g.raja_alussa
        g.raja_alussa = lambda **kw: g.Raja(60, 0, 1800000000)
        try:
            os.environ["HOME"], h = self.hak, os.environ.get("HOME")
            try:
                self.assertEqual(g.main(["pr", "o/r", "22"]), g.EI_RAJAA)
            finally:
                os.environ["HOME"] = h
        finally:
            g.raja_alussa = vanha

    def test_authorization_vain_api_githubiin(self):
        with open(self.polku, "w") as f:
            f.write(TUNNUS)
        t = Tynka()
        self.aja(t)
        for r in t.pyynnot:
            self.assertEqual(r.get_header("Authorization"), "Bearer " + TUNNUS)
        self.assertNotIn("Authorization", g.pyynto("https://example.com/x", "ua", polku=self.polku).headers)

    def test_tunnus_ei_tulosteeseen_eika_valimuistiin(self):
        with open(self.polku, "w") as f:
            f.write(TUNNUS)
        rivit, _ = self.aja(Tynka())
        self.assertNotIn(TUNNUS, "\n".join(rivit))
        for nimi in os.listdir(self.hak):
            p = os.path.join(self.hak, nimi)
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            with open(p) as f:
                sisalto = f.read()
            self.assertNotIn(TUNNUS, sisalto)
            self.assertNotIn("Authorization", sisalto)
            self.assertEqual(sorted(json.loads(sisalto)), ["etag", "runko"])
        self.assertEqual(stat.S_IMODE(os.stat(self.hak).st_mode), 0o700)

    def test_virheellinen_repo_hylataan(self):
        for repo in ("../x", "a/b/c", "a b/c", "x"):
            with self.assertRaises(ValueError):
                g.pr_tila(repo, 1, hak=self.hak, avaa=Tynka())
        with self.assertRaises(ValueError):
            g.pr_tila("o/r", "1/../2", hak=self.hak, avaa=Tynka())

    def test_merged_ja_ei_katselmointeja(self):
        class T(Tynka):
            def __call__(self, req, timeout=None):
                v = super().__call__(req, timeout)
                if req.full_url.endswith("/pulls/22"):
                    return Vast(json.dumps(dict(PR, merged=True, state="closed")).encode(), v.headers)
                if "/reviews" in req.full_url:
                    return Vast(b"[]", v.headers)
                return v
        rivit, _ = self.aja(T())
        self.assertIn("merged", rivit[0])
        self.assertIn("ei katselmointeja", "\n".join(rivit))


if __name__ == "__main__":
    unittest.main()
