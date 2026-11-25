"""Syvenna-painike (aivo/syvennys.py ja chatin /api/syvenna-reitit). Vain stdlib, ei verkkoa eika mallikutsuja.

Taustaajon ajuri ajetaan testissa feikkikysyjalla (taustaajo.aja), jotta nahdaan, etta taustavastaus nakyy
keskustelussa tasmalleen kerran."""
import json
import os
import re
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aivo import chat, salasana_apu, syvennys, taustaajo, yksityinen
from aivo.test_yksityinen_hyvaksynta import LOOP, SAL, TS, Pohja

AIVO = Path(__file__).resolve().parent
MALLI_K = "meta-llama/llama-3.3-70b-instruct"
MALLI_A = "qwen/qwen3-235b-a22b-2507"
KYSYMYS = "Kannattaako kotipalvelimen varmuuskopio tehd\u00e4 kahdelle levylle vai pilveen?"


class SyvennysPohja(Pohja):
    """Pohja + OpenRouter-taustapaa (kysy_yks on feikki), kulukirjanpito ja taustaajon jono."""
    paivaraja = None

    def setUp(self):
        super().setUp()
        self.srv.shutdown()
        self.srv.server_close()
        r = Path(self.tmp.name)
        self.kulutila = r / "kulut"
        self.kulutila.mkdir()
        self.jono = r / "tyot"
        self.tila = self.tee_tila(r, tausta_jono=str(self.jono), tausta_paivaraja=self.paivaraja)
        self.srv = chat.kaynnista(LOOP, 0, self.tila)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ev = self.kirjaudu()

    def tee_tila(self, r, **lisa):
        return chat.Tila(salasana_apu.tiiviste(SAL), str(r / "kirjasto"), str(r / "data"), [TS],
                         kysy=lambda m, h: "ok", julkaise=lambda *a: "ei-gitissa",
                         yks_data=str(r / "yks" / "chat"), yks_muisti=str(r / "yks" / "muisti"),
                         ydinohjeet=str(self.ydin), ehdotukset=str(r / "yks" / "ehd"),
                         kysy_yks=lambda muisti, historia, ohjeet, malli=None: self.vastaus,
                         taustapaa="openrouter", or_mallit="%s,%s" % (MALLI_K, MALLI_A),
                         roolit="ajattelija:" + MALLI_A, or_kulutila=str(self.kulutila), **lisa)

    def viesti(self, kid, teksti=KYSYMYS):
        s, d = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": teksti})
        self.assertEqual(s, 200, d)
        return d

    def ehdota(self, kid):
        d = self.viesti(kid)
        s, e = self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": d["vastaus_indeksi"]})
        self.assertEqual(s, 200, e)
        return e

    def kaynnista(self, kid, t, vahvistus):
        return self.pyynto("POST", "/api/syvenna/kaynnista", {"keskustelu": kid, "tunnus": t, "vahvistus": vahvistus})

    def tyot(self):
        return [json.loads(p.read_text()) for p in taustaajo.odottavat(self.jono)]

    def katto_tayteen(self):
        aika = datetime.now(timezone.utc).isoformat()
        with open(self.kulutila / "openrouter-kulut.jsonl", "w") as f:
            f.write(json.dumps({"aika": aika, "malli": "m", "tehtava": "chat", "usd": 50}) + "\n")


