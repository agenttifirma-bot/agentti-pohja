"""Kulutusmittari: jokaisesta ajosta rivi tiedostoon <tila>/kulutus.jsonl, koonti aamukoosteeseen ja laatu malleittain.

Rivi: {aika, tehtava, malli, reitti, ok, input, output, cache_luku, cache_luonti, kesto_s, usd, usd_peruste, rate_limit}.
  - reitti `claude`: luvut tulevat `claude -p --output-format json` -tulosteesta (usage, total_cost_usd, duration_ms). Tilauksessa
    usd on API-hinnaston mukainen arvio (costBasis=list), ei veloitus: se on vertailuluku mallien ja viikkojen valille.
  - reitti `openrouter`: luvut LiteLLM-vastauksesta, usd otsakkeesta x-litellm-response-cost (todellinen veloitus).
Kirjaus ei saa kaataa ajoa: virhe tulostaa vain tyypin nimen.

Kaytto:
  python3 -m claudejono.kulutus koonti [--tila POLKU]      tulostaa aamukoosteen kulutusrivin
  python3 -m claudejono.kulutus laatu [--tila POLKU]       ok-osuus malleittain + siirtoehdotus
  python3 -m claudejono.kulutus kalibroi PROSENTTI         tallentaa asetussivun "Talla viikolla x % kaytetty" -luvun
"""
import argparse
import fcntl
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Helsinki")
OLETUS_TILA = "/var/lib/claude-jono"
KULUTUS_TIEDOSTO = "kulutus.jsonl"
KALIBROINTI_TIEDOSTO = "kalibrointi.jsonl"
LAATU_MIN_AJOJA = 5          # alle taman ei tehda johtopaatosta mallin virheprosentista
LAATU_ERO_PROSENTTIYKSIKKOA = 15
LAATU_ERO_KERTOIMENA = 2.0


def tila_hakemisto(env=None):
    return Path((os.environ if env is None else env).get("CLAUDEJONO_TILA", OLETUS_TILA))


def _int(arvo):
    try:
        return max(0, int(arvo))
    except (TypeError, ValueError):
        return 0


def _usd(arvo):
    try:
        return float(arvo) if arvo is not None else None
    except (TypeError, ValueError):
        return None


def rivi_claude(tehtava, malli, d, kesto_s, ok, nyt=None, rate_limit=False):
    """Kulutusrivi `claude -p --output-format json` -tulosteesta d (dict tai None, jos tuloste oli lukukelvoton)."""
    d = d if isinstance(d, dict) else {}
    u = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    kesto = d.get("duration_ms")
    return {"aika": (nyt or datetime.now(TZ)).isoformat(timespec="seconds"), "tehtava": tehtava, "malli": malli, "reitti": "claude",
            "ok": bool(ok), "input": _int(u.get("input_tokens")), "output": _int(u.get("output_tokens")),
            "cache_luku": _int(u.get("cache_read_input_tokens")), "cache_luonti": _int(u.get("cache_creation_input_tokens")),
            "kesto_s": round(kesto / 1000, 1) if isinstance(kesto, (int, float)) else round(kesto_s, 1),
            "usd": _usd(d.get("total_cost_usd")), "usd_peruste": "api-hinnasto", "rate_limit": bool(rate_limit)}


def rivi_openrouter(tehtava, alias, tulos, kesto_s, ok, nyt=None):
    """tulos = malli.openrouter_kutsu:n paluuarvo tai None (kutsu epaonnistui)."""
    tulos = tulos or {}
    return {"aika": (nyt or datetime.now(TZ)).isoformat(timespec="seconds"), "tehtava": tehtava, "malli": f"openrouter:{alias}",
            "reitti": "openrouter", "ok": bool(ok), "input": _int(tulos.get("input")), "output": _int(tulos.get("output")),
            "cache_luku": 0, "cache_luonti": 0, "kesto_s": round(kesto_s, 1), "usd": _usd(tulos.get("usd")),
            "usd_peruste": "litellm", "rate_limit": False}


