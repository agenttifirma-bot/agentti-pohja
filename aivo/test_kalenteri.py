"""Testit aivo/kalenteri.py:lle. Ei verkkoa, ei oikeita osoitteita: haku on feikki, ICS on keksitty."""
import io
import logging
import os
import stat
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aivo import kalenteri
from aivo.kalenteri import IcalLahde, KalenteriVirhe, TZ

ICS = (Path(__file__).parent / "testidata" / "kalenteri.ics").read_bytes()
# Keksitty "salainen" osoite; testit varmistavat, ettei se vuoda.
OSOITE = "https://calendar.google.com/calendar/ical/keksitty%40esimerkki.invalid/private-SALAINENTUNNISTE123/basic.ics"
SALAINEN = "SALAINENTUNNISTE123"
ALKU = datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
LOPPU = datetime(2026, 11, 30, 0, 0, tzinfo=TZ)


def hae(teksti):
    return {t["otsikko"]: t for t in kalenteri.jasenna_ics(teksti, ALKU, LOPPU)}


class IcsTesti(unittest.TestCase):
    def setUp(self):
        self.lista = kalenteri.jasenna_ics(ICS.decode(), ALKU, LOPPU)
        self.otsikot = [t["otsikko"] for t in self.lista]

    def test_toistuva_viikkotapahtuma_ja_exdate(self):
        kerrat = [t["alku"] for t in self.lista if t["otsikko"] == "Viikkopalaveri, tiimi"]
        self.assertEqual(kerrat, [datetime(2026, 11, 16, 9, tzinfo=TZ), datetime(2026, 11, 25, 9, tzinfo=TZ)])

    def test_poikkeus_korvaa_esiintyman(self):
        t = [t for t in self.lista if t["otsikko"] == "Viikkopalaveri siirretty"]
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0]["alku"], datetime(2026, 11, 23, 11, tzinfo=TZ))
        self.assertNotIn(datetime(2026, 11, 23, 9, tzinfo=TZ), [x["alku"] for x in self.lista])

    def test_paikan_ja_otsikon_purku(self):
        t = [t for t in self.lista if t["otsikko"].startswith("Viikko")][0]
        self.assertEqual(t["paikka"], "Huone 1; ensimmainen kerros")
        self.assertIn("New Yorkin puhelu", self.otsikot)  # rivitaitto purettu

    def test_koko_paivan_tapahtuma(self):
        t = [t for t in self.lista if t["otsikko"] == "Kurssileiri"][0]
        self.assertTrue(t["koko_paiva"])
        self.assertEqual((t["alku"], t["loppu"]), (date(2026, 11, 20), date(2026, 11, 22)))

    def test_koko_paivan_tapahtuma_rajat(self):
        # DTEND on poissulkeva: 22.11. alkava haku ei saa nahda 20.-21.11. tapahtumaa
        a = datetime(2026, 11, 22, 0, 0, tzinfo=TZ)
        self.assertNotIn("Kurssileiri", [t["otsikko"] for t in kalenteri.jasenna_ics(ICS.decode(), a, a + timedelta(days=1))])
        b = datetime(2026, 11, 21, 12, 0, tzinfo=TZ)
        self.assertIn("Kurssileiri", [t["otsikko"] for t in kalenteri.jasenna_ics(ICS.decode(), b, b + timedelta(hours=1))])

    def test_aikavyohykkeet_muunnetaan_helsinkiin(self):
        u = [t for t in self.lista if t["otsikko"] == "UTC-tapahtuma"][0]
        self.assertEqual(u["alku"], datetime(2026, 11, 19, 14, 0, tzinfo=TZ))
        n = [t for t in self.lista if t["otsikko"] == "New Yorkin puhelu"][0]
        self.assertEqual(n["alku"].hour, 16)
        self.assertEqual(n["alku"].utcoffset(), timedelta(hours=2))

    def test_paivittainen_toisto_count_ja_kesto(self):
        kerrat = [t for t in self.lista if t["otsikko"] == "Lenkki"]
        self.assertEqual([t["alku"].day for t in kerrat], [24, 25, 26])
        self.assertEqual(kerrat[0]["loppu"] - kerrat[0]["alku"], timedelta(minutes=30))

    def test_peruttu_ohitetaan_ja_vanha_rajautuu_pois(self):
        self.assertNotIn("Peruttu tapaaminen", self.otsikot)
        self.assertNotIn("Vanha tapahtuma", self.otsikot)

    def test_kuukausitoistoa_ei_laajenneta(self):
        # rajoitus: vain ensimmainen esiintyma
        self.assertEqual(self.otsikot.count("Kuukausitapaaminen"), 1)
        pitka = kalenteri.jasenna_ics(ICS.decode(), datetime(2027, 1, 1, tzinfo=TZ), datetime(2027, 3, 1, tzinfo=TZ))
        self.assertNotIn("Kuukausitapaaminen", [t["otsikko"] for t in pitka])

    def test_jarjestys_alkamisajan_mukaan(self):
        avaimet = [datetime.combine(t["alku"], datetime.min.time(), tzinfo=TZ) if t["koko_paiva"] else t["alku"]
                   for t in self.lista]
        self.assertEqual(avaimet, sorted(avaimet))

    def test_until_ja_interval(self):
        ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nDTSTART;TZID=Europe/Helsinki:20261116T080000\n"
               "DTEND;TZID=Europe/Helsinki:20261116T090000\nRRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261120T060000Z\n"
               "SUMMARY:X\nEND:VEVENT\nEND:VCALENDAR\n")
        # 16., 18., 20.: 20.11. 08:00 Helsinki = 06:00Z, mukana (UNTIL on mukaan lukeva)
        self.assertEqual([t["alku"].day for t in kalenteri.jasenna_ics(ics, ALKU, LOPPU)], [16, 18, 20])
        ics2 = ics.replace("20261120T060000Z", "20261120T055959Z")
        self.assertEqual([t["alku"].day for t in kalenteri.jasenna_ics(ics2, ALKU, LOPPU)], [16, 18])

    def test_kesakuun_kesaaika(self):
        ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:b\nDTSTART:20260615T090000Z\nDTEND:20260615T100000Z\n"
               "SUMMARY:Kesa\nEND:VEVENT\nEND:VCALENDAR\n")
        t = kalenteri.jasenna_ics(ics, datetime(2026, 6, 15, tzinfo=TZ), datetime(2026, 6, 16, tzinfo=TZ))[0]
        self.assertEqual(t["alku"].hour, 12)  # EEST +3

    def test_viallinen_tapahtuma_ei_kaada_muita(self):
        ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:c\nDTSTART:EIPAIVA\nSUMMARY:Rikki\nEND:VEVENT\n"
               "BEGIN:VEVENT\nUID:d\nDTSTART:20261117T100000Z\nDTEND:20261117T110000Z\nSUMMARY:Ehja\nEND:VEVENT\nEND:VCALENDAR\n")
        self.assertEqual([t["otsikko"] for t in kalenteri.jasenna_ics(ics, ALKU, LOPPU)], ["Ehja"])

    def test_naivi_aika_hylataan(self):
        with self.assertRaises(ValueError):
            kalenteri.jasenna_ics(ICS.decode(), datetime(2026, 11, 16), LOPPU)

    def _ics(self, rivit):
        return "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\n" + "\n".join(rivit) + "\nEND:VEVENT\nEND:VCALENDAR\n"

    def test_until_paivamaara_on_mukaan_lukeva(self):
        ics = self._ics(["DTSTART;TZID=Europe/Helsinki:20261116T080000", "DTEND;TZID=Europe/Helsinki:20261116T090000",
                         "RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261120", "SUMMARY:X"])
        self.assertEqual([t["alku"].day for t in kalenteri.jasenna_ics(ics, ALKU, LOPPU)], [16, 18, 20])

    def test_viikkotoisto_ilman_byday_toistuu_alkamispaivana(self):
        ics = self._ics(["DTSTART;TZID=Europe/Helsinki:20261118T080000", "DTEND;TZID=Europe/Helsinki:20261118T090000",
                         "RRULE:FREQ=WEEKLY", "SUMMARY:X"])
        self.assertEqual([t["alku"].day for t in kalenteri.jasenna_ics(ics, ALKU, LOPPU)], [18, 25])

    def test_rivinvaihto_tekstissa_ja_tyhja_otsikko(self):
        ics = self._ics(["DTSTART:20261117T100000Z", "DTEND:20261117T110000Z", "LOCATION:Rivi 1\\nRivi 2"])
        t = kalenteri.jasenna_ics(ics, ALKU, LOPPU)[0]
        self.assertEqual(t["paikka"], "Rivi 1\nRivi 2")
        self.assertEqual(t["otsikko"], "(ei otsikkoa)")

    def test_kesto_jasennin(self):
        self.assertEqual(kalenteri._kesto("P1DT2H30M"), timedelta(days=1, hours=2, minutes=30))
        self.assertEqual(kalenteri._kesto("PT15M"), timedelta(minutes=15))
        self.assertEqual(kalenteri._kesto("P1W"), timedelta(weeks=1))
        with self.assertRaises(ValueError):
            kalenteri._kesto("1H")


