import io
import json
import os
import stat
import tempfile
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from aivo import yksityinen


def ip(*osat):
    return ".".join(str(o) for o in osat)


class HakemistoTesti(unittest.TestCase):
    def test_luo_0700_ja_korjaa_laajat_oikeudet(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "yks"
            yksityinen.tarkista_yksityinen_hakemisto(p)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)
            os.chmod(p, 0o755)
            yksityinen.tarkista_yksityinen_hakemisto(p)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)

    def test_symlinkki_ja_tiedosto_hylataan(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "oikea").mkdir()
            os.symlink(Path(d) / "oikea", Path(d) / "linkki")
            with self.assertRaises(yksityinen.YksityinenVirhe):
                yksityinen.tarkista_yksityinen_hakemisto(Path(d) / "linkki")
            (Path(d) / "f").write_text("x")
            with self.assertRaises(yksityinen.YksityinenVirhe):
                yksityinen.tarkista_yksityinen_hakemisto(Path(d) / "f")

    def test_toisen_kayttajan_kansio_hylataan(self):
        with tempfile.TemporaryDirectory() as d:
            vanha = os.geteuid
            try:
                os.geteuid = lambda: vanha() + 1
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.tarkista_yksityinen_hakemisto(d)
            finally:
                os.geteuid = vanha


