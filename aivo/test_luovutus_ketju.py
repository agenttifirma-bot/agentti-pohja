"""Luovutuspaketin koko kierros yhtena ketjuna (aivo/luovutuspaketti.py + aivo/luovutus.py + aivo/chat.py).

Ketju: yksityisen tilan vastauksen [[LUOVUTUSPAKETTI]]-lohko -> pakettiehdotus -> vartija -> "kylla <sha8>"
(+ "tarkistin kohdat <sha8>", koska paketin palat ovat aina "kysy") -> palat kirjaston kansiossa saapuneet/ ->
tyokalutilan nakyma saapuneisiin -> tulos <tulosrepo>/<pakettitunnus>/pala-<n>.md -> tarkista_paluut ja lue_tulos
yksityisessa tilassa. Ei verkkoa eika mallikutsuja: mallin vastaus on vaarennetty ja tulosrepo on tilapaishakemisto.
Vain stdlib."""
import re
from pathlib import Path

from aivo import luovutus, luovutuspaketti as lp
from aivo.test_luovutuspaketti import PakettiPohja
from aivo.yksityinen import YksityinenVirhe

KAKSI_PALAA = ("Pilkoin ty\u00f6n.\n[[LUOVUTUSPAKETTI Ketjutesti]]\n[[PALA 1]]\nToteuta KETJU-OSA-A.\n[[/PALA]]\n"
               "[[PALA 2]]\nKirjoita KETJU-OSA-B:n testit.\n[[/PALA]]\n[[/LUOVUTUSPAKETTI]]\nLoppu.\n")
# keksitty, muodoltaan suomalainen IBAN (ei oikea tili): vartijan mekaaninen estotyyppi "tilinumero"
KEKSITTY_IBAN = "FI12 3456 7890 1234 56"
OTSAKE_RE = re.compile(r"\A<!-- luovutuspaketti tunnus=([0-9a-f]{12}) pala=(\d{1,2}) nimi=([^\n]*?) -->\n")


class KetjuPohja(PakettiPohja):
    """Apumetodit tulevat pohjaluokista: paketti, hae ja hyvaksy_p PakettiPohjasta (aivo/test_luovutuspaketti.py),
    saapuneet_tiedostot ja tyokalun_kehote LuovutusPohjasta (aivo/test_luovutus.py) seka uusi ja pyynto sen
    pohjaluokista. Ne ajavat oikeaa chat-palvelua tilapaishakemistossa ilman verkkoa ja mallikutsuja."""

    def setUp(self):
        super().setUp()
        self.julkaisut = []     # testikohtainen: ei moduulitason tilaa, joka voisi vuotaa testista toiseen
        self.repo = Path(self.tmp.name) / "tulosrepo"
        self.repo.mkdir()

    def julkaise(self, kirjasto, polku, viesti=""):
        """Korvaa kirjaston commitin ja pushin: kirjaa kutsun eika koske gitiin."""
        self.julkaisut.append((str(kirjasto), str(polku), viesti))
        return "ei-gitissa"

    def irrota(self, vastaus):
        """Kuten chatin _viesti_yksityinen: lohko irrotetaan vastauksesta ja tallennetaan oletusvartijalla."""
        tallennetut = []

        def tallenna(nimi, palat):
            t = lp.tallenna_paketti(self.tila.luovutukset, nimi, palat, vartija_listat=self.tila.vartija_listat)
            tallennetut.append(t)
            return t
        nakyva = lp.irrota_paketit(lp.neutraloi_paluumerkinnat(vastaus), tallenna)
        return nakyva, tallennetut

    def tyokalutila_kirjoittaa_tulokset(self, kirjoita):
        """Tyokalutila lukee vain kirjaston saapuneet/-kansiota: palan otsakkeesta paketin tunnus ja palan numero,
        ja tulos kirjoitetaan polkuun <tulosrepo>/<pakettitunnus>/pala-<n>.md. Palauttaa [(tunnus, n, nimi)]."""
        tehdyt = []
        for s in luovutus.listaa_saapuneet(self.tila.kirjasto):
            self.assertNotIn("virhe", s)
            m = OTSAKE_RE.match(luovutus.lue_saapunut(self.tila.kirjasto, s["tunnus"])["teksti"])
            self.assertIsNotNone(m, s["tunnus"])
            pt, n, nimi = m.group(1), int(m.group(2)), m.group(3)
            if kirjoita:
                (self.repo / pt).mkdir(exist_ok=True)
                (self.repo / pt / ("pala-%d.md" % n)).write_text("TULOS %s pala %d valmis.\n" % (pt, n), encoding="utf-8")
            tehdyt.append((pt, n, nimi))
        return sorted(tehdyt)


