"""Valvottu autonomia, vaihe 1: laatumittarit agentti- ja muutosluokittain seka autonomiaportaiden arviointi (vain luku).

Lahde: GitHubin julkinen API (PR:t, tiedostot, tarkistukset, kommentit) ja halutessa tapahtumaloki (vain luku -yhteys).
Tama moduuli EI muuta automerge-saantoja, kattoja eika oikeuksia: portaat ovat ehdotus, jonka Tony hyvaksyy tai hylkaa.

Kaytto: python3 -m agentti.autonomia [--valimuisti POLKU] [--loki POLKU] [--kirjoita POLKU] [PAIVIA]
Valimuisti tallentaa suljettujen PR:ien rikastustiedot (tiedostot, CI, kommentit), koska suljettu PR ei muutu; ilman sita
tunnistamaton GitHub-API (60 pyyntoa/h) riittaa vain osaan PR:eista, ja raportti merkitsee silloin tuloksen vajaaksi."""
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

from . import pr_laatu
from .pr_kutsu import REPOT, suojattu

OLETUS_PAIVIA = 60
MAX_KUTSUJA = 150          # GitHub-pyyntoja per ajo rikastukseen (perusluettelo ei kuulu tahan)
RIKASTUS_VERSIO = 1

LUOKAT = ("dokumentaatio", "testit", "riippuvuus-patch", "pieni-korjaus", "suurempi", "suojattu")
# Kynnys = perakkaisia hyvaksyttyja (mergattu, ei revertia, CI ei punainen) ilman katkoa. None = ei koskaan automergeen.
KYNNYKSET = {"dokumentaatio": 20, "testit": 20, "riippuvuus-patch": 25, "pieni-korjaus": 40, "suurempi": None, "suojattu": None}
RAUHOITUS_PAIVAA = 14      # viimeisimmasta katkosta oltava vahintaan nain monta paivaa
# Nykytila: luokat, jotka tools/automerge.py jo mergaa botin PR:ille (peilaus kasin; tama moduuli ei lue eika muuta sita).
NYKYINEN_AUTOMERGE = ("dokumentaatio", "testit")
PIENI_RIVIT = 50
PIENI_TIEDOSTOT = 3
DEP_RE = re.compile(r"(^|/)(package(-lock)?\.json|requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|yarn\.lock|pnpm-lock\.yaml)$")
VERSIO_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)\D+?(\d+)\.(\d+)\.(\d+)")
REVERT_RE = re.compile(r"^revert\b", re.I)
VIITE_RE = re.compile(r"#(\d+)")
CI_OK = ("success", "neutral", "skipped")
CI_VIRHE = ("failure", "timed_out", "action_required", "cancelled", "startup_failure")


API = "https://api.github.com/repos/%s/%s/" % (pr_laatu.OMISTAJA, "%s")


def agentti_prsta(p):
    """Agentti PR:n otsikosta, haarasta ja kuvauksesta (heuristiikka): 'yojono', 'claude-jono', 'pilvi' tai 'muu'.
    Vain botin PR:t (kirjoittaja pr_laatu.BOTTI) ovat agenttien tyota; muut palauttavat None."""
    if ((p.get("user") or {}).get("login") or "").lower() != pr_laatu.BOTTI:
        return None
    otsikko = str(p.get("title") or "").lower()
    runko = str(p.get("body") or "").lower()
    haara = str(((p.get("head") or {}).get("ref")) or "").lower()
    if "claude-jono" in otsikko or "claudejono" in otsikko or "claude-jono" in runko or "claudejono" in runko:
        return "claude-jono"
    if "yojono" in otsikko or "yojono" in runko:
        return "yojono"
    if haara.startswith("claude/") or "generated with [claude code]" in runko:
        return "pilvi"
    return "muu"


