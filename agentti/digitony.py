"""Digi-Tony, varjotila: arvaa Tonyn vastauksen paatoskysymykseen, mutta ei toimi itse.

Varjotila saa kysymyksen ja vaihtoehdot, ja palauttaa arvauksen, perustelun ja varmuuden
paatosmuistin perusteella. Se ei tee mitaan: ei verkkoa, ei LLM:aa, ei komentoja eika
kirjoituksia muualle kuin omaan arvauslokiinsa. Kysymysteksti on aina pelkkaa dataa
(ei ohjeita), joten sen sisalto ei voi muuttaa toimintaa.

Rahapaatokset (luokka "raha") ohjataan aina Tonylle; niita ei arvata.

Paatosmuisti ja arvausloki ovat yksityista dataa, jota ei koskaan vieda julkiseen repoon.
Tama moduuli tuntee vain tiedostopolut, joita kayttaja antaa. Esimerkkidata: docs/digitony-esimerkki.jsonl.
"""

import json
import math
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

RAHA_LUOKKA = "raha"
LUOKAT = ("julkaisu", "raha", "oikeudet", "kulut", "tyonvalinta", "laatu", "tietoturva", "savy", "muu")
# Muistin luokat voivat olla kirjoitettu aakkosin (a, o); verrataan normalisoituna.
VARMUUS_KYNNYS = 0.25        # alle taman: "en tieda"
NAAPURIT_MAX = 5
NAAPURI_SIM_MIN = 0.15
PRIORI_PAINO = 1.0           # luokan kylla-osuuden paino kylla/ei-kysymyksissa (ei viritetty datalla)
PAKOLLISET_KENTAT = ("id", "paiva", "kysymys", "vaihtoehdot", "valittu", "luokka")

# Luokan tunnistus kysymyksesta, jos luokkaa ei anneta. Avainsanat ovat varttuneita juuria.
LUOKKA_SANAT = {
    "raha": ("oikea raha", "oikeaan rahaan", "kulukatt", "osto", "ostet", "maksu", "salkku", "sijoit"),
    "kulut": ("kulu", "budjet", "usd", "kuukausikatto", "paivakatto"),
    "oikeudet": ("oikeu", "sudo", "merge", "automerge", "polkuraj", "lupa", "repot", "tunnus"),
    "tietoturva": ("salaisu", "avain", "token", "tietoturv", "eristet", "hiekkalaat", "varmuuskop", "salat"),
    "julkaisu": ("julkais", "linkedin", "npm", "readme", "portfolio", "postau", "luonnos"),
    "laatu": ("tarkasta", "testi", "todenn", "virhe", "laatu", "faktan"),
    "savy": ("savy", "huumori", "kehu", "lopetus", "teksti", "aanikirja", "video"),
    "tyonvalinta": ("painopist", "tavoite", "tehtav", "priorit", "agentti", "suunnittel", "koulu"),
}

SEPPA = re.compile(r"[^a-z0-9]+")
STOP = frozenset(("onko", "saako", "tehdaan", "pitaa", "vai", "ja", "jos", "kun", "etta", "mika", "miten",
                  "ovat", "oli", "olla", "ole", "tama", "nama", "sita", "han", "the", "and", "kuin"))

ARKAINTA = (
    re.compile(r"\b\d{6}[-+A]\d{3}[0-9A-Y]\b"),                     # henkilotunnus
    re.compile(r"\bFI\d{2}[ ]?(?:\d{4}[ ]?){3}\d{2}\b", re.I),      # IBAN (FI)
    re.compile(r"\b(?:sk|ghp|gho|ghs|xox[bp])[-_][A-Za-z0-9_-]{16,}"),  # avaimen nakoinen
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),                              # pitka heksa (tokeni)
)
ARKAINTA_SANAT = ("diagnoos", "sairaus", "laakitys", "potilas", "tilinumero")


class ArkaluonteinenVirhe(Exception):
    """Teksti nayttaa henkilotunnukselta, tilinumerolta, avaimelta tai terveystiedolta."""


class MuistiVirhe(Exception):
    pass


