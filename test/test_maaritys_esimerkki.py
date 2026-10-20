import os
import unittest

from agentti import maaritys


class EsimerkkiTest(unittest.TestCase):
    def test_esimerkki_on_kelvollinen(self):
        polku = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "maaritys.esimerkki.json")
        self.assertEqual(maaritys.lue(polku)["nimi"], "ideointi")


if __name__ == "__main__":
    unittest.main()
