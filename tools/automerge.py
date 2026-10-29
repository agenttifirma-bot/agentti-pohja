"""Automaattinen yhdistaminen pienille, turvallisille muutoksille.

Ajetaan GitHub Actionsissa (pull_request_target, luotettu koodi paahaarasta; PR:n omaa koodia
ei koskaan ladata eika suoriteta). Paatos tehdaan vain PR:n metatiedoista ja tiedostolistasta.

Sallittu vain kun KAIKKI ehdot tayttyvat:
  - PR ei ole luonnos eika forkista, eika siina ole tunnistetta 'ei-automerge'
    (ainoa poikeus: botin forkki, ks. alla)
  - enintaan 20 tiedostoa ja 200 muutettua rivia (saman repon PR, jossa on vain test/*.py ja dokumentteja: 800 rivia)
  - tiedostot vain lisatty tai muokattu (ei poistoa, ei uudelleennimeamista)
  - jokainen tiedosto on dokumentti (*.md, docs/*.md) tai testi (test/*.py)
  - mikaan tiedosto ei ole suojatulla polulla (.github/, tools/, isanta/, systemd/, config, rajat,
    avain-/tunnistetiedostot)
Botin poikkeus (README 21.10.2026; testit ja ominaisuus 24.10.2026: Tony poisti mergauksen itseltaan): PR voi olla botin omasta forkista vain, jos tekija on BOTTI, head-repo on
BOTTI/<sama repo>, base on main, haaran nimi on yo/(readme|testit|ominaisuus)-<...>. readme: vain *.md. testit/ominaisuus: koodipaatteet (py/js/ts/md), enintaan 400 rivia, ei suojattuja polkuja (yojono/, portti, riippuvuus- ja asetustiedostot).
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
BOTTI = "agenttifirma-bot"
BOTIN_HAARA = re.compile(r"^yo/(readme|testit|ominaisuus)-[a-z0-9][a-z0-9._-]{0,59}$")
MAX_RIVEJA_KOODI = 400
# Saman repon PR, jossa on vain testitiedostoja (test/*.py) ja dokumentteja: testit ovat pitkia, mutaatiotestauksen aukkojen sulkeminen vaatii satoja rivia.
MAX_RIVEJA_TESTIT = 800
TESTIPOLKU = re.compile(r"^test/[A-Za-z0-9_./-]+\.py\Z")
# Laajennus 28.10.2026 (Tony hyvaksyi): yojonon testitiedostot (vain lisays/muokkaus; nimessa ei salaisuuksiin viittaavaa sanaa)
# (korjaus 29.10.: vain UUSI tiedosto, koska olemassa olevan testin muokkaus voisi heikentaa kulukattoa vartioivaa testia; `\\Z` ettei rivinvaihto paase lapi)
# ja CHANGELOG-fragmenttien poisto (tools/changelog_kokoa.py poistaa ne koostaessaan). Muu yojono/ pysyy suojattuna.
YOJONO_TESTI = re.compile(r"^yojono/test_(?!.*(secret|token|credential|password|key))[a-z0-9_]+\.py\Z", re.IGNORECASE)
FRAGMENTTI = re.compile(r"^docs/muutokset/[A-Za-z0-9_.-]+\.md\Z")
# Botin koodimuutoksille (testit, ominaisuus): vain nama paatteet; riippuvuus- ja asetustiedostot jaavat ihmiselle.
KOODIPAATTEET = (".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".md")

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
    re.compile(r"^yojono/"),
    re.compile(r"^action\.ya?ml$"),
    re.compile(r"^dist/"),
    re.compile(r"^agentti/(portti|ehdotukset|maaritys)"),
    re.compile(r"(^|/)(package(-lock)?\.json|requirements[^/]*\.txt|pyproject\.toml|setup\.(py|cfg)|poetry\.lock|yarn\.lock|pnpm-lock\.yaml|Dockerfile)$"),
    re.compile(r"secret|token|credential|password|key", re.IGNORECASE),
    re.compile(r"(^|/)\.\.(/|$)"),
]


def polku_ok(polku):
    """(ok, syy). Suojattu polku voittaa aina sallitun."""
    if not polku:
        return False, "tyhja polku"
    if YOJONO_TESTI.match(polku):
        return True, ""
    for s in SUOJATUT:
        if s.search(polku):
            return False, "suojattu polku: " + polku
    for s in SALLITUT:
        if s.match(polku):
            return True, ""
    return False, "ei sallittu tyyppi: " + polku


def botin_forkki_syyt(pr):
    """Botin forkista tuleva PR kelpaa vain tarkoin rajatuin ehdoin; palauttaa syyt (tyhja = ok)."""
    base = pr.get("base_repo") or ""
    nimi = base.split("/", 1)[1] if "/" in base else ""
    syyt = []
    if (pr.get("author") or "").lower() != BOTTI:
        syyt.append("PR ei ole saman repon haarasta")
    elif not nimi or (pr.get("head_repo") or "").lower() != f"{BOTTI}/{nimi}".lower():
        syyt.append("forkki ei ole botin oma fork samasta reposta")
    if pr.get("base_ref") not in ("main", "master"):
        syyt.append("base ei ole main eika master")
    if not BOTIN_HAARA.match(pr.get("head_ref") or ""):
        syyt.append("botin haaran nimi ei ole yo/(readme|testit|ominaisuus)-*")
    return syyt


def botin_koodi_ok(polku):
    """Botin forkista (testit/ominaisuus) sallittu tiedosto: ei suojattu, turvallinen nimi, sallittu paate."""
    if not re.match(r"^[A-Za-z0-9_./-]+$", polku or ""):
        return False, "ei sallittu polku: " + str(polku)
    for s_ in SUOJATUT:
        if s_.search(polku):
            return False, "suojattu polku: " + polku
    if not polku.endswith(KOODIPAATTEET):
        return False, "ei sallittu paate: " + polku
    return True, ""


def _testi(nimi):
    return bool(TESTIPOLKU.match(nimi) or YOJONO_TESTI.match(nimi))


def _vain_testeja_ja_dokumentteja(tiedostot):
    """Vahintaan yksi test/*.py ja kaikki muut tiedostot dokumentteja (SALLITUT[:-1]); nimet molemmista (uudelleennimeaminen) tarkistetaan."""
    nimet = [n for t in tiedostot for n in (t.get("filename"), t.get("previous_filename")) if n is not None]
    return bool(nimet) and any(_testi(n) for n in nimet) and all(_testi(n) or any(r.match(n) for r in SALLITUT[:2]) for n in nimet)


def arvioi(pr, tiedostot):
    """Palauttaa (sallittu, syyt). pr: dict (draft, head_repo, base_repo, labels, author, head_ref, base_ref), tiedostot: lista dict."""
    syyt = []
    forkki = pr.get("head_repo") != pr.get("base_repo")
    if pr.get("draft"):
        syyt.append("luonnos")
    if forkki:
        fs = botin_forkki_syyt(pr)
        syyt.extend(fs)
        if not fs:
            readme = (pr.get("head_ref") or "").startswith("yo/readme-")
            for t in tiedostot:
                if readme and not str(t.get("filename", "")).endswith(".md"):
                    syyt.append("readme-haarasta vain .md-tiedostot: " + str(t.get("filename")))
                elif not readme:
                    for nimi in (t.get("filename"), t.get("previous_filename")):
                        if nimi is not None:
                            ok, syy = botin_koodi_ok(nimi)
                            if not ok:
                                syyt.append(syy)
    if OPT_OUT in (pr.get("labels") or []):
        syyt.append("tunniste " + OPT_OUT)
    if not tiedostot:
        syyt.append("ei tiedostoja")
    if len(tiedostot) > MAX_TIEDOSTOA:
        syyt.append("liian monta tiedostoa (%d)" % len(tiedostot))
    rivit = sum(int(t.get("changes", 0)) for t in tiedostot)
    raja = MAX_RIVEJA_KOODI if (forkki and not (pr.get("head_ref") or "").startswith("yo/readme-")) else MAX_RIVEJA
    if not forkki and _vain_testeja_ja_dokumentteja(tiedostot):
        raja = MAX_RIVEJA_TESTIT
    if rivit > raja:
        syyt.append("liian suuri muutos (%d rivia)" % rivit)
    for t in tiedostot:
        poisto_ok = (not forkki and t.get("status") == "removed" and bool(FRAGMENTTI.match(str(t.get("filename")))))
        if t.get("status") not in ("added", "modified") and not poisto_ok:
            syyt.append("tiedoston tila %s: %s" % (t.get("status"), t.get("filename")))
        if any(n is not None and YOJONO_TESTI.match(n) for n in (t.get("filename"), t.get("previous_filename"))) and (
                t.get("status") != "added" or t.get("previous_filename") is not None):
            syyt.append("yojono-testia ei muokata automaattisesti (vain uusi tiedosto): " + str(t.get("filename")))
        for nimi in (t.get("filename"), t.get("previous_filename")):
            if nimi is None:
                continue
            if forkki and not (pr.get("head_ref") or "").startswith("yo/readme-"):
                ok, syy = botin_koodi_ok(nimi)
            else:
                ok, syy = polku_ok(nimi)
            if not ok and syy not in syyt:
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
        "author": (d.get("user") or {}).get("login"),
        "head_ref": (d.get("head") or {}).get("ref"),
        "base_ref": (d.get("base") or {}).get("ref"),
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
