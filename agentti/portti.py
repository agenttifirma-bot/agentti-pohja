"""Portti: AgentScope/agentti-pohja -agentit nakyviin Open WebUI:hin (OpenAI-yhteensopiva rajapinta).

Open WebUI:ssa: Admin -> Connections -> OpenAI API -> lisaa osoite http://<portti-ip>:<portti>/v1 ja
porttiavain. Agentit nakyvat sen jalkeen mallilistassa ja niiden kanssa voi keskustella suoraan.

Periaatteet (kaikki koodissa, ei agentin muokattavissa):
- Agentin ohje tulee AINA palvelimen omasta ohjetiedostosta. Asiakkaan (Open WebUI:n) system-viestit
  ja tyokalut ohitetaan, joten kukaan chatissa ei voi vaihtaa agentin ohjetta tai antaa sille oikeuksia.
- Versio 1 on keskusteluagentti ilman tyokaluja: maarityksen `tyokalut` ei anna gatewaylle mitaan.
- Oma paivabudjetti per agentti (portti-kulu.json, flock). Rikkinainen kirjanpito = kutsu estetaan.
- Pyyntojen koot rajattu, avain vertaillaan vakioaikaisesti, virheissa ei paljasteta sisaisia tietoja.
- Kuuntelee oletuksena vain 127.0.0.1; LAN-osoite annetaan tietoisesti --host-valitsimella.

Porttitiedosto (JSON): {"agentit": [{"maaritys": "agentit/tutkija.json", "budjetti_usd_paivassa": 1.0}]}
Polut ovat suhteessa porttitiedoston hakemistoon.
"""
import argparse
import hmac
import http.server
import json
import os
import sys
import time

from . import config, llm as llm_mod, maaritys
from .lukko import kirjoita_atomisesti, lukittu

# LAKI (muutos vaatii omistajan luvan ja oman commitin)
BUDJETTI_MAX_USD = 3.0           # yksittaisen agentin paivabudjetin ylaraja
VIESTEJA_MAX = 40                # viimeiset N viestia mukaan kutsuun
KONTEKSTI_MAX_MERKKEJA = 60000
OHJE_MAX_MERKKEJA = 20000
PYYNTO_MAX_TAVUA = 1_000_000
KUTSU_VARAUS_USD = 0.02          # pessimistinen varaus ennen kutsua
HINTA_ARVIO_USD_PER_M = (1.0, 4.0)   # jos mallin hintaa ei tunneta (syote, tuloste)
SAILYTYS_PAIVAA = 62
OLETUSPORTTI = 8810


class PorttiVirhe(Exception):
    pass


