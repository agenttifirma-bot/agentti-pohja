"""GitHub App -asennustunnus (lyhytikainen, 1 h) PAT:n tilalle. Vain stdlib + openssl-komento (RS256-allekirjoitus).

Asetukset (JSON, ei salaisuutta; esim. /etc/claudejono-pr/app.json, 600 prbotti):
    {"app_id": 123456, "avain": "/etc/claudejono-pr/app.pem", "asennus_fork": 111, "asennus_pr": 222}
- yksityinen avain on erillinen tiedosto (600, vain prbotti); sita ei lueta Pythonissa, vaan openssl saa polun
- tunnus haetaan vain tarvittavalle repolle ja vain tarvittavalla oikeudella (contents:write forkkiin, pull_requests:write PR:aan)
- valimuisti: tiedosto 600 hakemistossa `tila` (avain: asennus+repo+oikeus), uusitaan kun jaljella < MARGINAALI_S
- virheissa vain tyyppi / HTTP-tila, ei koskaan tunnusta tai avainta
"""
import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
MARGINAALI_S = 600          # uusi tunnus, jos vanha vanhenee alle 10 minuutin kuluttua (yksi PR-ajo kestaa < 10 min)
OIKEUDET = {"fork": {"contents": "write"}, "pr": {"pull_requests": "write"}}   # ei workflows-oikeutta
NIMI_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class AppVirhe(Exception):
    """Viesti on turvallinen tulostaa (ei sisalla tunnusta tai avainta)."""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def luo_jwt(app_id, avainpolku, nyt=None, suorita=subprocess.run):
    """RS256-JWT (voimassa 9 min, iat 60 s taakse kellovirheen varalta). Allekirjoitus: openssl dgst -sha256 -sign <avain>."""
    nyt = int(time.time() if nyt is None else nyt)
    if not isinstance(app_id, int) or app_id <= 0:
        raise AppVirhe("app_id ei kelpaa")
    osat = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "." + \
        _b64(json.dumps({"iat": nyt - 60, "exp": nyt + 540, "iss": app_id}).encode())
    try:
        r = suorita(["openssl", "dgst", "-sha256", "-sign", avainpolku], input=osat.encode("ascii"),
                    capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AppVirhe("openssl ei kaynnisty: " + type(e).__name__) from None
    if r.returncode != 0 or not r.stdout:
        raise AppVirhe("JWT:n allekirjoitus epaonnistui (avain puuttuu tai ei kelpaa)")
    return osat + "." + _b64(r.stdout)


def lue_asetukset(polku):
    try:
        with open(polku, encoding="ascii") as f:
            a = json.load(f)
    except (OSError, ValueError):
        raise AppVirhe("App-asetuksia ei voi lukea") from None
    if not (isinstance(a, dict) and isinstance(a.get("avain"), str) and a["avain"].startswith("/")
            and all(isinstance(a.get(k), int) and a[k] > 0 for k in ("app_id", "asennus_fork", "asennus_pr"))):
        raise AppVirhe("App-asetusten muoto ei kelpaa")
    return a


def _vanhenee(iso):
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone


def hae_tunnus(asetuspolku, rooli, repo, tila, nyt=None, avaa=urllib.request.urlopen, suorita=subprocess.run):
    """Palauttaa asennustunnuksen (ghs_...). rooli: 'fork' | 'pr'. repo: pelkka reponimi (ei omistajaa)."""
    if rooli not in OIKEUDET:
        raise AppVirhe("tuntematon rooli")
    if not NIMI_RE.match(repo or ""):
        raise AppVirhe("reponimi ei kelpaa")
    nyt = time.time() if nyt is None else nyt
    a = lue_asetukset(asetuspolku)
    asennus = a["asennus_" + rooli]
    valimuisti = os.path.join(tila, "app-%d-%s-%s.json" % (asennus, repo, rooli))
    try:
        with open(valimuisti, encoding="ascii") as f:
            v = json.load(f)
        if isinstance(v.get("token"), str) and v.get("vanhenee", 0) - nyt > MARGINAALI_S:
            return v["token"]
    except (OSError, ValueError, AttributeError):
        pass
    jwt = luo_jwt(a["app_id"], a["avain"], nyt=nyt, suorita=suorita)
    pyynto = urllib.request.Request(
        "%s/app/installations/%d/access_tokens" % (API, asennus), method="POST",
        data=json.dumps({"repositories": [repo], "permissions": OIKEUDET[rooli]}).encode(),
        headers={"Authorization": "Bearer " + jwt, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "yojono-github-app"})
    try:
        with avaa(pyynto, timeout=30) as vastaus:
            d = json.loads(vastaus.read().decode("utf-8"))
        token, vanhenee = d["token"], _vanhenee(d["expires_at"])
    except urllib.error.HTTPError as e:
        raise AppVirhe("tunnuksen haku hylatty (HTTP %s)" % e.code) from None
    except (urllib.error.URLError, ValueError, KeyError, TypeError, OSError) as e:
        raise AppVirhe("tunnuksen haku epaonnistui: " + type(e).__name__) from None
    if not (isinstance(token, str) and token.startswith("ghs_")):
        raise AppVirhe("vastauksen tunnus ei ole asennustunnus")
    try:
        os.makedirs(tila, mode=0o700, exist_ok=True)
        tmp = valimuisti + ".tmp"
        with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w", encoding="ascii") as f:
            json.dump({"token": token, "vanhenee": vanhenee}, f)
        os.replace(tmp, valimuisti)
    except OSError:
        pass                                   # valimuisti on vain optimointi
    return token