def luokittele(tiedostot, otsikko=""):
    """Muutosluokka PR:n tiedostolistasta (dicteja: filename, additions, deletions, status) ja otsikosta.
    Suojattu polku (pr_kutsu.suojattu tai automergen suojalista) voittaa aina: suojatut eivat koskaan siirry automergeen."""
    nimet = [t.get("filename") for t in tiedostot if t.get("filename")]
    nimet += [t.get("previous_filename") for t in tiedostot if t.get("previous_filename")]
    if not nimet:
        return "suurempi"
    if any(suojattu(n) or n.startswith("yojono/") for n in nimet):
        return "suojattu"
    if all(n.lower().endswith(".md") for n in nimet):
        return "dokumentaatio"
    if all(n.lower().endswith(".md") or re.match(r"^(test|tests)/", n) or re.match(r"^(.*/)?test_[a-z0-9_]+\.py$", n) for n in nimet):
        return "testit"
    if all(DEP_RE.search(n) for n in nimet):
        m = VERSIO_RE.search(str(otsikko))
        return "riippuvuus-patch" if m and m.group(1) == m.group(4) and m.group(2) == m.group(5) and m.group(3) != m.group(6) else "suurempi"
    rivit = sum(int(t.get("additions") or 0) + int(t.get("deletions") or 0) for t in tiedostot)
    return "pieni-korjaus" if rivit <= PIENI_RIVIT and len(tiedostot) <= PIENI_TIEDOSTOT else "suurempi"


def ci_tulos(vastaus):
    """'ok' (kaikki valmiit ja vihrea), 'virhe' (jokin punainen) tai 'tuntematon' (ei ajoja / kesken)."""
    ajot = (vastaus or {}).get("check_runs") or []
    if any(a.get("conclusion") in CI_VIRHE for a in ajot):
        return "virhe"
    if ajot and all(a.get("status") == "completed" and a.get("conclusion") in CI_OK for a in ajot):
        return "ok"
    return "tuntematon"


class Budjetti:
    """Rajaa GitHub-pyyntojen maaran; ylitys tai API:n hylkays (esim. 403) merkitsee tuloksen vajaaksi."""

    def __init__(self, hae, raja):
        self.hae, self.raja, self.kaytetty, self.vajaa = hae, raja, 0, False

    def __call__(self, url):
        if self.kaytetty >= self.raja:
            self.vajaa = True
            raise LookupError("budjetti")
        self.kaytetty += 1
        try:
            return self.hae(url)
        except Exception:
            self.vajaa = True
            raise


def rikasta(repo, p, hae):
    """Yhden PR:n lisatiedot: luokka, CI (haaran ja mergen jalkeinen), katselmoinnin loydokset ja Tonyn kommentit.
    Nosta LookupError/virhe ylos, jos jokin haku epaonnistuu (kutsuja jattaa PR:n rikastamatta)."""
    nro = int(p.get("number"))
    tied = hae(API % repo + "pulls/%d/files?per_page=100" % nro)
    luokka = luokittele(tied, p.get("title"))
    ci = ci_tulos(hae(API % repo + "commits/%s/check-runs?per_page=100" % (p.get("head") or {}).get("sha")))
    ci_main = "tuntematon"
    if p.get("merged_at") and p.get("merge_commit_sha"):
        ci_main = ci_tulos(hae(API % repo + "commits/%s/check-runs?per_page=100" % p.get("merge_commit_sha")))
    kirjoittaja = ((p.get("user") or {}).get("login") or "").lower()
    kat = hae(API % repo + "pulls/%d/comments?per_page=100" % nro)
    ongelmat = hae(API % repo + "issues/%d/comments?per_page=100" % nro)
    loput = lambda k: ((k.get("user") or {}).get("login") or "").lower()
    return {"v": RIKASTUS_VERSIO, "luokka": luokka, "ci": ci, "ci_main": ci_main,
            "loydokset": sum(1 for k in kat if loput(k) not in (pr_laatu.OMISTAJA, kirjoittaja)),
            "tonyn": sum(1 for k in list(kat) + list(ongelmat) if loput(k) == pr_laatu.OMISTAJA)}


