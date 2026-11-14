"""Jonon vahti: halyttaa ja kaynnistaa korjaajan, jos jono on pysahtynyt (tehtava 2026-11-04, doc 71).

Tausta: 20 tunnin katkos jai huomaamatta. Vahti ajetaan ajastimella 15 min valein (root, kapea tehtava).
Se ei muuta jonon tilaa, katto-, budjetti- eika oikeusarvoja. Se vain lukee ja ilmoittaa.

Paatos (`tarkista`):
  - terve: tehtava- tai suunnitteluajo on valmistunut (`ok`) viimeisen 2 h aikana kaistalokissa
  - tauolla: jono on tarkoituksella paikoillaan (pysaytystiedosto, kayttorajan tauko, kulutusjarru/varaus tai tyhja jono)
  - pysahtynyt: ei kumpaakaan -> Telegram-viesti + korjaajan kaynnistys, enintaan kerran 2 h aikana
  - ei_dataa: kaistalokia ei ole tai se on tyhja; ei halyteta (uusi asennus), mutta ei myoskaan pingata

Uptime Kuma: osoite luetaan ymparistomuuttujasta CLAUDEJONO_KUMA_PUSH_URL (/etc/claude-jono/asetukset.env, ei repoon).
Ping lahtee vain, kun jono on terve tai tauolla. Pysahtyneena pingia ei laheta, jolloin Kuma halyttaa myos silloin,
kun koko CT115 tai tama ajastin on alhaalla. Osoitetta ei tulosteta eika kirjata; virheista naytetaan vain tyyppi.

Kaytto:
  python3 -m claudejono.vahti            # tarkistus + toimet (ajastin)
  python3 -m claudejono.vahti --kuiva    # vain tulos, ei viestia, ei korjaajaa, ei pingia
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from . import ajuri, varaus

OLETUS_TILA = "/var/lib/claude-jono"
OLETUS_TYOHAK = "/opt/agentscope"
RAJA_S = 2 * 3600            # nain kauan ilman valmista ajoa = pysahtynyt
TOISTOESTE_S = 2 * 3600      # sama halytys enintaan kerran 2 h sisalla
TILA_TIEDOSTO = "vahti-tila.json"
PYSAYTYS_TIEDOSTO = "pysayta"   # Tony luo taman (touch), kun jono pysaytetaan tarkoituksella
LUKU_TAVUA = 256 * 1024         # kaistalokista luetaan vain loppu
KORJAAJA_YKSIKKO = "korjaaja@claude-jono.service.service"   # sama nimi kuin README:n kuivakokeessa; yksikko on valvottu
KUMA_AIKARAJA_S = 10
KAISTAJARJESTELMA_AJASTIMET = ("claude-jono@1.timer", "claude-jono@2.timer", "claude-jono@3.timer")


def viimeisin_valmis(tila, nyt_s):
    """Viimeisen onnistuneen tehtava- tai suunnitteluajon epoch-aika, tai None. Rikkinainen rivi ohitetaan."""
    polku = Path(tila) / ajuri.KAISTALOKI
    try:
        with open(polku, "rb") as f:
            f.seek(0, os.SEEK_END)
            koko = f.tell()
            f.seek(max(0, koko - LUKU_TAVUA))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    paras = None
    for rivi in data.splitlines():
        try:
            d = json.loads(rivi)
            if d.get("laji") not in ("tehtava", "suunnittelu") or d.get("ok") is not True:
                continue
            aika = datetime.fromisoformat(d["aika"]).timestamp()
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if aika <= nyt_s + 300 and (paras is None or aika > paras):   # tulevaisuuden aikaleima ei peita pysahdysta
            paras = aika
    return paras


def tauon_syy(tila, repo, tyohak, env, nyt_s, ajastin_aktiivinen=None):
    """Syy (teksti), jos jono on tarkoituksella paikoillaan, muuten None."""
    if (Path(tila) / PYSAYTYS_TIEDOSTO).exists():
        return "pysaytystiedosto"
    if ajastin_aktiivinen is not None and not any(ajastin_aktiivinen(t) for t in KAISTAJARJESTELMA_AJASTIMET):
        return "kaistaajastimet pois paalta"
    if varaus.raja_tauolla(tila, nyt_s) > 0:
        return "kayttorajan tauko"
    try:
        a = varaus.arvio(tila, env, datetime.fromtimestamp(nyt_s, varaus.TZ))
        if a.get("kaistoja") == 0:
            return f"kulutusjarru ({a.get('tila')})"
    except Exception as virhe:   # arvion virhe ei saa estaa vahtia; virhetilassa ei oleteta taukoa
        print(f"vahti: arvio epaonnistui: {type(virhe).__name__}", file=sys.stderr)
    try:
        if ajuri.avoimet_tehtavat(repo, tila, nyt_s) == 0:
            nyt = datetime.fromtimestamp(nyt_s).astimezone()
            tauko_s = int(env.get("CLAUDEJONO_SUUNNITTELU_TAUKO_S", ajuri.SUUNNITTELU_TAUKO_S))
            if env.get("CLAUDEJONO_ITSESUUNNITTELU", "1") != "1" or ajuri.suunnittelu_tauolla(tyohak, repo, nyt, tauko_s):
                return "jono tyhja"
    except Exception as virhe:
        print(f"vahti: jonon luku epaonnistui: {type(virhe).__name__}", file=sys.stderr)
    return None


def tarkista(tila, repo, tyohak, env, nyt_s=None, ajastin_aktiivinen=None):
    """{'tila': terve|tauolla|pysahtynyt|ei_dataa, 'ika_s': int|None, 'syy': str}. Ei sivuvaikutuksia."""
    nyt_s = time.time() if nyt_s is None else nyt_s
    viimeisin = viimeisin_valmis(tila, nyt_s)
    ika = None if viimeisin is None else max(0, int(nyt_s - viimeisin))
    if ika is not None and ika < RAJA_S:
        return {"tila": "terve", "ika_s": ika, "syy": "valmis ajo alle 2 h sitten"}
    syy = tauon_syy(tila, repo, tyohak, env, nyt_s, ajastin_aktiivinen)
    if syy:
        return {"tila": "tauolla", "ika_s": ika, "syy": syy}
    if ika is None:
        return {"tila": "ei_dataa", "ika_s": None, "syy": "kaistalokissa ei ole valmiita ajoja"}
    return {"tila": "pysahtynyt", "ika_s": ika, "syy": f"ei valmista ajoa {ika // 3600} h {ika % 3600 // 60} min"}


def _lue_tila(tila):
    try:
        d = json.loads((Path(tila) / TILA_TIEDOSTO).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def toisto_estetty(tila, nyt_s):
    try:
        return 0 <= nyt_s - float(_lue_tila(tila).get("halytys", 0)) < TOISTOESTE_S
    except (TypeError, ValueError):
        return False


def kirjaa_halytys(tila, nyt_s):
    """Kirjataan ennen toimia, jotta kaatuva toimi ei kierra toistoestetta."""
    polku = Path(tila) / TILA_TIEDOSTO
    tmp = polku.with_suffix(".tmp")
    tmp.write_text(json.dumps({"halytys": nyt_s}), encoding="utf-8")
    os.replace(tmp, polku)


def kaynnista_korjaaja(suorita=subprocess.run):
    """Kaynnistaa korjaajan taustalle (ei odotusta). Palauttaa True, jos systemctl hyvaksyi."""
    try:
        r = suorita(["systemctl", "start", "--no-block", KORJAAJA_YKSIKKO], capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as virhe:
        print(f"vahti: korjaajan kaynnistys epaonnistui: {type(virhe).__name__}", file=sys.stderr)
        return False


def kuman_osoite(env):
    """Kelvollinen http(s)-osoite tai None. Osoitetta ei koskaan tulosteta."""
    url = (env.get("CLAUDEJONO_KUMA_PUSH_URL") or "").strip()
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return None
    return url if u.scheme in ("http", "https") and u.netloc else None


def pingaa_kuma(env, avaa=urllib.request.urlopen):
    """True, jos ping onnistui. Ei osoitetta -> None. Virheesta vain tyyppi."""
    url = kuman_osoite(env)
    if not url:
        return None
    try:
        with avaa(urllib.request.Request(url, method="GET"), timeout=KUMA_AIKARAJA_S) as v:
            return 200 <= v.status < 300
    except Exception as virhe:
        print(f"vahti: Kuma-ping epaonnistui: {type(virhe).__name__}", file=sys.stderr)
        return False


def kasittele(tila, repo, tyohak, env, nyt_s=None, laheta=None, korjaaja=kaynnista_korjaaja, ping=pingaa_kuma,
              kuiva=False, ajastin_aktiivinen=None):
    """Tarkistaa ja tekee toimet. Palauttaa (tulos, rivi)."""
    nyt_s = time.time() if nyt_s is None else nyt_s
    t = tarkista(tila, repo, tyohak, env, nyt_s, ajastin_aktiivinen)
    rivi = f"vahti: {t['tila']} ({t['syy']})"
    if kuiva:
        return t, rivi + " [kuiva-ajo]"
    if t["tila"] == "pysahtynyt":
        if toisto_estetty(tila, nyt_s):
            rivi += "; halytys jo lahetetty alle 2 h sitten"
        else:
            kirjaa_halytys(tila, nyt_s)
            if laheta:
                laheta(f"HALYTYS: jono on pysahtynyt, {t['syy']}. Korjaaja kaynnistetaan. Tarkista: journalctl -u 'claude-jono@*' -n 50")
            rivi += "; halytys lahetetty, korjaaja " + ("kaynnistetty" if korjaaja() else "EI kaynnistynyt")
    elif t["tila"] in ("terve", "tauolla"):
        p = ping(env)
        if p is not None:
            rivi += "; Kuma-ping " + ("ok" if p else "epaonnistui")
    return t, rivi


def _ajastin_aktiivinen(nimi):
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", nimi], timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True   # epavarmuus ei saa peittaa pysahdysta


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ
    tila = env.get("CLAUDEJONO_TILA", OLETUS_TILA)
    repo = env.get("CLAUDEJONO_REPO", str(Path(tila) / "docs"))
    tyohak = env.get("CLAUDEJONO_TYOHAK", OLETUS_TYOHAK)
    try:
        from yojono.ajuri import laheta_telegram
    except Exception:
        laheta_telegram = None
    try:
        _, rivi = kasittele(tila, repo, tyohak, env, laheta=laheta_telegram, kuiva="--kuiva" in argv,
                            ajastin_aktiivinen=_ajastin_aktiivinen)
    except Exception as virhe:
        print(f"vahti virhe: {type(virhe).__name__}", file=sys.stderr)
        return 1
    print(rivi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
