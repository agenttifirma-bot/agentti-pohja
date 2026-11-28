"""Agenttitehtava yksityisesta chatista (eristettyjen agenttien osa 4): ehdotus, Tonyn kaynnistys ja tulos.

Turvarajat (koodi on laki):
  * Yksityisen tilan mallin vastauksessa voi olla lohko [[AGENTTI]] teksti [[/AGENTTI]]. Lohko luo vain ehdotuksen
    yksityiseen kansioon (0700, tiedostot 0600). Mitaan ei kaynnisty ilman Tonyn painallusta. Tonyn omia viesteja
    ei tulkita lohkoiksi, eika agentin tulosta jasenneta lainkaan.
  * Kaynnistys tulee vain chat-palvelimen paatepisteesta (POST /api/agentti/kaynnista), ja se on sidottu tekstin
    sha256-tiivisteeseen: vahvistus "kylla <sha8>". Muokkaus luo uuden sha:n, joten vanha vahvistus ei kelpaa.
    Ehdotus on sidottu keskusteluun, jossa se syntyi; toisen keskustelun tunnus hylataan.
  * Agentille menee vain ehdotuksen teksti (se, jonka Tony nakee kortissa). Ei muistia, keskusteluja, ydinohjeita
    eika liitteita. Jonotiedoston muoto on ajurin (aivo/agentti_ajuri.py) pyynto, versio 1.
  * Tulos luetaan ajurin tulostiedostosta vain lukien ja naytetaan vain aloittaneessa keskustelussa. Tiedostonakyma
    lukee ajurin tekemia kopioita (tulokset/<tunnus>/), vain tuloksen tiedostolistassa olevia polkuja, ilman linkkeja.
  * Loki (agenttiloki.jsonl, 0600) sisaltaa vain ajan, tunnuksen ja tilan, ei tehtavan tekstia eika tulosta.
  * Tama moduuli ei tee mallikutsuja eika lue, valitse tai muuta kulukattoja. Kulutieto tulee chatilta parametrina.
"""
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

from aivo import agentti_ajuri, yksityinen
from aivo.agentti import polut
from aivo.yksityinen import YksityinenVirhe

KANSIO = "agenttitehtavat"         # yksityisen datan viereinen kansio (0700)
KAYNNISTETYT = "kaynnistetyt"      # kaynnistetyt ehdotukset (0700); ei poisteta automaattisesti
LOKI = "agenttiloki.jsonl"
TEHTAVA_YLARAJA = 16_000           # merkkia; alle ajurin rajan (agentti_ajuri.RAJA_TEKSTI)
TULOS_TAVUT = 2 * 1024 * 1024      # tulostiedoston lukuraja (syotteen kelpoisuus)
TIEDOSTO_TAVUT = polut.RAJA_TIEDOSTO   # tiedostonakyman raja = agentin tiedostoraja
ARVIO_AJOJA = 20                   # kulun arvio: viimeisimpien ajojen mediaani

TUNNUS_RE = re.compile(r"\A[0-9a-f]{12}\Z")
AGENTTI_RE = re.compile(r"\[\[AGENTTI\]\]\n?(.*?)\[\[/AGENTTI\]\]", re.S)
KATKENNUT_AGENTTI_RE = re.compile(r"\[\[AGENTTI\]\].*\Z", re.S)
KATKENNUT_AGENTTI = "[agenttiteht\u00e4v\u00e4\u00e4 ei tallennettu: vastaus katkesi]"
EI_KAYTOSSA = "[agenttiteht\u00e4v\u00e4\u00e4 ei tallennettu: agenttiteht\u00e4v\u00e4t eiv\u00e4t ole k\u00e4yt\u00f6ss\u00e4]"
VAHVISTUS_RE = re.compile(r"\Akyll\u00e4 [0-9a-f]{8}\Z")

JONOSSA = "jonossa"
KAYNNISSA = "k\u00e4ynniss\u00e4"


def _nyt():
    return datetime.now(timezone.utc)


