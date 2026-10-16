"""LLM-asiakas (OpenAI-yhteensopiva, esim. LiteLLM). Ei tyokaluja, ei uudelleenyrityksia.

- Kulu varataan ennen kutsua (kulu.Kulu.varaa), joten katto pitaa myos virhetilanteissa.
- max_tokens on aina korkeintaan rajat.MAX_TOKENS.
- Uudelleenohjauksia ei seurata (Authorization-otsake ei saa karata muualle).
- Virheet ovat koodeja (LLMVirhe.koodi); avainta tai vastauksen sisaltoa ei koskaan tulosteta.
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import rajat

ROOLIT = ("system", "user", "assistant")


class LLMVirhe(Exception):
    """koodi: llm_asetus | llm_aikakatkaisu | llm_http_<koodi> | llm_yhteys |
    llm_vastaus_tyhja | llm_vastaus_katkaistu | llm_vastaus_rakenne"""

    def __init__(self, koodi):
        super().__init__(koodi)
        self.koodi = koodi


class _EiUudelleenohjauksia(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _http_post(url, avain, payload):
    pyynto = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + avain},
    )
    avaaja = urllib.request.build_opener(_EiUudelleenohjauksia)
    try:
        with avaaja.open(pyynto, timeout=rajat.LLM_AIKAKATKAISU) as v:
            return json.loads(v.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMVirhe("llm_http_%d" % e.code)
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise LLMVirhe("llm_aikakatkaisu")
        raise LLMVirhe("llm_yhteys")
    except (socket.timeout, TimeoutError):
        raise LLMVirhe("llm_aikakatkaisu")
    except OSError:
        raise LLMVirhe("llm_yhteys")
    except ValueError:
        raise LLMVirhe("llm_vastaus_rakenne")


def arvioi_usd(kaytto, malli):
    """Todellinen kulu hinnastosta, tai None jos mallia/kayttoa ei tunneta."""
    hinta = rajat.HINNAT_USD_PER_MILJOONA.get(malli)
    if not hinta or not isinstance(kaytto, dict):
        return None
    try:
        syote = float(kaytto["prompt_tokens"])
        tuloste = float(kaytto["completion_tokens"])
    except (KeyError, TypeError, ValueError):
        return None
    return (syote * hinta[0] + tuloste * hinta[1]) / 1_000_000


def _tarkista_viestit(viestit):
    if not isinstance(viestit, list) or not viestit:
        raise LLMVirhe("llm_asetus")
    for v in viestit:
        if not isinstance(v, dict) or v.get("role") not in ROOLIT or not isinstance(v.get("content"), str):
            raise LLMVirhe("llm_asetus")


def kysy(viestit, malli, env, kulu, hae=None, max_tokens=None):
    """Palauttaa (teksti, kaytto). Nostaa LLMVirhe tai kulu.KulukattoYlittyi."""
    _tarkista_viestit(viestit)
    osoite, avain = env.get("LLM_BASE_URL"), env.get("LLM_API_KEY")
    if not osoite or not avain or not malli:
        raise LLMVirhe("llm_asetus")
    if urllib.parse.urlparse(osoite).scheme not in ("http", "https"):
        raise LLMVirhe("llm_asetus")
    hae = hae or _http_post
    varaus = kulu.varaa()  # nostaa KulukattoYlittyi ennen verkkoa
    payload = {
        "model": malli,
        "messages": viestit,
        "max_tokens": min(int(max_tokens or rajat.MAX_TOKENS), rajat.MAX_TOKENS),
        "temperature": 0,
    }  # tarkoituksella ei 'tools' / 'functions'
    vastaus = hae(osoite.rstrip("/") + "/chat/completions", avain, payload)
    kaytto = vastaus.get("usage") if isinstance(vastaus, dict) else None
    kaytto = kaytto if isinstance(kaytto, dict) else {}
    kulu.kirjaa(varaus, arvioi_usd(kaytto, malli))
    try:
        valinta = vastaus["choices"][0]
        teksti = valinta["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMVirhe("llm_vastaus_rakenne")
    if valinta.get("finish_reason") == "length":
        raise LLMVirhe("llm_vastaus_katkaistu")
    if not isinstance(teksti, str) or not teksti.strip():
        raise LLMVirhe("llm_vastaus_tyhja")
    return teksti, kaytto
