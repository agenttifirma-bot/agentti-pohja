"""Testit yksityisen tilan itsetarkistukselle (aivo/itsetarkistus.py, AIVO_YKSITYINEN_ITSETARKISTUS). Ei verkkoa.

Kolme tasoa kuten test_yksityinen_yhdistelma.py:ssa:
  * Yksikkotaso: `itsetarkistus.aja` saa korvikemallin (`kysy`).
  * Kutsupolku: oikea `yksityinen_or.tarkista_vastaus` -> `_kysy_viestit` -> `openrouter_kulut.kutsu` -> ZDR-runko ->
    valekuljetin. Vain verkkoyhteys (`avaa`) on korvattu.
  * HTTP: oikea Tila ja kasittelija samalla valekuljettimella."""
import ast
import http.client
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from aivo import chat, itsetarkistus as it, openrouter_kulut as ok, salasana_apu, yhdistelma as yh, yksityinen
from aivo import yksityinen_or as yo

M1 = "qwen/qwen3-235b-a22b-2507"
M2 = "meta-llama/llama-3.3-70b-instruct"
AVAIN = "sk-testi-" + "x" * 30          # keksitty, ei oikea avain
SALASANA = "oikea-salasana-123"
NYT = datetime(2026, 11, 25, 12, 0, tzinfo=ok.TZ)
PERUS = [{"role": "system", "content": "KEHOTE: p\u00e4\u00e4t\u00f6s A984 = OpenRouter ZDR"},
         {"role": "user", "content": "Mik\u00e4 on p\u00e4iv\u00e4katto?"}]
FAKTA = "P\u00e4iv\u00e4katto on 20 \u20ac/vrk (A963)."
KOHTA = json.dumps([{"kohta": "20 \u20ac/vrk", "syy": "l\u00e4hteiden mukaan 10 \u20ac/vrk"}], ensure_ascii=False)
EHDOTUS = "[[EHDOTUS tyyli.md]]\nKirjoita lyhyesti.\n[[/EHDOTUS]]"


def _rooli(viestit):
    s = str(viestit[0].get("content", ""))
    if s == it.TARKASTAJA_OHJE:
        return "tarkastaja"
    if "vastaaja, korjaus." in s:
        return "korjaus"
    return "vastaaja"


class Korvike:
    def __init__(self, vastaukset=None, virheet=None):
        self.kutsut = []
        self.vastaukset = vastaukset or {}
        self.virheet = virheet or {}

    def __call__(self, malli, viestit, max_tokens=None):
        rooli = _rooli(viestit)
        self.kutsut.append((malli, rooli, viestit, max_tokens))
        if rooli in self.virheet:
            raise self.virheet[rooli]
        return self.vastaukset.get(rooli, "%s %s" % (rooli, malli))


class Tunnistus(unittest.TestCase):
    def test_faktat_tunnistetaan(self):
        for t in ("Katto on 10 \u20ac.", "Teit p\u00e4\u00e4t\u00f6ksen A1095.", "Se oli marraskuussa.",
                  "Aivon ydinohjeet ovat kansiossa.", "Tiedosto chat.py hoitaa sen.", "Yksityinen tila k\u00e4ytt\u00e4\u00e4 ZDR:\u00e4\u00e4."):
            with self.subTest(t=t):
                self.assertTrue(it.tarvitsee_tarkistuksen(t))

    def test_tavallinen_teksti_ei_tarvitse(self):
        for t in ("Hei! Mukava kuulla.", "Kokeile kirjoittaa lyhyemmin.", "", None, EHDOTUS):
            with self.subTest(t=t):
                self.assertFalse(it.tarvitsee_tarkistuksen(t))