def revertoidut(prt):
    """Revert-PR:ien (kuka tahansa kirjoittaja) viittaamat PR-numerot ja revertin ajankohta: {nro: aika}.
    Tunnistus: otsikko alkaa 'Revert' ja (runko tai otsikko viittaa #N:aan tai otsikko on Revert "<alkup. otsikko>")."""
    otsikot = {int(p["number"]): str(p.get("title") or "") for p in prt if p.get("number") is not None}
    tulos = {}
    for p in prt:
        otsikko = str(p.get("title") or "")
        if not REVERT_RE.match(otsikko):
            continue
        aika = pr_laatu._aika(p.get("created_at"))
        kohteet = {int(n) for n in VIITE_RE.findall(str(p.get("body") or "") + " " + otsikko)}
        m = re.match(r'^revert\s+"(.*)"\s*$', otsikko, re.I)
        if m:
            kohteet |= {n for n, o in otsikot.items() if o == m.group(1)}
        for n in kohteet - {int(p["number"])}:
            if n in otsikot and aika is not None and (n not in tulos or aika < tulos[n]):
                tulos[n] = aika
    return tulos


def keraa(hae=None, paivia=OLETUS_PAIVIA, nyt=None, valimuisti=None, max_kutsuja=MAX_KUTSUJA):
    """Palauttaa {'prt': [tietue], 'vajaa': bool, 'virheet': [repo], 'paivia': n}. Tietue: repo, nro, agentti, luokka, tila,
    luotu, paatetty (datetime/None), ci, ci_main, loydokset, tonyn, revertoitu (datetime/None).
    Vain botin PR:t ikkunassa; revert-PR:t haetaan koko listasta. `valimuisti` on dict, jota paivitetaan (vain suljetut PR:t)."""
    nyt = nyt or datetime.now(timezone.utc)
    raja = nyt - timedelta(days=paivia)
    b = Budjetti(hae or pr_laatu._oletushaku, max_kutsuja)
    perus = hae or pr_laatu._oletushaku       # luettelohaut eivat kuluta rikastusbudjettia
    valimuisti = valimuisti if valimuisti is not None else {}
    tulos, virheet = [], []
    for repo in REPOT:
        try:
            lista = perus(API % repo + "pulls?state=all&sort=created&direction=desc&per_page=100")
        except Exception:
            virheet.append(repo)
            continue
        rev = revertoidut(lista)
        for p in lista:
            luotu = pr_laatu._aika(p.get("created_at"))
            agentti = agentti_prsta(p)
            if agentti is None or luotu is None or luotu < raja:
                continue
            nro = int(p.get("number"))
            auki = p.get("state") == "open"
            avain = "%s#%d" % (repo, nro)
            tied = None if auki else valimuisti.get(avain)
            if tied is not None and tied.get("v") != RIKASTUS_VERSIO:
                tied = None
            if tied is None:
                try:
                    tied = rikasta(repo, p, b)
                except Exception:
                    tied = {"luokka": None, "ci": "tuntematon", "ci_main": "tuntematon", "loydokset": None, "tonyn": None}
                    b.vajaa = True
                else:
                    if not auki:
                        valimuisti[avain] = tied
            tila = "auki" if auki else ("mergattu" if p.get("merged_at") else "suljettu")
            tulos.append({"repo": repo, "nro": nro, "agentti": agentti, "tila": tila, "luotu": luotu,
                          "paatetty": pr_laatu._aika(p.get("merged_at") or p.get("closed_at")),
                          "luokka": tied["luokka"], "ci": tied["ci"], "ci_main": tied["ci_main"],
                          "loydokset": tied["loydokset"], "tonyn": tied["tonyn"], "revertoitu": rev.get(nro)})
    return {"prt": tulos, "vajaa": b.vajaa or bool(virheet), "virheet": virheet, "paivia": paivia}


def _pros(a, b):
    return "%d %%" % round(100 * a / b) if b else "-"


def mittarit(prt, avain):
    """Ryhmittaa PR-tietueet kentan `avain` mukaan; palauttaa {ryhma: luvut}."""
    ryhmat = {}
    for t in prt:
        r = ryhmat.setdefault(t[avain] or "tuntematon", {"mergattu": 0, "suljettu": 0, "auki": 0, "revertit": 0, "ci_punainen": 0,
                                                         "ci_tunnettu": 0, "loydokset": 0, "tonyn": 0})
        r[t["tila"]] += 1
        if t["revertoitu"]:
            r["revertit"] += 1
        if t["tila"] != "auki":
            if t["ci"] != "tuntematon" or t["ci_main"] != "tuntematon":
                r["ci_tunnettu"] += 1
            if "virhe" in (t["ci"], t["ci_main"]):
                r["ci_punainen"] += 1
        r["loydokset"] += t["loydokset"] or 0
        r["tonyn"] += t["tonyn"] or 0
    return ryhmat