def kirjaa(tila, rivi):
    """Liittaa rivin kulutus.jsonl:aan (flock). True jos onnistui; virhe ei kaada ajoa."""
    try:
        polku = Path(tila) / KULUTUS_TIEDOSTO
        polku.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(rivi, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(polku, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except (OSError, TypeError, ValueError) as virhe:
        print(f"kulutus: kirjaus epaonnistui ({type(virhe).__name__})", file=sys.stderr)
        return False


def lue(tila, tiedosto=KULUTUS_TIEDOSTO):
    """Rivit, joissa on kelvollinen aika. Rikkinaiset rivit ohitetaan."""
    ulos = []
    try:
        teksti = (Path(tila) / tiedosto).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ulos
    for rivi in teksti.splitlines():
        try:
            d = json.loads(rivi)
            d["_aika"] = datetime.fromisoformat(d["aika"])
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(d, dict):
            if d["_aika"].tzinfo is None:
                d["_aika"] = d["_aika"].replace(tzinfo=TZ)
            ulos.append(d)
    return ulos


def viikon_alku(nyt):
    """Maanantai 00:00 Helsingin aikaa. Oletus: tilauksen todellista nollautumishetkea ei voi lukea koneellisesti."""
    p = nyt.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return p - timedelta(days=p.weekday())


def _summaa(rivit):
    s = defaultdict(lambda: {"ajoja": 0, "usd": 0.0, "usd_puuttuu": 0, "tokenit": 0})
    for r in rivit:
        a = s[r.get("malli", "?")]
        a["ajoja"] += 1
        if isinstance(r.get("usd"), (int, float)):
            a["usd"] += r["usd"]
        else:
            a["usd_puuttuu"] += 1
        a["tokenit"] += _int(r.get("input")) + _int(r.get("output")) + _int(r.get("cache_luku")) + _int(r.get("cache_luonti"))
    return dict(s)


def koonti(rivit, nyt):
    """{eilen: {malli: summat}, viikko: {...}} (Helsingin kalenteripaiva eilen ja viikko maanantaista nykyhetkeen)."""
    tanaan = nyt.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    eilen_alku = tanaan - timedelta(days=1)
    viikko_alku = viikon_alku(nyt)
    eilen = [r for r in rivit if eilen_alku <= r["_aika"] < tanaan]
    viikko = [r for r in rivit if viikko_alku <= r["_aika"] <= nyt]
    return {"eilen": _summaa(eilen), "viikko": _summaa(viikko)}


def _desim(x):
    return f"{x:.2f}".replace(".", ",")


def _ajoja(n):
    return f"{n} ajo" if n == 1 else f"{n} ajoa"


def _osa(summat):
    if not summat:
        return "ei ajoja"
    return ", ".join(f"{m} {_ajoja(a['ajoja'])} {_desim(a['usd'])} USD" + ("*" if a["usd_puuttuu"] else "")
                     for m, a in sorted(summat.items()))


def kulutusrivi(k):
    """Aamukoosteen kulutusosa: eilinen ja viikon kertyma malleittain. `*` = osalta ajoista hinta puuttui."""
    teksti = f"Mallikulutus eilen: {_osa(k['eilen'])}; viikko: {_osa(k['viikko'])} (Claude-hinnat API-hinnaston arvioita)"
    if any(a["usd_puuttuu"] for jakso in k.values() for a in jakso.values()):
        teksti += ", * = hinta puuttui osalta ajoista"
    return teksti + "."


def laatu(rivit):
    """{malli: {ajoja, ok, ok_osuus}} ja ehdotuslista. Ehdotus vain jos halvan mallin (openrouter) virheprosentti on selvasti
    Sonnetin ylla: vahintaan LAATU_MIN_AJOJA ajoa molemmilla ja ero >= 15 %-yks. seka >= 2-kertainen."""
    ajot = defaultdict(lambda: [0, 0])
    for r in rivit:
        if r.get("rate_limit"):
            continue   # kayttorajapysaytys ei kerro mallin laadusta
        a = ajot[r.get("malli", "?")]
        a[0] += 1
        a[1] += 1 if r.get("ok") else 0
    tulos = {m: {"ajoja": n, "ok": ok, "virhe_osuus": (n - ok) / n} for m, (n, ok) in ajot.items() if n}
    ehdotukset = []
    vert = tulos.get("sonnet")
    for m, t in sorted(tulos.items()):
        if not m.startswith("openrouter:") or t["ajoja"] < LAATU_MIN_AJOJA or not vert or vert["ajoja"] < LAATU_MIN_AJOJA:
            continue
        ero = t["virhe_osuus"] - vert["virhe_osuus"]
        if ero * 100 >= LAATU_ERO_PROSENTTIYKSIKKOA and t["virhe_osuus"] >= LAATU_ERO_KERTOIMENA * max(vert["virhe_osuus"], 0.01):
            ehdotukset.append(f"{m}: virheprosentti {round(t['virhe_osuus'] * 100)} % ({t['ajoja']} ajoa) vs. sonnet "
                              f"{round(vert['virhe_osuus'] * 100)} % ({vert['ajoja']} ajoa). Ehdotus Tonylle: siirr\u00e4 mallin teht\u00e4v\u00e4t Sonnetille.")
    return tulos, ehdotukset


def laatuteksti(rivit):
    tulos, ehd = laatu(rivit)
    if not tulos:
        return "Laatu malleittain: ei ajoja."
    osat = [f"{m} {t['ok']}/{t['ajoja']} onnistui" for m, t in sorted(tulos.items())]
    return "Laatu malleittain: " + "; ".join(osat) + ("\n" + "\n".join(ehd) if ehd else ".")


# --- LiteLLM-kirjanpito (kaikkien agenttien OpenRouter-kulut) ---

def litellm_kulut(env, nyt, hae=None):
    """OpenRouter-kulut LiteLLM:n kirjanpidosta (GET /spend/logs): {malli: usd} eilen. None jos avainta ei ole tai haku epaonnistuu.
    Vastausrakenne luetaan toleranssilla (rivilista, kentat model/spend); sen tarkkaa muotoa ei ole varmennettu avaimella."""
    avain = env.get("LITELLM_API_KEY", "")
    if not avain:
        return None
    pohja = env.get("LITELLM_BASE_URL", "http://192.168.1.116:4000").rstrip("/")
    eilen = (nyt.astimezone(TZ) - timedelta(days=1)).date()
    url = f"{pohja}/spend/logs?start_date={eilen.isoformat()}&end_date={nyt.astimezone(TZ).date().isoformat()}"
    try:
        data = (hae or _hae_json)(url, avain)
    except Exception as virhe:
        print(f"litellm-kulut: haku epaonnistui ({type(virhe).__name__})", file=sys.stderr)
        return None
    if not isinstance(data, list):
        return None
    ulos = defaultdict(float)
    for r in data:
        if not isinstance(r, dict) or not isinstance(r.get("spend"), (int, float)):
            continue
        try:
            alku = datetime.fromisoformat(str(r.get("startTime", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if alku.tzinfo is None:
            alku = alku.replace(tzinfo=ZoneInfo("UTC"))
        if alku.astimezone(TZ).date() == eilen:
            ulos[str(r.get("model") or "?")] += float(r["spend"])
    return dict(ulos)


def _hae_json(url, avain):
    import urllib.request
    pyynto = urllib.request.Request(url, headers={"Authorization": "Bearer " + avain})
    with urllib.request.urlopen(pyynto, timeout=15) as v:
        return json.loads(v.read().decode("utf-8"))


def litellmrivi(ll):
    if ll is None:
        return "OpenRouter (LiteLLM) eilen: kirjanpitoa ei saatu luettua."
    if not ll:
        return "OpenRouter (LiteLLM) eilen: ei kulua."
    return "OpenRouter (LiteLLM) eilen: " + ", ".join(f"{m} {_desim(v)} USD" for m, v in sorted(ll.items())) + "."


def kalibroi(tila, prosentti, nyt=None):
    """Tallentaa asetussivun viikkoluvun. Nostaa ValueError, jos luku ei ole valilla 0-100."""
    p = float(str(prosentti).replace(",", ".").replace("%", ""))
    if not 0 <= p <= 100:
        raise ValueError("prosentin pitaa olla 0-100")
    polku = Path(tila) / KALIBROINTI_TIEDOSTO
    polku.parent.mkdir(parents=True, exist_ok=True)
    rivi = json.dumps({"aika": (nyt or datetime.now(TZ)).isoformat(timespec="seconds"), "prosentti": p})
    with open(polku, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(rivi + "\n")
    return p


def main(argv=None):
    p = argparse.ArgumentParser(description="Claude-jonon kulutusmittari")
    p.add_argument("komento", choices=["koonti", "laatu", "kalibroi"])
    p.add_argument("arvo", nargs="?")
    p.add_argument("--tila", default=str(tila_hakemisto()))
    a = p.parse_args(argv)
    nyt = datetime.now(TZ)
    if a.komento == "kalibroi":
        if a.arvo is None:
            print("kaytto: kulutus kalibroi PROSENTTI", file=sys.stderr)
            return 2
        try:
            print(f"Tallennettu: {kalibroi(a.tila, a.arvo, nyt)} %")
        except ValueError:
            print("virhe: anna luku valilta 0-100", file=sys.stderr)
            return 2
        return 0
    rivit = lue(a.tila)
    print(kulutusrivi(koonti(rivit, nyt)) if a.komento == "koonti" else laatuteksti(rivit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
