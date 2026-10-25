#!/usr/bin/env python3
"""Isannan pakotettu komento: kontti saa ottaa snapshotin VAIN itsestaan.

Asennetaan Proxmox-isannalle (asenna.sh) ja kytketaan authorized_keys-riviin. Kohdekontti tulee rivin
command=-argumentista (vain root voi muuttaa sita), ei koskaan asiakkaalta:
  from="<CT115-IP>",restrict,command="/root/snapshot-kutsu.py" ssh-ed25519 ...        (ei argumenttia = CT115)
  from="<CT118-IP>",restrict,command="/root/snapshot-kutsu.py 118" ssh-ed25519 ...    (ks. CT118-asennus.md)

Sallitut komennot (SSH_ORIGINAL_COMMAND):
  tila               -> VAIN LUKU, vain CT115:n avaimelle: isannan ja konttien tila tekstina (pct list, pvesm status, levy,
                        kuorma, epaonnistuneet palvelut ajossa olevissa konteissa, viimeisimmat varmuuskopiot).
                        Ei argumentteja, ei kayttajan syotetta komentoihin. CT118:n avain EI saa tata.
  listaa             -> avaimen oman kontin snapshotit
  snapshot ennen-xxx -> ottaa snapshotin (vain nimet muotoa ennen-<a-z0-9->)
Ei poistoa, ei rollbackia, ei muita kontteja. Rajat (KOHTEET): CT115 enintaan 20 snapshotia, 10 ottoa/vrk;
CT118 enintaan 10 snapshotia, 3 ottoa/vrk, eika ooteta, jos kontin thin pool (data tai metadata) on yli 80 % taynna.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time

OLETUS_KOHDE = "115"          # authorized_keys-rivi ilman argumenttia = CT115 (jo asennettu rivi toimii ennallaan)
KOHTEET = {
    "115": {"max_snapshotia": 20, "max_paivassa": 10, "levy_raja": None, "tila": True, "tarkka_loki": False},
    "118": {"max_snapshotia": 10, "max_paivassa": 3, "levy_raja": 80, "tila": False, "tarkka_loki": True},
}
CT = OLETUS_KOHDE
NIMI_RE = re.compile(r"^ennen-[a-z0-9][a-z0-9-]{1,40}$")
RIVI_RE = re.compile(r"`->\s+(\S+)")
MAX_SNAPSHOTIA = KOHTEET[OLETUS_KOHDE]["max_snapshotia"]
MAX_PAIVASSA = KOHTEET[OLETUS_KOHDE]["max_paivassa"]
LOKI = "/var/log/snapshot-kutsu.log"
LUKKO = "/run/snapshot-kutsu.lock"
LVS_KENTAT = "lv_name,vg_name,lv_attr,pool_lv,data_percent,metadata_percent"


class Virhe(Exception):
    tila = "virhe"            # lokin tila-sana (vain kohteilla, joilla tarkka_loki)


class RajaVirhe(Virhe):
    tila = "raja"


class LevyVirhe(Virhe):
    tila = "levy"


def jasenna(komento):
    osat = (komento or "").split()
    if osat == ["tila"]:
        return ("tila", None)
    if osat == ["listaa"]:
        return ("listaa", None)
    if len(osat) == 2 and osat[0] == "snapshot":
        if not NIMI_RE.match(osat[1]):
            raise Virhe("nimen pitaa olla muotoa ennen-<a-z0-9-> (8-47 merkkia)")
        return ("snapshot", osat[1])
    raise Virhe("sallitut komennot: listaa | snapshot ennen-<nimi>")


def kohde_argumentista(argv):
    """Kohde authorized_keys-rivin command=-argumentista; ei argumenttia = CT115, tuntematon = virhe."""
    if not argv:
        return OLETUS_KOHDE
    if len(argv) == 1 and argv[0] in KOHTEET:
        return argv[0]
    raise Virhe("isannan kohdeasetus virheellinen")


def nimet(listaus):
    return [n for n in RIVI_RE.findall(listaus) if n != "current"]


def _pct(suorita, *args):
    r = suorita(["pct", *args], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise Virhe(("pct %s epaonnistui: " % args[0]) + (r.stderr or r.stdout).strip()[-200:])
    return r.stdout


def _on_ok_otto(rivi, paiva, kohde):
    """Onnistunut snapshot-otto kohteelle, kentittain (ei alimerkkijonohakua: komennon teksti ei voi vaarentaa rivia)."""
    osat = rivi.rstrip("\n").split(" ", 4)
    if len(osat) < 4 or osat[0] != paiva or osat[1] != "snapshot" or osat[2] != "ok":
        return False
    if kohde == OLETUS_KOHDE:
        return osat[3] == "snapshot"
    return len(osat) == 5 and osat[3] == "ct=" + kohde and osat[4].startswith("snapshot ")


def paivan_otot(loki, paiva, kohde=OLETUS_KOHDE):
    try:
        with open(loki) as f:
            return sum(1 for rivi in f if _on_ok_otto(rivi, paiva, kohde))
    except OSError:
        return 0


def _prosentti(teksti):
    try:
        v = float(teksti)
    except ValueError:
        raise LevyVirhe("levytilaa ei voitu tarkistaa (lvs-arvo)")
    if not 0 <= v <= 100:                     # NaN ei kuulu valille
        raise LevyVirhe("levytilaa ei voitu tarkistaa (lvs-arvo)")
    return v


def tarkista_levy(kohde, raja, suorita=subprocess.run):
    """Fail closed: kontin levyn thin pool (data JA metadata) saa olla enintaan raja %; jos arvoa ei saada, ei oteta."""
    try:
        r = suorita(["lvs", "--noheadings", "--nosuffix", "--separator", ",", "-o", LVS_KENTAT],
                    capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise LevyVirhe("levytilaa ei voitu tarkistaa (lvs)")
    if r.returncode != 0:
        raise LevyVirhe("levytilaa ei voitu tarkistaa (lvs)")
    rivit = [[k.strip() for k in rivi.split(",")] for rivi in (r.stdout or "").splitlines() if rivi.strip()]
    rivit = [x for x in rivit if len(x) == 6]
    levyt = [x for x in rivit if re.fullmatch(r"vm-%s-disk-[0-9]+" % kohde, x[0]) and x[2][:1] == "V" and x[3]]
    if not levyt:
        raise LevyVirhe("levytilaa ei voitu tarkistaa (kontin levya ei loytynyt)")
    for vg, allas in sorted({(x[1], x[3]) for x in levyt}):
        altaat = [x for x in rivit if x[0] == allas and x[1] == vg and x[2][:1] == "t"]
        if len(altaat) != 1:
            raise LevyVirhe("levytilaa ei voitu tarkistaa (thin pool %s)" % allas)
        data, meta = _prosentti(altaat[0][4]), _prosentti(altaat[0][5])
        if data > raja or meta > raja:
            raise LevyVirhe("thin pool %s liian taynna (data %.2f %%, metadata %.2f %%, raja %d %%)" % (allas, data, meta, raja))


TILA_KOMENNOT = (
    ("Kontit (pct list)", ["pct", "list"]),
    ("Tallennustila (pvesm status)", ["pvesm", "status"]),
    ("Isannan levy", ["df", "-h", "/", "/var/lib/vz"]),
    ("Isannan kuorma ja muisti", ["sh", "-c", "cat /proc/loadavg; grep -E 'MemTotal|MemAvailable' /proc/meminfo"]),
    ("Viimeisimmat varmuuskopiot", ["sh", "-c", "ls -lt /var/lib/vz/dump 2>/dev/null | head -6"]),
)
TILA_MAX = 6000
# LXC-konteissa nama mountit ovat aina failed-tilassa (kohinaa, ei vika)
TILA_KOHINA = ("dev-mqueue.mount", "run-lock.mount", "tmp.mount")


def _suodata_kohina(teksti):
    rivit = [r for r in teksti.splitlines() if not any(k in r for k in TILA_KOHINA)]
    return "\n".join(rivit).strip()


def kerro_tila(suorita=subprocess.run):
    """Vain luku, kiintea komentolista (ei kayttajan syotetta). Virhe yhdessa komennossa ei kaada muita."""
    osat = []
    ajossa = []
    for otsikko, komento in TILA_KOMENNOT:
        try:
            r = suorita(komento, capture_output=True, text=True, timeout=30)
            ulos = (r.stdout or r.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            ulos = "(ei saatavilla)"
        osat.append("## %s\n%s" % (otsikko, ulos))
        if komento == ["pct", "list"]:
            for rivi in ulos.splitlines()[1:]:
                kentat = rivi.split()
                if len(kentat) >= 2 and kentat[0].isdigit() and kentat[1] == "running":
                    ajossa.append(kentat[0])
    for ct in ajossa:
        try:
            r = suorita(["pct", "exec", ct, "--", "systemctl", "list-units", "--failed", "--no-legend", "--no-pager"],
                        capture_output=True, text=True, timeout=30)
            ulos = _suodata_kohina((r.stdout or r.stderr or "").strip()) or "(ei epaonnistuneita palveluita)"
        except (OSError, subprocess.TimeoutExpired):
            ulos = "(ei saatavilla)"
        osat.append("## CT%s epaonnistuneet palvelut\n%s" % (ct, ulos[:600]))
    return "\n\n".join(osat)[:TILA_MAX]


def aja(komento, suorita=subprocess.run, loki=LOKI, nyt=None, kohde=OLETUS_KOHDE):
    asetus = KOHTEET[kohde]
    nyt = nyt or time.localtime()
    paiva = time.strftime("%Y-%m-%d", nyt)
    toiminto, nimi = jasenna(komento)
    if toiminto == "tila":
        if not asetus["tila"]:
            raise Virhe("komento ei ole sallittu taman kontin avaimelle")
        return {"ok": True, "tila": kerro_tila(suorita)}
    nykyiset = nimet(_pct(suorita, "listsnapshot", kohde))
    if toiminto == "listaa":
        return {"ok": True, "snapshotit": nykyiset}
    if nimi in nykyiset:
        raise Virhe("snapshot on jo olemassa: " + nimi)
    if len(nykyiset) >= asetus["max_snapshotia"]:
        raise RajaVirhe("snapshotteja jo %d (raja %d): siivoa kasin isannalla" % (len(nykyiset), asetus["max_snapshotia"]))
    if paivan_otot(loki, paiva, kohde) >= asetus["max_paivassa"]:
        raise RajaVirhe("paivan raja %d snapshotia tayttynyt" % asetus["max_paivassa"])
    if asetus["levy_raja"] is not None:
        tarkista_levy(kohde, asetus["levy_raja"], suorita)
    _pct(suorita, "snapshot", kohde, nimi, "--description", "CT%s-pyynto" % kohde)
    return {"ok": True, "snapshot": nimi}


def _puhdista(teksti):
    """Lokiin vain nakyva ASCII: rivinvaihto tai ohjausmerkki ei voi luoda tai vaarentaa lokiriveja."""
    return re.sub(r"[^\x20-\x7e]", "?", teksti)[:80]


def kirjaa(loki, tila, komento, kohde=OLETUS_KOHDE):
    komento = _puhdista(komento)
    laji = "snapshot" if komento.startswith("snapshot ") else "muu"
    tunnus = "" if kohde == OLETUS_KOHDE else "ct=%s " % kohde      # CT115:n rivimuoto on ennallaan
    try:
        with open(loki, "a") as f:
            f.write("%s %s %s %s%s\n" % (time.strftime("%Y-%m-%d"), laji, tila, tunnus, komento))
    except OSError:
        pass


def main(argv=()):
    komento = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    kohde = OLETUS_KOHDE
    try:
        kohde = kohde_argumentista(argv)
        with open(LUKKO, "w") as lukko:
            fcntl.flock(lukko, fcntl.LOCK_EX | fcntl.LOCK_NB)
            tulos = aja(komento, kohde=kohde)
        kirjaa(LOKI, "ok", komento, kohde)
        print(json.dumps(tulos))
        return 0
    except (Virhe, OSError, subprocess.TimeoutExpired) as e:
        tila = getattr(e, "tila", "virhe") if KOHTEET[kohde]["tarkka_loki"] else "virhe"
        kirjaa(LOKI, tila, komento, kohde)
        print(json.dumps({"ok": False, "virhe": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
