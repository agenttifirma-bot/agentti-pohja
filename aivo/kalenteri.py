"""Aivo: kalenterin luku (vain luku). Osa 1: moduuli ilman kytkentaa chattiin.

Lahderajapinta: `Lahde.tapahtumat(alku, loppu)` palauttaa listan sanakirjoja
{otsikko, alku, loppu, paikka, koko_paiva}, alkamisajan mukaan jarjestettyna.
Ensimmainen toteutus on `IcalLahde` (Googlen salainen iCal-osoite).

Turvarajat:
  * Osoite luetaan tiedostosta (oletus /etc/aivo/kalenteri-ical). Tiedoston pitaa olla tavallinen tiedosto,
    jota vain omistaja voi lukea (ei ryhma- eika muiden oikeuksia).
  * Sallittu on vain https ja vain isanta calendar.google.com (portti 443). Uudelleenohjauksia ei seurata.
  * Osoitetta ei koskaan tulosteta, kirjata lokiin eika laiteta virheilmoitukseen: virheilmoitukset ovat
    kiinteita tekstejae, ja ulkoisista poikkeuksista kirjataan vain tyypin nimi.
  * Vastaus on enintaan MAX_TAVUA tavua ja haulla on aikaraja.
  * Valimuisti on datakansiossa (kansio 0700, tiedosto 0600); verkkoon mennaan enintaan 15 minuutin valein.
  * Kalenterin sisalto on dataa, ei ohjeita.

Rajoitukset (RRULE): tuettu on FREQ=DAILY ja FREQ=WEEKLY (INTERVAL, COUNT, UNTIL, BYDAY viikkotoistolle),
EXDATE ja RECURRENCE-ID-poikkeukset. Muut FREQ-arvot (MONTHLY, YEARLY, ...) eivat laajene: tapahtuma
nakyy vain ensimmaisena esiintymanaan. Vain stdlib."""
import logging
import os
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOG = logging.getLogger("aivo.kalenteri")

OLETUS_OSOITETIEDOSTO = "/etc/aivo/kalenteri-ical"
OLETUS_DATAKANSIO = "/var/lib/aivo/kalenteri"
VALIMUISTI_TIEDOSTO = "kalenteri.ics"
SALLITTU_ISANTA = "calendar.google.com"
VALIMUISTI_VALI_S = 15 * 60
AIKARAJA_S = 10
MAX_TAVUA = 2_000_000
MAX_OSOITE_TAVUA = 2000
MAX_ESIINTYMIA = 2000           # yhden toistuvan tapahtuman esiintymien ylaraja haussa
TZ = ZoneInfo("Europe/Helsinki")
UTC = timezone.utc
PAIVAT = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class KalenteriVirhe(Exception):
    """Odotettu virhe. Viesti on aina kiintea ja turvallinen tulostaa (ei osoitetta, ei sisaltoa)."""


# --- Osoite ------------------------------------------------------------------------------------

def tarkista_osoite(osoite):
    """Palauttaa osoitteen, jos se on https ja isanta on tasmalleen calendar.google.com. Muuten KalenteriVirhe."""
    if not isinstance(osoite, str) or not osoite or len(osoite) > MAX_OSOITE_TAVUA:
        raise KalenteriVirhe("kalenteriosoite on virheellinen")
    if any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in osoite):
        raise KalenteriVirhe("kalenteriosoite on virheellinen")
    try:
        u = urllib.parse.urlsplit(osoite)
        isanta = u.hostname
        portti = u.port
    except ValueError:
        raise KalenteriVirhe("kalenteriosoite on virheellinen")
    if u.scheme != "https":
        raise KalenteriVirhe("kalenteriosoitteen pitaa olla https")
    if u.username is not None or u.password is not None:
        raise KalenteriVirhe("kalenteriosoite on virheellinen")
    if isanta != SALLITTU_ISANTA or portti not in (None, 443):
        raise KalenteriVirhe("kalenteriosoitteen isanta ei ole sallittu")
    return osoite


