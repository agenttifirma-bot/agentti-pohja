"""Aivon muistialue: hakemistopuu, jonka alta kaikki tilan polut johdetaan (suunnitelma aivo-keskustelumuisti, kohta 4).

Tama moduuli on tilaneutraali: siina ei ole yhtaan oletuspolkua eika viittausta yksityiseen tai tyokalutilaan.
Tilakohtaiset polut ovat omissa moduuleissaan (`yksityinen_alue`, `tyokalualue`), jotta erottelun voi todentaa
rakenteellisesti (ks. test_alue_erottelu.py). Ei mallikutsuja, ei verkkoa, ei alaprosesseja.
"""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

ALIKANSIO_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


class AlueVirhe(Exception):
    """Muistialueen tarkistus epaonnistui. Viesti ei sisalla polkuja eika sisaltoa."""


def tarkista_hakemisto(polku, luo=True, korjaa=True):
    """Kansion pitaa olla oikea kansio (ei linkki), prosessin kayttajan oma ja 0700. Liian laajat oikeudet yritetaan
    korjata; jos se ei onnistu, kieltaydytaan. korjaa=False: vain tarkistus (lukupolku ei muuta oikeuksia; liian
    laajat oikeudet => AlueVirhe). Palauttaa Path-olion."""
    p = Path(polku)
    if luo:
        try:
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as e:
            raise AlueVirhe("kansiota ei voi luoda (%s)" % type(e).__name__)
    try:
        st = os.lstat(p)
    except OSError as e:
        raise AlueVirhe("kansio puuttuu (%s)" % type(e).__name__)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise AlueVirhe("alueen kansion pitaa olla oikea kansio, ei linkki")
    if st.st_uid != os.geteuid():
        raise AlueVirhe("alueen kansio ei kuulu palvelun kayttajalle")
    if stat.S_IMODE(st.st_mode) & 0o077:
        if not korjaa:
            raise AlueVirhe("alueen kansion oikeudet ovat liian laajat")
        try:
            os.chmod(p, 0o700)
        except OSError:
            raise AlueVirhe("alueen kansion oikeudet ovat liian laajat")
    return p


def tarkista_tiedostot(kansio):
    """Kansion suorat tiedostot: ei linkkeja, ei muita kuin tavallisia tiedostoja ja ei toisen omistajan tiedostoja.
    Liian laajat oikeudet korjataan 0600:ksi; jos korjaus ei onnistu, kieltaydytaan."""
    try:
        nimet = sorted(os.listdir(kansio))
    except OSError as e:
        raise AlueVirhe("kansiota ei voi lukea (%s)" % type(e).__name__)
    for nimi in nimet:
        p = Path(kansio) / nimi
        try:
            st = os.lstat(p)
        except OSError as e:
            raise AlueVirhe("tiedostoa ei voi tarkistaa (%s)" % type(e).__name__)
        if not stat.S_ISREG(st.st_mode):
            raise AlueVirhe("alueen kansiossa on muu kuin tavallinen tiedosto (linkki tai kansio)")
        if st.st_uid != os.geteuid():
            raise AlueVirhe("alueen tiedosto ei kuulu palvelun kayttajalle")
        if stat.S_IMODE(st.st_mode) & 0o077:
            try:
                os.chmod(p, 0o600)
            except OSError:
                raise AlueVirhe("alueen tiedoston oikeudet ovat liian laajat")


@dataclass(frozen=True)
class Alue:
    """Yksi muistialue: nimi, juurikansio ja sallittu alikansioiden joukko. Polut johdetaan vain taalta."""
    nimi: str
    juuri: Path
    alikansiot: tuple

    def __post_init__(self):
        object.__setattr__(self, "juuri", Path(self.juuri))
        object.__setattr__(self, "alikansiot", tuple(self.alikansiot))
        if not self.juuri.is_absolute():
            raise AlueVirhe("alueen juuren pitaa olla absoluuttinen polku")
        if len(set(self.alikansiot)) != len(self.alikansiot):
            raise AlueVirhe("alikansiot eivat saa toistua")
        for a in self.alikansiot:
            if not isinstance(a, str) or not ALIKANSIO_RE.match(a):
                raise AlueVirhe("virheellinen alikansion nimi")

    def polku(self, alikansio):
        """Alikansion polku. Vain ennalta maaratyt alikansiot kelpaavat (ei '..', ei vierasta nimea)."""
        if alikansio not in self.alikansiot:
            raise AlueVirhe("alikansio ei kuulu alueeseen %s" % self.nimi)
        return self.juuri / alikansio

    def sisaltaa(self, polku):
        """Onko polku (symlinkit avattuna) alueen juuren alla tai sama kuin juuri."""
        try:
            Path(os.path.realpath(polku)).relative_to(os.path.realpath(self.juuri))
        except ValueError:
            return False
        return True

    def valmista(self, luo=True):
        """Luo ja tarkistaa juuren seka kaikki alikansiot (omistaja, 0700, ei linkkeja) ja niiden tiedostot (0600).
        Palauttaa {alikansio: Path}."""
        tarkista_hakemisto(self.juuri, luo=luo)
        tulos = {}
        for a in self.alikansiot:
            p = tarkista_hakemisto(self.polku(a), luo=luo)
            tarkista_tiedostot(p)
            tulos[a] = p
        return tulos


def tarkista_erottelu(a, b):
    """Kaksi aluetta eivat saa olla sama kansio eivatka toistensa sisalla (symlinkit avattuna)."""
    ra, rb = Path(os.path.realpath(a.juuri)), Path(os.path.realpath(b.juuri))
    for x, y in ((ra, rb), (rb, ra)):
        try:
            x.relative_to(y)
        except ValueError:
            continue
        raise AlueVirhe("alueet %s ja %s ovat paallekkaiset" % (a.nimi, b.nimi))
