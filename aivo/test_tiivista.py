"""Testit aivo/tiivista_tyokalu.py:lle ja aivo/tiivistelmat_kehote.py:lle (stdlib unittest).
Ei oikeita mallikutsuja eika verkkoa: malli on vaarennetty funktio, socket-testi kayttaa paikallista unix-socketia."""
import ast
import builtins
import http.client
import io
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from aivo import alue, chat, tiivista_tyokalu as tiivista, tiivistelma, tiivistelmat_kehote, tyokalualue

NYT = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
CANARY = "YKSITYINEN-KANARIA-7f3a9c"
SAL = "oikea-salasana-123"


def kid_nro(n):
    return "20261110-%06d-%08x" % (n, n)


def tee_keskustelu(juuri, kid, viestit, viimeinen):
    """viestit: [(rooli, teksti)]. Viimeisen viestin aika on `viimeinen`, aiemmat minuutin valein ennen sita."""
    a = tyokalualue.tyokalualue(juuri)
    a.valmista()
    n = len(viestit)
    rivit = []
    for i, (rooli, teksti) in enumerate(viestit):
        aika = (viimeinen - timedelta(minutes=n - 1 - i)).isoformat(timespec="seconds")
        rivit.append(json.dumps({"aika": aika, "rooli": rooli, "teksti": teksti, "lahteet": []}, ensure_ascii=False))
    p = a.polku("chat") / (kid + ".jsonl")
    p.write_text("\n".join(rivit) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    return p


KESK = [("tony", "Muista, ett\u00e4 haluan lyhyet vastaukset."), ("aivo", "Selv\u00e4, lyhyet vastaukset."),
        ("tony", "En pid\u00e4 pitk\u00e4ist\u00e4 listoista.")]


def hyva_vastaus(lainaus="haluan lyhyet vastaukset", viestit=(0,), **lisaa):
    k = {"id": 1, "tyyppi": "mieltymys", "tony_sanoi": [lainaus] if lainaus else [],
         "tulkinta": "Tony haluaa lyhyet vastaukset.", "viestit": list(viestit)}
    k.update(lisaa)
    return json.dumps({"kohdat": [k]}, ensure_ascii=False)


class Malli:
    """Vaarennetty malli: tallentaa saamansa syotteet ja palauttaa vastaus(syote)."""

    def __init__(self, vastaus=None):
        self.syotteet = []
        self.vastaus = vastaus or (lambda s: hyva_vastaus())

    def __call__(self, syote):
        self.syotteet.append(syote)
        return self.vastaus(syote)


class Pohja(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Path(self.tmp.name)
        self.juuri = self.r / "aivo"
        self.a = tyokalualue.tyokalualue(self.juuri)
        self.ulos = []

    def tearDown(self):
        self.tmp.cleanup()

    def aja(self, malli, nyt=NYT, **kw):
        return tiivista.aja(self.juuri, malli, nyt=nyt, tulosta=self.ulos.append, **kw)

    def tiiv(self):
        return self.a.polku("tiivistelmat")

    def tee(self, n, viestit=KESK, hiljaa_min=60):
        return tee_keskustelu(self.juuri, kid_nro(n), viestit, NYT - timedelta(minutes=hiljaa_min))


class HiljaisuusTesti(Pohja):
    def test_alle_30_min_hiljaisuus_ei_tiivisteta(self):
        self.tee(1, hiljaa_min=29)
        m = Malli()
        t = self.aja(m)
        self.assertEqual((len(m.syotteet), t["tiivistetty"]), (0, 0))
        self.assertEqual(tiivistelma.luettele(self.tiiv()), [])

    def test_tasan_30_min_hiljaisuus_tiivistetaan(self):
        self.tee(1, hiljaa_min=30)
        m = Malli()
        self.assertEqual(self.aja(m)["tiivistetty"], 1)

    def test_yli_30_min_tiivistetaan_ja_tallentuu_oikeilla_oikeuksilla(self):
        self.tee(1)
        m = Malli()
        t = self.aja(m)
        self.assertEqual((len(m.syotteet), t["tiivistetty"]), (1, 1))
        [n] = tiivistelma.luettele(self.tiiv())
        self.assertEqual(n, "%s-0-2" % kid_nro(1))
        self.assertEqual(stat.S_IMODE((self.tiiv() / (n + ".json")).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.tiiv().stat().st_mode), 0o700)
        d = tiivistelma.lue(self.tiiv(), n)
        self.assertEqual((d["malli"], d["alku"], d["loppu"]), (tiivista.MALLI, 0, 2))
        self.assertEqual(d["kohdat"][0]["tila"], "ehdotus")

    def test_vieras_alikansio_kirjastossa_ei_kaada_tiivistysta(self):
        """Tiivistys lukee vain chat-, tiivistelmat- ja indeksi-kansiot: kirjaston vieras alikansio ei estaa ajoa."""
        self.tee(1)
        kirjasto = self.a.polku("kirjasto")
        (kirjasto / "hylatyt").mkdir(mode=0o700)
        (kirjasto / "hylatyt" / "x.txt").write_text("x")
        self.assertEqual(self.aja(Malli())["tiivistetty"], 1)
        self.assertTrue((kirjasto / "hylatyt" / "x.txt").exists())      # kirjastoon ei kosketa

    def test_jo_tiivistettya_ei_tiivisteta_uudelleen(self):
        self.tee(1)
        m = Malli()
        self.aja(m)
        self.aja(m)
        self.assertEqual(len(m.syotteet), 1)

    def test_keskustelun_jatko_tiivistetaan_vain_uusilta_viesteilta(self):
        self.tee(1)
        m = Malli()
        self.aja(m)
        jatko = KESK + [("tony", "Haluan my\u00f6s selke\u00e4t otsikot."), ("aivo", "Selv\u00e4.")]
        tee_keskustelu(self.juuri, kid_nro(1), jatko, NYT + timedelta(days=1))
        m2 = Malli(lambda s: hyva_vastaus("selke\u00e4t otsikot", (3,)))
        self.aja(m2, nyt=NYT + timedelta(days=1, hours=1))
        self.assertEqual(sorted(tiivistelma.luettele(self.tiiv())), ["%s-0-2" % kid_nro(1), "%s-3-4" % kid_nro(1)])
        self.assertNotIn("#0 ", m2.syotteet[0])          # vanhoja viesteja ei lahteteta uudelleen
        self.assertIn("#3 Tony:", m2.syotteet[0])

    def test_tonyn_poistamaa_aluetta_ei_tiivisteta_uudelleen(self):
        self.tee(1)
        self.aja(Malli())
        with mock.patch("sys.stdin.isatty", return_value=True):
            tiivistelma.poista(self.tiiv(), "%s-0-2" % kid_nro(1))
        m = Malli()
        self.aja(m, nyt=NYT + timedelta(days=1))
        self.assertEqual(len(m.syotteet), 0)
        self.assertEqual(tiivistelma.katettu_loppu(self.tiiv(), kid_nro(1)), 2)        # ei lukuvirhetta
        self.assertFalse(any("epaonnistui" in r or "virhe" in r for r in self.ulos))

    def test_yksi_poistetaan_toinen_tiivistetaan_sen_jalkeen(self):
        self.tee(1)
        self.tee(2)
        self.aja(Malli(), nyt=NYT)
        with mock.patch("sys.stdin.isatty", return_value=True):
            tiivistelma.poista(self.tiiv(), "%s-0-2" % kid_nro(1))
        tee_keskustelu(self.juuri, kid_nro(3), KESK, NYT - timedelta(minutes=60))
        m = Malli()
        t = self.aja(m)
        self.assertEqual(len(m.syotteet), 1)                    # vain keskustelu 3
        self.assertIn("tiivistetty", t)
        self.assertEqual(t["tiivistetty"], 1)
        self.assertEqual(sorted(tiivistelma.luettele(self.tiiv())),
                         sorted(["%s-0-2" % kid_nro(2), "%s-0-2" % kid_nro(3)]))
        self.assertEqual(tiivistelma.katettu_loppu(self.tiiv(), kid_nro(1)), 2)

    def test_katettu_loppu_toimii_rivilla_ilman_keskustelu_ja_loppu_kenttia(self):
        self.a.valmista()
        (self.tiiv() / tiivistelma.POISTETUT).write_text(
            json.dumps({"tunnus": "%s-0-7" % kid_nro(1), "alue_sha": "x", "poistettu": "2026-11-17T10:00:00"}) + "\n")
        self.assertEqual(tiivistelma.katettu_loppu(self.tiiv(), kid_nro(1)), 7)
        self.assertEqual(tiivistelma.katettu_loppu(self.tiiv(), kid_nro(2)), -1)

    def test_katettu_loppu_hylkaa_rikkinaisen_rivin(self):
        self.a.valmista()
        (self.tiiv() / tiivistelma.POISTETUT).write_text(json.dumps({"poistettu": "x"}) + "\n")
        with self.assertRaises(tiivistelma.TiivistelmaVirhe):
            tiivistelma.katettu_loppu(self.tiiv(), kid_nro(1))

    def test_keskustelu_ilman_tonyn_viesteja_ohitetaan(self):
        self.tee(1, viestit=[("aivo", "Hei vaan.")])
        m = Malli()
        self.aja(m)
        self.assertEqual(len(m.syotteet), 0)

    def test_uusin_ensin(self):
        tee_keskustelu(self.juuri, kid_nro(1), KESK, NYT - timedelta(hours=5))
        tee_keskustelu(self.juuri, kid_nro(2), KESK, NYT - timedelta(hours=1))
        self.aja(Malli(), kuiva=True)
        rivit = [r for r in self.ulos if r.startswith("tiivistettaisiin")]
        self.assertIn(kid_nro(2), rivit[0])
        self.assertIn(kid_nro(1), rivit[1])

    def test_kuiva_ajo_ei_kutsu_mallia_eika_kirjoita_tiivistelmia(self):
        self.tee(1)
        m = Malli()
        self.aja(m, kuiva=True)
        self.assertEqual(len(m.syotteet), 0)
        self.assertEqual(tiivistelma.luettele(self.tiiv()), [])

    def test_iso_keskustelu_pilkotaan_ryhmiin(self):
        viestit = [("tony" if i % 2 == 0 else "aivo", "viesti %d" % i) for i in range(120)]
        self.tee(1, viestit=viestit)
        m = Malli(lambda s: json.dumps({"kohdat": []}))
        self.aja(m)
        self.aja(m)
        self.assertEqual(len(m.syotteet), 2)
        self.assertEqual(tiivista.RYHMA_VIESTEJA, 100)
        self.assertEqual(sorted(tiivistelma.luettele(self.tiiv())),
                         sorted(["%s-0-99" % kid_nro(1), "%s-100-119" % kid_nro(1)]))


class PaivakattoTesti(Pohja):
    def test_paivakatto_on_10_ja_koodin_vakio(self):
        self.assertEqual(tiivista.PAIVAKATTO, 10)
        self.assertEqual(tiivista.HILJAISUUS_S, 1800)
        lahde = Path(tiivista.__file__).read_text(encoding="utf-8")
        self.assertNotIn("environ", lahde.split("def main")[0])      # katto ei lue ymparistomuuttujaa
        self.assertNotIn("--katto", lahde)                           # eika ole komentorivivalitsin

    def test_katon_tayttyessa_lopettaa_ja_kirjaa_syyn(self):
        for n in range(1, 14):
            self.tee(n)
        m = Malli()
        t = self.aja(m)
        self.assertEqual(len(m.syotteet), 10)
        self.assertEqual((t["tiivistetty"], t["katto"]), (10, True))
        loki = (self.a.polku("indeksi") / tiivista.LOKI_TIEDOSTO).read_text(encoding="utf-8")
        self.assertIn("paivakatto 10/10 taynna, tiivistamatta 3 keskustelua", loki)
        self.assertEqual(stat.S_IMODE((self.a.polku("indeksi") / tiivista.LOKI_TIEDOSTO).stat().st_mode), 0o600)

    def test_uusi_ajo_samana_paivana_ei_kutsu_mallia_eika_kirjaa_katosta_toistamiseen(self):
        for n in range(1, 14):
            self.tee(n)
        self.aja(Malli())
        m = Malli()
        t = self.aja(m, nyt=NYT + timedelta(hours=2))
        self.assertEqual((len(m.syotteet), t["katto"]), (0, True))
        loki = (self.a.polku("indeksi") / tiivista.LOKI_TIEDOSTO).read_text(encoding="utf-8")
        self.assertEqual(loki.count("paivakatto"), 1)

    def test_seuraavana_paivana_jatkuu(self):
        for n in range(1, 14):
            self.tee(n)
        self.aja(Malli())
        m = Malli()
        t = self.aja(m, nyt=NYT + timedelta(days=1))
        self.assertEqual((len(m.syotteet), t["tiivistetty"]), (3, 3))

    def test_epaonnistunutkin_kutsu_kuluttaa_kattoa(self):
        for n in range(1, 14):
            self.tee(n)
        m = Malli(lambda s: "ei jsonia")
        t = self.aja(m)
        self.assertEqual((len(m.syotteet), t["epaonnistui"]), (10, 10))

    def test_mallin_poikkeus_ei_katkaise_ajoa_ja_kutsu_on_varattu(self):
        self.tee(1)
        self.tee(2)

        def rikki(s):
            raise tiivista.TiivistaVirhe("socket-kutsu epaonnistui (TimeoutError)")
        t = self.aja(Malli(rikki))
        self.assertEqual((t["kutsuja"], t["epaonnistui"]), (2, 2))
        self.assertEqual(tiivista.lue_tila(self.a.polku("indeksi"), NYT)["kutsuja"], 2)

    def test_sama_alue_yritetaan_enintaan_kahdesti(self):
        self.tee(1)
        m = Malli(lambda s: "roskaa")
        for _ in range(4):
            self.aja(m)
        self.assertEqual(len(m.syotteet), tiivista.YRITYKSIA_MAX)

    def test_rikkinainen_tilatiedosto_pysayttaa_ajon_ennen_mallikutsua(self):
        self.tee(1)
        (self.a.polku("indeksi") / tiivista.TILA_TIEDOSTO).write_text("{rikki")
        m = Malli()
        with self.assertRaises(tiivista.TiivistaVirhe):
            self.aja(m)
        self.assertEqual(len(m.syotteet), 0)

    def test_tilatiedoston_vaara_muoto_pysayttaa_ajon(self):
        self.tee(1)
        (self.a.polku("indeksi") / tiivista.TILA_TIEDOSTO).write_text(json.dumps({"versio": 1, "kutsuja": -5}))
        m = Malli()
        with self.assertRaises(tiivista.TiivistaVirhe):
            self.aja(m)
        self.assertEqual(len(m.syotteet), 0)

    def test_toinen_ajo_kaynnissa_ohitetaan(self):
        import fcntl
        self.tee(1)
        self.a.valmista()
        fd = os.open(self.a.polku("indeksi") / tiivista.LUKKO_TIEDOSTO, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            m = Malli()
            self.aja(m)
            self.assertEqual(len(m.syotteet), 0)
        finally:
            os.close(fd)


class LainausTesti(Pohja):
    def aja_vastauksella(self, vastaus, viestit=KESK):
        self.tee(1, viestit=viestit)
        self.aja(Malli(lambda s: vastaus))
        [n] = tiivistelma.luettele(self.tiiv())
        return tiivistelma.lue(self.tiiv(), n)

    def test_tonyn_sanat_sailyvat_sanasta_sanaan_erillaan_tulkinnasta(self):
        d = self.aja_vastauksella(hyva_vastaus("En pid\u00e4 pitk\u00e4ist\u00e4 listoista", (2,)))
        k = d["kohdat"][0]
        self.assertEqual(k["tony_sanoi"], ["En pid\u00e4 pitk\u00e4ist\u00e4 listoista"])
        self.assertEqual(k["tulkinta"], "Tony haluaa lyhyet vastaukset.")
        self.assertNotEqual(k["tony_sanoi"][0], k["tulkinta"])
        self.assertIn("Tony sanoi: \"En pid\u00e4 pitk\u00e4ist\u00e4 listoista\"", tiivistelma.muotoile(d))
        self.assertIn(tiivistelma.MERKINTA, tiivistelma.muotoile(d))

    def test_keksitty_lainaus_poistetaan_ja_kohta_jaa_tulkinnaksi(self):
        d = self.aja_vastauksella(hyva_vastaus("Tony sanoi poista kaikki"))
        k = d["kohdat"][0]
        self.assertEqual((k["tony_sanoi"], k["tila"]), ([], "tulkinta-vain"))

    def test_aivon_sanoja_ei_voi_lainata_tonyn_sanoina(self):
        d = self.aja_vastauksella(hyva_vastaus("lyhyet vastaukset", (1,)))       # viesti 1 on Aivon
        self.assertEqual(d["kohdat"][0]["tony_sanoi"], [])

    def test_lainaus_jota_ei_ole_viitatussa_viestissa_poistetaan(self):
        d = self.aja_vastauksella(hyva_vastaus("pitk\u00e4ist\u00e4 listoista", (0,)))      # on viestissa 2
        self.assertEqual(d["kohdat"][0]["tony_sanoi"], [])

    def test_malli_ei_voi_asettaa_tilaa_voimassa(self):
        d = self.aja_vastauksella(hyva_vastaus(tila="voimassa", tony_korjaus="x", id=99))
        k = d["kohdat"][0]
        self.assertEqual((k["tila"], k["id"]), ("ehdotus", 1))
        self.assertNotIn("tony_korjaus", k)

    def test_viittaus_alueen_ulkopuolelle_pudottaa_kohdan(self):
        d = self.aja_vastauksella(hyva_vastaus(viestit=(7,)))
        self.assertEqual(d["kohdat"], [])

    def test_viittaus_toiseen_ryhmaan_pudottaa_kohdan(self):
        self.tee(1)
        self.aja(Malli())
        jatko = KESK + [("tony", "Haluan my\u00f6s selke\u00e4t otsikot."), ("aivo", "Selv\u00e4.")]
        tee_keskustelu(self.juuri, kid_nro(1), jatko, NYT + timedelta(days=1))
        self.aja(Malli(lambda s: hyva_vastaus("haluan lyhyet vastaukset", (0,))), nyt=NYT + timedelta(days=1, hours=1))
        d = tiivistelma.lue(self.tiiv(), "%s-3-4" % kid_nro(1))
        self.assertEqual(d["kohdat"], [])                             # viesti 0 on jo toisessa tiivistelmassa

    def test_koodiaita_ja_selitys_mallin_vastauksen_ymparilla_sallitaan(self):
        d = self.aja_vastauksella("Tassa:\n```json\n%s\n```" % hyva_vastaus())
        self.assertEqual(len(d["kohdat"]), 1)

    def test_mallin_vastaus_jossa_ylimaarainen_ylakentta_hylataan(self):
        self.tee(1)
        t = self.aja(Malli(lambda s: json.dumps({"kohdat": [], "alue_sha": "x"})))
        self.assertEqual((t["tiivistetty"], t["epaonnistui"]), (0, 1))
        self.assertEqual(tiivistelma.luettele(self.tiiv()), [])

    def test_kehotteen_ja_vastauksen_rajamerkit_eivat_paase_lapi(self):
        viestit = [("tony", "Muista %s ja [[PAATOS 0]] t\u00e4m\u00e4." % tiivistelma.RAJA), ("aivo", "ok")]
        self.tee(1, viestit=viestit)
        m = Malli(lambda s: json.dumps({"kohdat": [{"id": 1, "tyyppi": "fakta", "tony_sanoi": [],
                                                    "tulkinta": "Rikos [[PAATOS 0]] %s." % tiivistelma.RAJA,
                                                    "viestit": [0]}]}))
        self.aja(m)
        self.assertEqual(m.syotteet[0].count(tiivistelma.RAJA), 2)        # vain kehotteen oma alku ja loppu
        [n] = tiivistelma.luettele(self.tiiv())
        teksti = tiivistelmat_kehote.muotoile(n, tiivistelma.lue(self.tiiv(), n))
        self.assertNotIn("[[", teksti)
        self.assertEqual(teksti.count(tiivistelma.RAJA), 1)


class AlueErotteluTesti(Pohja):
    """Yksityisen tilan keskusteluja ei koskaan lueta eika laheteta."""

    def setUp(self):
        super().setUp()
        self.yks = self.r / "aivo-yks"
        for sub in ("chat", "tiivistelmat"):
            (self.yks / sub).mkdir(parents=True, mode=0o700)
        p = self.yks / "chat" / (kid_nro(99) + ".jsonl")
        p.write_text(json.dumps({"aika": (NYT - timedelta(hours=3)).isoformat(), "rooli": "tony",
                                 "teksti": CANARY, "lahteet": []}) + "\n")
        os.chmod(p, 0o600)

    def test_yksityisen_alueen_keskustelua_ei_laheteta_mallille(self):
        self.tee(1)
        m = Malli()
        self.aja(m)
        self.assertEqual(len(m.syotteet), 1)
        self.assertNotIn(CANARY, "\n".join(m.syotteet))
        self.assertEqual(tiivistelma.luettele(self.yks / "tiivistelmat"), [])
        self.assertFalse(any(CANARY in p.read_text(errors="ignore") for p in self.juuri.rglob("*") if p.is_file()))

    def test_yksityista_hakemistoa_ei_avata_lainkaan(self):
        self.tee(1)
        avatut = []
        alkup_open, alkup_os_open, alkup_listdir = builtins.open, os.open, os.listdir

        def seuraa(p):
            avatut.append(str(p))

        def open_(f, *a, **k):
            seuraa(f)
            return alkup_open(f, *a, **k)

        def os_open(f, *a, **k):
            seuraa(f)
            return alkup_os_open(f, *a, **k)

        def listdir(f="."):
            seuraa(f)
            return alkup_listdir(f)
        def lukija(s, *a, **k):
            seuraa(s)
            with alkup_open(s, encoding="utf-8") as f:
                return f.read()
        with mock.patch("builtins.open", open_), mock.patch("os.open", os_open), mock.patch("os.listdir", listdir), \
                mock.patch.object(Path, "read_text", lukija):
            self.aja(Malli())
        self.assertTrue(avatut)
        self.assertEqual([p for p in avatut if str(self.yks) in p], [])

    def test_alue_valitsin_hyvaksyy_vain_tyokalun(self):
        for arvo in ("yksityinen", "kaikki", ""):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                tiivista.main(["--alue", arvo, "--kuiva", "--juuri", str(self.juuri)])
            self.assertEqual(e.exception.code, 2)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tiivista.main(["--kuiva", "--juuri", str(self.juuri)])           # --alue on pakollinen

    def test_moduuli_ei_tuo_yksityisen_alueen_moduuleja_eika_nimea_sen_polkuja(self):
        for tiedosto in (tiivista.__file__, tiivistelmat_kehote.__file__):
            puu = ast.parse(Path(tiedosto).read_text(encoding="utf-8"))
            tuodut = set()
            for n in ast.walk(puu):
                if isinstance(n, ast.Import):
                    tuodut |= {a.name for a in n.names}
                elif isinstance(n, ast.ImportFrom):
                    tuodut.add(n.module or "")
                    tuodut |= {"%s.%s" % (n.module, a.name) for a in n.names}
            self.assertEqual([t for t in tuodut if "yksityinen" in t or t.endswith("chat")], [], tiedosto)
            for n in ast.walk(puu):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    for kielletty in ("aivo-yksityinen", "ydinohjeet", "siirrot"):
                        self.assertNotIn(kielletty, n.value)

    def test_alueiden_erottelu_pitaa(self):
        with self.assertRaises(alue.AlueVirhe):                      # yksityinen alue tyokalualueen sisalla hylataan
            alue.tarkista_erottelu(tyokalualue.tyokalualue(self.juuri),
                                   alue.Alue("yksityinen", self.juuri / "x", ("chat",)))


class KehoteRajaTesti(Pohja):
    def tallenna_n(self, n, tulkinta="Tony haluaa lyhyet vastaukset.", aika=None):
        kid = kid_nro(n)
        viestit = [{"rooli": "tony", "teksti": "Haluan lyhyet vastaukset aina.", "aika": aika or "2026-11-10T10:00:00+00:00"}]
        d = {"versio": 1, "keskustelu": kid, "alku": 0, "loppu": 0, "ensimmainen_aika": viestit[0]["aika"],
             "viimeinen_aika": viestit[0]["aika"], "tiivistetty": NYT.isoformat(timespec="seconds"), "malli": "x",
             "alue_sha": tiivistelma.alueen_sha(viestit, 0, 0),
             "kohdat": [{"id": 1, "tyyppi": "mieltymys", "tony_sanoi": ["lyhyet vastaukset"], "tulkinta": tulkinta,
                         "viestit": [0], "tila": "ehdotus"}]}
        tiivistelma.tallenna(self.tiiv(), d, viestit)
        return "%s-0-0" % kid

    def test_tyhja_tai_puuttuva_kansio_antaa_tyhjan(self):
        self.assertEqual(tiivistelmat_kehote.muodosta(self.r / "ei-ole", "x"), ("", []))
        self.a.valmista()
        self.assertEqual(tiivistelmat_kehote.muodosta(self.tiiv(), "x"), ("", []))

    def test_60_kt_raja_pitaa(self):
        self.a.valmista()
        for n in range(1, 400):
            self.tallenna_n(n, tulkinta="T" * 290)
        teksti, mukana = tiivistelmat_kehote.muodosta(self.tiiv(), "lyhyet vastaukset")
        self.assertLessEqual(len(teksti.encode("utf-8")), 60_000)
        self.assertEqual(tiivistelmat_kehote.YLARAJA_TAVUA, 60_000)
        self.assertGreater(len(teksti.encode("utf-8")), 55_000)           # raja todella tayttyy
        self.assertTrue(0 < len(mukana) < 399)

    def test_raja_lasketaan_tavuina_ei_merkkeina(self):
        self.a.valmista()
        for n in range(1, 160):
            self.tallenna_n(n, tulkinta="\u00e4" * 290)                     # 2 tavua / merkki
        teksti, _ = tiivistelmat_kehote.muodosta(self.tiiv(), "x")
        self.assertLessEqual(len(teksti.encode("utf-8")), 60_000)
        self.assertGreater(len(teksti.encode("utf-8")), 50_000)           # raja tayttyi (merkkeja alle 60 000, tavuja ei)

    def test_pieni_ylaraja_ei_ylity(self):
        self.a.valmista()
        for n in range(1, 10):
            self.tallenna_n(n)
        teksti, mukana = tiivistelmat_kehote.muodosta(self.tiiv(), "x", ylaraja=1500)
        self.assertLessEqual(len(teksti.encode("utf-8")), 1500)
        self.assertTrue(mukana)

    def test_hakuun_osuva_ensin_sitten_uusin(self):
        self.a.valmista()
        vanha_osuva = self.tallenna_n(1, tulkinta="Tony pelaa sulkapalloa viikonloppuisin.", aika="2026-11-01T10:00:00+00:00")
        self.tallenna_n(2, tulkinta="Tony juo kahvia.", aika="2026-11-05T10:00:00+00:00")
        uusin = self.tallenna_n(3, tulkinta="Tony lukee kirjaa.", aika="2026-11-16T10:00:00+00:00")
        teksti, mukana = tiivistelmat_kehote.muodosta(self.tiiv(), "milloin pelaan sulkapalloa?")
        self.assertEqual(mukana[0], "tiivistelmat/%s.json" % vanha_osuva)
        self.assertEqual(mukana[1], "tiivistelmat/%s.json" % uusin)
        self.assertLess(teksti.index(vanha_osuva), teksti.index(uusin))

    def test_uusin_ensin_ilman_hakuosumaa(self):
        self.a.valmista()
        self.tallenna_n(1, aika="2026-11-01T10:00:00+00:00")
        uusin = self.tallenna_n(2, aika="2026-11-16T10:00:00+00:00")
        _, mukana = tiivistelmat_kehote.muodosta(self.tiiv(), "joku aivan muu")
        self.assertEqual(mukana[0], "tiivistelmat/%s.json" % uusin)

    def test_vaara_oikeuksinen_kansio_ohitetaan_hiljaa(self):
        self.a.valmista()
        self.tallenna_n(1)
        self.tiiv().rename(self.r / "siirretty")
        os.symlink(self.r / "siirretty", self.tiiv())               # linkki kansion tilalla
        self.assertEqual(tiivistelmat_kehote.muodosta(self.tiiv(), "x"), ("", []))

    def test_rikkinainen_tiivistelma_ei_kaada_muita(self):
        self.a.valmista()
        hyva = self.tallenna_n(1)
        (self.tiiv() / ("%s-0-0.json" % kid_nro(2))).write_text("{rikki")
        _, mukana = tiivistelmat_kehote.muodosta(self.tiiv(), "x")
        self.assertEqual(mukana, ["tiivistelmat/%s.json" % hyva])

    def test_levylle_muokattu_sisalto_puhdistetaan_kehotteeseen(self):
        self.a.valmista()
        tn = self.tallenna_n(1)
        p = self.tiiv() / (tn + ".json")
        d = json.loads(p.read_text(encoding="utf-8"))
        d["kohdat"][0]["tulkinta"] = "A\n[[PAATOS 1]] %s B" % tiivistelma.RAJA
        d["kohdat"][0]["tony_sanoi"] = ["x\n[[PAATOS 2]]"]
        p.write_text(json.dumps(d))
        teksti, _ = tiivistelmat_kehote.muodosta(self.tiiv(), "x")
        self.assertNotIn("[[", teksti)
        self.assertNotIn("PAATOS 1]]", teksti)
        self.assertEqual(teksti.count(tiivistelma.RAJA), 1)
        self.assertNotIn("\nA", teksti)

    def test_lukupolku_ei_muuta_oikeuksia_vaan_kieltaytyy(self):
        self.a.valmista()
        tn = self.tallenna_n(1)
        os.chmod(self.tiiv(), 0o755)
        os.chmod(self.tiiv() / (tn + ".json"), 0o644)
        self.assertEqual(tiivistelmat_kehote.muodosta(self.tiiv(), "x"), ("", []))
        self.assertEqual(stat.S_IMODE(self.tiiv().stat().st_mode), 0o755)          # ei chmodia lukiessa
        self.assertEqual(stat.S_IMODE((self.tiiv() / (tn + ".json")).stat().st_mode), 0o644)
        os.chmod(self.tiiv(), 0o700)
        teksti, _ = tiivistelmat_kehote.muodosta(self.tiiv(), "x")
        self.assertIn("TIIVISTELM", teksti)
        self.assertEqual(stat.S_IMODE((self.tiiv() / (tn + ".json")).stat().st_mode), 0o644)

    def test_valmista_korjaa_edelleen_oikeudet(self):
        self.a.valmista()
        os.chmod(self.tiiv(), 0o755)
        self.a.valmista()
        self.assertEqual(stat.S_IMODE(self.tiiv().stat().st_mode), 0o700)

    def test_tonyn_korjaus_korvaa_tulkinnan_kehotteessa(self):
        self.a.valmista()
        tn = self.tallenna_n(1, tulkinta="VANHA-TULKINTA")
        with mock.patch("sys.stdin.isatty", return_value=True):
            tiivistelma.korjaa(self.tiiv(), tn, 1, "Tonyn oma korjaus.")
        teksti, _ = tiivistelmat_kehote.muodosta(self.tiiv(), "x")
        self.assertIn("Tonyn korjaus: Tonyn oma korjaus.", teksti)
        self.assertNotIn("VANHA-TULKINTA", teksti)


class IndeksiTesti(Pohja):
    def test_indeksi_paivittyy_eika_sisalla_sisaltoa(self):
        self.tee(1)
        self.tee(2)
        self.aja(Malli())
        d = json.loads((self.a.polku("indeksi") / tiivista.INDEKSI_TIEDOSTO).read_text(encoding="utf-8"))
        self.assertEqual(len(d["tiivistelmat"]), 2)
        self.assertEqual(set(d["tiivistelmat"][0]), {"tunnus", "viimeinen_aika", "kohtia"})
        self.assertNotIn("lyhyet", json.dumps(d))
        self.assertEqual(stat.S_IMODE((self.a.polku("indeksi") / tiivista.INDEKSI_TIEDOSTO).stat().st_mode), 0o600)


class SocketTesti(unittest.TestCase):
    def palvele(self, vastaus, tulos):
        d = tempfile.mkdtemp()
        polku = os.path.join(d, "s.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(polku)
        srv.listen(1)

        def kasittele():
            c, _ = srv.accept()
            osat = []
            while True:
                x = c.recv(65536)
                if not x:
                    break
                osat.append(x)
            tulos.append(b"".join(osat))
            c.sendall(vastaus)
            c.close()
            srv.close()
        threading.Thread(target=kasittele, daemon=True).start()
        self.addCleanup(lambda: [os.unlink(polku), os.rmdir(d)] if os.path.exists(polku) else None)
        return polku

    def test_onnistunut_kutsu(self):
        saatu = []
        polku = self.palvele(b"vastaus\n\x00AIVO-EXIT 0\n", saatu)
        self.assertEqual(tiivista.kysy_socketista(polku, "syote \u00e4"), "vastaus")
        self.assertEqual(saatu[0].decode("utf-8"), "syote \u00e4")

    def test_nollasta_poikkeava_paluukoodi_ja_puuttuva_paatosrivi_ovat_virheita(self):
        for vastaus in (b"x\x00AIVO-EXIT 2\n", b"ilman paatosrivia"):
            polku = self.palvele(vastaus, [])
            with self.assertRaises(tiivista.TiivistaVirhe):
                tiivista.kysy_socketista(polku, "s")

    def test_puuttuva_socket_on_virhe_ilman_polkua_viestissa(self):
        with self.assertRaises(tiivista.TiivistaVirhe) as e:
            tiivista.kysy_socketista("/ei/ole/socketia", "s")
        self.assertNotIn("/ei/ole", str(e.exception))


class CliTesti(Pohja):
    def test_ilman_socketia_ei_ajeta_mallikutsua(self):
        self.tee(1)
        with redirect_stderr(io.StringIO()) as err:
            rc = tiivista.main(["--alue", "tyokalu", "--juuri", str(self.juuri)], env={})
        self.assertEqual(rc, 1)
        self.assertIn("AIVO_TYOKALU_SOCKET", err.getvalue())
        self.assertEqual(tiivistelma.luettele(self.tiiv()), [])

    def test_kuiva_ei_vaadi_socketia(self):
        self.tee(1, hiljaa_min=60)
        with redirect_stdout(io.StringIO()) as ulos:
            rc = tiivista.main(["--alue", "tyokalu", "--juuri", str(self.juuri), "--kuiva"], env={})
        self.assertEqual(rc, 0)
        self.assertIn("tiivistettaisiin", ulos.getvalue())

    def test_kysy_parametri_ohittaa_socketin(self):
        self.tee(1)
        m = Malli()
        with redirect_stdout(io.StringIO()):
            rc = tiivista.main(["--alue", "tyokalu", "--juuri", str(self.juuri)], kysy=m, env={})
        self.assertEqual((rc, len(m.syotteet)), (0, 1))

    def test_virhe_tulostaa_vain_tyypin_nimen(self):
        with mock.patch("aivo.tiivista_tyokalu.aja", side_effect=KeyError("SALAINEN-ARVO")), redirect_stderr(io.StringIO()) as err:
            rc = tiivista.main(["--alue", "tyokalu", "--juuri", str(self.juuri), "--kuiva"], env={})
        self.assertEqual(rc, 1)
        self.assertIn("KeyError", err.getvalue())
        self.assertNotIn("SALAINEN", err.getvalue())


class ChatKytkentaTesti(unittest.TestCase):
    """Tiivistelmat kulkevat tyokalutilan kehotteeseen kirjaston rinnalle, mutta eivat koskaan yksityiseen tilaan."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = Path(cls.tmp.name)
        (r / "kirjasto").mkdir()
        (r / "kirjasto" / "faktat.md").write_text("KIRJASTON-FAKTA")
        (r / "yks" / "muisti").mkdir(parents=True)
        (r / "yks" / "ydin").mkdir()
        (r / "yks" / "ydin" / "saannot.md").write_text("YDIN")
        a = tyokalualue.tyokalualue(r / "aivo")
        a.valmista()
        kid = kid_nro(5)
        viestit = [{"rooli": "tony", "teksti": "Haluan lyhyet vastaukset aina.", "aika": "2026-11-10T10:00:00+00:00"}]
        d = {"versio": 1, "keskustelu": kid, "alku": 0, "loppu": 0, "ensimmainen_aika": viestit[0]["aika"],
             "viimeinen_aika": viestit[0]["aika"], "tiivistetty": "2026-11-10T11:00:00+00:00", "malli": "x",
             "alue_sha": tiivistelma.alueen_sha(viestit, 0, 0),
             "kohdat": [{"id": 1, "tyyppi": "mieltymys", "tony_sanoi": ["lyhyet vastaukset"],
                         "tulkinta": "TIIVISTELMAN-TULKINTA", "viestit": [0], "tila": "ehdotus"}]}
        tiivistelma.tallenna(a.polku("tiivistelmat"), d, viestit)
        cls.tn = "tiivistelmat/%s-0-0.json" % kid
        cls.claude, cls.yks = [], []

        def kysy(muisti, historia):
            cls.claude.append(muisti)
            return "Vastaus [l\u00e4hde: %s] [l\u00e4hde: faktat.md]." % cls.tn

        def kysy_yks(muisti, historia, ohjeet):
            cls.yks.append(muisti + ohjeet)
            return "yksityinen vastaus"
        cls.tila = chat.Tila(chat.tiivista_salasana(SAL), str(r / "kirjasto"), str(r / "data"), [".ts" + ".net"],
                             kysy=kysy, yks_data=str(r / "yks" / "chat"), yks_muisti=str(r / "yks" / "muisti"),
                             ydinohjeet=str(r / "yks" / "ydin"), ehdotukset=str(r / "yks" / "ehd"), kysy_yks=kysy_yks,
                             tiivistelmat=str(a.polku("tiivistelmat")))
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

    def test_tyokalutila_saa_tiivistelmat_ja_lahde_tunnistetaan(self):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": "tyokalu"})
        s, v = self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": "mit\u00e4 tied\u00e4t vastausten pituudesta?"})
        self.assertEqual(s, 200)
        muisti = self.claude[-1]
        self.assertIn("KIRJASTON-FAKTA", muisti)                    # olemassa oleva muisti ennallaan
        self.assertIn("TIIVISTELMAN-TULKINTA", muisti)
        self.assertIn("Tony sanoi: \"lyhyet vastaukset\"", muisti)
        self.assertEqual(v["tuntemattomia_lahteita"], 0)             # tiivistelman nimi kelpaa lahteeksi

    def test_yksityinen_tila_ei_saa_tyokalutilan_tiivistelmia(self):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {})
        s, _ = self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": "lyhyet vastaukset?"})
        self.assertEqual(s, 200)
        self.assertNotIn("TIIVISTELMAN-TULKINTA", self.yks[-1])

    def test_ilman_tiivistelmakansiota_kaikki_toimii_kuten_ennen(self):
        tila = chat.Tila(chat.tiivista_salasana(SAL), self.tila.kirjasto, self.tila.keskustelut.data.as_posix(), [".ts" + ".net"],
                         kysy=lambda m, h: "ok")
        self.assertIsNone(tila.tiivistelmat)


if __name__ == "__main__":
    unittest.main()
