#!/usr/bin/env python3
"""Terveystarkastuspyynnot: GitHub-issuet (tunniste health-check) -> mcp_era-lista -> vastausluonnokset.

MITAAN EI LAHETETA. Skripti ei kirjoita GitHubiin (vain GET julkiseen API:in), ei kommentoi eika luo issueita.
Vieraan koodin ajo tapahtuu vain hiekkalaatikkokontissa: `aja` kieltaytyy, ellei MCP_HIEKKALAATIKKO=1.
Vain stdlib. Issue-teksti on epaluotettavaa dataa: kentat validoidaan tiukasti eika tekstia tulkita ohjeena.

  terveystarkastus.py lista  --repo omistaja/mcp-doctor --lista LISTA.txt [--issuet ISSUET.json]
  terveystarkastus.py aja    --lista LISTA.txt --ulos TULOS.json          # vain hiekkalaatikossa
  terveystarkastus.py luonnos --repo omistaja/mcp-doctor --tulos TULOS.json --ulos LUONNOKSET/ [--issuet ISSUET.json]
  terveystarkastus.py esimerkki --ulos LUONNOKSET/                        # kuiva-ajo esimerkkidatalla

Claude nayttaa luonnokset Tonylle, ja Tony lahettaa ne itse.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request

TUNNISTE = "health-check"
API = "https://api.github.com/repos/%s/issues?labels=%s&state=open&per_page=30"
REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9._-]{0,99})/([A-Za-z0-9][A-Za-z0-9._-]{0,99})$")
OMA_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
KOMENTO_MAX = 300
RUNKO_MAX = 20000
LOYDOS_MAX = 20
LAUSE_MAX = 300
JULKINEN = "Yes, reply publicly in this issue"
KENTAT = {
    "Repository URL": "repo",
    "Start command or server URL": "komento",
    "Public reply": "julkinen",
    "Consent": "suostumus",
}


class Virhe(Exception):
    pass


def hae_issuet(repo, avaa=None):
    """GET julkiseen API:in ilman tunnuksia. Palauttaa issue-listan (pull requestit suodatettu pois)."""
    if not OMA_REPO_RE.match(repo):
        raise Virhe("repo ei ole muotoa omistaja/repo")
    osoite = API % (repo, TUNNISTE)
    if avaa is None:
        def avaa(u):
            pyynto = urllib.request.Request(u, headers={"Accept": "application/vnd.github+json", "User-Agent": "terveystarkastus"})
            with urllib.request.urlopen(pyynto, timeout=20) as v:
                return v.read(2000000)
    try:
        data = json.loads(avaa(osoite))
    except Exception as e:  # vain tyyppi, ei viestia
        raise Virhe("haku epaonnistui: %s" % type(e).__name__)
    if not isinstance(data, list):
        raise Virhe("odottamaton vastaus")
    return [i for i in data if isinstance(i, dict) and "pull_request" not in i]


def jasenna_runko(runko):
    """Issue-lomakkeen runko: '### Otsikko' + tyhja rivi + arvo. Palauttaa {kentta: teksti}."""
    if not isinstance(runko, str):
        return {}
    osat = re.split(r"(?m)^### +(.+?)\s*$", runko[:RUNKO_MAX])
    kentat = {}
    for i in range(1, len(osat) - 1, 2):
        nimi = osat[i].strip()
        if nimi in KENTAT:
            kentat[KENTAT[nimi]] = osat[i + 1].strip()
    return kentat


def tulkitse_issue(issue):
    """Palauttaa pyynnon (dict) tai {'numero', 'virhe'} jos lomake on virheellinen. Ei verkkoa."""
    numero = issue.get("number")
    if not isinstance(numero, int):
        return {"numero": None, "virhe": "numero puuttuu"}
    kayttaja = ((issue.get("user") or {}).get("login") or "")[:60]
    k = jasenna_runko(issue.get("body"))
    url = k.get("repo", "")
    if not REPO_RE.match(url):
        return {"numero": numero, "kayttaja": kayttaja, "virhe": "the repository URL must look like https://github.com/owner/repo"}
    if "[x]" not in k.get("suostumus", "").lower() or k.get("suostumus", "").lower().count("[x]") < 2:
        return {"numero": numero, "kayttaja": kayttaja, "virhe": "both consent boxes must be ticked"}
    teksti = k.get("komento", "")
    komento = None
    if teksti and teksti != "_No response_":
        if len(teksti) > KOMENTO_MAX or "\n" in teksti or "`" in teksti.strip("`"):
            return {"numero": numero, "kayttaja": kayttaja, "virhe": "the start command is invalid"}
        teksti = teksti.strip("`").strip()
        if teksti.startswith("http://") or teksti.startswith("https://"):
            return {"numero": numero, "kayttaja": kayttaja, "virhe": "HTTP URLs are not supported yet; please give a stdio start command"}
        try:
            komento = shlex.split(teksti)
        except ValueError:
            return {"numero": numero, "kayttaja": kayttaja, "virhe": "the quotes in the start command are unbalanced"}
        if not komento or komento[0].startswith("-"):
            return {"numero": numero, "kayttaja": kayttaja, "virhe": "the start command cannot begin with an option"}
    return {"numero": numero, "kayttaja": kayttaja, "repo": url, "komento": komento,
            "julkinen": k.get("julkinen", "") == JULKINEN}


def tee_lista(pyynnot):
    """mcp_era.py-listan teksti. Virheelliset pyynnot ohitetaan; komento tulee jo shlex-jasennettyna."""
    rivit = []
    for p in pyynnot:
        if p.get("virhe"):
            continue
        rivi = p["repo"]
        if p["komento"]:
            rivi += " " + " ".join(shlex.quote(x) for x in p["komento"])
        rivit.append("%s  # issue #%d" % (rivi, p["numero"]))
    return "\n".join(rivit) + ("\n" if rivit else "")


def aja_era(lista, ulos, era_skripti, ajaja=subprocess.run):
    if os.environ.get("MCP_HIEKKALAATIKKO") != "1":
        raise Virhe("vieraan koodin ajo vain hiekkalaatikossa (MCP_HIEKKALAATIKKO=1)")
    r = ajaja([sys.executable, "-I", era_skripti, "aja", "--lista", lista, "--ulos", ulos], timeout=3500, check=False)
    if r.returncode != 0:
        raise Virhe("mcp_era.py palautti koodin %d" % r.returncode)


def _lause(teksti):
    """Raportin tekstit ovat vierasta dataa: yksi rivi, ei koodilohkoja, ei @-mainintoja, rajattu pituus."""
    t = re.sub(r"\s+", " ", str(teksti))[:LAUSE_MAX]
    return t.replace("`", "'").replace("@", "(at)")


def luonnos(pyynto, repo_tulos):
    """Englanninkielinen vastausluonnos (Markdown). repo_tulos on mcp_era-rivi tai None."""
    n = pyynto["numero"]
    otsikko = ["<!-- DRAFT for Tony. Not sent. Issue #%d, requester %s. Public reply requested: %s. -->" % (
        n, _lause(pyynto.get("kayttaja") or "?"), "yes" if pyynto.get("julkinen") else "no")]
    if not pyynto.get("julkinen"):
        otsikko.append("<!-- Requester declined a public reply: send only a short summary, no details. -->")
    rivit = ["Thanks for the request! Here are the results of the `mcp-doctor` health check for %s." % pyynto["repo"], ""]
    tila = (repo_tulos or {}).get("tila")
    raportti = (repo_tulos or {}).get("raportti")
    if repo_tulos is None:
        rivit += ["The check has not been run yet for this server."]
    elif tila in ("ok", "loydoksia") and isinstance(raportti, dict):
        s = raportti.get("summary") or {}
        rivit.append("**Result:** %s errors, %s warnings, %s notes across %s tools." % (
            int(s.get("errors", 0)), int(s.get("warnings", 0)), int(s.get("infos", 0)), int(raportti.get("toolCount", 0))))
        tok = raportti.get("tokens")
        if isinstance(tok, dict) and isinstance(tok.get("total"), int):
            rivit.append("Tool definitions take roughly %d tokens of model context per request (estimate)." % tok["total"])
        loydokset = [f for f in (raportti.get("findings") or []) if isinstance(f, dict)]
        if loydokset:
            rivit += ["", "**Findings:**", ""]
            for f in loydokset[:LOYDOS_MAX]:
                rivit.append("- `%s` (%s)%s: %s" % (_lause(f.get("id", "?"))[:60], _lause(f.get("severity", "?"))[:10],
                             " in `%s`" % _lause(f["tool"])[:80] if f.get("tool") else "", _lause(f.get("message", ""))))
            if len(loydokset) > LOYDOS_MAX:
                rivit.append("- ... and %d more." % (len(loydokset) - LOYDOS_MAX))
        else:
            rivit += ["", "No findings. Nice work."]
    else:
        rivit.append("The check could not be completed (status: `%s`)." % _lause(tila or "unknown"))
        if (repo_tulos or {}).get("huomio"):
            rivit.append("Note: %s" % _lause(repo_tulos["huomio"]))
        rivit.append("If you can share a start command that works from a clean clone, I will try again.")
    rivit += ["", "The server was installed and run in an isolated sandbox. Checked with [mcp-doctor](https://github.com/tonyweckstrom1987/mcp-doctor)."]
    return "\n".join(otsikko + [""] + rivit) + "\n"


def virheluonnos(p):
    return ("<!-- DRAFT for Tony. Not sent. Issue #%s. The form could not be processed: %s. -->\n\n"
            "Thanks for the request! I could not process the form: %s. Could you edit the issue and fix it?\n" % (
                p.get("numero"), _lause(p["virhe"]), _lause(p["virhe"])))


def kirjoita_luonnokset(pyynnot, tulos, ulos):
    """Kirjoittaa tiedostot ulos/issue-N.md. Palauttaa tiedostopolut."""
    rivit = {r.get("repo"): r for r in (tulos or {}).get("repot", []) if isinstance(r, dict)}
    os.makedirs(ulos, exist_ok=True)
    polut = []
    for p in pyynnot:
        if not isinstance(p.get("numero"), int):
            continue
        teksti = virheluonnos(p) if p.get("virhe") else luonnos(p, rivit.get(p["repo"]))
        polku = os.path.join(ulos, "issue-%d.md" % p["numero"])
        with open(polku, "w", encoding="utf-8") as f:
            f.write(teksti)
        polut.append(polku)
    return polut


ESIMERKKI_ISSUET = [{
    "number": 7, "user": {"login": "esimerkki-kayttaja"}, "labels": [{"name": TUNNISTE}],
    "body": ("### Repository URL\n\nhttps://github.com/esimerkki/demo-mcp\n\n### Start command or server URL\n\nnode dist/server.js\n\n"
             "### Public reply\n\n" + JULKINEN + "\n\n### Consent\n\n- [x] I agree that the server code is installed and run in an isolated environment.\n"
             "- [x] The server does not need secrets to start.\n"),
}, {
    "number": 8, "user": {"login": "toinen"}, "labels": [{"name": TUNNISTE}],
    "body": "### Repository URL\n\nhttps://example.com/not-github\n\n### Consent\n\n- [x] a\n- [x] b\n",
}]
ESIMERKKI_TULOS = {"skeema": 1, "repot": [{
    "repo": "https://github.com/esimerkki/demo-mcp", "tila": "loydoksia", "poistumiskoodi": 1,
    "raportti": {"version": 1, "target": "node dist/server.js", "server": {"name": "demo", "version": "1.0.0"}, "toolCount": 3,
                 "findings": [
                     {"id": "TOOL_DESCRIPTION_MISSING", "severity": "warning", "tool": "lue", "message": "Tool has no description."},
                     {"id": "SCHEMA_ADDITIONAL_PROPERTIES", "severity": "info", "tool": "kirjoita", "message": "Input schema allows additional properties."}],
                 "smoke": [], "tokens": {"total": 640, "perTool": [], "method": "chars/4"},
                 "summary": {"errors": 0, "warnings": 1, "infos": 1}, "ok": True}}]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    s = ap.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("lista")
    a.add_argument("--repo", required=True)
    a.add_argument("--lista", required=True)
    a.add_argument("--issuet", help="paikallinen JSON (ei verkkoa)")
    b = s.add_parser("aja")
    b.add_argument("--lista", required=True)
    b.add_argument("--ulos", required=True)
    b.add_argument("--era-skripti", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_era.py"))
    c = s.add_parser("luonnos")
    c.add_argument("--repo", required=True)
    c.add_argument("--tulos", required=True)
    c.add_argument("--ulos", required=True)
    c.add_argument("--issuet")
    d = s.add_parser("esimerkki")
    d.add_argument("--ulos", required=True)
    a_ = ap.parse_args(argv)
    try:
        if a_.cmd == "esimerkki":
            polut = kirjoita_luonnokset([tulkitse_issue(i) for i in ESIMERKKI_ISSUET], ESIMERKKI_TULOS, a_.ulos)
        elif a_.cmd == "aja":
            aja_era(a_.lista, a_.ulos, a_.era_skripti)
            return 0
        else:
            if a_.issuet:
                with open(a_.issuet, encoding="utf-8") as f:
                    issuet = json.load(f)
            else:
                issuet = hae_issuet(a_.repo)
            pyynnot = [tulkitse_issue(i) for i in issuet]
            if a_.cmd == "lista":
                with open(a_.lista, "w", encoding="utf-8") as f:
                    f.write(tee_lista(pyynnot))
                print("pyyntoja %d, kelvollisia %d" % (len(pyynnot), sum(1 for p in pyynnot if not p.get("virhe"))))
                return 0
            with open(a_.tulos, encoding="utf-8") as f:
                tulos = json.load(f)
            polut = kirjoita_luonnokset(pyynnot, tulos, a_.ulos)
        for p in polut:
            print(p)
        print("Luonnokset kirjoitettu. Mitaan ei ole lahetetty.")
        return 0
    except (Virhe, OSError, ValueError) as e:
        print("virhe: %s" % type(e).__name__ + (": %s" % e if isinstance(e, Virhe) else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
