#!/usr/bin/env python3
"""MCP-tarkastuksen erajo: kloonaa repolistan, ajaa mcp-doctor --json jokaiselle ja keraa tulokset yhteen JSON-tiedostoon.

AJETAAN VAIN HIEKKALAATIKKOKONTISSA (ks. mcp-tarkastus.md), ei koskaan CT115:lla eika isannalla.
Vain stdlib. Alikomennot ajetaan puhtaalla ymparistolla (ei isannan ymparistomuuttujia, ei salaisuuksia).

  mcp_era.py aja --lista LISTA --ulos TULOS.json [--tyo HAKEMISTO] [--kuiva]
  mcp_era.py tarkista TULOS.json        # validoi tulostiedoston ennen siirtoa CT115:lle

Listaformaatti (yksi repo per rivi, # aloittaa kommentin):
  https://github.com/omistaja/repo
  https://github.com/omistaja/toinen-repo node dist/server.js --stdio
Ilman komentoa kaynnistyskomento paatellaan package.json:n kentista bin ja main.
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

SKEEMA = 1
REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9._-]{0,99})/([A-Za-z0-9][A-Za-z0-9._-]{0,99})$")
OLETUS_PROXY = "http://10.98.0.2:3128"
# Kovat ylarajat: argumentit saavat vain pienentaa.
REPO_AIKARAJA_MAX = 900
ERA_AIKARAJA_MAX = 3300
REPOJA_MAX = 30
TULOSTE_MAX = 20000          # tavua per vaihe (hanta)
RAPORTTI_MAX = 200000        # tavua per repon mcp-doctor-raportti
TULOSTIEDOSTO_MAX = 5000000  # tavua yhteensa
TILAT = {
    "ok", "loydoksia", "kaytto_virhe", "sisainen_virhe", "kloonaus_epaonnistui", "asennus_epaonnistui",
    "rakennus_epaonnistui", "ei_kaynnistyskomentoa", "aikakatkaisu", "json_virheellinen",
    "ohitettu_aikakatko", "virheellinen_rivi", "kuiva",
}


class Virhe(Exception):
    pass


def nyt():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lue_lista(teksti):
    """Palauttaa listan (url, komento|None, virhe|None). Ei verkkoa, ei alikomentoja."""
    rivit = []
    for raaka in teksti.splitlines():
        rivi = raaka.split("#", 1)[0].strip()
        if not rivi:
            continue
        osat = rivi.split(None, 1)
        url = osat[0]
        if not REPO_RE.match(url):
            rivit.append((url[:120], None, "url ei ole muotoa https://github.com/omistaja/repo"))
            continue
        komento = None
        if len(osat) > 1:
            try:
                komento = shlex.split(osat[1])
            except ValueError:
                rivit.append((url, None, "komennon lainausmerkit ovat rikki"))
                continue
            if not komento or komento[0].startswith("-"):
                rivit.append((url, None, "komento ei voi alkaa valitsimella"))
                continue
        rivit.append((url, komento, None))
    return rivit


def paattele_komento(repohakemisto):
    """node <bin|main> package.json:sta; None jos ei loydy tai polku karkaa repon ulkopuolelle."""
    try:
        with open(os.path.join(repohakemisto, "package.json"), encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(pkg, dict):
        return None
    kohde = pkg.get("bin")
    if isinstance(kohde, dict):
        kohde = next(iter(kohde.values()), None)
    if not isinstance(kohde, str):
        kohde = pkg.get("main")
    if not isinstance(kohde, str) or not kohde:
        return None
    juuri = os.path.realpath(repohakemisto)
    abs_ = os.path.realpath(os.path.join(juuri, kohde))
    if os.path.commonpath([juuri, abs_]) != juuri:
        return None
    return ["node", os.path.relpath(abs_, juuri)]


def puhdas_ymparisto(koti, proxy):
    return {
        "PATH": "/usr/local/node/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": koti,
        "LANG": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
        "CI": "1",
        "http_proxy": proxy, "https_proxy": proxy, "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy,
        "npm_config_proxy": proxy, "npm_config_https_proxy": proxy,
        "NO_PROXY": "localhost,127.0.0.1",
    }


def _rajat():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except Exception:
        pass


def suorita(komento, cwd, env, aikaraja):
    """Oikea ajaja: (poistumiskoodi|None, stdout, stderr, aikakatkaisu). Aikakatkaisussa tapetaan koko prosessiryhma."""
    p = subprocess.Popen(komento, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True, preexec_fn=_rajat)
    try:
        ulos, virhe = p.communicate(timeout=aikaraja)
        katko = False
    except subprocess.TimeoutExpired:
        katko = True
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        ulos, virhe = p.communicate()
    return (None if katko else p.returncode), ulos.decode("utf-8", "replace"), virhe.decode("utf-8", "replace"), katko


def hanta(teksti):
    teksti = teksti or ""
    return teksti[-TULOSTE_MAX:]


def tarkista_repo(url, komento, hakemisto, env, aikaraja, ajaja, doctor):
    """Yhden repon vaiheet. Palauttaa tulosrivin (dict). Ei koskaan nosta poikkeusta ajajan virheesta."""
    alku = time.monotonic()
    tulos = {"repo": url, "tila": None, "poistumiskoodi": None, "komento": None, "raportti": None, "huomio": None}
    kohde = os.path.join(hakemisto, url.rsplit("/", 2)[-2] + "__" + url.rsplit("/", 1)[-1])

    def valmis(tila, huomio=None):
        tulos["tila"] = tila
        tulos["huomio"] = huomio
        tulos["kesto_s"] = round(time.monotonic() - alku, 1)
        return tulos

    def vaihe(nimi, kmd, cwd):
        jaljella = aikaraja - (time.monotonic() - alku)
        if jaljella <= 1:
            return None, "", "", True
        return ajaja(kmd, cwd, env, jaljella)

    koodi, _, virhe, katko = vaihe("klooni", ["git", "clone", "--depth", "1", "--no-tags", "--", url, kohde], hakemisto)
    if katko:
        return valmis("aikakatkaisu", "kloonaus")
    if koodi != 0:
        return valmis("kloonaus_epaonnistui", hanta(virhe)[-300:])

    if os.path.exists(os.path.join(kohde, "package.json")):
        koodi, _, virhe, katko = vaihe("asennus", ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], kohde)
        if katko:
            return valmis("aikakatkaisu", "npm install")
        if koodi != 0:
            return valmis("asennus_epaonnistui", hanta(virhe)[-300:])
        try:
            with open(os.path.join(kohde, "package.json"), encoding="utf-8") as f:
                skriptit = (json.load(f) or {}).get("scripts") or {}
        except (OSError, ValueError, AttributeError):
            skriptit = {}
        if isinstance(skriptit, dict) and "build" in skriptit:
            koodi, _, virhe, katko = vaihe("rakennus", ["npm", "run", "build", "--silent"], kohde)
            if katko:
                return valmis("aikakatkaisu", "npm run build")
            if koodi != 0:
                return valmis("rakennus_epaonnistui", hanta(virhe)[-300:])

    kmd = komento or paattele_komento(kohde)
    if not kmd:
        return valmis("ei_kaynnistyskomentoa", "anna komento listassa")
    tulos["komento"] = kmd
    koodi, ulos, virhe, katko = vaihe("doctor", [doctor, "--json", "--timeout-ms", "10000", "--"] + kmd, kohde)
    if katko:
        return valmis("aikakatkaisu", "mcp-doctor")
    tulos["poistumiskoodi"] = koodi
    if koodi in (0, 1):
        try:
            raportti = json.loads(ulos)
        except ValueError:
            return valmis("json_virheellinen", hanta(ulos)[-300:])
        if len(json.dumps(raportti)) > RAPORTTI_MAX:
            tulos["raportti"] = {"katkaistu": True, "koko_tavua": len(json.dumps(raportti))}
        else:
            tulos["raportti"] = raportti
        return valmis("ok" if koodi == 0 else "loydoksia")
    if koodi == 2:
        return valmis("kaytto_virhe", hanta(virhe)[-300:])
    return valmis("sisainen_virhe", hanta(virhe)[-300:])


def yhteenveto(repot):
    laskuri = {}
    for r in repot:
        laskuri[r["tila"]] = laskuri.get(r["tila"], 0) + 1
    return {"repoja": len(repot), "tilat": laskuri}


def aja_era(lista_teksti, ulos_polku, tyo, kuiva=False, repo_aikaraja=300, era_aikaraja=3000,
            ajaja=suorita, proxy=OLETUS_PROXY, doctor="mcp-doctor", koti=None):
    repo_aikaraja = max(10, min(int(repo_aikaraja), REPO_AIKARAJA_MAX))
    era_aikaraja = max(10, min(int(era_aikaraja), ERA_AIKARAJA_MAX))
    rivit = lue_lista(lista_teksti)
    if not rivit:
        raise Virhe("lista on tyhja")
    if len(rivit) > REPOJA_MAX:
        raise Virhe("liikaa repoja (%d > %d)" % (len(rivit), REPOJA_MAX))
    tulos = {"skeema": SKEEMA, "alkoi": nyt(), "kuiva": bool(kuiva), "repo_aikaraja_s": repo_aikaraja,
             "era_aikaraja_s": era_aikaraja, "repot": []}
    env = puhdas_ymparisto(koti or tyo, proxy)
    if not kuiva:
        os.makedirs(tyo, exist_ok=True)
        try:
            v = ajaja([doctor, "--version"], tyo, env, 20)
            tulos["doctor_versio"] = v[1].strip()[:40] if v[0] == 0 else None
        except OSError:
            tulos["doctor_versio"] = None
    alku = time.monotonic()
    for url, komento, virhe in rivit:
        if virhe:
            tulos["repot"].append({"repo": url, "tila": "virheellinen_rivi", "huomio": virhe})
        elif kuiva:
            tulos["repot"].append({"repo": url, "tila": "kuiva", "komento": komento or "paatellaan package.json:sta",
                                   "huomio": "ei ajettu"})
        elif time.monotonic() - alku > era_aikaraja:
            tulos["repot"].append({"repo": url, "tila": "ohitettu_aikakatko", "huomio": "erakatto tayttyi"})
        else:
            tulos["repot"].append(tarkista_repo(url, komento, tyo, env, repo_aikaraja, ajaja, doctor))
    tulos["loppui"] = nyt()
    tulos["yhteenveto"] = yhteenveto(tulos["repot"])
    tarkista_tulos(tulos)
    kirjoita_atomisesti(ulos_polku, tulos)
    return tulos


def kirjoita_atomisesti(polku, data):
    teksti = json.dumps(data, ensure_ascii=True, indent=1, sort_keys=True) + "\n"
    if len(teksti) > TULOSTIEDOSTO_MAX:
        raise Virhe("tulostiedosto liian suuri")
    tmp = polku + ".tmp"
    with open(tmp, "w", encoding="ascii") as f:
        f.write(teksti)
    os.replace(tmp, polku)


def tarkista_tulos(d):
    """Validoi tulosrakenteen. Nostaa Virhe jos jokin on pielessa. Tulos on dataa: sisaltoa ei tulkita."""
    if not isinstance(d, dict) or d.get("skeema") != SKEEMA:
        raise Virhe("skeema puuttuu tai vaara")
    repot = d.get("repot")
    if not isinstance(repot, list) or len(repot) > REPOJA_MAX:
        raise Virhe("repot-lista puuttuu tai liian pitka")
    for r in repot:
        if not isinstance(r, dict) or r.get("tila") not in TILAT or not isinstance(r.get("repo"), str):
            raise Virhe("virheellinen repo-rivi")
    y = d.get("yhteenveto")
    if not isinstance(y, dict) or y.get("repoja") != len(repot):
        raise Virhe("yhteenveto ei tasmaa")


def tarkista_tiedosto(polku):
    if os.path.getsize(polku) > TULOSTIEDOSTO_MAX:
        raise Virhe("tiedosto liian suuri")
    with open(polku, encoding="utf-8") as f:
        tarkista_tulos(json.load(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    alik = ap.add_subparsers(dest="komento", required=True)
    a = alik.add_parser("aja")
    a.add_argument("--lista", required=True)
    a.add_argument("--ulos", required=True)
    a.add_argument("--tyo", default=os.path.expanduser("~/tyo"))
    a.add_argument("--kuiva", action="store_true")
    a.add_argument("--repo-aikaraja", type=int, default=300)
    a.add_argument("--era-aikaraja", type=int, default=3000)
    a.add_argument("--proxy", default=os.environ.get("MCP_ERA_PROXY", OLETUS_PROXY))
    t = alik.add_parser("tarkista")
    t.add_argument("tiedosto")
    arg = ap.parse_args(argv)
    try:
        if arg.komento == "tarkista":
            tarkista_tiedosto(arg.tiedosto)
            print("ok")
            return 0
        with open(arg.lista, encoding="utf-8") as f:
            teksti = f.read()
        tulos = aja_era(teksti, arg.ulos, arg.tyo, arg.kuiva, arg.repo_aikaraja, arg.era_aikaraja, proxy=arg.proxy)
        print(json.dumps(tulos["yhteenveto"], sort_keys=True))
        return 0
    except (Virhe, OSError, ValueError) as e:
        print("virhe: " + type(e).__name__ + (": " + str(e) if isinstance(e, Virhe) else ""), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