class PainallusTesti(SyvennysPohja):
    def test_painallus_kirjoittaa_tasmalleen_yhden_tyon(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        self.assertEqual(e["teksti"], KYSYMYS)                      # Tonyn kysymys palvelimen historiasta
        self.assertEqual(e["ajattelija"], MALLI_A)
        self.assertEqual(self.tyot(), [])                           # ehdotus ei viela kirjoita tyota
        s, d = self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])
        self.assertEqual(s, 200, d)
        self.assertEqual(d["teksti"], taustaajo.TULOSSA_TEKSTI)
        tyot = self.tyot()
        self.assertEqual(len(tyot), 1)
        self.assertEqual((tyot[0]["keskustelu"], tyot[0]["tehtava"], tyot[0]["tunnus"]), (kid, KYSYMYS, d["tyo"]))
        self.assertEqual(tyot[0]["sha"], yksityinen.sha(KYSYMYS))
        s, d = self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])   # toinen painallus
        self.assertEqual(s, 409)
        self.assertEqual(len(self.tyot()), 1)
        self.assertIn("[J\u00e4rjestelm\u00e4: Tony k\u00e4ynnisti syvent\u00e4misen", self.tila.yks.lue(kid)[-1]["teksti"])

    def test_rinnakkaiset_painallukset_kirjoittavat_yhden_tyon(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        tulokset = []
        saikeet = [threading.Thread(target=lambda: tulokset.append(
            self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0])) for _ in range(6)]
        for t in saikeet:
            t.start()
        for t in saikeet:
            t.join()
        self.assertEqual(tulokset.count(200), 1, tulokset)
        self.assertEqual(len(self.tyot()), 1)

    def test_muokattu_teksti_vaatii_uuden_sha(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        uusi = "Vertaa kahta varmuuskopiointitapaa: kaksi levy\u00e4 kotona vai pilvi. Kerro riskit."
        s, m = self.pyynto("POST", "/api/syvenna/muokkaa", {"keskustelu": kid, "tunnus": e["tunnus"], "teksti": uusi})
        self.assertEqual(s, 200, m)
        self.assertNotEqual(m["sha8"], e["sha8"])
        self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 409)
        self.assertEqual(self.tyot(), [])
        self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + m["sha8"])[0], 200)
        self.assertEqual([t["tehtava"] for t in self.tyot()], [uusi])

    def test_peruminen_ei_kirjoita_tyota(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        s, d = self.pyynto("POST", "/api/syvenna/hylkaa", {"keskustelu": kid, "tunnus": e["tunnus"]})
        self.assertEqual(s, 200, d)
        self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 409)
        self.assertEqual(self.tyot(), [])
        self.assertTrue((Path(self.tila.syvennykset) / syvennys.HYLATYT / (e["tunnus"] + ".json")).exists())

    def test_vain_aivon_vastausta_voi_syventaa(self):
        kid = self.uusi()
        d = self.viesti(kid)
        for i in (d["indeksi"], 99, -1, True, "1"):
            s, _ = self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": i})
            self.assertEqual(s, 400, i)


