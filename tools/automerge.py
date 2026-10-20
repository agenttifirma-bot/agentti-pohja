"""Automaattinen yhdistaminen pienille, turvallisille muutoksille.

Ajetaan GitHub Actionsissa (pull_request_target, luotettu koodi paahaarasta; PR:n omaa koodia
ei koskaan ladata eika suoriteta). Paatos tehdaan vain PR:n metatiedoista ja tiedostolistasta.

Sallittu vain kun KAIKKI ehdot tayttyvat:
  - PR ei ole luonnos eika forkista, eika siina ole tunnistetta 'ei-automerge'
  - enintaan 20 tiedostoa ja 200 muutettua rivia
  - tiedostot vain lisatty tai muokattu (ei poistoa, ei uudelleennimeamista)
  - jokainen tiedosto on dokumentti (*.md, docs/*.md) tai testi (test/*.py)
  - mikaan tiedosto ei ole suojatulla polulla (.github/, tools/, isanta/, systemd/, config, rajat,
    avain-/tunnistetiedostot)
Silloin kytketaan GitHubin auto-merge (squash): yhdistyy vasta kun pakolliset tarkistukset ovat lapi.
Jos PR ei (enaa) kelpaa, auto-merge poistetaan (esim. kun kayttaja pushaa uuden commitin).
"""
import json
import os
import re
import subprocess
import sys

MAX_TIEDOSTOA = 20
MAX_RIVEJA = 200
OPT_OUT = "ei-automerge"

SALLITUT = [
    re.compile(r"^[A-Za-z0-9_.-]+\.md$"),
    re.compile(r"^docs/[A-Za-z0-9_./-]+\.md$"),
    re.compile(r"^test/[A-Za-z0-9_./-]+\.py$"),
]
SUOJATUT = [
    re.compile(r"^\.github/"),
    re.compile(r"^tools/"),
    re.compile(r"^isanta/"),
    re.compile(r"(^|/)systemd/"),
    re.compile(r"^agentti/(config|rajat)\.py$"),
    re.compile(r"(^|/)\.env"),
    re.compile(r"secret|token|credential|password|key", re.IGNORECASE),
    re.compile(r"(^|/)\.\.(/|$)"),
]


def polku_ok(polku):
    """(ok, syy). Suojattu polku voittaa aina sallitun."""
    if not polku:
        return False, "tyhja polku"
    for s in SUOJATUT:
        if s.search(polku):
            return False, "suojattu polku: " + polku
    for s in SALLITUT:
        if s.match(polku):
            return True, ""
    return False, "ei sallittu tyyppi: " + polku


def arvioi(pr, tiedostot):
    """Palauttaa (sallittu, syyt). pr: dict (draft, head_repo, base_repo, labels), tiedostot: lista dict."""
    syyt = []
    if pr.get("draft"):
        syyt.append("luonnos")
    if pr.get("head_repo") != pr.get("base_repo"):
        syyt.append("PR ei ole saman repon haarasta")
    if OPT_OUT in (pr.get("labels") or []):
        syyt.append("tunniste " + OPT_OUT)
    if not tiedostot:
        syyt.append("ei tiedostoja")
    if len(tiedostot) > MAX_TIEDOSTOA:
        syyt.append("liian monta tiedostoa (%d)" % len(tiedostot))
    rivit = sum(int(t.get("changes", 0)) for t in tiedostot)
    if rivit > MAX_RIVEJA:
        syyt.append("liian suuri muutos (%d rivia)" % rivit)
    for t in tiedostot:
        if t.get("status") not in ("added", "modified"):
            syyt.append("tiedoston tila %s: %s" % (t.get("status"), t.get("filename")))
        for nimi in (t.get("filename"), t.get("previous_filename")):
            if nimi is None:
                continue
            ok, syy = polku_ok(nimi)
            if not ok:
                syyt.append(syy)
    return (not syyt), syyt


def _gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)


def hae_pr(repo, numero):
    r = _gh("api", "repos/%s/pulls/%s" % (repo, numero))
    if r.returncode != 0:
        raise RuntimeError("PR:n haku epaonnistui: " + r.stderr.strip()[-200:])
    d = json.loads(r.stdout)
    return {
        "draft": bool(d.get("draft")),
        "head_repo": ((d.get("head") or {}).get("repo") or {}).get("full_name"),
        "base_repo": ((d.get("base") or {}).get("repo") or {}).get("full_name"),
        "labels": [l.get("name") for l in d.get("labels", [])],
    }


def hae_tiedostot(repo, numero):
    r = _gh("api", "--paginate", "repos/%s/pulls/%s/files?per_page=100" % (repo, numero), "--jq", ".[]")
    if r.returncode != 0:
        raise RuntimeError("tiedostojen haku epaonnistui: " + r.stderr.strip()[-200:])
    return [json.loads(rivi) for rivi in r.stdout.splitlines() if rivi.strip()]


def yhteenveto(teksti):
    polku = os.environ.get("GITHUB_STEP_SUMMARY")
    print(teksti)
    if polku:
        try:
            with open(polku, "a") as f:
                f.write(teksti + "\n")
        except OSError:
            pass


def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    numero = os.environ.get("PR_NUMBER", "")
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo) or not numero.isdigit():
        print("virheellinen GITHUB_REPOSITORY tai PR_NUMBER")
        return 2
    try:
        sallittu, syyt = arvioi(hae_pr(repo, numero), hae_tiedostot(repo, numero))
    except (RuntimeError, ValueError) as e:
        yhteenveto("Automerge: arviointi epaonnistui (%s), ei tehda mitaan" % e)
        return 1
    if sallittu:
        r = _gh("pr", "merge", numero, "--auto", "--squash", "--repo", repo)
        if r.returncode != 0:
            yhteenveto("Automerge: kytkenta epaonnistui: " + r.stderr.strip()[-200:])
            return 1
        yhteenveto("Automerge: PR #%s kelpaa (vain dokumentteja/testeja). Yhdistyy kun tarkistukset ovat lapi." % numero)
        return 0
    _gh("pr", "merge", numero, "--disable-auto", "--repo", repo)
    yhteenveto("Automerge: PR #%s ei kelpaa automaattiseen yhdistamiseen: %s. Auto-merge poistettu." % (numero, "; ".join(syyt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
