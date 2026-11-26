"""ci_testit.py: ajaa unittest-sarjan kuten `python -m unittest discover` ja nayttaa kaatuneet testit annotaatioina.

Kaytto (repon juuressa): python -m tools.ci_testit [unittest-argumentit...]
  Oletus: discover -s . -t . -p 'test_*.py' -v (sama kuin ci.yml:ssa aiemmin).

Miksi: GitHubin Actions-lokia ei voi lukea ilman tunnusta (HTTP 403), mutta check-runin annotaatiot voi.
Kun testi kaatuu, tulostetaan rivi `::error title=<testin tunnus>::<poikkeuksen tyyppi>`, jolloin kaatunut
testi nakyy tunnuksettomalla GET-kutsulla (/repos/<o>/<r>/check-runs/<id>/annotations).

Turva: annotaatioon menee vain testin tunnus ja poikkeuksen tyypin nimi, ei poikkeuksen viestia eika
tracebackia (viesti voi sisaltaa salaisuuksia). Paluuarvo on sama kuin unittestin: 0 ok, 1 kaatui,
5 ei yhtaan testia (Python 3.12+).
"""
import sys
import unittest

OLETUS = ["discover", "-s", ".", "-t", ".", "-p", "test_*.py", "-v"]
EI_TESTEJA = 5  # unittest.main: _NO_TESTS_EXITCODE (3.12+)
MAX_ANNOTAATIOT = 50  # GitHub nayttaa enintaan 50 annotaatiota tyota kohden


def _pako(arvo, ominaisuus=False):
    """GitHubin workflow-komennon koodaus: %, CR ja LF aina; ominaisuuksissa myos : ja ,."""
    s = str(arvo).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if ominaisuus:
        s = s.replace(":", "%3A").replace(",", "%2C")
    return s


def tyypin_nimi(exc_type):
    if exc_type is None:
        return "tuntematon"
    moduuli = getattr(exc_type, "__module__", "") or ""
    nimi = getattr(exc_type, "__qualname__", None) or getattr(exc_type, "__name__", "tuntematon")
    if moduuli in ("builtins", "__main__") or not moduuli:
        return nimi
    return "%s.%s" % (moduuli, nimi)


def annotaatio(tunnus, tyyppi):
    return "::error title=%s::%s" % (_pako(tunnus, ominaisuus=True), _pako(tyyppi))


class KeraavaTulos(unittest.TextTestResult):
    """TextTestResult, joka muistaa kaatuneiden testien tunnukset ja poikkeuksen tyypin (ei viestia)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.kaatuneet = []  # (tunnus, tyyppi)

    def _kirjaa(self, test, err):
        exc_type = err[0] if err else None
        self.kaatuneet.append((test.id(), tyypin_nimi(exc_type)))

    def addError(self, test, err):
        super().addError(test, err)
        self._kirjaa(test, err)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._kirjaa(test, err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._kirjaa(subtest, err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.kaatuneet.append((test.id(), "UnexpectedSuccess"))


class Ajaja(unittest.TextTestRunner):
    resultclass = KeraavaTulos


def paluuarvo(tulos):
    if tulos.testsRun == 0 and len(tulos.skipped) == 0 and sys.version_info >= (3, 12):
        return EI_TESTEJA
    return 0 if tulos.wasSuccessful() else 1


def kirjoita_annotaatiot(kaatuneet, ulos):
    for tunnus, tyyppi in kaatuneet[:MAX_ANNOTAATIOT]:
        print(annotaatio(tunnus, tyyppi), file=ulos)
    if len(kaatuneet) > MAX_ANNOTAATIOT:
        print("::error title=ci_testit::%d kaatunutta lisaa, katso loki" % (len(kaatuneet) - MAX_ANNOTAATIOT), file=ulos)
    if kaatuneet:
        print("KAATUNEET (%d):" % len(kaatuneet), file=ulos)
        for tunnus, tyyppi in kaatuneet:
            print("  %s: %s" % (tunnus, tyyppi), file=ulos)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv) or OLETUS
    ohjelma = unittest.main(module=None, argv=["python -m unittest"] + args, testRunner=Ajaja, exit=False)
    tulos = ohjelma.result
    sys.stderr.flush()
    kirjoita_annotaatiot(getattr(tulos, "kaatuneet", []), sys.stdout)
    sys.stdout.flush()
    return paluuarvo(tulos)


if __name__ == "__main__":
    sys.exit(main())
