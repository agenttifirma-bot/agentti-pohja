"""CI:n testiajo: sama unittest-discover kuin ennen, mutta kaatuneista testeista tulee GitHub-annotaatiot.

Syy: ilman tunnusta Actions-loki palauttaa HTTP 403, joten kaatuneen testin nimi nakyi vain lokissa.
Check-runin annotaatiot (`::error`) ovat luettavissa ilman tunnusta.
Annotaatioon tulee vain testin tunnus ja poikkeuksen tyyppi, ei poikkeuksen viestia (se voi sisaltaa mita tahansa).

Kaytto: python tools/ci_testit.py [-s HAKEMISTO] [-t JUURI] [-p KUVIO]   (oletus: -s . -t . -p 'test_*.py')
Paluukoodi: 0 = kaikki lapi, 1 = jokin kaatui tai antoi virheen."""
import argparse
import re
import sys
import unittest

ENINTAAN_RIVEJA = 30
_SALLITUT = re.compile(r"[^A-Za-z0-9_.()\[\] -]")


def _puhdista(teksti):
    """Vain turvalliset merkit: ei rivinvaihtoja, `::`-erotinta eika muita merkkeja, joilla annotaation voisi rikkoa."""
    return _SALLITUT.sub("?", str(teksti))[:200]


def annotaatiot(tulos):
    """Annotaatiorivit kaatuneista ja virheen antaneista testeista (enintaan ENINTAAN_RIVEJA + yhteenvetorivi)."""
    kaatuneet = list(tulos.failures) + list(tulos.errors)
    rivit = []
    for testi, _jaljitys in kaatuneet[:ENINTAAN_RIVEJA]:
        # _jaljitys on tekstia; tyyppi luetaan tulokseen talletetusta poikkeuksesta, ei viestista.
        tyyppi = tulos.poikkeustyypit.get(id(testi), "Exception") if hasattr(tulos, "poikkeustyypit") else "Exception"
        rivit.append("::error title=Kaatunut testi::%s (%s)" % (_puhdista(testi.id()), _puhdista(tyyppi)))
    if len(kaatuneet) > ENINTAAN_RIVEJA:
        rivit.append("::error title=Kaatunut testi::... ja %d muuta kaatunutta testia" % (len(kaatuneet) - ENINTAAN_RIVEJA))
    return rivit


class _Tulos(unittest.TextTestResult):
    """Tallettaa poikkeuksen tyypin testikohtaisesti (traceback-tekstista sen saisi vain arvaamalla)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.poikkeustyypit = {}

    def addFailure(self, test, err):
        self.poikkeustyypit[id(test)] = err[0].__name__
        super().addFailure(test, err)

    def addError(self, test, err):
        self.poikkeustyypit[id(test)] = err[0].__name__
        super().addError(test, err)


def aja(hakemisto=".", juuri=".", kuvio="test_*.py"):
    sarja = unittest.TestLoader().discover(hakemisto, pattern=kuvio, top_level_dir=juuri)
    tulos = unittest.TextTestRunner(verbosity=2, resultclass=_Tulos).run(sarja)
    for rivi in annotaatiot(tulos):
        print(rivi, flush=True)
    return 0 if tulos.wasSuccessful() else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-s", dest="hakemisto", default=".")
    p.add_argument("-t", dest="juuri", default=".")
    p.add_argument("-p", dest="kuvio", default="test_*.py")
    a = p.parse_args(argv)
    return aja(a.hakemisto, a.juuri, a.kuvio)


if __name__ == "__main__":
    sys.exit(main())