def _tunnus(tunnus):
    if not isinstance(tunnus, str) or not TUNNUS_RE.match(tunnus):
        raise YksityinenVirhe("virheellinen agenttiteht\u00e4v\u00e4n tunnus")
    return tunnus


def _tarkista_teksti(teksti):
    if not isinstance(teksti, str) or not teksti.strip():
        raise YksityinenVirhe("teht\u00e4v\u00e4n teksti puuttuu")
    if len(teksti) > TEHTAVA_YLARAJA:
        raise YksityinenVirhe("teht\u00e4v\u00e4n teksti on liian pitk\u00e4 (%d merkki\u00e4, raja %d)" % (
            len(teksti), TEHTAVA_YLARAJA))
    if "\x00" in teksti:
        raise YksityinenVirhe("teht\u00e4v\u00e4n tekstiss\u00e4 on NUL-merkki")
    return teksti


def _kirjoita_600(polku, teksti, uusi=False):
    polku = Path(polku)
    if uusi:
        fd = os.open(polku, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(teksti)
        return
    tmp = polku.with_name("." + polku.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(teksti)
    os.replace(tmp, polku)


def _lue_json(polku, raja):
    """Lukee JSON-olion ilman linkkien seuraamista. Virhe -> ValueError."""
    try:
        fd = os.open(polku, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError("ei voi avata") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("ei tavallinen tiedosto")
        raaka = f.read(raja + 1)
    if len(raaka) > raja:
        raise ValueError("liian suuri")
    try:
        d = json.loads(raaka.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ValueError("ei JSONia") from None
    if not isinstance(d, dict):
        raise ValueError("ei olio")
    return d


# --- Ehdotukset (yksityinen kansio) ---------------------------------------------------------------

def tallenna_ehdotus(hakemisto, teksti, keskustelu):
    """Tallentaa mallin ehdottaman tehtavan. Ei kaynnista mitaan. Palauttaa tunnuksen (12 heksamerkkia)."""
    _tarkista_teksti(teksti)
    if not isinstance(keskustelu, str) or not agentti_ajuri.KESKUSTELU_RE.fullmatch(keskustelu):
        raise YksityinenVirhe("virheellinen keskustelun tunniste")
    h = yksityinen.tarkista_yksityinen_hakemisto(hakemisto)
    tunnus = secrets.token_hex(6)
    d = {"teksti": teksti, "sha": yksityinen.sha(teksti), "keskustelu": keskustelu,
         "luotu": _nyt().isoformat(timespec="seconds")}
    _kirjoita_600(h / (tunnus + ".json"), json.dumps(d, ensure_ascii=False), uusi=True)
    return tunnus


def _lue_tietue(polku):
    try:
        d = _lue_json(polku, 4 * TEHTAVA_YLARAJA + 4096)
        if not isinstance(d.get("teksti"), str) or not isinstance(d.get("sha"), str) \
                or not isinstance(d.get("keskustelu"), str):
            raise ValueError
        if yksityinen.sha(d["teksti"]) != d["sha"]:
            raise ValueError
    except ValueError:
        raise YksityinenVirhe("agenttiteht\u00e4v\u00e4\u00e4 ei voi lukea") from None
    return d


def lue_ehdotus(hakemisto, tunnus, keskustelu):
    """Odottava ehdotus. Toisen keskustelun ehdotus hylataan kuin sita ei olisi."""
    _tunnus(tunnus)
    d = _lue_tietue(Path(hakemisto) / (tunnus + ".json"))
    if d["keskustelu"] != keskustelu:
        raise YksityinenVirhe("agenttiteht\u00e4v\u00e4\u00e4 ei voi lukea")
    return d


def lue_kaynnistetty(hakemisto, tunnus, keskustelu):
    _tunnus(tunnus)
    d = _lue_tietue(Path(hakemisto) / KAYNNISTETYT / (tunnus + ".json"))
    if d["keskustelu"] != keskustelu:
        raise YksityinenVirhe("agenttiteht\u00e4v\u00e4\u00e4 ei voi lukea")
    return d


def listaa(hakemisto, keskustelu):
    """Keskustelun odottavat ja kaynnistetyt tehtavat: [{"tunnus", "kaynnistetty"}], vanhimmasta uusimpaan."""
    h = Path(hakemisto)
    ulos = []
    for kansio, kaynnistetty in ((h, False), (h / KAYNNISTETYT, True)):
        if not kansio.is_dir():
            continue
        for p in kansio.glob("*.json"):
            if not TUNNUS_RE.match(p.stem):
                continue
            try:
                d = _lue_tietue(p)
            except YksityinenVirhe:
                continue
            if d["keskustelu"] == keskustelu:
                ulos.append((d.get("luotu") or "", p.stem, kaynnistetty))
    return [{"tunnus": t, "kaynnistetty": k} for _, t, k in sorted(ulos)]


def muokkaa_ehdotus(hakemisto, tunnus, keskustelu, uusi_teksti):
    """Korvaa odottavan ehdotuksen tekstin Tonyn muokkaamalla. Palauttaa uuden sha:n."""
    d = lue_ehdotus(hakemisto, tunnus, keskustelu)
    _tarkista_teksti(uusi_teksti)
    if uusi_teksti != d["teksti"]:
        d.setdefault("alkuperainen_sha", d["sha"])
        d["teksti"], d["sha"] = uusi_teksti, yksityinen.sha(uusi_teksti)
        d["muokattu"] = _nyt().isoformat(timespec="seconds")
        _kirjoita_600(Path(hakemisto) / (tunnus + ".json"), json.dumps(d, ensure_ascii=False))
    return d["sha"]


def hylkaa_ehdotus(hakemisto, tunnus, keskustelu):
    """Siirtaa ehdotuksen alikansioon hylatyt/ (0700). Ei poista mitaan."""
    lue_ehdotus(hakemisto, tunnus, keskustelu)
    return yksityinen.hylkaa_ehdotus(hakemisto, tunnus)


def irrota_lohkot(vastaus, tallenna):
    """Poistaa mallin vastauksesta [[AGENTTI]]-lohkot ja tallentaa ne ehdotuksiksi (tallenna(teksti) -> tunnus).
    tallenna=None: agenttitehtavat eivat ole kaytossa, lohko korvataan huomautuksella. Katkennut lohko ei tallennu."""
    def korvaa(m):
        if tallenna is None:
            return EI_KAYTOSSA
        try:
            tunnus = tallenna(m.group(1).strip() + "\n")
        except YksityinenVirhe:
            return "[agenttiteht\u00e4v\u00e4\u00e4 ei tallennettu]"
        return ("[Agenttiteht\u00e4v\u00e4n ehdotus tallennettu (tunnus %s). Mit\u00e4\u00e4n ei ole k\u00e4ynnistetty: Tony "
                "p\u00e4\u00e4tt\u00e4\u00e4 k\u00e4ynnistyksest\u00e4 itse.]" % tunnus)
    return KATKENNUT_AGENTTI_RE.sub(lambda m: KATKENNUT_AGENTTI, AGENTTI_RE.sub(korvaa, vastaus))


# --- Loki: aika, tunnus ja tila (ei sisaltoa) -------------------------------------------------------

def kirjaa(hakemisto, tunnus, tila, nyt=_nyt):
    _tunnus(tunnus)
    rivi = {"aika": nyt().isoformat(timespec="seconds"), "tunnus": tunnus, "tila": str(tila)[:40]}
    fd = os.open(Path(hakemisto) / LOKI, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(rivi, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def lue_loki(hakemisto):
    p = Path(hakemisto) / LOKI
    if not p.is_file():
        return []
    ulos = []
    for r in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(r)
        except ValueError:
            continue
        if isinstance(d, dict):
            ulos.append(d)
    return ulos


# --- Kaynnistys --------------------------------------------------------------------------------------

def kirjoita_jonoon(perus, tunnus, teksti, keskustelu):
    """Kirjoittaa ajurin pyynnon jono/<tunnus>.json: ensin piste-alkuinen valiaikainen nimi (0640), sitten nimeys.
    Pyynnossa on vain versio, teksti ja keskustelun tunniste (ajurin tarkistus ajetaan ennen kirjoitusta)."""
    _tunnus(tunnus)
    pyynto = {"versio": agentti_ajuri.VERSIO, "teksti": teksti, "keskustelu": keskustelu}
    try:
        agentti_ajuri.tarkista_syote(pyynto)
    except agentti_ajuri.SyoteVirhe as e:
        raise YksityinenVirhe("pyynt\u00f6 ei kelpaa ajurille: %s" % e) from None
    jono = os.path.join(perus, agentti_ajuri.JONO)
    kohde = os.path.join(jono, tunnus + ".json")
    if os.path.lexists(kohde) or os.path.lexists(os.path.join(perus, agentti_ajuri.TULOKSET, tunnus + ".json")):
        raise YksityinenVirhe("teht\u00e4v\u00e4 on jo jonossa tai ajettu")
    valiaikainen = os.path.join(jono, ".%s.tmp" % tunnus)
    data = json.dumps(pyynto, ensure_ascii=False).encode("utf-8")
    try:
        fd = os.open(valiaikainen, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    except OSError as e:
        raise YksityinenVirhe("jonoon ei voi kirjoittaa (%s)" % type(e).__name__) from None
    try:
        os.fchmod(fd, 0o640)          # palvelun UMask ei saa estaa ajuria lukemasta pyyntoa (ryhma aivo-agentit)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(valiaikainen, kohde)  # ei korvaa olemassa olevaa (toinen kaynnistys samalla tunnuksella)
    except OSError as e:
        raise YksityinenVirhe("jonoon ei voi kirjoittaa (%s)" % type(e).__name__) from None
    finally:
        try:
            os.unlink(valiaikainen)
        except OSError:
            pass


def kaynnista(hakemisto, perus, tunnus, keskustelu, vahvistus, katto_taynna, nyt=_nyt):
    """Tonyn painallus: (1) sha-tarkistus, (2) katto, (3) ehdotus siirretaan kaynnistettyihin (estaa toisen
    kaynnistyksen), (4) pyynto jonoon, (5) lokirivi. Jonovirheessa ehdotus palautetaan odottamaan."""
    d = lue_ehdotus(hakemisto, tunnus, keskustelu)
    if not isinstance(vahvistus, str) or not VAHVISTUS_RE.match(vahvistus) or vahvistus != "kyll\u00e4 " + d["sha"][:8]:
        raise YksityinenVirhe("vahvistus ei t\u00e4sm\u00e4\u00e4; mit\u00e4\u00e4n ei k\u00e4ynnistetty")
    if katto_taynna:
        raise YksityinenVirhe("p\u00e4iv\u00e4katto on t\u00e4ynn\u00e4 tai kulukirjanpitoa ei voi lukea; mit\u00e4\u00e4n ei k\u00e4ynnistetty")
    kaynn = yksityinen.tarkista_yksityinen_hakemisto(Path(hakemisto) / KAYNNISTETYT)
    lahde, kohde = Path(hakemisto) / (tunnus + ".json"), kaynn / (tunnus + ".json")
    try:
        os.link(lahde, kohde)
        os.unlink(lahde)
    except OSError:
        raise YksityinenVirhe("teht\u00e4v\u00e4 on jo k\u00e4ynnistetty") from None
    try:
        kirjoita_jonoon(perus, tunnus, d["teksti"], keskustelu)
    except BaseException:
        try:
            os.link(kohde, lahde)
            os.unlink(kohde)
        except OSError:
            pass
        raise
    kirjaa(hakemisto, tunnus, "k\u00e4ynnistetty", nyt)
    return d["sha"]


# --- Tila ja tulos ------------------------------------------------------------------------------------

def _tuloksen_polku(perus, tunnus):
    return os.path.join(perus, agentti_ajuri.TULOKSET, _tunnus(tunnus) + ".json")


def lue_tulos(perus, tunnus, keskustelu):
    """Ajurin tulos tai None (ei viela valmis). Tuloksen keskustelun pitaa olla sama kuin kaynnistyksessa."""
    p = _tuloksen_polku(perus, tunnus)
    if not os.path.lexists(p):
        return None
    try:
        d = _lue_json(p, TULOS_TAVUT)
    except ValueError:
        raise YksityinenVirhe("tulosta ei voi lukea") from None
    if d.get("tunnus") != tunnus or d.get("keskustelu") not in ("", keskustelu) \
            or d.get("tila") not in agentti_ajuri.TILAT:
        raise YksityinenVirhe("tulos ei kuulu t\u00e4h\u00e4n teht\u00e4v\u00e4\u00e4n")
    return d


def tila(perus, tunnus, keskustelu):
    """("jonossa" | "kaynnissa" | ajurin tila, tulos tai None)."""
    tulos = lue_tulos(perus, tunnus, keskustelu)
    if tulos is not None:
        return tulos["tila"], tulos
    if os.path.lexists(os.path.join(perus, agentti_ajuri.JONO, tunnus + ".json")):
        return JONOSSA, None
    return KAYNNISSA, None


def nayttotulos(tulos):
    """Selaimelle naytettavat kentat (teksti puhdistetaan; selain kayttaa textContentia)."""
    p = yksityinen.puhdista_naytolle
    tark = tulos.get("tarkastus") if isinstance(tulos.get("tarkastus"), dict) else {}
    tiedostot = []
    for t in tulos.get("tiedostot") or []:
        if isinstance(t, dict) and isinstance(t.get("polku"), str) and isinstance(t.get("koko"), int):
            tiedostot.append({"polku": p(t["polku"]), "koko": t["koko"]})
    luku = lambda x: x if isinstance(x, (int, float)) and not isinstance(x, bool) else None   # noqa: E731
    return {"tila": tulos.get("tila"), "syy": p(str(tulos.get("syy") or "")),
            "raportti": p(str(tulos.get("raportti") or "")),
            "arvio": p(str(tark.get("arvio") or "")), "perustelu": p(str(tark.get("perustelu") or "")),
            "tiedostot": tiedostot, "kulu_eur": luku(tulos.get("kulu_eur")),
            "kulu_tuntematon": bool(tulos.get("kulu_tuntematon")), "kutsuja": luku(tulos.get("kutsuja")),
            "kesto_s": luku(tulos.get("kesto_s")), "valmistui": p(str(tulos.get("valmistui") or "")),
            "verkko": _verkko_naytolle(tulos.get("verkko"))}


def _verkko_naytolle(v):
    """Agentin hakulausekkeet ja haetut osoitteet tiloineen (A1101: nakyvat kortissa). Ei sivujen sisaltoa."""
    p = yksityinen.puhdista_naytolle
    v = v if isinstance(v, dict) else {}
    haut = [{"lauseke": p(str(h.get("lauseke") or ""))[:300], "tulos": p(str(h.get("tulos") or ""))[:20],
             "tila": p(str(h.get("tila") or ""))[:40]}
            for h in (v.get("haut") if isinstance(v.get("haut"), list) else [])[:200] if isinstance(h, dict)]
    sivut = [{"url": p(str(s.get("url") or ""))[:2000], "tila": p(str(s.get("tila") or ""))[:40]}
             for s in (v.get("sivut") if isinstance(v.get("sivut"), list) else [])[:200] if isinstance(s, dict)]
    return {"haut": haut, "sivut": sivut}


def tulos_merkinta(tunnus, tila_):
    return "[J\u00e4rjestelm\u00e4: agenttiteht\u00e4v\u00e4 %s p\u00e4\u00e4ttyi tilaan %s. Tulos n\u00e4kyy Tonylle kortissa.]" % (
        tunnus, tila_)


def kaynnistys_merkinta(tunnus, sha8):
    return "[J\u00e4rjestelm\u00e4: Tony k\u00e4ynnisti agenttiteht\u00e4v\u00e4n %s (sha %s).]" % (tunnus, sha8)


def lue_tiedosto(perus, tunnus, keskustelu, polku):
    """Tuloksen tiedosto vain lukien: polun pitaa olla tuloksen tiedostolistassa. Avaus kansio kerrallaan ilman
    linkkeja (O_NOFOLLOW) ajurin kopioista tulokset/<tunnus>/. Palauttaa naytettavan tekstin."""
    tulos = lue_tulos(perus, tunnus, keskustelu)
    if tulos is None:
        raise YksityinenVirhe("teht\u00e4v\u00e4 ei ole valmis")
    try:
        osat = polut.jasenna_polku(polku)
        polut.tarkista_paate(osat)
    except polut.PolkuVirhe:
        raise YksityinenVirhe("tiedostoa ei voi n\u00e4ytt\u00e4\u00e4") from None
    listassa = {t.get("polku") for t in tulos.get("tiedostot") or [] if isinstance(t, dict)}
    if "/".join(osat) not in listassa:
        raise YksityinenVirhe("tiedostoa ei voi n\u00e4ytt\u00e4\u00e4")
    fd = None
    try:
        fd = os.open(os.path.join(perus, agentti_ajuri.TULOKSET), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for osa in [tunnus] + list(osat[:-1]):
            uusi = os.open(osa, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = uusi
        tfd = os.open(osat[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(tfd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise OSError("ei tavallinen tiedosto")
            raaka = f.read(TIEDOSTO_TAVUT + 1)
    except OSError:
        raise YksityinenVirhe("tiedostoa ei voi n\u00e4ytt\u00e4\u00e4") from None
    finally:
        if fd is not None:
            os.close(fd)
    katkaistu = len(raaka) > TIEDOSTO_TAVUT
    teksti = yksityinen.puhdista_naytolle(raaka[:TIEDOSTO_TAVUT].decode("utf-8", "replace"))
    return {"polku": "/".join(osat), "teksti": teksti, "katkaistu": katkaistu}


# --- Kortin kulutiedot ----------------------------------------------------------------------------------

def kulun_arvio(perus, raja=ARVIO_AJOJA):
    """Arvio viimeisimpien ajojen toteutuneista kuluista (mediaani, EUR) tai None, jos dataa ei ole.
    Mukana vain ajot, joissa oli mallikutsuja ja kulu oli tiedossa."""
    kansio = os.path.join(perus, agentti_ajuri.TULOKSET)
    try:
        with os.scandir(kansio) as it:
            ehdokkaat = []
            for e in it:
                if agentti_ajuri.JONONIMI_RE.fullmatch(e.name) and e.is_file(follow_symlinks=False):
                    ehdokkaat.append((e.stat(follow_symlinks=False).st_mtime_ns, e.path))
    except OSError:
        return None
    kulut = []
    for _, p in sorted(ehdokkaat, reverse=True):
        try:
            d = _lue_json(p, TULOS_TAVUT)
        except ValueError:
            continue
        k, n = d.get("kulu_eur"), d.get("kutsuja")
        if isinstance(k, (int, float)) and not isinstance(k, bool) and k >= 0 and isinstance(n, int) and n > 0 \
                and not d.get("kulu_tuntematon"):
            kulut.append(float(k))
        if len(kulut) >= raja:
            break
    if not kulut:
        return None
    kulut.sort()
    m = len(kulut) // 2
    mediaani = kulut[m] if len(kulut) % 2 else (kulut[m - 1] + kulut[m]) / 2
    return {"eur": round(mediaani, 4), "ajoja": len(kulut), "suurin_eur": round(kulut[-1], 4)}
