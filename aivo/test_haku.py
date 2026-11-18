"""Testit aivo/haku.py:lle (stdlib unittest). Ei verkkoa, ei mallikutsua, ei alaprosesseja."""
import ast
import io
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from aivo import haku, tiivistelma
from aivo.alue import Alue
from aivo.tyokalualue import ALIKANSIOT as TYOKALU_ALIKANSIOT
from aivo.yksityinen_alue import ALIKANSIOT as YKSITYINEN_ALIKANSIOT


def _kid(n):
    return "20261114-%06d-%08x" % (n, 0xA0000000 + n)


def tee_tiivistelma(alue, n, lainaus, tulkinta):
    """Tallentaa alueelle oikean, jasennetyn tiivistelman keksitysta keskustelusta. Palauttaa tunnuksen."""
    viestit = [{"rooli": "tony", "teksti": "Tony: " + lainaus, "aika": "2026-11-14T10:15:00+00:00"}]
    raaka = {
        "versio": 1, "keskustelu": _kid(n), "alku": 0, "loppu": 0,
        "ensimmainen_aika": viestit[0]["aika"], "viimeinen_aika": viestit[0]["aika"],
        "tiivistetty": "2026-11-14T11:00:00+00:00", "malli": "testimalli",
        "alue_sha": tiivistelma.alueen_sha(viestit, 0, 0),
        "kohdat": [{"id": 1, "tyyppi": "fakta", "tony_sanoi": [lainaus], "tulkinta": tulkinta,
                    "viestit": [0], "tila": "voimassa"}],
    }
    return tiivistelma.tallenna(alue.polku("tiivistelmat"), raaka, viestit)


