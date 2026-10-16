import json
import os
import tempfile
import threading
import unittest

from agentti import kulu, rajat
from test.apu import kello


class KuluTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def uusi(self, **kw):
        return kulu.Kulu(self.tmp.name, kello(**kw))

    def test_kutsuraja_paivassa(self):
        k = self.uusi()
        for _ in range(rajat.KUTSUT_PAIVA):
            k.varaa()
        with self.assertRaises(kulu.KulukattoYlittyi) as e:
            k.varaa()
        self.assertEqual(e.exception.syy, "kutsut_paiva")

    def test_uusi_paiva_nollaa_paivarajan(self):
        a = self.uusi(paiva=16)
        for _ in range(rajat.KUTSUT_PAIVA):
            a.varaa()
        self.uusi(paiva=17).varaa()  # ei nosta

    def test_paivan_usd_katto(self):
        k = self.uusi()
        vaihe = rajat.KULU_PAIVA_USD
        # kirjataan todellinen kulu varauksen tilalle niin, etta paivan usd-katto tayttyy ennen kutsurajaa
        v = k.varaa()
        k.kirjaa(v, vaihe - rajat.KUTSU_ARVIO_USD / 2)
        with self.assertRaises(kulu.KulukattoYlittyi) as e:
            k.varaa()
        self.assertEqual(e.exception.syy, "kulu_paiva")

    def test_kuukausikatto(self):
        # edellisten paivien kulut tiedostoon: kuukausisumma on heti katon alapuolella
        taysi = rajat.KULU_KUUKAUSI_USD - rajat.KUTSU_ARVIO_USD / 2
        paivat = {"2026-10-%02d" % p: {"kutsut": 1, "usd": 0.0} for p in range(1, 15)}
        paivat["2026-10-01"]["usd"] = taysi
        with open(os.path.join(self.tmp.name, "kulu.json"), "w") as f:
            json.dump({"paivat": paivat}, f)
        with self.assertRaises(kulu.KulukattoYlittyi) as e:
            self.uusi(paiva=20).varaa()
        self.assertEqual(e.exception.syy, "kulu_kuukausi")

    def test_kuukausikatto_nollautuu_uutena_kuukautena(self):
        paivat = {"2026-10-01": {"kutsut": 1, "usd": rajat.KULU_KUUKAUSI_USD}}
        with open(os.path.join(self.tmp.name, "kulu.json"), "w") as f:
            json.dump({"paivat": paivat}, f)
        self.uusi(kk=11, paiva=2).varaa()

    def test_tasaus_pienentaa_varausta(self):
        k = self.uusi()
        v = k.varaa()
        k.kirjaa(v, 0.001)
        self.assertAlmostEqual(k.tilanne()["usd_tanaan"], 0.001, places=6)

    def test_tasaus_none_jattaa_varauksen(self):
        k = self.uusi()
        v = k.varaa()
        k.kirjaa(v, None)
        self.assertAlmostEqual(k.tilanne()["usd_tanaan"], rajat.KUTSU_ARVIO_USD, places=6)

    def test_rikkinainen_kirjanpito_pysayttaa(self):
        with open(os.path.join(self.tmp.name, "kulu.json"), "w") as f:
            f.write("{ei json")
        with self.assertRaises(kulu.KirjanpitoVirhe):
            self.uusi().varaa()
        # eika tiedostoa ylikirjoitettu hiljaa
        with open(os.path.join(self.tmp.name, "kulu.json")) as f:
            self.assertEqual(f.read(), "{ei json")

    def test_vaara_rakenne_pysayttaa(self):
        with open(os.path.join(self.tmp.name, "kulu.json"), "w") as f:
            json.dump({"paivat": {"2026-10-16": {"kutsut": "x", "usd": 0}}}, f)
        with self.assertRaises(kulu.KirjanpitoVirhe):
            self.uusi().varaa()

    def test_rinnakkaiset_varaukset_eivat_ylita_rajaa(self):
        onnistui, hylatty = [], []

        def tyo():
            try:
                self.uusi().varaa()
                onnistui.append(1)
            except kulu.KulukattoYlittyi:
                hylatty.append(1)

        saikeet = [threading.Thread(target=tyo) for _ in range(12)]
        [s.start() for s in saikeet]
        [s.join() for s in saikeet]
        self.assertEqual(len(onnistui), rajat.KUTSUT_PAIVA)
        self.assertEqual(len(hylatty), 12 - rajat.KUTSUT_PAIVA)

    def test_vanhat_paivat_karsitaan(self):
        paivat = {"2026-%02d-%02d" % (m, p): {"kutsut": 0, "usd": 0.0}
                  for m in (6, 7, 8) for p in range(1, 29)}
        with open(os.path.join(self.tmp.name, "kulu.json"), "w") as f:
            json.dump({"paivat": paivat}, f)
        self.uusi().varaa()
        with open(os.path.join(self.tmp.name, "kulu.json")) as f:
            self.assertLessEqual(len(json.load(f)["paivat"]), kulu.SAILYTYS_PAIVAA)


if __name__ == "__main__":
    unittest.main()
