"""Agentin tiedostotyokalut: lue, kirjoita, listaa ja valmis. Vain oma tyokansio.

Ei verkkoa, ei aliprosesseja, ei koodin ajoa. Rakennetesti varmistaa, ettei tama moduuli tuo
urllib-, socket-, http- eika subprocess-moduuleja. Poistotyokalua ei ole.
Kaikki virheet palautetaan Tulos-oliona; mikaan mallin antama arvo ei nosta poikkeusta ulos.
"""
import os
from dataclasses import dataclass

from . import polut
from .polut import PolkuVirhe

RAJA_LUKU = 64 * 1024        # tavua kerralla
RAJA_RIVIT = 500             # listaus ja luettavat rivit
RAJA_RAPORTTI = 20 * 1024    # valmis(raportti), merkkia


class TyokaluVirhe(Exception):
    """Virheellinen argumentti. Viesti on turvallinen nayttaa mallille."""


@dataclass(frozen=True)
class Tulos:
    ok: bool
    teksti: str
    valmis: bool = False


def puhdista(teksti):
    """Tekee ohjausmerkeista nakyvia (\\xNN); rivinvaihto ja sarkain sailyvat."""
    ulos = []
    for c in teksti:
        o = ord(c)
        if c in "\n\t" or (o >= 32 and o != 127 and not 0x80 <= o < 0xA0):
            ulos.append(c)
        else:
            ulos.append("\\x%02x" % o)
    return "".join(ulos)


def _kokonaisluku(arvo, nimi, pienin, suurin):
    if isinstance(arvo, bool) or not isinstance(arvo, int):
        raise TyokaluVirhe(nimi + " pitaa olla kokonaisluku")
    if not pienin <= arvo <= suurin:
        raise TyokaluVirhe("%s pitaa olla valilla %d-%d" % (nimi, pienin, suurin))
    return arvo


def _tarkista_avaimet(arg, sallitut):
    outo = set(arg) - set(sallitut)
    if outo:
        raise TyokaluVirhe("tuntemattomia argumentteja")


