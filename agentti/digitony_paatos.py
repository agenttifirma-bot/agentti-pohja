"""Digi-Tony paattaa tyonvalintakysymyksia (Tonyn lisahollennys 3.11.2026), kun varmuus on riittava.

Kaytto (agentti tai itsesuunnittelu, ennen kuin kysymys kirjoitetaan Tonylle):
  python3 -m agentti.digitony_paatos kysy <tila> <kysymys> <vaihtoehto1> <vaihtoehto2> [...]
  python3 -m agentti.digitony_paatos kumoa <tila> <tunniste> [huomio]
  python3 -m agentti.digitony_paatos rivi <tila>            aamukoosteen rivi viime vuorokaudesta
Paatosmuisti: ymparistomuuttuja DIGITONY_MUISTI (JSONL, yksityista dataa; ei koskaan julkiseen repoon).

Vastaus on yksi kolmesta: 'paatetty' (Digi-Tony valitsee), 'en_tieda' (kysymys Tonylle) tai 'tonylle' (aihe kielletty).
Rajat ovat koodissa:
  - vain luokka tyonvalinta; raha, kulut, oikeudet, tietoturva ja julkaisu ohjataan aina Tonylle (avainsanatarkistus,
    joka ylikattaa luokittelun: yksikin osuma riittaa)
  - varmuus vahintaan KYNNYS (tiukempi kuin varjotilan 0.25) ja vahintaan MIN_NAAPURIT_LUOKASSA tyonvalintapaatosta perusteena
  - arkaluonteinen teksti (henkilotunnus, avain, terveys) ohjataan Tonylle eika kirjata
  - kumoukset: jos viimeisista KUMOUS_IKKUNA paatoksesta vahintaan KUMOUS_RAJA on kumottu, Digi-Tony lopettaa paattamisen
  - pysaytystiedosto <tila>/PYSAYTA estaa kaiken
Kaikki paatokset (myos en_tieda ja tonylle) kirjataan tiedostoon <tila>/digitony-paatokset.jsonl (vain liitto, 0600).
Koodi on ASCII-muotoista; ihmiselle menevat tekstit \\u-koodein.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from . import digitony as d

SALLITTU_LUOKKA = "tyonvalinta"
KIELLETYT_LUOKAT = ("raha", "kulut", "oikeudet", "tietoturva", "julkaisu")
KYNNYS = 0.6
MIN_NAAPURIT_LUOKASSA = 2
KUMOUS_IKKUNA = 5
KUMOUS_RAJA = 2
LOKI = "digitony-paatokset.jsonl"
KYSYMYS_MAX = 300
PYSAYTUS = "PYSAYTA"


def kielletty_aihe(kysymys, vaihtoehdot):
    """Palauttaa ensimmaisen kielletyn luokan nimen, jonka avainsana esiintyy tekstissa, tai None."""
    teksti = d.normalisoi(" ".join([str(kysymys)] + [str(v) for v in vaihtoehdot]))
    for luokka in KIELLETYT_LUOKAT:
        if any(a in teksti for a in d.LUOKKA_SANAT[luokka]):
            return luokka
    return None


def _lue_loki(tila):
    rivit = []
    try:
        with open(os.path.join(tila, LOKI), encoding="utf-8") as f:
            for r in f:
                try:
                    rivit.append(json.loads(r))
                except ValueError:
                    continue
    except OSError:
        pass
    return rivit


def _kirjaa(tila, rivi):
    os.makedirs(tila, exist_ok=True)
    with d._avaa_liita(os.path.join(tila, LOKI)) as f:
        f.write(json.dumps(rivi, ensure_ascii=True, sort_keys=True) + "\n")


def kumousportti_kiinni(tila):
    """True, jos viimeisista paatetyista (paatetty-tilaisista) KUMOUS_IKKUNA:sta vahintaan KUMOUS_RAJA on kumottu."""
    rivit = _lue_loki(tila)
    kumotut = {r.get("id") for r in rivit if r.get("tyyppi") == "kumoa"}
    viimeiset = [r for r in rivit if r.get("tyyppi") == "paatos" and r.get("tila") == "paatetty"][-KUMOUS_IKKUNA:]
    return sum(1 for r in viimeiset if r.get("id") in kumotut) >= KUMOUS_RAJA


def tunniste(nyt, kysymys, vaihtoehdot):
    h = hashlib.sha256(("%s|%s" % (kysymys, "|".join(vaihtoehdot))).encode("utf-8")).hexdigest()[:6]
    return "%s-%s" % (nyt.strftime("%Y%m%d"), h)


def _vastaus(tila_, tunn, valittu, varmuus, perustelu, luokka="", naapurit=()):
    return {"tila": tila_, "id": tunn, "valittu": valittu, "varmuus": round(varmuus, 3), "perustelu": perustelu,
            "luokka": luokka, "naapurit": list(naapurit)}


def kysy(tila, kysymys, vaihtoehdot, muisti, nyt=None):
    """Palauttaa vastauksen sanakirjana ja kirjaa sen. `muisti` = lataa_muisti-tulos (lista) tai None, jos ei saatavilla."""
    nyt = nyt or datetime.now(timezone.utc)
    vaihtoehdot = [str(v) for v in vaihtoehdot]
    if len(vaihtoehdot) < 2:
        raise ValueError("v\u00e4hint\u00e4\u00e4n kaksi vaihtoehtoa")
    tunn = tunniste(nyt, kysymys, vaihtoehdot)
    if os.path.exists(os.path.join(tila, PYSAYTUS)):
        return _vastaus("tonylle", tunn, None, 0.0, "Digi-Tony on pys\u00e4ytetty (PYSAYTA).")      # ei kirjausta: ajo on pois
    try:
        d.tarkista_turvallinen(kysymys)
        for v in vaihtoehdot:
            d.tarkista_turvallinen(v)
    except d.ArkaluonteinenVirhe:
        return _vastaus("tonylle", tunn, None, 0.0, "Teksti n\u00e4ytt\u00e4\u00e4 arkaluonteiselta: kysymys Tonylle, ei kirjausta.")
    kielto = kielletty_aihe(kysymys, vaihtoehdot)
    luokka = d.luokittele(kysymys, vaihtoehdot)
    if kielto:
        v = _vastaus("tonylle", tunn, None, 1.0, "Aihe kuuluu Tonylle (%s)." % kielto, kielto)
    elif luokka != SALLITTU_LUOKKA:
        v = _vastaus("tonylle", tunn, None, 0.0, "Ei ty\u00f6nvalintakysymys (luokka %s): Digi-Tony ei p\u00e4\u00e4t\u00e4." % luokka, luokka)
    elif kumousportti_kiinni(tila):
        v = _vastaus("tonylle", tunn, None, 0.0, "Tony on kumonnut liian monta viimeisist\u00e4 p\u00e4\u00e4t\u00f6ksist\u00e4: Digi-Tony on tauolla.", luokka)
    elif not muisti:
        v = _vastaus("en_tieda", tunn, None, 0.0, "P\u00e4\u00e4t\u00f6smuistia ei saatu luettua.", luokka)
    else:
        a = d.arvaa(kysymys, vaihtoehdot, muisti, luokka=luokka)
        id_luokat = {m["id"]: d.luokka_avain(m["luokka"]) for m in muisti}
        luokan_naapureita = sum(1 for n in a.naapurit if id_luokat.get(n) == SALLITTU_LUOKKA)
        if a.tila == "arvaus" and a.varmuus >= KYNNYS and luokan_naapureita >= MIN_NAAPURIT_LUOKASSA:
            v = _vastaus("paatetty", tunn, a.valittu, a.varmuus, a.perustelu, luokka, a.naapurit)
        else:
            syy = "Varmuus %.2f (raja %.2f), ty\u00f6nvalintaperusteita %d (v\u00e4hint\u00e4\u00e4n %d)." % (
                a.varmuus, KYNNYS, luokan_naapureita, MIN_NAAPURIT_LUOKASSA)
            v = _vastaus("en_tieda", tunn, None, a.varmuus, syy, luokka, a.naapurit)
            v["paras"] = a.paras
    rivi = dict(v, tyyppi="paatos", aika=nyt.strftime("%Y-%m-%dT%H:%M:%SZ"), kysymys=str(kysymys)[:KYSYMYS_MAX],
                vaihtoehdot=vaihtoehdot)
    _kirjaa(tila, rivi)
    return v


def kumoa(tila, tunn, huomio="", nyt=None):
    nyt = nyt or datetime.now(timezone.utc)
    if not any(r.get("tyyppi") == "paatos" and r.get("id") == tunn and r.get("tila") == "paatetty" for r in _lue_loki(tila)):
        raise KeyError("tunnistetta ei l\u00f6ydy")
    huomio = "".join(c for c in str(huomio) if c >= " ")[:KYSYMYS_MAX]
    d.tarkista_turvallinen(huomio)
    _kirjaa(tila, {"tyyppi": "kumoa", "id": tunn, "aika": nyt.strftime("%Y-%m-%dT%H:%M:%SZ"), "huomio": huomio})


def aamurivi(tila, nyt, tunnit=24):
    """'Digi-Tony p\u00e4\u00e4tti: ..., kumoa: ...' -rivit viime vuorokaudelta (enintaan 3), tai None."""
    raja = nyt - timedelta(hours=tunnit)
    kumotut = {r.get("id") for r in _lue_loki(tila) if r.get("tyyppi") == "kumoa"}
    osat, ei_tiedetty = [], 0
    for r in _lue_loki(tila):
        try:
            aika = datetime.strptime(r["aika"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if r.get("tyyppi") != "paatos" or aika < raja:
            continue
        if r.get("tila") == "paatetty":
            osat.append("Digi-Tony p\u00e4\u00e4tti: %s \u2192 %s%s, kumoa: python3 -m agentti.digitony_paatos kumoa %s %s" % (
                str(r.get("kysymys", ""))[:60], r.get("valittu"), " (kumottu)" if r.get("id") in kumotut else "", tila, r.get("id")))
        else:
            ei_tiedetty += 1
    if not osat and not ei_tiedetty:
        return None
    ulos = osat[:3]
    if ei_tiedetty:
        ulos.append("%d kysymyst\u00e4 j\u00e4i Tonylle (en tied\u00e4 / kielletty aihe)" % ei_tiedetty)
    return "; ".join(ulos)


def main(argv=None):
    a = sys.argv[1:] if argv is None else list(argv)
    try:
        if len(a) >= 5 and a[0] == "kysy":
            polku = os.environ.get("DIGITONY_MUISTI", "")
            try:
                muisti = d.lataa_muisti(polku) if polku else None
            except (OSError, d.MuistiVirhe) as e:
                print("muisti: ei luettavissa (%s)" % type(e).__name__, file=sys.stderr)
                muisti = None
            v = kysy(a[1], a[2], a[3:], muisti)
            print(json.dumps(v, ensure_ascii=False, sort_keys=True))
            return 0
        if len(a) >= 3 and a[0] == "kumoa":
            kumoa(a[1], a[2], " ".join(a[3:]))
            print("kumottu: " + a[2])
            return 0
        if len(a) == 2 and a[0] == "rivi":
            print(aamurivi(a[1], datetime.now(timezone.utc)) or "")
            return 0
    except (ValueError, KeyError, d.ArkaluonteinenVirhe) as e:
        print("VIRHE: %s" % type(e).__name__)
        return 1
    print("k\u00e4ytt\u00f6: python3 -m agentti.digitony_paatos kysy <tila> <kysymys> <vaihtoehto> <vaihtoehto> ... | kumoa <tila> <tunniste> | rivi <tila>")
    return 2


if __name__ == "__main__":
    sys.exit(main())
