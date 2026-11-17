"""aivo_arvio osumat: osumaprosentti Tonylle (A990). Synteettinen jsonl, ei oikeaa tiedostoa."""
import io
import json
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from claudejono import aivo_arvio


def rivi(laji, tehtava, kylla, aika="2026-11-10T08:00:00+00:00", **muu):
    return json.dumps({"aika": aika, "laji": laji, "tehtava": tehtava, "kylla": kylla, "syy": "salainen-syy", **muu})


def aja(rivit, polku=None):
    """Kirjoittaa jsonl:n tilapaishakemistoon, ajaa komennon, palauttaa (rc, stdout, stderr, hakemiston sisalto ennen/jalkeen)."""
    with tempfile.TemporaryDirectory() as hak:
        p = Path(hak) / "a.jsonl"
        if rivit is not None:
            p.write_text("\n".join(rivit) + "\n", encoding="utf-8")
        ennen = sorted(os.listdir(hak))
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = aivo_arvio.main(["osumat", "--polku", polku or str(p)])
        return rc, o.getvalue(), e.getvalue(), ennen, sorted(os.listdir(hak))


class Osumat(unittest.TestCase):
    def test_tonyn_tuomio_osumat(self):
        rc, ulos, _, _, _ = aja([rivi("aivo", "a", True), rivi("tony", "a", True), rivi("aivo", "b", True), rivi("tony", "b", False),
                                 rivi("aivo", "c", False), rivi("tony", "c", False)])
        self.assertEqual(rc, 0)
        self.assertIn("Vertailtavia: 3, osumia: 2, osumaprosentti: 66.7 %", ulos)

    def test_lopputulos_vertailuun(self):
        rivit = [rivi("aivo", "a", True, tulos="VALMIS"), rivi("aivo", "b", False, tulos="HYLATTY"),
                 rivi("aivo", "c", False, tulos="KESKEN"), rivi("aivo", "d", True, tulos="KESKEN")]
        _, ulos, _, _, _ = aja(rivit)
        self.assertIn("Vertailtavia: 4, osumia: 3, osumaprosentti: 75.0 %", ulos)

    def test_tonyn_tuomio_ohittaa_lopputuloksen(self):
        _, ulos, _, _, _ = aja([rivi("aivo", "a", True, tulos="HYLATTY"), rivi("tony", "a", True)])
        self.assertIn("Vertailtavia: 1, osumia: 1, osumaprosentti: 100.0 %", ulos)

    def test_epaonnistunut_ja_tulokseton_pois(self):
        rivit = [rivi("aivo", "a", True, tulos="EPAONNISTUI"), rivi("aivo", "b", True), rivi("aivo", "c", True, tulos="VALMIS")]
        _, ulos, _, _, _ = aja(rivit)
        self.assertIn("Arvioita yhteens\xe4: 3", ulos)
        self.assertIn("Vertailtavia: 1, osumia: 1", ulos)

    def test_ei_vertailtavia_ei_prosenttia(self):
        _, ulos, _, _, _ = aja([rivi("aivo", "a", True)])
        self.assertIn("osumaprosentti: ei viel\xe4 laskettavissa", ulos)

    def test_aikavali(self):
        _, ulos, _, _, _ = aja([rivi("aivo", "a", True, aika="2026-11-12T01:00:00+00:00"), rivi("aivo", "b", True, aika="2026-11-03T23:00:00+00:00"),
                                rivi("tony", "a", True, aika="2026-12-30T00:00:00+00:00")])
        self.assertIn("aikav\xe4li 2026-11-03 - 2026-11-12", ulos)

    def test_tuorein_rivi_korvaa(self):
        _, ulos, _, _, _ = aja([rivi("aivo", "a", True), rivi("tony", "a", False), rivi("tony", "a", True)])
        self.assertIn("Vertailtavia: 1, osumia: 1", ulos)

    def test_raja_taynna_vasta_20_vertailtavalla(self):
        def sarja(n):
            return [r for i in range(n) for r in (rivi("aivo", f"t{i}", True), rivi("tony", f"t{i}", True))]
        self.assertIn("t\xe4ynn\xe4: ei", aja(sarja(19))[1])
        self.assertIn("t\xe4ynn\xe4: kyll\xe4", aja(sarja(20))[1])

    def test_rikkinainen_rivi_ohitetaan_ja_lasketaan(self):
        rc, ulos, _, _, _ = aja([rivi("aivo", "a", True), "{ei json", "[1,2]", rivi("tony", "a", True)])
        self.assertEqual(rc, 0)
        self.assertIn("Vertailtavia: 1, osumia: 1", ulos)
        self.assertIn("rikkin\xe4isi\xe4 rivej\xe4: 2", ulos)

    def test_puuttuva_tiedosto_rc1(self):
        rc, ulos, err, _, _ = aja(None)
        self.assertEqual(rc, 1)
        self.assertEqual(ulos, "")
        self.assertIn("virhe: tiedostoa ei voi lukea (FileNotFoundError)", err)

    def test_ei_nimia_syita_eika_rivej(self):
        _, ulos, err, _, _ = aja([rivi("aivo", "salainen-tehtava-nimi", True), rivi("tony", "salainen-tehtava-nimi", True)])
        for kielletty in ("salainen", "tehtava-nimi", "{", "syy"):
            self.assertNotIn(kielletty, ulos + err)

    def test_ei_tiedostokirjoituksia(self):
        with tempfile.TemporaryDirectory() as hak:
            p = Path(hak) / "a.jsonl"
            p.write_text(rivi("aivo", "a", True) + "\n", encoding="utf-8")
            os.chmod(p, 0o600)
            ennen = (sorted(os.listdir(hak)), p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            with mock.patch("builtins.open", wraps=open) as av, redirect_stdout(io.StringIO()):
                aivo_arvio.main(["osumat", "--polku", str(p)])
            tilat = [c.args[1] if len(c.args) > 1 else c.kwargs.get("mode", "r") for c in av.call_args_list]
            self.assertTrue(all(set(t) <= set("rbt") for t in tilat), tilat)
            self.assertEqual(ennen, (sorted(os.listdir(hak)), p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode))

    def test_ei_verkkoyhteyksia(self):
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("verkko")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("verkko")):
            self.assertEqual(aja([rivi("aivo", "a", True)])[0], 0)

    def test_oletuspolku(self):
        self.assertEqual(aivo_arvio.OSUMAT_OLETUSPOLKU, "/var/lib/claude-jono/aivo-arviot.jsonl")
        with mock.patch("builtins.open", side_effect=PermissionError("x")) as av, redirect_stderr(io.StringIO()) as e:
            rc = aivo_arvio.main(["osumat"])
        self.assertEqual(rc, 1)
        self.assertEqual(av.call_args.args[0], "/var/lib/claude-jono/aivo-arviot.jsonl")
        self.assertIn("(PermissionError)", e.getvalue())


if __name__ == "__main__":
    unittest.main()