class OsoiteTesti(unittest.TestCase):
    def test_oikea_osoite_hyvaksytaan(self):
        self.assertEqual(kalenteri.tarkista_osoite(OSOITE), OSOITE)

    def test_http_hylataan(self):
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.tarkista_osoite(OSOITE.replace("https:", "http:"))
        self.assertNotIn(SALAINEN, str(e.exception))

    def test_vaara_isanta_hylataan(self):
        for huono in (
            "https://example.com/calendar/ical/x/private-SALAINENTUNNISTE123/basic.ics",
            "https://calendar.google.com.paha.example/x/private-SALAINENTUNNISTE123/basic.ics",
            "https://paha.example/calendar.google.com/private-SALAINENTUNNISTE123/basic.ics",
            "https://calendar.google.com@paha.example/private-SALAINENTUNNISTE123/basic.ics",
            "https://calendar.google.com:8443/private-SALAINENTUNNISTE123/basic.ics",
            "https://kayttaja:salasana@calendar.google.com/private-SALAINENTUNNISTE123/basic.ics",
            "https://Calendar.Google.Com.paha.example/private-SALAINENTUNNISTE123/basic.ics",
            "ftp://calendar.google.com/private-SALAINENTUNNISTE123/basic.ics",
            "file:///etc/passwd",
            "//calendar.google.com/private-SALAINENTUNNISTE123/basic.ics",
        ):
            with self.subTest(huono=huono.split("private")[0]):
                with self.assertRaises(KalenteriVirhe) as e:
                    kalenteri.tarkista_osoite(huono)
                self.assertNotIn(SALAINEN, str(e.exception))
                self.assertNotIn("paha.example", str(e.exception))

    def test_isanta_kirjainkoko_ja_portti_443_sallitaan(self):
        kalenteri.tarkista_osoite("https://CALENDAR.google.com:443/calendar/ical/x/basic.ics")

    def test_liian_pitka_osoite_hylataan(self):
        pitka = "https://calendar.google.com/" + "a" * 2000 + "/basic.ics"
        with self.assertRaises(KalenteriVirhe):
            kalenteri.tarkista_osoite(pitka)
        kalenteri.tarkista_osoite("https://calendar.google.com/" + "a" * 1900 + "/basic.ics")

    def test_valilyonti_ja_roska_hylataan(self):
        for huono in ("", None, 5, OSOITE + " x", OSOITE + "\n/..", OSOITE + "\u00e4", "x" * 5000):
            with self.assertRaises(KalenteriVirhe):
                kalenteri.tarkista_osoite(huono)


class TiedostoTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.polku = os.path.join(self.tmp.name, "osoite")

    def kirjoita(self, teksti, tila=0o600):
        fd = os.open(self.polku, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, teksti.encode())
        os.close(fd)
        os.chmod(self.polku, tila)

    def test_lukee_osoitteen_ja_poistaa_rivinvaihdon(self):
        self.kirjoita(OSOITE + "\n")
        self.assertEqual(kalenteri.lue_osoite(self.polku), OSOITE)

    def test_liian_laajat_oikeudet_hylataan_eika_sisaltoa_nay(self):
        for tila in (0o644, 0o640, 0o604, 0o660):
            self.kirjoita(OSOITE, tila)
            with self.assertRaises(KalenteriVirhe) as e:
                kalenteri.lue_osoite(self.polku)
            self.assertNotIn(SALAINEN, str(e.exception))
            self.assertIn("600", str(e.exception))

    def test_puuttuva_tiedosto_antaa_vain_tyypin(self):
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.lue_osoite(os.path.join(self.tmp.name, "ei-ole"))
        self.assertIn("FileNotFoundError", str(e.exception))
        self.assertNotIn(self.tmp.name, str(e.exception))

    def test_symlink_hylataan(self):
        self.kirjoita(OSOITE)
        linkki = os.path.join(self.tmp.name, "linkki")
        os.symlink(self.polku, linkki)
        with self.assertRaises(KalenteriVirhe):
            kalenteri.lue_osoite(linkki)

    def test_hakemisto_hylataan(self):
        with self.assertRaises(KalenteriVirhe):
            kalenteri.lue_osoite(self.tmp.name)

    def test_vaara_isanta_tiedostossa_hylataan(self):
        self.kirjoita("https://paha.example/private-SALAINENTUNNISTE123/basic.ics")
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.lue_osoite(self.polku)
        self.assertNotIn(SALAINEN, str(e.exception))