def lue_osoite(polku=OLETUS_OSOITETIEDOSTO):
    """Lukee osoitteen tiedostosta. Tiedoston oikeudet tarkistetaan; sisaltoa ei koskaan nayteta."""
    try:
        fd = os.open(str(polku), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise KalenteriVirhe("osoitetiedostoa ei voi lukea (%s)" % type(e).__name__)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise KalenteriVirhe("osoitetiedosto ei ole tavallinen tiedosto")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise KalenteriVirhe("osoitetiedoston oikeudet ovat liian laajat (pitaa olla 600)")
        if st.st_size > MAX_OSOITE_TAVUA + 10:
            raise KalenteriVirhe("kalenteriosoite on virheellinen")
        data = os.read(fd, MAX_OSOITE_TAVUA + 10)
    except OSError as e:
        raise KalenteriVirhe("osoitetiedostoa ei voi lukea (%s)" % type(e).__name__)
    finally:
        os.close(fd)
    try:
        teksti = data.decode("ascii").strip()
    except UnicodeDecodeError:
        raise KalenteriVirhe("kalenteriosoite on virheellinen")
    return tarkista_osoite(teksti)


# --- Haku ja valimuisti ------------------------------------------------------------------------

class _EiUudelleenohjausta(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def hae_https(osoite, aikaraja=AIKARAJA_S, ylaraja=MAX_TAVUA):
    """Hakee osoitteen (GET). Osoite tarkistetaan uudelleen; virheistae kerrotaan vain tyyppi tai HTTP-tila."""
    tarkista_osoite(osoite)
    opener = urllib.request.build_opener(_EiUudelleenohjausta)
    try:
        with opener.open(urllib.request.Request(osoite, method="GET"), timeout=aikaraja) as r:
            if r.status != 200:
                raise KalenteriVirhe("haku epaonnistui (HTTP %d)" % r.status)
            data = r.read(ylaraja + 1)
    except KalenteriVirhe:
        raise
    except urllib.error.HTTPError as e:
        e.close()                                   # vapauttaa virhevastauksen socketin
        raise KalenteriVirhe("haku epaonnistui (HTTP %d)" % e.code)
    except Exception as e:
        raise KalenteriVirhe("haku epaonnistui (%s)" % type(e).__name__)
    if len(data) > ylaraja:
        raise KalenteriVirhe("vastaus on liian suuri")
    if b"BEGIN:VCALENDAR" not in data[:2000].upper():
        raise KalenteriVirhe("vastaus ei ole iCal-tiedosto")
    return data


def _kirjoita_valimuisti(polku, data):
    kansio = os.path.dirname(polku)
    os.makedirs(kansio, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=kansio, prefix=".kal-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, polku)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- ICS-jasennin ------------------------------------------------------------------------------

def _pura_teksti(arvo):
    ulos, i = [], 0
    while i < len(arvo):
        c = arvo[i]
        if c == "\\" and i + 1 < len(arvo):
            n = arvo[i + 1]
            ulos.append("\n" if n in "nN" else n)
            i += 2
        else:
            ulos.append(c)
            i += 1
    return "".join(ulos)


def _rivit(teksti):
    """Purkaa rivitaiton (jatkorivi alkaa valilyonnilla tai tabulaattorilla) ja palauttaa (nimi, parametrit, arvo)."""
    raaka = teksti.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    yhdistetty = []
    for r in raaka:
        if r[:1] in (" ", "\t") and yhdistetty:
            yhdistetty[-1] += r[1:]
        else:
            yhdistetty.append(r)
    for r in yhdistetty:
        if ":" not in r:
            continue
        vasen, arvo = _jaa_kaksoispiste(r)
        osat = vasen.split(";")
        nimi = osat[0].upper()
        param = {}
        for p in osat[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                param[k.upper()] = v.strip('"')
        yield nimi, param, arvo


def _jaa_kaksoispiste(r):
    """Jakaa rivin ensimmaisesta kaksoispisteesta, joka ei ole lainausmerkkien sisalla."""
    lainaus = False
    for i, c in enumerate(r):
        if c == '"':
            lainaus = not lainaus
        elif c == ":" and not lainaus:
            return r[:i], r[i + 1:]
    return r, ""


def _tz(param):
    nimi = param.get("TZID")
    if not nimi:
        return TZ
    try:
        return ZoneInfo(nimi)
    except Exception:
        return TZ


def _aika(arvo, param):
    """Palauttaa (date tai datetime, koko_paiva). Aikavyohykkeellinen aika on aware, kellonaika paikallinen."""
    arvo = arvo.strip()
    if param.get("VALUE", "").upper() == "DATE" or (len(arvo) == 8 and arvo.isdigit()):
        return datetime.strptime(arvo[:8], "%Y%m%d").date(), True
    if arvo.endswith("Z"):
        return datetime.strptime(arvo[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False
    return datetime.strptime(arvo, "%Y%m%dT%H%M%S").replace(tzinfo=_tz(param)), False


def _kesto(arvo):
    """ISO 8601 -kesto (P1DT2H30M, P1W) timedeltaksi."""
    a = arvo.strip().upper().lstrip("+")
    if not a.startswith("P"):
        raise ValueError("kesto")
    a, aika, luku, td = a[1:], False, "", timedelta()
    yksikot = {"W": "weeks", "D": "days", "H": "hours", "M": "minutes", "S": "seconds"}
    for c in a:
        if c == "T":
            aika = True
        elif c.isdigit():
            luku += c
        elif c in yksikot and luku and not (c == "M" and not aika):
            td += timedelta(**{yksikot[c]: int(luku)})
            luku = ""
        else:
            raise ValueError("kesto")
    return td


def _rrule(arvo):
    r = {}
    for osa in arvo.split(";"):
        if "=" in osa:
            k, v = osa.split("=", 1)
            r[k.upper()] = v.upper()
    return r


class _Raaka:
    def __init__(self):
        self.k = {}  # nimi -> lista (param, arvo)

    def lisaa(self, nimi, param, arvo):
        self.k.setdefault(nimi, []).append((param, arvo))

    def yksi(self, nimi):
        v = self.k.get(nimi)
        return v[0] if v else None


def _tapahtumat_raaka(teksti):
    sisalla, nyt, ulos = False, None, []
    for nimi, param, arvo in _rivit(teksti):
        if nimi == "BEGIN" and arvo.strip().upper() == "VEVENT":
            sisalla, nyt = True, _Raaka()
        elif nimi == "END" and arvo.strip().upper() == "VEVENT":
            if nyt is not None:
                ulos.append(nyt)
            sisalla, nyt = False, None
        elif sisalla and nyt is not None:
            nyt.lisaa(nimi, param, arvo)
    return ulos


def _paikalliseksi(x, koko_paiva):
    """Vertailua varten: koko paiva -> datetime paikallisessa ajassa; aware -> sellaisenaan."""
    if koko_paiva:
        return datetime.combine(x, time.min, tzinfo=TZ)
    return x


def _esiintymat(raaka, alku_pv, loppu_pv):
    """Tuottaa esiintymien alkuhetket (date tai aware datetime), jotka voivat osua valille alku_pv..loppu_pv."""
    p, arvo = raaka.yksi("DTSTART")
    a, koko = _aika(arvo, p)
    rr = raaka.yksi("RRULE")
    if rr is None:
        yield a
        return
    r = _rrule(rr[1])
    freq = r.get("FREQ")
    if freq not in ("DAILY", "WEEKLY"):
        yield a  # rajoitus: muita toistoja ei laajenneta
        return
    try:
        vali = max(1, int(r.get("INTERVAL", "1")))
        maara = int(r["COUNT"]) if "COUNT" in r else None
    except ValueError:
        yield a
        return
    until = None
    if "UNTIL" in r:
        u, ukoko = _aika(r["UNTIL"], {})
        until = _paikalliseksi(u, ukoko)
        if ukoko:
            until += timedelta(days=1) - timedelta(microseconds=1)
    alku_d = a if koko else a.date()
    paivat = None
    if freq == "WEEKLY":
        paivat = sorted(PAIVAT[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in PAIVAT) or [alku_d.weekday()]
    laskuri = 0
    viikko0 = alku_d - timedelta(days=alku_d.weekday())
    n = 0
    while n < 20000:
        if freq == "DAILY":
            ehdokkaat = [alku_d + timedelta(days=n * vali)]
        else:
            vk = viikko0 + timedelta(weeks=n * vali)
            ehdokkaat = [vk + timedelta(days=d) for d in paivat]
        n += 1
        for d in ehdokkaat:
            if d < alku_d:
                continue
            esiintyma = d if koko else datetime.combine(d, a.timetz().replace(tzinfo=None), tzinfo=a.tzinfo)
            if until is not None and _paikalliseksi(esiintyma, koko) > until:
                return
            if maara is not None and laskuri >= maara:
                return
            laskuri += 1
            if d > loppu_pv:
                return
            if d >= alku_pv - timedelta(days=2):
                yield esiintyma


def _poissa(raaka):
    """EXDATE-arvot joukkona (date tai aware datetime UTC-muunnettuna vertailua varten)."""
    s = set()
    for p, arvo in raaka.k.get("EXDATE", []):
        for osa in arvo.split(","):
            try:
                x, koko = _aika(osa, p)
            except ValueError:
                continue
            s.add(x if koko else x.astimezone(UTC))
    return s


def _avain(x):
    return x if isinstance(x, date) and not isinstance(x, datetime) else x.astimezone(UTC)


def jasenna_ics(teksti, alku, loppu):
    """Palauttaa tapahtumat, jotka osuvat valille [alku, loppu). alku ja loppu ovat aware-datetimeja."""
    if alku.tzinfo is None or loppu.tzinfo is None:
        raise ValueError("alku ja loppu pitaa olla aikavyohykkeellisia")
    raakat = _tapahtumat_raaka(teksti)
    alku_pv = alku.astimezone(TZ).date()
    loppu_pv = loppu.astimezone(TZ).date()
    poikkeukset = {}  # (uid, alkuperainen alku) -> raaka
    for rk in raakat:
        rid, uid = rk.yksi("RECURRENCE-ID"), rk.yksi("UID")
        if rid and uid:
            try:
                x, _ = _aika(rid[1], rid[0])
            except ValueError:
                continue
            poikkeukset[(uid[1], _avain(x))] = rk
    tulos = []
    for rk in raakat:
        try:
            tulos.extend(_yksi_tapahtuma(rk, alku, loppu, alku_pv, loppu_pv, poikkeukset))
        except (ValueError, KeyError, OverflowError):
            continue  # viallinen tapahtuma ohitetaan, muut jatkavat
    tulos.sort(key=lambda t: (_paikalliseksi(t["alku"], t["koko_paiva"]), t["otsikko"]))
    return tulos


def _yksi_tapahtuma(rk, alku, loppu, alku_pv, loppu_pv, poikkeukset):
    if rk.yksi("DTSTART") is None:
        return []
    uid = rk.yksi("UID")
    if rk.yksi("RECURRENCE-ID"):
        esiintymat = [_aika(rk.yksi("DTSTART")[1], rk.yksi("DTSTART")[0])[0]]
        rid = False
    else:
        esiintymat = list(_esiintymat(rk, alku_pv, loppu_pv))
        rid = True
    p, arvo = rk.yksi("DTSTART")
    a0, koko = _aika(arvo, p)
    kesto = None
    if rk.yksi("DTEND"):
        pe, ae = rk.yksi("DTEND")
        l0, _ = _aika(ae, pe)
        kesto = l0 - a0
    elif rk.yksi("DURATION"):
        kesto = _kesto(rk.yksi("DURATION")[1])
    if kesto is None or kesto < timedelta(0):
        kesto = timedelta(days=1) if koko else timedelta(0)
    if koko:
        kesto = timedelta(days=max(1, kesto.days))
    poissa = _poissa(rk)
    ulos = []
    for e in esiintymat:
        if rid:
            if _avain(e) in poissa:
                continue
            if uid and (uid[1], _avain(e)) in poikkeukset:
                continue  # poikkeus korvaa esiintyman
        l = e + kesto
        a_vert, l_vert = _paikalliseksi(e, koko), _paikalliseksi(l, koko)
        osuu = (a_vert < loppu and l_vert > alku) if l_vert > a_vert else (alku <= a_vert < loppu)
        if not osuu:
            continue
        if (rk.yksi("STATUS") or ({}, ""))[1].strip().upper() == "CANCELLED":
            continue
        otsikko = _pura_teksti((rk.yksi("SUMMARY") or ({}, ""))[1]).strip() or "(ei otsikkoa)"
        paikka = _pura_teksti((rk.yksi("LOCATION") or ({}, ""))[1]).strip()
        ulos.append({
            "otsikko": otsikko,
            "alku": e if koko else e.astimezone(TZ),
            "loppu": l if koko else l.astimezone(TZ),
            "paikka": paikka,
            "koko_paiva": koko,
        })
    return ulos


# --- Lahteet -----------------------------------------------------------------------------------

class Lahde:
    """Lahderajapinta: myohemmin voidaan lisata esim. Googlen rajapintaan perustuva toteutus."""

    def tapahtumat(self, alku, loppu):
        raise NotImplementedError


class IcalLahde(Lahde):
    def __init__(self, osoitetiedosto=OLETUS_OSOITETIEDOSTO, datakansio=OLETUS_DATAKANSIO,
                 hae=hae_https, nyt=None, vali_s=VALIMUISTI_VALI_S):
        self.osoitetiedosto = osoitetiedosto
        self.valimuisti = os.path.join(str(datakansio), VALIMUISTI_TIEDOSTO)
        self._hae = hae
        self._nyt = nyt or (lambda: datetime.now(UTC))
        self.vali_s = vali_s
        self._viimeinen_yritys = None

    def _tuore(self):
        try:
            ika = self._nyt().timestamp() - os.stat(self.valimuisti).st_mtime
        except OSError:
            return False
        return 0 <= ika < self.vali_s

    def _teksti(self):
        nyt = self._nyt()
        yritetty = self._viimeinen_yritys is not None and 0 <= (nyt - self._viimeinen_yritys).total_seconds() < self.vali_s
        if not self._tuore() and not yritetty:
            self._viimeinen_yritys = nyt
            try:
                data = self._hae(lue_osoite(self.osoitetiedosto))
                _kirjoita_valimuisti(self.valimuisti, data)
            except KalenteriVirhe as e:
                LOG.warning("kalenterin haku epaonnistui: %s", e)
                if not os.path.exists(self.valimuisti):
                    raise
            except OSError as e:
                LOG.warning("valimuistin kirjoitus epaonnistui (%s)", type(e).__name__)
                raise KalenteriVirhe("valimuistia ei voi kirjoittaa (%s)" % type(e).__name__)
        try:
            with open(self.valimuisti, "rb") as f:
                return f.read(MAX_TAVUA + 1).decode("utf-8", "replace")
        except OSError as e:
            raise KalenteriVirhe("valimuistia ei voi lukea (%s)" % type(e).__name__)

    def tapahtumat(self, alku, loppu):
        return jasenna_ics(self._teksti(), alku, loppu)