class Kirjanpito:
    """Agenttikohtainen paivakulu. Fail closed: rikkinainen tiedosto estaa kutsut."""

    def __init__(self, hakemisto, kello=None):
        self.polku = os.path.join(hakemisto, "portti-kulu.json")
        self.lukko = os.path.join(hakemisto, "portti-kulu.lock")
        self._kello = kello or config.nyt

    def _lue(self):
        try:
            with open(self.polku, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise PorttiVirhe("kirjanpito_rikki")
        if not isinstance(data, dict) or any(
                not isinstance(v, dict) or any(not isinstance(x, (int, float)) for x in v.values())
                for v in data.values()):
            raise PorttiVirhe("kirjanpito_rikki")
        return data

    def _kirjoita(self, data):
        avaimet = sorted(data)[-SAILYTYS_PAIVAA:]
        kirjoita_atomisesti(self.polku, json.dumps({k: data[k] for k in avaimet}, sort_keys=True, indent=1))

    def varaa(self, agentti, katto):
        """Palauttaa varauksen tai None jos paivabudjetti ei riita."""
        paiva = config.paiva(self._kello())
        with lukittu(self.lukko):
            data = self._lue()
            rivi = data.setdefault(paiva, {})
            if rivi.get(agentti, 0.0) + KUTSU_VARAUS_USD > katto:
                return None
            rivi[agentti] = round(rivi.get(agentti, 0.0) + KUTSU_VARAUS_USD, 6)
            self._kirjoita(data)
        return {"paiva": paiva, "agentti": agentti}

    def tasaa(self, varaus, todellinen):
        """Korvaa varauksen todellisella kululla. None = jaa pessimistinen varaus."""
        if todellinen is None:
            return
        with lukittu(self.lukko):
            data = self._lue()
            rivi = data.get(varaus["paiva"])
            if rivi is None or varaus["agentti"] not in rivi:
                return
            rivi[varaus["agentti"]] = round(max(0.0, rivi[varaus["agentti"]] - KUTSU_VARAUS_USD + max(0.0, todellinen)), 6)
            self._kirjoita(data)

    def tanaan(self, agentti):
        with lukittu(self.lukko):
            data = self._lue()
        return data.get(config.paiva(self._kello()), {}).get(agentti, 0.0)


class Agentti:
    def __init__(self, nimi, kuvaus, malli, ohje, max_tokens, budjetti):
        self.nimi, self.kuvaus, self.malli = nimi, kuvaus, malli
        self.ohje, self.max_tokens, self.budjetti = ohje, max_tokens, budjetti


def lataa_agentit(portti_polku):
    """Lukee porttitiedoston ja maaritykset. Nostaa PorttiVirhe selkealla viestilla."""
    try:
        with open(portti_polku, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise PorttiVirhe("porttitiedosto ei lukeudu: %s" % type(e).__name__)
    if not isinstance(data, dict) or not isinstance(data.get("agentit"), list) or not data["agentit"]:
        raise PorttiVirhe("porttitiedostossa pitaa olla ei-tyhja lista 'agentit'")
    juuri = os.path.dirname(os.path.abspath(portti_polku))
    ulos = {}
    for rivi in data["agentit"]:
        if not isinstance(rivi, dict) or set(rivi) - {"maaritys", "budjetti_usd_paivassa"} or "maaritys" not in rivi:
            raise PorttiVirhe("agenttirivi: kentat 'maaritys' ja valinnainen 'budjetti_usd_paivassa'")
        mpolku = os.path.normpath(os.path.join(juuri, str(rivi["maaritys"])))
        try:
            m = maaritys.lue(mpolku)
        except maaritys.MaaritysVirhe as e:
            raise PorttiVirhe("%s: %s" % (rivi["maaritys"], e))
        ohjepolku = os.path.normpath(os.path.join(os.path.dirname(mpolku), m["ohje_tiedosto"]))
        try:
            with open(ohjepolku, encoding="utf-8") as f:
                ohje = f.read(OHJE_MAX_MERKKEJA + 1)
        except OSError:
            raise PorttiVirhe("%s: ohjetiedostoa ei voi lukea" % m["nimi"])
        if not ohje.strip() or len(ohje) > OHJE_MAX_MERKKEJA:
            raise PorttiVirhe("%s: ohje tyhja tai yli %d merkkia" % (m["nimi"], OHJE_MAX_MERKKEJA))
        b = rivi.get("budjetti_usd_paivassa", 1.0)
        if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 < b <= BUDJETTI_MAX_USD:
            raise PorttiVirhe("%s: budjetti_usd_paivassa yli 0 ja enintaan %s (laki)" % (m["nimi"], BUDJETTI_MAX_USD))
        if m["nimi"] in ulos:
            raise PorttiVirhe("kaksi agenttia samalla nimella: %s" % m["nimi"])
        ulos[m["nimi"]] = Agentti(m["nimi"], m["kuvaus"], m["malli"], ohje, m["max_tokens"], float(b))
    return ulos


def _teksti(sisalto):
    """OpenAI-viestin content -> merkkijono. Kuvat yms. osat pudotetaan."""
    if isinstance(sisalto, str):
        return sisalto
    if isinstance(sisalto, list):
        return "\n".join(o["text"] for o in sisalto if isinstance(o, dict) and o.get("type") == "text" and isinstance(o.get("text"), str))
    return ""


def puhdista_viestit(viestit):
    """Vain user/assistant-viestit, merkkijonoina. system/tool ohitetaan. Nostaa ValueError."""
    if not isinstance(viestit, list):
        raise ValueError("messages")
    ulos = []
    for v in viestit:
        if not isinstance(v, dict) or v.get("role") not in ("user", "assistant", "system", "tool", "developer"):
            raise ValueError("messages")
        if v["role"] not in ("user", "assistant"):
            continue
        t = _teksti(v.get("content")).strip()
        if t:
            ulos.append({"role": v["role"], "content": t})
    ulos = ulos[-VIESTEJA_MAX:]
    while ulos and ulos[0]["role"] != "user":
        ulos = ulos[1:]
    if not ulos or ulos[-1]["role"] != "user":
        raise ValueError("viimeisen viestin pitaa olla user")
    while len(ulos) > 1 and sum(len(x["content"]) for x in ulos) > KONTEKSTI_MAX_MERKKEJA:
        ulos = ulos[1:]
    if sum(len(x["content"]) for x in ulos) > KONTEKSTI_MAX_MERKKEJA:
        raise ValueError("viesti liian pitka")
    return ulos


class Portti:
    def __init__(self, agentit, kirjanpito, env, avain, hae_llm=None):
        self.agentit, self.kirjanpito, self.env, self.avain = agentit, kirjanpito, env, avain
        self.hae_llm = hae_llm or llm_mod._http_post

    def malliluettelo(self):
        t = int(time.time())
        return {"object": "list", "data": [
            {"id": a.nimi, "object": "model", "created": t, "owned_by": "agentti-pohja"}
            for a in self.agentit.values()]}

    def vastaa(self, nimi, viestit):
        """Palauttaa (teksti, virhekoodi|None). Virhekoodi ei sisalla sisaisia tietoja."""
        a = self.agentit.get(nimi)
        if a is None:
            return None, "tuntematon_malli"
        try:
            hist = puhdista_viestit(viestit)
        except ValueError:
            return None, "virheelliset_viestit"
        osoite, avain = self.env.get("LLM_BASE_URL"), self.env.get("LLM_API_KEY")
        if not osoite or not avain or not osoite.startswith(("http://", "https://")):
            return None, "llm_asetus"
        try:
            varaus = self.kirjanpito.varaa(a.nimi, a.budjetti)
        except PorttiVirhe:
            return None, "kirjanpito_rikki"
        if varaus is None:
            return "Taman agentin paivabudjetti (%.2f USD) on taynna. Jatka huomenna tai pyyda omistajaa nostamaan sita." % a.budjetti, None
        payload = {"model": a.malli, "max_tokens": a.max_tokens, "temperature": 0.3,
                   "messages": [{"role": "system", "content": a.ohje}] + hist}
        try:
            v = self.hae_llm(osoite.rstrip("/") + "/chat/completions", avain, payload)
        except llm_mod.LLMVirhe as e:
            return None, e.koodi
        kaytto = v.get("usage") if isinstance(v, dict) else None
        kulu = llm_mod.arvioi_usd(kaytto, a.malli)
        if kulu is None and isinstance(kaytto, dict):
            try:
                kulu = (float(kaytto["prompt_tokens"]) * HINTA_ARVIO_USD_PER_M[0]
                        + float(kaytto["completion_tokens"]) * HINTA_ARVIO_USD_PER_M[1]) / 1_000_000
            except (KeyError, TypeError, ValueError):
                kulu = None
        try:
            self.kirjanpito.tasaa(varaus, kulu)
        except PorttiVirhe:
            pass  # pessimistinen varaus jaa voimaan
        try:
            teksti = v["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None, "llm_vastaus_rakenne"
        if not isinstance(teksti, str) or not teksti.strip():
            return None, "llm_vastaus_tyhja"
        return teksti, None


VIRHEVIESTIT = {
    "tuntematon_malli": (404, "Tuntematon agentti."),
    "virheelliset_viestit": (400, "Virheelliset viestit."),
    "kirjanpito_rikki": (503, "Kulukirjanpito ei ole kunnossa, kutsu estetty."),
}


def _kasittelija(portti):
    class K(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 30

        def log_message(self, *a):  # ei lokiteta sisaltoa
            pass

        def _json(self, koodi, data):
            runko = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(koodi)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(runko)))
            self.end_headers()
            self.wfile.write(runko)

        def _virhe(self, koodi, viesti, tyyppi="error"):
            self._json(koodi, {"error": {"message": viesti, "type": tyyppi}})

        def _auth(self):
            a = self.headers.get("Authorization", "")
            if a.startswith("Bearer ") and hmac.compare_digest(a[7:].encode(), portti.avain.encode()):
                return True
            self._virhe(401, "Virheellinen avain.", "auth")
            return False

        def do_GET(self):
            if self.path.rstrip("/") == "/v1/models":
                if self._auth():
                    self._json(200, portti.malliluettelo())
            elif self.path == "/health":
                self._json(200, {"ok": True})
            else:
                self._virhe(404, "Ei loydy.")

        def do_POST(self):
            if self.path.rstrip("/") != "/v1/chat/completions":
                return self._virhe(404, "Ei loydy.")
            if not self._auth():
                return
            try:
                pituus = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._virhe(411, "Content-Length puuttuu.")
            if not 0 < pituus <= PYYNTO_MAX_TAVUA:
                return self._virhe(413, "Pyynto liian suuri.")
            try:
                pyynto = json.loads(self.rfile.read(pituus).decode("utf-8"))
                nimi, viestit = pyynto["model"], pyynto["messages"]
            except (ValueError, KeyError, TypeError):
                return self._virhe(400, "Virheellinen pyynto.")
            teksti, virhe = portti.vastaa(nimi, viestit)
            if virhe in VIRHEVIESTIT:
                return self._virhe(*VIRHEVIESTIT[virhe])
            if virhe:
                return self._virhe(502, "Mallikutsu epaonnistui (%s)." % virhe)
            tunniste, t = "chatcmpl-%d" % int(time.time() * 1000), int(time.time())
            if pyynto.get("stream") is True:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                for delta, syy in (({"role": "assistant", "content": teksti}, None), ({}, "stop")):
                    palanen = {"id": tunniste, "object": "chat.completion.chunk", "created": t, "model": nimi,
                               "choices": [{"index": 0, "delta": delta, "finish_reason": syy}]}
                    self.wfile.write(("data: " + json.dumps(palanen, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                return
            self._json(200, {"id": tunniste, "object": "chat.completion", "created": t, "model": nimi,
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": teksti}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
    return K


def luo_palvelin(portti, host, port):
    return http.server.ThreadingHTTPServer((host, port), _kasittelija(portti))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m agentti.portti")
    p.add_argument("--config", required=True, help="porttitiedosto (JSON)")
    p.add_argument("--tila", required=True, help="tilahakemisto (kirjanpito)")
    p.add_argument("--env", required=True, help="env-tiedosto: LLM_BASE_URL, LLM_API_KEY, PORTTI_AVAIN")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=OLETUSPORTTI)
    a = p.parse_args(argv)
    try:
        env = config.lue_env(a.env)
        agentit = lataa_agentit(a.config)
    except (config.EnvVirhe, PorttiVirhe) as e:
        print("virhe:", e, file=sys.stderr)
        return 2
    avain = env.get("PORTTI_AVAIN", "")
    if len(avain) < 24:
        print("virhe: PORTTI_AVAIN puuttuu tai on alle 24 merkkia", file=sys.stderr)
        return 2
    os.makedirs(a.tila, mode=0o700, exist_ok=True)
    palvelin = luo_palvelin(Portti(agentit, Kirjanpito(a.tila), env, avain), a.host, a.port)
    print("portti kuuntelee %s:%d, agentit: %s" % (a.host, a.port, ", ".join(sorted(agentit))), flush=True)
    try:
        palvelin.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