class FeikkiHaku:
    def __init__(self, *vastaukset):
        self.v, self.osoitteet = list(vastaukset), []

    def __call__(self, osoite):
        self.osoitteet.append(osoite)
        v = self.v.pop(0)
        if isinstance(v, Exception):
            raise v
        return v


class Kello:
    def __init__(self):
        self.t = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


class LahdeTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.osoite = os.path.join(self.tmp.name, "osoite")
        fd = os.open(self.osoite, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, OSOITE.encode())
        os.close(fd)
        self.data = os.path.join(self.tmp.name, "data", "kalenteri")
        self.kello = Kello()

    def lahde(self, hae):
        l = IcalLahde(self.osoite, self.data, hae=hae, nyt=self.kello)
        # valimuistin mtime on oikea kello; seurataan sita feikkikellolla
        return l

    def aseta_mtime(self, l):
        t = self.kello.t.timestamp()
        os.utime(l.valimuisti, (t, t))

    def test_hakee_ja_palauttaa_tapahtumat(self):
        h = FeikkiHaku(ICS)
        l = self.lahde(h)
        tulos = l.tapahtumat(ALKU, LOPPU)
        self.assertIn("Lenkki", [t["otsikko"] for t in tulos])
        self.assertEqual(h.osoitteet, [OSOITE])
        self.assertEqual(set(tulos[0]), {"otsikko", "alku", "loppu", "paikka", "koko_paiva"})

    def test_valimuisti_oikeudet_0600_ja_kansio_0700(self):
        l = self.lahde(FeikkiHaku(ICS))
        l.tapahtumat(ALKU, LOPPU)
        self.assertEqual(stat.S_IMODE(os.stat(l.valimuisti).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(l.valimuisti)).st_mode), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(l.valimuisti)), ["kalenteri.ics"])

    def test_valimuisti_ei_sisalla_osoitetta(self):
        l = self.lahde(FeikkiHaku(ICS))
        l.tapahtumat(ALKU, LOPPU)
        self.assertNotIn(SALAINEN.encode(), Path(l.valimuisti).read_bytes())

    def test_toinen_haku_15_minuutin_sisalla_kayttaa_valimuistia(self):
        h = FeikkiHaku(ICS)
        l = self.lahde(h)
        l.tapahtumat(ALKU, LOPPU)
        self.aseta_mtime(l)
        self.kello.t += timedelta(minutes=14, seconds=59)
        l.tapahtumat(ALKU, LOPPU)
        self.assertEqual(len(h.osoitteet), 1)

    def test_tasan_15_minuutin_kohdalla_haetaan_uudelleen(self):
        h = FeikkiHaku(ICS, ICS)
        l = self.lahde(h)
        l.tapahtumat(ALKU, LOPPU)
        self.aseta_mtime(l)
        self.kello.t += timedelta(minutes=15)
        l.tapahtumat(ALKU, LOPPU)
        self.assertEqual(len(h.osoitteet), 2)

    def test_valimuistin_kirjoitusvirhe_kirjaa_vain_tyypin(self):
        tiedosto = os.path.join(self.tmp.name, "tiedosto")
        Path(tiedosto).write_text("x")
        l = IcalLahde(self.osoite, os.path.join(tiedosto, "alikansio"), hae=FeikkiHaku(ICS), nyt=self.kello)
        with self.assertLogs("aivo.kalenteri", level="DEBUG") as loki:
            with self.assertRaises(KalenteriVirhe) as e:
                l.tapahtumat(ALKU, LOPPU)
        for teksti in [str(e.exception)] + loki.output:
            self.assertNotIn(self.tmp.name, teksti)
        self.assertTrue(any("Error" in t for t in loki.output))

    def test_15_minuutin_jalkeen_haetaan_uudelleen(self):
        h = FeikkiHaku(ICS, ICS)
        l = self.lahde(h)
        l.tapahtumat(ALKU, LOPPU)
        self.aseta_mtime(l)
        self.kello.t += timedelta(minutes=15, seconds=1)
        l.tapahtumat(ALKU, LOPPU)
        self.assertEqual(len(h.osoitteet), 2)

    def test_epaonnistunut_haku_ei_toistu_ennen_vaelia_ja_vanha_valimuisti_kay(self):
        h = FeikkiHaku(ICS, KalenteriVirhe("haku epaonnistui (HTTP 500)"))
        l = self.lahde(h)
        l.tapahtumat(ALKU, LOPPU)
        self.aseta_mtime(l)
        self.kello.t += timedelta(minutes=20)
        self.assertTrue(l.tapahtumat(ALKU, LOPPU))  # vanha valimuisti
        self.kello.t += timedelta(minutes=5)
        self.assertTrue(l.tapahtumat(ALKU, LOPPU))
        self.assertEqual(len(h.osoitteet), 2)  # ei uutta yritysta 15 min sisalla

    def test_haku_ilman_valimuistia_epaonnistuu_siististi(self):
        l = self.lahde(FeikkiHaku(KalenteriVirhe("haku epaonnistui (HTTP 404)")))
        with self.assertRaises(KalenteriVirhe) as e:
            l.tapahtumat(ALKU, LOPPU)
        self.assertIn("404", str(e.exception))
        self.assertFalse(os.path.exists(l.valimuisti))

    def test_vaara_osoite_ei_paase_hakuun_eika_vuoda(self):
        Path(self.osoite).write_text("https://paha.example/private-SALAINENTUNNISTE123/basic.ics")
        h = FeikkiHaku(ICS)
        l = self.lahde(h)
        with self.assertLogs("aivo.kalenteri", level="DEBUG") as loki:
            with self.assertRaises(KalenteriVirhe) as e:
                l.tapahtumat(ALKU, LOPPU)
        self.assertEqual(h.osoitteet, [])
        for teksti in [str(e.exception)] + loki.output:
            self.assertNotIn(SALAINEN, teksti)
            self.assertNotIn("paha.example", teksti)

    def test_osoite_ei_nay_lokissa_haun_epaonnistuessa(self):
        # feikki heittaa poikkeuksen, jonka viestissa on osoite; moduulin pitaa kirjata vain tyyppi
        h = FeikkiHaku(ICS, RuntimeError(OSOITE))
        l = self.lahde(h)
        l.tapahtumat(ALKU, LOPPU)
        self.aseta_mtime(l)
        self.kello.t += timedelta(minutes=20)
        puskuri = io.StringIO()
        kasittelija = logging.StreamHandler(puskuri)
        loki = logging.getLogger("aivo.kalenteri")
        loki.addHandler(kasittelija)
        self.addCleanup(loki.removeHandler, kasittelija)
        with self.assertRaises(RuntimeError):
            l.tapahtumat(ALKU, LOPPU)  # tuntematon poikkeus ei ole KalenteriVirhe: ei niellaa
        self.assertNotIn(SALAINEN, puskuri.getvalue())


