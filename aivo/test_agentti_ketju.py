"""Agenttitehtavan koko ketju paasta paahan (eristettyjen agenttien osat 2-4). Vain stdlib.

Ketju: mallin [[AGENTTI]]-lohko chatissa (POST /api/viesti) -> tallenna_ehdotus -> POST /api/agentti/kaynnista
(kaynnista, jono/<tunnus>.json) -> ajurin oikea kasittelyfunktio agentti_ajuri.aja_seuraava -> lapsi ->
malli.aja (suunnittelija, tekija ja silmukka tyokaluineen, tarkastaja) -> tulokset/<tunnus>.json ja tiedostokopiot
-> lue_tulos / nayttotulos -> GET /api/agentti ja /api/agentti/tiedosto.

Korvike: ainoa korvattu kohta on aliprosessin kaynnistys. Testi ajaa lapsen samassa prosessissa samoilla
argumenteilla, jotka ajuri antaisi komentorivilla (lapsikomento: --juuri, --roolit), ja kuljettaa tuloksen JSON-
merkkijonona kuten aliprosessin stdout. Mallikutsu kulkee oikean reitin openrouter_kulut.kutsu -> yksityinen_or-
kuljetin, mutta HTTP-avaus (avaa) on korvikemalli, joka palauttaa ennalta kirjoitetut vastaukset rooleittain.
Ei verkkoa, ei oikeita avaimia eika mallikutsuja. Rajoja, kattoa tai mallilistaa ei muuteta.

Chat ja ajuri kayttavat samaa kulukirjanpitoa (tilapaiskansio), kuten tuotannossa (yhteinen paivakatto).
"""
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from aivo import agentti_ajuri as aj
from aivo import agenttitehtava as at
from aivo import openrouter_kulut as ok
from aivo import yksityinen
from aivo.agentti import malli as am
from aivo.test_agentti_malli import AVAIN, MALLI, Vastaus, _rooli
from aivo.test_agenttitehtava import AgenttiPohja

TEHTAVA = "Kirjoita tiedosto yhteenveto.md, jossa on kolme rivi\u00e4 aiheesta X.\n"
SISALTO = "rivi 1\\nrivi 2\\nrivi 3"
KIRJOITA = '[[TYOKALU {"nimi": "kirjoita", "arg": {"polku": "yhteenveto.md", "sisalto": "%s"}}]]' % SISALTO
VALMIS = '[[TYOKALU {"nimi": "valmis", "arg": {"raportti": "Kirjoitin tiedoston yhteenveto.md (3 rivi\u00e4)."}}]]'
SUUNNITELMA = "1. Kirjoita yhteenveto.md. Valmis kun tiedostossa on kolme rivi\u00e4."
HYVAKSYTTY = "ARVIO: hyvaksytty\nRaportti vastaa ty\u00f6kalulokia ja tiedostolistaa."
HYLATTY = "ARVIO: hylatty\nTiedosto ei vastaa teht\u00e4v\u00e4\u00e4."


