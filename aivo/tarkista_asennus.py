"""Aivon asennuksen tilatarkistus (vain luku). Stdlib.

Kaytto: python3 -m aivo.tarkista_asennus ODOTETTU_COMMIT [--koodi /opt/agentti-pohja]
         [--yksityinen-juuri /var/lib/aivo-yksityinen] [--tyokalu-juuri /var/lib/aivo]
Tuloste: yksi rivi per tarkistus (OK/VIKA + lyhyt syy). Paluuarvo 0 vain, jos kaikki ovat OK.
Avaintiedoston sisaltoa ei koskaan avata: vain os.stat (olemassaolo ja oikeudet).
Tiivistyskansioista (molempien alueiden TIIVISTYS_ALIKANSIOT) vain os.lstat: kansioita ei listata, niiden tiedostoja
ei avata, eika mitaan luoda tai muuteta. Puuttuvasta kansiosta tulostetaan korjausvihje (install -d)."""
import argparse
import http.client
import os
import pwd
import stat
import subprocess
import sys

from aivo import tiivistelma, tyokalualue, yksityinen_alue

OLETUS_KOODI = "/opt/agentti-pohja"
OLETUS_PORTTI = 8780
CHAT_PALVELU = "aivo-chat"
TIIVISTYS_AJASTIN = "aivo-tiivista.timer"
AVAINTIEDOSTOT = ("/etc/aivo/chat-salasana",)
MODUULIT = ("aivo.chat", "aivo.tiivista", "aivo.tiivistelma")
AIKARAJA = 10
OMISTAJA_AVOIN = "kayttajanimi on Tonyn avoin paatos (aivo vai aivo-yksityinen), ks. docs/aivo-chat.md"


def aja(komento):
    """Oletusajuri: (paluukoodi, stdout). Testit korvaavat taman vaarennetulla."""
    try:
        p = subprocess.run(komento, capture_output=True, text=True, timeout=AIKARAJA)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, type(e).__name__
    return p.returncode, p.stdout.strip()


def http_get(portti, polku):
    """Oletus-HTTP: (tila, runko)."""
    yhteys = http.client.HTTPConnection("127.0.0.1", portti, timeout=AIKARAJA)
    try:
        yhteys.request("GET", polku)
        r = yhteys.getresponse()
        return r.status, r.read(200).decode("utf-8", "replace")
    finally:
        yhteys.close()


def tarkista_commit(odotettu, koodi, ajuri):
    rc, ulos = ajuri(["git", "-C", koodi, "rev-parse", "HEAD"])
    if rc != 0:
        return False, "commitia ei saatu (%s)" % koodi
    if ulos == odotettu or (len(odotettu) >= 7 and ulos.startswith(odotettu)):
        return True, ulos[:12]
    return False, "asennettu %s, odotettu %s" % (ulos[:12], odotettu[:12])


def tarkista_palvelu(nimi, ajuri):
    rc, ulos = ajuri(["systemctl", "is-active", nimi])
    tila = ulos.splitlines()[0] if ulos else "tuntematon"
    return rc == 0 and tila == "active", tila


def tarkista_terve(portti, hae):
    try:
        tila, runko = hae(portti, "/terve")
    except (OSError, http.client.HTTPException) as e:
        return False, "ei yhteytta (%s)" % type(e).__name__
    if tila != 200:
        return False, "HTTP %s" % tila
    return True, "HTTP 200"


def tarkista_moduulit(koodi):
    """Moduulit tarkistetaan tiedostoina --koodi-polusta: tiedosto on olemassa ja kaantyy.

    Tuontia ei kayteta, koska (1) aivo on jo sys.modules-sanakirjassa, joten --koodi ei
    vaikuttaisi, ja (2) tuonti ajaisi moduulin tuontiaikaisen koodin. compile() ei aja koodia."""
    puuttuu = []
    for nimi in MODUULIT:
        polku = os.path.join(koodi, *nimi.split(".")) + ".py"
        try:
            with open(polku, "rb") as f:
                lahde = f.read()
            compile(lahde, polku, "exec", dont_inherit=True)
        except FileNotFoundError:
            puuttuu.append("%s (puuttuu)" % nimi)
        except Exception as e:   # vain tyyppi, viesti voi sisaltaa salaisuuksia
            puuttuu.append("%s (%s)" % (nimi, type(e).__name__))
    return (not puuttuu), ("; ".join(puuttuu) if puuttuu else "%d moduulia" % len(MODUULIT))


def tarkista_avain(polku):
    """Vain os.stat: olemassaolo, tavallinen tiedosto, ei ryhma-/muiden oikeuksia."""
    try:
        st = os.stat(polku)
    except FileNotFoundError:
        return False, "puuttuu"
    except PermissionError:
        return False, "ei oikeutta tarkistaa (PermissionError)"
    except OSError as e:
        return False, type(e).__name__
    if not stat.S_ISREG(st.st_mode):
        return False, "ei tavallinen tiedosto"
    tila = stat.S_IMODE(st.st_mode)
    if tila & 0o077:
        return False, "oikeudet %o (pitaa olla 600)" % tila
    return True, "oikeudet %o" % tila