def lue(juuri, arg):
    _tarkista_avaimet(arg, ("polku", "alku", "rivit"))
    osat = polut.jasenna_polku(arg.get("polku"))
    alku = _kokonaisluku(arg.get("alku", 0), "alku", 0, 10**9)
    rivit = _kokonaisluku(arg.get("rivit", 200), "rivit", 1, RAJA_RIVIT)
    kansio = polut.avaa_kansio(juuri, osat[:-1])
    try:
        tila = polut.tarkista_tiedosto(kansio, osat[-1])
        if tila is None:
            raise PolkuVirhe("tiedostoa ei ole")
        if tila.st_size > polut.RAJA_TIEDOSTO:
            raise PolkuVirhe("tiedosto on liian suuri luettavaksi")
        try:
            fd = os.open(osat[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=kansio)
        except OSError:
            raise PolkuVirhe("tiedosto ei aukea (linkki?)") from None
    finally:
        os.close(kansio)
    with os.fdopen(fd, "rb") as f:
        raaka = f.read(polut.RAJA_TIEDOSTO + 1)
    if len(raaka) > polut.RAJA_TIEDOSTO:
        raise PolkuVirhe("tiedosto on liian suuri luettavaksi")
    try:
        teksti = raaka.decode("utf-8")
    except UnicodeDecodeError:
        raise TyokaluVirhe("tiedosto ei ole UTF-8-tekstia") from None
    kaikki = teksti.splitlines()
    valittu = kaikki[alku:alku + rivit]
    ulos = []
    koko = 0
    katkaistu = False
    for r in valittu:
        r = puhdista(r)
        koko += len(r.encode("utf-8")) + 1
        if koko > RAJA_LUKU:
            katkaistu = True
            break
        ulos.append(r)
    loppu = alku + len(ulos)
    teksti_ulos = "\n".join(ulos)
    if katkaistu or loppu < len(kaikki):
        teksti_ulos += "\n[luettu rivit %d-%d / %d; jatka alku=%d]" % (alku, loppu, len(kaikki), loppu)
    return Tulos(True, teksti_ulos)


def kirjoita(juuri, arg):
    _tarkista_avaimet(arg, ("polku", "sisalto"))
    osat = polut.jasenna_polku(arg.get("polku"))
    polut.tarkista_paate(osat)
    sisalto = arg.get("sisalto")
    if not isinstance(sisalto, str):
        raise TyokaluVirhe("sisalto pitaa olla merkkijono")
    try:
        data = sisalto.encode("utf-8")
    except UnicodeEncodeError:
        raise TyokaluVirhe("sisalto ei ole kelvollista UTF-8-tekstia") from None
    if b"\x00" in data:
        raise TyokaluVirhe("sisalto sisaltaa NUL-merkin")
    try:
        kansio = polut.avaa_kansio(juuri, osat[:-1])
    except polut.KansioPuuttuu:
        # uusi tiedosto uuteen kansioon: tila tarkistetaan ennen kansioiden luontia,
        # jotta hylatty kirjoitus ei jata tyhjia kansioita
        polut.tarkista_tila(juuri, len(data), None)
        kansio = polut.avaa_kansio(juuri, osat[:-1], luo=True)
    nimi = osat[-1]
    valiaikainen = polut.valiaikainen_nimi()
    try:
        vanha = polut.tarkista_tiedosto(kansio, nimi)
        polut.tarkista_tila(juuri, len(data), None if vanha is None else vanha.st_size)
        try:
            fd = os.open(valiaikainen, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=kansio)
        except OSError:
            raise PolkuVirhe("kirjoitus ei onnistu") from None
        try:
            with os.fdopen(fd, "wb") as f:
                polut.lukitse_valiaikainen(f.fileno())   # lukko pysyy, kunnes tiedosto on nimetty
                f.write(data)
                f.flush()
                os.replace(valiaikainen, nimi, src_dir_fd=kansio, dst_dir_fd=kansio)
        except BaseException:
            try:
                os.unlink(valiaikainen, dir_fd=kansio)
            except OSError:
                pass
            raise
    finally:
        os.close(kansio)
    return Tulos(True, "kirjoitettu %s (%d tavua)" % ("/".join(osat), len(data)))


def listaa(juuri, arg):
    _tarkista_avaimet(arg, ("polku",))
    osat = polut.jasenna_polku(arg.get("polku", ""), salli_tyhja=True)
    kansio = polut.avaa_kansio(juuri, osat)
    rivit = []
    try:
        with os.scandir(kansio) as it:
            kohteet = sorted(it, key=lambda e: e.name)
            for e in kohteet:
                nimi = puhdista(e.name)
                tila = e.stat(follow_symlinks=False)
                if e.is_symlink():
                    rivit.append("l " + nimi)
                elif e.is_dir(follow_symlinks=False):
                    rivit.append("d " + nimi + "/")
                else:
                    rivit.append("f %s %d" % (nimi, tila.st_size))
    finally:
        os.close(kansio)
    if len(rivit) > RAJA_RIVIT:
        yli = len(rivit) - RAJA_RIVIT
        rivit = rivit[:RAJA_RIVIT] + ["[%d rivia pois]" % yli]
    return Tulos(True, "\n".join(rivit) if rivit else "(tyhja)")


def valmis(juuri, arg):
    _tarkista_avaimet(arg, ("raportti",))
    raportti = arg.get("raportti")
    if not isinstance(raportti, str) or not raportti.strip():
        raise TyokaluVirhe("raportti puuttuu")
    if len(raportti.encode("utf-8", "replace")) > RAJA_RAPORTTI:
        raise TyokaluVirhe("raportti on liian pitka (enintaan %d kt)" % (RAJA_RAPORTTI // 1024))
    return Tulos(True, raportti, valmis=True)


TYOKALUT = {"lue": lue, "kirjoita": kirjoita, "listaa": listaa, "valmis": valmis}


def suorita(juuri, nimi, arg):
    """Ajaa yhden tyokalun tyokansiossa `juuri`. Ei nosta poikkeusta: virhe tulee Tulos(ok=False)-oliona."""
    toiminto = TYOKALUT.get(nimi)
    if toiminto is None:
        return Tulos(False, "tuntematon tyokalu")
    if not isinstance(arg, dict):
        return Tulos(False, "arg pitaa olla JSON-olio")
    try:
        return toiminto(juuri, arg)
    except (PolkuVirhe, TyokaluVirhe) as e:
        return Tulos(False, str(e))
    except OSError:
        return Tulos(False, "tiedostovirhe")
    except Exception as e:  # mallin arvo ei saa kaataa silmukkaa; vain tyypin nimi (ei viestia)
        return Tulos(False, "sisainen virhe (" + type(e).__name__ + ")")