class KokoKierrosTesti(KetjuPohja):
    def test_onnistunut_kierros_lohkosta_tulokseen(self):
        # (0) tulosrepo kelpaa: se on kirjaston ja tyokalutilan datan ulkopuolella
        self.assertEqual(lp.tarkista_tulos_repo(str(self.repo), (self.tila.kirjasto, str(self.tila.keskustelut.data))),
                         str(self.repo.resolve()))
        # (1) yksityisen tilan vastauksen lohko -> paketti; mitaan ei lahde
        nakyva, [t] = self.irrota(KAKSI_PALAA)
        self.assertIn("Luovutuspaketti tallennettu (tunnus %s, 2 palaa)" % t, nakyva)
        self.assertNotIn("KETJU-OSA", nakyva)
        self.assertTrue(nakyva.startswith("Pilkoin ty\u00f6n.\n") and nakyva.endswith("Loppu.\n"))
        self.assertEqual(self.saapuneet_tiedostot(), [])
        d = lp.lue_paketti(self.tila.luovutukset, t)
        self.assertEqual([p["n"] for p in d["palat"]], [1, 2])
        # (2) vartija: kumpikin pala "kysy" (koukku ei koskaan anna sallittu=True paketin palalle)
        self.assertEqual([p["vartija"]["sallittu"] for p in d["palat"]], [None, None])
        s8 = d["sha"][:8]
        # (3) pelkka "kylla <sha8>" ei riita, koska palat ovat "kysy"; mitaan ei kopioidu
        with self.assertRaises(luovutus.VartijaEsto) as cm:
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise)
        self.assertIn("tarkistin kohdat " + s8, str(cm.exception))
        self.assertEqual((self.saapuneet_tiedostot(), self.julkaisut), ([], []))
        # (4) hyvaksynta oikealla sha8:lla ja lisavahvistuksella: yksi julkaisu, kaksi palaa saapuneisiin
        tulos = lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise,
                                   lisavahvistus="tarkistin kohdat " + s8)
        self.assertEqual(tulos, "ei-gitissa")
        self.assertEqual(len(self.julkaisut), 1)
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset, lp.HYVAKSYTYT), [t])
        self.assertEqual(self.saapuneet_tiedostot(), sorted(lp.palan_tunnus(t, n) + ".md" for n in (1, 2)))
        for n, osa in ((1, "Toteuta KETJU-OSA-A.\n"), (2, "Kirjoita KETJU-OSA-B:n testit.\n")):
            s = luovutus.lue_saapunut(self.tila.kirjasto, lp.palan_tunnus(t, n))      # tarkiste tasmaa
            self.assertEqual(s["teksti"], "<!-- luovutuspaketti tunnus=%s pala=%d nimi=Ketjutesti -->\n%s" % (t, n, osa))
        # (5) tyokalutilan nakyma: kehote ja saapuneet-lista nayttavat molemmat palat otsakkeineen
        kehote = luovutus.saapuneet_kehote(self.tila.kirjasto)
        for n in (1, 2):
            self.assertIn("luovutuspaketti tunnus=%s pala=%d" % (t, n), kehote)
        self.assertIn("KETJU-OSA-A", kehote)
        self.assertIn("KETJU-OSA-B", kehote)
        # (6) ennen tulosta paluita ei ole eika tulosta voi lukea
        self.assertEqual(lp.tarkista_paluut(self.tila.luovutukset, str(self.repo)), [])
        with self.assertRaises(YksityinenVirhe):
            lp.lue_tulos(self.tila.luovutukset, str(self.repo), t, 1)
        # (7) tyokalutila kirjoittaa tulokset saapuneiden otsakkeiden perusteella
        self.assertEqual(self.tyokalutila_kirjoittaa_tulokset(True), [(t, 1, "Ketjutesti"), (t, 2, "Ketjutesti")])
        # (8) yksityinen tila: paluumerkinnat kerran ja tulokset luettavissa (tarkista_paluut jarjestaa
        # paketit ja palat sorted-funktiolla, joten jarjestys ei riipu tiedostojarjestelmasta)
        uudet = lp.tarkista_paluut(self.tila.luovutukset, str(self.repo))
        self.assertEqual([(u["tunnus"], u["n"], u["merkinta"]) for u in uudet],
                         [(t, 1, "[Paketin Ketjutesti pala 1 valmis]"), (t, 2, "[Paketin Ketjutesti pala 2 valmis]")])
        self.assertEqual(lp.tarkista_paluut(self.tila.luovutukset, str(self.repo)), [])
        for n in (1, 2):
            self.assertEqual(lp.lue_tulos(self.tila.luovutukset, str(self.repo), t, n), "TULOS %s pala %d valmis.\n" % (t, n))
        # palaa, jota paketissa ei ollut, ei lueta, vaikka tiedosto olisi tulosrepossa
        (self.repo / t / "pala-3.md").write_text("ei kuulu pakettiin\n")
        with self.assertRaises(YksityinenVirhe):
            lp.lue_tulos(self.tila.luovutukset, str(self.repo), t, 3)

    def test_vanha_vahvistus_ei_kelpaa_palan_poiston_jalkeen(self):
        _, [t] = self.irrota(KAKSI_PALAA)
        vanha = lp.lue_paketti(self.tila.luovutukset, t)["sha"][:8]
        uusi = lp.poista_pala(self.tila.luovutukset, t, 2, vanha)["sha"][:8]
        self.assertNotEqual(uusi, vanha)
        with self.assertRaises(YksityinenVirhe) as cm:
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + vanha, self.tila.kirjasto, julkaise=self.julkaise,
                               lisavahvistus="tarkistin kohdat " + vanha)
        self.assertNotIsInstance(cm.exception, luovutus.VartijaEsto)     # sha-tarkistus kaatuu ensin
        # vanhan sha:n lisavahvistus ei kelpaa uudelle paketille
        with self.assertRaises(luovutus.VartijaEsto):
            lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + uusi, self.tila.kirjasto, julkaise=self.julkaise,
                               lisavahvistus="tarkistin kohdat " + vanha)
        self.assertEqual((self.saapuneet_tiedostot(), self.julkaisut), ([], []))
        self.assertEqual(luovutus.lue_loki(self.tila.luovutukset), [])
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [t])
        # uudella sha:lla vain jaljelle jaanyt pala lahtee
        lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + uusi, self.tila.kirjasto, julkaise=self.julkaise,
                           lisavahvistus="tarkistin kohdat " + uusi)
        self.assertEqual(self.saapuneet_tiedostot(), [lp.palan_tunnus(t, 1) + ".md"])
        self.assertEqual(self.tyokalutila_kirjoittaa_tulokset(True), [(t, 1, "Ketjutesti")])
        self.assertEqual([u["n"] for u in lp.tarkista_paluut(self.tila.luovutukset, str(self.repo))], [1])

    def test_mekaanisesti_estetty_pala_estaa_koko_paketin_kunnes_poistetaan(self):
        vastaus = KAKSI_PALAA.replace("Kirjoita KETJU-OSA-B:n testit.", "Maksa tilille %s." % KEKSITTY_IBAN)
        nakyva, [t] = self.irrota(vastaus)
        self.assertNotIn(KEKSITTY_IBAN, nakyva)
        d = lp.lue_paketti(self.tila.luovutukset, t)
        self.assertEqual([p["vartija"]["sallittu"] for p in d["palat"]], [None, False])
        self.assertIn("tilinumero", " ".join(d["palat"][1]["vartija"]["merkinnat"]))
        self.assertNotIn(KEKSITTY_IBAN, " ".join(d["palat"][1]["vartija"]["merkinnat"]))   # tyyppi, ei sisaltoa
        s8 = d["sha"][:8]
        # oikea sha ja lisavahvistus eivat auta, eika injektoitu salliva vartija ohita mekaanista estoa
        for vartija in (lp.vartija_koukku, lambda teksti: {"tila": "ok", "sallittu": True, "merkinnat": []}):
            with self.assertRaises(luovutus.VartijaEsto) as cm:
                lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise,
                                   lisavahvistus="tarkistin kohdat " + s8, vartija=vartija)
            self.assertEqual(cm.exception.syyt, ["pala 2"])
            self.assertNotIn(KEKSITTY_IBAN, str(cm.exception))
        self.assertEqual((self.saapuneet_tiedostot(), self.julkaisut), ([], []))
        self.assertEqual(luovutus.lue_loki(self.tila.luovutukset), [])
        # palan poisto: uusi sha, ja paketti lahtee ilman estettya palaa
        uusi = lp.poista_pala(self.tila.luovutukset, t, 2, s8)["sha"][:8]
        lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + uusi, self.tila.kirjasto, julkaise=self.julkaise,
                           lisavahvistus="tarkistin kohdat " + uusi)
        self.assertEqual(self.saapuneet_tiedostot(), [lp.palan_tunnus(t, 1) + ".md"])
        self.assertNotIn(KEKSITTY_IBAN, luovutus.saapuneet_kehote(self.tila.kirjasto))
        self.assertNotIn(KEKSITTY_IBAN, "".join(r.get("teksti", "") for r in luovutus.lue_loki(self.tila.luovutukset)))

    def test_lisapala_kysy_vaatii_oman_hyvaksynnan_ja_tulos_palaa_perustunnukselle(self):
        self.assertEqual(lp.LISAPALAT_OLETUS, "kysy")
        self.assertEqual(self.tila.lisapalat, "kysy")
        _, [t] = self.irrota(KAKSI_PALAA)
        s8 = lp.lue_paketti(self.tila.luovutukset, t)["sha"][:8]
        lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise,
                           lisavahvistus="tarkistin kohdat " + s8)
        ennen, julkaisuja = self.saapuneet_tiedostot(), len(self.julkaisut)
        # mallin [[LISAPALA]]-lohko oletustilassa: vain ehdotus, ei julkaisua
        lisat = []

        def tallenna_lisa(jatkaa, tekstit):
            tunnus, lahti, yht = lp.tallenna_lisapalat(self.tila.luovutukset, self.tila.kirjasto, jatkaa, tekstit,
                                                      self.tila.lisapalat, julkaise=self.julkaise,
                                                      vartija_listat=self.tila.vartija_listat)
            lisat.append((tunnus, lahti, yht))
            return "[lisapala %s]" % tunnus
        nakyva = lp.irrota_paketit("Viel\u00e4:\n[[LISAPALA %s]]\nDokumentoi KETJU-OSA-C.\n[[/LISAPALA]]\n" % t,
                                   lambda *a: self.fail("ei pakettia"), tallenna_lisa)
        [(lt, lahti, yht)] = lisat
        self.assertEqual((lahti, yht), (False, None))
        self.assertNotIn("KETJU-OSA-C", nakyva)
        self.assertEqual((self.saapuneet_tiedostot(), len(self.julkaisut)), (ennen, julkaisuja))
        ld = lp.lue_paketti(self.tila.luovutukset, lt)
        self.assertEqual((ld["jatkaa"], [p["n"] for p in ld["palat"]]), (t, [3]))
        # oma hyvaksynta: paketin vanha sha8 ei kelpaa lisapalalle
        with self.assertRaises(YksityinenVirhe):
            lp.hyvaksy_paketti(self.tila.luovutukset, lt, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise,
                               lisavahvistus="tarkistin kohdat " + s8)
        ls8 = ld["sha"][:8]
        lp.hyvaksy_paketti(self.tila.luovutukset, lt, "kyll\u00e4 " + ls8, self.tila.kirjasto, julkaise=self.julkaise,
                           lisavahvistus="tarkistin kohdat " + ls8)
        self.assertEqual(len(self.julkaisut), julkaisuja + 1)
        # lisapala saapuu alkuperaisen paketin tunnuksella, ja tulos luetaan perustunnuksella
        self.assertEqual(self.tyokalutila_kirjoittaa_tulokset(True),
                         [(t, 1, "Ketjutesti"), (t, 2, "Ketjutesti"), (t, 3, "Ketjutesti")])
        self.assertFalse((self.repo / lt).exists())
        self.assertEqual([u["n"] for u in lp.tarkista_paluut(self.tila.luovutukset, str(self.repo))], [1, 2, 3])
        self.assertEqual(lp.lue_tulos(self.tila.luovutukset, str(self.repo), t, 3), "TULOS %s pala 3 valmis.\n" % t)
        with self.assertRaises(YksityinenVirhe):        # lisapaketin oma tunnus ei ole perustunnus
            lp.lue_tulos(self.tila.luovutukset, str(self.repo), lt, 3)

    def test_automaattinen_lisapala_ei_lahde_oletusvartijalla(self):
        _, [t] = self.irrota(KAKSI_PALAA)
        s8 = lp.lue_paketti(self.tila.luovutukset, t)["sha"][:8]
        lp.hyvaksy_paketti(self.tila.luovutukset, t, "kyll\u00e4 " + s8, self.tila.kirjasto, julkaise=self.julkaise,
                           lisavahvistus="tarkistin kohdat " + s8)
        ennen, julkaisuja = self.saapuneet_tiedostot(), len(self.julkaisut)
        lt, lahti, yht = lp.tallenna_lisapalat(self.tila.luovutukset, self.tila.kirjasto, t, ["Osa D.\n"],
                                               "automaattinen", julkaise=self.julkaise)
        self.assertFalse(lahti)
        self.assertIn("odottavat", yht)
        self.assertEqual((self.saapuneet_tiedostot(), len(self.julkaisut)), (ennen, julkaisuja))
        self.assertEqual(lp.listaa_paketit(self.tila.luovutukset), [lt])