def oletusalueet(yksityinen_juuri=yksityinen_alue.OLETUS_JUURI, tyokalu_juuri=tyokalualue.OLETUS_JUURI):
    """Alueet, joiden tiivistyskansiot tarkistetaan. Juuret ja alikansiot tulevat aluemoduuleista."""
    return (yksityinen_alue.yksityinen_alue(yksityinen_juuri), tyokalualue.tyokalualue(tyokalu_juuri))


def _juuren_omistaja(juuri):
    """(omistajan nimi tai None, syy). Vain os.lstat; nimi pwd:sta, tuntematon uid numerona."""
    try:
        st = os.lstat(juuri)
    except FileNotFoundError:
        return None, "alueen juuri %s puuttuu" % juuri
    except OSError as e:
        return None, "alueen juurta %s ei voi tarkistaa (%s)" % (juuri, type(e).__name__)
    try:
        return pwd.getpwuid(st.st_uid).pw_name, ""
    except KeyError:
        return str(st.st_uid), ""


def korjausvihje(polku, omistaja):
    """Komento, jonka Tony voi ajaa itse. Tarkistus ei aja sita. Tuntematon omistaja => <omistaja>."""
    o = omistaja or "<omistaja>"
    vihje = "korjaus: install -d -m 700 -o %s -g %s %s" % (o, o, polku)
    if omistaja is None:
        vihje += " (" + OMISTAJA_AVOIN + ")"
    return vihje


def tarkista_kansio(alue_, alikansio):
    """Alikansio on olemassa, oikea hakemisto (ei linkki) ja tila & 0o077 == 0. Vain os.lstat polkuun."""
    polku = alue_.polku(alikansio)
    try:
        st = os.lstat(polku)
    except FileNotFoundError:
        omistaja, syy = _juuren_omistaja(alue_.juuri)
        alku = "puuttuu (%s)" % syy if syy else "puuttuu"
        return False, "%s; %s" % (alku, korjausvihje(polku, omistaja))
    except PermissionError:
        return False, "ei oikeutta tarkistaa (PermissionError); aja alueen juuren omistajana"
    except OSError as e:
        return False, type(e).__name__
    if stat.S_ISLNK(st.st_mode):
        return False, "%s on linkki, ei hakemisto" % polku
    if not stat.S_ISDIR(st.st_mode):
        return False, "%s ei ole hakemisto" % polku
    tila = stat.S_IMODE(st.st_mode)
    if tila & 0o077:
        return False, "oikeudet %o (ryhmalla tai muilla ei saa olla oikeuksia); korjaus: chmod 700 %s" % (tila, polku)
    return True, "hakemisto, oikeudet %o (%s)" % (tila, polku)


def tarkistukset(odotettu, koodi, portti, ajuri, hae, avaimet, alueet=()):
    yield "commit", lambda: tarkista_commit(odotettu, koodi, ajuri)
    yield "palvelu " + CHAT_PALVELU, lambda: tarkista_palvelu(CHAT_PALVELU, ajuri)
    yield "ajastin " + TIIVISTYS_AJASTIN, lambda: tarkista_palvelu(TIIVISTYS_AJASTIN, ajuri)
    yield "terve /terve", lambda: tarkista_terve(portti, hae)
    yield "moduulit", lambda: tarkista_moduulit(koodi)
    for a in avaimet:
        yield "avain " + a, (lambda a=a: tarkista_avain(a))
    for al in alueet:
        for k in tiivistelma.TIIVISTYS_ALIKANSIOT:
            yield "kansio %s/%s" % (al.nimi, k), (lambda al=al, k=k: tarkista_kansio(al, k))


def main(argv=None, ajuri=aja, hae=http_get, avaimet=AVAINTIEDOSTOT, tulosta=print, alueet=None):
    ap = argparse.ArgumentParser(prog="aivo.tarkista_asennus", description=__doc__.split("\n")[0])
    ap.add_argument("odotettu_commit", help="odotettu commit (koko tai vahintaan 7 merkkia)")
    ap.add_argument("--koodi", default=OLETUS_KOODI)
    ap.add_argument("--portti", type=int, default=OLETUS_PORTTI)
    ap.add_argument("--yksityinen-juuri", default=yksityinen_alue.OLETUS_JUURI, help="yksityisen alueen juuri")
    ap.add_argument("--tyokalu-juuri", default=tyokalualue.OLETUS_JUURI, help="tyokalualueen juuri")
    a = ap.parse_args(argv)
    if alueet is None:
        alueet = oletusalueet(a.yksityinen_juuri, a.tyokalu_juuri)
    kaikki_ok = True
    for nimi, tarkistus in tarkistukset(a.odotettu_commit, a.koodi, a.portti, ajuri, hae, avaimet, alueet):
        try:
            ok, syy = tarkistus()
        except Exception as e:
            ok, syy = False, "poikkeus " + type(e).__name__
        kaikki_ok = kaikki_ok and ok
        tulosta("%-4s %s: %s" % ("OK" if ok else "VIKA", nimi, syy))
    return 0 if kaikki_ok else 1


if __name__ == "__main__":
    sys.exit(main())
