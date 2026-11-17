import http.client
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from aivo import chat

SAL = "oikea-salasana-123"


def ip(*osat):
    """Testiosoite osista: repon osoitetarkistus ei saa nahda kirjaimellisia osoitteita."""
    return ".".join(str(o) for o in osat)


TS = ".ts" + ".net"      # nimen paate koottu osista samasta syysta


class SalasanaTesti(unittest.TestCase):
    def test_tiiviste_toimii_ja_ei_sisalla_salasanaa(self):
        t = chat.tiivista_salasana(SAL)
        self.assertNotIn(SAL, t)
        self.assertTrue(chat.tarkista_salasana(SAL, t))
        self.assertFalse(chat.tarkista_salasana("vaara", t))
        self.assertFalse(chat.tarkista_salasana(SAL, "roskaa"))

    def test_aseta_salasana_kirjoittaa_600_ja_hylkaa_lyhyen(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sal"
            vastaukset = iter([SAL, SAL])
            chat.aseta_salasana(p, kysy=lambda _: next(vastaukset), tulosta=lambda *_: None)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertNotIn(SAL, p.read_text())
            with self.assertRaises(chat.ChatVirhe):
                chat.aseta_salasana(Path(d) / "x", kysy=lambda _: "lyhyt", tulosta=lambda *_: None)
            vastaukset = iter([SAL, SAL + "x"])
            with self.assertRaises(chat.ChatVirhe):
                chat.aseta_salasana(Path(d) / "y", kysy=lambda _: next(vastaukset), tulosta=lambda *_: None)

    def test_laaja_tiedosto_hylataan(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sal"
            p.write_text("x")
            os.chmod(p, 0o644)
            with self.assertRaises(chat.ChatVirhe):
                chat.lue_tiiviste(p)


class VerkkoTesti(unittest.TestCase):
    def test_vain_loopback_ja_tailscale(self):
        for ok in (ip(127, 0, 0, 1), "::1", ip(100, 100, 100, 100), ip(100, 64, 0, 1)):
            self.assertTrue(chat.sallittu_osoite(ok), ok)
        for ei in (ip(0, 0, 0, 0), ip(192, 168, 1, 5), ip(8, 8, 8, 8), "::", ip(100, 128, 0, 1), "esimerkki.fi"):
            self.assertFalse(chat.sallittu_osoite(ei), ei)
        with self.assertRaises(chat.ChatVirhe):
            chat.kaynnista(ip(0, 0, 0, 0), 0, None)

    def test_host_tarkistus(self):
        self.assertTrue(chat.sallittu_host("aivo.tail1234" + TS, [TS]))
        self.assertTrue(chat.sallittu_host("aivo.tail1234" + TS + ":443", [TS]))
        self.assertTrue(chat.sallittu_host("127.0.0.1:8780", []))
        self.assertFalse(chat.sallittu_host("paha.example.com", [TS]))
        self.assertFalse(chat.sallittu_host("ts.net" + ".paha.com", [TS]))
        self.assertFalse(chat.sallittu_host(None, [TS]))


class IstuntoTesti(unittest.TestCase):
    def test_lukitus_viidennen_virheen_jalkeen_ja_vanheneminen(self):
        aika = [0.0]
        i = chat.Istunnot(kello=lambda: aika[0])
        for _ in range(chat.VIRHE_RAJA):
            self.assertFalse(i.lukittu())
            i.virhe()
        self.assertTrue(i.lukittu())
        aika[0] += chat.LUKITUS_S + 1
        self.assertFalse(i.lukittu())
        t = i.luo()
        self.assertTrue(i.kelvollinen(t))
        self.assertFalse(i.kelvollinen("keksitty"))
        self.assertFalse(i.kelvollinen(None))
        aika[0] += chat.ISTUNTO_KESTO_S + 1
        self.assertFalse(i.kelvollinen(t))


class MuistiTesti(unittest.TestCase):
    def test_muisti_jarjestys_rajaus_ja_lahteet(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ulko:
            k = Path(d)
            (k / "aivo-paatoskirjasto.md").write_text("paatos A")
            (k / "kompassi.md").write_text("kompassi B")
            (k / "muu.md").write_text("muu C")
            (k / "kuva.png").write_bytes(b"x")
            (k / ".git").mkdir()
            (k / ".git" / "config.md").write_text("EI")
            (Path(ulko) / "salainen.md").write_text("ULKOPUOLINEN")
            os.symlink(Path(ulko) / "salainen.md", k / "linkki.md")
            teksti, tied = chat.lue_muisti(k)
            self.assertEqual(tied, ["aivo-paatoskirjasto.md", "kompassi.md", "muu.md"])
            self.assertNotIn("ULKOPUOLINEN", teksti)
            self.assertNotIn("EI", teksti.replace("MUISTI", ""))
            self.assertLess(teksti.index("paatos A"), teksti.index("kompassi B"))

    def test_muistin_raja_ei_voi_paattaa_osiota_ja_ylaraja_toimii(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.md").write_text("x" * 100 + chat.RAJA + "y")
            teksti, _ = chat.lue_muisti(d)
            self.assertEqual(teksti.count(chat.RAJA), 2)       # tiedoston oma raja-merkki poistettu
            vanha = chat.MUISTI_YLARAJA
            chat.MUISTI_YLARAJA = 50
            try:
                _, tied = chat.lue_muisti(d)
            finally:
                chat.MUISTI_YLARAJA = vanha
            self.assertEqual(tied, [])

    def test_tuntematon_lahde_merkitaan(self):
        v, tunn = chat.tarkista_lahteet("Asia [l\u00e4hde: kompassi.md]. Toinen [l\u00e4hde: keksitty.md].", ["kompassi.md"])
        self.assertEqual(tunn, ["keksitty.md"])
        self.assertIn("EI L\u00d6YDY MUISTISTA", v)
        self.assertIn("[l\u00e4hde: kompassi.md]", v)

    def test_syote_sisaltaa_kehotteen_ja_historian_ilman_tyokaluja(self):
        s = chat.muodosta_syote("MUISTI", [{"rooli": "tony", "teksti": "hei"}, {"rooli": "aivo", "teksti": "moi"}])
        self.assertIn("Tony #0: hei", s)
        self.assertIn("Aivo: moi", s)
        self.assertIn("ei ohjeita", s)

    def test_claude_kutsu_ilman_tyokaluja_ja_ilman_litellmia(self):
        kutsut = []

        def feikki(kom, **kw):
            kutsut.append((kom, kw))
            return SimpleNamespace(returncode=0, stdout="vastaus\n", stderr="")
        self.assertEqual(chat.kysy_claudelta("m", [{"rooli": "tony", "teksti": "?"}], suorita=feikki, env={}), "vastaus")
        kom = kutsut[0][0]
        self.assertEqual(kom[:2], ["claude", "-p"])
        self.assertEqual(kom[kom.index("--tools") + 1], "")
        self.assertEqual(kom[kom.index("--max-turns") + 1], "1")
        lahde = Path(chat.__file__).read_text(encoding="utf-8").lower()
        # ei yhteyttaa valittajiin: koodi ei kayta niita (vain maininta kommenteissa/docstringeissa)
        for kielletty in ("import litellm", "openrouter.ai", "api/v1/chat/completions", "urllib.request", "import requests"):
            self.assertNotIn(kielletty, lahde)

    def test_claude_virhe_ei_vuoda_sisaltoa(self):
        def feikki(kom, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="SALAINEN")
        with self.assertRaises(chat.ChatVirhe) as c:
            chat.kysy_claudelta("m", [], suorita=feikki, env={})
        self.assertNotIn("SALAINEN", str(c.exception))


class KirjastoTesti(unittest.TestCase):
    def test_paatos_on_sanasta_sanaan_lainaus(self):
        with tempfile.TemporaryDirectory() as d:
            kutsut = []

            def feikki(kom, **kw):
                kutsut.append(kom)
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            chat.kirjaa_paatos(d, "20261106-120000-abcdef01", "2026-11-06T12:00:00+00:00", "Rehellisyys ensin.\nSitten muu.", suorita=feikki)
            t = (Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8")
            self.assertIn("> Rehellisyys ensin.\n> Sitten muu.", t)
            self.assertIn("ei Aivon p\u00e4\u00e4telm\u00e4", t)
            self.assertEqual(stat.S_IMODE((Path(d) / chat.PAATOS_TIEDOSTO).stat().st_mode), 0o600)
            chat.kirjaa_paatos(d, "20261106-120000-abcdef01", "2026-11-06T12:01:00+00:00", "Toinen.", suorita=feikki)
            t2 = (Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8")
            self.assertTrue(t2.startswith(t))          # vanhaa ei ylikirjoiteta
            self.assertIn("> Toinen.", t2)

    def test_sama_paatos_kirjataan_vain_kerran_uudelleenyrityksessa(self):
        def feikki(kom, **kw):
            if "get-url" in kom:
                return SimpleNamespace(returncode=0, stdout="https://git.example/a.git\n", stderr="")
            if "push" in kom:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            if "status" in kom:
                return SimpleNamespace(returncode=0, stdout="M f\n", stderr="")
            if "symbolic-ref" in kom:
                return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, {"AIVO_SALLITUT_ETAISANNAT": "git.example"}):
            for _ in range(3):
                self.assertEqual(chat.kirjaa_paatos(d, "k1", "2026-11-16T10:00:00+00:00", "Paatos A", suorita=feikki),
                                 "push-epaonnistui")
            self.assertEqual((Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8").count("> Paatos A"), 1)
            chat.kirjaa_paatos(d, "k1", "2026-11-16T10:01:00+00:00", "Paatos A", suorita=feikki)    # eri aika = uusi viesti
            self.assertEqual((Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8").count("> Paatos A"), 2)

    def test_yksityinen_tila_ei_kirjaa_samaa_viestia_kahdesti(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(2):
                self.assertEqual(chat.kirjaa_paatos_yksityinen(d, "k1", "2026-11-16T10:00:00+00:00", "Yks"), "ei-julkaistu")
            self.assertEqual((Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8").count("> Yks"), 1)

    def test_uusi_painallus_pushaa_uudelleen_vaikka_tiedosto_ei_muutu(self):
        """Oikea git: ensimmainen push epaonnistuu (etarepo poissa), toinen painallus pushaa saman commitin."""
        import shutil
        import subprocess
        if shutil.which("git") is None:
            self.skipTest("git puuttuu")

        def git(*a, cwd=None):
            return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True,
                                  env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                                       "GIT_TERMINAL_PROMPT": "0"})

        def suorita(kom, **kw):
            if "get-url" in kom:
                return SimpleNamespace(returncode=0, stdout="https://git.example/a.git\n", stderr="")
            return subprocess.run(kom, **{**kw, "env": {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                                                        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"}})
        with tempfile.TemporaryDirectory() as t:
            eta, oma, pois = Path(t) / "eta.git", Path(t) / "oma", Path(t) / "poissa.git"
            git("init", "-q", "--bare", "-b", "main", str(eta))
            git("clone", "-q", str(eta), str(oma))
            for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
                git("-C", str(oma), "config", k, v)
            (oma / "a").write_text("a", encoding="utf-8")
            git("-C", str(oma), "add", "a")
            git("-C", str(oma), "commit", "-q", "-m", "alku")
            git("-C", str(oma), "push", "-q", "origin", "HEAD:refs/heads/main")
            eta.rename(pois)                                              # push epaonnistuu
            with unittest.mock.patch.dict(os.environ, {"AIVO_SALLITUT_ETAISANNAT": "git.example"}):
                args = (str(oma), "k1", "2026-11-16T10:00:00+00:00", "Paatos B")
                self.assertEqual(chat.kirjaa_paatos(*args, suorita=suorita), "push-epaonnistui")
                self.assertEqual(chat.kirjaa_paatos(*args, suorita=suorita), "push-epaonnistui")
                pois.rename(eta)                                          # etarepo palaa
                self.assertEqual(chat.kirjaa_paatos(*args, suorita=suorita), "pushattu")
                self.assertEqual(chat.kirjaa_paatos(*args, suorita=suorita), "ei-muutosta")
            self.assertEqual((oma / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8").count("> Paatos B"), 1)
            self.assertEqual(git("-C", str(eta), "rev-list", "--count", "main").stdout.strip(), "2")   # alku + yksi paatos

    def test_github_etarepo_estaa_pushin(self):
        def feikki(kom, **kw):
            if "get-url" in kom:
                return SimpleNamespace(returncode=0, stdout="https://github.com/x/y.git\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(chat.ChatVirhe):
                chat.julkaise_kirjastoon(d, Path(d) / "a.md", feikki)

    def test_julkaisun_epaonnistuessa_paatostiedosto_palautuu(self):
        def feikki(kom, **kw):
            if "get-url" in kom:
                return SimpleNamespace(returncode=0, stdout="https://github.com/x/y.git\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / chat.PAATOS_TIEDOSTO
            with self.assertRaises(chat.ChatVirhe):
                chat.kirjaa_paatos(d, "20261106-120000-abcdef01", "2026-11-06T12:00:00+00:00", "a", suorita=feikki)
            self.assertFalse(p.exists())
            chat.kirjaa_paatos(d, "20261106-120000-abcdef01", "2026-11-06T12:00:00+00:00", "vanha", julkaise=False)
            vanha = p.read_text(encoding="utf-8")
            with self.assertRaises(chat.ChatVirhe):
                chat.kirjaa_paatos(d, "20261106-120000-abcdef01", "2026-11-06T12:01:00+00:00", "uusi", suorita=feikki)
            self.assertEqual(p.read_text(encoding="utf-8"), vanha)

    def test_samanaikaiset_kirjaukset_eivat_havita_toisiaan(self):
        with tempfile.TemporaryDirectory() as d:
            saikeet = [threading.Thread(target=chat.kirjaa_paatos, args=(d, "20261106-120000-abcdef01",
                                        "2026-11-06T12:%02d:00+00:00" % i, "paatos-%02d" % i), kwargs={"julkaise": False})
                       for i in range(30)]
            for t in saikeet:
                t.start()
            for t in saikeet:
                t.join()
            teksti = (Path(d) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8")
            for i in range(30):
                self.assertIn("> paatos-%02d" % i, teksti)

    def test_host_vaatii_taydellisen_nimen(self):
        for paha in (["--host", ".esimerkki.fi"], ["--host", ""]):
            with tempfile.TemporaryDirectory() as d:
                virhe = io.StringIO()
                with unittest.mock.patch.object(sys, "stderr", virhe):
                    self.assertEqual(chat.main(["palvele", "--salasana-tiedosto", d + "/ei-ole", "--data", d, "--kirjasto", d] + paha), 1)
                self.assertIn("--host", virhe.getvalue())

    def test_keskustelun_tunniste_ei_paase_polkuun(self):
        with tempfile.TemporaryDirectory() as d:
            k = chat.Keskustelut(d)
            for paha in ("../../etc/passwd", "", None, "x"):
                with self.assertRaises(chat.ChatVirhe):
                    k.lue(paha)


class PalveluTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        k = Path(cls.tmp.name) / "kirjasto"
        k.mkdir()
        (k / "faktat.md").write_text("Tony opiskelee ohjelmistokehitt\u00e4j\u00e4ksi.")
        cls.kysytty = []
        cls.paatokset = []
        cls.julkaisun_tulos = "pushattu"

        def kysy(muisti, historia):
            cls.kysytty.append((muisti, historia))
            return "Opiskelet ohjelmistokehitt\u00e4j\u00e4ksi [l\u00e4hde: faktat.md] ja [l\u00e4hde: haamu.md]."

        def julkaise(kirjasto, kid, aika, teksti):
            cls.paatokset.append(teksti)
            return cls.julkaisun_tulos
        cls.tila = chat.Tila(chat.tiivista_salasana(SAL), str(k), str(Path(cls.tmp.name) / "data"), [TS],
                             kysy=kysy, julkaise=julkaise)
        cls.srv = chat.kaynnista(ip(127, 0, 0, 1), 0, cls.tila)
        cls.portti = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def pyynto(self, menetelma, polku, runko=None, otsakkeet=None, host=None):
        c = http.client.HTTPConnection(ip(127, 0, 0, 1), self.portti, timeout=10)
        h = dict(otsakkeet or {})
        if host:
            h["Host"] = host
        c.request(menetelma, polku, body=runko, headers=h)
        r = c.getresponse()
        data = r.read()
        return r.status, dict(r.getheaders()), data

    def kirjaudu(self):
        s, h, _ = self.pyynto("POST", "/kirjaudu", "salasana=" + SAL, {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(s, 303)
        ev = h["Set-Cookie"]
        for osa in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(osa, ev)
        return ev.split(";")[0]

    def api(self, ev, polku, olio):
        s, _, d = self.pyynto("POST", polku, json.dumps(olio), {"Cookie": ev, "X-Aivo": "1", "Content-Type": "application/json"})
        return s, json.loads(d)

    def test_ilman_kirjautumista_ei_paase(self):
        s, h, _ = self.pyynto("GET", "/")
        self.assertEqual((s, h["Location"]), (302, "/kirjaudu"))
        s, _, _ = self.pyynto("POST", "/api/uusi", "{}", {"X-Aivo": "1"})
        self.assertEqual(s, 401)

    def test_vaara_host_hylataan(self):
        s, _, _ = self.pyynto("GET", "/kirjaudu", host="paha.example.com")
        self.assertEqual(s, 421)

    def test_csrf_vaatii_otsakkeen_ja_saman_alkuperan(self):
        ev = self.kirjaudu()
        s, _, _ = self.pyynto("POST", "/api/uusi", "{}", {"Cookie": ev})
        self.assertEqual(s, 403)
        s, _, _ = self.pyynto("POST", "/api/uusi", "{}", {"Cookie": ev, "X-Aivo": "1", "Origin": "https://paha.example.com"})
        self.assertEqual(s, 403)

    def test_vaara_salasana_ja_lukitus(self):
        tila = chat.Tila(chat.tiivista_salasana(SAL), self.tmp.name, self.tmp.name, [TS])
        srv = chat.kaynnista(ip(127, 0, 0, 1), 0, tila)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def yrita(sal):
                c = http.client.HTTPConnection(ip(127, 0, 0, 1), srv.server_address[1], timeout=10)
                c.request("POST", "/kirjaudu", body="salasana=" + sal, headers={"Content-Type": "application/x-www-form-urlencoded"})
                r = c.getresponse()
                r.read()
                return r.status
            for _ in range(chat.VIRHE_RAJA):
                self.assertEqual(yrita("vaara"), 401)
            self.assertEqual(yrita(SAL), 429)        # oikeakaan ei kelpaa lukituksen aikana
        finally:
            srv.shutdown()
            srv.server_close()

    def test_keskustelu_muisti_lahteet_ja_paatos(self):
        ev = self.kirjaudu()
        s, d = self.api(ev, "/api/uusi", {"tila": "tyokalu"})
        self.assertEqual(s, 200)
        kid = d["id"]
        s, d = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "mit\u00e4 tied\u00e4t minusta?"})
        self.assertEqual(s, 200)
        self.assertIn("[l\u00e4hde: faktat.md]", d["vastaus"])
        self.assertIn("EI L\u00d6YDY MUISTISTA", d["vastaus"])
        self.assertEqual(d["tuntemattomia_lahteita"], 1)
        self.assertIn("Tony opiskelee", self.kysytty[-1][0])        # muisti luettiin ennen vastausta
        # tallennus isannalle, 600
        p = Path(self.tmp.name) / "data" / (kid + ".jsonl")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(len(p.read_text(encoding="utf-8").splitlines()), 2)
        # paatos: vain Tonyn viesti (indeksi 0) kelpaa, Aivon (1) ei
        s, _ = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": 1})
        self.assertEqual(s, 400)
        s, r = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": 0})
        self.assertEqual((s, r["tila"], r["teksti"]), (200, "pushattu", "Kirjattu"))
        self.assertEqual(self.paatokset, ["mit\u00e4 tied\u00e4t minusta?"])

    def _kirjaa_tuloksella(self, tulos):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": "tyokalu"})
        self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": "p\u00e4\u00e4t\u00f6s"})
        type(self).julkaisun_tulos = tulos
        try:
            return self.api(ev, "/api/paatos", {"keskustelu": d["id"], "indeksi": 0})
        finally:
            type(self).julkaisun_tulos = "pushattu"

    def test_paatos_epaonnistuneesta_pushista_ei_ole_kirjattu(self):
        for tulos in ("push-epaonnistui", "ei-etaa", "ei-gitissa"):
            with self.subTest(tulos=tulos):
                s, r = self._kirjaa_tuloksella(tulos)
                self.assertEqual((s, r["tila"]), (502, tulos))
                self.assertNotIn("Kirjattu", r["teksti"].replace("Ei kirjattu", ""))
                self.assertTrue(r["teksti"].startswith("Ei kirjattu"))

    def test_paatos_ei_muutosta_nayttaa_oman_tekstinsa(self):
        s, r = self._kirjaa_tuloksella("ei-muutosta")
        self.assertEqual((s, r["tila"]), (200, "ei-muutosta"))
        self.assertNotEqual(r["teksti"], "Kirjattu")
        self.assertIn("Ei muutosta", r["teksti"])

    def test_paatos_tuntematon_tulos_ja_vaara_tila_ovat_virhe(self):
        s, r = self._kirjaa_tuloksella("jotain-outoa")
        self.assertEqual((s, r["tila"]), (502, "tuntematon"))
        # "ei-julkaistu" kuuluu vain yksityiseen tilaan: tyokalutilassa se ei saa nayttaa onnistumista
        s, r = self._kirjaa_tuloksella("ei-julkaistu")
        self.assertEqual((s, r["tila"]), (502, "tuntematon"))

    def test_paatoksen_vastaus_yksityinen_vain_ei_julkaistu(self):
        self.assertEqual(chat.paatoksen_vastaus("ei-julkaistu", True)[0], 200)
        for t in ("pushattu", "push-epaonnistui", "ei-etaa", "ei-gitissa", "ei-muutosta", None):
            self.assertEqual(chat.paatoksen_vastaus(t, True)[0], 502, t)

    def test_kayttoliittyma_nayttaa_palvelimen_tekstin_eika_pelkkaa_kirjattu_r_ok_perusteella(self):
        self.assertIn("b.textContent=j.teksti||", chat.HTML)
        self.assertNotIn("r.ok?'Kirjattu'", chat.HTML)

    def test_liian_pitka_viesti_hylataan(self):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": "tyokalu"})
        s, _ = self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": "x" * (chat.VIESTI_YLARAJA + 1)})
        self.assertEqual(s, 400)

    def test_sivu_on_mobiiliystavallinen(self):
        ev = self.kirjaudu()
        s, h, d = self.pyynto("GET", "/", None, {"Cookie": ev})
        self.assertEqual(s, 200)
        self.assertIn(b'name="viewport"', d)
        self.assertEqual(h["Cache-Control"], "no-store")


class PaatosehdotusTesti(unittest.TestCase):
    """A997: Aivo ehdottaa, Tony vahvistaa. Merkint\u00e4 [[PAATOS n]] ei kirjaa mit\u00e4\u00e4n."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = Path(cls.tmp.name)
        (r / "kirjasto").mkdir()
        (r / "yks" / "muisti").mkdir(parents=True)
        cls.vastaus = "Selv\u00e4."
        cls.julkaisut, cls.git_kutsut = [], []

        def kysy(muisti, historia):
            return cls.vastaus

        def kysy_yks(muisti, historia, ohjeet):
            return cls.vastaus

        def julkaise(kirjasto, kid, aika, teksti):
            cls.julkaisut.append(teksti)
            return "pushattu"
        cls.tila = chat.Tila(chat.tiivista_salasana(SAL), str(r / "kirjasto"), str(r / "data"), [TS], kysy=kysy,
                             julkaise=julkaise, yks_data=str(r / "yks" / "chat"), yks_muisti=str(r / "yks" / "muisti"),
                             ydinohjeet=str(r / "yks" / "ydin"), ehdotukset=str(r / "yks" / "ehd"), kysy_yks=kysy_yks)
        cls.srv = chat.kaynnista(ip(127, 0, 0, 1), 0, cls.tila)
        cls.portti = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def api(self, ev, polku, olio):
        c = http.client.HTTPConnection(ip(127, 0, 0, 1), self.portti, timeout=10)
        c.request("POST", polku, body=json.dumps(olio),
                  headers={"Cookie": ev, "X-Aivo": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def kirjaudu(self):
        c = http.client.HTTPConnection(ip(127, 0, 0, 1), self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SAL, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        return r.getheader("Set-Cookie").split(";")[0]

    def viesti(self, tila, teksti, vastaus):
        type(self).vastaus = vastaus
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": tila})
        s, v = self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": teksti})
        self.assertEqual(s, 200)
        return ev, d["id"], v

    def test_merkinta_poistuu_nakyvasta_vastauksesta_ja_tulee_kenttana(self):
        for tila in ("tyokalu", "yksityinen"):
            _, _, v = self.viesti(tila, "kyll\u00e4, tehd\u00e4\u00e4n", "Selv\u00e4, kirjataan.\n[[PAATOS 0]]")
            self.assertEqual(v["paatosehdotus"], 0, tila)
            self.assertNotIn("PAATOS", v["vastaus"], tila)
            self.assertEqual(v["vastaus"], "Selv\u00e4, kirjataan.", tila)

    def test_ilman_merkintaa_ei_ehdotusta(self):
        for tila in ("tyokalu", "yksityinen"):
            _, _, v = self.viesti(tila, "mit\u00e4 mietit?", "Mietin asiaa.")
            self.assertNotIn("paatosehdotus", v, tila)
            self.assertEqual(v["vastaus"], "Mietin asiaa.")

    def test_vaara_indeksi_hylataan_hiljaa_ja_merkinta_silti_poistuu(self):
        for vastaus in ("Ok.\n[[PAATOS 7]]", "Ok.\n[[PAATOS 1]]",          # ei ole / Aivon oma viesti (1 = tuleva vastaus)
                        "Ok.\n[[PAATOS -1]]", "Ok.\n[[PAATOS x]]", "[[PAATOS 0]] Ok.", "Ok.\n[[PAATOS 0]]\nlis\u00e4\u00e4"):
            _, _, v = self.viesti("tyokalu", "tehd\u00e4\u00e4n", vastaus)
            self.assertNotIn("paatosehdotus", v, vastaus)
            self.assertNotIn("[[PAATOS", v["vastaus"], vastaus)

    def test_aivon_oman_viestin_indeksi_hylataan(self):
        ev, kid, v = self.viesti("tyokalu", "ensimm\u00e4inen", "Vastaus yksi.")
        type(self).vastaus = "Vastaus kaksi.\n[[PAATOS 1]]"                # 1 on Aivon edellinen vastaus
        s, v2 = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "toinen"})
        self.assertEqual(s, 200)
        self.assertNotIn("paatosehdotus", v2)
        type(self).vastaus = "Vastaus kolme.\n[[PAATOS 2]]"                # 2 on Tonyn viesti
        s, v3 = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "kolmas"})
        self.assertEqual(v3["paatosehdotus"], 2)

    def test_ehdotus_ei_kirjaa_mitaan_ja_paatos_kirjaa_vain_tonyn_tekstin(self):
        self.julkaisut.clear()
        ev, kid, v = self.viesti("tyokalu", "valitsen vaihtoehdon B", "Hyv\u00e4. Mallin oma tiivistelm\u00e4.\n[[PAATOS 0]]")
        self.assertEqual(self.julkaisut, [])                                # ehdotus ei kirjaa
        s, r = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": v["paatosehdotus"]})
        self.assertEqual((s, r["tila"]), (200, "pushattu"))
        self.assertEqual(self.julkaisut, ["valitsen vaihtoehdon B"])        # vain Tonyn sanat
        s, _ = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": 1})
        self.assertEqual(s, 400)                                            # Aivon viesti ei kirjaudu

    def test_yksityisessa_tilassa_vahvistus_ei_aja_gitia(self):
        self.julkaisut.clear()
        ev, kid, v = self.viesti("yksityinen", "p\u00e4\u00e4t\u00e4n lopettaa", "Selv\u00e4.\n[[PAATOS 0]]")
        with unittest.mock.patch("aivo.yksityinen.julkaise_kirjastoon",
                                 side_effect=AssertionError("git yksityisess\u00e4 tilassa")):
            s, r = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": v["paatosehdotus"]})
        self.assertEqual((s, r["tila"]), (200, "ei-julkaistu"))
        self.assertEqual(self.julkaisut, [])
        t = (Path(self.tila.yks_muisti) / chat.PAATOS_TIEDOSTO).read_text(encoding="utf-8")
        self.assertIn("> p\u00e4\u00e4t\u00e4n lopettaa", t)

    def test_syote_numeroi_tonyn_viestit_ja_kehote_kertoo_merkinnan(self):
        s = chat.muodosta_syote("M", [{"rooli": "tony", "teksti": "a"}, {"rooli": "aivo", "teksti": "b"},
                                      {"rooli": "tony", "teksti": "c"}])
        self.assertIn("Tony #0: a", s)
        self.assertIn("Tony #2: c", s)
        self.assertIn("[[PAATOS n]]", chat.KEHOTE)

    def test_kortti_kutsuu_vanhaa_paatosreittia_vain_kylla_painalluksesta(self):
        self.assertIn("e.onclick=()=>d.remove()", chat.HTML)                # ei sulkee kortin, ei kutsu
        self.assertIn("k.onclick=async()=>{", chat.HTML)
        self.assertIn("Number.isInteger(j.paatosehdotus)", chat.HTML)
        self.assertIn("q.textContent=s", chat.HTML)                          # Tonyn teksti textContentilla, ei innerHTML
        self.assertIn("Kirjaa p\u00e4\u00e4t\u00f6kseksi (sanasi sellaisenaan)", chat.HTML)   # vanha nappi s\u00e4ilyy


if __name__ == "__main__":
    unittest.main()
