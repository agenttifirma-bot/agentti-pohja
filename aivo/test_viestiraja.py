"""Viestiraja 16 000 merkkia: palvelin ja selain kayttavat samaa rajaa, liian pitkaa viestia ei katkaista
hiljaa, ja historian kokonaismerkit rajataan, jotta kehote pysyy kohtuullisena."""
import re
import unittest

from aivo import chat, mallivertailu, yksityinen, yksityinen_or
from aivo.test_chat import ChatPalveluPohja


class PalvelinRajaTesti(ChatPalveluPohja):
    def _uusi(self, tila):
        ev = self.kirjaudu()
        _, d = self.api(ev, "/api/uusi", {"tila": tila})
        return ev, d["id"]

    def test_raja_on_16000(self):
        self.assertEqual(chat.VIESTI_YLARAJA, 16_000)

    def test_15999_merkkia_menee_lapi_molemmissa_tiloissa(self):
        type(self).vastaus = "Selv\u00e4."
        for tila in ("tyokalu", "yksityinen"):
            ev, kid = self._uusi(tila)
            s, v = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "x" * 15_999})
            self.assertEqual(s, 200, tila)
            self.assertEqual(v["vastaus"], "Selv\u00e4.")

    def test_tasan_raja_menee_lapi_myos_aakkosilla(self):
        # json.dumps pakottaa a:n muotoon \u00e4 (6 tavua): runkorajan pitaa riittaa koko viestille
        ev, kid = self._uusi("tyokalu")
        s, _ = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "\u00e4" * chat.VIESTI_YLARAJA})
        self.assertEqual(s, 200)

    def test_16001_hylataan_selvalla_virheella_eika_tallenneta(self):
        for tila in ("tyokalu", "yksityinen"):
            ev, kid = self._uusi(tila)
            s, v = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "x" * 16_001})
            self.assertEqual(s, 400, tila)
            self.assertIn("liian pitk\u00e4", v["virhe"])
            self.assertIn("16\u00a0001", v["virhe"])
            self.assertIn("16\u00a0000", v["virhe"])
            self.assertIn("Jaa se osiin", v["virhe"])
        # hylatty viesti ei paady historiaan katkaistuna
            _, ks = self.tila.tila_ja_kasittelija(kid)
            self.assertEqual(ks.lue(kid), [], tila)

    def test_tyhja_viesti_saa_edelleen_oman_virheen(self):
        ev, kid = self._uusi("tyokalu")
        s, v = self.api(ev, "/api/viesti", {"keskustelu": kid, "teksti": "   "})
        self.assertEqual((s, v["virhe"]), (400, "viesti puuttuu tai on liian pitka"))

    def test_muiden_reittien_runkoraja_ei_kasva(self):
        self.assertGreaterEqual(chat.VIESTI_RUNKO_YLARAJA, 6 * chat.VIESTI_YLARAJA)
        ev, kid = self._uusi("tyokalu")
        s, _ = self.api(ev, "/api/paatos", {"keskustelu": kid, "indeksi": 0, "taytto": "x" * 25_000})
        self.assertEqual(s, 413)


class SivuRajaTesti(unittest.TestCase):
    def setUp(self):
        self.h = chat.sivu_html("openrouter")

    def test_selain_kayttaa_samaa_rajaa_kuin_palvelin(self):
        self.assertIn("const RAJA=%d;" % chat.VIESTI_YLARAJA, self.h)
        self.assertNotIn("{VIESTI_YLARAJA", self.h)

    def test_ei_maxlength_rajaa_joka_katkaisisi_liitetyn_tekstin_hiljaa(self):
        lomake = self.h[self.h.index('<form id="lomake">'):self.h.index("</form>")]
        self.assertNotRegex(lomake, re.compile("maxlength", re.I))
        muu = self.h[self.h.index("function valinnat("):self.h.index("function painike(")]
        self.assertNotRegex(muu, re.compile("maxlength", re.I))                         # "Muu vastaus"
        self.assertNotIn("4000", self.h)

    def test_laskuri_ja_varoitus_ovat_mukana(self):
        self.assertIn('<div id="laskuri" class="pieni" aria-live="polite">0 / 16\u00a0000</div>', self.h)
        self.assertIn('aria-describedby="laskuri"', self.h)
        self.assertIn("addEventListener('input',laskuri)", self.h)
        self.assertIn("Teksti on '+tuhat(n)+' merkki\u00e4, raja '+tuhat(RAJA)+'. Jaa se osiin.'", chat.HTML)
        self.assertIn("n>=0.9*RAJA?' varoitus'", self.h)

    def test_liian_pitkaa_ei_lahetetaan_eika_kenttaa_tyhjenneta(self):
        lomake = self.h[self.h.index("document.getElementById('lomake').onsubmit"):]
        self.assertLess(lomake.index("if(pituus(s)>RAJA){laskuri();t.focus();return;}"), lomake.index("t.value=''"))
        self.assertIn("if(pituus(s)>RAJA){lisaa('aivo',ylipitka(pituus(s)));return;}", self.h)   # laheta() myos
        muu = self.h[self.h.index("function valinnat("):self.h.index("function painike(")]
        self.assertIn("if(n>RAJA){ti.textContent=ylipitka(n);return;}", muu)              # "Muu vastaus"

    def test_textcontent_kaytanto_sailyy(self):
        self.assertIn("L.textContent=", self.h)
        self.assertNotIn("innerHTML", self.h)
        self.assertNotIn("insertAdjacentHTML", self.h)

    def test_pituus_lasketaan_koodipisteina_kuten_pythonissa(self):
        self.assertIn("function pituus(s){return Array.from(s).length;}", self.h)

    def test_tuhaterotin(self):
        self.assertEqual(chat.tuhaterotin(16000), "16\u00a0000")
        self.assertEqual(chat.tuhaterotin(1234), "1\u00a0234")
        self.assertEqual(chat.tuhaterotin(999), "999")


