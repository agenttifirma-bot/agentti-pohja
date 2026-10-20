"""Kerays: siirtaa agenttien tekstilokien rivit tapahtumalokiin (lukija/kirjoittaja-erottelu).

Agentti kirjoittaa vain oman lokinsa (esim. paivakatsaus.log); tama kerays ajetaan erikseen (root,
ajastin) ja lukee lokia ja kirjoittaa tietokantaan. Agentti ei saa uusia oikeuksia, eika kerays
suorita mitaan lokin sisallosta: rivit vain jasennetaan.

Rivimuoto: `ISO-AIKA KOMPONENTTI avain=arvo avain=arvo ...`. Hiljaiset rutiinirivit (tapahtuma=tyhja)
ohitetaan. Tulos on `virhe`, jos rivilla on virhekoodi; muuten tapahtuma-kentan arvo tai `ok`.
Edistyminen (tavusiirtyma) kirjataan tilatiedostoon: sama rivi ei kirjaudu kahdesti, ja kesken
kirjoituksen oleva viimeinen rivi odottaa seuraavaa ajoa. Pienentynyt tiedosto (kierto) luetaan alusta.
"""
import json
import os
import re
import sys
from datetime import datetime

from . import tapahtumaloki

RIVI = re.compile(r"^(\S+) (\w+)(?: (.*))?$")
PARI = re.compile(r"(\w+)=(\S*)")
HILJAISET = {("tapahtuma", "tyhja")}
MAX_RIVEJA_AJOSSA = 2000
MAX_KENTTIA = 12


def jasenna_rivi(rivi):
    """Palauttaa (aika, komponentti, kentat) tai None, jos rivi ei ole tunnettua muotoa."""
    m = RIVI.match(rivi.rstrip("\n"))
    if not m:
        return None
    try:
        aika = datetime.fromisoformat(m.group(1)).timestamp()
    except ValueError:
        return None
    kentat = dict(PARI.findall(m.group(3) or ""))
    return aika, m.group(2), kentat


def _luku(arvo):
    try:
        luku = float(arvo)
    except (TypeError, ValueError):
        return None
    return luku if luku >= 0 else None


def tapahtuma_riveista(aika, komponentti, kentat):
    """Kuvaa jasennetyn rivin kirjattavaksi tapahtumaksi, tai None jos se on hiljainen."""
    if any(kentat.get(k) == v for k, v in HILJAISET):
        return None
    virhe = kentat.get("virhekoodi")
    tulos = "virhe" if virhe and virhe != "-" else kentat.get("tapahtuma") or "ok"
    kulu = _luku(kentat.get("kulu_usd"))
    tiedot = {k: v for k, v in list(kentat.items())[:MAX_KENTTIA] if k not in ("kulu_usd",)}
    return {"aika": aika, "tyyppi": komponentti, "tulos": tulos, "kulu_usd": kulu, "tiedot": tiedot}


def _lue_tila(polku):
    try:
        with open(polku, encoding="utf-8") as f:
            t = json.load(f)
        return int(t.get("siirtyma", 0)), int(t.get("inode", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0, 0


def keraa(lokipolku, tilapolku, tietokanta, lahde, agentti, max_rivia=MAX_RIVEJA_AJOSSA):
    """Keraa uudet rivit. Palauttaa kirjattujen tapahtumien maaran. Puuttuva loki = 0."""
    try:
        st = os.stat(lokipolku)
    except OSError:
        return 0
    siirtyma, inode = _lue_tila(tilapolku)
    if st.st_size < siirtyma or (inode and inode != st.st_ino):
        siirtyma = 0  # kierretty tai vaihdettu tiedosto
    with open(lokipolku, "rb") as f:
        f.seek(siirtyma)
        data = f.read(min(st.st_size - siirtyma, 4_000_000))
    loppu = data.rfind(b"\n") + 1  # vain kokonaiset rivit
    rivit = data[:loppu].decode("utf-8", "replace").splitlines()[:max_rivia]
    kasitelty = sum(len(r.encode("utf-8", "replace")) + 1 for r in rivit) if len(rivit) == max_rivia else loppu
    yht = tapahtumaloki.avaa(tietokanta)
    maara = 0
    try:
        for rivi in rivit:
            j = jasenna_rivi(rivi)
            if not j:
                continue
            t = tapahtuma_riveista(*j)
            if not t:
                continue
            tapahtumaloki.kirjaa(yht, lahde, agentti, t["tyyppi"], t["tulos"], kulu_usd=t["kulu_usd"],
                                 tiedot=t["tiedot"], nyt=t["aika"])
            maara += 1
    finally:
        yht.close()
    tmp = tilapolku + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"siirtyma": siirtyma + kasitelty, "inode": st.st_ino}, f)
    os.replace(tmp, tilapolku)
    return maara


def main(argv=None):
    """python3 -m agentti.loki_keraaja LOKI TILA LAHDE AGENTTI   (tietokanta: TAPAHTUMALOKI)"""
    argv = sys.argv[1:] if argv is None else argv
    polku = os.environ.get("TAPAHTUMALOKI")
    if len(argv) != 4 or not polku:
        print("kaytto: TAPAHTUMALOKI=db python3 -m agentti.loki_keraaja LOKI TILA LAHDE AGENTTI", file=sys.stderr)
        return 2
    print("kerattu: %d" % keraa(argv[0], argv[1], polku, argv[2], argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
