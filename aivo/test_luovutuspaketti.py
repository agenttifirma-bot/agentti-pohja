"""Luovutuspaketti: monta palaa, yksi hyvaksynta (aivo/luovutuspaketti.py). Vain stdlib."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from aivo import chat, luovutus, luovutuspaketti as lp, yksityinen
from aivo.test_luovutus import LuovutusPohja

SALAINEN = "PAKETTI-SALAISUUS-31"
PAKETTI = ("Suunnitelma valmis.\n[[LUOVUTUSPAKETTI Mittari X]]\n[[PALA 1]]\nRakenna %s osa A.\n[[/PALA]]\n"
           "[[PALA 2]]\nRakenna osa B.\n[[/PALA]]\n[[PALA 3]]\nKirjoita testit.\n[[/PALA]]\n[[/LUOVUTUSPAKETTI]]\n"
           % SALAINEN)


def sallii(teksti):
    return {"tila": "tarkistettu", "sallittu": True, "merkinnat": ["ok"]}


def estaa_c(teksti):
    return {"tila": "tarkistettu", "sallittu": "ESTA" not in teksti, "merkinnat": ["vuoto?"] if "ESTA" in teksti else []}


class PakettiPohja(LuovutusPohja):
    def paketti(self, kid=None, vastaus=PAKETTI):
        kid = kid or self.uusi()
        self.vastaus = vastaus
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "pilko ty\u00f6"})
        self.assertEqual(s, 200)
        [t] = v["paketit"]
        return kid, t, v

    def hae(self, kid, t):
        s, d = self.pyynto("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (kid, t))
        self.assertEqual(s, 200)
        return d

    def hyvaksy_p(self, kid, t, vahvistus, lisa=True):
        """lisa=True: mukana vuotovartijan "kysy"-lisavahvistus samasta sha8:sta (paketin palat ovat aina kysy)."""
        d = {"keskustelu": kid, "tunnus": t, "vahvistus": vahvistus}
        if lisa and isinstance(vahvistus, str):
            d["lisavahvistus"] = "tarkistin kohdat " + vahvistus[-8:]
        return self.pyynto("POST", "/api/paketti/hyvaksy", d)


class ShaTesti(PakettiPohja):
    def test_mallin_paketti_luo_vain_ehdotuksen(self):
        kid, t, v = self.paketti()
        self.assertIn("Luovutuspaketti tallennettu (tunnus %s, 3 palaa)" % t, v["vastaus"])
        self.assertNotIn(SALAINEN, v["vastaus"])
        self.assertNotIn("luovutukset", v)                # paketin sisainen teksti ei ole yksittainen luovutus
        d = self.hae(kid, t)
        self.assertEqual([p["n"] for p in d["palat"]], [1, 2, 3])
        self.assertEqual(d["palat"][0]["teksti"], "Rakenna %s osa A.\n" % SALAINEN)
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_sha_kattaa_kaikki_palat(self):
        palat = [(1, "a\n"), (2, "b\n"), (3, "c\n")]
        perus = lp.paketin_sha("N", [{"n": n, "teksti": x} for n, x in palat])
        for i in range(3):
            muutettu = [dict(n=n, teksti=x + ("!" if j == i else "")) for j, (n, x) in enumerate(palat)]
            self.assertNotEqual(lp.paketin_sha("N", muutettu), perus, i)
        self.assertNotEqual(lp.paketin_sha("M", [{"n": n, "teksti": x} for n, x in palat]), perus)
        self.assertNotEqual(lp.paketin_sha("N", [{"n": n + 1, "teksti": x} for n, x in palat]), perus)
        # tallennetun paketin muuttaminen levylla rikkoo tarkisteen
        kid, t, v = self.paketti()
        p = Path(self.tila.luovutukset) / lp.PAKETIT / (t + ".json")
        d = json.loads(p.read_text())
        d["palat"][2]["teksti"] = "vaihdettu\n"
        p.write_text(json.dumps(d))
        self.assertEqual(self.pyynto("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (kid, t))[0], 400)

    def test_palan_poisto_vaihtaa_sha_ja_vanha_vahvistus_ei_kelpaa(self):
        kid, t, v = self.paketti()
        vanha = self.hae(kid, t)["sha8"]
        s, d = self.pyynto("POST", "/api/paketti/poista-pala", {"keskustelu": kid, "tunnus": t, "pala": 1, "sha8": vanha})
        self.assertEqual(s, 200)
        uusi = d["paketti"]["sha8"]
        self.assertNotEqual(uusi, vanha)
        self.assertEqual([p["n"] for p in d["paketti"]["palat"]], [2, 3])
        self.assertEqual(self.hyvaksy_p(kid, t, "kyll\u00e4 " + vanha)[0], 409)
        self.assertEqual(self.saapuneet_tiedostot(), [])
        # vanhentunut nakyma ei voi poistaa palaa
        s, _ = self.pyynto("POST", "/api/paketti/poista-pala", {"keskustelu": kid, "tunnus": t, "pala": 2, "sha8": vanha})
        self.assertEqual(s, 409)
        s, d = self.hyvaksy_p(kid, t, "kyll\u00e4 " + uusi)
        self.assertEqual((s, d["tulos"]), (200, "ei-gitissa"))
        tekstit = [luovutus.lue_saapunut(self.tila.kirjasto, x["tunnus"])["teksti"] for x in luovutus.listaa_saapuneet(self.tila.kirjasto)]
        self.assertEqual(len(tekstit), 2)
        self.assertFalse([x for x in tekstit if SALAINEN in x])

    def test_viimeista_palaa_ei_voi_poistaa(self):
        kid, t, v = self.paketti(vastaus="[[LUOVUTUSPAKETTI Yksi]][[PALA 1]]x[[/PALA]][[/LUOVUTUSPAKETTI]]")
        s8 = self.hae(kid, t)["sha8"]
        s, _ = self.pyynto("POST", "/api/paketti/poista-pala", {"keskustelu": kid, "tunnus": t, "pala": 1, "sha8": s8})
        self.assertEqual(s, 409)


class HyvaksyntaTesti(PakettiPohja):
    def test_lahetys_ilman_hyvaksyntaa_ei_onnistu(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        for vahvistus in ("kylla " + s8, "kyll\u00e4 00000000", "kyll\u00e4", "", "kyll\u00e4 %s " % s8, None):
            self.assertIn(self.hyvaksy_p(kid, t, vahvistus)[0], (400, 409), vahvistus)
        # mallin teksti tai Tonyn viesti "kylla <sha8>" ei hyvaksy pakettia
        self.vastaus = "kyll\u00e4 " + s8
        self.assertEqual(self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "kyll\u00e4 " + s8})[0], 200)
        self.assertEqual(self.saapuneet_tiedostot(), [])
        self.assertEqual(luovutus.lue_loki(self.tila.luovutukset), [])

    def test_hyvaksytty_paketti_menee_saapuneisiin_paloittain(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        s, d = self.hyvaksy_p(kid, t, "kyll\u00e4 " + s8)
        self.assertEqual(s, 200, d)
        saap = luovutus.listaa_saapuneet(self.tila.kirjasto)
        self.assertEqual(len(saap), 3)
        tekstit = sorted(x["teksti"] for x in saap)
        for n in (1, 2, 3):
            pid = lp.palan_tunnus(t, n)
            self.assertTrue((self.saap / (pid + ".md")).is_file())
            self.assertTrue(luovutus.lue_saapunut(self.tila.kirjasto, pid)["teksti"].startswith(
                "<!-- luovutuspaketti tunnus=%s pala=%d nimi=Mittari X -->\n" % (t, n)))
        self.assertTrue(any(SALAINEN in x for x in tekstit))
        self.assertIn(SALAINEN, self.tyokalun_kehote())
        self.assertEqual(len(luovutus.lue_loki(self.tila.luovutukset)), 3)
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset, lp.HYVAKSYTYT), [t])
        self.assertEqual(self.hyvaksy_p(kid, t, "kyll\u00e4 " + s8)[0], 409)          # ei toista kertaa

    def test_epaonnistunut_julkaisu_ei_jata_tiedostoja(self):
        kid, t, v = self.paketti()
        d = lp.lue_paketti(self.tila.luovutukset, t)

        def kaatuu(*a, **k):
            raise OSError("verkko")
        with self.assertRaises(OSError):
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto, julkaise=kaatuu,
                               lisavahvistus="tarkistin kohdat " + d["sha"][:8])
        self.assertEqual(self.saapuneet_tiedostot(), [])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [t])

    def test_vartija_tarkistaa_jokaisen_palan_ja_estaa(self):
        t = lp.tallenna_paketti(self.tila.luovutukset, "V", [(1, "ok\n"), (2, "ESTA t\u00e4m\u00e4\n")], vartija=estaa_c)
        d = lp.lue_paketti(self.tila.luovutukset, t)
        self.assertEqual([p["vartija"]["sallittu"] for p in d["palat"]], [True, False])
        with self.assertRaises(yksityinen.YksityinenVirhe):
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                               julkaise=lambda *a, **k: "ei-gitissa", vartija=estaa_c)
        self.assertEqual(self.saapuneet_tiedostot(), [])
        d = lp.poista_pala(self.tila.luovutukset, t, 2, d["sha"][:8])
        lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                           julkaise=lambda *a, **k: "ei-gitissa", vartija=estaa_c)
        self.assertEqual(len(self.saapuneet_tiedostot()), 1)

    def test_vartijan_epatyypillinen_sallittu_estaa(self):
        # 0 == False, mutta 0 is not False: aiemmin sallittu=0 tallentui sellaisenaan eika estanyt lahetysta
        for arvo in (0, 1, 0.0, "true", "False", []):
            def vartija(teksti, arvo=arvo):
                return {"tila": "tarkistettu", "sallittu": arvo, "merkinnat": ["vuoto"]}
            t = lp.tallenna_paketti(self.tila.luovutukset, "V", [(1, "x %r\n" % (arvo,))], vartija=vartija)
            d = lp.lue_paketti(self.tila.luovutukset, t)
            self.assertIs(d["palat"][0]["vartija"]["sallittu"], False, arvo)
            with self.assertRaises(yksityinen.YksityinenVirhe):
                lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + d["sha"][:8], self.tila.kirjasto,
                                   julkaise=lambda *a, **k: "ei-gitissa", vartija=vartija)
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_koukku_kayttaa_mekaanista_vartijaa(self):
        r = lp.vartija_koukku("teksti")
        self.assertEqual((r["tila"], r["sallittu"]), ("kysy", None))     # malli ei tarkista paloja -> kysy
        r = lp.vartija_koukku("Kone on " + ".".join(["10", "1", "2", "3"]) + ".\n")
        self.assertEqual((r["tila"], r["sallittu"]), ("esta", False))
        self.assertEqual(r["merkinnat"], ["Estetty: yksityinen IP-osoite"])         # tyyppi, ei sisaltoa
        kid, t, v = self.paketti()
        for p in self.hae(kid, t)["palat"]:
            self.assertIn("Vartijamalli ei tarkista paketin paloja", p["vartija"]["merkinnat"][-1])

    def test_hylkays_siirtaa_eika_poista(self):
        kid, t, v = self.paketti()
        s, _ = self.pyynto("POST", "/api/paketti/hylkaa", {"keskustelu": kid, "tunnus": t})
        self.assertEqual(s, 200)
        self.assertTrue((Path(self.tila.luovutukset) / lp.PAKETIT / "hylatyt" / (t + ".json")).is_file())
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [])

    def test_katkennut_ja_tyhja_paketti_ei_tallennu(self):
        kid = self.uusi()
        for vastaus, odotus in (("[[LUOVUTUSPAKETTI X]]\n[[PALA 1]]\n%s" % SALAINEN, "vastaus katkesi"),
                                ("[[LUOVUTUSPAKETTI X]]ei paloja %s[[/LUOVUTUSPAKETTI]]" % SALAINEN, "ei ole paloja"),
                                ("[[LUOVUTUSPAKETTI <b>]][[PALA 1]]x[[/PALA]][[/LUOVUTUSPAKETTI]]", "nimi ei kelpaa"),
                                ("[[LUOVUTUSPAKETTI X]][[PALA 1]]a[[/PALA]][[PALA 1]]b[[/PALA]][[/LUOVUTUSPAKETTI]]", "toistuu")):
            self.vastaus = vastaus
            s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "x"})
            self.assertEqual(s, 200)
            self.assertNotIn("paketit", v)
            self.assertIn(odotus, v["vastaus"])
            self.assertNotIn(SALAINEN, v["vastaus"])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [])


class LisapalatTesti(PakettiPohja):
    def hyvaksytty(self):
        kid, t, v = self.paketti()
        self.hyvaksy_p(kid, t, "kyll\u00e4 " + self.hae(kid, t)["sha8"])
        return kid, t

    def test_oletus_on_kysy_ja_lisapala_vaatii_oman_hyvaksynnan(self):
        self.assertEqual(self.tila.lisapalat, "kysy")
        self.assertEqual(chat.Tila.__init__.__defaults__[-1], "kysy")
        kid, t = self.hyvaksytty()
        ennen = self.saapuneet_tiedostot()
        self.vastaus = "Lis\u00e4\u00e4:\n[[LISAPALA %s]]\nOsa D.\n[[/LISAPALA]]" % t
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "jatka"})
        self.assertEqual(s, 200)
        [lt] = v["paketit"]
        self.assertNotIn("lisapalat", v)
        self.assertEqual(self.saapuneet_tiedostot(), ennen)
        d = self.hae(kid, lt)
        self.assertEqual((d["jatkaa"], [p["n"] for p in d["palat"]]), (t, [4]))
        s, _ = self.hyvaksy_p(kid, lt, "kyll\u00e4 " + d["sha8"])
        self.assertEqual(s, 200)
        self.assertTrue((self.saap / (lp.palan_tunnus(t, 4) + ".md")).is_file())

    def test_automaattinen_vain_vartijan_hyvaksymana(self):
        kid, t = self.hyvaksytty()
        self.tila.lisapalat = "automaattinen"
        ennen = self.saapuneet_tiedostot()
        # ilman vartijaa ei lahde automaattisesti
        self.vastaus = "[[LISAPALA %s]]\nOsa D.\n[[/LISAPALA]]" % t
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "jatka"})
        self.assertEqual(len(v["paketit"]), 1)
        self.assertEqual(self.saapuneet_tiedostot(), ennen)
        # vartijan hyvaksyma lahtee ilman painallusta ja yhteenveto kirjataan
        tunnus, lahti, yht = lp.tallenna_lisapalat(self.tila.luovutukset, self.tila.kirjasto, t, ["Osa E.\n"],
                                                   "automaattinen", julkaise=lambda *a, **k: "ei-gitissa", vartija=sallii)
        self.assertTrue(lahti)
        self.assertIn("automaattisesti", yht)
        self.assertTrue((self.saap / (lp.palan_tunnus(t, 5) + ".md")).is_file())
        loki = (Path(self.tila.luovutukset) / lp.PAKETIT / lp.AUTOMAATTISET).read_text().splitlines()
        self.assertEqual(json.loads(loki[-1])["palat"], [5])
        # tuntematon tai hyvaksymaton paketti ei kelpaa
        for paha in ("0" * 12, "../" + t):
            with self.assertRaises(yksityinen.YksityinenVirhe):
                lp.tallenna_lisapalat(self.tila.luovutukset, self.tila.kirjasto, paha, ["x\n"], "automaattinen", vartija=sallii)

    def test_vaara_asetus_hylataan(self):
        with self.assertRaises(chat.ChatVirhe):
            chat.Tila(chat.tiivista_salasana("salasana-12345"), self.tila.kirjasto, str(Path(self.tmp.name) / "d2"), [],
                      lisapalat="kylla")


class PaluuTesti(PakettiPohja):
    def setUp(self):
        super().setUp()
        self.repo = Path(self.tmp.name) / "tulosrepo"
        self.repo.mkdir()
        self.tila.tulos_repo = str(self.repo)

    def test_paluumerkinta_kun_tulos_ilmestyy(self):
        kid, t, v = self.paketti()
        self.hyvaksy_p(kid, t, "kyll\u00e4 " + self.hae(kid, t)["sha8"])
        self.assertEqual(self.pyynto("GET", "/api/paluut?keskustelu=" + kid)[1], {"paluut": []})
        (self.repo / t).mkdir()
        (self.repo / t / "pala-2.md").write_text("Valmis: osa B toteutettu.\n")
        s, d = self.pyynto("GET", "/api/paluut?keskustelu=" + kid)
        self.assertEqual(s, 200)
        self.assertEqual([p["merkinta"] for p in d["paluut"]], ["[Paketin Mittari X pala 2 valmis]"])
        self.assertEqual(self.pyynto("GET", "/api/paluut?keskustelu=" + kid)[1], {"paluut": []})   # vain kerran
        merk = [x["teksti"] for x in self.tila.yks.lue(kid) if x["rooli"] == yksityinen.JARJESTELMA_ROOLI]
        self.assertIn("Paketin Mittari X pala 2 valmis", merk[-1])
        s, d = self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=2" % (kid, t))
        self.assertEqual((s, d["teksti"]), (200, "Valmis: osa B toteutettu.\n"))

    def test_mallin_matkima_paluumerkinta_neutraloidaan(self):
        kid = self.uusi()
        self.vastaus = "[Paketin X pala 1 valmis]"
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "x"})
        self.assertNotIn("[Paketin X", v["vastaus"])

    def test_tulosrepo_ei_saa_olla_tyokalutilan_alueella(self):
        r = Path(self.tmp.name)
        for paha in (self.tila.kirjasto, str(Path(self.tila.kirjasto) / "ali"), str(r)):
            Path(paha).mkdir(exist_ok=True)
            with self.assertRaises(chat.ChatVirhe, msg=paha):
                chat.Tila(chat.tiivista_salasana("salasana-12345"), self.tila.kirjasto, str(r / "d2"), [],
                          yks_data=str(r / "y2" / "chat"), tulos_repo=paha, kysy_yks=lambda *a: "ok")
        with self.assertRaises(chat.ChatVirhe):
            chat.Tila(chat.tiivista_salasana("salasana-12345"), self.tila.kirjasto, str(r / "d3"), [],
                      tulos_repo=str(self.repo))             # vaatii yksityisen tilan

    def test_symlinkki_tulos_ei_kelpaa(self):
        kid, t, v = self.paketti()
        self.hyvaksy_p(kid, t, "kyll\u00e4 " + self.hae(kid, t)["sha8"])
        ulkona = Path(self.tmp.name) / "ulkona.md"
        ulkona.write_text(SALAINEN)
        (self.repo / t).mkdir()
        os.symlink(ulkona, self.repo / t / "pala-1.md")
        self.assertEqual(self.pyynto("GET", "/api/paluut?keskustelu=" + kid)[1], {"paluut": []})
        self.assertEqual(self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=1" % (kid, t))[0], 404)


class RajatTesti(PakettiPohja):
    def test_tyokalutila_ei_nae_pakettia_ennen_hyvaksyntaa(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        repo = Path(self.tmp.name) / "tulosrepo"
        (repo / t).mkdir(parents=True)
        (repo / t / "pala-1.md").write_text("TULOS-%s" % SALAINEN)
        self.tila.tulos_repo = str(repo)
        tkid = self.uusi("tyokalu")
        for metodi, polku, olio in (("GET", "/api/paketit?keskustelu=" + tkid, None),
                                    ("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (tkid, t), None),
                                    ("GET", "/api/paluut?keskustelu=" + tkid, None),
                                    ("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=1" % (tkid, t), None),
                                    ("GET", "/api/paketit", None),
                                    ("POST", "/api/paketti/poista-pala", {"keskustelu": tkid, "tunnus": t, "pala": 1, "sha8": s8}),
                                    ("POST", "/api/paketti/hyvaksy", {"keskustelu": tkid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8}),
                                    ("POST", "/api/paketti/hylkaa", {"keskustelu": tkid, "tunnus": t})):
            self.assertEqual(self.pyynto(metodi, polku, olio)[0], 404, polku)
        self.assertNotIn(SALAINEN, self.tyokalun_kehote())
        self.assertEqual(self.pyynto("GET", "/api/saapuneet?keskustelu=" + tkid)[1], {"saapuneet": []})
        # tyokalutilan vastauksen paketti- tai lisapalalohko ei luo mitaan
        self.vastaus = PAKETTI + "[[LISAPALA %s]]x[[/LISAPALA]]" % t
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": tkid, "teksti": "moi"})
        self.assertNotIn("paketit", v)
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [t])
        # hyvaksynnan jalkeenkin tyokalutila nakee vain saapuneet, ei tulosrepoa
        self.hyvaksy_p(kid, t, "kyll\u00e4 " + s8)
        k = self.tyokalun_kehote()
        self.assertIn(SALAINEN, k)
        self.assertNotIn("TULOS-" + SALAINEN, k)

    def test_polkujen_ohitus_estetty(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        repo = Path(self.tmp.name) / "tulosrepo"
        repo.mkdir()
        self.tila.tulos_repo = str(repo)
        ulkona = Path(self.tmp.name) / "ulkona.json"
        ulkona.write_text(json.dumps({"nimi": "x", "palat": [], "sha": "0"}))
        for paha in ("../ulkona", "../../ulkona", "/etc/passwd", t + "/../" + t, t.upper(), "a" * 13, "", None, 5):
            self.assertEqual(self.pyynto("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (kid, paha))[0], 400, paha)
            for polku, lisa in (("/api/paketti/hyvaksy", {"vahvistus": "kyll\u00e4 " + s8}),
                                ("/api/paketti/poista-pala", {"pala": 1, "sha8": s8}), ("/api/paketti/hylkaa", {})):
                s = self.pyynto("POST", polku, dict({"keskustelu": kid, "tunnus": paha}, **lisa))[0]
                self.assertIn(s, (400, 409), (polku, paha))
            self.assertIn(self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=1" % (kid, paha))[0], (400, 404))
        for pala in ("../1", "-1", "1/../2", "100", "x", ""):
            self.assertEqual(self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=%s" % (kid, t, pala))[0], 400, pala)
        for pala in (True, "1", 0, 100, None):
            s = self.pyynto("POST", "/api/paketti/poista-pala", {"keskustelu": kid, "tunnus": t, "pala": pala, "sha8": s8})[0]
            self.assertIn(s, (400, 409), pala)
        self.assertTrue(ulkona.is_file())
        self.assertEqual(self.saapuneet_tiedostot(), [])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [t])

    def test_palan_numero_vain_ascii_numeroina(self):
        # "\u00b2".isdigit() on tosi, mutta int() kaatuu: palvelin katkaisi yhteyden ja poikkeusteksti meni stderriin
        kid, t, v = self.paketti()
        self.tila.tulos_repo = self.tmp.name
        for pala in ("%C2%B2", "%E2%91%A0", "%EF%BC%91", "%D9%A1"):
            s = self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=%s" % (kid, t, pala))[0]
            self.assertEqual(s, 400, pala)

    def test_ilman_kirjautumista_401_ilman_otsaketta_403(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        for metodi, polku, olio in (("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (kid, t), None),
                                    ("POST", "/api/paketti/hyvaksy", {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8})):
            self.assertEqual(self.pyynto(metodi, polku, olio, ev=False)[0], 401, polku)
            self.assertEqual(self.pyynto(metodi, polku, olio, otsake=False)[0], 403, polku)
        self.assertEqual(self.saapuneet_tiedostot(), [])

    def test_yksittainen_luovutus_ennallaan(self):
        kid = self.uusi()
        self.vastaus = "[[LUOVUTUS]]\nyksi teksti\n[[/LUOVUTUS]]"
        s, v = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "x"})
        [t] = v["luovutukset"]
        self.assertNotIn("paketit", v)
        s, d = self.hyvaksy_l(kid, t, "kyll\u00e4 " + yksityinen.sha("yksi teksti\n")[:8])
        self.assertEqual(s, 200)
        self.assertEqual(luovutus.lue_saapunut(self.tila.kirjasto, t)["teksti"], "yksi teksti\n")


class KyselymerkkijonoTesti(PakettiPohja):
    # reitti valitaan polusta ilman kyselymerkkijonoa kuten muilla POST-reiteilla (#429); ennen korjausta 404
    def test_pakettireitit_toimivat_kyselymerkkijonon_kanssa(self):
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        s, d = self.pyynto("POST", "/api/paketti/poista-pala?x=1", {"keskustelu": kid, "tunnus": t, "pala": 1, "sha8": s8})
        self.assertEqual(s, 200, d)
        uusi = d["paketti"]["sha8"]
        s, d = self.pyynto("POST", "/api/paketti/hyvaksy?x=1", {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + uusi,
                                                               "lisavahvistus": "tarkistin kohdat " + uusi})
        self.assertEqual((s, d.get("tulos")), (200, "ei-gitissa"), d)
        self.assertEqual(len(luovutus.listaa_saapuneet(self.tila.kirjasto)), 2)
        kid2, t2, _ = self.paketti()
        s, d = self.pyynto("POST", "/api/paketti/hylkaa?x=1", {"keskustelu": kid2, "tunnus": t2})
        self.assertEqual(s, 200, d)
        self.assertTrue((Path(self.tila.luovutukset) / lp.PAKETIT / "hylatyt" / (t2 + ".json")).is_file())

    def test_kyselymerkkijono_ei_vaihda_reittia(self):
        # kyselyosa ei voi ohjata pyyntoa toiselle reitille; tuntematon polku on edelleen 404
        kid, t, v = self.paketti()
        s8 = self.hae(kid, t)["sha8"]
        self.assertEqual(self.pyynto("POST", "/api/paketti/tuntematon?/api/paketti/hyvaksy",
                                     {"keskustelu": kid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8})[0], 404)
        self.assertEqual(self.saapuneet_tiedostot(), [])


class SivuTesti(unittest.TestCase):
    def test_sivu_textcontent(self):
        h = chat.sivu_html("loopback")
        for t in ("L\u00e4het\u00e4 paketti", "Poista pala ", "N\u00e4m\u00e4 palat l\u00e4htev\u00e4t Clauden pilveen",
                  "/api/paketti/hyvaksy", "/api/paketti/poista-pala", "vahvistus:'kyll\u00e4 '+e.sha8",
                  "pre.textContent=p.teksti", "li.textContent=String(m)", "lisaa('aivo',p.merkinta)",
                  "pre.textContent=y.r.ok?y.j.teksti"):
            self.assertIn(t, h)
        for kielletty in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(kielletty, h)

    def test_kehote_kertoo_paketista(self):
        from aivo import yksityinen_or
        for k in (yksityinen.YKSITYINEN_KEHOTE, yksityinen_or.KEHOTE):
            self.assertIn("[[LUOVUTUSPAKETTI nimi]] [[PALA 1]] teksti [[/PALA]]", k)


if __name__ == "__main__":
    unittest.main()