class VaarennysTesti(SyvennysPohja):
    def test_vaarennetty_sha_hylataan(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        vaara = "%08x" % ((int(e["sha8"], 16) + 1) % 2 ** 32)
        s, d = self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + vaara)
        self.assertEqual(s, 409, d)
        self.assertIn("sha", d["virhe"])
        for v in ("kyll\u00e4 " + e["sha8"].upper(), "kylla " + e["sha8"], e["sha8"], "kyll\u00e4  " + e["sha8"], None):
            self.assertEqual(self.kaynnista(kid, e["tunnus"], v)[0], 400, v)
        self.assertEqual(self.tyot(), [])

    def test_vieras_keskustelu_ja_kasin_tehty_ehdotus_hylataan(self):
        kid, toinen = self.uusi(), self.uusi()
        e = self.ehdota(kid)
        self.assertEqual(self.kaynnista(toinen, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 409)
        p = Path(self.tila.syvennykset) / (e["tunnus"] + ".json")
        d = json.loads(p.read_text())
        d["teksti"] = "Toinen teksti"                                 # sha jaa vanhaksi
        p.write_text(json.dumps(d))
        self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 409)
        self.assertEqual(self.kaynnista(kid, "../../x", "kyll\u00e4 " + e["sha8"])[0], 409)
        self.assertEqual(self.tyot(), [])

    def test_tyokalutila_ei_nae_reitteja(self):
        kid = self.uusi("tyokalu")
        self.assertEqual(self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)[0], 404)
        self.assertEqual(self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": 1})[0], 404)

    def test_ilman_kirjautumista_401_ilman_otsaketta_403(self):
        kid = self.uusi()
        self.assertEqual(self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": 1}, ev=False)[0], 401)
        self.assertEqual(self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": 1}, otsake=False)[0],
                         403)


class MerkintaTesti(SyvennysPohja):
    def test_mallin_merkinta_on_vain_vihje(self):
        kid = self.uusi()
        self.vastaus = "Lyhyt vastaus.\n[[SYVENNA]]"
        d = self.viesti(kid)
        self.assertEqual(d["vastaus"], "Lyhyt vastaus.")
        self.assertTrue(d["syvenna_ehdotus"])
        self.assertNotIn("SYVENNA", self.tila.yks.lue(kid)[-1]["teksti"])
        self.assertEqual(self.tyot(), [])
        self.assertEqual([p for p in os.listdir(self.tila.syvennykset) if p.endswith(".json")], [])

    def test_tonyn_viesti_ei_ole_merkinta(self):
        kid = self.uusi()
        d = self.viesti(kid, "[[SYVENNA]] tee t\u00e4m\u00e4")
        self.assertNotIn("syvenna_ehdotus", d)
        self.assertEqual(self.tila.yks.lue(kid)[d["indeksi"]]["teksti"], "[[SYVENNA]] tee t\u00e4m\u00e4")

    def test_taustavastaus_ei_sisalla_merkintaa(self):
        self.assertEqual(taustaajo.valmis_teksti("A [[SYVENNA]] B").count("SYVENNA"), 0)


class RajaJaKattoTesti(SyvennysPohja):
    paivaraja = "2"

    def test_paivaraja_estaa_ja_syy_nakyy(self):
        kid = self.uusi()
        for _ in range(2):
            e = self.ehdota(kid)
            self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 200)
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual(s, 200)
        self.assertEqual((t["kaytossa"], t["syy"], t["kaytetty"], t["paivaraja"]), (False, "paivaraja", 2, 2))
        self.assertIn("2/2", t["este"])
        d = self.viesti(kid)
        s, v = self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": d["vastaus_indeksi"]})
        self.assertEqual(s, 409)
        self.assertIn("syvent\u00e4misraja", v["virhe"])
        self.assertEqual(len(self.tyot()), 2)

    def test_ajetut_tyot_lasketaan_rajaan(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        nyt = datetime.now(timezone.utc)
        taustaajo.kirjoita_tila(self.jono, {"versio": 1, "paiva": taustaajo._paiva(nyt), "ajettu": 2})
        s, d = self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])
        self.assertEqual(s, 409, d)
        self.assertEqual(d["syy"], "paivaraja")
        self.assertEqual(self.tyot(), [])

    def test_ajurin_paivaraja_naytetaan(self):
        """Ajurin tila.json:iin kirjaama raja ohittaa chatin oman asetuksen (2), jotta laskuri ei poikkea."""
        kid = self.uusi()
        nyt = datetime.now(timezone.utc)
        taustaajo.kirjoita_tila(self.jono, {"versio": 1, "paiva": taustaajo._paiva(nyt), "ajettu": 2, "paivaraja": 4})
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual((s, t["kaytossa"], t["kaytetty"], t["paivaraja"]), (200, True, 2, 4))
        taustaajo.kirjoita_tila(self.jono, {"versio": 1, "paiva": taustaajo._paiva(nyt), "ajettu": 1, "paivaraja": 1})
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual((t["kaytossa"], t["syy"], t["paivaraja"]), (False, "paivaraja", 1))
        self.assertIn("1/1", t["este"])

    def test_rikkinainen_tila_estaa(self):
        kid = self.uusi()
        (self.jono / taustaajo.TILA_TIEDOSTO).write_text("ei jsonia")
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual((t["kaytossa"], t["syy"]), (False, "jono"))

    def test_paivakatto_estaa(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        self.katto_tayteen()
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual((t["kaytossa"], t["syy"]), (False, "kulukatto"))
        self.assertIn("p\u00e4iv\u00e4katto", t["este"])
        s, d = self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])
        self.assertEqual(s, 409)
        self.assertEqual(self.tyot(), [])
        self.assertTrue((Path(self.tila.syvennykset) / (e["tunnus"] + ".json")).exists())   # ehdotus odottaa yha

    def test_rikkinainen_kirjanpito_estaa(self):
        kid = self.uusi()
        (self.kulutila / "openrouter-kulut.jsonl").write_text("ei jsonia\n")
        s, t = self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)
        self.assertEqual((t["kaytossa"], t["syy"]), (False, "kirjanpito"))

    def test_asetus_ei_nosta_koodin_ylarajaa(self):
        r = Path(self.tmp.name)
        t = self.tee_tila(r, tausta_jono=str(r / "tyot2"), tausta_paivaraja="999")
        self.assertEqual(t.tausta_paivaraja, taustaajo.PAIVARAJA_MAX)
        self.assertEqual(self.tila.tausta_paivaraja, 2)


