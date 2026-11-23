import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from tools import systemd_ymparisto as s

JUURI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEMD_ANALYZE = shutil.which("systemd-analyze")
# Varoitukset, jotka systemd antaa virheellisesta Environment=-rivista.
SYSTEMD_VAROITUS = re.compile(r"Invalid environment assignment|Invalid syntax|Unbalanced quoting")
VIRHEELLINEN = "Environment=GIT_SSH_COMMAND=ssh -i /var/lib/aivo/.ssh/avain -o IdentitiesOnly=yes\n"
KORJATTU = 'Environment="GIT_SSH_COMMAND=ssh -i /var/lib/aivo/.ssh/avain -o IdentitiesOnly=yes"\n'


def mallit():
    """Kaikki repon yksikkomallit, joita systemd-analyze voi tarkistaa."""
    return [p for p, ohje in s.tiedostot(JUURI) if not ohje and ".service" in os.path.basename(p)]


class ArvonTarkistus(unittest.TestCase):
    def test_lainaamaton_valilyonti_hylataan(self):
        virheet = s.tarkista_arvo(VIRHEELLINEN.split("=", 1)[1].strip())
        self.assertEqual(len(virheet), 3)  # -i, polku, -o
        self.assertIn("'-i'", virheet[0])

    def test_lainattu_hyvaksytaan(self):
        self.assertEqual(s.tarkista_arvo(KORJATTU.split("=", 1)[1].strip()), [])

    def test_useampi_pari_samalla_rivilla_hyvaksytaan(self):
        self.assertEqual(s.tarkista_arvo("HOME=/var/lib/aivo PYTHONPATH=/opt/agentti-pohja"), [])
        self.assertEqual(s.tarkista_arvo('A=1 "B=kaksi sanaa" C='), [])

    def test_lainaus_vain_arvon_ymparilla_toimii_kuten_systemd(self):
        # systemd poistaa lainausmerkit sanan sisalta: A="x y" on yksi sana A=x y.
        self.assertEqual(s.tarkista_arvo('A="x y"'), [])

    def test_parittomat_lainausmerkit_hylataan(self):
        self.assertEqual(s.tarkista_arvo('"A=x y'), ["lainausmerkit parittomat"])

    def test_tyhja_arvo_hyvaksytaan(self):
        # Pelkka "Environment=" nollaa listan systemd:ssa.
        self.assertEqual(s.tarkista_arvo(""), [])

    def test_avaimen_muoto(self):
        self.assertTrue(s.tarkista_arvo("1A=x"))
        self.assertTrue(s.tarkista_arvo("=x"))
        self.assertTrue(s.tarkista_arvo("A-B=x"))


class RivienPoiminta(unittest.TestCase):
    def test_yksikossa_vain_rivin_alusta(self):
        teksti = "[Service]\n# Environment=A=b c\n  Environment=X=y z\nEnvironment=A=1\n"
        self.assertEqual(s.environment_rivit(teksti), [(4, "A=1")])

    def test_jatkorivi_yhdistetaan(self):
        teksti = "Environment=A=1 \\\n  B=2\n"
        self.assertEqual(s.tarkista_arvo(s.environment_rivit(teksti)[0][1]), [])
        teksti = "Environment=A=1 \\\n  ssh -i\n"
        self.assertTrue(s.tarkista_arvo(s.environment_rivit(teksti)[0][1]))

    def test_ohjeessa_sisennetty_lohko(self):
        teksti = "Teksti `Environment=A=b c` ei kuulu.\n| `Environment=A=b c` |\n   Environment=X=1\n"
        self.assertEqual(s.environment_rivit(teksti, ohje=True), [(3, "X=1")])

    def test_ei_sekoita_environmentfileen(self):
        self.assertEqual(s.environment_rivit("EnvironmentFile=-/etc/x y.env\n"), [])


class TiedostoTarkistus(unittest.TestCase):
    def test_virheellinen_malli_loydetaan_ja_korjattu_kelpaa(self):
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "koe.service.mall")
            with open(polku, "w") as f:
                f.write("[Service]\n" + VIRHEELLINEN)
            virheet = s.tarkista(d)
            self.assertEqual({(p, r) for p, r, _ in virheet}, {("koe.service.mall", 2)})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(s.main([d]), 1)
            with open(polku, "w") as f:
                f.write("[Service]\n" + KORJATTU)
            self.assertEqual(s.tarkista(d), [])

    def test_ohjeen_lohko_tarkistetaan(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "docs"))
            with open(os.path.join(d, "docs", "ohje.md"), "w") as f:
                f.write("```\n[Service]\n" + VIRHEELLINEN + "```\n")
            self.assertEqual(len(s.tarkista(d)), 3)

    def test_repon_mallit_ja_ohjeet_ovat_kunnossa(self):
        virheet = s.tarkista(JUURI)
        self.assertEqual(virheet, [], "\n".join("%s:%d: %s" % v for v in virheet))

    def test_mallit_loytyvat(self):
        nimet = {os.path.basename(p) for p in mallit()}
        self.assertIn("agenttidata-pull.service.mall", nimet)


@unittest.skipUnless(SYSTEMD_ANALYZE, "systemd-analyze puuttuu (esim. macOS)")
class SystemdAnalyze(unittest.TestCase):
    """Ajaa systemd-analyze verify -tarkistuksen malleille ja hylkaa Environment=-varoitukset.

    Muita verify-ilmoituksia (puuttuvat kayttajat, ohjelmat tai paikkamerkit) ei arvioida,
    koska ne riippuvat koneesta eivatka kerro Environment=-rivien jasentymisesta.
    """

    def verify(self, sisalto, nimi):
        with tempfile.TemporaryDirectory() as d:
            # Paikkamerkit (<GITEA-IP> ym.) korvataan kelvollisella dokumentaatio-osoitteella.
            sisalto = re.sub(r"<[^<>\n]+>", "192.0.2.1", sisalto)
            polku = os.path.join(d, nimi)
            with open(polku, "w") as f:
                f.write(sisalto)
            p = subprocess.run([SYSTEMD_ANALYZE, "verify", "--man=no", polku],
                               capture_output=True, text=True, timeout=60)
            return [r for r in (p.stdout + p.stderr).splitlines() if SYSTEMD_VAROITUS.search(r)]

    def test_virheellinen_rivi_tunnistetaan(self):
        # Varmistaa, etta tarkistus todella nakee vian (muuten alla oleva testi olisi tyhja).
        varoitukset = self.verify("[Service]\nType=oneshot\nExecStart=/bin/true\n" + VIRHEELLINEN, "koe.service")
        self.assertTrue(varoitukset)

    def test_repon_mallit(self):
        kaikki = []
        for polku in mallit():
            nimi = os.path.basename(polku)
            if nimi.endswith(".mall"):
                nimi = nimi[: -len(".mall")]
            if not nimi.endswith(".service"):
                continue
            nimi = nimi.replace("@.service", "@koe.service")
            with open(polku, encoding="utf-8") as f:
                sisalto = f.read()
            kaikki += ["%s: %s" % (os.path.relpath(polku, JUURI), r) for r in self.verify(sisalto, nimi)]
        self.assertEqual(kaikki, [], "\n".join(kaikki))


if __name__ == "__main__":
    unittest.main()
