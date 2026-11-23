#!/usr/bin/env python3
"""Tarkistaa, etta repon Python-tiedostot kaantyvat Python 3.10:lla (CI-matriisin vanhin versio).

Peruste: tulos 2026-11-08-33. Koodi meni lapi 3.13:lla, mutta 3.10 kaatui jo tuonnissa (esim. f-merkkijonon
lausekkeessa kenoviiva, sallittu vasta 3.12:ssa, PEP 701).

Kaytto: tools/py310_tarkistus.py [--python POLKU] [HAKEMISTO]   (oletus: nykyinen hakemisto)
Tulkki: --python, muuten ympariston PY310, muuten pysyva /opt/python310 (uv-asennus UV_PYTHON_INSTALL_DIR=/opt/python310),
muuten varapolku /opt/agentscope/tyo/_apu/pythons/cpython-3.10*/bin/python3.10. Ajuri ei valita PY310:ta agentille
(lapsen ymparisto on rajattu), joten pysyva oletuspolku on se, joka toimii agentin ajossa.
Tuloste: yksi rivi per virhe, "tiedosto:rivi: virheen tyyppi". Virheviestin tekstia ei tulosteta.
Tulkin versio varmistetaan (oltava tasan 3.10). Muu versio tai puuttuva tulkki tulostaa "EPAVARMA: ..." eika koskaan "OK".
Poistumiskoodi: 0 kaikki kaantyy, 1 kaantovirhe, 3 oikeaa 3.10-tulkkia ei loydy (EPAVARMA), 2 muu virhe (esim. hakemistoa ei ole).
Vain stdlib. Tavukoodi ohjataan tilapaiseen hakemistoon, joten repoon ei jaa __pycache__-tiedostoja.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

PYSYVA_HAUT = ["/opt/python310/bin/python3.10", "/opt/python310/cpython-3.10*/bin/python3.10"]
OLETUS_HAKU = "/opt/agentscope/tyo/_apu/pythons/cpython-3.10*/bin/python3.10"
EI_TULKKIA = 3
POISTETUT = r"[\\/](\.git|\.venv|venv|node_modules|__pycache__)[\\/]"
TIEDOSTO_RE = re.compile(r'^\s*File "(.+)", line (\d+)')
TYYPPI_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):")
TIEDOSTO_VIRHE_RE = re.compile(r"^\*\*\* Error compiling '(.+)'")


def loyda_tulkki(polku=None):
    ehdokkaat = [polku, os.environ.get("PY310")]
    for haku in PYSYVA_HAUT + [OLETUS_HAKU]:
        ehdokkaat += sorted(glob.glob(haku), reverse=True)
    for e in ehdokkaat:
        if e and os.path.isfile(e) and os.access(e, os.X_OK):
            return e
    return None


def versio(tulkki):
    """Palauttaa tulkin (major, minor) tai None, jos sita ei saa ajettua."""
    try:
        p = subprocess.run([tulkki, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=30)
        a, b = p.stdout.strip().split(".")
        return int(a), int(b)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def jasenna(teksti):
    """Poimii compileallin virhetulosteesta (tiedosto, rivi, tyyppi) -kolmikot."""
    tulos = []
    tiedosto, rivi = None, "?"
    for r in teksti.splitlines():
        m = TIEDOSTO_VIRHE_RE.match(r)
        if m:
            tiedosto, rivi = m.group(1), "?"
            tulos.append([tiedosto, rivi, "tuntematon virhe"])
            continue
        m = TIEDOSTO_RE.match(r)
        if m and tulos and tulos[-1][1] == "?":
            tulos[-1][0], tulos[-1][1] = m.group(1), m.group(2)
            continue
        m = TYYPPI_RE.match(r)
        if m and tulos and tulos[-1][2] == "tuntematon virhe":
            tulos[-1][2] = m.group(1)
    return [tuple(t) for t in tulos]


def tarkista(hakemisto, tulkki):
    """Palauttaa (paluukoodi, virheet). Virheet ovat (tiedosto, rivi, tyyppi)."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PYTHONPYCACHEPREFIX=tmp)
        p = subprocess.run([tulkki, "-m", "compileall", "-q", "-x", POISTETUT, hakemisto],
                           capture_output=True, text=True, env=env)
    if p.returncode == 0:
        return 0, []
    virheet = jasenna(p.stdout + "\n" + p.stderr)
    return 1, virheet or [(hakemisto, "?", "tuntematon virhe")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hakemisto", nargs="?", default=".")
    ap.add_argument("--python", help="3.10-tulkin polku")
    a = ap.parse_args(argv)
    tulkki = loyda_tulkki(a.python)
    if not tulkki:
        print("EPAVARMA: python3.10 puuttuu (anna --python tai PY310). Tarkistusta ei tehty.")
        return EI_TULKKIA
    v = versio(tulkki)
    if v != (3, 10):
        print("EPAVARMA: tulkki ei ole 3.10 (versio %s). Tarkistusta ei tehty."
              % ("%d.%d" % v if v else "tuntematon"))
        return EI_TULKKIA
    if not os.path.isdir(a.hakemisto):
        print("VIRHE: hakemistoa ei ole")
        return 2
    koodi, virheet = tarkista(a.hakemisto, tulkki)
    for tiedosto, rivi, tyyppi in virheet:
        print("%s:%s: %s" % (tiedosto, rivi, tyyppi))
    if koodi == 0:
        print("OK: kaikki kaantyy 3.10:lla")
    return koodi


if __name__ == "__main__":
    sys.exit(main())
