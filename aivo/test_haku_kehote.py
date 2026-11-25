"""Muistihaun kytkenta chattiin (aivo/haku.py -> tiivistelmat_kehote.hakuosio -> chat). Stdlib unittest.

Tarkistetaan: oikean alueen osumat, ei vuotoa alueiden valilla, osumat lahdeviitteineen ensimmaisena muistiosana,
tyhja tai rikkinainen haku ei kaada, indeksi paivittyy tiivistyksen yhteydessa. Ei verkkoa (paitsi testin oma
loopback-chat), ei mallikutsuja.
"""
import ast
import http.client
import io
import json
import os
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from aivo import (chat, haku, salasana_apu, tiivista_tyokalu, tiivista_yksityinen, tiivistelma, tiivistelmat_kehote,
                  tyokalualue, yhdistelma, yksityinen, yksityinen_alue)

SAL = "oikea-salasana-123"
OR_MALLI = "qwen/qwen3-235b-a22b-2507"
AIVO = Path(__file__).resolve().parent


def _kid(n):
    return "20261114-%06d-%08x" % (n, 0xB0000000 + n)


def tee_tiivistelma(kansio, n, kohdat, aika="2026-11-14T10:15:00+00:00"):
    """Tallentaa jasennetyn tiivistelman. kohdat: [(lainaus, tulkinta), ...]. Palauttaa tunnuksen."""
    viestit = [{"rooli": "tony", "teksti": "Tony: " + " ".join(q for q, _ in kohdat), "aika": aika}]
    raaka = {
        "versio": 1, "keskustelu": _kid(n), "alku": 0, "loppu": 0,
        "ensimmainen_aika": aika, "viimeinen_aika": aika,
        "tiivistetty": "2026-11-14T11:00:00+00:00", "malli": "testimalli",
        "alue_sha": tiivistelma.alueen_sha(viestit, 0, 0),
        "kohdat": [{"id": i + 1, "tyyppi": "fakta", "tony_sanoi": [q], "tulkinta": t, "viestit": [0], "tila": "voimassa"}
                   for i, (q, t) in enumerate(kohdat)],
    }
    return tiivistelma.tallenna(kansio, raaka, viestit)