class _Pohja(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        juuri = Path(self._tmp.name)
        self.tyokalu = Alue("tyokalu", juuri / "tyokalu", TYOKALU_ALIKANSIOT)
        self.yksityinen = Alue("yksityinen", juuri / "yksityinen", YKSITYINEN_ALIKANSIOT)
        self.tyokalu.valmista()
        self.yksityinen.valmista()


class AluerajaTesti(_Pohja):
    def test_kanaria_yksityisesta_ei_loydy_tyokalualueen_haulla(self):
        kanaria = "kanariasana"
        tee_tiivistelma(self.yksityinen, 1, "salainen %s on tarkea" % kanaria, "Yksityinen asia.")
        tee_tiivistelma(self.tyokalu, 2, "julkinen paatos koskee tyokalua", "Tyokalun paatos.")
        haku.rakenna(self.yksityinen)
        haku.rakenna(self.tyokalu)
        self.assertEqual([t["tunnus"] for t in haku.hae(self.yksityinen, kanaria)], [_kid(1) + "-0-0"])
        self.assertEqual(haku.hae(self.tyokalu, kanaria), [])
        self.assertEqual([t["tunnus"] for t in haku.hae(self.tyokalu, "tyokalun paatos")], [_kid(2) + "-0-0"])
        self.assertEqual(haku.hae(self.yksityinen, "tyokalun paatos"), [])

    def test_indeksit_ovat_eri_tiedostoja_eika_toisen_sana_ole_toisen_indeksissa(self):
        tee_tiivistelma(self.yksityinen, 1, "kanariasana yksityisessa", "Yksityinen.")
        tee_tiivistelma(self.tyokalu, 2, "toinenkanaria tyokalussa", "Tyokalu.")
        haku.rakenna(self.yksityinen)
        haku.rakenna(self.tyokalu)
        pa, pb = haku.indeksin_polku(self.yksityinen), haku.indeksin_polku(self.tyokalu)
        self.assertNotEqual(pa, pb)
        for polku, sana, ei_sana in ((pa, "kanari", "toinen"), (pb, "toinen", "kanari")):
            db = sqlite3.connect(str(polku))
            try:
                teksti = " ".join(r[0] for r in db.execute("select teksti from pala"))
            finally:
                db.close()
            self.assertIn(sana, teksti)
            self.assertNotIn(ei_sana, teksti)

    def test_erikoismerkit_eivat_ohita_aluerajaa(self):
        tee_tiivistelma(self.yksityinen, 1, "kanariasana salainen", "Yksityinen.")
        tee_tiivistelma(self.tyokalu, 2, "julkinen asia", "Tyokalu.")
        haku.rakenna(self.yksityinen)
        haku.rakenna(self.tyokalu)
        for kysely in ('kanariasana', 'kanariasana*', '"kanariasana"', 'tunnus:* OR kanariasana', 'NOT julkinen OR kanariasana',
                       '{teksti}: kanari*', "x') OR 1=1 --", 'NEAR(kanariasana julkinen)', 'pala:kanariasana'):
            with self.subTest(kysely=kysely):
                self.assertEqual([t for t in haku.hae(self.tyokalu, kysely) if t["tunnus"].startswith(_kid(1))], [])


class ErikoismerkkiTesti(_Pohja):
    def setUp(self):
        super().setUp()
        tee_tiivistelma(self.tyokalu, 1, "kaytamme tietokantana postgresia", "Tietokanta on postgres.")
        haku.rakenna(self.tyokalu)

    def test_fts5_erikoismerkit_eivat_kaada_hakua(self):
        for kysely in ('"', '""', '"""', "'", "*", "**", "^", "(", ")", "()", ":", "a:b", "AND", "OR", "NOT", "NEAR(", "NEAR/2",
                       "-", "+", "{", "}", "\\", "%", ";", "--", "/*", "\x00", "\n", "\t", "\u202e", "postgres\"", "(postgres",
                       'postgres" OR "', "col:postgres", "postgres*", "- postgres", "NOT postgres", "postgres AND"):
            with self.subTest(kysely=kysely):
                tulos = haku.hae(self.tyokalu, kysely)
                self.assertIsInstance(tulos, list)

    def test_lainausmerkit_syotteessa_eivat_rikko_osumaa(self):
        self.assertEqual(len(haku.hae(self.tyokalu, 'tietokantana "postgresia" "')), 1)

    def test_tyhja_ja_vain_valimerkkeja_sisaltava_kysely_palauttaa_tyhjan(self):
        for kysely in ("", "   ", "***", '"" ""', "!?"):
            self.assertEqual(haku.hae(self.tyokalu, kysely), [])

    def test_erikoismerkkeja_sisaltava_teksti_indeksoituu_ja_loytyy(self):
        tee_tiivistelma(self.tyokalu, 2, 'sanoi: "NEAR(a b)" ja AND * OR', "Sisaltaa erikoismerkkeja.")
        haku.rakenna(self.tyokalu)
        self.assertEqual(len(haku.hae(self.tyokalu, "sisaltaa erikoismerkkeja")), 1)

    def test_virheellinen_k_hylataan(self):
        for k in (0, -1, 51, True, "5", None):
            with self.subTest(k=k):
                with self.assertRaises(haku.HakuVirhe):
                    haku.hae(self.tyokalu, "postgres", k)


class IndeksiTesti(_Pohja):
    def test_puuttuva_indeksi_palauttaa_tyhjan(self):
        self.assertEqual(haku.hae(self.tyokalu, "mikatahansa"), [])

    def test_tyhja_indeksi(self):
        self.assertEqual(haku.rakenna(self.tyokalu), (0, 0))
        self.assertTrue(haku.indeksin_polku(self.tyokalu).is_file())
        self.assertEqual(haku.hae(self.tyokalu, "mikatahansa"), [])

    def test_uudelleenrakennus_on_idempotentti_ja_paivittaa_sisallon(self):
        tunnus = tee_tiivistelma(self.tyokalu, 1, "ensimmainen asia vanhasana", "Vanha.")
        self.assertEqual(haku.rakenna(self.tyokalu), (1, 1))
        self.assertEqual(haku.rakenna(self.tyokalu), (1, 1))
        self.assertEqual(len(haku.hae(self.tyokalu, "vanhasana")), 1)
        tiivistelma.poista(self.tyokalu.polku("tiivistelmat"), tunnus)
        tee_tiivistelma(self.tyokalu, 2, "toinen asia uusisana", "Uusi.")
        haku.rakenna(self.tyokalu)
        self.assertEqual(haku.hae(self.tyokalu, "vanhasana"), [])
        self.assertEqual([t["tunnus"] for t in haku.hae(self.tyokalu, "uusisana")], [_kid(2) + "-0-0"])

    def test_poistettu_tiivistelma_ei_jaa_indeksiin_rakennuksen_jalkeen(self):
        tunnus = tee_tiivistelma(self.tyokalu, 1, "poistettava kanariasana", "X.")
        haku.rakenna(self.tyokalu)
        self.assertEqual(len(haku.hae(self.tyokalu, "kanariasana")), 1)
        tiivistelma.poista(self.tyokalu.polku("tiivistelmat"), tunnus)
        haku.rakenna(self.tyokalu)
        self.assertEqual(haku.hae(self.tyokalu, "kanariasana"), [])

    def test_indeksi_on_0600_eika_valiaikaisia_tiedostoja_jaa(self):
        tee_tiivistelma(self.tyokalu, 1, "jokin asia", "Y.")
        haku.rakenna(self.tyokalu)
        kansio = self.tyokalu.polku("indeksi")
        self.assertEqual(os.listdir(kansio), [haku.INDEKSI_NIMI])
        self.assertEqual(stat.S_IMODE(os.stat(haku.indeksin_polku(self.tyokalu)).st_mode), 0o600)

    def test_rikkinainen_tiivistelma_ohitetaan(self):
        tee_tiivistelma(self.tyokalu, 1, "hyva kanariasana", "Z.")
        (self.tyokalu.polku("tiivistelmat") / (_kid(9) + "-0-0.json")).write_text("{ei json", encoding="utf-8")
        self.assertEqual(haku.rakenna(self.tyokalu), (1, 1))

    def test_tulos_sisaltaa_lahdeviitteen_tunnuksen(self):
        tunnus = tee_tiivistelma(self.tyokalu, 1, "viitattava asia", "V.")
        haku.rakenna(self.tyokalu)
        self.assertEqual(haku.hae(self.tyokalu, "viitattava")[0]["tunnus"], tunnus)
        tiivistelma.lue(self.tyokalu.polku("tiivistelmat"), tunnus)   # tunnus kelpaa sellaisenaan lahteeksi

    def test_yksi_tulos_per_tiivistelma_ja_k_rajaa_maaran(self):
        for n in range(1, 8):
            tee_tiivistelma(self.tyokalu, n, "yhteinen hakusana numero %d" % n, "Yhteinen.")
        haku.rakenna(self.tyokalu)
        self.assertEqual(len(haku.hae(self.tyokalu, "yhteinen hakusana", 3)), 3)
        tunnukset = [t["tunnus"] for t in haku.hae(self.tyokalu, "yhteinen hakusana", 50)]
        self.assertEqual(len(tunnukset), 7)
        self.assertEqual(len(set(tunnukset)), 7)


class PilkontaTesti(unittest.TestCase):
    def test_pitka_teksti_pilkotaan_rajoihin_eika_sana_halkea(self):
        sanat = ["sana%d" % i for i in range(1000)]
        paloja = haku.pilko(" ".join(sanat))
        self.assertGreater(len(paloja), 3)
        self.assertTrue(all(len(p) <= haku.PALA_MAX for p in paloja))
        self.assertTrue(all(len(p) >= haku.PALA_MIN for p in paloja[:-1]))
        self.assertEqual(" ".join(paloja).split(), sanat)

    def test_lyhyt_ja_tyhja_teksti(self):
        self.assertEqual(haku.pilko("lyhyt teksti"), ["lyhyt teksti"])
        self.assertEqual(haku.pilko(""), [])
        self.assertEqual(haku.pilko("   \n "), [])

    def test_ylipitka_sana_leikataan(self):
        paloja = haku.pilko("a" * 4000)
        self.assertTrue(all(len(p) <= haku.PALA_MAX for p in paloja))
        self.assertEqual("".join(paloja), "a" * 4000)

    def test_pitkan_tekstin_loppuosa_on_haettavissa(self):
        with tempfile.TemporaryDirectory() as d:
            alue = Alue("tyokalu", Path(d) / "a", TYOKALU_ALIKANSIOT)
            alue.valmista()
            pitka = " ".join("taytesana%d" % i for i in range(300)) + " loppukanaria"
            tee_tiivistelma(alue, 1, pitka[:480].rsplit(" ", 1)[0], pitka[:290].rsplit(" ", 1)[0])
            haku.rakenna(alue)
            self.assertEqual(len(haku.hae(alue, "taytesana3")), 1)


class VartaloTesti(unittest.TestCase):
    def test_taivutus_siedetaan(self):
        self.assertEqual(haku.sanat("Tietokannassa TIETOKANTA"), ["tietok", "tietok"])
        self.assertEqual(haku.sanat("kayttajan, kayttajalle"), ["kaytta", "kaytta"])


# --- Synteettinen recall@5 -----------------------------------------------------------------------

# (lainaus, tulkinta, kysymys). Kysymyksessa on taivutettuja muotoja eika samoja sanoja kuin tiivistelmassa.
AINEISTO = [
    ("haluan kayttaa postgres tietokantaa kaikissa projekteissa", "Tietokantavalinta: postgres.", "Mita tietokantaa Tony halusi kayttavansa?"),
    ("deploy tehdaan aina perjantaisin iltapaivalla", "Julkaisupaiva on perjantai.", "Milloin julkaisuja tehtiin?"),
    ("en halua pitkia listoja vastauksiin", "Lyhyet vastaukset ovat suositumpia.", "Millaisia vastauksia Tony toivoi listoista?"),
    ("tallennetaan salasanat vain holviin", "Salaisuudet kuuluvat holviin.", "Mihin salasanoja saa tallentaa?"),
    ("ajastus tehdaan systemd timerilla eika cronilla", "Ajastus: systemd timer.", "Millaisella ajastimella ajot ajastetaan?"),
    ("opiskelen ohjelmistokehittajaksi taitotalossa", "Tony opiskelee ohjelmistokehitysta.", "Missa Tony opiskelee ohjelmistokehittajaksi?"),
    ("testit kirjoitetaan unittestilla ilman lisariippuvuuksia", "Testikirjasto: unittest.", "Millaisilla kirjastoilla testeja kirjoitetaan?"),
    ("kuukauden budjetti mallikutsuille on viisikymmenta euroa", "Mallikutsujen kuukausibudjetti 50 euroa.", "Paljonko mallikutsujen budjetti kuukaudessa on?"),
    ("portfolioon tulee kolme repoa syksyn aikana", "Portfolion tavoite: kolme repoa.", "Montako repoa portfolioon suunniteltiin?"),
    ("telegram-ilmoitukset vain maanantaisin aamulla", "Telegram-ilmoitus maanantaiaamuna.", "Mihin aikaan Telegramiin ilmoitetaan maanantaina?"),
]
HAJOTTAJAT = [
    ("lounas syodaan yleensa puoli kahdentoista aikoihin", "Lounasaika."),
    ("kissa nukkuu sohvalla koko paivan", "Kissan nukkuminen."),
    ("matkustus tapahtuu junalla pohjoiseen", "Matkustussuunnitelma."),
    ("kahvi juodaan mustana ilman sokeria", "Kahvimieltymys."),
    ("kuntosalille mennaan kolmesti viikossa", "Liikuntatottumus."),
    ("auto huolletaan kevaalla renkaiden vaihdon yhteydessa", "Auton huolto."),
    ("kirjaston kirjat palautetaan kuun lopussa", "Kirjastolainat."),
    ("lamppu keittiossa vaihdetaan led-versioon", "Valaistus."),
    ("sunnuntaisin soitetaan isovanhemmille", "Perhesoitto."),
    ("musiikki kuunnellaan kuulokkeilla iltaisin", "Musiikkitottumus."),
]


def recall_at_5(alue):
    for n, (lain, tulk, _) in enumerate(AINEISTO, start=1):
        tee_tiivistelma(alue, n, lain, tulk)
    for n, (lain, tulk) in enumerate(HAJOTTAJAT, start=100):
        tee_tiivistelma(alue, n, lain, tulk)
    haku.rakenna(alue)
    osumia = 0
    for n, (_, _, kysymys) in enumerate(AINEISTO, start=1):
        if _kid(n) + "-0-0" in [t["tunnus"] for t in haku.hae(alue, kysymys, 5)]:
            osumia += 1
    return osumia, len(AINEISTO)


class RecallTesti(_Pohja):
    def test_synteettinen_recall_at_5(self):
        osumia, yht = recall_at_5(self.tyokalu)
        print("\nsynteettinen recall@5: %d/%d = %.2f" % (osumia, yht, osumia / yht))
        self.assertGreaterEqual(osumia / yht, 0.8)


class CliTesti(_Pohja):
    def test_rakenna_ja_hae_cli_ja_virheet_eivat_vuoda(self):
        tunnus = tee_tiivistelma(self.tyokalu, 1, "cli kanariasana", "C.")
        ulos, virhe = io.StringIO(), io.StringIO()
        with redirect_stdout(ulos), redirect_stderr(virhe):
            self.assertEqual(haku.main(["rakenna", "--alue", "tyokalu", "--juuri", str(self.tyokalu.juuri)]), 0)
            self.assertEqual(haku.main(["hae", "--alue", "tyokalu", "--juuri", str(self.tyokalu.juuri), "--k", "5",
                                        'kanariasana "']), 0)
            self.assertEqual(haku.main(["hae", "--alue", "tyokalu", "--juuri", str(self.tyokalu.juuri), "--k", "0", "x"]), 1)
        self.assertIn(tunnus, ulos.getvalue())
        self.assertNotIn("Traceback", virhe.getvalue())


class RakenneTesti(unittest.TestCase):
    def test_moduuli_ei_tuo_verkkoa_alaprosesseja_eika_viittaa_mallipalveluihin(self):
        puu = ast.parse((Path(__file__).parent / "haku.py").read_text(encoding="utf-8"))
        tuodut = set()
        for n in ast.walk(puu):
            if isinstance(n, ast.Import):
                tuodut |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                tuodut.add(n.module.split(".")[0])
        self.assertFalse(tuodut & {"subprocess", "socket", "urllib", "http", "requests", "os.system"}, tuodut)
        nimet = {n.id.lower() for n in ast.walk(puu) if isinstance(n, ast.Name)}
        nimet |= {n.attr.lower() for n in ast.walk(puu) if isinstance(n, ast.Attribute)}
        for kielletty in ("openrouter", "litellm", "kysy_claudelta", "urlopen"):
            self.assertNotIn(kielletty, nimet)

    def test_chat_ja_kehote_eivat_tuo_hakua_viela(self):
        for nimi in ("chat.py", "tyokalu_kaares.py", "yksityinen.py", "tiivistelma.py"):
            puu = ast.parse((Path(__file__).parent / nimi).read_text(encoding="utf-8"))
            for n in ast.walk(puu):
                if isinstance(n, ast.Import):
                    kohteet = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    kohteet = [(n.module or "")] + [a.name for a in n.names]
                else:
                    continue
                self.assertFalse(any(k.split(".")[-1] == "haku" for k in kohteet), nimi)


if __name__ == "__main__":
    unittest.main()
