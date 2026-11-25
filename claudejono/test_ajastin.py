"""Kaista-ajastimen malli: kaista kaynnistyy aina myos uudelleen kytkemisen jalkeen (22.11.2026)."""
import unittest
from pathlib import Path

MALLI = Path(__file__).resolve().parent / "systemd" / "claude-jono@.timer.mall"
# Asetukset, jotka laskevat ajastimen omasta kaynnistyksesta tai kellosta, eivat palvelun edellisesta ajosta.
KAYNNISTYKSESTA = ("OnActiveSec", "OnCalendar")


def timer_osio(teksti):
    arvot, osio = {}, None
    for rivi in teksti.splitlines():
        rivi = rivi.strip()
        if not rivi or rivi.startswith(("#", ";")):
            continue
        if rivi.startswith("["):
            osio = rivi
            continue
        if osio == "[Timer]" and "=" in rivi:
            avain, arvo = rivi.split("=", 1)
            arvot.setdefault(avain.strip(), []).append(arvo.strip())
    return arvot


class KaistaAjastin(unittest.TestCase):
    def setUp(self):
        self.t = timer_osio(MALLI.read_text(encoding="utf-8"))

    def test_kaynnistyksesta_laskeva_asetus_on(self):
        self.assertTrue(any(self.t.get(k) and all(self.t[k]) for k in KAYNNISTYKSESTA),
                        f"[Timer]-osiossa pitaa olla jokin {KAYNNISTYKSESTA}, ei pelkka OnUnitInactiveSec")

    def test_ei_tyhjaa_nollausta(self):
        # Tyhja arvo (esim. OnActiveSec=) nollaa kaikki aiemmat ajastimet.
        for avain, arvot in self.t.items():
            if avain.startswith("On"):
                self.assertNotIn("", arvot, avain)

    def test_tahti_ja_yksikko_ennallaan(self):
        self.assertEqual(self.t.get("OnActiveSec"), ["1min"])
        self.assertEqual(self.t.get("OnUnitInactiveSec"), ["10min"])
        self.assertEqual(self.t.get("Persistent"), ["true"])
        self.assertEqual(self.t.get("Unit"), ["claude-jono@%i.service"])

    def test_tunnistaa_pelkan_onunitinactivesec(self):
        vanha = "[Timer]\nOnBootSec=5min\nOnUnitInactiveSec=10min\nPersistent=true\n"
        self.assertFalse(any(timer_osio(vanha).get(k) for k in KAYNNISTYKSESTA))


if __name__ == "__main__":
    unittest.main()
