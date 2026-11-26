#!/usr/bin/env python3
"""Hakuvalittaja (hakukontti): ainoa reitti hakukonttiin. Vain stdlib.

Rajapinta (vain kontille 122, jaettu avain otsakkeessa Authorization: Bearer):
  Kuuntelee vain asetetussa osoitteessa (--kuuntele, ei 0.0.0.0) ja hylkaa yhteydet muista kuin sallituista
  osoitteista (--salli) jo ennen pyynnon lukemista. Palomuuri on ensimmainen raja, tama toinen.
  POST /haku {lauseke, reitti, tunnus} -> {tulokset: [{otsikko, url, ote, moottori}], estaneet: [...]}
  POST /sivu {url, reitti, tunnus}     -> {teksti, merkkeja, katkaistu, sha256, sisaltotyyppi, tila, url, ohjauksia}

Turvaperiaatteet (suunnitelma aivo-verkkohaku.md kohdat 3.3, 4 ja 8; Tonyn paatokset A1101):
- Reitti tarkistetaan ennen jokaista pyyntoa Torin hallintasoketista (status/circuit-established=1).
  Jos tarkistus epaonnistuu, vastaus on reitti_poikki. Suoraa yhteytta ei avata koskaan.
- /haku pyytaa ennen hakua uuden piirin (SIGNAL NEWNYM), koska SearXNG ei laheta SOCKS-tunnusta.
- /sivu kulkee Torin SOCKS-portin kautta (socks5h: nimi ratkaistaan Torissa, ei tassa kontissa).
  SOCKS-kayttajanimi on tunnus + jarjestysnumero, joten jokainen sivuhaku saa oman piirin (IsolateSOCKSAuth).
- Vain https ja portti 443, enintaan 3 uudelleenohjausta (jokainen tarkistetaan), raakadata enintaan 2 Mt,
  aikaraja 30 s, sallitut sisaltotyypit text/html, application/xhtml+xml ja text/plain.
- Sisalto siivotaan ennen palautusta: HTML-jasennys (script, style, piilotetut jne. pois), ohjausmerkit
  nakyviksi, [[ ]] ja <<< >>> pois, enintaan 30 000 merkkia.
- Hakulausekkeen mekaaniset salaisuustyypit estetaan aina (A1096, toinen kerros; ensisijainen tarkistus on kontissa 122).
- Lokiin vain aika (journald), toiminto, tunnus, tila, kesto, tavumaara ja virhekoodi. Ei lauseketta eika osoitetta.

Rajat ovat koodin vakioita. Konstruktorin arvot saavat vain pienentaa niita.
"""
import argparse
import codecs
import hashlib
import hmac
import html.parser
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import struct
import sys
import threading
import time
import unicodedata
import urllib.parse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- Koodin rajat (asetus saa vain pienentaa) ---
SIVU_MAX_TAVUA = 2 * 1024 * 1024
SIVU_AIKARAJA_S = 30.0
HAKU_AIKARAJA_S = 30.0
TEKSTI_MAX_MERKKIA = 30000
TULOKSIA_MAX = 10
OTE_MAX = 300
OTSIKKO_MAX = 200
MOOTTORI_MAX = 40
URL_MAX = 2048
OHJAUKSIA_MAX = 3
PYYNTO_MAX_TAVUA = 8192
LAUSEKE_MAX = 300
SEARXNG_VASTAUS_MAX = 2 * 1024 * 1024
SAMANAIKAISIA_MAX = 4
HALLINTA_AIKARAJA_S = 5.0
AVAIN_MIN_PITUUS = 32
TIEDOSTO_MAX_TAVUA = 4096
PIIRILASKURIT_MAX = 1024

SALLITUT_TYYPIT = ("text/html", "application/xhtml+xml", "text/plain")
OHJAUSKOODIT = (301, 302, 303, 307, 308)
# Kiintea, yleinen selaimen otsakejoukko kaikille hauille: otsakkeista ei synny tunnistetta.
# Ei evasteita, ei Referer-otsaketta.
OTSAKKEET = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    "Accept-Language": "en",
    "Accept-Encoding": "identity",
    "Connection": "close",
}
KIELLETYT_PAATTEET = (".onion", ".local", ".localhost", ".localdomain", ".internal", ".intranet", ".lan", ".home",
                      ".corp", ".home.arpa", ".ts.net", ".test", ".invalid", ".example", ".arpa", ".exit", ".noconnect")
SALLITUT_MERKISTOT = frozenset(("utf-8", "ascii", "iso8859-1", "iso8859-15", "cp1252", "utf-16", "utf-16-le", "utf-16-be"))
TUNNUS_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
NIMIOSA_RE = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")
NUMEROOSA_RE = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$")

# Mekaaniset salaisuustyypit (A1096: esto). Sama tarkistus koskee sivun osoitetta ilman yleista pitkan merkkijonon saantoa.
SALAISUUSKUVIOT = (
    ("avain", re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)")),
    ("avain", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("avain", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("avain", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("avain", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("avain", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("avain", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("avain", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
    ("henkilotunnus", re.compile(r"(?<![0-9A-Za-z])[0-3][0-9][01][0-9][0-9]{2}[-+ABCDEFUVWXY][0-9]{3}[0-9A-Y](?![0-9A-Za-z])")),
    ("tailnet", re.compile(r"\.ts\.net\b", re.IGNORECASE)),
)
PITKA_AVAIN_RE = re.compile(r"[A-Za-z0-9+/_=]{32,}")  # ei yhdysmerkkia: pitkat yhdyssanalausekkeet sallitaan
HEKSA_RE = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32,}(?![0-9A-Za-z])")
IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]){11,30}\b")
IPV4_RE = re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9.])")
IPV6_RE = re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![0-9A-Fa-f:])")

POISTETTAVAT_TAGIT = frozenset(("script", "style", "noscript", "iframe", "svg", "form", "nav", "template", "object",
                                "embed", "canvas", "math", "select", "button", "textarea", "dialog", "frameset"))
TYHJAT_TAGIT = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                          "source", "track", "wbr"))
LOHKOTAGIT = frozenset(("p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
                        "section", "article", "header", "footer", "main", "aside", "blockquote", "pre", "hr",
                        "dd", "dt", "dl", "figcaption", "title", "td", "th"))
