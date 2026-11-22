"""Drive-asiakkaan HTTP-virhekoodien testit (200, 401, 403, 404, 500, tyhja vastaus). Ei verkkoa, ei tunnistetiedostoja."""
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest import mock

from aivo import drive

KOODIT_VIRHE = (401, 403, 404, 500)


class Vast:
    def __init__(self, tila, runko):
        self.status, self._r = tila, runko
        self.luettu_n = None

    def read(self, n=-1):
        self.luettu_n = n
        return self._r if n < 0 else self._r[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Feikki:
    """Palauttaa jonosta (tila, runko); muu tila kuin 200 nostaa HTTPError kuten urlopen."""

    def __init__(self, *vastaukset):
        self.v, self.kutsut, self.vast = list(vastaukset), [], []

    def __call__(self, pyynto, timeout=None):
        self.kutsut.append((pyynto.get_method(), pyynto.full_url, dict(pyynto.header_items()), timeout))
        tila, runko = self.v.pop(0)
        if tila != 200:
            raise urllib.error.HTTPError(pyynto.full_url, tila, "x", {}, io.BytesIO(b"salainen-virherunko"))
        v = Vast(tila, runko if isinstance(runko, bytes) else json.dumps(runko).encode())
        self.vast.append(v)
        return v


TUNNUS = {"client_id": "a", "client_secret": "b", "refresh_token": "c"}


class PyyntoTesti(unittest.TestCase):
    def test_200_palauttaa_tilan_ja_rungon(self):
        f = Feikki((200, b"abc"))
        self.assertEqual(drive._pyynto("GET", drive.API + "files", {"X": "y"}, None, f), (200, b"abc"))
        self.assertEqual(f.kutsut[0][3], 60)                               # aikaraja
        self.assertEqual(f.kutsut[0][2].get("X"), "y")                     # otsakkeet menevat mukaan

    def test_luku_rajataan_yhta_yli_enimmaisen(self):
        f = Feikki((200, b"x" * (drive.MAX_TAVUA + 50)))
        tila, runko = drive._pyynto("GET", drive.API + "files", None, None, f)
        self.assertEqual(f.vast[0].luettu_n, drive.MAX_TAVUA + 1)
        self.assertEqual(len(runko), drive.MAX_TAVUA + 1)

    def test_otsakkeeton_pyynto_toimii(self):
        self.assertEqual(drive._pyynto("GET", drive.API + "files", None, None, Feikki((200, b"")))[0], 200)

    def test_http_virheet_palautuvat_tilana_ilman_runkoa(self):
        for koodi in KOODIT_VIRHE:
            with self.subTest(koodi=koodi):
                self.assertEqual(drive._pyynto("GET", drive.API + "files", None, None, Feikki((koodi, b""))),
                                 (koodi, b""))

    def test_verkkovirhe_kertoo_vain_tyypin(self):
        def avaa(pyynto, timeout=None):
            raise urllib.error.URLError("salainen-syy")
        with self.assertRaises(drive.DriveVirhe) as e:
            drive._pyynto("GET", drive.API + "files", None, None, avaa)
        self.assertIn("URLError", str(e.exception))
        self.assertNotIn("salainen", str(e.exception))


class PaivitaPaasyTesti(unittest.TestCase):
    def test_200_palauttaa_access_tunnuksen(self):
        f = Feikki((200, {"access_token": "AT"}))
        self.assertEqual(drive.paivita_paasy(TUNNUS, f), "AT")
        self.assertEqual(f.kutsut[0][0], "POST")

    def test_virhekoodit_nostavat_virheen_ja_kertovat_tilan(self):
        for koodi in KOODIT_VIRHE:
            with self.subTest(koodi=koodi):
                with self.assertRaises(drive.DriveVirhe) as e:
                    drive.paivita_paasy(TUNNUS, Feikki((koodi, b"")))
                self.assertIn("HTTP %d" % koodi, str(e.exception))
                self.assertNotIn("salainen", str(e.exception))

    def test_tyhja_vastaus_ei_anna_tunnusta(self):
        with self.assertRaises(drive.DriveVirhe) as e:
            drive.paivita_paasy(TUNNUS, Feikki((200, b"")))
        self.assertIn("virheellinen", str(e.exception))

    def test_vastaus_ilman_access_tokenia_hylataan(self):
        with self.assertRaises(drive.DriveVirhe):
            drive.paivita_paasy(TUNNUS, Feikki((200, {"muu": 1})))
        with self.assertRaises(drive.DriveVirhe):
            drive.paivita_paasy(TUNNUS, Feikki((200, b"[]")))


class AsiakasVirheTesti(unittest.TestCase):
    def test_get_virhekoodit_nostavat_virheen_tilalla(self):
        for koodi in KOODIT_VIRHE:
            with self.subTest(koodi=koodi):
                a = drive.Asiakas("tok", Feikki((koodi, b"")))
                with self.assertRaises(drive.DriveVirhe) as e:
                    a.uusimmat(3)
                self.assertIn("HTTP %d" % koodi, str(e.exception))
                self.assertNotIn("salainen", str(e.exception))

    def test_tiedot_ja_sisalto_nostavat_virheen_404(self):
        with self.assertRaises(drive.DriveVirhe):
            drive.Asiakas("t", Feikki((404, b""))).tiedot("x")
        meta = {"id": "i", "mimeType": drive.GOOGLE_DOC, "parents": [drive.AIVO_KANSIO_ID]}
        with self.assertRaises(drive.DriveVirhe):
            drive.Asiakas("t", Feikki((401, b""))).sisalto(meta)

    def test_200_palauttaa_tiedostot(self):
        r = drive.Asiakas("t", Feikki((200, {"files": [{"id": "1"}]}))).uusimmat(3)
        self.assertEqual(r, [{"id": "1"}])

    def test_200_tyhja_lista_ja_puuttuva_files(self):
        self.assertEqual(drive.Asiakas("t", Feikki((200, {"files": []}))).uusimmat(3), [])
        self.assertEqual(drive.Asiakas("t", Feikki((200, {}))).uusimmat(3), [])

    def test_tyhja_runko_200_ei_palauta_hiljaa_tyhjaa(self):
        with self.assertRaises(ValueError):
            drive.Asiakas("t", Feikki((200, b""))).uusimmat(3)

    def test_tyhja_sisalto_on_tyhja_merkkijono(self):
        meta = {"id": "i", "mimeType": "text/plain", "parents": [drive.AIVO_KANSIO_ID]}
        self.assertEqual(drive.Asiakas("t", Feikki((200, b""))).sisalto(meta), "")

    def test_sivukoko_rajataan_valille_1_100(self):
        for syote, odotettu in ((10, "10"), (0, "1"), (1, "1"), (2, "2"), (100, "100"), (99, "99"), (500, "100")):
            with self.subTest(n=syote):
                f = Feikki((200, {"files": []}))
                drive.Asiakas("t", f).uusimmat(syote)
                self.assertIn("pageSize=" + odotettu + "&", f.kutsut[0][1])

    def test_oletussivukoko_on_10(self):
        f = Feikki((200, {"files": []}))
        drive.Asiakas("t", f).uusimmat()
        self.assertIn("pageSize=10&", f.kutsut[0][1])

    def test_kansion_nimi(self):
        self.assertEqual(drive.Asiakas("t", Feikki((200, {"name": "Aivo"}))).kansion_nimi("k"), "Aivo")
        self.assertEqual(drive.Asiakas("t", Feikki((200, {}))).kansion_nimi("k"), "?")
        for koodi in KOODIT_VIRHE:
            with self.subTest(koodi=koodi):
                self.assertEqual(drive.Asiakas("t", Feikki((koodi, b""))).kansion_nimi("k"), "?")
        self.assertEqual(drive.Asiakas("t", Feikki((200, b""))).kansion_nimi("k"), "?")

    def test_kirjoitustesti_palauttaa_tilan(self):
        for koodi in (200, 401, 403, 404, 500):
            with self.subTest(koodi=koodi):
                f = Feikki((koodi, {}))
                self.assertEqual(drive.Asiakas("t", f).kirjoitustesti(), koodi)
                self.assertEqual(f.kutsut[0][0], "POST")


class MainTesti(unittest.TestCase):
    """main() ilman tunnistetiedostoja: lue_tunnus, paivita_paasy ja Asiakas korvataan."""

    def aja(self, argv, asiakas=None, paasy=None):
        ulos, virhe = io.StringIO(), io.StringIO()
        paasy = paasy or mock.Mock(return_value="AT")
        with contextlib.ExitStack() as s:
            s.enter_context(mock.patch.object(drive, "lue_tunnus", return_value=dict(TUNNUS)))
            s.enter_context(mock.patch.object(drive, "paivita_paasy", paasy))
            if asiakas is not None:
                s.enter_context(mock.patch.object(drive, "Asiakas", return_value=asiakas))
            s.enter_context(contextlib.redirect_stdout(ulos))
            s.enter_context(contextlib.redirect_stderr(virhe))
            koodi = drive.main(argv)
        return koodi, ulos.getvalue(), virhe.getvalue()

    def test_kirjoitustesti_401_ja_403_ovat_odotettuja(self):
        for t in (401, 403):
            with self.subTest(t=t):
                a = mock.Mock(); a.kirjoitustesti.return_value = t
                koodi, ulos, virhe = self.aja(["kirjoitustesti"], a)
                self.assertEqual(koodi, 0)
                self.assertEqual(ulos.strip(), "kirjoitus hylatty (HTTP %d), odotettu" % t)

    def test_kirjoitustesti_muut_tilat_varoittavat(self):
        for t in (200, 402, 404, 500):
            with self.subTest(t=t):
                a = mock.Mock(); a.kirjoitustesti.return_value = t
                koodi, ulos, _ = self.aja(["kirjoitustesti"], a)
                self.assertEqual(koodi, 2)
                self.assertEqual(ulos.strip(), "VAROITUS: kirjoitus ei hylatty (HTTP %d)" % t)

    def test_tunnuksen_paivitys_401_antaa_virheen_ja_koodin_1(self):
        paasy = mock.Mock(side_effect=drive.DriveVirhe("tunnuksen paivitys epaonnistui (HTTP 401)"))
        a = mock.Mock()
        koodi, ulos, virhe = self.aja(["listaa"], a, paasy)
        self.assertEqual(koodi, 1)
        self.assertIn("HTTP 401", virhe)
        self.assertEqual(ulos, "")
        a.uusimmat.assert_not_called()

    def test_listaus_403_antaa_virheen_eika_tulosta_tyhjaa_listaa(self):
        asiakas = drive.Asiakas("t", Feikki((403, b"")))
        koodi, ulos, virhe = self.aja(["listaa"], asiakas)
        self.assertEqual(koodi, 1)
        self.assertIn("HTTP 403", virhe)
        self.assertEqual(ulos, "")

    def test_listaus_200_tulostaa_rivit_ja_koodin_0(self):
        a = mock.Mock()
        a.uusimmat.return_value = [{"modifiedTime": "2026-11-20T10:00:00Z", "name": "N", "mimeType": "M", "id": "I"}]
        koodi, ulos, _ = self.aja(["listaa", "-n", "5"], a)
        self.assertEqual((koodi, ulos), (0, "2026-11-20\tN\tM\tI\n"))
        a.uusimmat.assert_called_once_with(5)

    def test_listaus_oletus_on_10(self):
        a = mock.Mock(); a.uusimmat.return_value = []
        self.assertEqual(self.aja(["listaa"], a)[0], 0)
        a.uusimmat.assert_called_once_with(10)

    def test_tiivista_tuntematon_tyyppi_ja_404(self):
        a = mock.Mock(); a.tiedot.return_value = {"mimeType": "image/png"}; a.sisalto.return_value = None
        koodi, _, virhe = self.aja(["tiivista", "ID"], a)
        self.assertEqual(koodi, 1)
        self.assertIn("tiedostotyyppia ei tiivisteta: image/png", virhe)
        a2 = drive.Asiakas("t", Feikki((404, b"")))
        koodi, _, virhe = self.aja(["tiivista", "ID"], a2)
        self.assertEqual(koodi, 1)
        self.assertIn("HTTP 404", virhe)

    def test_odottamaton_virhe_tulostaa_vain_tyypin(self):
        a = mock.Mock(); a.uusimmat.side_effect = RuntimeError("salainen-viesti")
        koodi, _, virhe = self.aja(["listaa"], a)
        self.assertEqual(koodi, 1)
        self.assertIn("RuntimeError", virhe)
        self.assertNotIn("salainen", virhe)

    def test_vaikutus_kirjaus_ja_yhteensa(self):
        with tempfile.TemporaryDirectory() as d:
            koodi, ulos, _ = self.aja(["--data", d, "vaikutus", "paatos", "lahde", "kuvaus"])
            self.assertEqual((koodi, ulos.strip()), (0, "kirjattu"))
            koodi, ulos, _ = self.aja(["--data", d, "vaikutus", "yhteensa"])
            self.assertEqual(koodi, 0)
            self.assertEqual(json.loads(ulos), {"paatos": 1, "kysymys": 0, "yhteensa": 1})

    def test_vaikutus_huono_laji_antaa_virhekoodin(self):
        with self.assertRaises(SystemExit):
            self.aja(["vaikutus", "huono"])


class MuutTesti(unittest.TestCase):
    def test_nyt_palauttaa_ajan(self):
        self.assertIsInstance(drive._nyt(), datetime)
        self.assertEqual(drive._nyt().tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