def normalisoi(teksti):
    """Pienet kirjaimet ilman diakriitteja (a, o); ainoastaan a-z ja 0-9."""
    t = unicodedata.normalize("NFKD", str(teksti).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t


def sanat(teksti):
    """Karkea vartalo: ensimmaiset 6 merkkia, vahintaan 3 merkin sanat, ilman tayttosanoja."""
    ulos = []
    for s in SEPPA.split(normalisoi(teksti)):
        if len(s) >= 3 and s not in STOP:
            ulos.append(s[:6])
    return ulos


def tarkista_turvallinen(teksti):
    """Nostaa ArkaluonteinenVirhe, jos teksti ei saa menna muistiin tai lokiin. Viesti ei sisalla tekstia."""
    s = str(teksti)
    for kuvio in ARKAINTA:
        if kuvio.search(s):
            raise ArkaluonteinenVirhe("kuvio")
    pienet = s.lower()
    for sana in ARKAINTA_SANAT:
        if sana in pienet:
            raise ArkaluonteinenVirhe("terveys_tai_talous")


def luokka_avain(luokka):
    return normalisoi(luokka or "muu").strip() or "muu"


def luokittele(kysymys, vaihtoehdot=()):
    """Luokan arvaus avainsanoista. Palauttaa luokan normalisoituna nimena."""
    teksti = normalisoi(" ".join([str(kysymys)] + [str(v) for v in vaihtoehdot]))
    paras, pisteet = "muu", 0
    for luokka, avaimet in LUOKKA_SANAT.items():
        n = sum(1 for a in avaimet if a in teksti)
        if n > pisteet:
            paras, pisteet = luokka, n
    return paras


def _kanoninen(vaihtoehto):
    """Kylla/ei-vaihtoehdot yhdistetaan samaksi arvoksi; muut jaavat sellaisenaan."""
    t = normalisoi(vaihtoehto).strip()
    if t in ("kylla", "joo", "yes"):
        return "kylla"
    if t in ("ei", "no"):
        return "ei"
    return None


def _yhteensopivuus(vaihtoehto, toinen):
    a, b = _kanoninen(vaihtoehto), _kanoninen(toinen)
    if a and b:
        return 1.0 if a == b else 0.0
    if a or b:
        return 0.0
    x, y = set(sanat(vaihtoehto)), set(sanat(toinen))
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def lataa_muisti(polku):
    """Lukee paatosmuistin (JSONL). Virheellinen rivi nostaa MuistiVirhe (vain rivinumero)."""
    rivit = []
    with open(polku, encoding="utf-8") as f:
        for nro, rivi in enumerate(f, 1):
            rivi = rivi.strip()
            if not rivi:
                continue
            try:
                d = json.loads(rivi)
            except ValueError:
                raise MuistiVirhe("rivi %d: ei JSON" % nro)
            if not isinstance(d, dict) or any(k not in d for k in PAKOLLISET_KENTAT):
                raise MuistiVirhe("rivi %d: pakollinen kentta puuttuu" % nro)
            if not isinstance(d["vaihtoehdot"], list) or d["valittu"] not in d["vaihtoehdot"]:
                raise MuistiVirhe("rivi %d: valittu ei ole vaihtoehdoissa" % nro)
            rivit.append(d)
    return rivit


class Arvaus(object):
    """Varjotilan vastaus. tila: 'arvaus', 'en_tieda' tai 'tonylle' (raha)."""

    def __init__(self, tila, valittu, varmuus, perustelu, luokka, paras=None, naapurit=()):
        self.tila = tila
        self.valittu = valittu          # None, jos tila ei ole 'arvaus'
        self.varmuus = varmuus          # 0.0 - 1.0
        self.perustelu = perustelu
        self.luokka = luokka
        self.paras = paras              # paras vaihtoehto myos silloin, kun varmuus ei riita
        self.naapurit = list(naapurit)  # paatosten id:t, joihin arvaus nojaa

    def sanakirja(self):
        return {"tila": self.tila, "valittu": self.valittu, "varmuus": round(self.varmuus, 3),
                "perustelu": self.perustelu, "luokka": self.luokka, "paras": self.paras,
                "naapurit": self.naapurit}


class _Indeksi(object):
    def __init__(self, muisti):
        self.muisti = muisti
        self.sanat = [Counter(sanat(m["kysymys"])) for m in muisti]
        df = Counter()
        for c in self.sanat:
            df.update(c.keys())
        n = max(len(muisti), 1)
        self.idf = {s: math.log((n + 1.0) / (d + 0.5)) + 1.0 for s, d in df.items()}
        self.normit = [self._norm(c) for c in self.sanat]
        # Luokan kylla-osuus (Laplace-tasoitettu) kylla/ei-paatoksista.
        yn = {}
        for m in muisti:
            if {_kanoninen(v) for v in m["vaihtoehdot"]} == {"kylla", "ei"}:
                k = yn.setdefault(luokka_avain(m["luokka"]), [0, 0])
                k[1] += 1
                k[0] += 1 if _kanoninen(m["valittu"]) == "kylla" else 0
        self.kylla_osuus = {k: (a + 1.0) / (n + 2.0) for k, (a, n) in yn.items()}

    def _norm(self, c):
        return math.sqrt(sum((v * self.idf.get(s, 1.0)) ** 2 for s, v in c.items())) or 1.0

    def samankaltaisuus(self, kysymys):
        q = Counter(sanat(kysymys))
        qn = self._norm(q)
        ulos = []
        for i, c in enumerate(self.sanat):
            dot = sum(v * c[s] * self.idf.get(s, 1.0) ** 2 for s, v in q.items() if s in c)
            ulos.append(dot / (qn * self.normit[i]))
        return ulos


def arvaa(kysymys, vaihtoehdot, muisti, luokka=None, indeksi=None):
    """Arvaa Tonyn vastaus. Ei sivuvaikutuksia. Tyhja muisti tai heikko osuma = 'en_tieda'."""
    vaihtoehdot = [str(v) for v in vaihtoehdot]
    if len(vaihtoehdot) < 2:
        raise ValueError("vahintaan kaksi vaihtoehtoa")
    luokka = luokka_avain(luokka) if luokka else luokittele(kysymys, vaihtoehdot)
    if luokka == RAHA_LUOKKA:
        return Arvaus("tonylle", None, 1.0,
                      "Rahapaatos: Tonyn linja on, etta rahan paatokset tekee han itse.", luokka)
    if not muisti:
        return Arvaus("en_tieda", None, 0.0, "Paatosmuisti on tyhja.", luokka)
    ind = indeksi or _Indeksi(muisti)
    sim = ind.samankaltaisuus(kysymys)
    jarjestys = sorted(range(len(muisti)), key=lambda i: -sim[i])
    naapurit = [i for i in jarjestys[:NAAPURIT_MAX] if sim[i] >= NAAPURI_SIM_MIN]
    if not naapurit:
        return Arvaus("en_tieda", None, 0.0, "Muistissa ei ole samankaltaista paatosta.", luokka)
    pisteet = []
    for v in vaihtoehdot:
        p = 0.0
        for i in naapurit:
            m = muisti[i]
            hylatyt = [h for h in m["vaihtoehdot"] if h != m["valittu"]]
            vastus = (sum(_yhteensopivuus(v, h) for h in hylatyt) / len(hylatyt)) if hylatyt else 0.0
            p += sim[i] * (_yhteensopivuus(v, m["valittu"]) - 0.5 * vastus)
        pisteet.append(p)
    if {_kanoninen(v) for v in vaihtoehdot} == {"kylla", "ei"} and luokka in ind.kylla_osuus:
        priori = PRIORI_PAINO * (ind.kylla_osuus[luokka] - 0.5)
        pisteet = [p + (priori if _kanoninen(v) == "kylla" else -priori) for p, v in zip(pisteet, vaihtoehdot)]
    jarj = sorted(range(len(vaihtoehdot)), key=lambda j: -pisteet[j])
    paras, toinen = jarj[0], jarj[1]
    kattavuus = min(1.0, sum(sim[i] for i in naapurit) / 1.0)
    marginaali = (pisteet[paras] - pisteet[toinen]) / (abs(pisteet[paras]) + abs(pisteet[toinen]) + 1e-9)
    varmuus = max(0.0, min(1.0, marginaali * kattavuus))
    tunnisteet = [muisti[i]["id"] for i in naapurit]
    perustelu = "Samankaltaiset paatokset %s; paras vaihtoehto '%s'." % (", ".join(tunnisteet), vaihtoehdot[paras])
    if pisteet[paras] <= 0 or varmuus < VARMUUS_KYNNYS:
        return Arvaus("en_tieda", None, varmuus, perustelu + " Varmuus liian pieni.", luokka,
                      paras=vaihtoehdot[paras], naapurit=tunnisteet)
    return Arvaus("arvaus", vaihtoehdot[paras], varmuus, perustelu, luokka, paras=vaihtoehdot[paras],
                  naapurit=tunnisteet)


def _avaa_liita(polku):
    return os.fdopen(os.open(polku, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", encoding="utf-8")


class Varjotila(object):
    """Arvaa, kirjaa arvaukset ja osumat. Kirjaus: vain liitto (append) omaan lokitiedostoon, tila 0600."""

    def __init__(self, muisti_polku, loki_polku, nyt=None):
        self.muisti = lataa_muisti(muisti_polku)
        self.loki_polku = loki_polku
        self._indeksi = _Indeksi(self.muisti)
        self._nyt = nyt or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def _kirjaa(self, rivi):
        with _avaa_liita(self.loki_polku) as f:
            f.write(json.dumps(rivi, ensure_ascii=False) + "\n")

    def kysy(self, tunniste, kysymys, vaihtoehdot, luokka=None):
        """Arvaa ja kirjaa arvaus. Arkaluonteinen kysymys hylataan ennen kirjausta."""
        tarkista_turvallinen(kysymys)
        for v in vaihtoehdot:
            tarkista_turvallinen(v)
        a = arvaa(kysymys, vaihtoehdot, self.muisti, luokka=luokka, indeksi=self._indeksi)
        rivi = {"tyyppi": "arvaus", "id": tunniste, "aika": self._nyt(), "kysymys": kysymys,
                "vaihtoehdot": list(vaihtoehdot)}
        rivi.update(a.sanakirja())
        self._kirjaa(rivi)
        return a

    def vastaa(self, tunniste, valittu):
        """Tony vastasi: kirjaa osuma (True/False) tai None, jos varjotila ei arvannut."""
        arvaus = None
        for r in self._lue_loki():
            if r.get("tyyppi") == "arvaus" and r.get("id") == tunniste:
                arvaus = r
        if arvaus is None:
            raise KeyError("tuntematon tunniste")
        osuma = None
        if arvaus["tila"] == "arvaus":
            osuma = arvaus["valittu"] == valittu
        self._kirjaa({"tyyppi": "vastaus", "id": tunniste, "aika": self._nyt(), "valittu": valittu,
                      "luokka": arvaus["luokka"], "tila": arvaus["tila"], "osuma": osuma})
        return osuma

    def _lue_loki(self):
        if not os.path.exists(self.loki_polku):
            return []
        ulos = []
        with open(self.loki_polku, encoding="utf-8") as f:
            for rivi in f:
                rivi = rivi.strip()
                if rivi:
                    try:
                        ulos.append(json.loads(rivi))
                    except ValueError:
                        continue
        return ulos

    def osumat(self):
        """Luokittain: vastauksia, arvattuja, osumia, en_tieda, tonylle."""
        return laske_osumat(r for r in self._lue_loki() if r.get("tyyppi") == "vastaus")


def laske_osumat(vastaukset):
    ulos = {}
    for r in vastaukset:
        k = ulos.setdefault(r["luokka"], {"vastauksia": 0, "arvattu": 0, "osumia": 0, "en_tieda": 0, "tonylle": 0})
        k["vastauksia"] += 1
        if r["tila"] == "arvaus":
            k["arvattu"] += 1
            if r["osuma"]:
                k["osumia"] += 1
        elif r["tila"] == "en_tieda":
            k["en_tieda"] += 1
        elif r["tila"] == "tonylle":
            k["tonylle"] += 1
    return ulos
