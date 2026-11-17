"""Aivon keskustelumuistin tiivistyksen komentorivi: valitsee muistialueen ja antaa ajon alueen omalle moduulille.

Kaytto:  python3 -m aivo.tiivista --alue yksityinen [--kuiva] [--juuri KANSIO] [--malli-url URL]
Alueen ajo on moduulissa aivo.tiivista_yksityinen (paikallinen malli, vain loopback)."""
import argparse
import sys

from aivo import tiivista_yksityinen


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m aivo.tiivista", description=__doc__.split("\n")[0], add_help=False)
    ap.add_argument("--alue", required=True, choices=("yksityinen",), help="muistialue")
    a, loput = ap.parse_known_args(argv)
    return tiivista_yksityinen.main(loput)


if __name__ == "__main__":
    sys.exit(main())
