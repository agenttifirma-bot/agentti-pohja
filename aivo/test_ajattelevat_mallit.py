"""Testit: ajattelevan mallin tyhja vastaus (paattely kulutti max_tokens-rajan, finish_reason "length").
Mallivertailu (aja, itse-aja, kokoaja), pisteytys ("ei vastausta" omana luokkanaan) ja tuotanto (yksityinen_or,
taustaajo). Ei verkkoa eika oikeita avaimia: kuljetin on feikki ja kulukirjanpito tilapainen."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aivo import itsetuntemus as it, mallivertailu as mv, openrouter_kulut as ok, openrouter_zdr, taustaajo
from aivo import yksityinen, yksityinen_or as yo

AJATTELEVA = "qwen/qwen3.5-397b-a17b"
TAVALLINEN = mv.NYKYINEN                         # qwen3-235b-a22b-2507 (instruct), ei listalla
AVAIN = "sk-testi-" + "x" * 30                   # keksitty, ei oikea avain
NYT = datetime(2026, 11, 25, 12, 0, tzinfo=ok.TZ)
# Tonyn 25.11. pyytamat mallit uusintaajoon (A1110)
UUSINTA = ("qwen/qwen3-235b-a22b-2507", "deepseek/deepseek-chat-v3.1", "qwen/qwen3.8-2.4t-a95b",
           "qwen/qwen3.5-397b-a17b", "deepseek/deepseek-r1-0528", "qwen/qwen3-235b-a22b-thinking-2507",
           "meta-llama/llama-4-maverick", "mistralai/mistral-small-2603")


def or_vastaus(content="Vastaus.", finish="stop", paattely=None, perustelu=None, kulu=0.002):
    """OpenRouterin vastauksen muoto (docs/use-cases/reasoning-tokens): message.reasoning ja
    usage.completion_tokens_details.reasoning_tokens."""
    viesti = {"role": "assistant", "content": content}
    if perustelu is not None:
        viesti["reasoning"] = perustelu
    kaytto = {"cost": kulu, "prompt_tokens": 1000, "completion_tokens": 800}
    if paattely is not None:
        kaytto["completion_tokens_details"] = {"reasoning_tokens": paattely}
    return {"choices": [{"message": viesti, "finish_reason": finish}], "usage": kaytto, "provider": "Feikki"}


TYHJA_AJATTELU = dict(content="", finish="length", paattely=800, perustelu="mietin...")


def tehdas(rungot, vastaus_mallille):
    def t():
        def laheta(runko):
            rungot.append(runko)
            return vastaus_mallille(runko)
        return laheta
    return t


class Tilapainen(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.d = Path(self._d.name)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)
        self.ulos = self.d / "ulos"
        self.loki = []


class ListaTesti(unittest.TestCase):
    def test_lista_vain_tunnettuja_malleja(self):
        for m in mv.AJATTELEVAT_MALLIT:
            self.assertTrue(m in openrouter_zdr.AVOIMET_MALLIT or m in mv.EHDOKKAAT, m)
        self.assertIn(AJATTELEVA, mv.AJATTELEVAT_MALLIT)            # havaittu 25.11.
        self.assertNotIn(TAVALLINEN, mv.AJATTELEVAT_MALLIT)

    def test_uusinnan_mallit_kelpaavat(self):
        self.assertEqual(mv.itse_mallit(list(UUSINTA)), list(UUSINTA))
        mv.itse_yhdistelma(list(UUSINTA[:3]), 3, AJATTELEVA)
        mv.itse_yhdistelma(list(UUSINTA[:5]), 5, AJATTELEVA)

    def test_rajat_ennallaan(self):
        self.assertEqual(mv.ITSE_MAX_TOKENIA, 800)
        self.assertEqual(mv.MAX_TOKENIA, 700)
        self.assertEqual(mv.AJATTELU_MAX_TOKENIA, yo.MAX_TOKENIA)
        self.assertEqual(mv.ITSE_KULURAJA_USD, 3.0)
        self.assertEqual(mv.KULURAJA_USD, 3.0)
        self.assertEqual(ok.PAIVAKATTO_EUR, 10)

    def test_vastauksen_tiedot(self):
        t = mv.vastauksen_tiedot(or_vastaus(**TYHJA_AJATTELU))
        self.assertEqual(t, {"vastaus": "", "finish_reason": "length", "tyhja": True, "ajatteli": True,
                             "tokenit_paattely": 800})
        self.assertNotIn("mietin", json.dumps(t))                    # paattelyn tekstia ei tallenneta
        t = mv.vastauksen_tiedot(or_vastaus(content=None, finish="length"))
        self.assertEqual((t["vastaus"], t["tyhja"], t["ajatteli"]), ("", True, False))
        t = mv.vastauksen_tiedot(or_vastaus(content=" Hei. "))
        self.assertEqual((t["vastaus"], t["tyhja"], t["finish_reason"], t["tokenit_paattely"]), ("Hei.", False, "stop", None))


class ItseAjoTesti(Tilapainen):
    def aja(self, mallit, vastaus, **kw):
        rungot = []
        yv = mv.aja_itsetuntemus(mallit, self.ulos, tehdas(rungot, vastaus), kulutila=str(self.kulut),
                                 loki=self.loki.append, **kw)
        return yv, rungot, it.lue_vastaukset(self.ulos)

    def test_ajatteleva_saa_tuotannon_rajan_ilman_reasoning_parametria(self):
        _, rungot, _ = self.aja([TAVALLINEN, AJATTELEVA], lambda r: or_vastaus())
        rajat = {r["model"]: r["max_tokens"] for r in rungot}
        self.assertEqual(rajat, {TAVALLINEN: mv.ITSE_MAX_TOKENIA, AJATTELEVA: yo.MAX_TOKENIA})
        for r in rungot:
            self.assertNotIn("reasoning", r)                          # sama kuin tuotannossa
            self.assertEqual(r["provider"], {"zdr": True, "data_collection": "deny"})

    def test_tyhja_vastaus_kirjataan_riville_ja_on_ei_vastausta(self):
        n = len(it.lue_kysymykset()["kysymykset"])
        yv, _, rivit = self.aja([AJATTELEVA], lambda r: or_vastaus(**TYHJA_AJATTELU))
        self.assertEqual(len(rivit), n)
        for r in rivit:
            self.assertEqual((r["vastaus"], r["tyhja"], r["finish_reason"], r["ajatteli"]), ("", True, "length", True))
            self.assertNotIn("virhe", r)
            self.assertEqual(r["kulu_usd"], 0.002)                    # paattely laskutetaan silti
        self.assertEqual(yv["ei_vastausta"], n)
        self.assertEqual(yv["virheita"], 0)
        self.assertEqual(yv["ajattelevat_listan_ulkopuolella"], [])
        self.assertIn("tyhja (length)", self.loki[0])
        t = it.pisteet(rivit)[AJATTELEVA]
        self.assertEqual(t["luokat"]["ei_vastausta"], n)
        self.assertEqual(t["luokat"]["vaarin"], 0)                    # 25.11.: 33 x "vaarin"
        self.assertIsNone(t["yhteensa"])
        rivi = [x for x in it.taulukko({AJATTELEVA: t}).splitlines() if x.startswith("| " + AJATTELEVA)][0]
        self.assertIn("| - |", rivi)
        self.assertIn("| %d |" % n, rivi)

    def test_ei_vastausta_ei_laske_pisteita(self):
        rivit = [{"malli": "a", "kysymys": "U01", "vastaus": "En tied\u00e4."},
                 {"malli": "a", "kysymys": "U02", "vastaus": "", "tyhja": True},
                 {"malli": "a", "kysymys": "R04", "virhe": "TimeoutError"}]
        t = it.pisteet(rivit)["a"]
        self.assertEqual((t["luokat"]["ei_vastausta"], t["luokat"]["vaarin"], t["luokat"]["en_tieda_oikein"]), (1, 1, 1))
        self.assertEqual(t["yhteensa"], 0.5)                          # (1 + 0) / 2: tyhja ei ole mukana

    def test_listan_ulkopuolinen_ajatteleva_nakyy_yhteenvedossa(self):
        yv, _, _ = self.aja([TAVALLINEN], lambda r: or_vastaus(**TYHJA_AJATTELU))
        self.assertEqual(yv["ajattelevat_listan_ulkopuolella"], [TAVALLINEN])
        ajo = json.loads((self.ulos / "ajo.json").read_text(encoding="utf-8"))
        self.assertEqual(ajo["ajattelevat_listan_ulkopuolella"], [TAVALLINEN])

    def test_kuluarvio_kayttaa_mallikohtaista_rajaa(self):
        n = len(it.lue_kysymykset()["kysymykset"])
        a = mv.itse_kuluarvio([TAVALLINEN, AJATTELEVA])
        self.assertEqual(a["tokenit_ulos_enintaan"][AJATTELEVA], n * yo.MAX_TOKENIA)
        self.assertIn("ajattelevat mallit", mv.itse_arvioteksti(a))
        k = mv.itse_kuluarvio([TAVALLINEN, "deepseek/deepseek-chat-v3.1", "meta-llama/llama-4-maverick"],
                              kokoaja=AJATTELEVA)
        self.assertEqual(k["ylaraja_usd_per_malli"]["kokoaja " + AJATTELEVA],
                         float(ok.arvioi_usd(AJATTELEVA, k["tokenit_sisaan_kokoaja"], n * yo.MAX_TOKENIA)))


class KokoajaTesti(ItseAjoTesti):
    JASENET = [TAVALLINEN, "deepseek/deepseek-chat-v3.1", "meta-llama/llama-4-maverick"]

    @staticmethod
    def on_kokoaja(runko):
        return "kokoaja" in runko["messages"][0]["content"]

    def test_kokoajan_tyhja_vastaus_on_ei_vastausta(self):
        yv, rungot, rivit = self.aja(self.JASENET, lambda r: or_vastaus(**TYHJA_AJATTELU) if self.on_kokoaja(r)
                                     else or_vastaus("J\u00e4sen."), kokoaja=AJATTELEVA)
        kokoajalle = [r for r in rungot if self.on_kokoaja(r)]
        self.assertTrue(kokoajalle)
        self.assertEqual({r["max_tokens"] for r in kokoajalle}, {yo.MAX_TOKENIA})
        for r in rivit:
            self.assertEqual((r["vastaus"], r["tyhja"], r["finish_reason"]), ("", True, "length"))
            self.assertNotIn("virhe", r)
        nimi = mv.itse_yhdistelman_nimi(self.JASENET, AJATTELEVA)
        t = it.pisteet(rivit)[nimi]
        self.assertEqual(t["luokat"]["ei_vastausta"], len(rivit))
        self.assertEqual(t["luokat"]["vaarin"], 0)
        ajo = json.loads((self.ulos / "ajo-yhdistelma-3.json").read_text(encoding="utf-8"))
        self.assertEqual(ajo["ei_vastausta"], len(rivit))
        self.assertEqual(ajo["jasenten_tyhjat"], 0)

    def test_jasenen_tyhja_vastaus_ei_mene_kokoajalle(self):
        def vastaa(r):
            if self.on_kokoaja(r):
                return or_vastaus("Lopullinen.")
            if r["model"] == TAVALLINEN:
                return or_vastaus(**TYHJA_AJATTELU)
            return or_vastaus("J\u00e4sen %s." % r["model"][:3])
        yv, rungot, rivit = self.aja(self.JASENET, vastaa, kokoaja=AJATTELEVA)
        for r in (x for x in rungot if self.on_kokoaja(x)):
            self.assertIn("VASTAUS 2:", r["messages"][-1]["content"])
            self.assertNotIn("VASTAUS 3:", r["messages"][-1]["content"])
        self.assertEqual(rivit[0]["vastauksia"], 2)
        self.assertEqual(rivit[0]["vastaus"], "Lopullinen.")
        ajo = json.loads((self.ulos / "ajo-yhdistelma-3.json").read_text(encoding="utf-8"))
        self.assertEqual(ajo["jasenten_tyhjat"], len(rivit))
        self.assertEqual(ajo["ajattelevat_listan_ulkopuolella"], [TAVALLINEN])

    def test_kaikki_jasenet_tyhjia_ei_kokoajan_kutsua(self):
        yv, rungot, rivit = self.aja(self.JASENET, lambda r: or_vastaus(**TYHJA_AJATTELU), kokoaja=AJATTELEVA)
        self.assertFalse([r for r in rungot if self.on_kokoaja(r)])
        for r in rivit:
            self.assertEqual((r["vastaus"], r["tyhja"]), ("", True))
            self.assertNotIn("virhe", r)
        self.assertEqual(yv["virheita"], 0)


class VertailuAjoTesti(Tilapainen):
    def test_vertailu_tyhja_ei_ole_nolla_eika_mene_tuomarille(self):
        rungot = []

        def vastaa(r):
            return or_vastaus(**TYHJA_AJATTELU) if r["model"] == AJATTELEVA else or_vastaus("Vastaus.")
        yv = mv.aja([TAVALLINEN, AJATTELEVA], self.ulos, tehdas(rungot, vastaa), toistot=1,
                    kulutila=str(self.kulut), loki=self.loki.append)
        self.assertEqual({r["model"]: r["max_tokens"] for r in rungot},
                         {TAVALLINEN: mv.MAX_TOKENIA, AJATTELEVA: yo.MAX_TOKENIA})
        self.assertEqual(yv["ei_vastausta"], mv.TEHTAVIA)
        rivit = mv.lue_vastaukset(self.ulos)
        self.assertTrue(all(r["finish_reason"] in ("stop", "length") and "tyhja" in r for r in rivit))
        self.assertEqual(mv.paketti(self.ulos), mv.TEHTAVIA)          # vain ei-tyhjat tuomarille
        tulos = mv.pisteet(self.ulos)
        self.assertEqual(tulos[AJATTELEVA]["ei_vastausta"], mv.TEHTAVIA)
        self.assertIsNone(tulos[AJATTELEVA]["yhteensa"])
        self.assertEqual(tulos[AJATTELEVA]["alueet"], {})
        taulu = mv.taulukko(tulos).splitlines()
        self.assertIn("Ei vastausta", taulu[0])
        viimeinen = taulu[-1]
        self.assertTrue(viimeinen.startswith("| %s | - |" % AJATTELEVA), viimeinen)
        self.assertIn("| %d/%d |" % (mv.TEHTAVIA, mv.TEHTAVIA), viimeinen)
        self.assertIn("(ei vastausta)", mv.sokkonaytteet(self.ulos, tulos))


class TuotantoTesti(unittest.TestCase):
    """yksityinen_or: tyhja content + finish_reason "length" -> VastausKatkesi (ilmoitus), ei tyhjaa viestia."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.avain = self.d / "avain"
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)

    def yhteiset(self, data):
        class Vastaus(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def avaa(pyynto, timeout=None):
            return Vastaus(json.dumps(data).encode())
        return dict(avain_tiedosto=str(self.avain), kulutila=str(self.kulut), avaa=avaa, nyt=lambda: NYT)

    def test_chat_ilmoittaa_katkeamisesta(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(yo.VastausKatkesi) as cm:
            yo.kysy_openrouterilta("muisti", [{"rooli": "tony", "teksti": "moi"}], "", malli=AJATTELEVA,
                                   **self.yhteiset(or_vastaus(**TYHJA_AJATTELU)))
        self.assertIsInstance(cm.exception, yksityinen.YksityinenVirhe)
        self.assertIn("katkesi", str(cm.exception))
        self.assertNotIn("mietin", str(cm.exception) + err.getvalue())
        self.assertIn("katkesi", err.getvalue())

    def test_content_none_ja_length(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(yo.VastausKatkesi):
            yo.kysy_openrouterilta("", [{"rooli": "tony", "teksti": "moi"}], "", malli=AJATTELEVA,
                                   **self.yhteiset(or_vastaus(content=None, finish="length")))

    def test_tyhja_ilman_lengthia_on_tavallinen_virhe(self):
        with self.assertRaises(yksityinen.YksityinenVirhe) as cm:
            yo.kysy_openrouterilta("", [{"rooli": "tony", "teksti": "moi"}], "", malli=AJATTELEVA,
                                   **self.yhteiset(or_vastaus(content="", finish="stop")))
        self.assertNotIsInstance(cm.exception, yo.VastausKatkesi)

    def test_katkennut_teksti_saa_huomautuksen_kuten_ennen(self):
        with contextlib.redirect_stderr(io.StringIO()):
            v = yo.kysy_openrouterilta("", [{"rooli": "tony", "teksti": "moi"}], "", malli=AJATTELEVA,
                                       **self.yhteiset(or_vastaus(content="Alku", finish="length")))
        self.assertEqual(v, "Alku\n\n" + yo.KATKENNUT_HUOMAUTUS)

    def test_tiivistys_ja_taustatyo(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(yo.VastausKatkesi):
                yo.kysy_tiivistys("ohje", "data", malli=AJATTELEVA, **self.yhteiset(or_vastaus(**TYHJA_AJATTELU)))
            with self.assertRaises(yo.VastausKatkesi):
                yo.kysy_taustatyo(AJATTELEVA, [{"role": "user", "content": "x"}], aikaraja_s=60,
                                  **self.yhteiset(or_vastaus(**TYHJA_AJATTELU)))
            v = yo.kysy_taustatyo(AJATTELEVA, [{"role": "user", "content": "x"}], aikaraja_s=60,
                                  **self.yhteiset(or_vastaus(content="Puolikas", finish="length")))
        self.assertEqual(v, "Puolikas\n\n" + yo.TAUSTA_KATKENNUT_HUOMAUTUS)
        with contextlib.redirect_stderr(io.StringIO()):
            v = yo.kysy_taustatyo(AJATTELEVA, [{"role": "user", "content": "x"}], aikaraja_s=60,
                                  **self.yhteiset(or_vastaus(content="Valmis.")))
        self.assertEqual(v, "Valmis.")

    def test_taustaajon_syy(self):
        self.assertEqual(taustaajo._syy(yo.VastausKatkesi("x")), "katkesi")
        self.assertIn("katkesi", taustaajo.epaonnistui_teksti("katkesi"))
        self.assertEqual(taustaajo._syy(yksityinen.YksityinenVirhe("x")), "malli")

    def test_taustaajon_ajattelija_katkesi(self):
        roolit = {"ajattelija": AJATTELEVA, "keskustelija": AJATTELEVA}

        def kysy(malli, viestit, aikaraja_s):
            raise yo.VastausKatkesi(yo.KATKESI_TYHJANA)
        with self.assertRaises(yo.VastausKatkesi):
            taustaajo.aja_tyo({"tehtava": "x"}, kysy, roolit, 60)


if __name__ == "__main__":
    unittest.main()
