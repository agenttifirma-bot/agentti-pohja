"""Testiapu: salasanatiiviste lasketaan kerran per salasana ja prosessi.

Tuotannon scrypt-parametreja ei kevenneta: tiivista_salasana ajaa saman laskennan kuin ennen,
mutta vain kerran. Kirjautumisen tarkistus (tarkista_salasana) ajaa edelleen oikean scryptin.
"""
import functools

from aivo import chat


@functools.lru_cache(maxsize=None)
def tiiviste(salasana):
    return chat.tiivista_salasana(salasana)