class HaeHttpsTesti(unittest.TestCase):
    """hae_https ilman verkkoa: opener korvataan feikilla."""

    def setUp(self):
        self.vanha = kalenteri.urllib.request.build_opener
        self.addCleanup(setattr, kalenteri.urllib.request, "build_opener", self.vanha)

    def asenna(self, tila=200, runko=ICS, poikkeus=None):
        outer = self

        class R:
            status = tila

            def __init__(s):
                s.luettu = None

            def read(s, n=-1):
                s.luettu = n
                return runko[:n] if n >= 0 else runko

            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

        class O:
            def open(s, pyynto, timeout=None):
                outer.timeout = timeout
                outer.pyynto = pyynto
                if poikkeus:
                    raise poikkeus
                outer.vastaus = R()
                return outer.vastaus

        kalenteri.urllib.request.build_opener = lambda *a: O()

    def test_onnistunut_haku_get_aikarajalla(self):
        self.asenna()
        self.assertEqual(kalenteri.hae_https(OSOITE), ICS)
        self.assertEqual(self.pyynto.get_method(), "GET")
        self.assertEqual(self.timeout, kalenteri.AIKARAJA_S)

    def test_http_osoitetta_ei_haeta(self):
        self.asenna()
        with self.assertRaises(KalenteriVirhe):
            kalenteri.hae_https(OSOITE.replace("https:", "http:"))
        self.assertFalse(hasattr(self, "pyynto"))

    def test_liian_suuri_vastaus_hylataan(self):
        self.asenna(runko=b"BEGIN:VCALENDAR" + b"x" * 100)
        with self.assertRaises(KalenteriVirhe):
            kalenteri.hae_https(OSOITE, ylaraja=100)
        self.assertEqual(self.vastaus.luettu, 101)
        self.asenna(runko=b"BEGIN:VCALENDAR" + b"x" * 85)  # tasan 100 tavua
        self.assertEqual(len(kalenteri.hae_https(OSOITE, ylaraja=100)), 100)

    def test_muu_kuin_200_hylataan(self):
        self.asenna(tila=204)
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.hae_https(OSOITE)
        self.assertIn("204", str(e.exception))

    def test_ei_ical_hylataan(self):
        self.asenna(runko=b"<html>kirjaudu</html>")
        with self.assertRaises(KalenteriVirhe):
            kalenteri.hae_https(OSOITE)

    def test_virhetila_ei_sisalla_osoitetta(self):
        import urllib.error
        self.asenna(poikkeus=urllib.error.HTTPError(OSOITE, 404, "x", {}, None))
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.hae_https(OSOITE)
        self.assertIn("404", str(e.exception))
        self.assertNotIn(SALAINEN, str(e.exception))

    def test_muu_poikkeus_antaa_vain_tyypin(self):
        self.asenna(poikkeus=OSError("yhteys " + OSOITE))
        with self.assertRaises(KalenteriVirhe) as e:
            kalenteri.hae_https(OSOITE)
        self.assertIn("OSError", str(e.exception))
        self.assertNotIn(SALAINEN, str(e.exception))

    def test_uudelleenohjausta_ei_seurata(self):
        self.assertIsNone(kalenteri._EiUudelleenohjausta().redirect_request(None, None, 302, "x", {}, "https://paha.example/"))


if __name__ == "__main__":
    unittest.main()