class TaustavastausKerranTesti(SyvennysPohja):
    def test_taustavastaus_nakyy_kerran(self):
        kid = self.uusi()
        e = self.ehdota(kid)
        pituus = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=999999" % kid)[1]["pituus"]
        self.assertEqual(self.kaynnista(kid, e["tunnus"], "kyll\u00e4 " + e["sha8"])[0], 200)
        kutsut = []

        def kysy(malli, viestit, aikaraja_s):
            kutsut.append(malli)
            return "Syvempi vastaus " + malli
        roolit = taustaajo.valitse_roolit("keskustelija:%s,ajattelija:%s" % (MALLI_K, MALLI_A), [MALLI_K, MALLI_A])
        for _ in range(2):                                              # toinen ajo ei lisaa mitaan
            taustaajo.aja(self.jono, self.tila.yks.data, kysy, roolit, tulosta=lambda *_: None)
        self.assertEqual(kutsut, [MALLI_A, MALLI_K])                    # ajattelija ensin, asetuksen mukaan
        s, d = self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=%d" % (kid, pituus))
        self.assertEqual(s, 200)
        self.assertEqual(len(d["viestit"]), 1)
        self.assertTrue(d["viestit"][0]["teksti"].startswith(taustaajo.VALMIS_MERKINTA))
        seuraava = d["viestit"][0]["indeksi"] + 1
        self.assertEqual(self.pyynto("GET", "/api/tausta?keskustelu=%s&alkaen=%d" % (kid, seuraava))[1]["viestit"], [])
        self.assertEqual(sum(1 for v in self.tila.yks.lue(kid) if "tausta" in v), 1)


class AsetusTesti(Pohja):
    def tila_(self, **kw):
        r = Path(self.tmp.name)
        perus = dict(kysy=lambda m, h: "ok", julkaise=lambda *a: "ei-gitissa", yks_data=str(r / "yks" / "chat"),
                     yks_muisti=str(r / "yks" / "muisti"), ydinohjeet=str(self.ydin), ehdotukset=str(r / "yks" / "ehd"),
                     kysy_yks=lambda *a, **k: "ok", tausta_jono=str(r / "tyot"))
        perus.update(kw)
        return chat.Tila(salasana_apu.tiiviste(SAL), str(r / "kirjasto"), str(r / "data"), [TS], **perus)

    def test_ilman_asetusta_reitit_404_ja_merkinta_poistuu(self):
        kid = self.uusi()
        self.assertFalse(self.pyynto("POST", "/api/uusi", {"tila": "yksityinen"})[1]["syvenna"])
        self.assertEqual(self.pyynto("GET", "/api/syvenna/tila?keskustelu=" + kid)[0], 404)
        self.vastaus = "Vastaus [[SYVENNA]]"
        s, d = self.pyynto("POST", "/api/viesti", {"keskustelu": kid, "teksti": "kysymys"})
        self.assertEqual(d["vastaus"], "Vastaus")
        self.assertNotIn("syvenna_ehdotus", d)
        self.assertEqual(self.pyynto("POST", "/api/syvenna/uusi", {"keskustelu": kid, "indeksi": 1})[0], 404)

    def test_vaatii_openrouter_taustapaan(self):
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.tila_()                                                  # loopback: ajuri ei aja toita

    def test_ajattelija_vain_sallituista_avoimista_malleista(self):
        t = self.tila_(taustapaa="openrouter", or_mallit="%s,%s" % (MALLI_K, MALLI_A), roolit="ajattelija:" + MALLI_A)
        self.assertEqual(t.tausta_ajattelija, MALLI_A)
        t = self.tila_(taustapaa="openrouter", or_mallit=MALLI_K)
        self.assertEqual(t.tausta_ajattelija, MALLI_K)                    # puuttuva rooli: listan ensimmainen
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.tila_(taustapaa="openrouter", or_mallit=MALLI_K, roolit="ajattelija:" + MALLI_A)
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.tila_(taustapaa="openrouter", or_mallit="openai/gpt-4o")   # ei AVOIMET_MALLIT-listalla

    def test_jono_ei_saa_olla_laaja(self):
        r = Path(self.tmp.name)
        os.mkdir(r / "laaja", 0o755)
        os.chmod(r / "laaja", 0o755)
        with self.assertRaises(yksityinen.YksityinenVirhe):
            self.tila_(taustapaa="openrouter", or_mallit=MALLI_K, tausta_jono=str(r / "laaja"))