class HistoriaRajausTesti(unittest.TestCase):
    def test_mahtuva_historia_ei_muutu(self):
        self.assertEqual(yksityinen.lyhenna_historia(["a", "bb", "ccc"], 6), ["a", "bb", "ccc"])

    def test_uusin_sailyy_kokonaan_ja_vanhimmat_lyhennetaan(self):
        t = yksityinen.lyhenna_historia(["A" * 50, "B" * 50, "C" * 50], 80)
        self.assertEqual(t[2], "C" * 50)
        self.assertEqual(t[1], "B" * 30 + yksityinen.LYHENNETTY % 20)
        self.assertEqual(t[0], yksityinen.LYHENNETTY % 50)
        self.assertEqual(len(t), 3)

    def test_uusin_sailyy_vaikka_ylittaisi_rajan(self):
        t = yksityinen.lyhenna_historia(["vanha", "x" * 100], 10)
        self.assertEqual(t, [yksityinen.LYHENNETTY % 5, "x" * 100])

    def test_yksityinen_or_pahin_tapaus_pysyy_rajassa(self):
        h = [{"rooli": "tony" if i % 2 == 0 else "aivo", "teksti": "x" * chat.VIESTI_YLARAJA} for i in range(40)]
        v = yksityinen.muodosta_viestit("", h, "", yksityinen_or.KEHOTE, yksityinen_or.HISTORIA_YLARAJA,
                                        yksityinen_or.HISTORIA_MERKIT_YLARAJA)
        self.assertEqual(len(v), 41)                                   # viestien maara ja roolit ennallaan
        self.assertEqual(v[-1]["content"], "x" * chat.VIESTI_YLARAJA)  # uusin kokonaan
        merkit = sum(len(x["content"]) for x in v[1:])
        self.assertLess(merkit, yksityinen_or.HISTORIA_MERKIT_YLARAJA + 40 * 60)   # merkinnat mukaan

    def test_paikallinen_oletusraja(self):
        h = [{"rooli": "tony" if i % 2 == 0 else "aivo", "teksti": "y" * chat.VIESTI_YLARAJA} for i in range(12)]
        v = yksityinen.muodosta_viestit("", h, "")
        self.assertEqual(v[-1]["content"], "y" * chat.VIESTI_YLARAJA)
        self.assertLess(sum(len(x["content"]) for x in v[1:]), yksityinen.HISTORIA_MERKIT_YLARAJA + 12 * 60)

    def test_tyokalutila_rajaa_historian(self):
        h = [{"rooli": "tony" if i % 2 == 0 else "aivo", "teksti": "z" * chat.VIESTI_YLARAJA} for i in range(40)]
        s = chat.muodosta_syote("M", h)
        self.assertIn("Tony #38: " + "z" * chat.VIESTI_YLARAJA, s)     # numerointi sailyy
        self.assertIn("Tony #0: ", s)
        self.assertLess(len(s), len(chat.KEHOTE) + chat.HISTORIA_MERKIT_YLARAJA + 40 * 80)

    def test_mallivertailu_kayttaa_tuotannon_merkkirajaa(self):
        h = [{"rooli": "tony" if i % 2 == 0 else "aivo", "teksti": "w" * chat.VIESTI_YLARAJA} for i in range(40)]
        sarja = {"ydinohjeet": "", "muisti": ""}
        v = mallivertailu.viestit(sarja, {"historia": h})
        self.assertLess(sum(len(x["content"]) for x in v[1:]), yksityinen_or.HISTORIA_MERKIT_YLARAJA + 40 * 60)


if __name__ == "__main__":
    unittest.main()
