#!/usr/bin/env python3
"""Kertoo, paljonko kayttoonotettu kopio on jaljessa GitHubin oletushaaraa (yhdistetty ei ole sama kuin kaytossa).

Peruste: tulos 2026-11-05-34. PR #214 oli mainissa, mutta /opt/agentti-pohja ei ollut paivittynyt, joten
PR-avaajan virheen syy ei tullut lokiin.

Verkko: tyokalu tekee GitHubin rajapintaan (api.github.com) lukupyynnon (compare) ja tarvittaessa toisen (repon
olemassaolo, vain 404:n syyn erottamiseen). Jos vain luku -tunnus on olemassa (agentti/github_luku.py, oletuksena
/etc/agentscope/github-luku.token), pyynnot kayttavat sita: raja on silloin 5000 pyyntoa/h eika 60. Tunnusta ei
tulosteta. Jos GitHub hylkaa tunnuksen (401), pyynto toistetaan kerran ilman tunnusta. Muuta tyokalu ei tee: ei fetchia,
ei pullia, ei kirjoituksia. Ilman tunnusta yksityinen repo nakyy 404:na.
Git: jos paikallinen kopio kuuluu eri kayttajalle ("dubious ownership"), luku toistetaan kerran valilla
`git -c safe.directory=<tama polku>`; poikkeus koskee vain sita polkua eika kirjoita mitaan gitin asetuksiin.

Kaytto: tools/kayttoonotto_ero.py [--hakemisto /opt/agentti-pohja] [--repo agentti-pohja] [--haara main]
Poistumiskoodi: 0 ajan tasalla, 1 jaljessa, 2 tilaa ei saatu selville.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from agentti import github_luku
except ImportError:   # tyokalu ajettu suoraan polusta tools/...: lisataan repon juuri polulle
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from agentti import github_luku
    except ImportError:
        github_luku = None

API = "https://api.github.com"
OMISTAJA = "tonyweckstrom1987"
# Vain GitHubin yhdistamisotsikot: "Merge pull request #N from ..." ja squash-yhdistamisen paate "Otsikko (#N)".
# Muut #-numerot otsikossa tai rungossa (esim. "viittaa #1") eivat ole PR-numeroita.
PR_RE = re.compile(r"^Merge pull request #(\d+) from |\s\(#(\d+)\)$")
AIKARAJA_S = 20


class EroVirhe(Exception):
    """`lyhyt` on lyhyt, turvallinen syy (ei poikkeuksen tekstia) aamukoosteen riville."""
    def __init__(self, viesti, lyhyt="tuntematon syy"):
        super().__init__(viesti)
        self.lyhyt = lyhyt


def _pyynto(url, tunnuksella=True):
    otsakkeet = {"Accept": "application/vnd.github+json", "User-Agent": "kayttoonotto-ero"}
    if tunnuksella and github_luku is not None:
        return github_luku.pyynto(url, "kayttoonotto-ero")
    return urllib.request.Request(url, headers=otsakkeet)


def _avaa_tunnuksella(url, avaa):
    """Avaa osoitteen tunnuksella (jos on); 401 -> yksi toisto ilman tunnusta. Palauttaa vastauksen (with-lauseelle)."""
    try:
        return avaa(_pyynto(url), timeout=AIKARAJA_S)
    except urllib.error.HTTPError as e:
        if e.code == 401 and github_luku is not None and github_luku.lue_tunnus():
            return avaa(_pyynto(url, tunnuksella=False), timeout=AIKARAJA_S)
        raise


def paikallinen_commit(hakemisto, suorita=subprocess.run):
    def aja(komento):
        try:
            return suorita(komento, capture_output=True, text=True, check=False)
        except OSError as e:
            raise EroVirhe("gitia ei voitu ajaa: " + type(e).__name__, "git ei ajettavissa")
    r = aja(["git", "-C", hakemisto, "rev-parse", "HEAD"])
    if r.returncode != 0 and "dubious ownership" in (r.stderr or ""):
        # Kopio kuuluu toiselle kayttajalle (esim. root): poikkeus vain tallle polulle, vain taman kutsun ajaksi.
        r = aja(["git", "-c", "safe.directory=" + os.path.realpath(hakemisto), "-C", hakemisto, "rev-parse", "HEAD"])
    if r.returncode != 0:
        omistaja = "dubious ownership" in (r.stderr or "")
        raise EroVirhe("%s ei ole luettava git-kopio (safe.directory?): %s" % (hakemisto, (r.stderr or "").strip()[:200]),
                       "git: kopion omistaja ei tasmaa (safe.directory ei auttanut)" if omistaja else "git: kopio ei ole luettava")
    return r.stdout.strip()


def hae_vertailu(repo, commit, haara, avaa=urllib.request.urlopen):
    url = "%s/repos/%s/%s/compare/%s...%s" % (API, OMISTAJA, repo, commit, haara)
    try:
        with _avaa_tunnuksella(url, avaa) as v:
            return json.loads(v.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise EroVirhe(selita_404(repo, commit, avaa), "GitHub 404 (commit, yksityinen repo tai vaara repo)")
        raise EroVirhe("GitHub HTTP %s" % e.code, "GitHub HTTP %s" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise EroVirhe("GitHub-haku epaonnistui: " + type(e).__name__, "GitHub-yhteys: " + type(e).__name__)


def repo_nakyy(repo, avaa=urllib.request.urlopen):
    """True/False: repo nakyy pyynnolle (tunnuksella, jos sellainen on); None: ei voitu selvittaa."""
    try:
        with _avaa_tunnuksella("%s/repos/%s/%s" % (API, OMISTAJA, repo), avaa):
            return True
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def selita_404(repo, commit, avaa=urllib.request.urlopen):
    """404 voi tarkoittaa kolmea asiaa: erotellaan ne."""
    nakyy = repo_nakyy(repo, avaa=avaa)
    if nakyy is True:
        return "commit %s ei loydy GitHubista: kopiossa voi olla omia committeja tai haara on eri" % commit[:12]
    if nakyy is False:
        return ("GitHub vastasi 404 myos repolle %s/%s: repo on yksityinen (pyynto ei nae sita; tunnus puuttuu tai ei riita) "
                "tai --repo on vaarin" % (OMISTAJA, repo))
    return "GitHub vastasi 404, eika repon nakyvyytta saatu selville: syy voi olla commit, yksityinen repo tai vaara --repo"


def tiivista(vertailu):
    """Palauttaa (jaljessa, omia_committeja, PR-numerot vanhimmasta uusimpaan). PR:t vain vertailun palauttamista commiteista."""
    pr = []
    for c in vertailu.get("commits") or []:
        otsikko = ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0]
        for m in PR_RE.finditer(otsikko):
            nro = int(m.group(1) or m.group(2))
            if nro not in pr:
                pr.append(nro)
    return int(vertailu.get("ahead_by") or 0), int(vertailu.get("behind_by") or 0), pr


def raportti(hakemisto, repo, haara, commit, jaljessa, omia, pr):
    if jaljessa == 0 and omia == 0:
        return "%s: ajan tasalla %s:n kanssa (%s)" % (hakemisto, haara, commit[:7])
    osat = ["%s: %d committia jaljessa %s/%s:sta (kaytossa %s)" % (hakemisto, jaljessa, repo, haara, commit[:7])]
    if omia:
        osat.append("%d committia, joita GitHubissa ei ole" % omia)
    if pr:
        osat.append("PR:t: " + ", ".join("#%d" % n for n in pr))
    return "; ".join(osat)


def main(argv=None, avaa=urllib.request.urlopen, suorita=subprocess.run, tuloste=sys.stdout):
    p = argparse.ArgumentParser(description="Paljonko kayttoonotto on jaljessa GitHubia")
    p.add_argument("--hakemisto", default="/opt/agentti-pohja")
    p.add_argument("--repo", default="agentti-pohja")
    p.add_argument("--haara", default="main")
    a = p.parse_args(argv)
    try:
        commit = paikallinen_commit(a.hakemisto, suorita=suorita)
        jaljessa, omia, pr = tiivista(hae_vertailu(a.repo, commit, a.haara, avaa=avaa))
    except EroVirhe as e:
        print("%s: tila ei selvinnyt: %s" % (a.hakemisto, e), file=tuloste)
        return 2
    print(raportti(a.hakemisto, a.repo, a.haara, commit, jaljessa, omia, pr), file=tuloste)
    return 0 if jaljessa == 0 and omia == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