PIILOTUS_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.0-9]*[1-9])", re.IGNORECASE)
KIELLETYT_JONOT = ("[[", "]]", "<<<", ">>>")


class Virhe(Exception):
    """Hallittu virhe: koodi palautetaan kutsujalle ja kirjataan lokiin. Ei sisaltoa."""

    def __init__(self, koodi, http_tila=502, **lisa):
        super().__init__(koodi)
        self.koodi = koodi
        self.http_tila = http_tila
        self.lisa = lisa


# --- Tiedostot: kaynnistystarkistus ja palvelu kayttavat samaa avausta (samat liput) ---

def lue_tiedosto(polku, maksimi=TIEDOSTO_MAX_TAVUA):
    """Lukee pienen tiedoston liputuksin O_RDONLY|O_NOFOLLOW|O_CLOEXEC. Sama funktio kaynnistystarkistuksessa ja palvelussa."""
    fd = os.open(polku, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        data = b""
        while len(data) <= maksimi:
            pala = os.read(fd, maksimi + 1 - len(data))
            if not pala:
                break
            data += pala
    finally:
        os.close(fd)
    if len(data) > maksimi:
        raise ValueError("tiedosto liian suuri")
    return data


def lue_avain(polku):
    avain = lue_tiedosto(polku).decode("ascii").strip()
    if len(avain) < AVAIN_MIN_PITUUS or any(c.isspace() for c in avain):
        raise ValueError("avain ei kelpaa")
    return avain


# --- Siivous ---

def _nakyvaksi(merkki):
    return "\\u%04x" % ord(merkki)


def siivoa_teksti(teksti, maksimi, yksirivinen=False):
    """Palauttaa (teksti, katkaistu). NFKC, ohjausmerkit nakyviksi, [[ ]] ja <<< >>> pois, valit tiivistetty.

    Teksti katkaistaan ennen ja jalkeen NFKC:n (2 x maksimi), koska NFKC voi pidentaa merkin jopa 18-kertaiseksi:
    muisti ja CPU-aika pysyvat rajattuina sivun koosta riippumatta."""
    esiraja = 2 * maksimi
    katkaistu_alussa = len(teksti) > esiraja
    teksti = unicodedata.normalize("NFKC", teksti[:esiraja])[:esiraja].replace("\r\n", "\n")
    osat = []
    for m in teksti:
        if m == "\n" or m == "\t":
            osat.append(" " if (yksirivinen or m == "\t") else "\n")
            continue
        if m == "\r":
            osat.append("\n" if not yksirivinen else " ")
            continue
        kat = unicodedata.category(m)
        if kat in ("Zl", "Zp"):
            osat.append(" " if yksirivinen else "\n")
        elif kat in ("Cc", "Cf", "Co", "Cs", "Cn"):
            osat.append(_nakyvaksi(m))
        elif kat.startswith("Z"):
            osat.append(" ")
        else:
            osat.append(m)
    teksti = "".join(osat)
    edellinen = None
    while edellinen != teksti:
        edellinen = teksti
        for jono in KIELLETYT_JONOT:
            teksti = teksti.replace(jono, "")
    rivit = [re.sub(r" {2,}", " ", r).strip() for r in teksti.split("\n")]
    teksti = re.sub(r"\n{3,}", "\n\n", "\n".join(rivit)).strip()
    if len(teksti) > maksimi:
        return teksti[:maksimi].rstrip(), True
    return teksti, katkaistu_alussa


class _Tekstiksi(html.parser.HTMLParser):
    """HTML -> teksti. Poistaa skriptit, tyylit, lomakkeet, navigaation ja piilotetut elementit."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.osat = []
        self.pino = []  # avoimet poistettavat tagit

    @staticmethod
    def _piilotettu(attrs):
        for nimi, arvo in attrs:
            nimi = (nimi or "").lower()
            arvo = arvo or ""
            if nimi == "hidden":
                return True
            if nimi == "aria-hidden" and arvo.strip().lower() == "true":
                return True
            if nimi == "style" and PIILOTUS_RE.search(arvo):
                return True
        return False

    def handle_starttag(self, tag, attrs):
        if tag in TYHJAT_TAGIT:
            if not self.pino and tag in LOHKOTAGIT:
                self.osat.append("\n")
            return
        if self.pino or tag in POISTETTAVAT_TAGIT or self._piilotettu(attrs):
            self.pino.append(tag)
            return
        if tag in LOHKOTAGIT:
            self.osat.append("\n")

    def handle_startendtag(self, tag, attrs):
        if not self.pino and tag in LOHKOTAGIT:
            self.osat.append("\n")

    def handle_endtag(self, tag):
        if self.pino:
            if tag in self.pino:
                while self.pino:
                    if self.pino.pop() == tag:
                        break
            return
        if tag in LOHKOTAGIT:
            self.osat.append("\n")

    def handle_data(self, data):
        if not self.pino:
            self.osat.append(data)


def html_tekstiksi(html_teksti):
    p = _Tekstiksi()
    try:
        p.feed(html_teksti)
        p.close()
    except Exception:  # jasennysvirhe: kaytetaan siihen asti saatu teksti
        pass
    return "".join(p.osat)


# --- Tarkistukset ---

def _iban_kelpaa(ehdokas):
    s = ehdokas.replace(" ", "")
    if not (15 <= len(s) <= 34):
        return False
    s = s[4:] + s[:4]
    numerot = "".join(str(int(c, 36)) for c in s)
    return int(numerot) % 97 == 1


def _ei_julkinen_ip(teksti):
    for ehdokas in IPV4_RE.findall(teksti) + IPV6_RE.findall(teksti):
        try:
            ip = ipaddress.ip_address(ehdokas)
        except ValueError:
            continue
        if not ip.is_global:
            return True
    return False


def salaisuustyyppi(teksti, yleinen=True):
    """Palauttaa ensimmaisen mekaanisen salaisuustyypin nimen tai None. Ei palauta osumaa itseaan."""
    for nimi, kuvio in SALAISUUSKUVIOT:
        if kuvio.search(teksti):
            return nimi
    for ehdokas in IBAN_RE.findall(teksti):
        if _iban_kelpaa(ehdokas):
            return "iban"
    if _ei_julkinen_ip(teksti):
        return "yksityinen_ip"
    if yleinen:
        if HEKSA_RE.search(teksti):
            return "avain"
        for ehdokas in PITKA_AVAIN_RE.findall(teksti):
            if re.search(r"[0-9]", ehdokas) and re.search(r"[a-z]", ehdokas) and re.search(r"[A-Z]", ehdokas):
                return "avain"
    return None


def tarkista_tunnus(tunnus):
    if not isinstance(tunnus, str) or not TUNNUS_RE.match(tunnus):
        raise Virhe("tunnus_ei_kelpaa", 400)
    return tunnus


def tarkista_reitti(reitti):
    if reitti is None or reitti == "tor":
        return "tor"
    if reitti == "vpn":
        raise Virhe("reitti_ei_kaytossa", 400)
    raise Virhe("reitti_tuntematon", 400)


def tarkista_lauseke(lauseke):
    if not isinstance(lauseke, str):
        raise Virhe("lauseke_puuttuu", 400)
    lauseke = lauseke.strip()
    if not lauseke:
        raise Virhe("lauseke_puuttuu", 400)
    if len(lauseke) > LAUSEKE_MAX:
        raise Virhe("lauseke_liian_pitka", 400)
    if any(unicodedata.category(m) in ("Cc", "Cf") for m in lauseke):
        raise Virhe("lauseke_ohjausmerkki", 400)
    tyyppi = salaisuustyyppi(unicodedata.normalize("NFKC", lauseke))
    if tyyppi:
        raise Virhe("lauseke_estetty", 400, tyyppi=tyyppi)
    return lauseke


def tarkista_url(url):
    """Palauttaa (isanta, portti, polku, normalisoitu_url). Hylkaa kaiken paitsi julkisen https-osoitteen portissa 443."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        raise Virhe("url_ei_kelpaa", 400)
    if any(ord(m) <= 0x20 or ord(m) == 0x7F or unicodedata.category(m) in ("Cc", "Cf") for m in url):
        raise Virhe("url_ei_kelpaa", 400)
    try:
        osat = urllib.parse.urlsplit(url)
    except ValueError:
        raise Virhe("url_ei_kelpaa", 400)
    if osat.scheme.lower() != "https":
        raise Virhe("vain_https", 403)
    if "@" in osat.netloc or osat.username is not None or osat.password is not None:
        raise Virhe("url_ei_sallittu", 403)
    try:
        portti = osat.port
    except ValueError:
        raise Virhe("url_ei_kelpaa", 400)
    if portti not in (None, 443):
        raise Virhe("portti_ei_sallittu", 403)
    isanta = (osat.hostname or "").rstrip(".")
    if not isanta:
        raise Virhe("url_ei_kelpaa", 400)
    try:
        ip = ipaddress.ip_address(isanta)
    except ValueError:
        ip = None
    if ip is not None:
        mapattu = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or ip.is_multicast or (mapattu is not None and not mapattu.is_global):
            raise Virhe("osoite_ei_sallittu", 403)
        isanta_ascii = ip.compressed
        netloc = "[%s]" % isanta_ascii if ip.version == 6 else isanta_ascii
    else:
        try:
            isanta_ascii = isanta.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError):
            raise Virhe("url_ei_kelpaa", 400)
        osiot = isanta_ascii.split(".")
        if len(isanta_ascii) > 253 or any(not NIMIOSA_RE.match(o) for o in osiot):
            raise Virhe("url_ei_kelpaa", 400)
        if len(osiot) < 2 or isanta_ascii == "localhost":
            raise Virhe("osoite_ei_sallittu", 403)
        if all(NUMEROOSA_RE.match(o) for o in osiot) or osiot[-1].isdigit():
            raise Virhe("osoite_ei_sallittu", 403)
        paate = "." + isanta_ascii
        if any(paate.endswith(k) for k in KIELLETYT_PAATTEET):
            raise Virhe("osoite_ei_sallittu", 403)
        netloc = isanta_ascii
    polku = urllib.parse.quote(osat.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if osat.query:
        polku += "?" + urllib.parse.quote(osat.query, safe="/%:@!$&'()*+,;=-._~?")
    normalisoitu = "https://" + netloc + polku
    tyyppi = salaisuustyyppi(unicodedata.normalize("NFKC", urllib.parse.unquote(normalisoitu)), yleinen=False)
    if tyyppi:
        raise Virhe("url_estetty", 403, tyyppi=tyyppi)
    return isanta_ascii, 443, polku, normalisoitu


def _silmukka_osoite(isanta):
    try:
        return ipaddress.ip_address(isanta).is_loopback
    except ValueError:
        return False


# --- Tor: hallintasoketti (reitin tarkistus ja uusi piiri) ---

class TorReitti:
    def __init__(self, soketti="/run/tor/control", evaste="/run/tor/control.authcookie", aikaraja=HALLINTA_AIKARAJA_S):
        self.soketti = soketti
        self.evaste = evaste
        self.aikaraja = min(aikaraja, HALLINTA_AIKARAJA_S)

    @staticmethod
    def _vastaus(tiedosto):
        rivit = []
        while True:
            rivi = tiedosto.readline(4096)
            if not rivi:
                raise Virhe("reitti_poikki", 503)
            rivi = rivi.decode("ascii", "replace").rstrip("\r\n")
            rivit.append(rivi)
            if len(rivi) >= 4 and rivi[3] == " ":
                return rivit
            if len(rivit) > 50:
                raise Virhe("reitti_poikki", 503)

    def _komento(self, s, f, komento):
        s.sendall(komento.encode("ascii") + b"\r\n")
        rivit = self._vastaus(f)
        if not rivit[-1].startswith("250"):
            raise Virhe("reitti_poikki", 503)
        return rivit

    def tarkista(self, vaadi_piiri=True, uusi_piiri=False):
        """Tunnistautuu evasteella. vaadi_piiri: status/circuit-established=1. uusi_piiri: SIGNAL NEWNYM."""
        try:
            evaste = lue_tiedosto(self.evaste, 64)
            if len(evaste) != 32:
                raise Virhe("reitti_poikki", 503)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.aikaraja)
                s.connect(self.soketti)
                with s.makefile("rb") as f:
                    self._komento(s, f, "AUTHENTICATE " + evaste.hex())
                    if vaadi_piiri:
                        rivit = self._komento(s, f, "GETINFO status/circuit-established")
                        if "250-status/circuit-established=1" not in rivit:
                            raise Virhe("reitti_poikki", 503)
                    if uusi_piiri:
                        self._komento(s, f, "SIGNAL NEWNYM")
                    try:
                        s.sendall(b"QUIT\r\n")
                    except OSError:
                        pass
        except Virhe:
            raise
        except (OSError, ValueError):
            raise Virhe("reitti_poikki", 503)


