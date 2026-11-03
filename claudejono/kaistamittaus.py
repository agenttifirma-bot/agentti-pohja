"""Kaistakoe: rinnakkaisten kaistojen mittaus (tehtava 2026-11-03, viikon mittaus).

Lahteet (kaikki vain luku, paitsi nayte joka kirjoittaa oman rivinsa kuormalokiin):
  - kaistaloki.jsonl: ajuri kirjaa jokaisesta ajosta rivin (kaista, kesto, onnistuiko, rajaan osuminen, kierrokset, API-arvo)
  - kuorma.jsonl: tama moduuli kirjaa 15 min valein /proc/loadavg ja /proc/meminfo -luvut
  - yojonon tila.json: kulut per paiva (LiteLLM/OpenRouter), vain luettuna

Kaytto (tila-hakemisto = docs-kloonin vanhempi, oletus /var/lib/claude-jono):
  python3 -m claudejono.kaistamittaus nayte              # yksi kuormanayte (ajastin)
  python3 -m claudejono.kaistamittaus raportti [--kirjoita TIEDOSTO]
  python3 -m claudejono.kaistamittaus rivi               # yksi rivi aamukoosteeseen

Raja: mittaus ei muuta katto- eika budjettiarvoja. Rajaan osuminen tunnistetaan virheilmoituksen tekstista (arvaus: ilmaukset
`ajuri.RAJA_RE`); jos Clauden ilmaisu muuttuu, osumia jaa havaitsematta, joten nolla osumaa ei todista etta rajaa ei lahestytty.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import ajuri

OLETUS_TILA = "/var/lib/claude-jono"
OLETUS_YOJONO = "/var/lib/yojono"
KUORMA = "kuorma.jsonl"
RAUTA_LATAUS_SUHDE = 1.5     # load1 / ytimet; ylitys = kuormaa enemman kuin ytimia
RAUTA_MUISTI_MIN_MB = 400    # MemAvailable alle taman = muisti loppumassa
RAUTA_SWAP_MB = 256
MIN_DATA_H = 24


def _meminfo():
    ulos = {}
    try:
        for rivi in Path("/proc/meminfo").read_text().splitlines():
            nimi, _, loput = rivi.partition(":")
            osat = loput.split()
            if osat and osat[0].isdigit():
                ulos[nimi] = int(osat[0]) // 1024   # kB -> MB
    except OSError:
        pass
    return ulos


def nayte(tila, nyt=None, lataus=None, muisti=None, ytimet=None):
    """Kirjaa yhden kuormanaytteen. Palauttaa kirjatun rivin. Argumentit ovat testeja varten."""
    nyt = nyt or datetime.now().astimezone()
    if lataus is None:
        try:
            lataus = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
        except (OSError, ValueError):
            lataus = [0.0, 0.0, 0.0]
    m = muisti if muisti is not None else _meminfo()
    rivi = {"aika": nyt.isoformat(timespec="seconds"), "load1": lataus[0], "load5": lataus[1], "load15": lataus[2],
            "muisti_kaikki_mb": m.get("MemTotal"), "muisti_vapaa_mb": m.get("MemAvailable"),
            "swap_kaytossa_mb": (m.get("SwapTotal", 0) - m.get("SwapFree", 0)) if "SwapTotal" in m else None,
            "ytimet": ytimet or os.cpu_count() or 1,
            "varaukset": len([n for n in ajuri.aktiiviset_varaukset(tila) if n != ajuri.SUUNNITTELU_VARAUS])}
    fd = os.open(Path(tila) / KUORMA, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(rivi) + "\n")
    return rivi


def lue_jsonl(polku, alku=None, loppu=None):
    ulos = []
    try:
        rivit = Path(polku).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ulos
    for r in rivit:
        try:
            d = json.loads(r)
            aika = datetime.fromisoformat(d["aika"])
        except (ValueError, KeyError, TypeError):
            continue   # rikkinainen rivi ei kaada raporttia
        if (alku is None or aika >= alku) and (loppu is None or aika <= loppu):
            d["_aika"] = aika
            ulos.append(d)
    return ulos


def kulut_per_paiva(yojono_perus):
    """Yojonon kulut per paiva (USD, LiteLLM/OpenRouter), vain luettuna. Puuttuva tila -> {}."""
    try:
        k = json.loads((Path(yojono_perus) / "tila.json").read_text(encoding="utf-8")).get("kulut", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(p): float(v) for p, v in k.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(k, dict) else {}


def yhteenveto(tila, alku, loppu, yojono_perus=OLETUS_YOJONO):
    ajot = [d for d in lue_jsonl(Path(tila) / ajuri.KAISTALOKI, alku, loppu) if d.get("laji") == "tehtava"]
    kuorma = lue_jsonl(Path(tila) / KUORMA, alku, loppu)
    kaistat = {}
    for d in ajot:
        k = kaistat.setdefault(d.get("kaista"), {"tehtavia": 0, "ok": 0, "epaonnistui": 0, "raja": 0, "kestot": [], "arvo": 0.0,
                                                  "kierrokset": 0, "push_epaonnistui": 0, "lukko_max": 0.0, "paivat": {}})
        k["tehtavia"] += 1
        k["ok" if d.get("ok") else "epaonnistui"] += 1
        k["raja"] += 1 if d.get("raja") else 0
        k["push_epaonnistui"] += 1 if d.get("push") is False else 0
        k["kestot"].append(float(d.get("kesto_s", 0)))
        k["arvo"] += float(d.get("arvo_usd", 0) or 0)
        k["kierrokset"] += int(d.get("kierrokset", 0) or 0)
        k["lukko_max"] = max(k["lukko_max"], float(d.get("lukko_odotus_s", 0) or 0))
        paiva = d["_aika"].date().isoformat()
        k["paivat"][paiva] = k["paivat"].get(paiva, 0) + 1
    # rinnakkaisuus: montako ajoa oli samaan aikaan kaynnissa (alku = loppuaika - kesto)
    tapahtumat = []
    for d in ajot:
        lop = d["_aika"]
        tapahtumat += [(lop - timedelta(seconds=float(d.get("kesto_s", 0))), 1), (lop, -1)]
    nyt_ajossa = huippu = 0
    paallekkain_s = 0.0
    edellinen = None
    for aika, delta in sorted(tapahtumat, key=lambda x: (x[0], x[1])):
        if edellinen is not None and nyt_ajossa >= 2:
            paallekkain_s += (aika - edellinen).total_seconds()
        nyt_ajossa += delta
        huippu = max(huippu, nyt_ajossa)
        edellinen = aika
    k1 = [d["load1"] for d in kuorma if isinstance(d.get("load1"), (int, float))]
    vapaa = [d["muisti_vapaa_mb"] for d in kuorma if isinstance(d.get("muisti_vapaa_mb"), (int, float))]
    swap = [d["swap_kaytossa_mb"] for d in kuorma if isinstance(d.get("swap_kaytossa_mb"), (int, float))]
    ytimet = max([d.get("ytimet", 1) for d in kuorma] or [1])
    data_h = ((max(d["_aika"] for d in ajot + kuorma) - min(d["_aika"] for d in ajot + kuorma)).total_seconds() / 3600) if (ajot or kuorma) else 0.0
    kulut = kulut_per_paiva(yojono_perus)
    return {"kaistat": kaistat, "huippurinnakkaisuus": huippu, "paallekkain_min": round(paallekkain_s / 60, 1),
            "load1_keski": round(statistics.mean(k1), 2) if k1 else None, "load1_max": max(k1) if k1 else None,
            "muisti_vapaa_min_mb": min(vapaa) if vapaa else None, "swap_max_mb": max(swap) if swap else None,
            "ytimet": ytimet, "naytteita": len(kuorma), "data_h": round(data_h, 1),
            "kulut": {p: v for p, v in sorted(kulut.items()) if alku.date().isoformat() <= p <= loppu.date().isoformat()}}


def paatelma(y):
    """Ohjeellinen pullonkaulaluokitus. Ei muuta mitaan; Tony paattaa. Vahan dataa -> sanotaan se."""
    rivit = []
    if y["data_h"] < MIN_DATA_H or not y["kaistat"]:
        return ["Data ei riit\u00e4 p\u00e4\u00e4telm\u00e4\u00e4n (%.1f h mittausta, v\u00e4hint\u00e4\u00e4n %d h)." % (y["data_h"], MIN_DATA_H)]
    raja = sum(k["raja"] for k in y["kaistat"].values())
    if raja:
        rivit.append(f"Tilauksen k\u00e4ytt\u00f6raja: {raja} osumaa. Kolmatta kaistaa ei kannata ottaa k\u00e4ytt\u00f6\u00f6n.")
    else:
        rivit.append("Tilauksen k\u00e4ytt\u00f6raja: ei havaittuja osumia (tunnistus perustuu virheilmoituksen tekstiin, ks. rajoite).")
    rauta = []
    if y["load1_max"] is not None and y["load1_max"] > RAUTA_LATAUS_SUHDE * y["ytimet"]:
        rauta.append(f"kuorma enimmill\u00e4\u00e4n {y['load1_max']} ({y['ytimet']} ydint\u00e4)")
    if y["muisti_vapaa_min_mb"] is not None and y["muisti_vapaa_min_mb"] < RAUTA_MUISTI_MIN_MB:
        rauta.append(f"vapaata muistia alimmillaan {y['muisti_vapaa_min_mb']} Mt")
    if y["swap_max_mb"] is not None and y["swap_max_mb"] > RAUTA_SWAP_MB:
        rauta.append(f"swapia k\u00e4ytetty {y['swap_max_mb']} Mt")
    rivit.append("Rauta: " + ("rajoittaa (" + "; ".join(rauta) + ")." if rauta else "ei rajoita mitatuilla mittareilla."))
    rivit.append("OpenRouter: katso kulut alta. Budjettiraja on Tonyn p\u00e4\u00e4tett\u00e4v\u00e4; t\u00e4m\u00e4 raportti ei arvioi sit\u00e4.")
    return rivit


def _kesto(s):
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.1f} min"


def raportti(tila, alku, loppu, yojono_perus=OLETUS_YOJONO):
    y = yhteenveto(tila, alku, loppu, yojono_perus)
    ul = ["# Kaistakoe 2026-11", "",
          f"Aikav\u00e4li: {alku.isoformat(timespec='minutes')} \u2013 {loppu.isoformat(timespec='minutes')} ({y['data_h']} h dataa, {y['naytteita']} kuorman\u00e4ytett\u00e4).",
          "Luotu: `python3 -m claudejono.kaistamittaus raportti`. L\u00e4hteet: kaistaloki.jsonl, kuorma.jsonl, y\u00f6jonon tila.json (vain luku).", "",
          "## Kaistat", "", "| Kaista | Teht\u00e4vi\u00e4 | Valmis | Ep\u00e4onnistui | Rajaosumia | Kesto ka. | Kesto max | Kierroksia | API-arvo (arvio, USD) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for n in sorted(y["kaistat"], key=lambda x: (x is None, x)):
        k = y["kaistat"][n]
        ul.append(f"| {n} | {k['tehtavia']} | {k['ok']} | {k['epaonnistui']} | {k['raja']} | {_kesto(statistics.mean(k['kestot']))} | "
                  f"{_kesto(max(k['kestot']))} | {k['kierrokset']} | {k['arvo']:.2f} |")
    if not y["kaistat"]:
        ul.append("| \u2013 | 0 | 0 | 0 | 0 | \u2013 | \u2013 | 0 | 0.00 |")
    paivat = sorted({p for k in y["kaistat"].values() for p in k["paivat"]})
    if paivat:
        ul += ["", "### Teht\u00e4vi\u00e4 per vuorokausi", "", "| P\u00e4iv\u00e4 | " + " | ".join(f"Kaista {n}" for n in sorted(y["kaistat"])) + " | Yhteens\u00e4 |",
               "|---|" + "---|" * (len(y["kaistat"]) + 1)]
        for p in paivat:
            arvot = [y["kaistat"][n]["paivat"].get(p, 0) for n in sorted(y["kaistat"])]
            ul.append(f"| {p} | " + " | ".join(map(str, arvot)) + f" | {sum(arvot)} |")
    ul += ["", "## Rinnakkaisuus ja varausten toimivuus", "",
           f"- Korkein yht\u00e4 aikaa k\u00e4ynniss\u00e4 ollut ajojen m\u00e4\u00e4r\u00e4: {y['huippurinnakkaisuus']}.",
           f"- V\u00e4hint\u00e4\u00e4n kaksi ajoa p\u00e4\u00e4llekk\u00e4in: {y['paallekkain_min']} min.",
           f"- Push ep\u00e4onnistui: {sum(k['push_epaonnistui'] for k in y['kaistat'].values())} kertaa; pisin git-lukon odotus: "
           f"{max([k['lukko_max'] for k in y['kaistat'].values()] or [0]):.1f} s.", "",
           "## Kuorma ja muisti (CT115)", "",
           f"- Kuorma (load1): keskiarvo {y['load1_keski']}, enint. {y['load1_max']} ({y['ytimet']} ydint\u00e4).",
           f"- Vapaa muisti alimmillaan: {y['muisti_vapaa_min_mb']} Mt; swap enint. {y['swap_max_mb']} Mt.", "",
           "## OpenRouter-kulut (y\u00f6jonon tila, USD/vrk)", ""]
    if y["kulut"]:
        ul += [f"- {p}: {v:.2f}" for p, v in y["kulut"].items()]
    else:
        ul.append("- Ei lukua (y\u00f6jonon tila.json puuttuu tai ei sis\u00e4ll\u00e4 kuluja t\u00e4lt\u00e4 v\u00e4lilt\u00e4).")
    ul += ["", "## P\u00e4\u00e4telm\u00e4 (ohjeellinen, Tony p\u00e4\u00e4tt\u00e4\u00e4)", ""] + [f"- {r}" for r in paatelma(y)]
    ul += ["", "## Rajoitteet", "",
           "- Tilauksen k\u00e4ytt\u00f6rajasta ei ole suoraa lukua. Mitataan vain osumat (virheilmoituksen teksti) ja Clauden ilmoittama API-arvo, joka on arvio kulutuksesta eik\u00e4 lasku.",
           "- Rajaosuman tunnistus on arvaus ilmauksista. Nolla osumaa ei todista, ettei rajaa l\u00e4hestytty.",
           "- Kaistat jakavat saman tilauksen; kuorma-aineisto on 15 min v\u00e4lein, joten lyhyet piikit voivat j\u00e4\u00e4d\u00e4 n\u00e4kym\u00e4tt\u00e4."]
    return "\n".join(ul) + "\n"


def rivi(tila, nyt=None, yojono_perus=OLETUS_YOJONO):
    """Yksi lyhyt aamukoosteen osa viimeisen vuorokauden kaistoista. None, jos kaistalokia ei ole (vanha yksikaistainen asennus)."""
    nyt = nyt or datetime.now().astimezone()
    y = yhteenveto(tila, nyt - timedelta(hours=24), nyt, yojono_perus)
    if not y["kaistat"]:
        return None
    osat = ", ".join(f"k{n} {k['tehtavia']}" for n, k in sorted(y["kaistat"].items(), key=lambda x: (x[0] is None, x[0])))
    raja = sum(k["raja"] for k in y["kaistat"].values())
    epa = sum(k["epaonnistui"] for k in y["kaistat"].values())
    return (f"kaistat {osat}, rinnakkain {y['paallekkain_min']:.1f} min, rajaosumia {raja}, ep\u00e4onnistui {epa}"
            + (f", kuorma enint. {y['load1_max']}" if y["load1_max"] is not None else ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="Kaistakoe: kuormanayte, raportti ja aamukoosterivi")
    p.add_argument("komento", choices=["nayte", "raportti", "rivi"])
    p.add_argument("--tila", default=os.environ.get("CLAUDEJONO_TILA", OLETUS_TILA))
    p.add_argument("--yojono", default=os.environ.get("YOJONO_PERUS", OLETUS_YOJONO))
    p.add_argument("--alku", help="ISO-aika; oletus 7 vrk sitten")
    p.add_argument("--loppu", help="ISO-aika; oletus nyt")
    p.add_argument("--kirjoita", help="kirjoita raportti tiedostoon (muuten tulostetaan)")
    a = p.parse_args(argv)
    nyt = datetime.now().astimezone()
    if a.komento == "nayte":
        nayte(a.tila, nyt)
        return 0
    loppu = datetime.fromisoformat(a.loppu) if a.loppu else nyt
    if loppu.tzinfo is None:
        loppu = loppu.astimezone()
    if a.komento == "rivi":
        print(rivi(a.tila, loppu, a.yojono) or "")
        return 0
    alku = datetime.fromisoformat(a.alku) if a.alku else loppu - timedelta(days=7)
    if alku.tzinfo is None:
        alku = alku.astimezone()
    teksti = raportti(a.tila, alku, loppu, a.yojono)
    if a.kirjoita:
        Path(a.kirjoita).write_text(teksti, encoding="utf-8")
    else:
        print(teksti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
