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


class TulosKirjaus(unittest.TestCase):
    """kirjaa_tulos kirjoittaa Aivon arvion viereen tehtavan lopputuloksen, jotta osumat voi verrata niita."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tila = self.td.name
        self.p = Path(self.tila) / aivo_arvio.TIEDOSTO

    def tearDown(self):
        self.td.cleanup()

    def osumat(self):
        with open(self.p, encoding="utf-8") as f:
            return aivo_arvio.laske_osumat(f)

    def test_arvio_ja_tulos_on_vertailtava(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        self.assertEqual(self.osumat()["vertailtavia"], 0)   # puuttuva tulos -> ei vertailtava
        self.assertTrue(aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS"))
        l = self.osumat()
        self.assertEqual((l["vertailtavia"], l["osumia"], l["prosentti"]), (1, 1, 100.0))

    def test_ei_osuma_kun_aivo_sanoi_kylla_mutta_hylatty(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "HYLATTY")
        l = self.osumat()
        self.assertEqual((l["vertailtavia"], l["osumia"], l["prosentti"]), (1, 0, 0.0))

    def test_epaonnistunut_kirjataan_mutta_ei_vertailla(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", False, "syy")
        self.assertTrue(aivo_arvio.kirjaa_tulos(self.tila, "a.md", "EPAONNISTUI"))
        self.assertEqual(self.osumat()["vertailtavia"], 0)

    def test_uusintaajon_tulos_korvaa_vanhan(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "KESKEN")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS")
        self.assertEqual(self.osumat()["osumia"], 1)

    def test_ilman_arviota_ei_kirjata(self):
        self.assertFalse(aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS"))
        self.assertFalse(self.p.exists())

    def test_tuntematon_tila_ei_kirjata(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        for t in ("", "ok", None, "VALMIS; rm", "valmiiksi"):
            self.assertFalse(aivo_arvio.kirjaa_tulos(self.tila, "a.md", t), t)
        self.assertEqual(len(self.p.read_text().splitlines()), 1)

    def test_pieni_kirjain_normalisoidaan(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        self.assertTrue(aivo_arvio.kirjaa_tulos(self.tila, "a.md", " valmis "))
        self.assertEqual(json.loads(self.p.read_text().splitlines()[-1])["tulos"], "VALMIS")

    def test_rivilla_vain_nimi_ja_tila_ja_oikeudet_0600(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS")
        d = json.loads(self.p.read_text().splitlines()[-1])
        self.assertEqual(sorted(d), ["aika", "laji", "tehtava", "tulos"])
        self.assertEqual(d["laji"], "tulos")
        self.assertEqual(oct(self.p.stat().st_mode & 0o777), "0o600")

    def test_tulosrivi_ei_muuta_arvioita_otosta_eika_osumaa(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS")
        self.assertEqual(aivo_arvio.arviot(self.tila), {"a.md": {"kylla": True, "syy": "syy", "tony": None}})
        self.assertEqual(aivo_arvio.osuma(self.tila), (0, 0, None, 1))

    def test_virhe_ei_nouse(self):
        aivo_arvio.kirjaa_arvio(self.tila, "a.md", True, "syy")
        with mock.patch.object(aivo_arvio, "_liita", side_effect=OSError("x")), redirect_stderr(io.StringIO()) as e:
            self.assertFalse(aivo_arvio.kirjaa_tulos(self.tila, "a.md", "VALMIS"))
        self.assertIn("(OSError)", e.getvalue())


if __name__ == "__main__":
    unittest.main()