def _katko(t):
    """Katkon ajankohta (datetime) tai None, jos PR on hyva: hylatty, revertoitu tai CI punainen."""
    if t["tila"] == "suljettu":
        return t["paatetty"]
    if t["tila"] == "mergattu":
        if t["revertoitu"]:
            return t["revertoitu"]
        if "virhe" in (t["ci"], t["ci_main"]):
            return t["paatetty"]
    return None


def portaat(prt, nyt=None, nykyinen=NYKYINEN_AUTOMERGE):
    """Autonomiaportaiden arvio per (agentti, luokka): perakkaisia hyvia = mergattuja PR:ia viimeisimman katkon jalkeen.
    Tila: 'ehdokas' (kynnys tayttyy ja rauhoitusaika kulunut), 'ei viela', 'ei koskaan' (suojattu/suurempi) tai 'pudota'
    (luokka on nykyisessa automergessa, mutta ikkunassa on tuore katko). Luokka tuntematon (rikastus puuttuu) ohitetaan."""
    nyt = nyt or datetime.now(timezone.utc)
    ryhmat = {}
    for t in prt:
        if t["luokka"] and t["tila"] != "auki":
            ryhmat.setdefault((t["agentti"], t["luokka"]), []).append(t)
    tulos = []
    for (agentti, luokka), lista in sorted(ryhmat.items()):
        lista.sort(key=lambda t: t["paatetty"] or t["luotu"])
        katkot = [k for k in (_katko(t) for t in lista) if k]
        viimeinen = max(katkot) if katkot else None
        putki = sum(1 for t in lista if t["tila"] == "mergattu" and not _katko(t) and (viimeinen is None or (t["paatetty"] or t["luotu"]) > viimeinen))
        kynnys = KYNNYKSET[luokka]
        tuore = viimeinen is not None and (nyt - viimeinen) < timedelta(days=RAUHOITUS_PAIVAA)
        if kynnys is None:
            tila = "ei koskaan"
        elif luokka in nykyinen and viimeinen is not None and tuore:
            tila = "pudota"
        elif putki >= kynnys and not tuore:
            tila = "ehdokas"
        else:
            tila = "ei viela"
        tulos.append({"agentti": agentti, "luokka": luokka, "putki": putki, "kynnys": kynnys, "tila": tila,
                      "katko": viimeinen, "nykyinen": luokka in nykyinen})
    return tulos


def lokirivit(polku, paivia, nyt=None):
    """Tapahtumalokin yhteenveto agenteittain (vain luku -yhteys): {agentti: (tapahtumia, virheita, kulu_usd)}. Puuttuva loki -> {}."""
    if not polku or not os.path.exists(polku):
        return {}
    alku = (time.time() if nyt is None else nyt) - paivia * 86400
    try:
        yht = sqlite3.connect("file:%s?mode=ro" % polku, uri=True, timeout=5)
        try:
            return {a: (int(n), int(v), round(float(k), 4)) for a, n, v, k in yht.execute(
                "SELECT agentti, COUNT(*), COALESCE(SUM(tulos='virhe'),0), COALESCE(SUM(kulu_usd),0) FROM tapahtuma WHERE aika>=? GROUP BY agentti", (alku,))}
        finally:
            yht.close()
    except sqlite3.Error:
        return {}


def _taulukko(otsikko, ryhmat):
    rivit = [otsikko, "  ryhma | merg. | sulj. | auki | merge-% | revertit | CI punainen | loydokset | Tonyn komm."]
    for nimi, r in sorted(ryhmat.items()):
        rivit.append("  %s | %d | %d | %d | %s | %d | %d/%d | %d | %d" % (
            nimi, r["mergattu"], r["suljettu"], r["auki"], _pros(r["mergattu"], r["mergattu"] + r["suljettu"]), r["revertit"],
            r["ci_punainen"], r["ci_tunnettu"], r["loydokset"], r["tonyn"]))
    return "\n".join(rivit)