class _Alueet(unittest.TestCase):
    """Kaksi aluetta samassa tilapaishakemistossa: yksityinen ja tyokalu, kummallakin oma kanaria."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.r = Path(self._t.name)
        self.yks = yksityinen_alue.yksityinen_alue(self.r / "yks")
        self.tyo = tyokalualue.tyokalualue(self.r / "tyo")
        self.yks.valmista()
        self.tyo.valmista()
        self.yks_t = tee_tiivistelma(self.yks.polku("tiivistelmat"), 1,
                                     [("muuttokuorma lauantaina", "YKS-KANARIA: Tony muuttaa lauantaina.")])
        self.tyo_t = tee_tiivistelma(self.tyo.polku("tiivistelmat"), 2,
                                     [("pipeline hajosi eilen", "TYO-KANARIA: CI-putki hajosi.")])
        haku.rakenna(self.yks)
        haku.rakenna(self.tyo)

    def osio(self, a, kysely, **kw):
        return tiivistelmat_kehote.hakuosio(str(a.polku("tiivistelmat")), kysely, **kw)


class HakuosioTesti(_Alueet):
    def test_oikean_alueen_osuma_lahdeviitteineen(self):
        teksti, tiedostot = self.osio(self.yks, "milloin muuttokuorma on?")
        self.assertTrue(teksti.startswith(tiivistelmat_kehote.HAKU_OTSIKKO))
        self.assertIn("YKS-KANARIA", teksti)
        self.assertIn("[l\u00e4hde: tiivistelmat/%s.json]" % self.yks_t, teksti)
        self.assertIn('Tony sanoi: "muuttokuorma lauantaina"', teksti)
        self.assertEqual(tiedostot, ["tiivistelmat/%s.json" % self.yks_t])

    def test_ei_vuotoa_alueiden_valilla(self):
        for a, vieras in ((self.yks, "pipeline hajosi"), (self.tyo, "muuttokuorma lauantaina")):
            self.assertEqual(self.osio(a, vieras), ("", []))
        teksti, _ = self.osio(self.tyo, "pipeline hajosi muuttokuorma")
        self.assertIn("TYO-KANARIA", teksti)
        self.assertNotIn("YKS-KANARIA", teksti)

    def test_toisen_alueen_indeksi_ei_tuo_toisen_alueen_sisaltoa(self):
        """Vaikka tyokalualueen indeksi kopioitaisiin yksityiselle alueelle, sisalto luetaan vain omasta kansiosta."""
        (self.yks.polku("indeksi") / haku.INDEKSI_NIMI).write_bytes(
            (self.tyo.polku("indeksi") / haku.INDEKSI_NIMI).read_bytes())
        self.assertEqual(self.osio(self.yks, "pipeline hajosi"), ("", []))

    def test_tyhja_haku_ei_kaada(self):
        for kysely in ("", "   ", "?!.,", None, 123):
            self.assertEqual(self.osio(self.yks, kysely), ("", []), repr(kysely))
        self.assertEqual(self.osio(self.yks, "sana jota ei ole missaan"), ("", []))
        self.assertEqual(tiivistelmat_kehote.hakuosio(None, "muuttokuorma"), ("", []))
        self.assertEqual(self.osio(self.yks, "muuttokuorma", ylaraja=0), ("", []))

    def test_puuttuva_tai_rikkinainen_indeksi_ei_kaada(self):
        p = self.yks.polku("indeksi") / haku.INDEKSI_NIMI
        p.write_bytes(b"ei sqlite-tiedosto" * 100)
        self.assertEqual(self.osio(self.yks, "muuttokuorma"), ("", []))
        p.unlink()
        self.assertEqual(self.osio(self.yks, "muuttokuorma"), ("", []))
        os.symlink(self.tyo.polku("indeksi") / haku.INDEKSI_NIMI, p)
        self.assertEqual(self.osio(self.yks, "pipeline"), ("", []))

    def test_kansio_ei_nimelta_tiivistelmat_ei_arvaa_indeksia(self):
        muu = self.r / "yks" / "muut"
        muu.mkdir(mode=0o700)
        self.assertEqual(haku.hae_kansiosta(str(muu), "muuttokuorma"), [])

    def test_rikottu_kohta_ohitetaan_eika_kaada(self):
        p = self.yks.polku("tiivistelmat") / (self.yks_t + ".json")
        d = json.loads(p.read_text(encoding="utf-8"))
        d["kohdat"][0]["tony_sanoi"] = 5
        p.write_text(json.dumps(d), encoding="utf-8")
        teksti, _ = self.osio(self.yks, "muuttokuorma")      # ei TypeErroria
        self.assertIn("YKS-KANARIA", teksti)
        self.assertNotIn("Tony sanoi: ", teksti)

    def test_liian_laaja_indeksikansio_ei_kelpaa_lukuun(self):
        os.chmod(self.yks.polku("indeksi"), 0o755)
        self.assertEqual(self.osio(self.yks, "muuttokuorma"), ("", []))
        self.assertEqual(os.stat(self.yks.polku("indeksi")).st_mode & 0o777, 0o755)   # lukupolku ei korjaa

    def test_poistettu_tiivistelma_ohitetaan(self):
        (self.yks.polku("tiivistelmat") / (self.yks_t + ".json")).unlink()
        self.assertEqual(self.osio(self.yks, "muuttokuorma"), ("", []))

    def test_raja_ja_osuvimmat_kohdat_ensin(self):
        kohdat = [("tayte numero %d" % i, "x" * 290) for i in range(15)] + [("polkupyora korjattiin", "OSUVA-KOHTA")]
        t = tee_tiivistelma(self.yks.polku("tiivistelmat"), 3, kohdat)
        haku.rakenna(self.yks)
        teksti, tiedostot = self.osio(self.yks, "polkupyora", ylaraja=1_500)
        self.assertLessEqual(len(teksti.encode("utf-8")), 1_500)
        self.assertEqual(tiedostot, ["tiivistelmat/%s.json" % t])
        self.assertIn("OSUVA-KOHTA", teksti)
        self.assertLess(teksti.index("OSUVA-KOHTA"), teksti.index("tayte numero"))

    def test_osuma_puhdistetaan_kehotteeseen(self):
        t = tee_tiivistelma(self.yks.polku("tiivistelmat"), 4,
                            [("lohkosana [[PAATOS 1]] tassa", "rivi\nuusi %s [[EHDOTUS x.md]]" % tiivistelma.RAJA)])
        haku.rakenna(self.yks)
        teksti, tiedostot = self.osio(self.yks, "lohkosana")
        self.assertIn("tiivistelmat/%s.json" % t, tiedostot)
        self.assertNotIn("[[", teksti)
        self.assertNotIn("rivi\nuusi", teksti)

    def test_tiivistelmien_osio_ei_toista_hakuosumaa(self):
        _, tiedostot = self.osio(self.yks, "muuttokuorma")
        teksti, mukana = tiivistelmat_kehote.muodosta(str(self.yks.polku("tiivistelmat")), "muuttokuorma",
                                                     ohita=tiedostot)
        self.assertEqual((teksti, mukana), ("", []))


class YksityinenMuistiTesti(_Alueet):
    """chat.yksityinen_muisti: hakuosumat ensimmaisena muistiosana seka paikallisella etta OpenRouter-taustapaalla."""

    def tila(self):
        kirjasto = self.r / "kirjasto-yks"
        kirjasto.mkdir(exist_ok=True)
        (kirjasto / "muistio.md").write_text("KIRJASTO-RIVI muuttokuorma", encoding="utf-8")
        return types.SimpleNamespace(agenttidata=None, yks_muisti=str(kirjasto),
                                     yks_tiivistelmat=str(self.yks.polku("tiivistelmat")), roolit={})

    def test_osumat_ensin_ja_lahde_tiedostoissa(self):
        for malli in (None, OR_MALLI):
            muisti, tiedostot = chat.yksityinen_muisti(self.tila(), "muuttokuorma?", [{"rooli": "tony", "teksti": "x"}],
                                                      "o", malli, yhdistelma.OLETUS)
            self.assertTrue(muisti.startswith(tiivistelmat_kehote.HAKU_OTSIKKO), malli)
            self.assertEqual(tiedostot[0], "tiivistelmat/%s.json" % self.yks_t)
            self.assertIn("KIRJASTO-RIVI", muisti)
            self.assertEqual(muisti.count("tiivistelmat/%s.json" % self.yks_t), 1)    # ei toistoa tiivistelmien osiossa
            self.assertNotIn("TYO-KANARIA", muisti)

    def test_paikallinen_muistiraja_ei_kasva(self):
        muisti, _ = chat.yksityinen_muisti(self.tila(), "muuttokuorma", [], "o", None, yhdistelma.OLETUS)
        haku_osa = muisti[:muisti.index("KIRJASTO-RIVI")]
        self.assertLessEqual(len(haku_osa.encode("utf-8")), yksityinen.MUISTI_YLARAJA // 4 + len(chat.RAJA) + 1)

    def test_ilman_osumia_muisti_kuten_ennen(self):
        muisti, tiedostot = chat.yksityinen_muisti(self.tila(), "kirjasto-rivi", [], "o", None, yhdistelma.OLETUS)
        self.assertNotIn(tiivistelmat_kehote.HAKU_OTSIKKO, muisti)
        self.assertEqual(tiedostot[0], "muistio.md")


class ChatKytkentaTesti(unittest.TestCase):
    """Molemmat tilat HTTP:n kautta: kumpikin saa vain oman alueensa osumat, ja osuman lahde kelpaa."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = Path(cls.tmp.name)
        (r / "kirjasto").mkdir()
        (r / "kirjasto" / "faktat.md").write_text("KIRJASTON-FAKTA")
        (r / "yks" / "muisti").mkdir(parents=True)
        (r / "yks" / "ydin").mkdir()
        (r / "yks" / "ydin" / "saannot.md").write_text("YDIN")
        tyo = tyokalualue.tyokalualue(r / "aivo")
        tyo.valmista()
        yks = yksityinen_alue.yksityinen_alue(r / "yksalue")
        yks.valmista()
        cls.tyo_t = "tiivistelmat/%s.json" % tee_tiivistelma(tyo.polku("tiivistelmat"), 7,
                                                             [("deploy torstaina", "TYO-KANARIA")])
        cls.yks_t = "tiivistelmat/%s.json" % tee_tiivistelma(yks.polku("tiivistelmat"), 8,
                                                             [("hammaslaakari torstaina", "YKS-KANARIA")])
        haku.rakenna(tyo)
        haku.rakenna(yks)
        cls.claude, cls.paikallinen = [], []

        def kysy(muisti, historia):
            cls.claude.append(muisti)
            return "Vastaus [l\u00e4hde: %s]." % cls.tyo_t

        def kysy_yks(muisti, historia, ohjeet):
            cls.paikallinen.append(muisti)
            return "Vastaus [l\u00e4hde: %s]." % cls.yks_t
        cls.tila = chat.Tila(salasana_apu.tiiviste(SAL), str(r / "kirjasto"), str(r / "data"), [".ts" + ".net"],
                             kysy=kysy, yks_data=str(r / "yks" / "chat"), yks_muisti=str(r / "yks" / "muisti"),
                             ydinohjeet=str(r / "yks" / "ydin"), ehdotukset=str(r / "yks" / "ehd"), kysy_yks=kysy_yks,
                             tiivistelmat=str(tyo.polku("tiivistelmat")),
                             yks_tiivistelmat=str(yks.polku("tiivistelmat")))
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
        c.request("POST", polku, body=json.dumps(olio),
                  headers={"Cookie": ev, "X-Aivo": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def kirjaudu(self):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SAL,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        return r.getheader("Set-Cookie").split(";")[0]

    def viesti(self, tila, teksti):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": tila} if tila else {})
        return self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": teksti})

    def test_tyokalutila_saa_oman_alueen_osuman_ensin(self):
        s, v = self.viesti("tyokalu", "mita torstaina tapahtuu?")
        self.assertEqual(s, 200)
        muisti = self.claude[-1]
        self.assertTrue(muisti.startswith(tiivistelmat_kehote.HAKU_OTSIKKO))
        self.assertIn("TYO-KANARIA", muisti)
        self.assertIn("KIRJASTON-FAKTA", muisti)
        self.assertNotIn("YKS-KANARIA", muisti)
        self.assertEqual(v["tuntemattomia_lahteita"], 0)

    def test_yksityinen_tila_saa_oman_alueen_osuman_ensin(self):
        s, v = self.viesti(None, "mita torstaina tapahtuu?")
        self.assertEqual(s, 200)
        muisti = self.paikallinen[-1]
        self.assertTrue(muisti.startswith(tiivistelmat_kehote.HAKU_OTSIKKO))
        self.assertIn("YKS-KANARIA", muisti)
        self.assertNotIn("TYO-KANARIA", muisti)
        self.assertEqual(v["tuntemattomia_lahteita"], 0)

    def test_journaliin_vain_osumien_maara(self):
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            s, _ = self.viesti(None, "torstaina")
        self.assertEqual(s, 200)
        self.assertIn("muistihaku yksityinen: 1 osumaa", err.getvalue())
        self.assertNotIn("YKS-KANARIA", err.getvalue())
        self.assertNotIn(self.yks_t, err.getvalue())

    def test_tyhja_haku_ei_kaada_chattia(self):
        for tila in ("tyokalu", None):
            s, _ = self.viesti(tila, "?")
            self.assertEqual(s, 200)

    def test_hakuvirhe_ei_kaada_chattia(self):
        with mock.patch.object(haku, "hae", side_effect=haku.HakuVirhe("haku epaonnistui (OperationalError)")):
            for tila in ("tyokalu", None):
                s, _ = self.viesti(tila, "torstaina")
                self.assertEqual(s, 200)


class IndeksinPaivitysTesti(unittest.TestCase):
    """Tiivistysajon lopussa hakuindeksi rakennetaan, jos tiivistelmia tuli, indeksi puuttuu tai kansio muuttui."""

    MODUULIT = ((tiivista_yksityinen, yksityinen_alue.yksityinen_alue), (tiivista_tyokalu, tyokalualue.tyokalualue))

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.nyt = tiivista_tyokalu._nyt()

    def alue(self, tee):
        a = tee(Path(self._t.name) / tee.__name__)
        a.valmista()
        return a

    def test_puuttuva_indeksi_rakennetaan_ja_muuttumaton_jaa(self):
        for m, tee in self.MODUULIT:
            a = self.alue(tee)
            t = tee_tiivistelma(a.polku("tiivistelmat"), 1, [("kesamokki jarvella", "mokki")])
            ulos = []
            m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 0}, ulos.append)
            self.assertEqual([x["tunnus"] for x in haku.hae(a, "kesamokki")], [t], m.__name__)
            self.assertIn("hakuindeksi: 1 tiivistelmaa", ulos[-1])
            ulos.clear()
            m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 0}, ulos.append)
            self.assertEqual(ulos, [], m.__name__)                         # ei muutosta => ei uudelleenrakennusta

    def test_uusi_tiivistelma_tai_kansion_muutos_rakentaa_uudelleen(self):
        for m, tee in self.MODUULIT:
            a = self.alue(tee)
            m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 0}, lambda _: None)
            vanha = time.time() - 100
            os.utime(haku.indeksin_polku(a), (vanha, vanha))
            t = tee_tiivistelma(a.polku("tiivistelmat"), 2, [("purjevene satamassa", "vene")])
            m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 0}, lambda _: None)
            self.assertEqual([x["tunnus"] for x in haku.hae(a, "purjevene")], [t], m.__name__)
            t2 = tee_tiivistelma(a.polku("tiivistelmat"), 3, [("talviturkki pois", "uinti")])
            m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 1}, lambda _: None)
            self.assertEqual([x["tunnus"] for x in haku.hae(a, "talviturkki")], [t2], m.__name__)

    def test_rakennusvirhe_kirjataan_tyyppina_eika_kaada(self):
        for m, tee in self.MODUULIT:
            a = self.alue(tee)
            ulos = []
            with mock.patch.object(haku, "rakenna", side_effect=haku.HakuVirhe("x (OperationalError)")):
                m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 1}, ulos.append)
            self.assertIn("hakuindeksi: rakennus epaonnistui (HakuVirhe)", ulos[-1])

    def test_levyvirhe_kirjataan_eika_kaada(self):
        for m, tee in self.MODUULIT:
            a = self.alue(tee)
            ulos = []
            with mock.patch.object(haku.tempfile, "mkstemp", side_effect=OSError("taynna")):
                m.paivita_hakuindeksi(a, self.nyt, {"tiivistetty": 1}, ulos.append)
            self.assertIn("hakuindeksi: rakennus epaonnistui (OSError)", ulos[-1])

    def test_aja_rakentaa_indeksin_tiivistyksen_jalkeen(self):
        """Kokonainen tyokalualueen ajo vaarennetylla mallilla: tiivistyksen jalkeen haku loytaa uuden tiivistelman."""
        a = self.alue(tyokalualue.tyokalualue)
        kid = _kid(9)
        viestit = [{"rooli": "tony", "teksti": "Haluan oppia kubernetesin perusteet.", "aika": "2026-11-01T10:00:00+00:00"},
                   {"rooli": "aivo", "teksti": "Selva.", "aika": "2026-11-01T10:01:00+00:00"}]
        (a.polku("chat") / (kid + ".jsonl")).write_text(
            "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in viestit), encoding="utf-8")
        vastaus = json.dumps({"kohdat": [{"tyyppi": "fakta", "tony_sanoi": ["oppia kubernetesin perusteet"],
                                          "tulkinta": "Tony haluaa oppia Kubernetesia.", "viestit": [0]}]})
        with mock.patch("sys.stdout", io.StringIO()):
            tulos = tiivista_tyokalu.aja(a.juuri, lambda syote: vastaus)
        self.assertEqual(tulos["tiivistetty"], 1, tulos)
        self.assertEqual(len(haku.hae(a, "kubernetesin")), 1)


class RakenneTesti(unittest.TestCase):
    def test_hakuosio_ei_tuo_verkkoa_alaprosesseja_eika_tilamoduuleja(self):
        for n in ("tiivistelmat_kehote.py", "haku.py"):
            puu = ast.parse((AIVO / n).read_text(encoding="utf-8"))
            tuodut = set()
            for x in ast.walk(puu):
                if isinstance(x, ast.Import):
                    tuodut |= {a.name for a in x.names}
                elif isinstance(x, ast.ImportFrom):
                    tuodut |= {"%s.%s" % (x.module, a.name) for a in x.names} | {x.module or ""}
            for kielletty in ("subprocess", "socket", "urllib", "http", "requests", "aivo.chat", "aivo.yksityinen",
                              "aivo.yksityinen_or", "aivo.openrouter_kulut", "aivo.tyokalu_kaares"):
                self.assertNotIn(kielletty, tuodut, n)


if __name__ == "__main__":
    unittest.main()
