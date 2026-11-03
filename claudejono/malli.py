"""Mallin valinta tehtavalle (Tonyn tyonjako 3.11.2026): halvin malli, joka riittaa laatuun.

Reitit:
  opus | sonnet              -> `claude -p --model <malli>` (Claude-tilaus)
  openrouter:<alias>         -> LiteLLM chat/completions (halvat mallit OpenRouterin kautta), EI tyokaluja

Tehtavatiedoston rivi `Malli: opus|sonnet|openrouter:<alias>` (ensimmaiset 15 rivia) ratkaisee. Puuttuessa malli paatellaan
tehtavan nimen tyypista (TYYPPIKARTTA, ainoa paikka). Tuntematon tai kielletty arvo ei kaada ajoa: kaytetaan paatelty malli ja
huomautus kirjataan tulokseen.

OpenRouter-reitti on tarkoituksella rajattu: sallitut aliakset on lueteltu tassa (OPENROUTER_ALIAKSET), eika reitti saa
tyokaluja, joten tehtavan tekstin pitaa sisaltaa kaiken syotteen. Siksi paattely valitsee sen vain selvasti tekstiluonteisille
tyypeille; muulloin tehtavassa on oltava nimenomainen `Malli:`-rivi.
"""
import json
import re
import socket
import urllib.error
import urllib.request
from collections import namedtuple

CLAUDE_MALLIT = ("opus", "sonnet")
OPENROUTER_ALIAKSET = ("qwen-coder", "deepseek-flash", "deepseek-pro")   # LiteLLM-aliakset (CLAUDE.md); posti-zdr kuuluu posti-agentille
OLETUS_MALLI = "sonnet"
ITSESUUNNITTELUN_MALLI = "sonnet"   # jonon itsesuunnittelu; Tony voi halutessaan vaihtaa opukseksi tasta
OPENROUTER_OLETUS_URL = "http://192.168.1.116:4000"
OPENROUTER_MAX_TOKENS = 4000
OPENROUTER_AIKARAJA_S = 300
MALLI_RIVI_RE = re.compile(r"(?im)^[ \t]*malli[ \t]*:[ \t]*(\S+)[ \t]*$")
MALLI_ARVO_RE = re.compile(r"^(opus|sonnet|openrouter:[a-z0-9][a-z0-9.-]{0,40})$")

# (regex tehtavan nimen sluggiin, malli); ensimmainen osuma voittaa. Slug = nimi ilman paivamaaraa, numeroa ja paatetta.
TYYPPIKARTTA = (
    (r"(^|-)(tiivistelma|luokittelu|kaannos|savy-esitarkistus|esitarkistus)(-|$)", "openrouter:deepseek-flash"),
    (r"(^|-)(suunnittelu|arkkitehtuuri|tarkastus|tarkastaja|katselmointi|riippumaton|vikatutkinta|digi-tony|paatos)(-|$)", "opus"),
)

Valinta = namedtuple("Valinta", "reitti malli lahde huomautus")   # reitti: "claude" | "openrouter"; malli: opus|sonnet|<alias>


def slug(nimi):
    """'2026-11-03-05-malli-tyonjako.md' -> 'malli-tyonjako'."""
    s = re.sub(r"\.md$", "", str(nimi))
    return re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-", "", s)


def paattele(nimi):
    s = slug(nimi)
    for kuvio, malli in TYYPPIKARTTA:
        if re.search(kuvio, s):
            return malli, "tyyppi"
    return OLETUS_MALLI, "oletus"


def _kelpaa(arvo):
    if arvo in CLAUDE_MALLIT:
        return True
    return arvo.startswith("openrouter:") and arvo.split(":", 1)[1] in OPENROUTER_ALIAKSET


def _valinta(malli, lahde, huomautus=""):
    if malli.startswith("openrouter:"):
        return Valinta("openrouter", malli.split(":", 1)[1], lahde, huomautus)
    return Valinta("claude", malli, lahde, huomautus)


def valitse(nimi, teksti):
    """Tehtavan malli: `Malli:`-rivi > tyyppi > oletus."""
    alku = "\n".join(str(teksti).splitlines()[:15])
    m = MALLI_RIVI_RE.search(alku)
    muu, lahde = paattele(nimi)
    if not m:
        return _valinta(muu, lahde)
    arvo = m.group(1).lower()
    if MALLI_ARVO_RE.match(arvo) and _kelpaa(arvo):
        return _valinta(arvo, "tehtava")
    return _valinta(muu, lahde, f"Malli-rivin arvo ei kelpaa ({arvo[:40]!r}), kaytettiin {muu}")


def nimi(v):
    return v.malli if v.reitti == "claude" else f"openrouter:{v.malli}"


class OpenRouterVirhe(Exception):
    """koodi: or_asetus | or_http_<koodi> | or_aikakatkaisu | or_yhteys | or_vastaus"""

    def __init__(self, koodi):
        super().__init__(koodi)
        self.koodi = koodi


class _EiUudelleenohjauksia(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _http_post(url, avain, payload, aikaraja):
    pyynto = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + avain})
    try:
        with urllib.request.build_opener(_EiUudelleenohjauksia).open(pyynto, timeout=aikaraja) as v:
            return json.loads(v.read().decode("utf-8")), dict(v.headers.items())
    except urllib.error.HTTPError as e:
        raise OpenRouterVirhe("or_http_%d" % e.code)
    except urllib.error.URLError as e:
        raise OpenRouterVirhe("or_aikakatkaisu" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "or_yhteys")
    except (socket.timeout, TimeoutError):
        raise OpenRouterVirhe("or_aikakatkaisu")
    except OSError:
        raise OpenRouterVirhe("or_yhteys")
    except ValueError:
        raise OpenRouterVirhe("or_vastaus")


def openrouter_kutsu(alias, kehote, env, hae=None):
    """Yksi chat/completions-kutsu LiteLLM:lle. Palauttaa {teksti, input, output, usd}. Avain vain ymparistosta
    (LITELLM_API_KEY), ei koskaan tulosteisiin. Nostaa OpenRouterVirhe (vain koodi)."""
    if alias not in OPENROUTER_ALIAKSET:
        raise OpenRouterVirhe("or_asetus")
    avain = env.get("LITELLM_API_KEY", "")
    pohja = env.get("LITELLM_BASE_URL", OPENROUTER_OLETUS_URL).rstrip("/")
    if not avain or not pohja.startswith(("http://", "https://")):
        raise OpenRouterVirhe("or_asetus")
    payload = {"model": alias, "max_tokens": OPENROUTER_MAX_TOKENS, "temperature": 0,
               "messages": [{"role": "user", "content": kehote}]}   # tarkoituksella ei tools-kenttaa
    vastaus, otsakkeet = (hae or _http_post)(pohja + "/chat/completions", avain, payload, OPENROUTER_AIKARAJA_S)
    try:
        teksti = vastaus["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise OpenRouterVirhe("or_vastaus")
    if not isinstance(teksti, str) or not teksti.strip():
        raise OpenRouterVirhe("or_vastaus")
    kaytto = vastaus.get("usage") if isinstance(vastaus.get("usage"), dict) else {}
    usd = None
    for avain_nimi, arvo in (otsakkeet or {}).items():
        if avain_nimi.lower() == "x-litellm-response-cost":
            try:
                usd = float(arvo)
            except (TypeError, ValueError):
                usd = None
    return {"teksti": teksti, "input": int(kaytto.get("prompt_tokens") or 0),
            "output": int(kaytto.get("completion_tokens") or 0), "usd": usd}
