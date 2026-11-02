"""Kysyntamittari: viikon luvut Tonyn julkisista tyokaluista (valitavoite 5, Tonyn paatos 2.11.2026).

Laskee npm-lataukset seka GitHubin tahdet, forkit, issuet ja PR:t siten, etta omat tunnukset ja botit eivat kasvata
ulkoisia lukuja (botin oma forkki ei ole kysyntaa). Epaonnistunut haku on "?", ei koskaan 0: tuntematon ei saa
nayttaa silta, ettei kukaan kayta. Yhteydenotot Tony kertoo itse, niita ei lueta mistaan.

Kaytto:
    python3 -m agentti.kysynta [--tila polku | --ei-tilaa]
Tulostaa markdown-taulukon. Paivan luvut tallentuvat tilatiedostoon (oletus TILA_OLETUS, --tila vaihtaa, --ei-tilaa jattaa
tallentamatta) ja taulukko nayttaa muutoksen edelliseen eri paivan mittaukseen. Tahdet ovat repon stargazers_count eli
kokonaismaara (omat mukana); forkit, issuet ja PR:t ovat ulkoisia.
Vain luku, ei tunnuksia, vain stdlib. GitHubin kirjautumaton raja on 60 pyyntoa tunnissa; yksi ajo kuluttaa enintaan
3 pyyntoa repoa kohden (+1 npm), joten aja kerran paivassa tai harvemmin. Virheista nakyy vain tyypin nimi ja HTTP-tila."""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .pr_kutsu import REPOT

TILA_OLETUS = "/opt/agentscope/tyo/kysynta-tila/kysynta.json"  # claudejono saa kirjoittaa tanne; /var/lib/claude-jono ei
OMISTAJA = "tonyweckstrom1987"
OMAT_TUNNUKSET = {OMISTAJA, "agenttifirma-bot"}
NPM_PAKETIT = {
    "mcp-doctor": "@tonyweckstrom/mcp-doctor",
    "mcp-model-router": "mcp-model-router",
    "evalkit": "@tonyweckstrom/evalkit",
    "llm-cassette": "@tonyweckstrom/llm-cassette",
}
AIKAKATKAISU = 20
SIVUKOKO = 100
HISTORIA_MAX = 120
UA = "agenttifirma-kysynta/1"
SARAKKEET = ("npm_viikko", "tahdet", "forkit", "issuet", "prt")