# --- SOCKS5 (socks5h): nimi lahetetaan Torille, ei ratkaista tassa ---

SOCKS_VIRHEET = {1: "sivu_ei_saatavilla", 2: "sivu_ei_saatavilla", 3: "sivu_ei_saatavilla", 4: "sivu_ei_saatavilla",
                 5: "sivu_ei_saatavilla", 6: "aikaraja", 7: "reitti_poikki", 8: "reitti_poikki"}


def _lue_tasan(s, n):
    data = b""
    while len(data) < n:
        pala = s.recv(n - len(data))
        if not pala:
            raise Virhe("reitti_poikki", 503)
        data += pala
    return data


def socks5_yhteys(socks, isanta, portti, kayttaja, salasana, aikaraja):
    """Avaa TCP-yhteyden SOCKS5-palvelimen kautta. socks on (osoite, portti) silmukassa."""
    try:
        s = socket.create_connection(socks, timeout=aikaraja)
    except socket.timeout:
        raise Virhe("reitti_poikki", 503)
    except OSError:
        raise Virhe("reitti_poikki", 503)
    try:
        s.sendall(b"\x05\x01\x02")
        if _lue_tasan(s, 2) != b"\x05\x02":
            raise Virhe("reitti_poikki", 503)
        k = kayttaja.encode("ascii")
        p = salasana.encode("ascii")
        s.sendall(b"\x01" + bytes([len(k)]) + k + bytes([len(p)]) + p)
        if _lue_tasan(s, 2)[1] != 0:
            raise Virhe("reitti_poikki", 503)
        nimi = isanta.encode("ascii")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(nimi)]) + nimi + struct.pack(">H", portti))
        alku = _lue_tasan(s, 4)
        if alku[0] != 5:
            raise Virhe("reitti_poikki", 503)
        if alku[1] != 0:
            raise Virhe(SOCKS_VIRHEET.get(alku[1], "sivu_ei_saatavilla"), 504 if alku[1] == 6 else 502)
        if alku[3] == 1:
            _lue_tasan(s, 4 + 2)
        elif alku[3] == 4:
            _lue_tasan(s, 16 + 2)
        elif alku[3] == 3:
            _lue_tasan(s, _lue_tasan(s, 1)[0] + 2)
        else:
            raise Virhe("reitti_poikki", 503)
        return s
    except Virhe:
        s.close()
        raise
    except socket.timeout:
        s.close()
        raise Virhe("aikaraja", 504)
    except OSError:
        s.close()
        raise Virhe("reitti_poikki", 503)


