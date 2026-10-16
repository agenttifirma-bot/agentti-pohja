"""Ajon kulku: kerays -> (LLM -> skeematarkistus) -> render -> (Telegram, kerran paivassa).

Oletus on kuiva-ajo: ei verkkoa. LLM ja lahetys kytketaan erikseen paalle (--llm, --send).
Virhetilanteessa lahetetaan varaviesti raakadatasta ja virhekoodista, ja paluukoodi on 1,
jolloin systemd ja sydamenlyonti nayttavat vian.
"""
import os

from . import config, kulu as kulu_mod, llm as llm_mod, sydan, telegram, tulos as tulos_mod
from .lukko import kirjoita_atomisesti, lukittu


def _laheta_kerran(teksti, env, tila, kello, hae_tg):
    """'lahetetty' | 'jo_lahetetty' | 'epaonnistui'. Merkki kirjoitetaan vasta onnistumisen jalkeen."""
    paiva = config.paiva(kello() if kello else None)
    merkki = os.path.join(tila, "lahetetty-%s.txt" % paiva)
    with lukittu(os.path.join(tila, "laheta.lock")):
        if os.path.exists(merkki):
            return "jo_lahetetty"
        if not telegram.laheta(teksti, env, hae=hae_tg):
            return "epaonnistui"
        kirjoita_atomisesti(merkki, "ok\n")
    return "lahetetty"


def suorita(agentti, env, tila, *, llm=False, laheta=False, kello=None,
            hae_llm=None, hae_tg=None, hae_sydan=None):
    """Palauttaa dictin: teksti, koodi (0/1), virhe (str|None), lahetys (str|None)."""
    os.makedirs(tila, mode=0o700, exist_ok=True)
    kulu = kulu_mod.Kulu(tila, kello)
    data = agentti.kerays()
    virhe = None
    if not llm:
        teksti = "[kuiva-ajo, LLM ei kaytossa]\n" + agentti.render_kuiva(data)
    else:
        try:
            vastaus, _ = llm_mod.kysy(agentti.viestit(data), agentti.MALLI, env, kulu, hae=hae_llm)
            tulos = tulos_mod.lue(vastaus, agentti.SKEEMA)
            if tulos.tila == "ok":
                teksti = agentti.render(tulos.sisalto)
            else:
                teksti = "%s: en tieda. Syy: %s" % (agentti.NIMI, tulos.syy)
        except kulu_mod.KulukattoYlittyi as e:
            virhe = "kulukatto_" + e.syy
        except kulu_mod.KirjanpitoVirhe:
            virhe = "kirjanpito_virhe"
        except llm_mod.LLMVirhe as e:
            virhe = e.koodi
        except tulos_mod.TulosVirhe as e:
            virhe = e.koodi
        if virhe:
            teksti = "%s: tiivistys ei onnistunut (%s).\n%s" % (agentti.NIMI, virhe, agentti.render_kuiva(data))
    lahetys = _laheta_kerran(teksti, env, tila, kello, hae_tg) if laheta else None
    koodi = 1 if (virhe or lahetys == "epaonnistui") else 0
    if koodi == 0 and laheta:
        sydan.ping(env, hae=hae_sydan)
    return {"teksti": teksti, "koodi": koodi, "virhe": virhe, "lahetys": lahetys}
