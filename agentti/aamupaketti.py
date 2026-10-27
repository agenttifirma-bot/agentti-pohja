"""Aamupaketti: yhteenveto avoimista PR:ista (vain luku, julkinen GitHub-API, ei tunnuksia).

Jakaa PR:t kolmeen ryhmaan: Tonyn mergattavat (muuttavat suojattuja polkuja), automerge hoitaa (vain sallittuja polkuja)
ja muut (luonnos, CI kesken tai punainen). Kaytto: python3 -m agentti.aamupaketti [--laheta]
--laheta kayttaa ymparistoa YOJONO_TELEGRAM_TOKEN ja YOJONO_TELEGRAM_CHAT (kuten yojonon yhteenveto)."""
import json
import os
import sys
import urllib.request

from . import telegram
from .pr_kutsu import REPOT

OMISTAJA = "tonyweckstrom1987"
MAX_PR_REPOA_KOHDEN = 15
MAX_TIEDOSTOJA_HAKUUN = 100
OTSIKKO_MAX = 70


def _suojattu(polku):
    """True jos polku kuuluu automergen suojalistalle tai ei ole sallittu (Tony katselmoi)."""
    from tools import automerge
    ok, _ = automerge.polku_ok(polku)
    return not ok


def _oletushaku(url):
    pyynto = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agenttifirma-aamupaketti"})
    with urllib.request.urlopen(pyynto, timeout=20) as v:
        return json.loads(v.read().decode("utf-8"))


def _ci(hae, repo, sha):
    """'vihrea', 'punainen' tai 'kesken' check-runeista."""
    try:
        runit = hae("https://api.github.com/repos/%s/%s/commits/%s/check-runs?per_page=50" % (OMISTAJA, repo, sha)).get("check_runs", [])
    except Exception:
        return "kesken"
    if not runit or any(r.get("status") != "completed" for r in runit):
        return "kesken"
    huonot = [r for r in runit if r.get("conclusion") not in ("success", "skipped", "neutral")]
    return "punainen" if huonot else "vihrea"


def keraa(hae=None):
    """Palauttaa {'tony': [...], 'automerge': [...], 'muut': [...]}, kukin rivi dict (repo, numero, otsikko, url, ci, syy)."""
    hae = hae or _oletushaku
    ryhmat = {"tony": [], "automerge": [], "muut": []}
    for repo in REPOT:
        try:
            prt = hae("https://api.github.com/repos/%s/%s/pulls?state=open&per_page=%d" % (OMISTAJA, repo, MAX_PR_REPOA_KOHDEN))
        except Exception:
            continue
        for p in prt[:MAX_PR_REPOA_KOHDEN]:
            nro = p.get("number")
            rivi = {"repo": repo, "numero": nro, "otsikko": " ".join(str(p.get("title", "")).split())[:OTSIKKO_MAX],
                    "url": p.get("html_url") or "https://github.com/%s/%s/pull/%s" % (OMISTAJA, repo, nro), "ci": "", "syy": ""}
            if p.get("draft"):
                rivi["syy"] = "luonnos"
                ryhmat["muut"].append(rivi)
                continue
            rivi["ci"] = _ci(hae, repo, (p.get("head") or {}).get("sha", ""))
            try:
                tiedostot = hae("https://api.github.com/repos/%s/%s/pulls/%s/files?per_page=%d" % (OMISTAJA, repo, nro, MAX_TIEDOSTOJA_HAKUUN))
            except Exception:
                tiedostot = None
            if tiedostot is None:
                rivi["syy"] = "tiedostoja ei saatu"
                ryhmat["muut"].append(rivi)
                continue
            if rivi["ci"] == "punainen":
                rivi["syy"] = "CI punainen"
                ryhmat["muut"].append(rivi)
                continue
            suojattu = any(_suojattu(n) for t in tiedostot for n in (t.get("filename"), t.get("previous_filename")) if n)
            if suojattu:
                ryhmat["tony"].append(rivi)
            elif rivi["ci"] == "vihrea":
                ryhmat["automerge"].append(rivi)
            else:
                rivi["syy"] = "CI kesken"
                ryhmat["muut"].append(rivi)
    return ryhmat


def _rivi(r):
    lisa = " [%s]" % r["syy"] if r["syy"] else (" (CI %s)" % r["ci"] if r["ci"] else "")
    return "- %s #%s %s%s\n  %s" % (r["repo"], r["numero"], r["otsikko"], lisa, r["url"])


def muotoile(ryhmat):
    osat = ["Aamupaketti: avoimet PR:t"]
    for avain, otsikko in (("tony", "Sinun mergattavat (suojatut polut)"), ("automerge", "Automerge hoitaa (CI vihrea)"), ("muut", "Muut (luonnos, CI kesken tai punainen)")):
        rivit = ryhmat.get(avain) or []
        osat.append("\n%s: %d" % (otsikko, len(rivit)))
        osat.extend(_rivi(r) for r in rivit)
    if not any(ryhmat.values()):
        osat.append("\nEi avoimia PR:ita.")
    return "\n".join(osat)


def main(argv=None, hae=None, env=None):
    a = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    if any(x not in ("--laheta",) for x in a):
        print("kaytto: python3 -m agentti.aamupaketti [--laheta]", file=sys.stderr)
        return 2
    teksti = muotoile(keraa(hae))
    print(teksti)
    if "--laheta" in a:
        ok = telegram.laheta(teksti, {"TELEGRAM_BOT_TOKEN": env.get("YOJONO_TELEGRAM_TOKEN"), "TELEGRAM_CHAT_ID": env.get("YOJONO_TELEGRAM_CHAT")})
        if not ok:
            print("Telegram-lahetys epaonnistui tai ei asetettu", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
