"""Tyokansion sisainen polkujen tarkistus.

Saannot: polku ratkaistaan tyokansion juuren alle. Hylataan `..`, absoluuttinen polku, symbolinen
linkki (lehti ja valikansio), ylisuuri tiedosto, kielletty paate ja tyokansion tayttyminen.
Kansiot avataan osa kerrallaan lipulla O_NOFOLLOW (dir_fd), joten tarkistuksen ja avauksen valille
ei jaa kilpailuikkunaa, jossa osa vaihdettaisiin linkiksi.
"""
import fcntl
import os
import re
import stat
import threading
import time

RAJA_TIEDOSTO = 200 * 1024           # tavua per tiedosto
RAJA_KANSIO_TAVUT = 20 * 1024 * 1024  # tyokansio yhteensa
RAJA_TIEDOSTOT = 200                 # tiedostoja tyokansiossa
RAJA_SYVYYS = 8                      # kansiotasoja polussa
RAJA_NIMI = 100                      # merkkia per polun osa
RAJA_POLKU = 200                     # merkkia koko polussa
SALLITUT_PAATTEET = (".md", ".txt", ".csv", ".json")
# kirjoita-tyokalun valiaikaistiedosto: .kirj-<pid>-<saie>-<satunnainen>.tmp (vanha muoto .kirj-<pid>.tmp).
# Kirjoittaja pitaa tiedostossa flock-lukkoa, kunnes se on nimetty lopulliseksi.
VALIAIKAINEN = re.compile(r"\.kirj-[0-9]+(?:-[0-9]+-[0-9a-f]{16})?\.tmp")
VALIAIKAINEN_ARMO_S = 10             # lukitsematon tiedosto poistetaan vasta taman jalkeen (avaus -> lukitus)
VALIAIKAINEN_IKA_S = 3600            # tata vanhempi poistetaan lukosta riippumatta

class PolkuVirhe(Exception):
    """Polku tai tyokansion tila rikkoo saannon. Viesti on turvallinen nayttaa mallille."""


class KansioPuuttuu(PolkuVirhe):
    """Polun valikansiota ei ole (avaa_kansio, luo=False)."""


def jasenna_polku(polku, salli_tyhja=False):
    """Palauttaa polun osat (tuple). Hylkaa kaiken, mika ei ole puhdas suhteellinen polku."""
    if not isinstance(polku, str):
        raise PolkuVirhe("polun pitaa olla merkkijono")
    if polku == "" or polku == ".":
        if salli_tyhja:
            return ()
        raise PolkuVirhe("polku puuttuu")
    if len(polku) > RAJA_POLKU:
        raise PolkuVirhe("polku on liian pitka")
    if "\x00" in polku or any(ord(c) < 32 or ord(c) == 127 for c in polku):
        raise PolkuVirhe("polussa on ohjausmerkki")
    if "\\" in polku:
        raise PolkuVirhe("kenoviiva ei kelpaa polussa")
    if polku.startswith("/"):
        raise PolkuVirhe("absoluuttinen polku ei kelpaa")
    osat = []
    for osa in polku.split("/"):
        if osa == "..":
            raise PolkuVirhe("'..' ei kelpaa polussa")
        if osa in ("", "."):
            continue                   # a//b ja ./a tarkoittavat samaa kuin a/b
        if len(osa) > RAJA_NIMI:
            raise PolkuVirhe("polun osa on liian pitka")
        if osa.startswith("."):
            raise PolkuVirhe("pisteella alkava nimi ei kelpaa")
        osat.append(osa)
    if len(osat) > RAJA_SYVYYS:
        raise PolkuVirhe("polku on liian syva")
    if not osat and not salli_tyhja:
        raise PolkuVirhe("polku puuttuu")
    return tuple(osat)