def tls_kaari(raaka, isanta):
    """Varmenne tarkistetaan aina (oletuskonteksti), vahintaan TLS 1.2."""
    konteksti = ssl.create_default_context()
    konteksti.minimum_version = ssl.TLSVersion.TLSv1_2
    return konteksti.wrap_socket(raaka, server_hostname=isanta)


class _ValmisYhteys(http.client.HTTPConnection):
    """HTTP-yhteys valmiiseen sokettiin (SOCKS + TLS). Host-otsake ilman porttia 443."""
    default_port = 443

    def __init__(self, isanta, avaaja, aikaraja):
        super().__init__(isanta, 443, timeout=aikaraja)
        self._avaaja = avaaja

    def connect(self):
        self.sock = self._avaaja()


# --- Valittaja ---

class Valittaja:
    def __init__(self, avain, reitti, searxng="http://127.0.0.1:8888", socks=("127.0.0.1", 9050), kaari=tls_kaari,
                 loki=None, sivu_max=SIVU_MAX_TAVUA, sivu_aikaraja=SIVU_AIKARAJA_S, haku_aikaraja=HAKU_AIKARAJA_S,
                 teksti_max=TEKSTI_MAX_MERKKIA):
        if not isinstance(avain, str) or len(avain) < AVAIN_MIN_PITUUS:
            raise ValueError("avain ei kelpaa")
        osat = urllib.parse.urlsplit(searxng)
        if osat.scheme != "http" or not _silmukka_osoite(osat.hostname or ""):
            raise ValueError("searxng vain silmukkaosoitteessa")
        if not _silmukka_osoite(socks[0]):
            raise ValueError("socks vain silmukkaosoitteessa")
        self._avain = avain.encode("ascii")
        self.reitti = reitti
        self.searxng = searxng.rstrip("/")
        self._searxng_isanta = osat.hostname
        self._searxng_portti = osat.port or 80
        self._searxng_polku = osat.path.rstrip("/")
        self.socks = (socks[0], int(socks[1]))
        self.kaari = kaari
        self.loki = loki if loki is not None else sys.stderr
        self.sivu_max = min(int(sivu_max), SIVU_MAX_TAVUA)
        self.sivu_aikaraja = min(float(sivu_aikaraja), SIVU_AIKARAJA_S)
        self.haku_aikaraja = min(float(haku_aikaraja), HAKU_AIKARAJA_S)
        self.teksti_max = min(int(teksti_max), TEKSTI_MAX_MERKKIA)
        self._laskurit = OrderedDict()
        self._suola = secrets.token_hex(6)  # prosessikohtainen: uudelleenkaynnistys ei kierrata vanhoja SOCKS-nimia
        self._lukko = threading.Lock()
        self._lokilukko = threading.Lock()
        self.vapaat = threading.BoundedSemaphore(SAMANAIKAISIA_MAX)

    def tunnistus_ok(self, otsake):
        if not otsake or not otsake.startswith("Bearer "):
            return False
        try:
            annettu = otsake[7:].strip().encode("ascii")
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(annettu, self._avain)

    def kirjaa(self, **kentat):
        rivi = json.dumps(kentat, ensure_ascii=True, sort_keys=True)
        with self._lokilukko:
            self.loki.write(rivi + "\n")
            self.loki.flush()

    def _piiri(self, tunnus):
        with self._lukko:
            n = self._laskurit.pop(tunnus, 0) + 1
            self._laskurit[tunnus] = n
            while len(self._laskurit) > PIIRILASKURIT_MAX:
                self._laskurit.popitem(last=False)
        return "%s-%s-%d" % (tunnus, self._suola, n)

    # /haku
    def haku(self, pyynto):
        tunnus = tarkista_tunnus(pyynto.get("tunnus"))
        tarkista_reitti(pyynto.get("reitti"))
        lauseke = tarkista_lauseke(pyynto.get("lauseke"))
        self.reitti.tarkista(vaadi_piiri=True, uusi_piiri=True)
        kysely = urllib.parse.urlencode({"q": lauseke, "format": "json"})
        # http.client suoraan: ei uudelleenohjausten seurantaa eika muita protokollia (urllib seuraisi 3xx-vastauksia).
        yhteys = http.client.HTTPConnection(self._searxng_isanta, self._searxng_portti, timeout=self.haku_aikaraja)
        try:
            yhteys.request("GET", self._searxng_polku + "/search?" + kysely, headers={"Accept": "application/json"})
            v = yhteys.getresponse()
            if v.status != 200:
                raise Virhe("searxng_virhe", 502)
            data = v.read(SEARXNG_VASTAUS_MAX + 1)
        except Virhe:
            raise
        except socket.timeout:
            raise Virhe("aikaraja", 504)
        except (OSError, http.client.HTTPException):
            raise Virhe("searxng_virhe", 502)
        finally:
            yhteys.close()
        if len(data) > SEARXNG_VASTAUS_MAX:
            raise Virhe("searxng_vastaus_liian_suuri", 502)
        try:
            vastaus = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Virhe("searxng_virhe", 502)
        if not isinstance(vastaus, dict):
            raise Virhe("searxng_virhe", 502)
        tulokset = []
        for t in vastaus.get("results") or []:
            if len(tulokset) >= TULOKSIA_MAX:
                break
            if not isinstance(t, dict) or not isinstance(t.get("url"), str):
                continue
            try:
                _, _, _, url = tarkista_url(t["url"])
            except Virhe:
                continue
            otsikko, _ = siivoa_teksti(str(t.get("title") or ""), OTSIKKO_MAX, yksirivinen=True)
            ote, _ = siivoa_teksti(str(t.get("content") or ""), OTE_MAX, yksirivinen=True)
            tulokset.append({"otsikko": otsikko, "url": url, "ote": ote, "moottori": _moottori(t.get("engine"))})
        estaneet = []
        for e in vastaus.get("unresponsive_engines") or []:
            nimi = e[0] if isinstance(e, (list, tuple)) and e else e
            nimi = _moottori(nimi)
            if nimi and nimi not in estaneet:
                estaneet.append(nimi)
        return tunnus, {"tulokset": tulokset, "estaneet": estaneet[:50]}, len(data)

    # /sivu
    def sivu(self, pyynto):
        tunnus = tarkista_tunnus(pyynto.get("tunnus"))
        tarkista_reitti(pyynto.get("reitti"))
        nyky = pyynto.get("url")
        tarkista_url(nyky)  # hylkaa ennen reitin tarkistusta: kielletty osoite ei avaa mitaan
        kayttaja = self._piiri(tunnus)
        takaraja = time.monotonic() + self.sivu_aikaraja
        for ohjaus in range(OHJAUKSIA_MAX + 1):
            isanta, portti, polku, nyky = tarkista_url(nyky)
            self.reitti.tarkista(vaadi_piiri=True, uusi_piiri=False)  # ennen jokaista pyyntoa, myos ohjausten jalkeen
            tila, sijainti, tulos = self._yksi_haku(isanta, portti, polku, kayttaja, takaraja)
            if tila in OHJAUSKOODIT:
                if not sijainti:
                    raise Virhe("ohjaus_ilman_kohdetta", 502)
                if ohjaus >= OHJAUKSIA_MAX:
                    raise Virhe("liian_monta_ohjausta", 502)
                nyky = urllib.parse.urljoin(nyky, sijainti.strip())
                continue
            tulos["url"] = nyky
            tulos["ohjauksia"] = ohjaus
            return tunnus, tulos, tulos.pop("_tavuja")
        raise Virhe("liian_monta_ohjausta", 502)

    def _jaljella(self, takaraja):
        jaljella = takaraja - time.monotonic()
        if jaljella <= 0:
            raise Virhe("aikaraja", 504)
        return jaljella

    def _yksi_haku(self, isanta, portti, polku, kayttaja, takaraja):
        ajastimet = []
        laukesi = threading.Event()

        def avaa():
            raaka = socks5_yhteys(self.socks, isanta, portti, kayttaja, "x", self._jaljella(takaraja))
            # Kokonaisaikaraja: soketin aikakatkaisu koskee vain yksittaista operaatiota, joten hidas lahettaja
            # (tavu kerrallaan otsakkeissa, TLS-kattelyssa tai chunked-riveilla) katkaistaan ajastimella.
            ajastin = threading.Timer(max(0.0, takaraja - time.monotonic()), _katkaise, args=(raaka, laukesi))
            ajastin.daemon = True
            ajastin.start()
            ajastimet.append(ajastin)
            try:
                return self.kaari(raaka, isanta)
            except ssl.SSLError:
                raaka.close()
                raise Virhe("tls_virhe", 502)
            except socket.timeout:
                raaka.close()
                raise Virhe("aikaraja", 504)
            except OSError:
                raaka.close()
                raise Virhe("aikaraja", 504) if time.monotonic() >= takaraja else Virhe("sivu_ei_saatavilla", 502)

        yhteys = _ValmisYhteys(isanta, avaa, self._jaljella(takaraja))
        try:
            return self._yksi_haku_yhteys(yhteys, polku, takaraja, laukesi)
        finally:
            for a in ajastimet:
                a.cancel()
            yhteys.close()

    def _yksi_haku_yhteys(self, yhteys, polku, takaraja, laukesi):
        try:
            yhteys.request("GET", polku, headers=dict(OTSAKKEET))
            vastaus = yhteys.getresponse()
        except Virhe:
            raise
        except socket.timeout:
            raise Virhe("aikaraja", 504)
        except (OSError, http.client.HTTPException):
            if time.monotonic() >= takaraja:
                raise Virhe("aikaraja", 504)
            raise Virhe("sivu_ei_saatavilla", 502)
        if laukesi.is_set():  # ajastin katkaisi yhteyden kesken otsakkeiden: EOF ei ole oikea vastaus
            raise Virhe("aikaraja", 504)
        tila = vastaus.status
        if tila in OHJAUSKOODIT:
            return tila, vastaus.getheader("Location"), None
        if tila != 200:
            raise Virhe("http_tila", 502, tila=tila)
        # Raakaotsake: get_content_type() palauttaisi puuttuvalle tai virheelliselle otsakkeelle text/plain.
        tyyppi = (vastaus.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if tyyppi not in SALLITUT_TYYPIT:
            raise Virhe("sisaltotyyppi_ei_sallittu", 502)
        pakkaus = (vastaus.getheader("Content-Encoding") or "identity").strip().lower()
        if pakkaus != "identity":
            raise Virhe("pakkaus_ei_tuettu", 502)
        ilmoitettu = vastaus.getheader("Content-Length")
        if ilmoitettu and ilmoitettu.strip().isdigit() and int(ilmoitettu) > self.sivu_max:
            raise Virhe("liian_suuri", 502)
        raaka, katkaistu_raaka = self._lue(yhteys, vastaus, takaraja)
        if laukesi.is_set():
            raise Virhe("aikaraja", 504)
        merkisto = _merkisto(vastaus.headers.get_content_charset(), raaka if tyyppi != "text/plain" else b"")
        teksti = raaka.decode(merkisto, "replace")
        self._jaljella(takaraja)
        if tyyppi != "text/plain":
            teksti = html_tekstiksi(teksti)
        self._jaljella(takaraja)
        teksti, katkaistu = siivoa_teksti(teksti, self.teksti_max)
        return tila, None, {"teksti": teksti, "merkkeja": len(teksti), "katkaistu": katkaistu or katkaistu_raaka,
                            "sha256": hashlib.sha256(raaka).hexdigest(), "sisaltotyyppi": tyyppi, "tila": tila,
                            "_tavuja": len(raaka)}

    def _lue(self, yhteys, vastaus, takaraja):
        osat = []
        maara = 0
        while True:
            if yhteys.sock is not None:
                yhteys.sock.settimeout(self._jaljella(takaraja))
            else:
                self._jaljella(takaraja)
            try:
                pala = vastaus.read1(min(65536, self.sivu_max + 1 - maara))  # read1: ei odota koko puskuria
            except socket.timeout:
                raise Virhe("aikaraja", 504)
            except (OSError, http.client.HTTPException, ValueError):
                if time.monotonic() >= takaraja:
                    raise Virhe("aikaraja", 504)
                raise Virhe("sivu_ei_saatavilla", 502)
            if not pala:
                return b"".join(osat), False
            osat.append(pala)
            maara += len(pala)
            if maara > self.sivu_max:
                return b"".join(osat)[:self.sivu_max], True


def _katkaise(soketti, laukesi):
    laukesi.set()
    try:
        soketti.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _moottori(nimi):
    if not isinstance(nimi, str):
        return ""
    nimi = re.sub(r"[^a-z0-9 _.-]", "", nimi.lower())
    return nimi[:MOOTTORI_MAX]


def _merkisto(otsakkeesta, alku):
    ehdokas = otsakkeesta
    if not ehdokas and alku:
        m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]{1,40})", alku[:4096], re.IGNORECASE)
        if m:
            ehdokas = m.group(1).decode("ascii")
    try:
        nimi = codecs.lookup(ehdokas).name if ehdokas else "utf-8"
    except LookupError:
        return "utf-8"
    return nimi if nimi in SALLITUT_MERKISTOT else "utf-8"


