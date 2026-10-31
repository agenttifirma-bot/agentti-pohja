import json
import os
import subprocess
import tempfile
import time
import unittest
import urllib.error
from types import SimpleNamespace

from agentti import github_app as ga
from agentti import pr_kutsu as pk

GHS = "ghs_" + "A1b2C3d4E5" * 4


class Vastaus:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.d).encode()


def avain_ok(cmd, **kw):
    return SimpleNamespace(returncode=0, stdout=b"\x01\x02sig")


class AppTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.as_ = os.path.join(self.d.name, "app.json")
        with open(self.as_, "w") as f:
            json.dump({"app_id": 7, "avain": "/ei/ole.pem", "asennus_fork": 11, "asennus_pr": 22}, f)
        self.tila = os.path.join(self.d.name, "tila")

    def hae(self, rooli="fork", nyt=None, avaa=None, suorita=avain_ok):
        return ga.hae_tunnus(self.as_, rooli, "repo-x", self.tila, nyt=nyt, avaa=avaa, suorita=suorita)

    def vastaus(self, nyt, kesto=3600):
        return Vastaus({"token": GHS, "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(nyt + kesto))})

    def test_jwt_muoto(self):
        jwt = ga.luo_jwt(7, "/x", nyt=1000, suorita=avain_ok)
        h, p, s = jwt.split(".")
        self.assertEqual(ga._b64(b"\x01\x02sig"), s)
        pad = p + "=" * (-len(p) % 4)
        import base64
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad)), {"iat": 940, "exp": 1540, "iss": 7})

    def test_pyynto_rajaa_repon_ja_oikeuden(self):
        nyt = time.time()
        pyynnot = []

        def avaa(p, timeout):
            pyynnot.append(p)
            return self.vastaus(nyt)
        self.assertEqual(self.hae("pr", nyt, avaa), GHS)
        p = pyynnot[0]
        self.assertTrue(p.full_url.endswith("/app/installations/22/access_tokens"))
        self.assertEqual(json.loads(p.data), {"repositories": ["repo-x"], "permissions": {"pull_requests": "write"}})
        self.assertNotIn("workflows", json.dumps(ga.OIKEUDET))

    def test_valimuisti_ja_uusinta(self):
        nyt = time.time()
        n = []

        def avaa(p, timeout):
            n.append(1)
            return self.vastaus(nyt)
        self.hae("fork", nyt, avaa)
        self.hae("fork", nyt + 60, avaa)
        self.assertEqual(len(n), 1)                       # valimuistista
        self.hae("fork", nyt + 3600 - 300, avaa)          # alle marginaalin: uusi haku
        self.assertEqual(len(n), 2)
        tiedosto = os.path.join(self.tila, "app-11-repo-x-fork.json")
        self.assertEqual(os.stat(tiedosto).st_mode & 0o777, 0o600)

    def test_virheet_vain_tyyppi(self):
        def hylkaa(p, timeout):
            raise urllib.error.HTTPError(p.full_url, 401, "Bearer " + GHS, {}, None)
        with self.assertRaises(ga.AppVirhe) as c:
            self.hae(avaa=hylkaa)
        self.assertEqual(str(c.exception), "tunnuksen haku hylatty (HTTP 401)")
        with self.assertRaises(ga.AppVirhe):
            self.hae(suorita=lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=b""))
        with self.assertRaises(ga.AppVirhe):
            ga.hae_tunnus(self.as_, "pr", "../x", self.tila)

    def test_vaara_asetusmuoto(self):
        with open(self.as_, "w") as f:
            json.dump({"app_id": 7, "avain": "suhteellinen", "asennus_fork": 1, "asennus_pr": 2}, f)
        with self.assertRaises(ga.AppVirhe):
            self.hae()


class TunnusTiedostoTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.pat = os.path.join(self.d.name, "pat")
        self.env = {"YOJONO_BOT_TUNNUS": self.pat, "YOJONO_PR_TILA": os.path.join(self.d.name, "t", "pr.json")}

    def test_ilman_asetusta_pat(self):
        self.assertEqual(pk.tunnus_tiedosto(self.env, "r", "fork", self.d.name), self.pat)

    def test_app_ensisijainen_ja_tiedosto_600(self):
        self.env["YOJONO_APP_ASETUKSET"] = "/x"
        orig = ga.hae_tunnus
        ga.hae_tunnus = lambda a, rooli, repo, tila: GHS
        self.addCleanup(setattr, ga, "hae_tunnus", orig)
        polku = pk.tunnus_tiedosto(self.env, "r", "pr", self.d.name)
        self.assertNotEqual(polku, self.pat)
        self.assertEqual(os.stat(polku).st_mode & 0o777, 0o600)
        self.assertEqual(pk.lue_tunnus(polku), GHS)

    def test_app_vika_palaa_patiin(self):
        self.env["YOJONO_APP_ASETUKSET"] = "/ei/ole.json"
        self.assertEqual(pk.tunnus_tiedosto(self.env, "r", "fork", self.d.name), self.pat)


if __name__ == "__main__":
    unittest.main()
