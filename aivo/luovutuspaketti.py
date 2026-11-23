"""Luovutuspaketti: monta palaa, yksi hyvaksynta (yksityisesta tilasta tyokalutilaan, yksisuuntainen).

Rakentuu yksittaisen luovutuksen (aivo/luovutus.py) paalle. Yksittaisen luovutuksen sha-sidonta ja
yksityinen.hyvaksy_ehdotus pysyvat ennallaan; tama moduuli ei muuta niita.

Turvarajat (koodi on laki):
  * Yksityisen tilan vastauksen lohko [[LUOVUTUSPAKETTI nimi]] [[PALA 1]] ... [[/PALA]] ... [[/LUOVUTUSPAKETTI]] luo
    vain pakettiehdotuksen yksityiseen kansioon <luovutukset>/paketit (0700, tiedostot 0600). Mitaan ei lahde.
  * Paketin sha256 lasketaan koko paketista (nimi, jatkettava paketti ja jokaisen palan numero ja teksti).
    Hyvaksynta "kylla <sha8>" on sidottu siihen. Palan poisto luo uuden sha:n, joten vanha vahvistus ei kelpaa.
  * Vuotovartija (tehtava 20-31) tarkistaa jokaisen palan koukun vartija_koukku kautta. Kun vartijaa ei ole,
    palan merkinta kertoo sen, eika automaattinen lisapala koskaan lahde.
    Vartijan estama pala estaa koko paketin lahetyksen, kunnes Tony poistaa palan.
  * Hyvaksytty paketti: jokainen pala kopioidaan kirjaston kansioon saapuneet/ omana tiedostonaan
    (luovutus.saapunut_teksti), ja tekstin alussa on rivi, jossa on paketin tunnus ja palan numero.
  * Paluu: AIVO_TULOS_REPO on yksityinen tulosrepo (polku tai klooni). Tulos palalle n on tiedosto
    <tulosrepo>/<pakettitunnus>/pala-<n>.md. Vain yksityinen tila lukee sita. Tyokalutila ei koskaan lue
    yksityista aluetta, eika tulosrepo saa olla kirjaston tai tyokalutilan datan sisalla.
  * Lisapalat: [[LISAPALA <pakettitunnus>]] teksti [[/LISAPALA]]. AIVO_LISAPALAT=kysy (oletus): jokainen lisapala
    vaatii oman hyvaksynnan. "automaattinen": vartijan hyvaksyma, hyvaksytyn paketin tunnuksella merkitty lisapala
    lahtee ilman painallusta, ja siita kirjataan yhteenveto. Vaihto on Tonyn paatos."""
import importlib
import importlib.util
import json
import os
import re
import secrets
import stat
from pathlib import Path

from aivo import luovutus, yksityinen
from aivo.yksityinen import YksityinenVirhe

PAKETIT = "paketit"
HYVAKSYTYT = "hyvaksytyt"
PALUUT = "paluut.json"
AUTOMAATTISET = "automaattiset.jsonl"
PALOJA_ENINTAAN = 20
PAKETTI_YLARAJA = 40_000          # merkkia kaikissa paloissa yhteensa
TULOS_YLARAJA = 50_000            # tavua yhdessa tulostiedostossa
LISAPALAT_ARVOT = ("kysy", "automaattinen")
LISAPALAT_OLETUS = "kysy"

TUNNUS_RE = luovutus.TUNNUS_RE
NIMI_RE = re.compile(r"\A[^\W_][\w .,:()\-]{0,79}\Z")       # ei hakasulkeita, ei <>-merkkeja, ei rivinvaihtoja
PAKETTI_RE = re.compile(r"\[\[LUOVUTUSPAKETTI ([^\[\]\n]{1,80})\]\]\n?(.*?)\[\[/LUOVUTUSPAKETTI\]\]", re.S)
KATKENNUT_PAKETTI_RE = re.compile(r"\[\[LUOVUTUSPAKETTI\b[^\]\n]*\]\].*\Z", re.S)
PALA_RE = re.compile(r"\[\[PALA (\d{1,2})\]\]\n?(.*?)\[\[/PALA\]\]", re.S)
LISAPALA_RE = re.compile(r"\[\[LISAPALA ([0-9a-f]{12})\]\]\n?(.*?)\[\[/LISAPALA\]\]", re.S)
KATKENNUT_LISAPALA_RE = re.compile(r"\[\[LISAPALA\b[^\]\n]*\]\].*\Z", re.S)
PALUU_MATKINTA_RE = re.compile(r"\[\s*Paketin\b", re.I)
PALUU_NEUTRALOITU = "[Aivon teksti, ei paluumerkint\u00e4: Paketin"
KATKENNUT_PAKETTI = "[luovutuspakettia ei tallennettu: vastaus katkesi]"