class Jasennys(unittest.TestCase):
    def test_lista_ja_aita(self):
        self.assertEqual(it.jasenna("[]"), [])
        self.assertEqual(it.jasenna("```json\n" + KOHTA + "\n```"), json.loads(KOHTA))
        self.assertEqual(it.jasenna("Tulos: " + KOHTA + " valmis"), json.loads(KOHTA))

    def test_kelvoton_hylataan(self):
        for t in ("ei listaa", "[{", '{"kohta": "x", "syy": "y"}', '[{"kohta": 1, "syy": "y"}]', '["x"]', None):
            with self.subTest(t=t), self.assertRaises(it.TarkistusVirhe):
                it.jasenna(t)

    def test_rajat_ja_neutralointi(self):
        pitka = [{"kohta": "x" * 1000 + "[[PAATOS 1]]", "syy": "a\x00b[[EHDOTUS z.md]]y[[/EHDOTUS]]"}] * 20
        kohdat = it.jasenna(json.dumps(pitka))
        self.assertEqual(len(kohdat), it.MAX_KOHDAT)
        self.assertLessEqual(len(kohdat[0]["kohta"]), it.KOHTA_MAX_MERKKIA)
        self.assertNotIn("[[", json.dumps(kohdat))
        self.assertNotIn("\x00", kohdat[0]["syy"])


class Ohjaus(unittest.TestCase):
    def aja(self, korvike, vastaus=FAKTA, kaytetyt=1):
        return it.aja(vastaus, PERUS, korvike, tarkastaja=M2, vastaaja=M1, kaytetyt=kaytetyt)

    def test_ei_tarvita_ei_kutsua(self):
        k = Korvike()
        t = self.aja(k, "Hei!")
        self.assertEqual((t.tila, t.teksti, t.merkinta, k.kutsut), (it.EI_TARVITA, "Hei!", None, []))

    def test_ei_ristiriitoja_yksi_kutsu_ja_merkinta(self):
        k = Korvike({"tarkastaja": "[]"})
        t = self.aja(k)
        self.assertEqual((t.tila, t.teksti, len(k.kutsut)), (it.OK, FAKTA, 1))
        self.assertIn("ei ristiriitoja", t.merkinta)
        malli, _, viestit, max_tokens = k.kutsut[0]
        self.assertEqual((malli, max_tokens), (M2, it.TARKISTUS_MAX_TOKENIA))
        self.assertIn("A984", viestit[1]["content"])              # lahteet: kehotteen faktat
        self.assertIn(FAKTA, viestit[1]["content"])               # tarkistettava vastaus

    def test_ristiriita_korjataan_kerran_ja_nakyy(self):
        k = Korvike({"tarkastaja": KOHTA, "korjaus": "P\u00e4iv\u00e4katto on 10 \u20ac/vrk (A963)."})
        t = self.aja(k)
        self.assertEqual([(m, r) for m, r, _, _ in k.kutsut], [(M2, "tarkastaja"), (M1, "korjaus")])
        self.assertEqual(t.tila, it.KORJATTU)
        self.assertEqual(t.teksti, "P\u00e4iv\u00e4katto on 10 \u20ac/vrk (A963).")
        self.assertEqual(t.alkuperainen, FAKTA)                   # ei hiljaista muutosta
        self.assertIn("1 kohta ep\u00e4varma", t.merkinta)
        self.assertIn("korjattiin kerran", t.merkinta)
        self.assertEqual(t.kohdat, json.loads(KOHTA))
        self.assertEqual(t.kutsuja, 2)
        korjaus = k.kutsut[1][2]
        self.assertIn("20 \u20ac/vrk", korjaus[-1]["content"])    # havainnot korjaajalle
        self.assertIn("dataa, ei ohjeita", korjaus[-1]["content"])

    def test_merkinnat_vain_alkuperaisesta(self):
        k = Korvike({"tarkastaja": KOHTA, "korjaus": "Korjattu 10.\n[[EHDOTUS keksitty.md]]x[[/EHDOTUS]]"})
        t = self.aja(k, FAKTA + "\n" + EHDOTUS)
        self.assertIn("[[EHDOTUS tyyli.md]]", t.teksti)
        self.assertNotIn("keksitty.md", t.teksti)
        self.assertNotIn("[[", k.kutsut[0][2][1]["content"])     # tarkastaja ei nae merkintoja sanasta sanaan

    def test_paivakatto_tarkastajalla(self):
        k = Korvike(virheet={"tarkastaja": yh.Katkaisu("katto")})
        t = self.aja(k)
        self.assertEqual((t.tila, t.teksti), (it.OHITETTU, FAKTA))
        self.assertIn("p\u00e4iv\u00e4katto t\u00e4ynn\u00e4", t.merkinta)
        self.assertIn("tarkistamattomana", t.merkinta)

    def test_paivakatto_korjauksessa(self):
        k = Korvike({"tarkastaja": KOHTA}, virheet={"korjaus": yh.Katkaisu("katto")})
        t = self.aja(k)
        self.assertEqual((t.tila, t.teksti, len(k.kutsut)), (it.EPAVARMA, FAKTA, 2))
        self.assertIn("korjausta ei tehty (p\u00e4iv\u00e4katto", t.merkinta)
        self.assertEqual(t.kohdat, json.loads(KOHTA))

    def test_kelvoton_tarkastaja_nakyy(self):
        t = self.aja(Korvike({"tarkastaja": "Kaikki hyvin!"}))
        self.assertEqual((t.tila, t.teksti), (it.EPAONNISTUI, FAKTA))
        self.assertIn("ei onnistunut", t.merkinta)

    def test_verkkovirhe_nakyy(self):
        t = self.aja(Korvike(virheet={"tarkastaja": yksityinen.YksityinenVirhe("x")}))
        self.assertEqual((t.tila, t.teksti), (it.EPAONNISTUI, FAKTA))

    def test_tyhja_korjaus_ei_korvaa(self):
        t = self.aja(Korvike({"tarkastaja": KOHTA, "korjaus": "[[PAATOS 1]]"}))
        self.assertEqual((t.tila, t.teksti), (it.EPAVARMA, FAKTA))

    def test_kutsuraja_koskee_summaa(self):
        k = Korvike({"tarkastaja": KOHTA})
        t = self.aja(k, kaytetyt=yh.MAX_KUTSUT_VIESTI)
        self.assertEqual((t.tila, k.kutsut), (it.OHITETTU, []))
        self.assertIn("kutsuraja", t.merkinta)
        t = self.aja(k, kaytetyt=yh.MAX_KUTSUT_VIESTI - 1)
        self.assertEqual((t.tila, len(k.kutsut)), (it.EPAVARMA, 1))
        self.assertIn("korjausta ei tehty (kutsuraja)", t.merkinta)
        for kaytetyt in range(0, yh.MAX_KUTSUT_VIESTI + 1):
            k = Korvike({"tarkastaja": KOHTA})
            self.aja(k, kaytetyt=kaytetyt)
            self.assertLessEqual(kaytetyt + len(k.kutsut), max(kaytetyt, yh.MAX_KUTSUT_VIESTI))