class ChatReititTesti(KetjuPohja):
    def test_kierros_chatin_reittien_kautta(self):
        self.tila.tulos_repo = str(self.repo)
        kid, t, v = self.paketti(vastaus=KAKSI_PALAA)
        self.assertNotIn("KETJU-OSA", v["vastaus"])
        d = self.hae(kid, t)
        self.assertEqual(([p["n"] for p in d["palat"]], [p["vartija"]["sallittu"] for p in d["palat"]]), ([1, 2], [None, None]))
        # ilman lisavahvistusta 409 eika mitaan kopioidu
        s, e = self.hyvaksy_p(kid, t, "kyll\u00e4 " + d["sha8"], lisa=False)
        self.assertEqual((s, e["vartija"]["tulos"]), (409, "kysy"))
        self.assertEqual(self.saapuneet_tiedostot(), [])
        s, e = self.hyvaksy_p(kid, t, "kyll\u00e4 " + d["sha8"])
        self.assertEqual((s, e["tulos"]), (200, "ei-gitissa"), e)
        # tyokalutilan keskustelu nakee palat /api/saapuneet-reitilla ja kehotteessa
        tkid = self.uusi("tyokalu")
        s, sa = self.pyynto("GET", "/api/saapuneet?keskustelu=" + tkid)
        self.assertEqual(s, 200)
        self.assertEqual(sorted(x["tunnus"] for x in sa["saapuneet"]), sorted(lp.palan_tunnus(t, n) for n in (1, 2)))
        self.assertTrue(all(OTSAKE_RE.match(x["teksti"]) for x in sa["saapuneet"]))
        self.assertIn("KETJU-OSA-A", self.tyokalun_kehote())
        self.assertEqual(self.tyokalutila_kirjoittaa_tulokset(True), [(t, 1, "Ketjutesti"), (t, 2, "Ketjutesti")])
        # yksityinen keskustelu: paluut kerran, jarjestelmamerkinta keskusteluun ja tulos reitilta
        s, p = self.pyynto("GET", "/api/paluut?keskustelu=" + kid)
        self.assertEqual((s, [x["n"] for x in p["paluut"]]), (200, [1, 2]))
        self.assertEqual(self.pyynto("GET", "/api/paluut?keskustelu=" + kid)[1], {"paluut": []})
        merk = [x["teksti"] for x in self.tila.yks.lue(kid) if "Paketin Ketjutesti pala" in x["teksti"]]
        self.assertEqual(len(merk), 2)
        for n in (1, 2):
            s, r = self.pyynto("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=%d" % (kid, t, n))
            self.assertEqual((s, r["teksti"]), (200, "TULOS %s pala %d valmis.\n" % (t, n)))

    def test_tyokalutila_saa_404_eika_nae_tulosrepoa(self):
        self.tila.tulos_repo = str(self.repo)
        kid, t, v = self.paketti(vastaus=KAKSI_PALAA)
        s8 = self.hae(kid, t)["sha8"]
        self.assertEqual(self.hyvaksy_p(kid, t, "kyll\u00e4 " + s8)[0], 200)
        self.tyokalutila_kirjoittaa_tulokset(False)
        (self.repo / t).mkdir()
        (self.repo / t / "pala-1.md").write_text("YKSITYINEN-TULOS-KETJU\n")
        tkid = self.uusi("tyokalu")
        for metodi, polku, olio in (
                ("GET", "/api/paketit?keskustelu=" + tkid, None),
                ("GET", "/api/paketti?keskustelu=%s&tunnus=%s" % (tkid, t), None),
                ("GET", "/api/paluut?keskustelu=" + tkid, None),
                ("GET", "/api/paketti/tulos?keskustelu=%s&tunnus=%s&pala=1" % (tkid, t), None),
                ("POST", "/api/paketti/poista-pala", {"keskustelu": tkid, "tunnus": t, "pala": 1, "sha8": s8}),
                ("POST", "/api/paketti/hyvaksy", {"keskustelu": tkid, "tunnus": t, "vahvistus": "kyll\u00e4 " + s8,
                                                  "lisavahvistus": "tarkistin kohdat " + s8}),
                ("POST", "/api/paketti/hylkaa", {"keskustelu": tkid, "tunnus": t})):
            s, r = self.pyynto(metodi, polku, olio)
            self.assertEqual(s, 404, polku)
            self.assertNotIn("YKSITYINEN-TULOS-KETJU", str(r))
        # tyokalutilan kehote ja saapuneet-lista eivat sisalla tulosrepon tekstia, ja paluuta ei kulutettu
        self.assertNotIn("YKSITYINEN-TULOS-KETJU", self.tyokalun_kehote())
        self.assertNotIn("YKSITYINEN-TULOS-KETJU", str(self.pyynto("GET", "/api/saapuneet?keskustelu=" + tkid)[1]))
        s, p = self.pyynto("GET", "/api/paluut?keskustelu=" + kid)
        self.assertEqual([x["n"] for x in p["paluut"]], [1])
        # yksityisen tilan saapuneet-reitti on puolestaan 404 (saapuneet kuuluvat tyokalutilalle)
        self.assertEqual(self.pyynto("GET", "/api/saapuneet?keskustelu=" + kid)[0], 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