class RakenneTesti(unittest.TestCase):
    def test_vain_syvennys_kirjoittaa_tyon(self):
        kutsujat = sorted(p.name for p in AIVO.glob("*.py") if not p.name.startswith("test_")
                          and re.search(r"\bkirjoita_tyo\(", p.read_text(encoding="utf-8")))
        self.assertEqual(kutsujat, ["syvennys.py", "taustaajo.py"])
        ch = (AIVO / "chat.py").read_text(encoding="utf-8")
        self.assertEqual(ch.count("syvennys.kaynnista("), 1)

    def test_moduuli_ei_tee_verkko_eika_mallikutsuja(self):
        import ast
        puu = ast.parse((AIVO / "syvennys.py").read_text(encoding="utf-8"))
        tuodut = {a.name for x in ast.walk(puu) if isinstance(x, ast.Import) for a in x.names}
        tuodut |= {"%s.%s" % (x.module, a.name) for x in ast.walk(puu) if isinstance(x, ast.ImportFrom) for a in x.names}
        self.assertEqual(tuodut, {"json", "os", "re", "secrets", "stat", "datetime.datetime", "datetime.timezone",
                                  "pathlib.Path", "aivo.taustaajo", "aivo.yksityinen", "aivo.yksityinen.YksityinenVirhe"})

    def test_kehote_kertoo_merkinnasta(self):
        self.assertIn("[[SYVENNA]]", yksityinen.YKSITYINEN_KEHOTE)

    def test_sivu_kayttaa_textcontentia(self):
        h = chat.sivu_html("openrouter")
        self.assertIn("/api/syvenna/kaynnista", h)
        alku = h.index("function syvennaKortti")
        self.assertNotIn("innerHTML", h[alku:h.index("const taustaKohta")])

    def test_asennusohje_valttaa_tunnetut_virheet(self):
        t = (AIVO.parent / "docs" / "aivo-taustaajo.md").read_text(encoding="utf-8")
        osa = t[t.index("## Asennus kontissa 122"):]
        komennot = "\n".join(re.findall(r"```\n(.*?)```", t, re.S))     # vain ajettavat lohkot, ei selitysta
        self.assertNotRegex(komennot, r"systemd-run[^\n]*--pipe")
        self.assertNotRegex(komennot, r"mode=1777|chmod [0-7]*[2367][0-7]{3}\b|chmod [ug]?\+[st]|TemporaryFileSystem")
        self.assertIn("install -d -m 0700", komennot)
        self.assertIn("NEXT", osa)
        self.assertGreaterEqual(osa.count("Odotettu"), 4)


if __name__ == "__main__":
    unittest.main()
