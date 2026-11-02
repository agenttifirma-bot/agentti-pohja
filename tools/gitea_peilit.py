"""gitea_peilit.py: luo Giteaan pull-peilit GitHub-kayttajan julkisista repoista (vain vakiokirjasto).

Kaytto (Tonin koneelta tai CT113:n kanssa samassa verkossa):
  GITEA_TOKEN=... python3 tools/gitea_peilit.py --gitea https://GITEA-OSOITE            # kuiva-ajo (oletus)
  GITEA_TOKEN=... python3 tools/gitea_peilit.py --gitea https://GITEA-OSOITE --aja      # luo peilit

- Kuiva-ajo on oletus: se listaa repot ja koon, mutta ei kirjoita Giteaan.
- Gitea-token luetaan vain ymparistomuuttujasta GITEA_TOKEN. Sita ei tulosteta, eika se mene lokiin.
- GitHubista luetaan vain julkiset repot (tokenia ei tarvita). Yksityiset repot eivat kuulu tahan skriptiin.
- Jo olemassa oleva Gitea-repo ohitetaan, joten skriptin voi ajaa uudelleen.
- Virheista tulostetaan vain tyyppi ja HTTP-tila.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

GITHUB_API = "https://api.github.com"
VALI = "1h0m0s"  # Gitean mirror_interval; "1h" ei kelpaa muodoksi kaikissa versioissa
AIKAKATKAISU = 30


def _pyynto(url, token=None, data=None, metodi=None):
    """Palauttaa (tila, json). HTTP-virheesta tilakoodi ja None; verkkovirheesta (0, None)."""
    otsakkeet = {"Accept": "application/json", "User-Agent": "gitea-peilit"}
    if token:
        otsakkeet["Authorization"] = "token " + token
    runko = None
    if data is not None:
        runko = json.dumps(data).encode()
        otsakkeet["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=runko, headers=otsakkeet, method=metodi)
    try:
        with urllib.request.urlopen(req, timeout=AIKAKATKAISU) as r:
            teksti = r.read()
            return r.status, (json.loads(teksti) if teksti else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def github_repot(kayttaja, pyynto=_pyynto, forkit=False):
    """Kayttajan julkiset repot GitHubista (sivutettu). Nostaa RuntimeErrorin, jos haku epaonnistuu."""
    tulos, sivu = [], 1
    while True:
        tila, data = pyynto(f"{GITHUB_API}/users/{kayttaja}/repos?per_page=100&type=owner&page={sivu}")
        if tila != 200 or not isinstance(data, list):
            raise RuntimeError(f"GitHub-haku epaonnistui, tila {tila}")
        tulos += data
        if len(data) < 100:
            break
        sivu += 1
    return [r for r in tulos if not r.get("private") and (forkit or not r.get("fork"))]


def koko_mt(repot):
    """GitHubin size-kentta on kilotavuja."""
    return sum(r.get("size", 0) for r in repot) / 1024


def peilaa(repot, gitea, token, aja, pyynto=_pyynto, tulosta=print):
    """Kay repot lapi. Palauttaa laskurit {luotu, ohitettu, kuiva, virhe}."""
    n = {"luotu": 0, "ohitettu": 0, "kuiva": 0, "virhe": 0}
    for r in repot:
        nimi = r["name"]
        if aja:
            # Omistajan saa tokenin kayttajasta: haetaan oma tunnus ja tarkistetaan onko repo jo olemassa.
            tila, kayttaja = pyynto(f"{gitea}/api/v1/user", token)
            if tila != 200 or not isinstance(kayttaja, dict):
                tulosta(f"VIRHE Gitea-tunnistus epaonnistui, tila {tila}")
                n["virhe"] += 1
                break
            tila, _ = pyynto(f"{gitea}/api/v1/repos/{kayttaja['login']}/{nimi}", token)
            if tila == 200:
                tulosta(f"OHITETTU {nimi} (on jo Giteassa)")
                n["ohitettu"] += 1
                continue
            tila, _ = pyynto(
                f"{gitea}/api/v1/repos/migrate", token, metodi="POST",
                data={"clone_addr": r["clone_url"], "repo_name": nimi, "service": "git", "mirror": True,
                      "mirror_interval": VALI, "private": True, "description": (r.get("description") or "")[:250]},
            )
            if tila in (200, 201):
                tulosta(f"LUOTU {nimi}")
                n["luotu"] += 1
            else:
                tulosta(f"VIRHE {nimi}: tila {tila}")
                n["virhe"] += 1
        else:
            tulosta(f"KUIVA {nimi} ({r.get('size', 0)} kt) <- {r['clone_url']}")
            n["kuiva"] += 1
    return n


def main(argv=None, pyynto=_pyynto):
    p = argparse.ArgumentParser(description="Luo Gitea-pull-peilit GitHub-kayttajan julkisista repoista.")
    p.add_argument("--gitea", required=True, help="Gitean perusosoite, esim. https://gitea.example")
    p.add_argument("--kayttaja", default="tonyweckstrom1987", help="GitHub-kayttaja")
    p.add_argument("--aja", action="store_true", help="luo peilit oikeasti (oletus: kuiva-ajo)")
    p.add_argument("--forkit", action="store_true", help="ota mukaan myos forkit")
    a = p.parse_args(argv)
    token = os.environ.get("GITEA_TOKEN", "")
    if a.aja and not token:
        print("GITEA_TOKEN puuttuu ymparistosta", file=sys.stderr)
        return 2
    try:
        repot = github_repot(a.kayttaja, pyynto, a.forkit)
    except RuntimeError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    n = peilaa(repot, a.gitea.rstrip("/"), token, a.aja, pyynto)
    print(f"Repoja {len(repot)}, GitHubin ilmoittama koko yhteensa {koko_mt(repot):.1f} Mt; {n}")
    return 1 if n["virhe"] else 0


if __name__ == "__main__":
    sys.exit(main())