def hae_json(osoite):
    pyynto = urllib.request.Request(osoite, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(pyynto, timeout=AIKAKATKAISU) as v:
        return json.loads(v.read().decode("utf-8"))


def _virhe(e):
    """Virheen tyyppi ja mahdollinen HTTP-tila (esim. "HTTPError 401"). Vastauksen sisaltoa tai osoitetta ei oteta mukaan."""
    koodi = getattr(e, "code", None) if isinstance(e, urllib.error.HTTPError) else None
    return type(e).__name__ + (" %d" % koodi if isinstance(koodi, int) else "")


def ulkoinen(kayttaja):
    """Onko GitHub-kayttaja joku muu kuin Tony, hanen bottinsa tai mika tahansa automaatio."""
    if not isinstance(kayttaja, dict) or not kayttaja.get("login"):
        return False
    tunnus = kayttaja["login"]
    return kayttaja.get("type") != "Bot" and not tunnus.endswith("[bot]") and tunnus.lower() not in {o.lower() for o in OMAT_TUNNUKSET}


def _laske_ulkoiset(lista):
    """Taysi sivu tarkoittaa, etta rivit saattoivat jaada lukematta: luku on silloin alaraja, joka merkitaan +:lla."""
    maara = sum(1 for k in lista if ulkoinen(k))
    return "%d+" % maara if len(lista) >= SIVUKOKO else maara


def repo_luvut(repo, hae=hae_json):
    """Yhden repon GitHub-luvut. Kukin luku haetaan erikseen, joten yksi epaonnistunut haku ei vie muita."""
    perus = "https://api.github.com/repos/%s/%s" % (OMISTAJA, repo)
    luvut = {"tahdet": "?", "forkit": "?", "issuet": "?", "prt": "?"}
    virheet = []
    try:
        # Repon oma stargazers_count-kentta: stargazers-osoite vaatii kirjautumisen (401). Luku on kokonaismaara, omat tahdet mukana.
        maara = hae(perus).get("stargazers_count")
        if isinstance(maara, bool) or not isinstance(maara, int):
            raise ValueError("ei lukua")
        luvut["tahdet"] = maara
    except Exception as e:
        virheet.append("tahdet: " + _virhe(e))
    try:
        luvut["forkit"] = _laske_ulkoiset([f.get("owner") for f in hae("%s/forks?per_page=%d" % (perus, SIVUKOKO))])
    except Exception as e:
        virheet.append("forkit: " + _virhe(e))
    try:
        # GitHubin issues-rajapinta palauttaa myos PR:t; ne erottaa pull_request-kentasta.
        rivit = hae("%s/issues?state=all&per_page=%d" % (perus, SIVUKOKO))
        taysi = len(rivit) >= SIVUKOKO
        issuet = [r.get("user") for r in rivit if "pull_request" not in r]
        prt = [r.get("user") for r in rivit if "pull_request" in r]
        for avain, lista in (("issuet", issuet), ("prt", prt)):
            maara = sum(1 for k in lista if ulkoinen(k))
            luvut[avain] = "%d+" % maara if taysi else maara
    except Exception as e:
        virheet.append("issuet: " + _virhe(e))
    return luvut, virheet


def npm_viikko(paketti, hae=hae_json):
    """Viimeisen viikon lataukset. Julkaisematon paketti tai virhe: "?". Palauttaa (luku, virhe tai None)."""
    if paketti is None:
        return "-", None
    try:
        vastaus = hae("https://api.npmjs.org/downloads/point/last-week/" + paketti)
        luku = vastaus.get("downloads")
        if isinstance(luku, bool) or not isinstance(luku, int):
            return "?", "npm: ei lukua"
        return luku, None
    except Exception as e:
        return "?", "npm: " + _virhe(e)


def mittaa(repot=REPOT, hae=hae_json):
    """Palauttaa (luvut repoittain, virherivit). Virherivilla on vain virheen tyyppi."""
    tulos, virheet = {}, []
    for repo in repot:
        luvut, repon_virheet = repo_luvut(repo, hae)
        luku, virhe = npm_viikko(NPM_PAKETIT.get(repo), hae)
        luvut["npm_viikko"] = luku
        tulos[repo] = luvut
        virheet += ["%s %s" % (repo, v) for v in repon_virheet + ([virhe] if virhe else [])]
    return tulos, virheet


def _muutos(nyt, ennen):
    """Muutos vain kahden tunnetun, tarkan luvun valilla; "?" ja alarajat ("5+") eivat anna muutosta."""
    if type(nyt) is int and type(ennen) is int and nyt != ennen:
        return " (%+d)" % (nyt - ennen)
    return ""


def muotoile(luvut, virheet, edellinen=None, edellinen_pvm=None):
    rivit = ["# Kysynt\u00e4mittari", "", "Ulkoiset luvut: omat tunnukset ja botit eiv\u00e4t ole mukana. ? = haku ep\u00e4onnistui. - = ei npm-pakettia. Luku + = v\u00e4hint\u00e4\u00e4n."]
    if edellinen_pvm:
        rivit.append("Suluissa muutos mittaukseen %s." % edellinen_pvm)
    rivit += ["", "| Repo | npm/vko | T\u00e4hdet | Forkit | Issuet | PR:t |", "|---|---|---|---|---|---|"]
    edellinen = edellinen or {}
    for repo in sorted(luvut):
        vanha = edellinen.get(repo, {})
        solut = ["%s%s" % (luvut[repo].get(s, "?"), _muutos(luvut[repo].get(s), vanha.get(s))) for s in SARAKKEET]
        rivit.append("| %s | %s |" % (repo, " | ".join(solut)))
    rivit += ["", "npm laskee my\u00f6s CI-ajot ja peilit, joten lataus ei ole sama kuin k\u00e4ytt\u00e4j\u00e4."]
    if virheet:
        rivit += ["", "## Ep\u00e4onnistuneet haut"] + ["- " + v for v in virheet]
    return "\n".join(rivit) + "\n"


def lue_tila(polku):
    try:
        data = json.loads(Path(polku).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def kirjoita_tila(polku, tila, pvm, luvut):
    """Saman paivan uusi ajo korvaa mittauksen. Vanhimmat karsitaan. Kirjoitus on atominen, ettei kaatuminen riko historiaa."""
    uusi = dict(tila)
    uusi[pvm] = luvut
    for vanha in sorted(uusi)[:-HISTORIA_MAX]:
        del uusi[vanha]
    kohde = Path(polku)
    kohde.parent.mkdir(parents=True, exist_ok=True)
    kahva, tmp = tempfile.mkstemp(dir=str(kohde.parent), prefix=".kysynta-")
    try:
        with os.fdopen(kahva, "w", encoding="utf-8") as f:
            json.dump(uusi, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, kohde)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None, hae=hae_json, tanaan=None):
    ap = argparse.ArgumentParser(prog="agentti.kysynta")
    ap.add_argument("--tila", default=TILA_OLETUS, help="JSON-historia, johon paivan luvut tallennetaan (oletus %s)" % TILA_OLETUS)
    ap.add_argument("--ei-tilaa", action="store_true", help="ala lue tai kirjoita tilaa")
    a = ap.parse_args(argv)
    pvm = tanaan or time.strftime("%Y-%m-%d")
    luvut, virheet = mittaa(hae=hae)
    tila = {} if a.ei_tilaa else lue_tila(a.tila)
    aiemmat = sorted(p for p in tila if p < pvm)
    edellinen_pvm = aiemmat[-1] if aiemmat else None
    print(muotoile(luvut, virheet, tila.get(edellinen_pvm), edellinen_pvm), end="")
    if not a.ei_tilaa:
        kirjoita_tila(a.tila, tila, pvm, luvut)
    # Kaikkien hakujen epaonnistuminen on verkko- tai rajaongelma, ei tyhja tulos: exit 1 nakyy valvonnassa.
    tunnetut = any(v not in ("?", "-") for rivi in luvut.values() for v in rivi.values())
    return 0 if tunnetut else 1


if __name__ == "__main__":
    sys.exit(main())