def muotoile(data, loki=None, nyt=None):
    prt = data["prt"]
    nyt = nyt or datetime.now(timezone.utc)
    rivit = ["Autonomian laatumittarit, %d vrk (botin PR:t; GitHub julkinen API, vain luku)" % data["paivia"], ""]
    if not prt:
        rivit.append("Ei PR:ia ikkunassa: data ei riita.")
    else:
        rivit.append(_taulukko("Agenteittain:", mittarit(prt, "agentti")))
        rivit.append("")
        rivit.append(_taulukko("Muutosluokittain:", mittarit(prt, "luokka")))
    if loki:
        rivit += ["", "Tapahtumaloki (agentti: tapahtumia / virheita / kulu USD):"]
        rivit += ["  %s: %d / %d / %.2f" % (a, n, v, k) for a, (n, v, k) in sorted(loki.items())]
    rivit += ["", "Autonomiaportaat (ehdotus, ei kaytossa; Tony paattaa). Kynnys = perakkaisia hyvaksyttyja ilman katkoa (hylkays, revert, punainen CI), rauhoitus %d vrk:" % RAUHOITUS_PAIVAA]
    arvio = portaat(prt, nyt)
    for a in arvio:
        katko = a["katko"].date().isoformat() if a["katko"] else "-"
        rivit.append("  %s / %s: putki %d/%s, viimeisin katko %s -> %s%s" % (
            a["agentti"], a["luokka"], a["putki"], a["kynnys"] if a["kynnys"] else "-", katko, a["tila"].upper() if a["tila"] in ("ehdokas", "pudota") else a["tila"],
            " (nyt automergessa)" if a["nykyinen"] else ""))
    if not arvio:
        rivit.append("  data ei riita")
    if data["vajaa"]:
        rivit += ["", "HUOM: tulos on vajaa (API-raja, budjetti tai haku epaonnistui%s); aja uudelleen valimuistin kanssa." % (
            ": " + ", ".join(data["virheet"]) if data["virheet"] else "")]
    unk = sum(1 for t in prt if t["luokka"] is None)
    if unk:
        rivit.append("%d PR:lla ei luokkaa (rikastus puuttuu); ne eivat ole portaissa." % unk)
    rivit.append("Rajoitteet: agentti tunnistetaan otsikosta/kuvauksesta (heuristiikka); revert tunnistetaan vain PR:sta, ei suorasta commitista.")
    return "\n".join(rivit) + "\n"


def lue_valimuisti(polku):
    try:
        with open(polku, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def kirjoita(polku, teksti):
    hak = os.path.dirname(os.path.abspath(polku))
    fd, vali = tempfile.mkstemp(dir=hak, prefix=".autonomia.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(teksti)
        os.replace(vali, polku)
    except BaseException:
        if os.path.exists(vali):
            os.unlink(vali)
        raise


def main(argv=None, hae=None):
    a = list(sys.argv[1:] if argv is None else argv)
    valinnat = {}
    while a and a[0] in ("--valimuisti", "--loki", "--kirjoita"):
        if len(a) < 2:
            break
        valinnat[a[0]], a = a[1], a[2:]
    if len(a) > 1 or (a and not a[0].isdigit()) or (a and a[0].startswith("--")):
        print("kaytto: python3 -m agentti.autonomia [--valimuisti POLKU] [--loki POLKU] [--kirjoita POLKU] [PAIVIA]", file=sys.stderr)
        return 2
    paivia = int(a[0]) if a else OLETUS_PAIVIA
    vm = lue_valimuisti(valinnat["--valimuisti"]) if "--valimuisti" in valinnat else None
    data = keraa(hae, paivia, valimuisti=vm)
    if vm is not None:
        kirjoita(valinnat["--valimuisti"], json.dumps(vm))
    teksti = muotoile(data, lokirivit(valinnat.get("--loki"), paivia))
    if "--kirjoita" in valinnat:
        kirjoita(valinnat["--kirjoita"], teksti)
    else:
        print(teksti, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