# --- HTTP-palvelin ---

def tee_kasittelija(valittaja):
    class Kasittelija(BaseHTTPRequestHandler):
        server_version = "hakuvalittaja"
        sys_version = ""
        protocol_version = "HTTP/1.1"
        timeout = 10  # hidas lahettaja ei pida yhteytta auki

        def log_message(self, *args):  # ei oletuspaasylokia
            pass

        def _laheta(self, tila, runko):
            data = json.dumps(runko, ensure_ascii=False).encode("utf-8")
            self.close_connection = True
            try:
                self.send_response(tila)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            except OSError:  # asiakas katkaisi yhteyden: ei tracebackia
                pass

        def _ei_sallittu(self):
            self._laheta(405, {"virhe": "metodi_ei_sallittu"})

        do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = _ei_sallittu

        def do_POST(self):
            alku = time.monotonic()
            toiminto = {"/haku": "haku", "/sivu": "sivu"}.get(self.path)
            tunnus = None
            tila, virhe, tavuja = 200, None, 0
            try:
                if toiminto is None:
                    raise Virhe("tuntematon_polku", 404)
                if not valittaja.tunnistus_ok(self.headers.get("Authorization")):
                    raise Virhe("tunnistus", 401)
                pituus = self.headers.get("Content-Length", "")
                if not pituus.isdigit():
                    raise Virhe("pituus_puuttuu", 411)
                if int(pituus) > PYYNTO_MAX_TAVUA:
                    raise Virhe("pyynto_liian_suuri", 413)
                if (self.headers.get_content_type() or "") != "application/json":
                    raise Virhe("vain_json", 415)
                try:
                    pyynto = json.loads(self.rfile.read(int(pituus)).decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise Virhe("json_ei_kelpaa", 400)
                if not isinstance(pyynto, dict):
                    raise Virhe("json_ei_kelpaa", 400)
                if isinstance(pyynto.get("tunnus"), str) and TUNNUS_RE.match(pyynto["tunnus"]):
                    tunnus = pyynto["tunnus"]
                if not valittaja.vapaat.acquire(blocking=False):
                    raise Virhe("kiireinen", 503)
                try:
                    if toiminto == "haku":
                        tunnus, runko, tavuja = valittaja.haku(pyynto)
                    else:
                        tunnus, runko, tavuja = valittaja.sivu(pyynto)
                finally:
                    valittaja.vapaat.release()
            except Virhe as v:
                tila, virhe = v.http_tila, v.koodi
                runko = {"virhe": v.koodi}
                runko.update(v.lisa)
            except Exception as e:  # odottamaton: vain tyypin nimi
                tila, virhe = 500, "sisainen:" + type(e).__name__
                runko = {"virhe": "sisainen"}
            # Lokirivi ennen vastausta: rivi on kirjattu, kun kutsuja saa vastauksen.
            valittaja.kirjaa(toiminto=toiminto or "tuntematon", tunnus=tunnus, tila=tila, virhe=virhe,
                             kesto_ms=int((time.monotonic() - alku) * 1000), tavuja=tavuja)
            self._laheta(tila, runko)

    return Kasittelija


def _osoite(teksti):
    isanta, _, portti = teksti.rpartition(":")
    return isanta.strip("[]"), int(portti)


def _ip(teksti):
    """IP-literaali ilman jokerimerkkia ja monilahetysta. Nimia ei hyvaksyta (ei nimipalvelua)."""
    ip = ipaddress.ip_address(teksti)
    if ip.is_unspecified or ip.is_multicast:
        raise ValueError("osoite ei kelpaa")
    return ip


def kuunteluosoite(teksti):
    """--kuuntele IP:PORTTI -> (ip, portti). 0.0.0.0, :: ja nimet hylataan."""
    if not isinstance(teksti, str) or not teksti:
        raise ValueError("kuunteluosoite puuttuu")
    isanta, portti = _osoite(teksti)
    if not 0 < portti < 65536:
        raise ValueError("portti ei kelpaa")
    return _ip(isanta).compressed, portti


def sallitut_osoitteet(teksti):
    """--salli A[,B...] -> frozenset normalisoituja IP-osoitteita. Tyhja lista, verkot ja nimet hylataan."""
    if not isinstance(teksti, str):
        raise ValueError("sallitut puuttuvat")
    osat = [o.strip() for o in teksti.split(",") if o.strip()]
    if not osat:
        raise ValueError("sallitut puuttuvat")
    return frozenset(_ip(o).compressed for o in osat)


def asiakkaan_osoite(osoite):
    """Normalisoi asiakkaan osoitteen vertailua varten (IPv4-mapattu IPv6 -> IPv4). Kelvoton -> None."""
    try:
        ip = ipaddress.ip_address(str(osoite).split("%", 1)[0])
    except ValueError:
        return None
    mapattu = getattr(ip, "ipv4_mapped", None)
    return (mapattu or ip).compressed


class Palvelin(ThreadingHTTPServer):
    """HTTP-palvelin, joka kuuntelee vain yhdessa osoitteessa ja palvelee vain sallittuja asiakasosoitteita."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, osoite, kasittelija, sallitut, kirjaa=None):
        isanta, portti = osoite
        ip = _ip(isanta)  # 0.0.0.0, ::, tyhja ja nimet -> ValueError
        if not sallitut:
            raise ValueError("sallitut puuttuvat")
        self.sallitut = frozenset(_ip(o).compressed for o in sallitut)
        self._kirjaa = kirjaa
        if ip.version == 6:
            self.address_family = socket.AF_INET6
        super().__init__((ip.compressed, portti), kasittelija)

    def verify_request(self, request, client_address):
        """Muu kuin sallittu osoite: yhteys suljetaan ilman vastausta ja ennen kuin pyyntoa luetaan."""
        if asiakkaan_osoite(client_address[0]) in self.sallitut:
            return True
        rivi = dict(toiminto="hylatty_osoite", tunnus=None, tila=0, virhe="osoite_ei_sallittu", kesto_ms=0, tavuja=0)
        if self._kirjaa is not None:
            self._kirjaa(**rivi)  # ei asiakkaan osoitetta lokiin
        else:
            sys.stderr.write(json.dumps(rivi, sort_keys=True) + "\n")
        return False

    def handle_error(self, request, client_address):
        """Ei tracebackia lokiin (voisi sisaltaa dataa): vain poikkeuksen tyyppi."""
        tyyppi = type(sys.exc_info()[1]).__name__
        sys.stderr.write(json.dumps({"toiminto": "kasittelyvirhe", "virhe": tyyppi}) + "\n")


def kaynnistystarkistus(args, tuloste=None):
    """Avaa avaimen ja evasteen samoin liputuksin kuin palvelu ja tunnistautuu hallintasokettiin. Ei vaadi piiria."""
    tuloste = tuloste if tuloste is not None else sys.stdout
    vaihe = "osoitteet"
    try:
        if args.kuuntele is not None or args.salli is not None:
            kuunteluosoite(args.kuuntele)
            sallitut_osoitteet(args.salli)
        vaihe = "avain"
        lue_avain(args.avain)
        vaihe = "evaste"
        if len(lue_tiedosto(args.tor_evaste, 64)) != 32:
            raise ValueError("evaste ei kelpaa")
        vaihe = "hallinta"
        TorReitti(args.tor_hallinta, args.tor_evaste).tarkista(vaadi_piiri=False)
    except Virhe as v:
        tuloste.write("TARKISTUS: VIRHE %s %s\n" % (vaihe, v.koodi))
        return 1
    except Exception as e:
        tuloste.write("TARKISTUS: VIRHE %s %s\n" % (vaihe, type(e).__name__))
        return 1
    tuloste.write("TARKISTUS: OK\n")
    return 0


def koe(args, tuloste=None, valittaja=None):
    """Kayttoonoton koekutsu samassa prosessissa (ei HTTP:ta): palvelu ei palvele kontin omaa osoitetta.
    Tulostaa vain tilan ja maarat, ei sisaltoa eika avainta."""
    tuloste = tuloste if tuloste is not None else sys.stdout
    toiminto, arvo = args.koe
    if toiminto not in ("haku", "sivu"):
        tuloste.write("KOE: tuntematon toiminto (haku tai sivu)\n")
        return 2
    if valittaja is None:
        try:
            avain = lue_avain(args.avain)
        except Exception as e:
            tuloste.write("KOE %s: avain %s\n" % (toiminto, type(e).__name__))
            return 1
        try:
            valittaja = Valittaja(avain, TorReitti(args.tor_hallinta, args.tor_evaste), searxng=args.searxng,
                                  socks=_osoite(args.socks))
        except Exception as e:
            tuloste.write("KOE %s: asetus %s\n" % (toiminto, type(e).__name__))
            return 1
    runko = {"tunnus": "kayttoonotto-koe", "reitti": "tor", ("lauseke" if toiminto == "haku" else "url"): arvo}
    try:
        _, vastaus, _ = (valittaja.haku if toiminto == "haku" else valittaja.sivu)(runko)
        tila = 200
    except Virhe as v:
        tila, vastaus = v.http_tila, {"virhe": v.koodi}
    except Exception as e:
        tuloste.write("KOE %s: sisainen %s\n" % (toiminto, type(e).__name__))
        return 1
    if tila != 200:
        tuloste.write("KOE %s: tila %d, virhe %s\n" % (toiminto, tila, vastaus.get("virhe")))
        return 1
    if toiminto == "haku":
        tuloste.write("KOE haku: tila 200, tuloksia %d, estaneet %d\n" % (len(vastaus.get("tulokset", [])),
                                                                         len(vastaus.get("estaneet", []))))
    else:
        tuloste.write("KOE sivu: tila 200, http %s, merkkeja %s, katkaistu %s, ohjauksia %s\n" % (
            vastaus.get("tila"), vastaus.get("merkkeja"), vastaus.get("katkaistu"), vastaus.get("ohjauksia")))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hakuvalittaja (hakukontti)")
    ap.add_argument("--kuuntele", help="pakollinen: kontin oma sisaverkon osoite ja portti (IP:PORTTI), ei 0.0.0.0")
    ap.add_argument("--salli", help="pakollinen: sallitut asiakasosoitteet pilkuin eroteltuna (Aivon kontti)")
    ap.add_argument("--avain", default="/etc/aivo-haku/avain")
    ap.add_argument("--searxng", default="http://127.0.0.1:8888")
    ap.add_argument("--socks", default="127.0.0.1:9050")
    ap.add_argument("--tor-hallinta", default="/run/tor/control")
    ap.add_argument("--tor-evaste", default="/run/tor/control.authcookie")
    ap.add_argument("--tarkista", action="store_true", help="kaynnistystarkistus: avain ja Torin hallintasoketti")
    ap.add_argument("--koe", nargs=2, metavar=("TOIMINTO", "ARVO"),
                    help="kayttoonoton koekutsu paikalliseen valittajaan: haku LAUSEKE tai sivu URL")
    args = ap.parse_args(argv)
    if args.koe:
        return koe(args)
    if args.tarkista:
        return kaynnistystarkistus(args)
    try:
        avain = lue_avain(args.avain)
        osoite = kuunteluosoite(args.kuuntele)
        sallitut = sallitut_osoitteet(args.salli)
        valittaja = Valittaja(avain, TorReitti(args.tor_hallinta, args.tor_evaste), searxng=args.searxng,
                              socks=_osoite(args.socks))
        palvelin = Palvelin(osoite, tee_kasittelija(valittaja), sallitut, kirjaa=valittaja.kirjaa)
    except Exception as e:
        sys.stderr.write("hakuvalittaja: kaynnistys epaonnistui: %s\n" % type(e).__name__)
        return 1
    valittaja.kirjaa(toiminto="kaynnistys", tunnus=None, tila=0, virhe=None, kesto_ms=0, tavuja=0)
    try:
        palvelin.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        palvelin.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
