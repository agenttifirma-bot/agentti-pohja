import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from agentti import autonomia as au
from agentti import pr_laatu

NYT = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
BOT = pr_laatu.BOTTI
TONY = pr_laatu.OMISTAJA


def iso(paivaa_sitten):
    return (NYT - timedelta(days=paivaa_sitten)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(nro, otsikko="yojono: testit x", tila="closed", merged=True, ika=5, kirjoittaja=BOT, runko=""):
    return {"number": nro, "title": otsikko, "state": tila, "body": runko, "created_at": iso(ika + 1),
            "merged_at": iso(ika) if merged and tila == "closed" else None, "closed_at": iso(ika) if tila == "closed" else None,
            "merge_commit_sha": "m%d" % nro, "head": {"sha": "h%d" % nro, "ref": "yo/x"}, "user": {"login": kirjoittaja}}


def tied(*nimet, rivit=1):
    return [{"filename": n, "additions": rivit, "deletions": 0, "status": "modified"} for n in nimet]


def ajot(*tulokset):
    return {"check_runs": [{"status": "completed", "conclusion": t} for t in tulokset]}


def feikki(prt, tiedostot=None, ci=None, kommentit=None, puuttuva=()):
    """prt: {repo: [PR]}; tiedostot: {nro: [..]}; ci: {sha: vastaus}; kommentit: {(tyyppi, nro): [..]}"""
    kutsut = []

    def hae(url):
        kutsut.append(url)
        osa = url.split("/repos/%s/" % TONY)[1]
        repo, loppu = osa.split("/", 1)
        if repo in puuttuva:
            raise OSError("403")
        if loppu.startswith("pulls?"):
            return prt.get(repo, [])
        nro = int(loppu.split("/")[1]) if loppu.startswith(("pulls/", "issues/")) else None
        if "/files" in loppu:
            return (tiedostot or {}).get(nro, tied("README.md"))
        if loppu.startswith("commits/"):
            return (ci or {}).get(loppu.split("/")[1], ajot("success"))
        if loppu.startswith("pulls/"):
            return (kommentit or {}).get(("r", nro), [])
        return (kommentit or {}).get(("i", nro), [])
    hae.kutsut = kutsut
    return hae


class AgenttiJaLuokka(unittest.TestCase):
    def test_agentti(self):
        self.assertEqual(au.agentti_prsta(pr(1)), "yojono")
        self.assertEqual(au.agentti_prsta(pr(1, "Claude-jono: dokumentit")), "claude-jono")
        self.assertEqual(au.agentti_prsta(pr(1, "Jotain", runko="Generated with [Claude Code](x)")), "pilvi")
        self.assertEqual(au.agentti_prsta(pr(1, "Jotain")), "muu")
        self.assertIsNone(au.agentti_prsta(pr(1, kirjoittaja=TONY)))

    def test_luokat(self):
        self.assertEqual(au.luokittele(tied("README.md", "docs/a.md")), "dokumentaatio")
        self.assertEqual(au.luokittele(tied("test/test_a.py", "docs/a.md")), "testit")
        self.assertEqual(au.luokittele(tied("agentti/a.py"), "x"), "pieni-korjaus")
        self.assertEqual(au.luokittele(tied("agentti/a.py", rivit=200)), "suurempi")
        self.assertEqual(au.luokittele(tied("package.json"), "Bump x from 1.2.3 to 1.2.4"), "riippuvuus-patch")
        self.assertEqual(au.luokittele(tied("package.json"), "Bump x from 1.2.3 to 1.3.0"), "suurempi")
        self.assertEqual(au.luokittele([]), "suurempi")

    def test_suojattu_voittaa(self):
        for n in (".github/workflows/a.yml", "tools/automerge.py", "agentti/config.py", "yojono/a.py", "test/token.md", "../x.md"):
            self.assertEqual(au.luokittele(tied(n, "README.md")), "suojattu", n)
        self.assertEqual(au.luokittele([{"filename": "docs/b.md", "previous_filename": "tools/a.md"}]), "suojattu")

    def test_ci(self):
        self.assertEqual(au.ci_tulos(ajot("success", "skipped")), "ok")
        self.assertEqual(au.ci_tulos(ajot("success", "failure")), "virhe")
        self.assertEqual(au.ci_tulos({"check_runs": []}), "tuntematon")
        self.assertEqual(au.ci_tulos({"check_runs": [{"status": "in_progress", "conclusion": None}]}), "tuntematon")


class Revertit(unittest.TestCase):
    def test_revert_viittauksella_ja_otsikolla(self):
        prt = [pr(1, "yojono: a"), pr(2, "yojono: b"), pr(3, "Revert #1", runko="Reverts #1", kirjoittaja=TONY, ika=2),
               pr(4, 'Revert "yojono: b"', kirjoittaja=TONY, ika=1), pr(5, "Reverts nothing")]
        r = au.revertoidut(prt)
        self.assertEqual(sorted(r), [1, 2])
        self.assertNotIn(3, r)

    def test_itseensa_ei_viittaa(self):
        self.assertEqual(au.revertoidut([pr(7, "Revert #7")]), {})


class Keruu(unittest.TestCase):
    def test_mittarit_ja_rajaus(self):
        prt = {"agentti-pohja": [pr(1), pr(2, merged=False), pr(3, tila="open"), pr(4, kirjoittaja=TONY), pr(5, ika=100)]}
        kom = {("r", 1): [{"user": {"login": "reviewer-bot"}}, {"user": {"login": TONY}}], ("i", 1): [{"user": {"login": TONY}}]}
        d = au.keraa(feikki(prt, kommentit=kom), 60, NYT)
        self.assertEqual(sorted(t["nro"] for t in d["prt"]), [1, 2, 3])
        self.assertFalse(d["vajaa"])
        m = au.mittarit(d["prt"], "agentti")["yojono"]
        self.assertEqual((m["mergattu"], m["suljettu"], m["auki"], m["loydokset"], m["tonyn"]), (1, 1, 1, 1, 2))

    def test_ci_punainen_ja_revert_lasketaan(self):
        prt = {"agentti-pohja": [pr(1), pr(2), pr(3, "Revert #1", kirjoittaja=TONY, ika=1)]}
        d = au.keraa(feikki(prt, ci={"m2": ajot("failure")}), 60, NYT)
        m = au.mittarit(d["prt"], "agentti")["yojono"]
        self.assertEqual((m["revertit"], m["ci_punainen"]), (1, 1))

    def test_budjetti_ja_valimuisti(self):
        prt = {"agentti-pohja": [pr(i) for i in range(1, 6)]}
        h = feikki(prt)
        vm = {}
        d = au.keraa(h, 60, NYT, vm, max_kutsuja=12)    # 5 kutsua / merged PR -> 2 PR:aa
        self.assertTrue(d["vajaa"])
        self.assertEqual(sum(1 for t in d["prt"] if t["luokka"]), 2)
        self.assertEqual(len(vm), 2)
        d2 = au.keraa(h, 60, NYT, vm, max_kutsuja=12)   # valimuisti: uudet 2 lisaa
        self.assertEqual(len(vm), 4)

    def test_repo_virhe_merkitsee_vajaaksi(self):
        d = au.keraa(feikki({}, puuttuva=("evalkit",)), 60, NYT)
        self.assertTrue(d["vajaa"])
        self.assertEqual(d["virheet"], ["evalkit"])


def t(luokka, tila="mergattu", ika=5, agentti="yojono", revert=None, ci="ok"):
    return {"repo": "r", "nro": 1, "agentti": agentti, "luokka": luokka, "tila": tila, "luotu": NYT - timedelta(days=ika + 1),
            "paatetty": NYT - timedelta(days=ika), "ci": ci, "ci_main": "tuntematon", "loydokset": 0, "tonyn": 0,
            "revertoitu": (NYT - timedelta(days=revert)) if revert is not None else None}


class Portaat(unittest.TestCase):
    def tila(self, prt, luokka="pieni-korjaus"):
        return [a for a in au.portaat(prt, NYT) if a["luokka"] == luokka][0]

    def test_kynnys_taynna_on_ehdokas(self):
        a = self.tila([t("pieni-korjaus", ika=60 - i) for i in range(40)])
        self.assertEqual((a["putki"], a["tila"]), (40, "ehdokas"))

    def test_alle_kynnyksen(self):
        self.assertEqual(self.tila([t("pieni-korjaus", ika=30 - i) for i in range(39)])["tila"], "ei viela")

    def test_revert_nollaa_putken(self):
        prt = [t("pieni-korjaus", ika=60 - i) for i in range(40)] + [t("pieni-korjaus", ika=3 + 20, revert=20)]
        a = self.tila(prt)
        self.assertEqual(a["putki"], 0)   # kaikki PR:t ovat revertin (20 vrk sitten) edella
        self.assertEqual(a["tila"], "ei viela")

    def test_hylkays_ja_punainen_ci_katkaisevat(self):
        prt = [t("pieni-korjaus", ika=50 - i) for i in range(10)] + [t("pieni-korjaus", "suljettu", ika=30)] + \
              [t("pieni-korjaus", ika=29 - i) for i in range(5)] + [t("pieni-korjaus", ika=20, ci="virhe")] + [t("pieni-korjaus", ika=19 - i) for i in range(3)]
        self.assertEqual(self.tila(prt)["putki"], 3)

    def test_rauhoitusaika(self):
        prt = [t("pieni-korjaus", "suljettu", ika=10)] + [t("pieni-korjaus", ika=9 - i % 9) for i in range(45)]
        self.assertEqual(self.tila(prt)["tila"], "ei viela")      # katko 10 vrk sitten: alle 14 vrk

    def test_suojattu_ja_suurempi_eivat_koskaan(self):
        prt = [t("suojattu", ika=90 - i) for i in range(100)] + [t("suurempi", ika=90 - i) for i in range(100)]
        self.assertEqual(self.tila(prt, "suojattu")["tila"], "ei koskaan")
        self.assertEqual(self.tila(prt, "suurempi")["tila"], "ei koskaan")

    def test_pudotus_nykyisesta_automergesta(self):
        prt = [t("testit", ika=40 - i) for i in range(25)] + [t("testit", ika=3, revert=1)]
        self.assertEqual(self.tila(prt, "testit")["tila"], "pudota")

    def test_ei_pudotusta_luokalle_jolla_ei_automergea(self):
        prt = [t("pieni-korjaus", "suljettu", ika=2)]
        self.assertEqual(self.tila(prt)["tila"], "ei viela")

    def test_agentit_erikseen_ja_luokaton_ohitetaan(self):
        a = au.portaat([t("testit", agentti="yojono"), t("testit", agentti="pilvi"), t(None)], NYT)
        self.assertEqual(sorted((x["agentti"], x["luokka"]) for x in a), [("pilvi", "testit"), ("yojono", "testit")])

    def test_kynnykset_suojattu_ei_numeroa(self):
        self.assertIsNone(au.KYNNYKSET["suojattu"])
        self.assertIsNone(au.KYNNYKSET["suurempi"])


class Raportti(unittest.TestCase):
    def test_tyhja(self):
        self.assertIn("data ei riita", au.muotoile({"prt": [], "vajaa": False, "virheet": [], "paivia": 60}, nyt=NYT))

    def test_raportti_ja_vajaa(self):
        d = au.keraa(feikki({"agentti-pohja": [pr(1)]}, puuttuva=("evalkit",)), 60, NYT)
        s = au.muotoile(d, {"yojono": (3, 1, 0.5)}, NYT)
        for osa in ("yojono", "dokumentaatio", "vajaa", "Autonomiaportaat", "yojono: 3 / 1 / 0.50", "evalkit"):
            self.assertIn(osa, s)

    def test_loki_vain_luku_ja_puuttuva(self):
        self.assertEqual(au.lokirivit("/ei/ole", 7), {})
        import sqlite3
        with tempfile.TemporaryDirectory() as hak:
            polku = os.path.join(hak, "l.db")
            c = sqlite3.connect(polku)
            c.execute("CREATE TABLE tapahtuma(aika REAL, agentti TEXT, tulos TEXT, kulu_usd REAL)")
            c.execute("INSERT INTO tapahtuma VALUES(?,?,?,?)", (NYT.timestamp(), "a", "virhe", 0.25))
            c.commit()
            c.close()
            self.assertEqual(au.lokirivit(polku, 7, NYT.timestamp()), {"a": (1, 1, 0.25)})

    def test_main_kirjoittaa_valimuistin_ja_tiedoston(self):
        with tempfile.TemporaryDirectory() as hak:
            vm, ulos = os.path.join(hak, "vm.json"), os.path.join(hak, "r.txt")
            self.assertEqual(au.main(["--valimuisti", vm, "--kirjoita", ulos, "60"], hae=feikki({"agentti-pohja": []})), 0)
            self.assertTrue(os.path.exists(ulos))
            self.assertEqual(json.load(open(vm, encoding="utf-8")), {})
        self.assertEqual(au.main(["abc"]), 2)


if __name__ == "__main__":
    unittest.main()
