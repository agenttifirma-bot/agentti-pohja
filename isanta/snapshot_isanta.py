#!/usr/bin/env python3
"""Isannan pakotettu komento: CT115 saa ottaa snapshotin itsestaan.

Asennetaan Proxmox-isannalle (asenna.sh) ja kytketaan authorized_keys-riviin:
  from="<CT115-IP>",restrict,command="/root/snapshot-kutsu.py" ssh-ed25519 ...

Sallitut komennot (SSH_ORIGINAL_COMMAND):
  listaa             -> CT115:n snapshotit
  snapshot ennen-xxx -> ottaa snapshotin (vain nimet muotoa ennen-<a-z0-9->)
Ei poistoa, ei rollbackia, ei muita kontteja. Rajat: enintaan 20 snapshotia, 10 ottoa/vrk.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time

CT = "115"
NIMI_RE = re.compile(r"^ennen-[a-z0-9][a-z0-9-]{1,40}$")
RIVI_RE = re.compile(r"`->\s+(\S+)")
MAX_SNAPSHOTIA = 20
MAX_PAIVASSA = 10
LOKI = "/var/log/snapshot-kutsu.log"
LUKKO = "/run/snapshot-kutsu.lock"


class Virhe(Exception):
    pass


def jasenna(komento):
    osat = (komento or "").split()
    if osat == ["listaa"]:
        return ("listaa", None)
    if len(osat) == 2 and osat[0] == "snapshot":
        if not NIMI_RE.match(osat[1]):
            raise Virhe("nimen pitaa olla muotoa ennen-<a-z0-9-> (8-47 merkkia)")
        return ("snapshot", osat[1])
    raise Virhe("sallitut komennot: listaa | snapshot ennen-<nimi>")


def nimet(listaus):
    return [n for n in RIVI_RE.findall(listaus) if n != "current"]


def _pct(suorita, *args):
    r = suorita(["pct", *args], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise Virhe(("pct %s epaonnistui: " % args[0]) + (r.stderr or r.stdout).strip()[-200:])
    return r.stdout


def paivan_otot(loki, paiva):
    try:
        with open(loki) as f:
            return sum(1 for rivi in f if rivi.startswith(paiva) and " snapshot ok " in rivi)
    except OSError:
        return 0


def aja(komento, suorita=subprocess.run, loki=LOKI, nyt=None):
    nyt = nyt or time.localtime()
    paiva = time.strftime("%Y-%m-%d", nyt)
    toiminto, nimi = jasenna(komento)
    nykyiset = nimet(_pct(suorita, "listsnapshot", CT))
    if toiminto == "listaa":
        return {"ok": True, "snapshotit": nykyiset}
    if nimi in nykyiset:
        raise Virhe("snapshot on jo olemassa: " + nimi)
    if len(nykyiset) >= MAX_SNAPSHOTIA:
        raise Virhe("snapshotteja jo %d (raja %d): siivoa kasin isannalla" % (len(nykyiset), MAX_SNAPSHOTIA))
    if paivan_otot(loki, paiva) >= MAX_PAIVASSA:
        raise Virhe("paivan raja %d snapshotia tayttynyt" % MAX_PAIVASSA)
    _pct(suorita, "snapshot", CT, nimi, "--description", "CT115-pyynto")
    return {"ok": True, "snapshot": nimi}


def kirjaa(loki, tila, komento):
    laji = "snapshot" if komento.startswith("snapshot ") else "muu"
    try:
        with open(loki, "a") as f:
            f.write("%s %s %s %s\n" % (time.strftime("%Y-%m-%d"), laji, tila, komento[:80]))
    except OSError:
        pass


def main():
    komento = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    try:
        with open(LUKKO, "w") as lukko:
            fcntl.flock(lukko, fcntl.LOCK_EX | fcntl.LOCK_NB)
            tulos = aja(komento)
        kirjaa(LOKI, "ok", komento)
        print(json.dumps(tulos))
        return 0
    except (Virhe, OSError, subprocess.TimeoutExpired) as e:
        kirjaa(LOKI, "virhe", komento)
        print(json.dumps({"ok": False, "virhe": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