class Rakenne(unittest.TestCase):
    def test_ei_verkkoa_eika_openrouter_moduuleja(self):
        puu = ast.parse((Path(it.__file__)).read_text(encoding="utf-8"))
        tuodut = set()
        for s in ast.walk(puu):
            if isinstance(s, ast.Import):
                tuodut.update(a.name for a in s.names)
            elif isinstance(s, ast.ImportFrom):
                tuodut.update([s.module or ""] + [a.name for a in s.names])
        for kielletty in ("urllib", "urllib.request", "http", "socket", "openrouter_kulut", "openrouter_zdr",
                          "yksityinen_or"):
            self.assertNotIn(kielletty, tuodut)


class FeikkiVastaus:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Verkko:
    """Valekuljetin: korvaa vain verkkoyhteyden ja kirjaa rungot."""

    def __init__(self, vastaukset=None, kulu=0.001):
        self.rungot = []
        self.aikarajat = []
        self.vastaukset = vastaukset or {}
        self.kulu = kulu
        self._lukko = threading.Lock()

    def __call__(self, pyynto, timeout=None):
        runko = json.loads(pyynto.data)
        with self._lukko:
            self.rungot.append(runko)
            self.aikarajat.append(timeout)
        teksti = self.vastaukset.get(_rooli(runko["messages"]), "%s %s" % (_rooli(runko["messages"]), runko["model"]))
        return FeikkiVastaus({"choices": [{"message": {"content": teksti}}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": self.kulu}})

    def roolit(self):
        return [_rooli(r["messages"]) for r in self.rungot]


class Kutsupolku(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.avain = self.d / "avain"
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.kulut = self.d / "kulut"
        self.kulut.mkdir(mode=0o700)

    def aja(self, verkko, tarkastaja=M2, vastaus=FAKTA):
        return yo.tarkista_vastaus("muisti: katto 10 \u20ac/vrk", [{"rooli": "tony", "teksti": "katto?"}], "ohje",
                                   vastaus, vastaaja=M1, tarkastaja=tarkastaja, avain_tiedosto=str(self.avain),
                                   kulutila=str(self.kulut), avaa=verkko, nyt=lambda: NYT)

    def kulurivit(self):
        p = self.kulut / ok.KULUT
        rivit = [json.loads(r) for r in p.read_text().splitlines()] if p.exists() else []
        return [r for r in rivit if not r.get("varaus")]

    def test_zdr_runko_kulukirjaus_ja_oma_tehtava(self):
        v = Verkko({"tarkastaja": KOHTA, "korjaus": "Katto on 10 \u20ac/vrk."})
        t = self.aja(v)
        self.assertEqual((t.tila, v.roolit()), (it.KORJATTU, ["tarkastaja", "korjaus"]))
        self.assertEqual([r["model"] for r in v.rungot], [M2, M1])
        for runko in v.rungot:
            self.assertIs(runko["provider"]["zdr"], True)
            self.assertEqual(runko["provider"]["data_collection"], "deny")
            self.assertTrue(yo.avoin_malli(runko["model"]))
            self.assertLessEqual(runko["max_tokens"], yo.MAX_TOKENIA)
        self.assertEqual(v.rungot[0]["max_tokens"], it.TARKISTUS_MAX_TOKENIA)
        self.assertLessEqual(v.aikarajat[0], yo.VASTAUS_AIKARAJA_S)
        self.assertLessEqual(v.aikarajat[1], yo.CHAT_AIKARAJA_S)
        self.assertIn("katto 10", v.rungot[0]["messages"][1]["content"])     # muisti lahteena
        self.assertEqual([r["tehtava"] for r in self.kulurivit()], [yo.TARKISTUS_TEHTAVA] * 2)
        self.assertEqual(chat.kayttotarkoitus(yo.TARKISTUS_TEHTAVA), "chat")

    def test_suljettu_tarkastaja_hylataan_ennen_kutsua(self):
        v = Verkko()
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.aja(v, tarkastaja="openai/gpt-4o")
        self.assertEqual(v.rungot, [])

    def test_puuttuva_tarkastaja_kayttaa_vastaajaa(self):
        v = Verkko({"tarkastaja": "[]"})
        self.assertEqual(self.aja(v, tarkastaja=None).tila, it.OK)
        self.assertEqual([r["model"] for r in v.rungot], [M1])

    def test_paivakatto_taynna_ei_kutsua_ja_vastaus_nakyy(self):
        ok.kirjaa(M1, "muu", {"usage": {"cost": 20.0}}, NYT, str(self.kulut))
        v = Verkko()
        t = self.aja(v)
        self.assertEqual((t.tila, t.teksti, v.rungot), (it.OHITETTU, FAKTA, []))
        self.assertIn("p\u00e4iv\u00e4katto", t.merkinta)

    def test_paivakatto_tayttyy_tarkistuksessa(self):
        v = Verkko({"tarkastaja": KOHTA}, kulu=11.5)            # tarkastajan kutsu tayttaa 10 EUR katon
        t = self.aja(v)
        self.assertEqual((t.tila, t.teksti, len(v.rungot)), (it.EPAVARMA, FAKTA, 1))
        self.assertIn("korjausta ei tehty (p\u00e4iv\u00e4katto", t.merkinta)

    def test_puuttuva_avain_nakyy_merkintana(self):
        os.unlink(self.avain)
        v = Verkko()
        t = self.aja(v)
        self.assertEqual((t.tila, t.teksti, v.rungot), (it.EPAONNISTUI, FAKTA, []))


class Palvelin(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        r = self.r = Path(self._t.name)
        (r / "kirjasto").mkdir()
        (r / "avain").write_text(AVAIN + "\n")
        os.chmod(r / "avain", 0o600)
        (r / "kulut").mkdir(mode=0o700)
        self.verkko = Verkko({"vastaaja": FAKTA, "tarkastaja": KOHTA, "korjaus": "Katto on 10 \u20ac/vrk."})
        alkup = yo.tee_kuljetin
        p = mock.patch.object(yo, "tee_kuljetin",
                              lambda avain, avaa=None, aikaraja_s=None, **kw: alkup(avain, self.verkko, aikaraja_s, **kw))
        p.start()
        self.addCleanup(p.stop)

    def kaynnista(self, **kw):
        r = self.r
        self.tila = chat.Tila(salasana_apu.tiiviste(SALASANA), str(r / "kirjasto"), str(r / "data"), ["localhost"],
                              kysy=lambda m, h: "pilvi", yks_data=str(r / "yks"), yks_muisti=str(r / "yksm"),
                              ydinohjeet=str(r / "ydin"), ehdotukset=str(r / "ehd"), or_avain=str(r / "avain"),
                              or_kulutila=str(r / "kulut"), taustapaa="openrouter", or_mallit=[M1, M2],
                              roolit="tarkastaja:%s" % M2, **kw)
        srv = chat.kaynnista("127.0.0.1", 0, self.tila)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.portti = srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SALASANA,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        x = c.getresponse()
        x.read()
        self.ev = x.getheader("Set-Cookie").split(";")[0]

    def api(self, polku, olio=None, metodi="POST"):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=20)
        c.request(metodi, polku, body=None if olio is None else json.dumps(olio),
                  headers={"Cookie": self.ev, "X-Aivo": "1", "Content-Type": "application/json"})
        x = c.getresponse()
        return x.status, json.loads(x.read())

    def viesti(self, **kw):
        _, j = self.api("/api/uusi", dict({"tila": "yksityinen"}, **kw))
        s, v = self.api("/api/viesti", {"keskustelu": j["id"], "teksti": "Mik\u00e4 on katto?"})
        return j["id"], s, v

    def test_oletus_pois_ei_lisakutsuja(self):
        self.kaynnista()
        _, s, v = self.viesti()
        self.assertEqual((s, v["vastaus"], len(self.verkko.rungot)), (200, FAKTA, 1))
        self.assertNotIn("tarkistus", v)

    def test_paalla_korjaus_ja_merkinta_nakyvat(self):
        self.kaynnista(itsetarkistus="paalla")
        kid, s, v = self.viesti()
        self.assertEqual(s, 200)
        self.assertEqual(self.verkko.roolit(), ["vastaaja", "tarkastaja", "korjaus"])
        self.assertEqual(v["vastaus"], "Katto on 10 \u20ac/vrk.")
        self.assertEqual(v["tarkistus"]["tila"], it.KORJATTU)
        self.assertIn("1 kohta ep\u00e4varma", v["tarkistus"]["merkinta"])
        self.assertEqual(v["tarkistus"]["alkuperainen"], FAKTA)
        self.assertEqual(v["tarkistus"]["kohdat"], json.loads(KOHTA))
        rivi = self.tila.yks.lue(kid)[-1]
        self.assertEqual((rivi["teksti"], rivi["tarkistus"]["alkuperainen"]), (v["vastaus"], FAKTA))
        self.assertEqual(rivi["tarkistus"]["mallit"], [M2, M1])
        self.assertEqual(self.verkko.rungot[1]["model"], M2)        # rooli tarkastaja asetuksesta

    def test_ei_faktoja_ei_tarkistusta(self):
        self.verkko.vastaukset["vastaaja"] = "Hei!"
        self.kaynnista(itsetarkistus="paalla")
        _, s, v = self.viesti()
        self.assertEqual((s, v["vastaus"], len(self.verkko.rungot)), (200, "Hei!", 1))
        self.assertNotIn("tarkistus", v)

    def test_yhdistelman_kutsut_lasketaan_rajaan(self):
        self.kaynnista(itsetarkistus="paalla", yhdistelma_oletus="tarkastus")
        self.verkko.vastaukset["vastaaja"] = FAKTA
        _, s, v = self.viesti()
        self.assertEqual(s, 200)
        self.assertLessEqual(len(self.verkko.rungot), yh.MAX_KUTSUT_VIESTI)
        self.assertEqual(v["kutsuja"], 2)                      # yhdistelman omat kutsut ennallaan
        self.assertIn("tarkistus", v)

    def test_sivu_nayttaa_tarkistuksen(self):
        self.kaynnista(itsetarkistus="paalla")
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("GET", "/", headers={"Cookie": self.ev})
        sivu = c.getresponse().read().decode("utf-8")
        self.assertIn("tarkistustieto(odota,j.tarkistus)", sivu)
        self.assertNotIn("innerHTML", sivu.split("function tarkistustieto", 1)[1].split("const H=", 1)[0])


class Asetus(unittest.TestCase):
    def test_arvot(self):
        for a, odotettu in ((None, False), ("", False), ("pois", False), ("paalla", True), (" PAALLA ", True)):
            with self.subTest(a=a):
                self.assertIs(chat.tarkista_itsetarkistus(a), odotettu)
        for a in ("kylla", "1", "on"):
            with self.subTest(a=a), self.assertRaises(yksityinen.YksityinenVirhe):
                chat.tarkista_itsetarkistus(a)

    def test_vaatii_openrouterin(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "kirjasto").mkdir()
            with self.assertRaises(yksityinen.YksityinenVirhe):
                chat.Tila(salasana_apu.tiiviste(SALASANA), str(r / "kirjasto"), str(r / "data"), ["localhost"],
                          yks_data=str(r / "yks"), yks_muisti=str(r / "yksm"), ydinohjeet=str(r / "ydin"),
                          ehdotukset=str(r / "ehd"), itsetarkistus="paalla")
            with self.assertRaises(yksityinen.YksityinenVirhe):
                chat.Tila(salasana_apu.tiiviste(SALASANA), str(r / "kirjasto"), str(r / "data"), ["localhost"],
                          itsetarkistus="paalla")

    def test_main_lukee_ymparistomuuttujan(self):
        saatu = {}

        def tila(*a, **kw):
            saatu.update(kw)
            raise chat.ChatVirhe("pysaytetty testissa")
        pois = {k: v for k, v in os.environ.items() if not k.startswith("AIVO_")}
        with mock.patch.dict(os.environ, {**pois, "AIVO_YKSITYINEN_ITSETARKISTUS": "paalla"}, clear=True), \
                mock.patch.object(chat, "lue_tiiviste", return_value="x"), mock.patch.object(chat, "Tila", tila), \
                mock.patch("sys.stderr"):
            self.assertEqual(chat.main(["palvele"]), 1)
        self.assertEqual(saatu["itsetarkistus"], "paalla")
        with mock.patch.dict(os.environ, pois, clear=True), mock.patch.object(chat, "lue_tiiviste", return_value="x"), \
                mock.patch.object(chat, "Tila", tila), mock.patch("sys.stderr"):
            chat.main(["palvele"])
        self.assertEqual(saatu["itsetarkistus"], "")           # oletus pois


if __name__ == "__main__":
    unittest.main()
