"""Kilpailun kytkenta jonoon (ajuri.aja) ja aamukoosteeseen: feikkimallit."""
import json
import random
import subprocess
import unittest
from datetime import datetime, timedelta

from claudejono import aamukooste, ajuri, kilpailu, kulutus
from claudejono.test_ajuri import Pohja
from claudejono.test_kilpailu import Feikki, FeikkiLitellm, KYSYMYS

TZ = kulutus.TZ
ENV = {"CLAUDEJONO_ITSESUUNNITTELU": "0"}
NIMI = "2026-11-04-01-arkkitehtuuri-kitka.md"


def tulos_teksti(repo, nimi):
    return (repo / ajuri.JONO / "tulokset" / nimi).read_text(encoding="utf-8")


class Jonoon(Pohja):
    def test_kilpailutehtava_ajetaan_kilpailuna_ja_tulos_kirjoitetaan(self):
        self.lisaa_tehtava(NIMI, KYSYMYS)
        f, l = Feikki(), FeikkiLitellm()
        viesti = ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=f, litellm=l)
        self.assertEqual(viesti, "claude-jono: %s VALMIS" % NIMI)
        teksti = tulos_teksti(self.repo, NIMI)
        for osa in ("## Kilpailun tulos", "Voittajan vastaus", "| Malli |", "- Malli: opus"):
            self.assertIn(osa, teksti)
        self.assertEqual(len(f.kutsut), 2)       # opus-kilpailija + tuomari
        self.assertEqual(len(l.kutsut), 2)
        self.assertEqual(len(kilpailu.lue_pisteet(self.tmp)), 3)
        lajit = sorted(r["laji"] for r in kulutus.lue(self.tmp))
        self.assertEqual(lajit, ["kilpailu"] * 3 + ["kilpailu-tuomari"])   # ei tuplakirjausta "tehtava"-rivina
        for kom, kw in f.kutsut:
            self.assertEqual(kom[kom.index("--tools") + 1], "")           # ei tyokaluja kenellakaan

    def test_virheellinen_kilpailurivi_epaonnistuu_eika_ajaa_mitaan(self):
        self.lisaa_tehtava(NIMI, "Kilpailu: opus, openrouter:kimi\nkysymys")
        f, l = Feikki(), FeikkiLitellm()
        self.assertEqual(ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=f, litellm=l), "claude-jono: %s EPAONNISTUI" % NIMI)
        self.assertEqual((f.kutsut, l.kutsut), ([], []))

    def test_kilpailu_ohitetaan_kun_clauden_kaytto_on_tauolla(self):
        self.lisaa_tehtava("2026-11-04-01-tee-x.md", "tee")

        def raja(kom, **kw):
            return subprocess.CompletedProcess(kom, 1, json.dumps({"subtype": "error_during_execution", "is_error": True,
                                                                     "result": "Claude usage limit reached"}), "")
        self.assertIn("KAYTTORAJA", ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=raja))
        self.lisaa_tehtava(NIMI, KYSYMYS)
        f = Feikki()
        viesti = ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=f, litellm=FeikkiLitellm())
        self.assertIn("jono odottaa", viesti)
        self.assertEqual(f.kutsut, [])


class Otos(Pohja):
    def test_joka_viides_tavallinen_tehtava_saa_vertailun(self):
        f, l = Feikki(), FeikkiLitellm()
        viestit = []
        for n in range(1, 6):
            nimi = "2026-11-04-%02d-tee-asia.md" % n
            self.lisaa_tehtava(nimi, "tee asia %d" % n)
            viestit.append(ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=f, litellm=l))
        self.assertTrue(all("VALMIS" in v for v in viestit), viestit)
        self.assertEqual(len(l.kutsut), 1)        # vertailu vain viidennella
        self.assertEqual(len(f.kutsut), 5 + 1)    # 5 tehtavaa + tuomari
        rivit = kilpailu.lue_pisteet(self.tmp)
        self.assertEqual(sorted(r["malli"] for r in rivit), ["openrouter:deepseek-flash", "sonnet"])
        self.assertTrue(all(r["laji"] == "otos" for r in rivit))
        # vertailu ei tee tulostiedostoa eika muutoksia: tulokset vain viidelle tehtavalle
        self.assertEqual(len(list((self.repo / ajuri.JONO / "tulokset").glob("*.md"))), 5)
        self.assertNotIn("Kilpailun tulos", "".join(p.read_text() for p in (self.repo / ajuri.JONO / "tulokset").glob("*.md")))

    def test_otoksen_virhe_ei_kaada_ajoa(self):
        n = ajuri.aja.__globals__["kilpailu"]
        alkup = n.otos
        n.otos = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("salainen"))
        try:
            (self.tmp / kilpailu.OTOS_LASKURI).write_text(json.dumps({"n": 4}))
            self.lisaa_tehtava("2026-11-04-01-tee-asia.md", "tee")
            self.assertIn("VALMIS", ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=Feikki(), litellm=FeikkiLitellm()))
        finally:
            n.otos = alkup

    def test_openrouter_reitti_ei_laske_otokseen(self):
        self.lisaa_tehtava("2026-11-04-01-x.md", "Malli: openrouter:deepseek-flash\nTiivista.")
        ajuri.aja(self.repo, self.tmp, env=dict(ENV), suorita=Feikki(), litellm=FeikkiLitellm())
        self.assertFalse((self.tmp / kilpailu.OTOS_LASKURI).exists())


class Aamukooste(Pohja):
    def koosta(self, nyt):
        t = aamukooste.keraa(str(self.repo), str(self.tmp / "yojono"), nyt, hae=lambda url: [], yksikot=lambda: [])
        return t, aamukooste.rivit(t)[4]

    def test_viikkokooste_vain_maanantaina(self):
        vk = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
        (self.tmp / kilpailu.PISTEET).write_text(json.dumps({"aika": vk.isoformat(), "malli": "opus", "yhteensa": 22, "voitto": True, "ok": True}) + "\n")
        _, ma = self.koosta(datetime(2026, 11, 9, 8, 0, tzinfo=TZ))
        self.assertIn("Ajattelun kilpailut viime viikolta: opus 1 kisaa, 1 voittoa", ma)
        _, ti = self.koosta(datetime(2026, 11, 10, 8, 0, tzinfo=TZ))
        self.assertNotIn("kilpailut", ti)


if __name__ == "__main__":
    unittest.main()
