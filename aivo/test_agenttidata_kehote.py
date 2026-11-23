"""Testit agenttidata-kopion lukemiselle Aivon kehotteeseen (AIVO_AGENTTIDATA). Ei verkkoa, ei gitia."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aivo import agenttidata_kehote as ak, chat, salasana_apu, yksityinen

SAL = "oikea-salasana-123"
TS = ".ts" + ".net"
RAJA = chat.RAJA


def pohdinta(n, alku=1):
    rivit = ["# Pohdinta-vastaukset", ""]
    for i in range(alku, alku + n):
        rivit.append("- **A%d (23.11.):** Tony: \"p\u00e4\u00e4t\u00f6s numero %d\" -> kirjattu." % (i, i))
    return "\n".join(rivit) + "\n"


class Pohja(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.r = Path(self._tmp.name)
        self.ad = self.r / "agenttidata"
        (self.ad / ".git").mkdir(parents=True)
        (self.ad / "tulokset").mkdir()
        (self.ad / "tehtavat").mkdir()
        (self.ad / "kompassi.md").write_text("# Kompassi\nKOMPASSI-SISALTO: Aivo ensin.\n")
        (self.ad / "faktat.md").write_text("# Faktat\nFAKTA-SISALTO: kontti 122.\n")
        (self.ad / "pohdinta-vastaukset.md").write_text(pohdinta(100))
        (self.ad / "tulokset" / "23-01.md").write_text("TULOS-SISALTO ei kehotteeseen\n")
        (self.ad / "tehtavat" / "23-01.md").write_text("TEHTAVA-SISALTO ei kehotteeseen\n")
        (self.ad / "muu.md").write_text("MUU-SISALTO ei kehotteeseen\n")

    def tuore(self):
        return datetime.now(timezone.utc)


class MuodostaTesti(Pohja):
    def test_asetus_pois_ei_osiota(self):
        self.assertEqual(ak.muodosta("", RAJA, 10_000, 5_000), ("", []))
        self.assertEqual(ak.muodosta(None, RAJA, 10_000, 5_000), ("", []))

    def test_kolme_tiedostoa_mukana_muut_eivat(self):
        t, nimet = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000, nyt=self.tuore())
        self.assertEqual(nimet, ["agenttidata/kompassi.md", "agenttidata/faktat.md",
                                 "agenttidata/pohdinta-vastaukset.md"])
        for s in ("KOMPASSI-SISALTO", "FAKTA-SISALTO", "A100 "):
            self.assertIn(s, t)
        for s in ("TULOS-SISALTO", "TEHTAVA-SISALTO", "MUU-SISALTO"):
            self.assertNotIn(s, t)
        self.assertIn("AGENTTIDATA (l\u00e4hde: Gitean tony/agenttidata", t)
        self.assertIn("kopion aika ", t)
        self.assertNotIn("VAROITUS", t)

    def test_pohdinnasta_vain_viimeiset_merkinnat(self):
        t, _ = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000, nyt=self.tuore())
        self.assertIn("**A41 ", t)          # 100 merkintaa, viimeiset 60 = A41-A100
        self.assertIn("**A100 ", t)
        self.assertNotIn("**A40 ", t)
        self.assertNotIn("**A1 ", t)
        self.assertNotIn("# Pohdinta-vastaukset", t)

    def test_pohdinnan_kokoraja_ei_katkaise_merkintaa_kesken(self):
        loppu = ak.viimeiset_merkinnat(pohdinta(100), 60, raja=300)
        self.assertLessEqual(len(loppu), 300)
        self.assertTrue(loppu.startswith("- **A"))
        self.assertIn("**A100 ", loppu)

    def test_ilman_merkintoja_raaka_loppu(self):
        self.assertEqual(ak.viimeiset_merkinnat("abcdef", 60, raja=3), "def")

    def test_linkki_ulos_ohitetaan(self):
        ulko = self.r / "salainen.md"
        ulko.write_text("ULKOPUOLINEN-SISALTO\n")
        (self.ad / "faktat.md").unlink()
        os.symlink(ulko, self.ad / "faktat.md")
        (self.ad / ".git" / "config").write_text("GIT-SISALTO\n")
        (self.ad / "kompassi.md").unlink()
        os.symlink(self.ad / ".git" / "config", self.ad / "kompassi.md")
        t, nimet = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000, nyt=self.tuore())
        self.assertNotIn("ULKOPUOLINEN-SISALTO", t)
        self.assertNotIn("GIT-SISALTO", t)
        self.assertEqual(nimet, ["agenttidata/pohdinta-vastaukset.md"])

    def test_kansio_ei_tiedosto_ohitetaan(self):
        (self.ad / "faktat.md").unlink()
        (self.ad / "faktat.md").mkdir()
        _, nimet = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000, nyt=self.tuore())
        self.assertNotIn("agenttidata/faktat.md", nimet)

    def test_vanha_kopio_varoittaa(self):
        vanha = time.time() - 30 * 3600
        for n in ak.TIEDOSTOT:
            os.utime(self.ad / n, (vanha, vanha))
        t, _ = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000)
        self.assertIn("VAROITUS: kopio on yli 24 h vanha (30 h)", t)
        self.assertIn("(tiedostot muuttuneet)", t)

    def test_tuore_haku_voittaa_vanhat_tiedostot(self):
        vanha = time.time() - 72 * 3600
        for n in ak.TIEDOSTOT:
            os.utime(self.ad / n, (vanha, vanha))
        (self.ad / ".git" / "FETCH_HEAD").write_text("x\n")
        t, _ = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000)
        self.assertNotIn("VAROITUS", t)
        self.assertIn("(haettu)", t)

    def test_vanha_haku_varoittaa(self):
        (self.ad / ".git" / "FETCH_HEAD").write_text("x\n")
        vanha = time.time() - 25 * 3600
        os.utime(self.ad / ".git" / "FETCH_HEAD", (vanha, vanha))
        t, _ = ak.muodosta(str(self.ad), RAJA, 300_000, 120_000)
        self.assertIn("VAROITUS: kopio on yli 24 h vanha (25 h)", t)

    def test_puuttuva_kopio_huomautetaan(self):
        t, nimet = ak.muodosta(str(self.r / "eiole"), RAJA, 300_000, 120_000)
        self.assertIn("kopiota ei l\u00f6ydy", t)
        self.assertEqual(nimet, [])

    def test_rajamerkki_ja_nul_poistetaan_ja_kokoraja(self):
        (self.ad / "kompassi.md").write_text("alku " + RAJA + "\x00" + "k" * 50_000)
        t, _ = ak.muodosta(str(self.ad), RAJA, 300_000, 1_000, nyt=self.tuore())
        osio = t.split("agenttidata/kompassi.md", 1)[1]
        self.assertEqual(osio.count(RAJA), 2)       # vain osioiden omat rajat, ei sisallosta tullutta
        self.assertNotIn("\x00", t)
        self.assertIn("katkaistu kokorajan vuoksi", t)
        self.assertLess(len(t), 4_000)

    def test_kokonaisraja_suosii_tuoreimpia_paatoksia(self):
        (self.ad / "kompassi.md").write_text("k" * 5_000)
        t, nimet = ak.muodosta(str(self.ad), RAJA, 2_000, 2_000, nyt=self.tuore())
        self.assertIn("**A100 ", t)
        self.assertNotIn("agenttidata/kompassi.md", nimet)
        self.assertLess(len(t), 2_000 + 600)          # otsikot ja rajat budjetin paalle

    def test_odottamaton_virhe_ei_kaada(self):
        alkup = ak._lue
        ak._lue = lambda p, loppu: (_ for _ in ()).throw(RuntimeError("salainen sisalto"))
        self.addCleanup(setattr, ak, "_lue", alkup)
        with self.assertLogs("aivo.agenttidata_kehote", level="WARNING") as loki:
            self.assertEqual(ak.muodosta(str(self.ad), RAJA, 300_000, 120_000), ("", []))
        self.assertIn("RuntimeError", "\n".join(loki.output))
        self.assertNotIn("salainen", "\n".join(loki.output))

    def test_ei_kirjoita_kopioon(self):
        ennen = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.ad.rglob("*")}
        ak.muodosta(str(self.ad), RAJA, 300_000, 120_000)
        jalkeen = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.ad.rglob("*")}
        self.assertEqual(ennen, jalkeen)


class ChatTesti(Pohja):
    def kaynnista(self, agenttidata):
        r = self.r
        (r / "kirjasto").mkdir(exist_ok=True)
        (r / "kirjasto" / "vanha.md").write_text("KIRJASTO-SISALTO\n")
        (r / "yks" / "muisti").mkdir(parents=True, exist_ok=True)
        for k in ("yks", "yks/muisti"):
            os.chmod(r / k, 0o700)
        self.muistit = {"tyokalu": [], "yksityinen": []}

        def kysy(muisti, historia):
            self.muistit["tyokalu"].append(muisti)
            return "Selv\u00e4. [l\u00e4hde: agenttidata/kompassi.md]"

        def kysy_yks(muisti, historia, ohjeet):
            self.muistit["yksityinen"].append(muisti)
            return "Selv\u00e4."
        tila = chat.Tila(salasana_apu.tiiviste(SAL), str(r / "kirjasto"), str(r / "chatdata"), [TS], kysy=kysy,
                         yks_data=str(r / "yks" / "chat"), yks_muisti=str(r / "yks" / "muisti"),
                         ydinohjeet=str(r / "yks" / "ydin"), ehdotukset=str(r / "yks" / "ehd"), kysy_yks=kysy_yks,
                         agenttidata=agenttidata)
        srv = chat.kaynnista("127.0.0.1", 0, tila)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        self.portti = srv.server_address[1]

    def api(self, ev, polku, olio):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", polku, body=json.dumps(olio),
                  headers={"Cookie": ev, "X-Aivo": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def viesti(self, tila, teksti="mik\u00e4 on tuorein p\u00e4\u00e4t\u00f6s?"):
        c = http.client.HTTPConnection("127.0.0.1", self.portti, timeout=10)
        c.request("POST", "/kirjaudu", body="salasana=" + SAL,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        ev = r.getheader("Set-Cookie").split(";")[0]
        _, d = self.api(ev, "/api/uusi", {"tila": tila})
        return self.api(ev, "/api/viesti", {"keskustelu": d["id"], "teksti": teksti})

    def test_asetus_pois_kehote_ennallaan(self):
        self.kaynnista(None)
        for tila in ("tyokalu", "yksityinen"):
            s, _ = self.viesti(tila)
            self.assertEqual(s, 200)
            self.assertNotIn("AGENTTIDATA", self.muistit[tila][0])
        self.assertIn("KIRJASTO-SISALTO", self.muistit["tyokalu"][0])

    def test_paalla_molemmissa_tiloissa(self):
        self.kaynnista(str(self.ad))
        for tila in ("tyokalu", "yksityinen"):
            s, v = self.viesti(tila)
            self.assertEqual(s, 200)
            m = self.muistit[tila][0]
            self.assertIn("AGENTTIDATA (l\u00e4hde:", m)
            self.assertIn("**A100 ", m)
            self.assertIn("FAKTA-SISALTO", m)
            self.assertIn("KOMPASSI-SISALTO", m)
            self.assertNotIn("TULOS-SISALTO", m)
            self.assertNotIn("TEHTAVA-SISALTO", m)
        self.assertIn("KIRJASTO-SISALTO", self.muistit["tyokalu"][0])
        self.assertLessEqual(len(self.muistit["yksityinen"][0]), yksityinen.MUISTI_YLARAJA + 1_000)

    def test_lahdeviite_agenttidataan_kelpaa(self):
        self.kaynnista(str(self.ad))
        s, v = self.viesti("tyokalu")
        self.assertEqual(s, 200)
        self.assertEqual(v["tuntemattomia_lahteita"], 0)

    def test_paallekkainen_kirjoitettavan_kansion_kanssa_hylataan(self):
        for huono in (self.r / "kirjasto", self.r / "kirjasto" / "ad", self.r):
            with self.assertRaises(chat.ChatVirhe):
                self.kaynnista(str(huono))


class AsetusTesti(unittest.TestCase):
    def test_ymparistomuuttuja_ja_oletus(self):
        lahetetty = {}

        class Seis(Exception):
            pass

        def feikki(*a, **k):
            lahetetty.update(k)
            raise Seis()
        alkup = chat.Tila
        chat.Tila = feikki
        self.addCleanup(setattr, chat, "Tila", alkup)
        alkup_lue = chat.lue_tiiviste
        chat.lue_tiiviste = lambda p: "x"
        self.addCleanup(setattr, chat, "lue_tiiviste", alkup_lue)
        vanha = os.environ.pop("AIVO_AGENTTIDATA", None)
        self.addCleanup(lambda: os.environ.__setitem__("AIVO_AGENTTIDATA", vanha) if vanha is not None else None)
        with self.assertRaises(Seis):
            chat.main(["palvele"])
        self.assertIsNone(lahetetty["agenttidata"])
        os.environ["AIVO_AGENTTIDATA"] = "/var/lib/aivo/agenttidata"
        self.addCleanup(os.environ.pop, "AIVO_AGENTTIDATA", None)
        with self.assertRaises(Seis):
            chat.main(["palvele"])
        self.assertEqual(lahetetty["agenttidata"], "/var/lib/aivo/agenttidata")


if __name__ == "__main__":
    unittest.main()