def tarkista_paate(osat):
    """Hylkaa tiedostonimen, jonka paate ei ole sallittujen joukossa."""
    if not osat:
        raise PolkuVirhe("tiedostonimi puuttuu")
    nimi = osat[-1].lower()
    if not nimi.endswith(SALLITUT_PAATTEET) or nimi in SALLITUT_PAATTEET:
        raise PolkuVirhe("paate ei kelpaa (sallitut: " + " ".join(SALLITUT_PAATTEET) + ")")


def avaa_juuri(juuri):
    """Avaa tyokansion juuren. Itse juuri ei saa olla symbolinen linkki."""
    try:
        tila = os.lstat(juuri)
    except OSError:
        raise PolkuVirhe("tyokansiota ei voi avata") from None
    if not stat.S_ISDIR(tila.st_mode):
        raise PolkuVirhe("tyokansio ei ole tavallinen kansio")
    return os.open(juuri, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def avaa_kansio(juuri, osat, luo=False):
    """Avaa kansion `osat` tyokansion alla. Palauttaa fd:n, jonka kutsuja sulkee.

    Jokainen valikansio avataan O_NOFOLLOW + lstat-tarkistuksella; linkki hylataan.
    luo=True luo puuttuvat kansiot (vain kirjoitus).
    """
    fd = avaa_juuri(juuri)
    try:
        for osa in osat:
            try:
                tila = os.stat(osa, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if not luo:
                    raise KansioPuuttuu("kansiota ei ole") from None
                try:
                    os.mkdir(osa, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass               # rinnakkainen kirjoitus loi kansion; tarkistetaan alla
                tila = os.stat(osa, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(tila.st_mode):
                raise PolkuVirhe("symbolinen linkki ei kelpaa")
            if not stat.S_ISDIR(tila.st_mode):
                raise PolkuVirhe("polun osa ei ole kansio")
            try:
                uusi = os.open(osa, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError:
                raise PolkuVirhe("symbolinen linkki tai kansio ei aukea") from None
            os.close(fd)
            fd = uusi
        return fd
    except BaseException:
        os.close(fd)
        raise


def tarkista_tiedosto(fd, nimi):
    """Palauttaa lstat-tilan tavalliselle tiedostolle tai None, jos nimea ei ole.

    Linkki ja muu kuin tavallinen tiedosto hylataan.
    """
    try:
        tila = os.stat(nimi, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(tila.st_mode):
        raise PolkuVirhe("symbolinen linkki ei kelpaa")
    if not stat.S_ISREG(tila.st_mode):
        raise PolkuVirhe("ei ole tavallinen tiedosto")
    return tila


def _tila_tai_none(e):
    """lstat-tila scandir-kohteelle tai None, jos kohde katosi listauksen jalkeen."""
    try:
        return e.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None


def _avaa_alikansio(nimi, fd):
    """Avaa alikansion (O_NOFOLLOW) tai palauttaa None, jos se katosi listauksen jalkeen."""
    try:
        return os.open(nimi, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except FileNotFoundError:
        return None


def mittaa_kansio(juuri):
    """Palauttaa (tiedostoja, tavuja) tyokansiossa. Linkkeja ei seurata; ne lasketaan tiedostoiksi."""
    tiedostoja = 0
    tavuja = 0
    pino = [os.open(juuri, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        while pino:
            fd = pino.pop()
            try:
                with os.scandir(fd) as it:
                    for e in it:
                        tila = _tila_tai_none(e)
                        if tila is None:
                            continue           # rinnakkainen kirjoitus nimesi tai poisti kohteen
                        if stat.S_ISDIR(tila.st_mode):
                            uusi = _avaa_alikansio(e.name, fd)
                            if uusi is not None:
                                pino.append(uusi)
                        else:
                            tiedostoja += 1
                            tavuja += tila.st_size
            finally:
                os.close(fd)
    finally:
        for fd in pino:
            os.close(fd)
    return tiedostoja, tavuja


def tarkista_tila(juuri, uusi_koko, vanha_koko):
    """Hylkaa kirjoituksen, jos tyokansio ylittaisi tiedosto- tai tavurajan.

    vanha_koko on None, kun tiedosto on uusi, muuten korvattavan tiedoston koko.
    """
    if uusi_koko > RAJA_TIEDOSTO:
        raise PolkuVirhe("tiedosto on liian suuri (enintaan %d kt)" % (RAJA_TIEDOSTO // 1024))
    tiedostoja, tavuja = mittaa_kansio(juuri)
    if vanha_koko is None:
        tiedostoja += 1
        vanha_koko = 0
    if tiedostoja > RAJA_TIEDOSTOT:
        raise PolkuVirhe("tyokansio on taynna (enintaan %d tiedostoa)" % RAJA_TIEDOSTOT)
    if tavuja - vanha_koko + uusi_koko > RAJA_KANSIO_TAVUT:
        raise PolkuVirhe("tyokansio on taynna (enintaan %d Mt)" % (RAJA_KANSIO_TAVUT // (1024 * 1024)))


def valiaikainen_nimi():
    """Kirjoituksen valiaikaistiedoston nimi: pid, saie ja satunnainen osa (avataan O_EXCL)."""
    return ".kirj-%d-%d-%s.tmp" % (os.getpid(), threading.get_ident(), os.urandom(8).hex())


def lukitse_valiaikainen(fd):
    """Kirjoittajan lukko valiaikaistiedostoon. Siivous ei poista lukittua tiedostoa."""
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _kesken(nimi, fd):
    """True, jos joku pitaa lukkoa tiedostossa `nimi` (kirjoitus kesken). Kadonnut tiedosto: None."""
    try:
        tfd = os.open(nimi, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(tfd).st_mode):
            return True                # ei tavallinen tiedosto: ei kosketa
        try:
            fcntl.flock(tfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False                   # lukko vapautuu, kun tfd suljetaan
    finally:
        os.close(tfd)


def _poistettava(nimi, tila, nyt, fd):
    """Valiaikaistiedosto poistetaan, jos se on yli VALIAIKAINEN_IKA_S vanha tai jos kukaan ei pida
    siina lukkoa ja se on yli VALIAIKAINEN_ARMO_S vanha (tai muokkausaika on tulevaisuudessa).
    Lukittu tiedosto on rinnakkaisen ajon kesken oleva kirjoitus."""
    if VALIAIKAINEN.fullmatch(nimi) is None:
        return False
    ika = nyt - tila.st_mtime
    if ika > VALIAIKAINEN_IKA_S:
        return True
    if -VALIAIKAINEN_ARMO_S <= ika <= VALIAIKAINEN_ARMO_S:
        return False
    return _kesken(nimi, fd) is False


def siivoa_valiaikaiset(juuri):
    """Poistaa keskeytyneiden kirjoitusten valiaikaistiedostot tyokansiosta. Palauttaa lukumaaran.

    Vain tavalliset tiedostot, joiden nimi tasmaa tarkasti; linkkeja ei seurata. Rinnakkaisen ajon
    kesken oleva (lukittu) tiedosto jatetaan (ks. _poistettava). Kutsutaan silmukan alussa, jotta jaannokset eivat
    laske tiedostorajaa.
    """
    poistettu = 0
    nyt = time.time()
    pino = [avaa_juuri(juuri)]
    try:
        while pino:
            fd = pino.pop()
            try:
                poistettavat = []
                with os.scandir(fd) as it:
                    for e in it:
                        tila = _tila_tai_none(e)
                        if tila is None:
                            continue
                        if stat.S_ISDIR(tila.st_mode):
                            uusi = _avaa_alikansio(e.name, fd)
                            if uusi is not None:
                                pino.append(uusi)
                        elif stat.S_ISREG(tila.st_mode) and _poistettava(e.name, tila, nyt, fd):
                            poistettavat.append(e.name)
                for nimi in poistettavat:
                    try:
                        os.unlink(nimi, dir_fd=fd)
                        poistettu += 1
                    except OSError:
                        pass
            finally:
                os.close(fd)
    finally:
        for fd in pino:
            os.close(fd)
    return poistettu
