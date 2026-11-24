"""Luovutuksen merkkiraja 16 000 (sama kuin chatin viestiraja): palvelin ja selain kayttavat samaa arvoa,
liian pitkaa tekstia ei katkaista hiljaa, ja /api/luovutus/muokkaa-reitin runkoraja riittaa koko tekstille."""
import re
import unittest

from aivo import chat, luovutus, yksityinen
from aivo.test_luovutus import LuovutusPohja


class PalvelinRajaTesti(LuovutusPohja):
    def test_raja_on_sama_kuin_viestiraja(self):
        self.assertEqual(luovutus.LUOVUTUS_YLARAJA, 16_000)
        self.assertEqual(luovutus.LUOVUTUS_YLARAJA, chat.VIESTI_YLARAJA)

    def test_16000_kelpaa_ja_16001_hylataan_ilman_katkaisua(self):
        t = luovutus.tallenna_ehdotus(self.tila.luovutukset, "x" * 16_000, "lohko")
        self.assertEqual(luovutus.lue_ehdotus(self.tila.luovutukset, t)["teksti"], "x" * 16_000)
        ennen = luovutus.listaa_ehdotukset(self.tila.luovutukset)
        with self.assertRaises(yksityinen.YksityinenVirhe) as k:
            luovutus.tallenna_ehdotus(self.tila.luovutukset, "x" * 16_001, "lohko")
        self.assertIn("liian pitk\u00e4", str(k.exception))
        self.assertIn("16\u00a0001", str(k.exception))
        self.assertIn("16\u00a0000", str(k.exception))
        self.assertEqual(luovutus.listaa_ehdotukset(self.tila.luovutukset), ennen)   # mitaan ei tallennettu

    def test_muokkaus_16000_aakkosella_mahtuu_runkoon(self):
        # json.dumps koodaa a-umlautin 6 tavun escapeksi: 16 000 merkkia = 96 000 tavua, yli vanhan 20 000 rajan
        kid = self.uusi()
        t, _ = self.ehdota_luovutus()
        uusi = "\u00e4" * luovutus.LUOVUTUS_YLARAJA
        s, d = self.pyynto("POST", "/api/luovutus/muokkaa", {"keskustelu": kid, "tunnus": t, "teksti": uusi})
        self.assertEqual(s, 200)
        self.assertEqual(d["sha8"], yksityinen.sha(uusi)[:8])
        self.assertEqual(luovutus.lue_ehdotus(self.tila.luovutukset, t)["teksti"], uusi)

    def test_muokkaus_emojeilla_mahtuu_runkoon(self):
        kid = self.uusi()
        t, _ = self.ehdota_luovutus()
        uusi = "\U0001f600" * luovutus.LUOVUTUS_YLARAJA          # ensure_ascii: 12 tavua merkkia kohti
        s, _ = self.pyynto("POST", "/api/luovutus/muokkaa", {"keskustelu": kid, "tunnus": t, "teksti": uusi})
        self.assertEqual(s, 200)

    def test_muokkaus_16001_hylataan_eika_vanhaa_tekstia_muuteta(self):
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus("alkuper\u00e4inen\n")
        s, d = self.pyynto("POST", "/api/luovutus/muokkaa", {"keskustelu": kid, "tunnus": t, "teksti": "x" * 16_001})
        self.assertEqual(s, 400)
        self.assertIn("liian pitk\u00e4", d["virhe"])
        e = luovutus.lue_ehdotus(self.tila.luovutukset, t)
        self.assertEqual(e["teksti"], "alkuper\u00e4inen\n")
        self.assertEqual(e["sha"][:8], s8)
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_kyselymerkkijono_ei_vaihda_rajaa(self):
        # raja valitaan polusta; kyselymerkkijono ei pienenna eika kasvata sita. Reitti itse on edelleen tarkka.
        self.assertEqual(chat.SUURI_RUNKO["/api/luovutus/muokkaa"], chat.LUOVUTUS_RUNKO_YLARAJA)
        kid = self.uusi()
        t, _ = self.ehdota_luovutus()
        uusi = "\u00e4" * luovutus.LUOVUTUS_YLARAJA
        s, d = self.pyynto("POST", "/api/luovutus/muokkaa?x=1", {"keskustelu": kid, "tunnus": t, "teksti": uusi})
        self.assertEqual(s, 200)                       # ei 413 eika 404: raja ja reitti polusta
        self.assertEqual(luovutus.lue_ehdotus(self.tila.luovutukset, t)["teksti"], uusi)
        type(self).vastaus = "Selv\u00e4."
        s, _ = self.pyynto("POST", "/api/viesti?x=1", {"keskustelu": kid, "teksti": "\u00e4" * 16_000})
        self.assertEqual(s, 200)
        self.assertEqual(self.pyynto("POST", "/api/tuntematon?x=1", {"keskustelu": kid})[0], 404)

    def test_muiden_reittien_runkoraja_ei_kasva(self):
        self.assertGreaterEqual(chat.LUOVUTUS_RUNKO_YLARAJA, 12 * luovutus.LUOVUTUS_YLARAJA)
        kid = self.uusi()
        t, s8 = self.ehdota_luovutus()
        for polku, olio in (("/api/luovutus/hyvaksy", {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8}),
                            ("/api/luovutus/hylkaa", {"keskustelu": kid, "tunnus": t}),
                            ("/api/luovutus/uusi", {"keskustelu": kid, "indeksi": 0}),
                            ("/api/luovutus/hyvaksy?x=/api/luovutus/muokkaa", {"keskustelu": kid})):
            olio = dict(olio, taytto="x" * 25_000)
            self.assertEqual(self.pyynto("POST", polku, olio)[0], 413, polku)
        self.assertEqual(self.saapuneet_tiedostot(), [])


