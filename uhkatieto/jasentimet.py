"""Jasentimet: syotteen raakateksti -> rivit (lahde, id, pvm, otsikko, tagit, url).

Syotteen sisalto on DATAA: jasentimet eivat suorita, evaluoi tai tulkitse sita ohjeina. Kaikki tekstikentat siivotaan
(ohjausmerkit pois, pituusrajat), ja url hyvaksytaan vain jos se alkaa http(s)://. Vain stdlib.
"""
import json
import re

OTSIKKO_MAX = 300
TAGI_MAX = 60
TAGEJA_MAX = 20
URL_MAX = 500
_OHJAUS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_PVM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def siivoa(teksti, max_pituus):
    """Muuttaa mielivaltaisen arvon lyhyeksi yhden rivin merkkijonoksi."""
    if not isinstance(teksti, str):
        return ""
    return " ".join(_OHJAUS_RE.sub(" ", teksti).split())[:max_pituus]


def siisti_url(url):
    u = siivoa(url, URL_MAX)
    return u if u.lower().startswith(("https://", "http://")) and " " not in u else ""


def siisti_pvm(arvo):
    m = _PVM_RE.match(arvo.strip()) if isinstance(arvo, str) else None
    return m.group(0) if m else ""


def rivi(lahde, id_, pvm, otsikko, tagit, url):
    """Normalisoitu rivi; palauttaa None jos id puuttuu."""
    id_ = siivoa(id_, 100)
    if not id_:
        return None
    tagit_siisti = []
    for t in tagit:
        t = siivoa(t, TAGI_MAX).lower().replace(",", " ")
        if t and t not in tagit_siisti:
            tagit_siisti.append(t)
    return {"lahde": lahde, "id": id_, "pvm": siisti_pvm(pvm), "otsikko": siivoa(otsikko, OTSIKKO_MAX),
            "tagit": tagit_siisti[:TAGEJA_MAX], "url": siisti_url(url)}


def _json(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    return json.loads(data)


def jasenna_kev(data):
    """CISA KEV: {"vulnerabilities": [{cveID, vendorProject, product, vulnerabilityName, dateAdded, ...}]}."""
    tulos = []
    for v in _json(data).get("vulnerabilities", []):
        if not isinstance(v, dict):
            continue
        cve = v.get("cveID", "")
        tagit = ["kev", v.get("vendorProject", ""), v.get("product", "")]
        if str(v.get("knownRansomwareCampaignUse", "")).lower() == "known":
            tagit.append("ransomware")
        r = rivi("kev", cve, v.get("dateAdded", ""), "%s: %s" % (cve, v.get("vulnerabilityName", "")), tagit,
                 "https://nvd.nist.gov/vuln/detail/" + siivoa(cve, 40))
        if r:
            tulos.append(r)
    return tulos


def _skalaari(rivit, alku, loppu):
    """Lukee YAML-skalaarin (yksinkertainen, kentta yhdella tai usealla rivilla). Palauttaa merkkijonon."""
    osat = [alku.strip()] + [x.strip() for x in rivit[:loppu]]
    s = " ".join(o for o in osat if o)
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"')
    return s


_OSIOT = {"techniques": ("technique", "techniques"), "mitigations": ("mitigation", "mitigations"),
          "case-studies": ("case-study", "studies")}
_OSIO_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(#.*)?$")
_ENTRY_RE = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$")
_KENTTA_RE = re.compile(r"^    (name|created-date|modified-date):[ ]?(.*)$")


def jasenna_atlas(teksti):
    """MITRE ATLAS (dist/v6/ATLAS-*.yaml). PyYAMLia ei ole, joten luetaan vain tunnettu rakenne rivipohjaisesti:
    ylataso 'techniques|mitigations|case-studies:', 2 valilyonnilla sisennetty avain = id, 4 valilyonnilla sisennetyt kentat name,
    created-date, modified-date. Muu YAML ohitetaan. Muodon muuttuessa rivit vain vahenevat (testi huomaa)."""
    if isinstance(teksti, (bytes, bytearray)):
        teksti = teksti.decode("utf-8", "replace")
    rivit = teksti.splitlines()
    tulos, osio, nykyinen = [], None, None

    def valmis():
        if nykyinen and nykyinen.get("name"):
            laji, polku = _OSIOT[osio]
            tagit = ["atlas", laji] + (["sub-technique"] if laji == "technique" and nykyinen["id"].count(".") > 1 else [])
            r = rivi("atlas", nykyinen["id"], nykyinen.get("created-date") or nykyinen.get("modified-date", ""),
                     "%s: %s" % (nykyinen["id"], nykyinen["name"]), tagit,
                     "https://atlas.mitre.org/%s/%s" % (polku, nykyinen["id"]))
            if r:
                tulos.append(r)

    i = 0
    while i < len(rivit):
        r = rivit[i]
        i += 1
        if r and not r[0].isspace() and not r.startswith(("#", "-")):
            valmis()
            nykyinen = None
            m = _OSIO_RE.match(r)
            osio = m.group(1) if m and m.group(1) in _OSIOT else None
            continue
        if osio is None:
            continue
        m = _ENTRY_RE.match(r)
        if m:
            valmis()
            nykyinen = {"id": m.group(1).strip("'\"")}
            continue
        m = _KENTTA_RE.match(r)
        if m and nykyinen is not None:
            jatko = []
            while i + len(jatko) < len(rivit):
                j = rivit[i + len(jatko)]
                if j.strip() and (len(j) - len(j.lstrip())) <= 4:
                    break
                jatko.append(j)
            nykyinen[m.group(1)] = _skalaari(jatko, m.group(2), len(jatko))
            i += len(jatko)
    valmis()
    return tulos


def jasenna_nvd(data, avainsana):
    """NVD REST 2.0: {"vulnerabilities": [{"cve": {id, published, descriptions, metrics}}]}. avainsana -> tagiksi."""
    tulos = []
    for v in _json(data).get("vulnerabilities", []):
        cve = v.get("cve") if isinstance(v, dict) else None
        if not isinstance(cve, dict):
            continue
        kuvaus = ""
        for d in cve.get("descriptions", []):
            if isinstance(d, dict) and d.get("lang") == "en":
                kuvaus = d.get("value", "")
                break
        tagit = ["nvd", "kw-" + str(avainsana)]
        metriikat = cve.get("metrics", {})
        for avain in ("cvssMetricV31", "cvssMetricV40", "cvssMetricV30"):
            lista = metriikat.get(avain) if isinstance(metriikat, dict) else None
            if lista and isinstance(lista[0], dict):
                sev = lista[0].get("cvssData", {}).get("baseSeverity")
                if isinstance(sev, str):
                    tagit.append("sev-" + sev)
                    break
        id_ = cve.get("id", "")
        r = rivi("nvd", id_, cve.get("published", ""), "%s: %s" % (id_, kuvaus), tagit,
                 "https://nvd.nist.gov/vuln/detail/" + siivoa(id_, 40))
        if r:
            tulos.append(r)
    return tulos