# --- Apufunktiot ------------------------------------------------------------------------------------

def paketit_hakemisto(luovutukset):
    """Pakettiehdotusten kansio yksityisen luovutuskansion alla (0700)."""
    return yksityinen.tarkista_yksityinen_hakemisto(Path(luovutukset) / PAKETIT)


def _tunnus(tunnus):
    if not isinstance(tunnus, str) or not TUNNUS_RE.fullmatch(tunnus):
        raise YksityinenVirhe("virheellinen paketin tunnus")
    return tunnus


def _nimi(nimi):
    nimi = nimi.strip() if isinstance(nimi, str) else ""
    if not NIMI_RE.fullmatch(nimi):
        raise YksityinenVirhe("paketin nimi ei kelpaa (1-80 merkkia: kirjaimet, numerot, valilyonti, .,:()-)")
    return nimi


def _palan_nro(n):
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 99:
        raise YksityinenVirhe("virheellinen palan numero")
    return n


def paketin_sha(nimi, palat, jatkaa=None):
    """sha256 koko paketista: nimi, jatkettava paketti ja jokaisen palan numero ja teksti."""
    kanoninen = json.dumps({"nimi": nimi, "jatkaa": jatkaa, "palat": [[p["n"], p["teksti"]] for p in palat]},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return yksityinen.sha(kanoninen)


def palan_tunnus(perusta, n):
    """Saapuneet-tiedoston tunnus palalle: johdetaan paketin tunnuksesta ja palan numerosta (sama pala ei lahde kahdesti)."""
    return yksityinen.sha("%s:%d" % (_tunnus(perusta), _palan_nro(n)))[:12]


def palan_teksti(perusta, nimi, n, teksti):
    """Saapuneisiin menevan palan teksti: ensimmaisella rivilla paketin tunnus ja palan numero."""
    return "<!-- luovutuspaketti tunnus=%s pala=%d nimi=%s -->\n%s" % (perusta, n, nimi, teksti)


def paluumerkinta(nimi, n):
    return "[Paketin %s pala %d valmis]" % (nimi, n)


def neutraloi_paluumerkinnat(teksti):
    """Mallin teksti ei saa nayttaa palvelimen paluumerkinnalta."""
    return PALUU_MATKINTA_RE.sub(lambda m: PALUU_NEUTRALOITU, teksti)


def vartija_koukku(teksti):
    """Koukku vuotovartijalle (tehtava 20-31). Kun moduuli aivo.vuotovartija on olemassa ja tarjoaa funktion
    tarkista(teksti) -> {"sallittu": bool, "merkinnat": [str]}, sita kaytetaan. Ilman vartijaa palautetaan
    sallittu=None: pala ei esty, mutta Tony tarkistaa sen itse eika automaattinen lisapala lahde."""
    try:
        if importlib.util.find_spec("aivo.vuotovartija") is None:
            return {"tila": "ei-vartijaa", "sallittu": None,
                    "merkinnat": ["Vuotovartija ei ole viel\u00e4 k\u00e4yt\u00f6ss\u00e4: tarkista pala itse."]}
        vuotovartija = importlib.import_module("aivo.vuotovartija")
    except Exception as e:      # vartijan latausvirhe ei saa paastaa palaa lapi
        return {"tila": "virhe", "sallittu": False, "merkinnat": ["Vuotovartijaa ei voitu ladata (%s)." % type(e).__name__]}
    try:
        r = vuotovartija.tarkista(teksti)
        sallittu = r.get("sallittu") is True
        merkinnat = [str(m)[:300] for m in (r.get("merkinnat") or [])][:20]
    except Exception as e:
        return {"tila": "virhe", "sallittu": False, "merkinnat": ["Vuotovartija ep\u00e4onnistui (%s)." % type(e).__name__]}
    return {"tila": "tarkistettu", "sallittu": sallittu, "merkinnat": merkinnat}


def _vartioi(vartija, teksti):
    try:
        r = vartija(teksti)
    except Exception as e:
        return {"tila": "virhe", "sallittu": False, "merkinnat": ["Vuotovartija ep\u00e4onnistui (%s)." % type(e).__name__]}
    if not isinstance(r, dict):
        return {"tila": "virhe", "sallittu": False, "merkinnat": ["Vuotovartijan vastaus ei kelpaa."]}
    s = r.get("sallittu")
    # identiteettivertailu: "s in (True, False, None)" paastaisi 0:n ja 1:n (0 == False), ja 0 ei estaisi palaa
    return {"tila": str(r.get("tila", "tarkistettu"))[:40], "sallittu": s if s is True or s is None else False,
            "merkinnat": [str(m)[:300] for m in (r.get("merkinnat") or [])][:20]}


# --- Ehdotukset (yksityinen kansio) ---------------------------------------------------------------

def _tarkista_palat(palat):
    if not isinstance(palat, (list, tuple)) or not 1 <= len(palat) <= PALOJA_ENINTAAN:
        raise YksityinenVirhe("paketissa pitaa olla 1-%d palaa" % PALOJA_ENINTAAN)
    ulos, nahdyt, yht = [], set(), 0
    for n, teksti in palat:
        _palan_nro(n)
        if n in nahdyt:
            raise YksityinenVirhe("palan numero %d toistuu" % n)
        nahdyt.add(n)
        luovutus._tarkista_teksti(teksti)
        yht += len(teksti)
        ulos.append({"n": n, "teksti": teksti})
    if yht > PAKETTI_YLARAJA:
        raise YksityinenVirhe("paketti on liian pitka (enintaan %d merkkia)" % PAKETTI_YLARAJA)
    return sorted(ulos, key=lambda p: p["n"])


def tallenna_paketti(luovutukset, nimi, palat, lahde="lohko", jatkaa=None, vartija=vartija_koukku):
    """Tallentaa pakettiehdotuksen. palat: [(n, teksti)]. jatkaa: hyvaksytyn paketin tunnus (lisapalat).
    Ei luovuta mitaan. Palauttaa tunnuksen."""
    nimi = _nimi(nimi)
    if lahde not in ("lohko", "lisapala"):
        raise YksityinenVirhe("tuntematon paketin lahde")
    if jatkaa is not None:
        _tunnus(jatkaa)
    pl = _tarkista_palat(palat)
    for p in pl:
        p["vartija"] = _vartioi(vartija, p["teksti"])
    h = paketit_hakemisto(luovutukset)
    tunnus = secrets.token_hex(6)
    d = {"nimi": nimi, "jatkaa": jatkaa, "palat": pl, "sha": paketin_sha(nimi, pl, jatkaa), "lahde": lahde,
         "luotu": luovutus._nyt().isoformat(timespec="seconds"), "poistetut": []}
    luovutus._kirjoita_600(h / (tunnus + ".json"), json.dumps(d, ensure_ascii=False), uusi=True)
    return tunnus


def _lue_json(p):
    if not stat.S_ISREG(os.lstat(p).st_mode):
        raise ValueError
    d = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not isinstance(d["nimi"], str) or not isinstance(d["palat"], list):
        raise ValueError
    for x in d["palat"]:
        if not isinstance(x, dict) or not isinstance(x["teksti"], str) or isinstance(x["n"], bool) or not isinstance(x["n"], int):
            raise ValueError
    if paketin_sha(d["nimi"], d["palat"], d.get("jatkaa")) != d["sha"]:
        raise ValueError
    return d


def lue_paketti(luovutukset, tunnus, kansio=None):
    """Lukee odottavan (kansio=None) tai hyvaksytyn (kansio=HYVAKSYTYT) paketin ja tarkistaa sha:n."""
    _tunnus(tunnus)
    h = Path(luovutukset) / PAKETIT
    try:
        return _lue_json((h / kansio if kansio else h) / (tunnus + ".json"))
    except (OSError, ValueError, KeyError, TypeError):
        raise YksityinenVirhe("pakettia ei voi lukea")


def listaa_paketit(luovutukset, kansio=None):
    h = Path(luovutukset) / PAKETIT
    if kansio:
        h = h / kansio
    return sorted(p.stem for p in h.glob("*.json") if TUNNUS_RE.fullmatch(p.stem)) if h.is_dir() else []


def poista_pala(luovutukset, tunnus, n, sha8):
    """Tonyn painike: poistaa palan n odottavasta paketista. sha8 = Tonyn nakeman paketin sha:n alku (vanhentunut
    nakyma ei voi poistaa vaaraa palaa). Palauttaa paivitetyn paketin; uusi sha mitatoi vanhan vahvistuksen."""
    _palan_nro(n)
    d = lue_paketti(luovutukset, tunnus)
    if not isinstance(sha8, str) or sha8 != d["sha"][:8]:
        raise YksityinenVirhe("paketti on muuttunut; lataa se uudelleen")
    jaljelle = [p for p in d["palat"] if p["n"] != n]
    if len(jaljelle) == len(d["palat"]):
        raise YksityinenVirhe("palaa ei ole paketissa")
    if not jaljelle:
        raise YksityinenVirhe("viimeista palaa ei voi poistaa; hylkaa paketti")
    d["poistetut"].append({"n": n, "sha": yksityinen.sha([p for p in d["palat"] if p["n"] == n][0]["teksti"]),
                           "aika": luovutus._nyt().isoformat(timespec="seconds")})
    d["palat"] = jaljelle
    d["sha"] = paketin_sha(d["nimi"], jaljelle, d.get("jatkaa"))
    luovutus._kirjoita_600(Path(luovutukset) / PAKETIT / (tunnus + ".json"), json.dumps(d, ensure_ascii=False))
    return d


def hylkaa_paketti(luovutukset, tunnus):
    """Siirtaa paketin alikansioon paketit/hylatyt/ (0700). Ei poista mitaan."""
    _tunnus(tunnus)
    return yksityinen.hylkaa_ehdotus(paketit_hakemisto(luovutukset), tunnus)


def perusta(luovutukset, tunnus):
    """Hyvaksytyn paketin perustunnus ja nimi: lisapaketti osoittaa alkuperaiseen pakettiin."""
    d = lue_paketti(luovutukset, tunnus, HYVAKSYTYT)
    if d.get("jatkaa"):
        return d["jatkaa"], lue_paketti(luovutukset, d["jatkaa"], HYVAKSYTYT)["nimi"]
    return tunnus, d["nimi"]


def hyvaksytyt_palat(luovutukset):
    """{perustunnus: {"nimi": nimi, "palat": set(n)}} kaikista hyvaksytyista paketeista lisapalat mukaan lukien."""
    ulos = {}
    for t in listaa_paketit(luovutukset, HYVAKSYTYT):
        try:
            d = lue_paketti(luovutukset, t, HYVAKSYTYT)
            pt, nimi = perusta(luovutukset, t)
        except YksityinenVirhe:
            continue
        e = ulos.setdefault(pt, {"nimi": nimi, "palat": set()})
        e["palat"].update(p["n"] for p in d["palat"])
    return ulos


# --- Hyvaksynta ------------------------------------------------------------------------------------

def hyvaksy_paketti(luovutukset, tunnus, vahvistus, kirjasto, julkaise=yksityinen.julkaise_kirjastoon,
                    nyt=luovutus._nyt, vartija=vartija_koukku):
    """Vie jokaisen palan kirjaston kansioon saapuneet/ omana tiedostonaan vain, jos vahvistus on tasmalleen
    "kylla <sha8>" koko paketin sha:sta. Jarjestys: (1) sha-tarkistus, (2) vartija tarkistaa jokaisen palan uudelleen,
    (3) lokirivit yksityiseen lokiin, (4) tiedostot kirjastoon ja yksi julkaisu, (5) virheessa kaikki tiedostot
    poistetaan ja paketti jaa odottamaan, (6) onnistuessa paketti siirretaan kansioon paketit/hyvaksytyt/."""
    d = lue_paketti(luovutukset, tunnus)
    if not isinstance(vahvistus, str) or not luovutus.VAHVISTUS_RE.match(vahvistus) or vahvistus != "kyll\u00e4 " + d["sha"][:8]:
        raise YksityinenVirhe("vahvistus ei tasmaa; mitaan ei luovutettu")
    estetyt = [p["n"] for p in d["palat"] if _vartioi(vartija, p["teksti"])["sallittu"] is False]
    if estetyt:
        raise YksityinenVirhe("vuotovartija esti palat %s; poista ne ennen lahetysta" % ", ".join(map(str, estetyt)))
    if d.get("jatkaa"):
        pt, nimi = perusta(luovutukset, d["jatkaa"])
    else:
        pt, nimi = tunnus, d["nimi"]
    aika = nyt().isoformat(timespec="seconds")
    saap = Path(kirjasto) / luovutus.SAAPUNEET
    saap.mkdir(mode=0o700, parents=True, exist_ok=True)
    kohteet = []
    for p in d["palat"]:
        pid = palan_tunnus(pt, p["n"])
        k = saap / (pid + ".md")
        if k.exists() or (saap / luovutus.KASITELLYT / (pid + ".md")).exists():
            raise YksityinenVirhe("paketin pala %d on jo saapuneissa" % p["n"])
        kohteet.append((p, pid, k))
    for p, pid, k in kohteet:                                                                        # (3)
        luovutus._kirjaa_lokiin(luovutukset, {"aika": aika, "tunnus": pid, "sha": yksityinen.sha(p["teksti"]),
                                              "teksti": p["teksti"], "paketti": pt, "pala": p["n"]})
    kirjoitetut = []
    try:
        for p, pid, k in kohteet:                                                                    # (4)
            sisalto = palan_teksti(pt, nimi, p["n"], p["teksti"])
            luovutus._kirjoita_600(k, luovutus.saapunut_teksti(pid, yksityinen.sha(sisalto), aika, sisalto), uusi=True)
            kirjoitetut.append(k)
        tulos = julkaise(kirjasto, saap, viesti="Luovutuspaketti %s: Tony hyvaksyi %d palaa (sha %s)"
                         % (pt, len(kohteet), d["sha"][:8]))
    except BaseException as e:
        for k in kirjoitetut:                                                                        # (5)
            k.unlink(missing_ok=True)
        for p, pid, k in kohteet:
            luovutus._kirjaa_lokiin(luovutukset, {"aika": aika, "tunnus": pid, "tulos": "virhe: " + type(e).__name__})
        raise
    for p, pid, k in kohteet:
        luovutus._kirjaa_lokiin(luovutukset, {"aika": aika, "tunnus": pid, "tulos": tulos})
    h = Path(luovutukset) / PAKETIT                                                                  # (6)
    hyv = yksityinen.tarkista_yksityinen_hakemisto(h / HYVAKSYTYT)
    d["hyvaksytty"] = aika
    try:
        luovutus._kirjoita_600(hyv / (tunnus + ".json"), json.dumps(d, ensure_ascii=False), uusi=True)
        os.unlink(h / (tunnus + ".json"))
    except OSError:
        pass        # palat ovat jo perilla; toista lahetysta estaa kohteiden olemassaolo
    return tulos


# --- Lisapalat ------------------------------------------------------------------------------------

def _seuraavat_numerot(luovutukset, pt, maara):
    kaytetyt = set(hyvaksytyt_palat(luovutukset).get(pt, {}).get("palat", ()))
    for t in listaa_paketit(luovutukset):
        try:
            d = lue_paketti(luovutukset, t)
        except YksityinenVirhe:
            continue
        if d.get("jatkaa") == pt:
            kaytetyt.update(p["n"] for p in d["palat"])
    alku = max(kaytetyt, default=0) + 1
    return list(range(alku, alku + maara))


def tallenna_lisapalat(luovutukset, kirjasto, jatkaa, tekstit, tila=LISAPALAT_OLETUS, julkaise=yksityinen.julkaise_kirjastoon,
                       vartija=vartija_koukku):
    """Lisapalat hyvaksytylle paketille. Palauttaa (tunnus, lahti, yhteenveto).
    tila="kysy": vain ehdotus (oma hyvaksynta). tila="automaattinen": lahtee ilman painallusta vain, jos vartija on
    hyvaksynyt jokaisen palan (sallittu is True); muuten jaa odottamaan hyvaksyntaa."""
    if tila not in LISAPALAT_ARVOT:
        raise YksityinenVirhe("tuntematon AIVO_LISAPALAT-arvo")
    pt, nimi = perusta(luovutukset, _tunnus(jatkaa))
    numerot = _seuraavat_numerot(luovutukset, pt, len(tekstit))
    if numerot and numerot[-1] > 99:
        raise YksityinenVirhe("paketissa on jo liikaa paloja")
    tunnus = tallenna_paketti(luovutukset, nimi, list(zip(numerot, tekstit)), "lisapala", pt, vartija)
    if tila != "automaattinen":
        return tunnus, False, None
    d = lue_paketti(luovutukset, tunnus)
    if not all(p["vartija"]["sallittu"] is True for p in d["palat"]):
        return tunnus, False, "Lis\u00e4palat odottavat hyv\u00e4ksynt\u00e4\u00e4: vuotovartija ei hyv\u00e4ksynyt kaikkia."
    tulos = hyvaksy_paketti(luovutukset, tunnus, "kyll\u00e4 " + d["sha"][:8], kirjasto, julkaise=julkaise, vartija=vartija)
    yhteenveto = ("Lis\u00e4palat %s l\u00e4htiv\u00e4t automaattisesti paketille %s (%s), vuotovartija hyv\u00e4ksyi. Tulos: %s."
                  % (", ".join(map(str, numerot)), nimi, pt, tulos))
    p = paketit_hakemisto(luovutukset) / AUTOMAATTISET
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps({"aika": luovutus._nyt().isoformat(timespec="seconds"), "tunnus": tunnus,
                                  "paketti": pt, "palat": numerot, "sha": d["sha"], "tulos": tulos,
                                  "yhteenveto": yhteenveto}, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return tunnus, True, yhteenveto


# --- Mallin vastauksen kasittely ------------------------------------------------------------------

def irrota_paketit(vastaus, tallenna, tallenna_lisa=None):
    """Poistaa vastauksesta [[LUOVUTUSPAKETTI]]- ja [[LISAPALA]]-lohkot ja tallentaa ne.
    tallenna(nimi, [(n, teksti)]) -> tunnus. tallenna_lisa(pakettitunnus, [teksti]) -> naytettava huomautus.
    Lohkon tilalle tulee huomautus. Katkennut lohko korvataan nakyvalla huomautuksella."""
    def korvaa(m):
        palat = [(int(pm.group(1)), pm.group(2).strip() + "\n") for pm in PALA_RE.finditer(m.group(2))]
        if not palat:
            return "[luovutuspakettia ei tallennettu: paketissa ei ole paloja]"
        try:
            tunnus = tallenna(m.group(1), palat)
        except YksityinenVirhe as e:
            return "[luovutuspakettia ei tallennettu: %s]" % e
        return ("[Luovutuspaketti tallennettu (tunnus %s, %d palaa). Mit\u00e4\u00e4n ei ole l\u00e4htenyt: Tony p\u00e4\u00e4tt\u00e4\u00e4 "
                "l\u00e4hetyksest\u00e4 itse.]" % (tunnus, len(palat)))
    vastaus = KATKENNUT_PAKETTI_RE.sub(lambda m: KATKENNUT_PAKETTI, PAKETTI_RE.sub(korvaa, vastaus))
    lisat = {}
    for m in LISAPALA_RE.finditer(vastaus):
        lisat.setdefault(m.group(1), []).append(m.group(2).strip() + "\n")
    tehdyt = set()

    def korvaa_lisa(m):
        t = m.group(1)
        if t in tehdyt:
            return ""
        tehdyt.add(t)
        if tallenna_lisa is None:
            return "[lis\u00e4palaa ei tallennettu]"
        return tallenna_lisa(t, lisat[t])
    vastaus = LISAPALA_RE.sub(korvaa_lisa, vastaus)
    return KATKENNUT_LISAPALA_RE.sub(lambda m: "[lis\u00e4palaa ei tallennettu: vastaus katkesi]", vastaus)


# --- Paluu: yksityinen tulosrepo (vain yksityinen tila) ---------------------------------------------

def tarkista_tulos_repo(tulos_repo, kielletyt=()):
    """Tulosrepon pitaa olla olemassa oleva kansio (ei symlinkki), eika se saa olla kirjaston tai tyokalutilan datan
    sisalla tai niiden ylapuolella: tyokalutila ei saa koskaan lukea yksityista aluetta."""
    if not tulos_repo:
        return None
    p = Path(tulos_repo)
    try:
        if not stat.S_ISDIR(os.lstat(p).st_mode):
            raise YksityinenVirhe("AIVO_TULOS_REPO ei ole kansio")
    except OSError:
        raise YksityinenVirhe("AIVO_TULOS_REPO ei ole olemassa")
    r = os.path.realpath(p)
    for k in kielletyt:
        if not k:
            continue
        kr = os.path.realpath(k)
        if r == kr or r.startswith(kr.rstrip(os.sep) + os.sep) or kr.startswith(r.rstrip(os.sep) + os.sep):
            raise YksityinenVirhe("AIVO_TULOS_REPO ei saa olla tyokalutilan kansion sisalla tai ylapuolella")
    return r


def _tulos_polku(tulos_repo, pt, n):
    """<tulosrepo>/<pakettitunnus>/pala-<n>.md; mikaan osa ei saa olla symlinkki."""
    juuri = Path(tulos_repo)
    kansio = juuri / _tunnus(pt)
    p = kansio / ("pala-%d.md" % _palan_nro(n))
    if not stat.S_ISDIR(os.lstat(juuri).st_mode) or not stat.S_ISDIR(os.lstat(kansio).st_mode):
        raise OSError("ei kansio")
    if not stat.S_ISREG(os.lstat(p).st_mode):
        raise OSError("ei tiedosto")
    return p


def _lue_paluut(luovutukset):
    p = paketit_hakemisto(luovutukset) / PALUUT
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return set(x for x in d if isinstance(x, str)) if isinstance(d, list) else set()
    except (OSError, ValueError):
        return set()


def tarkista_paluut(luovutukset, tulos_repo):
    """Uudet tulokset hyvaksytyille paloille: [{"tunnus", "nimi", "n", "merkinta"}]. Kukin ilmoitetaan kerran
    (kirjanpito paketit/paluut.json, 0600)."""
    if not tulos_repo:
        return []
    nahdyt, uudet = _lue_paluut(luovutukset), []
    for pt, e in sorted(hyvaksytyt_palat(luovutukset).items()):
        for n in sorted(e["palat"]):
            avain = "%s:%d" % (pt, n)
            if avain in nahdyt:
                continue
            try:
                _tulos_polku(tulos_repo, pt, n)
            except (OSError, YksityinenVirhe):
                continue
            nahdyt.add(avain)
            uudet.append({"tunnus": pt, "nimi": e["nimi"], "n": n, "merkinta": paluumerkinta(e["nimi"], n)})
    if uudet:
        luovutus._kirjoita_600(paketit_hakemisto(luovutukset) / PALUUT, json.dumps(sorted(nahdyt)))
    return uudet


def lue_tulos(luovutukset, tulos_repo, pt, n):
    """Lukee hyvaksytyn paketin palan tuloksen yksityisesta tulosreposta (enintaan TULOS_YLARAJA tavua)."""
    if not tulos_repo:
        raise YksityinenVirhe("tulosrepoa ei ole asetettu (AIVO_TULOS_REPO)")
    _tunnus(pt)
    _palan_nro(n)
    e = hyvaksytyt_palat(luovutukset).get(pt)
    if e is None or n not in e["palat"]:
        raise YksityinenVirhe("palaa ei ole hyvaksytyissa paketeissa")
    try:
        p = _tulos_polku(tulos_repo, pt, n)
        with open(p, "rb") as f:
            raaka = f.read(TULOS_YLARAJA + 1)
    except OSError:
        raise YksityinenVirhe("tulosta ei ole viela")
    if len(raaka) > TULOS_YLARAJA:
        raise YksityinenVirhe("tulos on liian suuri naytettavaksi")
    return raaka.decode("utf-8", "replace")
