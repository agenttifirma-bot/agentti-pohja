"""Muistialueen erottelutestit (suunnitelma aivo-keskustelumuisti, PR 1; Tonyn paatokset A728-A730, A983).

Kolme kerrosta:
1. AlueTesti: alueabstraktio ja hakemistotarkistus (omistaja, oikeudet, linkit, paallekkaisyys).
2. KanariaTesti: yksityisen alueen tunnettu merkkijono ei paady tyokalutilan kehotteeseen, lokiin, alaprosessikutsuun,
   ei-loopback-yhteyteen eika tyokalualueen tiedostoihin.
3. RakenneTesti: AST-tarkistus, ettei tyokalutilan koodi tuo yksityisen alueen moduuleja tai polkuja eika yksityisen
   alueen moduuli tuo alaprosesseja, verkkoa tai Clauden/OpenRouterin/LiteLLM:n nimia.
"""

import ast
import contextlib
import http.client
import io
import json
import logging
import os
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aivo import alue, chat, tyokalualue, yksityinen_alue

SAL = "oikea-salasana-123"
AIVO = Path(__file__).resolve().parent


class AlueTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_polku_vain_sallituista_alikansioista(self):
        a = alue.Alue("x", self.r / "x", ("chat", "indeksi"))
        self.assertEqual(a.polku("chat"), self.r / "x" / "chat")
        for paha in ("..", "../chat", "muu", "", "chat/../indeksi", "/etc"):
            with self.assertRaises(alue.AlueVirhe):
                a.polku(paha)

    def test_alueen_maaritys_hylkaa_virheelliset_nimet_ja_suhteellisen_juuren(self):
        for nimet in (("../x",), ("a", "a"), ("A",), ("a/b",), ("",)):
            with self.assertRaises(alue.AlueVirhe):
                alue.Alue("x", self.r, nimet)
        with self.assertRaises(alue.AlueVirhe):
            alue.Alue("x", "suhteellinen/polku", ("chat",))

    def test_valmista_luo_kaikki_alikansiot_0700(self):
        a = yksityinen_alue.yksityinen_alue(self.r / "yks")
        polut = a.valmista()
        self.assertEqual(set(polut), set(yksityinen_alue.ALIKANSIOT))
        for p in [a.juuri] + list(polut.values()):
            self.assertTrue(p.is_dir())
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)

    def test_liian_laaja_kansio_korjataan_0700(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        os.chmod(a.polku("chat"), 0o755)
        a.valmista()
        self.assertEqual(stat.S_IMODE(a.polku("chat").stat().st_mode), 0o700)

    def test_symlink_alikansiona_estaa_kaynnistyksen(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        (self.r / "x").mkdir(mode=0o700)
        (self.r / "muualle").mkdir()
        os.symlink(self.r / "muualle", self.r / "x" / "chat")
        with self.assertRaises(alue.AlueVirhe):
            a.valmista()

    def test_symlink_juurena_estaa_kaynnistyksen(self):
        (self.r / "oikea").mkdir()
        os.symlink(self.r / "oikea", self.r / "linkki")
        with self.assertRaises(alue.AlueVirhe):
            alue.Alue("x", self.r / "linkki", ("chat",)).valmista()

    def test_vaara_omistaja_estaa_kaynnistyksen(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(alue.AlueVirhe):
                a.valmista(luo=False)

    def test_vaara_omistaja_tiedostolla_estaa_kaynnistyksen(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        (a.polku("chat") / "k.jsonl").write_text("x")
        with mock.patch("aivo.alue.os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(alue.AlueVirhe):
                alue.tarkista_tiedostot(a.polku("chat"))

    def test_puuttuva_kansio_ilman_luontia_epaonnistuu(self):
        with self.assertRaises(alue.AlueVirhe):
            alue.Alue("x", self.r / "ei-ole", ("chat",)).valmista(luo=False)

    def test_tiedoston_oikeudet_korjataan_0600_ja_linkki_estaa(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        t = a.polku("chat") / "k.jsonl"
        t.write_text("x")
        os.chmod(t, 0o644)
        a.valmista()
        self.assertEqual(stat.S_IMODE(t.stat().st_mode), 0o600)
        os.symlink(t, a.polku("chat") / "linkki.jsonl")
        with self.assertRaises(alue.AlueVirhe):
            a.valmista()

    def test_kansio_tiedoston_paikalla_estaa(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        (a.polku("chat") / "alikansio").mkdir()
        with self.assertRaises(alue.AlueVirhe):
            a.valmista()

    def test_paallekkaiset_alueet_hylataan(self):
        yks = yksityinen_alue.yksityinen_alue(self.r / "a")
        for toinen in (self.r / "a", self.r / "a" / "sisalla", self.r):
            with self.assertRaises(alue.AlueVirhe):
                alue.tarkista_erottelu(yks, tyokalualue.tyokalualue(toinen))
            with self.assertRaises(alue.AlueVirhe):
                alue.tarkista_erottelu(tyokalualue.tyokalualue(toinen), yks)

    def test_erilliset_alueet_hyvaksytaan_vaikka_nimi_alkaa_samoin(self):
        # "aivo" ja "aivo-yksityinen" eivat ole sisakkain, vaikka toinen on toisen merkkijonoetuliite
        alue.tarkista_erottelu(yksityinen_alue.yksityinen_alue(self.r / "aivo-yksityinen"),
                               tyokalualue.tyokalualue(self.r / "aivo"))

    def test_oletusjuuret_ovat_erilliset_ja_alikansiot_odotetut(self):
        alue.tarkista_erottelu(yksityinen_alue.yksityinen_alue(), tyokalualue.tyokalualue())
        self.assertEqual(yksityinen_alue.yksityinen_alue().juuri, Path("/var/lib/aivo-yksityinen"))
        self.assertEqual(tyokalualue.tyokalualue().juuri, Path("/var/lib/aivo"))
        for uusi in ("tiivistelmat", "indeksi"):
            self.assertIn(uusi, yksityinen_alue.ALIKANSIOT)
            self.assertIn(uusi, tyokalualue.ALIKANSIOT)
        self.assertIn("siirrot", yksityinen_alue.ALIKANSIOT)
        self.assertNotIn("siirrot", tyokalualue.ALIKANSIOT)

    def test_sisaltaa_avaa_symlinkit(self):
        a = alue.Alue("x", self.r / "x", ("chat",))
        a.valmista()
        (self.r / "muu").mkdir()
        os.symlink(self.r / "muu", a.polku("chat") / "ulos")
        self.assertTrue(a.sisaltaa(a.polku("chat") / "k.jsonl"))
        self.assertFalse(a.sisaltaa(a.polku("chat") / "ulos" / "k.jsonl"))
        self.assertFalse(a.sisaltaa(self.r / "muu"))

    def test_kaksi_aluetta_eivat_jaa_yhtaan_polkua(self):
        yks = yksityinen_alue.yksityinen_alue(self.r / "yks")
        tyo = tyokalualue.tyokalualue(self.r / "tyo")
        yp, tp = yks.valmista(), tyo.valmista()
        for p in yp.values():
            self.assertFalse(tyo.sisaltaa(p))
        for p in tp.values():
            self.assertFalse(yks.sisaltaa(p))


class _Loopback:
    """Korvaa socket.socket.connect: vain loopback-yhteydet ja unix-socketit sallitaan, muut kirjataan ja kaadetaan."""

    def __init__(self):
        self.ulkoiset = []
        self._alku = socket.socket.connect

    def __enter__(self):
        alku, ulkoiset = self._alku, self.ulkoiset

        def connect(s, osoite):
            if isinstance(osoite, tuple) and str(osoite[0]) not in ("127.0.0.1", "::1", "localhost"):
                ulkoiset.append(type(osoite).__name__)
                raise AssertionError("ei-loopback-yhteys")
            return alku(s, osoite)
        self._p = mock.patch.object(socket.socket, "connect", connect)
        self._p.start()
        return self

    def __exit__(self, *a):
        self._p.stop()


class KanariaTesti(unittest.TestCase):
    """Yksityisen alueen kanaria ei paady mihinkaan tyokalutilan kautta kulkevaan."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = Path(cls.tmp.name)
        cls.kanaria = "KANARIA-" + os.urandom(8).hex()
        cls.yks = yksityinen_alue.yksityinen_alue(r / "aivo-yksityinen")
        cls.tyo = tyokalualue.tyokalualue(r / "aivo")
        alue.tarkista_erottelu(cls.yks, cls.tyo)
        yp, tp = cls.yks.valmista(), cls.tyo.valmista()
        (yp["muisti"] / "oma.md").write_text("Salainen muisti: %s ja hiljaisuus." % cls.kanaria)
        (yp["ydinohjeet"] / "saannot.md").write_text("Ydinohje: %s" % cls.kanaria)
        (yp["tiivistelmat"] / "t1.json").write_text(json.dumps({"kohta": cls.kanaria}))
        (yp["indeksi"] / "i.db").write_text(cls.kanaria)
        (tp["kirjasto"] / "faktat.md").write_text("TYOKALUTILAN-FAKTA")
        cls.tp = tp
        cls.alaprosessit, cls.claude_syotteet, cls.lokit = [], [], io.StringIO()

        def suorita(kom, **kw):
            cls.alaprosessit.append((list(kom), kw.get("input") or ""))
            return subprocess.CompletedProcess(kom, 0, stdout="pilvivastaus", stderr="")

        def kysy_claude(muisti, historia):
            cls.claude_syotteet.append(chat.muodosta_syote(muisti, historia))
            return chat.kysy_claudelta(muisti, historia, suorita=suorita, env={})

        def kysy_yks(muisti, historia, ohjeet):
            return "Paikallinen vastaus. Muistissa oli: " + cls.kanaria

        cls.tila = chat.Tila(chat.tiivista_salasana(SAL), str(tp["kirjasto"]), str(tp["chat"]), ["h.example"],
                             kysy=kysy_claude, julkaise=lambda *a: "ei-gitissa", yks_data=str(yp["chat"]),
                             yks_muisti=str(yp["muisti"]), ydinohjeet=str(yp["ydinohjeet"]),
                             ehdotukset=str(yp["ehdotukset"]), kysy_yks=kysy_yks)
        cls.srv = chat.kaynnista("127.0.0.1", 0, cls.tila)
        cls.portti = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def api(self, ev, polku, olio):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", polku, body=json.dumps(olio), headers={"Cookie": ev, "X-Aivo": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def kirjaudu(self):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SAL, headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        return r.getheader("Set-Cookie").split(";")[0]

    def aja_molemmat_tilat(self):
        """Yksityinen keskustelu (kanaria viestissa, muistissa ja vastauksessa), sitten tyokalutilan keskustelu.
        Palauttaa (stdout+stderr+logging-teksti, ulkoisten yhteyksien lista)."""
        puskuri = io.StringIO()
        kasittelija = logging.StreamHandler(puskuri)
        juuri_loki = logging.getLogger()
        taso = juuri_loki.level
        juuri_loki.addHandler(kasittelija)
        juuri_loki.setLevel(logging.DEBUG)
        try:
            with contextlib.redirect_stdout(puskuri), contextlib.redirect_stderr(puskuri), _Loopback() as lo:
                ev = self.kirjaudu()
                _, y = self.api(ev, "/api/uusi", {})
                self.assertEqual(y["tila"], "yksityinen")
                s, v = self.api(ev, "/api/viesti", {"keskustelu": y["id"], "teksti": "kerro hiljaisuus " + self.kanaria})
                self.assertEqual(s, 200)
                self.assertIn(self.kanaria, v["vastaus"])         # kanaria kulkee yksityisessa tilassa, kuten pitaakin
                _, t = self.api(ev, "/api/uusi", {"tila": "tyokalu"})
                self.assertEqual(t["tila"], "tyokalu")
                s, v2 = self.api(ev, "/api/viesti", {"keskustelu": t["id"], "teksti": "moi, kerro hiljaisuudesta"})
                self.assertEqual(s, 200)
                self.assertEqual(v2["vastaus"], "pilvivastaus")
        finally:
            juuri_loki.removeHandler(kasittelija)
            juuri_loki.setLevel(taso)
        return puskuri.getvalue(), lo.ulkoiset

    def test_kanaria_ei_paady_tyokalutilan_kehotteeseen_alaprosessiin_lokiin_tai_verkkoon(self):
        n_claude, n_alap = len(self.claude_syotteet), len(self.alaprosessit)
        loki, ulkoiset = self.aja_molemmat_tilat()
        uudet_syotteet = self.claude_syotteet[n_claude:]
        uudet_alap = self.alaprosessit[n_alap:]
        self.assertTrue(uudet_syotteet and uudet_alap)             # tyokalutila todella ajettiin
        self.assertIn("TYOKALUTILAN-FAKTA", uudet_syotteet[-1])    # ja sen muisti on mukana
        for s in uudet_syotteet:
            self.assertNotIn(self.kanaria, s)
        for kom, syote in uudet_alap:
            self.assertNotIn(self.kanaria, " ".join(kom) + syote)
            self.assertNotIn("hiljaisuus " + self.kanaria, syote)
        self.assertNotIn(self.kanaria, loki)
        self.assertEqual(ulkoiset, [])

    def test_kanaria_ei_loydy_tyokalualueen_tiedostoista(self):
        self.aja_molemmat_tilat()
        loydetyt = []
        for p in self.tyo.juuri.rglob("*"):
            if p.is_file() and self.kanaria.encode() in p.read_bytes():
                loydetyt.append(p.name)
        self.assertEqual(loydetyt, [])
        self.assertTrue(any(self.tp["chat"].glob("*.jsonl")))      # tyokalutilan keskustelu tallentui sinne
        # ja vastaavasti yksityisella puolella kanaria on tallessa omassa alueessaan (testi ei ole tyhja)
        self.assertTrue(any(self.kanaria.encode() in p.read_bytes() for p in self.yks.polku("chat").glob("*.jsonl")))

    def test_ei_ulkoisia_kutsuja_urlopen_tai_subprocess_yksityisessa_tilassa(self):
        kutsut = []
        with mock.patch.object(urllib.request, "urlopen", side_effect=lambda *a, **k: kutsut.append("urlopen")), \
                mock.patch.object(subprocess, "run", side_effect=lambda *a, **k: kutsut.append("run")), \
                mock.patch.object(subprocess, "Popen", side_effect=lambda *a, **k: kutsut.append("Popen")):
            ev = self.kirjaudu()
            _, y = self.api(ev, "/api/uusi", {})
            s, _ = self.api(ev, "/api/viesti", {"keskustelu": y["id"], "teksti": "yksityinen " + self.kanaria})
            self.assertEqual(s, 200)
        self.assertEqual(kutsut, [])

    def test_tyokalutilan_syote_ei_sisalla_yksityisia_tiivistelmia_eika_indeksia(self):
        self.aja_molemmat_tilat()
        syote = self.claude_syotteet[-1]
        for tavu in ("Salainen muisti", "Ydinohje", '"kohta"'):
            self.assertNotIn(tavu, syote)

    def test_kanariatesti_havaitsee_vuodon(self):
        """Vastatesti: jos tyokalutilan muisti osoittaisi yksityiseen kansioon, kanaria loytyisi kehotteesta."""
        muisti, _ = chat.lue_muisti(str(self.yks.polku("muisti")))
        self.assertIn(self.kanaria, chat.muodosta_syote(muisti, []))


def _moduulin_puu(nimi):
    return ast.parse((AIVO / nimi).read_text(encoding="utf-8"), filename=nimi)


def _tuodut(puu):
    """Kaikki tuodut moduulinimet kokonaisina ja osina (a.b.c -> a, a.b, a.b.c; from x import y -> x ja x.y)."""
    nimet = set()
    for n in ast.walk(puu):
        if isinstance(n, ast.Import):
            for a in n.names:
                nimet.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            m = ("." * n.level) + (n.module or "")
            nimet.add(m)
            for a in n.names:
                nimet.add(m + "." + a.name)
                nimet.add(a.name)
    osat = set(nimet)
    for k in list(nimet):
        p = k.split(".")
        for i in range(1, len(p) + 1):
            osat.add(".".join(p[:i]))
    return osat


def _tunnisteet(puu):
    """Name-, Attribute-, funktio-, argumentti- ja alias-nimet (ei merkkijonovakioita eika docstringeja)."""
    t = set()
    for n in ast.walk(puu):
        if isinstance(n, ast.Name):
            t.add(n.id)
        elif isinstance(n, ast.Attribute):
            t.add(n.attr)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            t.add(n.name)
        elif isinstance(n, ast.arg):
            t.add(n.arg)
        elif isinstance(n, ast.alias):
            t.add((n.asname or n.name).split(".")[-1])
    return t


def _merkkijonovakiot(puu):
    """Merkkijonovakiot ilman docstringeja."""
    doc = set()
    for n in ast.walk(puu):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = n.body[0] if n.body else None
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                doc.add(id(d.value))
    return [n.value for n in ast.walk(puu)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]


# Moduulit, jotka kuuluvat vain tyokalutilaan (ei sekaprosessia): ne eivat saa tuntea yksityista aluetta.
TYOKALUMODUULIT = ("alue.py", "tyokalualue.py", "tyokalu_kaares.py")
YKSITYISET_MODUULIT_NIMET = ("aivo.yksityinen", "aivo.yksityinen_alue", "yksityinen", "yksityinen_alue", "aivo.tiivista_yksityinen", "tiivista_yksityinen")


class RakenneTesti(unittest.TestCase):
    def test_tarkistetut_tiedostot_ovat_olemassa(self):
        for n in TYOKALUMODUULIT + ("yksityinen_alue.py",):
            self.assertTrue((AIVO / n).is_file(), n)

    def test_tyokalumoduulit_eivat_tuo_yksityisen_alueen_moduuleja(self):
        for n in TYOKALUMODUULIT:
            tuodut = _tuodut(_moduulin_puu(n))
            for kielletty in YKSITYISET_MODUULIT_NIMET:
                self.assertNotIn(kielletty, tuodut, "%s tuo %s" % (n, kielletty))
            self.assertFalse([t for t in tuodut if "yksityinen" in t], n)

    def test_tyokalumoduulit_eivat_sisalla_yksityisen_alueen_polkuja(self):
        for n in TYOKALUMODUULIT:
            for v in _merkkijonovakiot(_moduulin_puu(n)):
                self.assertNotIn("aivo-yksityinen", v, n)
                self.assertNotIn("ydinohjeet", v, n)
                self.assertNotIn("siirrot", v, n)
            self.assertNotIn("aivo-yksityinen", _tunnisteet(_moduulin_puu(n)))

    def test_tyokalualueen_alikansiot_eivat_nimea_yksityisia_kansioita(self):
        for kielletty in ("ydinohjeet", "siirrot", "ehdotukset", "muisti"):
            self.assertNotIn(kielletty, tyokalualue.ALIKANSIOT)

    def test_yksityinen_alue_ei_tuo_alaprosesseja_eika_verkkoa(self):
        tuodut = _tuodut(_moduulin_puu("yksityinen_alue.py"))
        for kielletty in ("subprocess", "socket", "urllib", "http", "requests", "os.system", "aivo.chat", "aivo.tyokalualue",
                          "aivo.tyokalu_kaares", "aivo.openrouter_kulut", "aivo.openrouter_zdr", "tyokalu_kaares"):
            self.assertNotIn(kielletty, tuodut)

    def test_yksityinen_alue_ei_viittaa_clauden_openrouterin_eika_litellmin_nimiin(self):
        puu = _moduulin_puu("yksityinen_alue.py")
        kielletyt = ("claude", "openrouter", "litellm", "kysy_claudelta", "kysy", "subprocess")
        for t in _tunnisteet(puu):
            for k in kielletyt:
                self.assertNotIn(k, t.lower(), t)
        for v in _merkkijonovakiot(puu):
            for k in ("claude", "openrouter", "litellm", "aivo/kirjasto", "/var/lib/aivo/"):
                self.assertNotIn(k, v.lower())

    def test_yksityisen_alueen_juuri_ei_ole_tyokalualueen_sisalla(self):
        self.assertFalse(yksityinen_alue.OLETUS_JUURI.startswith(tyokalualue.OLETUS_JUURI + "/"))
        self.assertNotEqual(yksityinen_alue.OLETUS_JUURI, tyokalualue.OLETUS_JUURI)

    def test_ast_tarkistin_nappaa_haitallisen_esimerkin(self):
        """Vastatesti tarkistimille: haitallinen lahdeteksti havaitaan, hyvaksyttava ei."""
        paha = ast.parse("import subprocess\nfrom aivo import yksityinen_alue\nP = '/var/lib/aivo-yksityinen/chat'\n"
                         "def kysy_claudelta(): pass\n")
        self.assertIn("subprocess", _tuodut(paha))
        self.assertIn("aivo.yksityinen_alue", _tuodut(paha))
        self.assertIn("kysy_claudelta", _tunnisteet(paha))
        self.assertIn("/var/lib/aivo-yksityinen/chat", _merkkijonovakiot(paha))
        hyva = ast.parse('"""Docstring: aivo-yksityinen, claude."""\nimport os\nx = 1\n')
        self.assertEqual(_merkkijonovakiot(hyva), [])
        self.assertEqual(_tuodut(hyva), {"os"})


if __name__ == "__main__":
    unittest.main()