class KetjuPohja(AgenttiPohja):
    """AgenttiPohja (chat-palvelin, ajurin kansiot, yhteinen kulukirjanpito) + korvikemalli ajurin lapselle."""

    def setUp(self):
        super().setUp()
        r = Path(self.tmp.name)
        self.avain = r / "agentti-avain"            # agentin oma avain (keksitty), ei chatin avaintiedosto
        self.avain.write_text(AVAIN + "\n")
        os.chmod(self.avain, 0o600)
        self.mallivastaukset = {"suunnittelija": [SUUNNITELMA], "tekija": [KIRJOITA, VALMIS],
                                "tarkastaja": [HYVAKSYTTY]}
        self.rungot = []
        self.lapsikomennot = []

    def avaa(self, pyynto, timeout=None):
        """Korvikemalli: OpenRouterin vastaus rooleittain (rooli tunnistetaan jarjestelmakehotteesta)."""
        runko = json.loads(pyynto.data)
        rooli = _rooli(runko)
        self.rungot.append((rooli, runko))
        jono = self.mallivastaukset[rooli]
        teksti = jono.pop(0) if len(jono) > 1 else jono[0]
        return Vastaus({"choices": [{"message": {"content": teksti}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}})

    def _aliprosessi(self, komento, teksti, aikaraja_s):
        """Korvaa vain aja_aliprosessina: sama lapsi samoilla argumenteilla samassa prosessissa, tulos JSONina."""
        self.lapsikomennot.append(list(komento))
        a = komento[komento.index("lapsi") + 1:]
        juuri, roolit = a[a.index("--juuri") + 1], a[a.index("--roolit") + 1]
        self.assertNotIn("--haku-osoite", a)             # verkkohaku ei ole tassa testissa kaytossa
        d = aj.lapsi(juuri, roolit, syote=io.StringIO(json.dumps({"teksti": teksti})),
                     avain_tiedosto=str(self.avain), kulutila=str(self.kulutila), avaa=self.avaa)
        d = json.loads(json.dumps(d, ensure_ascii=True))  # kuten aliprosessin stdout
        if not isinstance(d, dict) or d.get("tila") not in aj.TILAT:
            return None, "aliprosessin tulos ei kelpaa"
        return d, ""

    def aja_ajuri(self):
        """Ajurin oikea kasittelyfunktio yhdelle jonotiedostolle (palvelu-silmukan yksi kierros)."""
        with mock.patch.object(aj, "aja_aliprosessina", side_effect=self._aliprosessi), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            return aj.aja_seuraava(self.perus, MALLI)

    def kaynnistetty(self, teksti=TEHTAVA):
        """Lohko chatin kautta -> ehdotus -> kaynnistys reitin kautta. Palauttaa (keskustelu, tunnus)."""
        kid = self.uusi()
        t = self.ehdota(kid, teksti)
        self.assertEqual(at.listaa(self.tila.agenttitehtavat, kid), [{"tunnus": t, "kaynnistetty": False}])
        s, d = self.kaynnista(kid, t, "kyll\u00e4 " + yksityinen.sha(teksti)[:8])
        self.assertEqual(s, 200, d)
        self.assertEqual(at.tila(self.perus, t, kid), (at.JONOSSA, None))
        self.assertEqual(aj.jonossa(self.perus), [(t, t + ".json")])
        return kid, t

    def roolit(self):
        return [r for r, _ in self.rungot]


class OnnistunutKetjuTesti(KetjuPohja):
    def test_ehdotuksesta_chatin_tulosnayttoon(self):
        kid, t = self.kaynnistetty()
        tulos = self.aja_ajuri()
        self.assertEqual((tulos["tunnus"], tulos["tila"], tulos["kirjoitettu"]), (t, am.VALMIS, True))
        # ajuri kaynnisti lapsen omalla tyokansiolla ja oikealla rooliasetuksella
        self.assertEqual(len(self.lapsikomennot), 1)
        k = self.lapsikomennot[0]
        self.assertEqual(k[k.index("--juuri") + 1], os.path.join(self.perus, aj.TYO, t))
        self.assertEqual(am.tarkista_roolit(k[k.index("--roolit") + 1]), {r: MALLI for r in am.ROOLIT})
        # agentti sai vain kortin tekstin; jokainen kutsu ZDR-runkona
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija", "tarkastaja"])
        self.assertIn(TEHTAVA.strip(), self.rungot[0][1]["messages"][1]["content"])
        for _, runko in self.rungot:
            self.assertIs(runko["provider"]["zdr"], True)
            self.assertEqual(runko["model"], MALLI)
        # jono tyhja, pyynto kasitelty; kulut kirjattiin yhteiseen kirjanpitoon
        self.assertEqual(aj.jonossa(self.perus), [])
        self.assertTrue(os.path.isfile(os.path.join(self.perus, aj.KASITELLYT, t + ".json")))
        tehtavat = [json.loads(r).get("tehtava") for r in
                    (self.kulutila / ok.KULUT).read_text(encoding="utf-8").splitlines()]
        self.assertIn("aivo-agentti:tarkastaja", tehtavat)

        # chatin moduulifunktiot
        tila_, d = at.tila(self.perus, t, kid)
        self.assertEqual(tila_, am.VALMIS)
        self.assertEqual(at.lue_tulos(self.perus, t, kid), d)
        n = at.nayttotulos(d)
        self.assertEqual((n["tila"], n["arvio"], n["syy"]), (am.VALMIS, am.HYVAKSYTTY, ""))
        self.assertIn("tyokalulokia", n["perustelu"].replace("\u00f6", "o"))
        self.assertIn("yhteenveto.md", n["raportti"])
        self.assertEqual(sorted(f["polku"] for f in n["tiedostot"]), [am.SUUNNITELMA_TIEDOSTO, "yhteenveto.md"])
        self.assertEqual(n["kutsuja"], 4)
        self.assertGreater(n["kulu_eur"], 0)
        self.assertFalse(n["kulu_tuntematon"])
        f = at.lue_tiedosto(self.perus, t, kid, "yhteenveto.md")
        self.assertEqual(f["teksti"], "rivi 1\nrivi 2\nrivi 3")

        # chatin HTTP-reitit
        s, kortti = self.kortti(kid, t)
        self.assertEqual((s, kortti["kaynnistetty"], kortti["tila"]), (200, True, am.VALMIS))
        self.assertEqual(kortti["tulos"], json.loads(json.dumps(n)))
        s, f = self.pyynto("GET", "/api/agentti/tiedosto?keskustelu=%s&tunnus=%s&polku=yhteenveto.md" % (kid, t))
        self.assertEqual((s, f["teksti"]), (200, "rivi 1\nrivi 2\nrivi 3"))
        loki = at.lue_loki(self.tila.agenttitehtavat)
        self.assertEqual([(r["tunnus"], r["tila"]) for r in loki], [(t, "k\u00e4ynnistetty"), (t, am.VALMIS)])
        merkinnat = [v["teksti"] for v in self.tila.yks.lue(kid) if v["rooli"] == yksityinen.JARJESTELMA_ROOLI]
        self.assertEqual(merkinnat[-1], at.tulos_merkinta(t, am.VALMIS))
        self.assertFalse([m for m in merkinnat if "rivi 1" in m])        # tiedoston sisalto ei mene historiaan

    def test_toista_ajoa_samalla_tunnuksella_ei_tule(self):
        kid, t = self.kaynnistetty()
        self.aja_ajuri()
        self.assertIsNone(self.aja_ajuri())                              # jono tyhja
        self.assertEqual(self.kaynnista(kid, t, "kyll\u00e4 " + yksityinen.sha(TEHTAVA)[:8])[0], 409)
        self.assertEqual(aj.jonossa(self.perus), [])


class HylkaysTesti(KetjuPohja):
    def test_tarkastaja_hylkaa(self):
        self.mallivastaukset["tarkastaja"] = [HYLATTY]
        kid, t = self.kaynnistetty()
        tulos = self.aja_ajuri()
        self.assertEqual((tulos["tila"], tulos["syy"]), (am.KESKEN, "tarkastaja: " + am.HYLATTY))
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija", "tarkastaja"])   # ei korjauskierrosta
        s, kortti = self.kortti(kid, t)
        self.assertEqual(s, 200)
        self.assertEqual(kortti["tila"], am.KESKEN)
        self.assertNotEqual(kortti["tila"], am.VALMIS)
        n = kortti["tulos"]
        self.assertEqual((n["tila"], n["arvio"], n["syy"]), (am.KESKEN, am.HYLATTY, "tarkastaja: " + am.HYLATTY))
        self.assertIn("ei vastaa", n["perustelu"])
        loki = at.lue_loki(self.tila.agenttitehtavat)
        self.assertEqual(loki[-1]["tila"], am.KESKEN)
        merkinnat = [v["teksti"] for v in self.tila.yks.lue(kid) if v["rooli"] == yksityinen.JARJESTELMA_ROOLI]
        self.assertEqual(merkinnat[-1], at.tulos_merkinta(t, am.KESKEN))

    def test_korjattava_ja_sitten_hyvaksytty(self):
        korjaus = '[[TYOKALU {"nimi": "kirjoita", "arg": {"polku": "yhteenveto.md", "sisalto": "a\\nb\\nc"}}]]'
        self.mallivastaukset["tarkastaja"] = ["ARVIO: korjattava\nRivit puuttuvat.", HYVAKSYTTY]
        self.mallivastaukset["tekija"] = [KIRJOITA, VALMIS, korjaus, VALMIS]
        kid, t = self.kaynnistetty()
        self.assertEqual(self.aja_ajuri()["tila"], am.VALMIS)
        self.assertEqual(self.roolit(), ["suunnittelija", "tekija", "tekija", "tarkastaja", "tekija", "tekija",
                                         "tarkastaja"])
        s, f = self.pyynto("GET", "/api/agentti/tiedosto?keskustelu=%s&tunnus=%s&polku=yhteenveto.md" % (kid, t))
        self.assertEqual((s, f["teksti"]), (200, "a\nb\nc"))


class KattoKetjuTesti(KetjuPohja):
    """Kaynnistyksen jalkeen yhteinen paivakatto tayttyy tai kirjanpito rikkoutuu ennen ajurin vuoroa."""

    def _tarkista_keskeytys(self, kid, t, tulos):
        self.assertEqual((tulos["tila"], tulos["syy"]), (am.KESKEYTETTY, am.KATTO_SYY))
        self.assertEqual(self.rungot, [])                                # yhtaan mallikutsua ei tehty
        s, kortti = self.kortti(kid, t)
        self.assertEqual((s, kortti["tila"]), (200, am.KESKEYTETTY))
        n = kortti["tulos"]
        # kutsuja laskee yritykset: estetty ensimmainen yritys on 1, vaikka mitaan ei lahetetty (malli._Kutsuja)
        self.assertEqual((n["tila"], n["syy"], n["arvio"], n["kutsuja"]), (am.KESKEYTETTY, am.KATTO_SYY, "", 1))
        self.assertEqual(n["raportti"], "")
        self.assertNotIn("aiheesta X", json.dumps(n, ensure_ascii=False))   # syy ilman tehtavan sisaltoa
        merkinnat = [v["teksti"] for v in self.tila.yks.lue(kid) if v["rooli"] == yksityinen.JARJESTELMA_ROOLI]
        self.assertEqual(merkinnat[-1], at.tulos_merkinta(t, am.KESKEYTETTY))

    def test_katto_taynna_ajurin_vuorolla(self):
        kid, t = self.kaynnistetty()
        self.katto_tayteen()
        self._tarkista_keskeytys(kid, t, self.aja_ajuri())

    def test_rikkinainen_kirjanpito_ajurin_vuorolla(self):
        kid, t = self.kaynnistetty()
        (self.kulutila / ok.KULUT).write_text("ei jsonia\n")
        self._tarkista_keskeytys(kid, t, self.aja_ajuri())


class VierasKeskusteluTesti(KetjuPohja):
    def test_toinen_keskustelu_ei_nae_tulosta(self):
        kid, t = self.kaynnistetty()
        self.assertEqual(self.aja_ajuri()["tila"], am.VALMIS)
        toinen = self.uusi()
        with self.assertRaises(yksityinen.YksityinenVirhe):
            at.lue_tulos(self.perus, t, toinen)
        with self.assertRaises(yksityinen.YksityinenVirhe):
            at.lue_tiedosto(self.perus, t, toinen, "yhteenveto.md")
        s, d = self.kortti(toinen, t)
        self.assertEqual(s, 400)
        self.assertNotIn("rivi", json.dumps(d))
        s, d = self.pyynto("GET", "/api/agentti/tiedosto?keskustelu=%s&tunnus=%s&polku=yhteenveto.md" % (toinen, t))
        self.assertEqual(s, 400)
        self.assertNotIn("rivi", json.dumps(d))
        self.assertEqual(self.pyynto("GET", "/api/agentit?keskustelu=" + toinen)[1], {"agentit": []})
        self.assertEqual(self.kortti(kid, t)[0], 200)                    # aloittanut keskustelu nakee yha


if __name__ == "__main__":
    unittest.main()
