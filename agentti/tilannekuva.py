"""Tilannekuva: tarkkailija-agenttien syote (VAIN LUKU, ei kirjoita mihinkaan muualle kuin annettuun hakemistoon).

Keraa tekstitiedostoiksi: GitHubin julkiset tiedot, yojonon tila ja raportit, kulut ja palvelimen perustila.
Agentti lukee vain nama tiedostot; salaisuuden nakoiset merkkijonot siivotaan pois ennen kirjoitusta.
Kaytto: python3 -m agentti.tilannekuva <kohdehakemisto>   (ymparisto: YOJONO_PERUS, PORTTI_TILA)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .pr_kutsu import REPOT

OMISTAJA = "tonyweckstrom1987"
RAJA_RIVEJA = 400
SALAISUUDET = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer)\s*[:=]\s*\S{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def siivoa(teksti):
    """Poistaa salaisuuden nakoiset merkkijonot ja rajaa pituuden."""
    for s in SALAISUUDET:
        teksti = s.sub("[poistettu]", teksti)
    rivit = teksti.splitlines()
    if len(rivit) > RAJA_RIVEJA:
        rivit = rivit[:RAJA_RIVEJA] + ["(katkaistu)"]
    return "\n".join(rivit) + "\n"


def _json(polku, oletus):
    try:
        return json.loads(Path(polku).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return oletus


def github_osio(hae=None):
    """Julkisten repojen viimeisimmat PR:t ja commitit (ilman tunnuksia)."""
    def oletushaku(url):
        pyynto = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agenttifirma-tilannekuva"})
        with urllib.request.urlopen(pyynto, timeout=20) as v:
            return json.loads(v.read().decode("utf-8"))
    hae = hae or oletushaku
    rivit = ["# GitHub (julkiset repot)"]
    for repo in REPOT:
        rivit.append("\n## " + repo)
        try:
            prt = hae("https://api.github.com/repos/%s/%s/pulls?state=all&per_page=12&sort=updated" % (OMISTAJA, repo))
            for p in prt:
                tila = "mergattu" if p.get("merged_at") else p.get("state")
                rivit.append("- PR #%s [%s] %s (tekija %s, %s)" % (p.get("number"), tila, str(p.get("title"))[:90],
                                                                   (p.get("user") or {}).get("login"), str(p.get("updated_at"))[:10]))
            cs = hae("https://api.github.com/repos/%s/%s/commits?per_page=8" % (OMISTAJA, repo))
            for c in cs:
                rivit.append("- commit %s %s" % (str(c.get("sha"))[:7], str((c.get("commit") or {}).get("message", "")).splitlines()[0][:90]))
        except Exception as e:  # yksi repo ei saa kaataa kokonaisuutta
            rivit.append("(haku epaonnistui: %s)" % type(e).__name__)
    return "\n".join(rivit)


def yojono_osio(perus):
    perus = Path(perus)
    tila = _json(perus / "tila.json", {})
    jono = _json(perus / "jono.json", {})
    rivit = ["# Yojono"]
    rivit.append("paivakatto: %s, kuukausikatto: %s" % (jono.get("paivakatto"), jono.get("kuukausikatto")))
    rivit.append("\n## Tehtavat (tila.json)")
    for tid, s in sorted((tila.get("tehtavat") or {}).items()):
        rivit.append("- %s: %s, yrityksia %s, pvm %s, kulu %s, viesti: %s" % (
            tid, s.get("tila"), s.get("yrityksia"), s.get("pvm"), s.get("kulu"), str(s.get("viesti"))[:120]))
    rivit.append("\n## Jonossa mutta ei ajettu")
    ajettu = set((tila.get("tehtavat") or {}))
    for t in jono.get("tehtavat", []):
        if t.get("id") not in ajettu:
            rivit.append("- %s [%s%s] %s" % (t.get("id"), t.get("tyyppi"), "/" + t["aihe"] if t.get("aihe") else "", t.get("repo")))
    rivit.append("\n## Viimeisimmat raportit")
    raportit = sorted((perus / "raportit").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:12] if (perus / "raportit").is_dir() else []
    for r in raportit:
        try:
            alku = [l for l in r.read_text(encoding="utf-8").splitlines() if l.startswith(("- PR", "- Syy", "- Testit", "# "))][:5]
        except OSError:
            alku = []
        rivit.append("- %s: %s" % (r.name, " | ".join(a.strip() for a in alku)))
    return "\n".join(rivit)


def kulut_osio(perus, portti_tila):
    tila = _json(Path(perus) / "tila.json", {})
    rivit = ["# Kulut (USD)"]
    kulut = tila.get("kulut") or {}
    for pvm in sorted(kulut)[-14:]:
        rivit.append("- yojono %s: %s" % (pvm, kulut[pvm]))
    if portti_tila:
        data = _json(Path(portti_tila) / "portti-kulu.json", {})
        rivit.append("\n## Portti (paivakirjanpito)")
        rivit.append(json.dumps(data, ensure_ascii=True)[:1500])
    return "\n".join(rivit)


def _komento(*args):
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=15, check=False)
        return (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return "(ei saatavilla)"


def palvelin_osio():
    rivit = ["# Palvelin (CT115)"]
    kokonais, kaytetty, vapaa = shutil.disk_usage("/")
    rivit.append("levy /: %.1f GB kaytetty / %.1f GB (vapaa %.1f GB)" % (kaytetty / 1e9, kokonais / 1e9, vapaa / 1e9))
    try:
        mem = dict(l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines() if ":" in l)
        rivit.append("muisti: yht %s, vapaana %s" % (mem.get("MemTotal", "?").strip(), mem.get("MemAvailable", "?").strip()))
        rivit.append("kuorma: " + Path("/proc/loadavg").read_text().strip())
    except OSError:
        rivit.append("(muisti/kuorma ei saatavilla)")
    rivit.append("\n## Epaonnistuneet palvelut (systemctl --failed)")
    rivit.append(_komento("systemctl", "list-units", "--failed", "--no-legend", "--no-pager") or "(ei yhtaan)")
    rivit.append("\n## Ajastimet")
    rivit.append(_komento("systemctl", "list-timers", "--no-pager", "--no-legend")[:1500])
    rivit.append("\n## Versiot")
    for k in (("node", "--version"), ("npm", "--version"), ("python3", "--version"), ("git", "--version")):
        rivit.append("%s: %s" % (k[0], _komento(*k)[:60]))
    return "\n".join(rivit)


def keraa_kaikki(kohde, perus="/var/lib/yojono", portti_tila="/var/lib/agentti/portti", hae=None):
    """Kirjoittaa tilannekuvan tiedostot kohdehakemistoon; palauttaa kirjoitettujen nimien listan."""
    kohde = Path(kohde)
    kohde.mkdir(parents=True, exist_ok=True)
    osat = {
        "github.md": lambda: github_osio(hae),
        "yojono.md": lambda: yojono_osio(perus),
        "kulut.md": lambda: kulut_osio(perus, portti_tila),
        "palvelin.md": palvelin_osio,
    }
    nimet = []
    for nimi, f in osat.items():
        try:
            teksti = f()
        except Exception as e:
            teksti = "(osio epaonnistui: %s)" % type(e).__name__
        (kohde / nimi).write_text(siivoa(teksti), encoding="utf-8")
        nimet.append(nimi)
    (kohde / "aika.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n", encoding="utf-8")
    return nimet


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("kaytto: python3 -m agentti.tilannekuva <kohdehakemisto>", file=sys.stderr)
        return 2
    nimet = keraa_kaikki(argv[0], os.environ.get("YOJONO_PERUS", "/var/lib/yojono"), os.environ.get("PORTTI_TILA", "/var/lib/agentti/portti"))
    print("tilannekuva: " + ", ".join(nimet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