class SivuRajaTesti(unittest.TestCase):
    def setUp(self):
        self.h = chat.sivu_html("loopback")
        self.kortti = self.h[self.h.index("async function luovutusKortti("):self.h.index("function luovuta(")]

    def test_selain_kayttaa_samaa_rajaa_kuin_palvelin(self):
        self.assertIn("const LRAJA=%d;" % luovutus.LUOVUTUS_YLARAJA, self.h)
        self.assertNotIn("{LUOVUTUS_YLARAJA}", self.h)

    def test_ei_maxlength_rajaa_joka_katkaisisi_tekstin_hiljaa(self):
        self.assertNotRegex(self.kortti, re.compile("maxlength", re.I))
        self.assertNotIn("8000", self.h)

    def test_laskuri_ja_varoitus_kentassa(self):
        self.assertIn("ta.addEventListener('input',()=>lLaskuri(ta,ll));lLaskuri(ta,ll);", self.kortti)
        self.assertIn("ta.setAttribute('aria-describedby',ll.id)", self.kortti)
        self.assertIn("ll.setAttribute('aria-live','polite')", self.kortti)
        self.assertIn("ll.id='llaskuri-'+(++lLaskureita)", self.kortti)        # yksilollinen myos samalle tunnukselle
        self.assertIn("d.append(va,vk,ta,ll,l,h,vv,ti)", self.kortti)
        self.assertIn("L.textContent=tuhat(n)+' / '+tuhat(LRAJA)", self.h)
        self.assertIn("n>=0.9*LRAJA?' varoitus'", self.h)
        self.assertIn("' \u2013 '+lYlipitka(n)", chat.HTML)
        self.assertIn("raja '+tuhat(LRAJA)+'. Lyhenn\u00e4 teksti\u00e4: ylim\u00e4\u00e4r\u00e4\u00e4 ei katkaista", self.h)

    def test_liian_pitkaa_ei_lahetetaan(self):
        l = self.kortti[self.kortti.index("l.onclick="):]
        tarkistus = "if(lLaskuri(ta,ll)>LRAJA){ti.textContent=lYlipitka(pituus(ta.value));ta.focus();return;}"
        self.assertIn(tarkistus, l)
        self.assertLess(l.index(tarkistus), l.index("/api/luovutus/muokkaa"))
        self.assertLess(l.index(tarkistus), l.index("/api/luovutus/hyvaksy"))

    def test_pituus_koodipisteina_ilman_trimmia_kuten_palvelimella(self):
        self.assertIn("function lLaskuri(ta,L){const n=pituus(ta.value);", self.h)
        self.assertIn("function pituus(s){return Array.from(s).length;}", self.h)

    def test_textcontent_ei_innerhtml(self):
        self.assertIn("L.textContent=", self.h)
        for kielletty in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(kielletty, self.h)

    def test_hyvaksynta_ennallaan(self):
        self.assertIn("vahvistus:'kyll\u00e4 '+e.sha8", self.kortti)
        self.assertIn("if(!confirm('L\u00e4hetet\u00e4\u00e4nk\u00f6 laatikon teksti", self.kortti)


if __name__ == "__main__":
    unittest.main()