class MalliTesti(unittest.TestCase):
    def test_vain_loopback_ip(self):
        self.assertTrue(yksityinen.sallittu_malli_osoite("http://" + ip(127, 0, 0, 1) + ":8081"))
        self.assertTrue(yksityinen.sallittu_malli_osoite("http://[::1]:8081"))
        for paha in ("https://" + ip(127, 0, 0, 1), "http://localhost:8081", "http://example.com", "http://" + ip(10, 0, 0, 5),
                     "http://u:p@" + ip(127, 0, 0, 1), "", "roskaa"):
            self.assertFalse(yksityinen.sallittu_malli_osoite(paha), paha)

    def test_ulkoiseen_osoitteeseen_ei_lahteta_mitaan(self):
        kutsuttu = []
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.kysy_paikalliselta("m", [], "", "http://example.com", avaa=lambda *a, **k: kutsuttu.append(1))
        self.assertEqual(kutsuttu, [])

    def test_pyynto_ja_vastaus(self):
        saatu = {}

        class Vast(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def avaa(pyynto, timeout):
            saatu["url"] = pyynto.full_url
            saatu["runko"] = json.loads(pyynto.data)
            return Vast(json.dumps({"choices": [{"message": {"content": " Hei. "}}]}).encode())
        v = yksityinen.kysy_paikalliselta("MUISTI", [{"rooli": "tony", "teksti": "moi"}], "OHJE", avaa=avaa)
        self.assertEqual(v, "Hei.")
        self.assertTrue(saatu["url"].endswith("/v1/chat/completions"))
        viestit = saatu["runko"]["messages"]
        self.assertIn("OHJE", viestit[0]["content"])
        self.assertIn("MUISTI", viestit[0]["content"])
        self.assertEqual(viestit[1], {"role": "user", "content": "moi"})

    def test_virhe_ei_vuoda_sisaltoa(self):
        def avaa(*a, **k):
            raise OSError("salainen-sisalto")
        with self.assertRaises(yksityinen.YksityinenVirhe) as c:
            yksityinen.kysy_paikalliselta("m", [], avaa=avaa)
        self.assertNotIn("salainen", str(c.exception))


class OhjeetTesti(unittest.TestCase):
    def test_ydinohjeet_luetaan_mutta_ei_ulkopuolelta_eika_gitista(self):
        with tempfile.TemporaryDirectory() as d:
            juuri = Path(d) / "ohjeet"
            (juuri / ".git").mkdir(parents=True)
            (juuri / ".git" / "x.md").write_text("GIT")
            (juuri / "saannot.md").write_text("Saanto 1")
            (Path(d) / "ulko.md").write_text("ULKO")
            os.symlink(Path(d) / "ulko.md", juuri / "linkki.md")
            t = yksityinen.lue_ydinohjeet(juuri)
            self.assertIn("Saanto 1", t)
            self.assertNotIn("GIT", t)
            self.assertNotIn("ULKO", t)

    def test_ehdotus_ei_muuta_ohjeita_ennen_hyvaksyntaa(self):
        with tempfile.TemporaryDirectory() as d:
            eh, oh = Path(d) / "eh", Path(d) / "oh"
            oh.mkdir()
            (oh / "saannot.md").write_text("vanha\n")
            vastaus = yksityinen.irrota_ehdotukset(
                "Ehdotan.\n[[EHDOTUS saannot.md]]\nuusi\n[[/EHDOTUS]]\nValmis.",
                lambda n, t: yksityinen.tallenna_ehdotus(eh, n, t))
            self.assertNotIn("uusi", vastaus)
            self.assertIn("ei ole voimassa", vastaus)
            self.assertEqual((oh / "saannot.md").read_text(), "vanha\n")
            [eid] = yksityinen.listaa_ehdotukset(eh)
            self.assertEqual(stat.S_IMODE((eh / (eid + ".json")).stat().st_mode), 0o600)
            d1 = yksityinen.lue_ehdotus(eh, eid)
            for paha in ("", "kylla", "kyll\u00e4 00000000", "kyll\u00e4 " + d1["sha"][:8] + " x"):
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.hyvaksy_ehdotus(eh, oh, eid, paha, suorita=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
            self.assertEqual((oh / "saannot.md").read_text(), "vanha\n")
            yksityinen.hyvaksy_ehdotus(eh, oh, eid, "kyll\u00e4 " + d1["sha"][:8],
                                       suorita=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
            self.assertEqual((oh / "saannot.md").read_text(), "uusi\n")
            self.assertEqual(yksityinen.listaa_ehdotukset(eh), [])

    def test_muokattu_ehdotus_ei_mene_lapi(self):
        with tempfile.TemporaryDirectory() as d:
            eid = yksityinen.tallenna_ehdotus(d, "a.md", "teksti\n")
            p = Path(d) / (eid + ".json")
            j = json.loads(p.read_text())
            j["teksti"] = "vaihdettu\n"
            p.write_text(json.dumps(j))
            with self.assertRaises(yksityinen.YksityinenVirhe):
                yksityinen.lue_ehdotus(d, eid)

    def test_ehdotuksen_nimi_ei_paase_polkuun(self):
        with tempfile.TemporaryDirectory() as d:
            for nimi in ("../x.md", "a/b.md", "x.sh", ".md"):
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.tallenna_ehdotus(d, nimi, "x")

    def test_github_etarepo_estaa_ydinohjeiden_pushin(self):
        def suorita(kom, **k):
            if "get-url" in kom:
                return SimpleNamespace(returncode=0, stdout="https://github.com/x/y.git")
            return SimpleNamespace(returncode=0, stdout="")
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.julkaise_kirjastoon("k", "k/a.md", suorita)


class FakeGit:
    """Tallentaa git-kutsut ja palauttaa ohjelmoidut vastaukset (avain: git-alikomennon ensimmainen sana)."""
    def __init__(self, push_url="https://gitea.lan/aivo/ydinohjeet.git", commit_rc=0, status_out="M a.md\n",
                 poikkeus=None, haara="main"):
        self.kutsut, self.push_url, self.commit_rc, self.status_out = [], push_url, commit_rc, status_out
        self.poikkeus, self.haara = poikkeus, haara

    def __call__(self, kom, **k):
        self.kutsut.append(kom[3:])
        a = kom[3:]
        if self.poikkeus and a[0] == self.poikkeus[0]:
            raise self.poikkeus[1]
        if a[0] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="true\n")
        if a[0] == "remote":
            return SimpleNamespace(returncode=0, stdout=self.push_url + "\n")
        if a[0] == "symbolic-ref":
            return SimpleNamespace(returncode=0 if self.haara else 1, stdout=self.haara + "\n")
        if a[0] == "status":
            return SimpleNamespace(returncode=0, stdout=self.status_out)
        if a[0] == "commit":
            return SimpleNamespace(returncode=self.commit_rc, stdout="")
        return SimpleNamespace(returncode=0, stdout="")


class JulkaisuTesti(unittest.TestCase):
    SALLITTU = "gitea.lan"

    def _ehdotus(self, d):
        eh, oh = Path(d) / "eh", Path(d) / "oh"
        oh.mkdir()
        (oh / "a.md").write_text("vanha\n")
        eid = yksityinen.tallenna_ehdotus(eh, "a.md", "uusi\n")
        return eh, oh, eid, "kylla " + yksityinen.lue_ehdotus(eh, eid)["sha"][:8]

    def test_push_osoitteen_pitaa_olla_listalla_eika_sana_github_riita(self):
        for url in ("https://github.com/x/y.git", "git@github.com:x/y.git", "ssh://git@gh-alias/x.git",
                    "https://peili.example.org/x.git", "/polku/paikallinen", "https://gitea.lan.example.org/x.git"):
            with self.assertRaises(yksityinen.YksityinenVirhe, msg=url):
                yksityinen.tarkista_julkaisukohde("k", FakeGit(push_url=url), self.SALLITTU)
        for url in ("https://gitea.lan/aivo/y.git", "ssh://git@gitea.lan:2222/aivo/y.git", "git@GITEA.lan:aivo/y.git"):
            self.assertEqual(yksityinen.tarkista_julkaisukohde("k", FakeGit(push_url=url), self.SALLITTU)[0], "main")

    def test_tyhja_lista_estaa_kaiken_pushin(self):
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.tarkista_julkaisukohde("k", FakeGit(), "")

    def test_pushurl_tarkistetaan_push_valitsimella_ja_kaikki_osoitteet(self):
        g = FakeGit(push_url="https://gitea.lan/a.git\nhttps://github.com/x/y.git")
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.tarkista_julkaisukohde("k", g, self.SALLITTU)
        self.assertIn(("remote", "get-url", "--push", "--all", "origin"), [tuple(x) for x in g.kutsut])

    def test_push_nimeaa_kohteen_eika_kayta_pushdefaultia(self):
        g = FakeGit()
        self.assertEqual(yksityinen.julkaise_kirjastoon("k", "k/a.md", g, sallitut=self.SALLITTU), "pushattu")
        self.assertIn(["push", "origin", "HEAD:refs/heads/main"], g.kutsut)
        self.assertNotIn(["push"], g.kutsut)

    def test_detached_head_ei_pushaa(self):
        with self.assertRaises(yksityinen.YksityinenVirhe):
            yksityinen.tarkista_julkaisukohde("k", FakeGit(haara=""), self.SALLITTU)

    def test_kielletty_kohde_ei_muuta_ohjeita_eika_poista_ehdotusta(self):
        with tempfile.TemporaryDirectory() as d:
            eh, oh, eid, v = self._ehdotus(d)
            with self.assertRaises(yksityinen.YksityinenVirhe):
                yksityinen.hyvaksy_ehdotus(eh, oh, eid, v, FakeGit(push_url="https://github.com/x/y.git"), self.SALLITTU)
            self.assertEqual((oh / "a.md").read_text(), "vanha\n")
            self.assertEqual(yksityinen.listaa_ehdotukset(eh), [eid])

    def test_commit_virhe_palauttaa_tiedoston_ja_jattaa_ehdotuksen(self):
        with tempfile.TemporaryDirectory() as d:
            eh, oh, eid, v = self._ehdotus(d)
            g = FakeGit(commit_rc=128)
            with self.assertRaises(yksityinen.YksityinenVirhe) as c:
                yksityinen.hyvaksy_ehdotus(eh, oh, eid, v, g, self.SALLITTU)
            self.assertIn("commit", str(c.exception))
            self.assertEqual((oh / "a.md").read_text(), "vanha\n")
            self.assertEqual(yksityinen.listaa_ehdotukset(eh), [eid])
            self.assertTrue(any(k[0] == "reset" for k in g.kutsut))
            self.assertFalse(any(k[0] == "push" for k in g.kutsut))

    def test_git_timeout_ja_puuttuva_git_ovat_hallittuja_virheita(self):
        import subprocess
        for poik in (subprocess.TimeoutExpired("git", 1), FileNotFoundError()):
            with tempfile.TemporaryDirectory() as d:
                eh, oh, eid, v = self._ehdotus(d)
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.hyvaksy_ehdotus(eh, oh, eid, v, FakeGit(poikkeus=("rev-parse", poik)), self.SALLITTU)
                self.assertEqual((oh / "a.md").read_text(), "vanha\n")
                self.assertEqual(yksityinen.listaa_ehdotukset(eh), [eid])

    def test_onnistunut_hyvaksynta_poistaa_ehdotuksen_vasta_commitin_jalkeen(self):
        with tempfile.TemporaryDirectory() as d:
            eh, oh, eid, v = self._ehdotus(d)
            self.assertEqual(yksityinen.hyvaksy_ehdotus(eh, oh, eid, v, FakeGit(), self.SALLITTU), "pushattu")
            self.assertEqual((oh / "a.md").read_text(), "uusi\n")
            self.assertEqual(yksityinen.listaa_ehdotukset(eh), [])

    def test_push_epaonnistuminen_ei_peru_commitoitua_muutosta(self):
        class PushRikki(FakeGit):
            def __call__(self, kom, **k):
                r = super().__call__(kom, **k)
                return SimpleNamespace(returncode=1, stdout="") if kom[3] == "push" else r
        with tempfile.TemporaryDirectory() as d:
            eh, oh, eid, v = self._ehdotus(d)
            self.assertEqual(yksityinen.hyvaksy_ehdotus(eh, oh, eid, v, PushRikki(), self.SALLITTU), "push-epaonnistui")
            self.assertEqual((oh / "a.md").read_text(), "uusi\n")

    def test_muuttumaton_tiedosto_on_ei_muutosta_ei_virhe(self):
        self.assertEqual(yksityinen.julkaise_kirjastoon("k", "k/a.md", FakeGit(status_out=""), sallitut=self.SALLITTU),
                         "ei-muutosta")


class TurvaTesti(unittest.TestCase):
    def test_ydinohjekansion_laajat_oikeudet_korjataan_tai_hylataan(self):
        with tempfile.TemporaryDirectory() as d:
            oh = Path(d) / "oh"
            oh.mkdir()
            os.chmod(oh, 0o755)
            (oh / "a.md").write_text("saanto")
            self.assertIn("saanto", yksityinen.lue_ydinohjeet(oh))
            self.assertEqual(stat.S_IMODE(oh.stat().st_mode), 0o700)
            os.chmod(oh, 0o755)
            with unittest.mock.patch.object(yksityinen.os, "chmod", side_effect=PermissionError):
                with self.assertRaises(yksityinen.YksityinenVirhe):
                    yksityinen.lue_ydinohjeet(oh)

    def test_naytolle_ei_paase_ohjausmerkkeja(self):
        t = yksityinen.puhdista_naytolle("a\x1b[2Kb\rc\u202ed\tok\n")
        self.assertNotIn("\x1b", t)
        self.assertNotIn("\r", t)
        self.assertNotIn("\u202e", t)
        self.assertIn("\\x1b", t)
        self.assertIn("\\u202e", t)
        self.assertTrue(t.endswith("ok\n"))

    def test_ylitys_ei_ole_hiljainen(self):
        with tempfile.TemporaryDirectory() as d:
            oh = Path(d) / "oh"
            oh.mkdir(mode=0o700)
            (oh / "a-iso.md").write_text("x" * (yksityinen.YDINOHJE_YLARAJA - 10))
            (oh / "b-saanto.md").write_text("tarkea saanto " * 5)
            t = yksityinen.lue_ydinohjeet(oh)
            self.assertIn("ei mahtunut", t)
            self.assertIn("b-saanto.md", t.split("ei mahtunut")[1])

    def test_vioittunut_ehdotus_ei_kaada(self):
        with tempfile.TemporaryDirectory() as d:
            eid = "0123456789ab"
            for sisalto in ('{"tiedosto": 5, "teksti": "x", "sha": "y"}', '{"tiedosto": "a.md", "teksti": 7, "sha": "y"}',
                            '[1]', '"x"', '{"tiedosto": "a.md", "teksti": null, "sha": null}'):
                (Path(d) / (eid + ".json")).write_text(sisalto)
                with self.assertRaises(yksityinen.YksityinenVirhe, msg=sisalto):
                    yksityinen.lue_ehdotus(d, eid)
            with unittest.mock.patch.object(sys, "stdout", io.StringIO()) as out:
                self.assertEqual(yksityinen.main(["ehdotukset", "--ehdotukset", d]), 0)
            self.assertIn("viallinen", out.getvalue())


class MittaaTesti(unittest.TestCase):
    def test_mittaus_ja_ulkoinen_osoite(self):
        from aivo import mittaa_malli

        class Vast(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        avaa = lambda p, timeout: Vast(json.dumps({"choices": [{"message": {"content": "vastaus"}}],
                                                    "usage": {"completion_tokens": 10}}).encode())
        t = mittaa_malli.mittaa("http://" + ip(127, 0, 0, 1) + ":8081", avaa)
        self.assertEqual(len(t), len(mittaa_malli.KYSYMYKSET))
        self.assertEqual(t[0]["tokenia"], 10)
        with self.assertRaises(yksityinen.YksityinenVirhe):
            mittaa_malli.mittaa("http://example.com", avaa)


if __name__ == "__main__":
    unittest.main()
