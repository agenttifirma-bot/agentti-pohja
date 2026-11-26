"""Aivon yksityisen tilan OpenRouter-taustapaa (Tonyn paatos A984; rajattu ulkoinen mallipalvelu, A728).

Vaihtoehto loopback-mallipalvelimelle (`yksityinen.kysy_paikalliselta`). Muisti, keskustelut ja ydinohjeet pysyvat
palvelun omissa kansioissa; OpenRouterille lahtee jokaisella viestilla koko kehote (ydinohjeet, valitut muistiotteet ja
keskusteluhistoria) ja ZDR on pakotettu.

Saannot (koodi on laki):
  * Yksi yhteinen kulukirjanpito ja yksi paivakatto: ei omaa kulutilaa. Oletus on `openrouter_kulut.OLETUS_TILA`,
    joten yksityisen tilan kutsut kuluttavat samaa 10 EUR/vrk kattoa kuin ajurin kutsut (A963, #309). `kulutila`-parametri
    on vain testeja varten eika sita voi asettaa palvelun asetuksista.
  * Pyynto rakennetaan aina lipulla `yksityinen_chat=True` (A984): saantomoduuli hyvaksyy sen vain avoimella mallilla.
  * Kaikki kutsut kulkevat `openrouter_kulut.kutsu`n kautta: paivakatkaisin (10 EUR/vrk) tarkistetaan ennen kutsua,
    pyynto rakennetaan `openrouter_zdr.rakenna_runko`lla (ZDR ja data_collection=deny) ja kulu kirjataan.
    Tama moduuli ei rakenna `provider`-rungon osaa eika tuo katon arvoja ulos muutettavaksi.
  * Kuljetin kieltaytyy lahettamasta, jos runko ei sisalla `provider.zdr == True` ja `provider.data_collection == "deny"`
    (toinen lukko ZDR:lle).
  * Malli on asetus eika oletusta ole. Vain tarkan listan AVOIMET_MALLIT mallit kelpaavat; suljetut mallit
    ja kaikki liitteet (`:free`, `:batch`, `:online` ym.) hylataan jo asetuksessa.
  * Malleja voi olla lista (AIVO_OPENROUTER_MALLIT, pilkuin erotettu; tarkista_mallit). Jokaisen pitaa lapaista
    avoin_malli(), muuten palvelu ei kaynnisty. Ensimmainen on oletus. Kaikilla malleilla on sama kulukirjanpito ja
    sama paivakatto.
  * Avain luetaan tiedostosta, jonka omistaa palvelun kayttaja ja jonka oikeudet ovat 0600 tai tiukemmat (ei linkki).
    Avainta ei lueta ymparistomuuttujasta, eika sita kirjoiteta lokiin, virheviesteihin eika muualle.
    Virheista nakyy vain tyyppi ja HTTP-tila.
  * Avain luetaan jokaisella kutsulla (Tony voi vaihtaa tiedoston kayttamatta palvelun uudelleenkaynnistysta) ja ennen
    paivakattovarausta: puuttuva avain ei jata varausta eika anna arvoituksellista virhetta.
  * Usean mallin yhdistelmat (aivo/yhdistelma.py, AIVO_YKSITYINEN_YHDISTELMA): jokainen osakutsu kulkee taman
    moduulin `_kysy_viestit`-funktion kautta, joka tarkistaa mallin (avoin_malli) ja kutsuu `openrouter_kulut.kutsu`a
    lipulla `yksityinen_chat=True`. Paivakatto nostaa yhdistelma.Katkaisu, joka lopettaa seuraavat osakutsut.
  * Tyokalutila ei kayta tata moduulia (testi tarkistaa).
  * Yksityisen alueen keskustelujen tiivistys (aivo/tiivista_yksityinen.py) kayttaa OpenRouteria vain funktion
    `kysy_tiivistys` kautta: sama avain, sama avoimen mallin tarkistus, sama `openrouter_kulut.kutsu` (ZDR,
    data_collection=deny, yhteinen 10 EUR/vrk katto ja kirjaus) ja lippu `yksityinen_chat=True`. Tehtavan tunniste
    on oma (TIIVISTYS_TEHTAVA), jotta tiivistyksen osuus nakyy kulukirjanpidossa.
  * Taustaajo (aivo/taustaajo.py) kayttaa OpenRouteria vain funktion `kysy_taustatyo` kautta: sama avain, sama avoimen
    mallin tarkistus, sama `openrouter_kulut.kutsu` (ZDR, data_collection=deny, yhteinen 10 EUR/vrk katto ja kirjaus),
    lippu `yksityinen_chat=True` ja sama MAX_TOKENIA kuin chatissa. Vain yhden kutsun aikaraja on pidempi
    (TAUSTA_AIKARAJA_S), koska ajattelija saa vastata hitaasti. Tehtavan tunniste on oma (TAUSTA_TEHTAVA).
  * Itsetarkistus (aivo/itsetarkistus.py, AIVO_YKSITYINEN_ITSETARKISTUS): tarkastajan ja korjauksen kutsut kulkevat
    funktion `tarkista_vastaus` kautta `_kysy_viestit`-reittia (avoin_malli, ZDR, yhteinen 10 EUR/vrk katto ja kirjaus,
    lippu `yksityinen_chat=True`). Tehtavan tunniste on oma (TARKISTUS_TEHTAVA), jotta osuus nakyy kulukirjanpidossa.
    Paivakatto nayttaa vastauksen ilman tarkistusta; kutsuraja 4 per viesti koskee yhdistelman ja tarkistuksen summaa.
    Tarkastajan lahteiden raja lasketaan tarkastajamallin kontekstista samalla laskennalla kuin kehotteen raja
    (tarkastajan_lahderaja). Korjauskutsun lisasyotteelle (itsetarkistus.KORJAUS_LISAVARAUS) varataan tila ennen
    muistin ja historian tayttoa (chat: muistin_merkkiraja, tarkista_vastaus: historian_merkkiraja).
  * Vastauksen pituusraja (A1095): OpenRouter-taustapaan MAX_TOKENIA = 8 000 on erillaan paikallisen loopback-mallin
    rajasta (yksityinen.MAX_TOKENIA = 700, i5-8400 ei ehtisi 8 000 tokenia). Yhden mallin chat-kutsun aikaraja on
    CHAT_AIKARAJA_S. Jos vastaus katkeaa pituusrajaan (finish_reason == "length"), chat lisaa loppuun
    KATKENNUT_HUOMAUTUS ja kirjaa stderriin vain tiedon katkeamisesta (ei sisaltoa). Paivakatto ja varaus eivat muutu.
  * Ajatteleva malli (paattely ja vastaus jakavat max_tokens-rajan): jos raja taytty paattelyssa, content on tyhja ja
    finish_reason "length". Silloin kaikki reitit (chat, yhdistelman osakutsu, tiivistys, taustaajo) nostavat
    VastausKatkesi-virheen (YksityinenVirhe), jonka viesti kertoo katkeamisesta; tyhjaa viestia ei palauteta.
    Taustaajon katkennut mutta ei-tyhja vastaus saa loppuun TAUSTA_KATKENNUT_HUOMAUTUS-merkinnan.
  * Kehotteen koko (A1106, aivo/kontekstiraja.py): muisti ja historia tayttavat mallin kontekstin, josta varataan
    vastaukselle MAX_TOKENIA (pienella mallilla enintaan neljannes) ja 10 % marginaali. Yhdistelmassa raja on
    pienimman mukana olevan mallin konteksti, ja roolisyotteelle varataan YHDISTELMA_LISAVARAUS. Kehotteen arvioitu
    ylin hinta pidetaan enintaan kiintean varauksen (openrouter_kulut.VARAUS_USD) suuruisena. Jokaisesta kutsusta
    stderriin (journal) kehotteen koko merkkeina ja tokeneina, arvioitu hinta ja toteutuneet tokenit (ei sisaltoa).
    Paikallisen taustapaan rajat (yksityinen.MUISTI_YLARAJA ym.) eivat muutu."""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import itsetarkistus, kontekstiraja, openrouter_kulut, yhdistelma, yksityinen
from .yksityinen import YKSITYINEN_KEHOTE, YksityinenVirhe

OLETUS_AVAIN = "/var/lib/aivo-yksityinen/openrouter-avain"
TEHTAVA = "aivo-yksityinen"
VASTAUS_AIKARAJA_S = 120
MAX_VASTAUS_TAVUA = 2_000_000
# OpenRouter-taustapaan vastausraja (Tonyn paatos A1095): noin 20 000-24 000 merkkia suomea. Paikallisen
# loopback-mallin raja on yksityinen.MAX_TOKENIA (700) eika muutu. Kulu: avoimella mallilla 8 000 tokenia ulos maksaa
# ZDR-ylarajahinnalla (0,825 USD/Mtok) noin 0,007 USD, selvasti alle kiintean varauksen (openrouter_kulut.VARAUS_USD 0,50 USD).
MAX_TOKENIA = 8_000
# Yhden mallin chat-kutsun aikaraja. stream=False: palvelin ei laheta mitaan ennen kuin koko vastaus on valmis.
# Hitaat avoimet mallit (esim. deepseek-r1) tuottavat OpenRouterissa noin 25-40 tokenia/s; 8 000 / 25 = 320 s ja
# kehotteen kasittely noin 10-30 s, joten 360 s riittaa pahimmassakin tavallisessa tapauksessa. Selain (fetch ilman
# AbortControlleria) ja ThreadingHTTPServer eivat katkaise odotusta. Yhdistelmat, tiivistys ja agentit kayttavat
# edelleen VASTAUS_AIKARAJA_S:aa (120 s) tai omaa rajaansa. Mallivertailu kayttaa samaa rajaa kuin chat
# (mallivertailu.VERTAILU_AIKARAJA_S), koska sen ajattelevat mallit saavat saman 8 000 tokenin vastausrajan.
CHAT_AIKARAJA_S = 360
KATKENNUT_HUOMAUTUS = "[vastaus katkesi pituusrajaan, kirjoita: jatka]"
TAUSTA_KATKENNUT_HUOMAUTUS = "[vastaus katkesi pituusrajaan]"
KATKESI_TYHJANA = ("Vastaus katkesi pituusrajaan ennen kuin malli ehti kirjoittaa vastauksen (ajatteleva malli "
                   "k\u00e4ytti rajan p\u00e4\u00e4ttelyyn). Kokeile uudelleen tai valitse toinen malli.")
# Historia on taustapaakohtainen. Paikallinen malli (yksityinen.HISTORIA_YLARAJA = 12) kasittelee kehotteen hitaasti
# 900 s aikarajan sisalla; OpenRouterin malli kasittelee pitkan kehotteen sekunneissa. Kehotteen koko seuraa mallin
# kontekstia (Tonyn paatos A1106, aivo/kontekstiraja.py): muisti ja historia tayttavat kontekstin, josta on varattu
# vastaus (MAX_TOKENIA) ja 10 % marginaali. Viestimaara HISTORIA_YLARAJA on vain ylaraja; varsinainen raja on
# historian merkkimaara (kontekstiraja.historiaraja). Uusin Tonyn viesti sailyy aina kokonaan, vanhemmat lyhennetaan
# (yksityinen.lyhenna_historia).
# HISTORIA_MERKIT_YLARAJA (80 000) on kiintea raja tyokalutilalle (chat.HISTORIA_MERKIT_YLARAJA) ja mallivertailulle;
# yksityisen tilan OpenRouter-kutsut kayttavat mallikohtaista rajaa.
HISTORIA_YLARAJA = 200
HISTORIA_MERKIT_YLARAJA = 80_000
# Yhdistelman roolisyote (luonnos, tai rinnakkaisen kaksi vastausta, yhdistelma.VASTAUS_MAX_MERKKIA kukin) lisataan
# perusviestien peraan, joten sille varataan tila kehotteesta. Roolin ohjeet ovat alle 500 merkkia.
YHDISTELMA_LISAVARAUS = 2 * yhdistelma.VASTAUS_MAX_MERKKIA + 1_000
# Kehotteen arvioitu ylin hinta enintaan kulukatkaisimen kiintea varaus (luetaan, ei muuteta).
VARAUS_USD_ARVIO = float(openrouter_kulut.VARAUS_USD)
_VARAUS_USD = VARAUS_USD_ARVIO

TIIVISTYS_TEHTAVA = "aivo-yksityinen-tiivistys"
# Tiivistys palauttaa JSON:n (enintaan tiivistelma.MAX_KOHDAT kohtaa, tulkinta enintaan 300 merkkia). 700 tokenia
# (paikallisen mallin raja) katkaisee pitkan vastauksen kesken; 1 500 riittaa ja maksaa avoimella mallilla senttien osia.
TIIVISTYS_MAX_TOKENIA = 1_500

TAUSTA_TEHTAVA = "aivo-yksityinen-tausta"

TARKISTUS_TEHTAVA = "aivo-yksityinen-tarkistus"
# Taustaajossa yksi kutsu saa kestaa enintaan 10 min (ajattelija voi miettia minuutteja). Keskustelu ei odota sita.
TAUSTA_AIKARAJA_S = 600

AVOIMET_MALLIT = openrouter_kulut.AVOIMET_MALLIT      # lista on saantomoduulissa (A984); uudelleenvienti
_VANHA_LAUSE = ("sinua ajetaan Tonyn omalla\nkoneella, eik\u00e4 t\u00e4m\u00e4 keskustelu l\u00e4hde millek\u00e4\u00e4n ulkoiselle palvelulle.")
_UUSI_LAUSE = ("sinua ajetaan avoimella mallilla\nOpenRouterin kautta nollas\u00e4ilytyksell\u00e4 (ZDR). Koko t\u00e4m\u00e4 kehote (ydinohjeet, muisti, agenttidata\n"
               "ja keskustelu) l\u00e4htee jokaisella viestill\u00e4 OpenRouterille. ZDR-tilassa sit\u00e4 ei tallenneta eik\u00e4 k\u00e4ytet\u00e4\n"
               "koulutukseen. Muisti ja keskustelut tallennetaan Tonyn omalle palvelimelle.")
KEHOTE = YKSITYINEN_KEHOTE.replace(_VANHA_LAUSE, _UUSI_LAUSE)
_AVAIN_RE = re.compile(r"^[\x21-\x7e]{16,300}$")


avoin_malli = openrouter_kulut.avoin_malli


class VastausKatkesi(YksityinenVirhe):
    """Vastaus katkesi pituusrajaan ennen yhtaan vastaustekstia (finish_reason "length", tyhja content)."""


class Aikakatkaisu(YksityinenVirhe):
    """Mallipalvelu ei vastannut kuljettimen aikarajassa (TimeoutError, myos URLError(reason=TimeoutError) yhteyden
    avauksessa). Aliluokka, jotta mallivertailu erottaa aikakatkaisun muista virheista; muut kutsujat nakevat sen
    YksityinenVirheena kuten ennen (sama viesti)."""


def vastauksen_teksti(data: Any) -> str:
    """Vastauksen teksti (strip). Tyhja content + finish_reason "length" -> VastausKatkesi; muu tyhja tai puuttuva
    -> YksityinenVirhe. Viesteissa ei ole vastauksen sisaltoa."""
    try:
        teksti = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        teksti = None
        if not katkesi_pituusrajaan(data):
            raise YksityinenVirhe("OpenRouterin vastauksessa ei ollut tekstia") from None
    if teksti is None or (isinstance(teksti, str) and not teksti.strip()):
        if katkesi_pituusrajaan(data):
            raise VastausKatkesi(KATKESI_TYHJANA)
    if not isinstance(teksti, str) or not teksti.strip():
        raise YksityinenVirhe("OpenRouter antoi tyhjan vastauksen")
    return teksti.strip()


def tarkista_malli(malli: Any) -> str:
    if not avoin_malli(malli):
        raise YksityinenVirhe("OpenRouter-malli puuttuu tai ei ole sallittu avoin malli (AVOIMET_MALLIT)")
    return malli


MALLIT_YLARAJA = 10


def tarkista_mallit(mallit: Any) -> tuple[str, ...]:
    """Mallilista asetuksesta: pilkuin erotettu merkkijono tai lista. Jokaisen pitaa lapaista avoin_malli();
    muuten YksityinenVirhe (palvelu ei kaynnisty). Ensimmainen on oletus. Tyhja kohta, kaksoiskappale ja
    liian pitka lista hylataan. Yksi malli (vanha AIVO_OPENROUTER_MALLI) on yhden mallin lista."""
    if isinstance(mallit, str):
        osat = [m.strip() for m in mallit.split(",")]
    elif isinstance(mallit, (list, tuple)):
        osat = [m.strip() if isinstance(m, str) else m for m in mallit]
    else:
        osat = []
    if not osat or osat == [""]:
        raise YksityinenVirhe("OpenRouter-malli puuttuu tai ei ole sallittu avoin malli (AVOIMET_MALLIT)")
    if len(osat) > MALLIT_YLARAJA:
        raise YksityinenVirhe("OpenRouter-malleja on liikaa (enintaan 10, MALLIT_YLARAJA)")
    for m in osat:
        tarkista_malli(m)
    if len(set(osat)) != len(osat):
        raise YksityinenVirhe("OpenRouter-mallilistassa on sama malli kahdesti")
    return tuple(osat)


def lue_avain(polku: Any) -> str:
    """Lukee avaimen tiedostosta. Virheviestissa ei ole avainta eika sen osia."""
    p = Path(str(polku or ""))
    try:
        st = os.lstat(p)
    except OSError:
        raise YksityinenVirhe("OpenRouter-avain puuttuu: avaintiedostoa ei ole tai sita ei voi lukea") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise YksityinenVirhe("OpenRouter-avaintiedoston pitaa olla tavallinen tiedosto, ei linkki")
    if st.st_uid != os.geteuid():
        raise YksityinenVirhe("OpenRouter-avaintiedosto ei kuulu palvelun kayttajalle")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise YksityinenVirhe("OpenRouter-avaintiedoston oikeudet ovat liian laajat (pitaa olla 0600)")
    try:
        avain = p.read_bytes()[:1000].decode("ascii").strip()
    except (OSError, ValueError):
        raise YksityinenVirhe("OpenRouter-avaintiedostoa ei voi lukea") from None
    if not avain:
        raise YksityinenVirhe("OpenRouter-avain puuttuu: avaintiedosto on tyhja")
    if not _AVAIN_RE.fullmatch(avain):
        raise YksityinenVirhe("OpenRouter-avaintiedoston sisalto ei ole avaimen nakoinen")
    return avain


def _zdr_kunnossa(runko: Any) -> bool:
    prov = runko.get("provider") if isinstance(runko, Mapping) else None
    return isinstance(prov, Mapping) and prov.get("zdr") is True and prov.get("data_collection") == "deny"


def tee_kuljetin(avain: str, avaa: Callable[..., Any] | None = None,
                 aikaraja_s: float | None = None,
                 ylaraja_s: float = VASTAUS_AIKARAJA_S) -> Callable[[dict[str, Any]], Mapping[str, Any]]:
    """Kuljetin `openrouter_kulut.kutsu`lle: lahettaa rungon OpenRouteriin. Kieltaytyy, ellei ZDR ole rungossa.
    `aikaraja_s` voi vain lyhentaa ylarajaa (yhdistelman kokonaisaikaraja). `ylaraja_s` on VASTAUS_AIKARAJA_S,
    paitsi taustaajossa (kysy_taustatyo, TAUSTA_AIKARAJA_S)."""
    aikaraja = ylaraja_s if aikaraja_s is None else max(1.0, min(float(aikaraja_s), ylaraja_s))
    if avaa is None:
        avaa = urllib.request.build_opener(urllib.request.ProxyHandler({})).open     # ei valityspalvelinta

    def laheta(runko: dict[str, Any]) -> Mapping[str, Any]:
        if not _zdr_kunnossa(runko):
            raise YksityinenVirhe("ZDR puuttuu pyynnosta; ei lahetetty")
        pyynto = urllib.request.Request(
            openrouter_kulut.OSOITE, data=json.dumps(runko).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + avain})
        try:
            with avaa(pyynto, timeout=aikaraja) as r:
                data = json.loads(r.read(MAX_VASTAUS_TAVUA))
        except urllib.error.HTTPError as e:
            e.close()                               # vapauttaa virhevastauksen socketin
            raise YksityinenVirhe("mallipalvelu hylkasi pyynnon (HTTP %s)" % e.code) from None
        except (OSError, ValueError) as e:
            if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                raise Aikakatkaisu("mallipalvelu ei vastannut (%s)" % type(e).__name__) from None
            raise YksityinenVirhe("mallipalvelu ei vastannut (%s)" % type(e).__name__) from None
        if not isinstance(data, Mapping):
            raise YksityinenVirhe("OpenRouter antoi odottamattoman vastauksen")
        return data
    return laheta


def _kysy_viestit(
    malli: str,
    viestit: list[dict[str, Any]],
    *,
    avain_tiedosto: str = OLETUS_AVAIN,
    kulutila: str | None = None,
    avaa: Callable[..., Any] | None = None,
    nyt: Callable[[], datetime] | None = None,
    ilmoita: Callable[[str], Any] | None = None,
    aikaraja_s: float | None = None,
    max_tokens: int | None = None,
    ylaraja_s: float = VASTAUS_AIKARAJA_S,
    huomauta_katkeamisesta: bool = False,
    tehtava: str = TEHTAVA,
    **lisa: Any,
) -> str:
    """Yksi kutsu valmiilla viestilistalla. Ainoa reitti, jota kysy_openrouterilta ja yhdistelmat kayttavat.
    `huomauta_katkeamisesta`: vain yhden mallin chat (kysy_openrouterilta). Yhdistelman osakutsujen (reititin,
    luokittelu) vastauksia jasennetaan, joten niihin ei lisata huomautusta."""
    tarkista_malli(malli)
    avain = lue_avain(avain_tiedosto)                     # ennen varausta: puuttuva avain ei jata varausta
    laheta = tee_kuljetin(avain, avaa, aikaraja_s, ylaraja_s=ylaraja_s)
    tokenit = MAX_TOKENIA if max_tokens is None else max(1, min(int(max_tokens), MAX_TOKENIA))
    tokenit = min(tokenit, kontekstiraja.vastausvaraus(malli, MAX_TOKENIA))   # pieni konteksti: vastaus ei vie kaikkea
    loki_kehote(malli, viestit, tokenit)
    try:
        data = openrouter_kulut.kutsu(
            malli, viestit, laheta, tehtava=tehtava, nyt=nyt, tila=kulutila, ilmoita=ilmoita,
            max_tokens=tokenit, temperature=0.3, stream=False, usage={"include": True},
            **{**lisa, "yksityinen_chat": True})
    except openrouter_kulut.KutsuEstetty:
        raise yhdistelma.Katkaisu("OpenRouterin p\u00e4iv\u00e4katto on t\u00e4ynn\u00e4 tai kulukirjanpito ei kelpaa; kutsua ei tehty") from None
    except openrouter_kulut.ZdrVirhe:
        raise YksityinenVirhe("ZDR-s\u00e4\u00e4nt\u00f6 est\u00e4\u00e4 pyynn\u00f6n; kutsua ei tehty") from None
    loki_toteutunut(malli, data)
    try:
        teksti = vastauksen_teksti(data)
    except VastausKatkesi:
        print("yksityinen_or: vastaus katkesi pituusrajaan ennen tekstia (max_tokens=%d)" % tokenit, file=sys.stderr)
        raise
    if huomauta_katkeamisesta and katkesi_pituusrajaan(data):
        print("yksityinen_or: vastaus katkesi pituusrajaan (max_tokens=%d)" % tokenit, file=sys.stderr)
        return teksti + "\n\n" + KATKENNUT_HUOMAUTUS
    return teksti


def loki_kehote(malli: str, viestit: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    """Kirjaa stderriin (journal) kehotteen koon ja arvioidun hinnan ennen kutsua. Ei sisaltoa: vain luvut ja malli."""
    merkit = kontekstiraja.viestien_merkit(viestit)
    tiedot = {"merkit": merkit, "tokenit_arvio": kontekstiraja.arvioi_tokenit(merkit),
              "syoteraja_tokenit": kontekstiraja.syote_tokenit(malli, MAX_TOKENIA, _VARAUS_USD),
              "konteksti": kontekstiraja.konteksti(malli), "max_tokens": int(max_tokens)}
    tiedot["usd_arvio"] = kontekstiraja.arvioi_usd(malli, tiedot["tokenit_arvio"], tiedot["max_tokens"])
    print("yksityinen_or: kehote %(merkit)d merkkia, arvio %(tokenit_arvio)d tokenia (syoteraja %(syoteraja_tokenit)d, "
          "konteksti %(konteksti)d, vastaus enintaan %(max_tokens)d), arvioitu hinta enintaan %(usd_arvio).4f USD"
          % tiedot + ", malli " + str(malli)[:100], file=sys.stderr)
    return tiedot


def loki_toteutunut(malli: str, data: Any) -> None:
    """Kirjaa OpenRouterin ilmoittamat toteutuneet prompt- ja completion-tokenit ja kulun (ei sisaltoa)."""
    u = data.get("usage") if isinstance(data, Mapping) else None
    if not isinstance(u, Mapping):
        return
    osat = []
    for avain in ("prompt_tokens", "completion_tokens"):
        if isinstance(u.get(avain), int) and not isinstance(u.get(avain), bool):
            osat.append("%s=%d" % (avain, u[avain]))
    if isinstance(u.get("cost"), (int, float)) and not isinstance(u.get("cost"), bool):
        osat.append("cost=%.4f USD" % u["cost"])
    if osat:
        print("yksityinen_or: toteutunut " + ", ".join(osat) + ", malli " + str(malli)[:100], file=sys.stderr)


def historian_merkkiraja(mallit: Any, muisti: str, ohjeet: str, historia: list[dict[str, Any]],
                         lisavaraus_merkit: int = 0) -> int:
    """Historian merkkiraja OpenRouter-kutsulle: mallin konteksti - jarjestelmaviesti (kehote, ydinohjeet, muisti)
    - viestien rakenne - yhdistelman lisavaraus. Uusin Tonyn viesti sailyy lyhenna_historia-funktiossa aina."""
    jarjestelma = len(KEHOTE) + len(ohjeet or "(ei ydinohjeita)\n") + len(muisti or "") + kontekstiraja.JARJESTELMA_LISA
    viesteja = min(len(historia), HISTORIA_YLARAJA)
    # jokaiseen viestiin voi tulla rakenne ja lyhennysmerkinta ("[... vanha viesti lyhennetty: n merkkia pois]")
    per_viesti = kontekstiraja.VIESTI_LISA + len(yksityinen.LYHENNETTY % 10 ** 7)
    return max(0, kontekstiraja.historiaraja(mallit, MAX_TOKENIA, jarjestelma, lisavaraus_merkit, _VARAUS_USD)
               - viesteja * per_viesti)


def muistin_merkkiraja(mallit: Any, ohjeet: str, historia: list[dict[str, Any]], lisavaraus_merkit: int = 0) -> int:
    """Muistiosion merkkiraja (kirjasto, agenttidata ja tiivistelmat yhteensa) OpenRouter-taustapaalla. Historialle
    jaa aina vahintaan kontekstiraja.HISTORIA_VAHIMMAISOSUUS jaljella olevasta tilasta."""
    viimeiset = historia[-HISTORIA_YLARAJA:]
    per_viesti = kontekstiraja.VIESTI_LISA + len(yksityinen.LYHENNETTY % 10 ** 7)     # sama kuin historian_merkkiraja
    tarve = sum(len(str(v.get("teksti", ""))) + per_viesti for v in viimeiset)
    # uusin Tonyn viesti ja sita uudemmat sailyvat aina kokonaan (lyhenna_historia): niille tila ensin
    tony = [i for i, v in enumerate(viimeiset) if v.get("rooli") == "tony"]
    suojattu = sum(len(str(v.get("teksti", ""))) + per_viesti for v in viimeiset[tony[-1]:]) if tony else 0
    suojattu += (tony[-1] if tony else 0) * per_viesti      # vanhemmista jaa ainakin rakenne ja lyhennysmerkinta
    kiintea = len(KEHOTE) + len(ohjeet or "(ei ydinohjeita)\n")
    return kontekstiraja.muistiraja(mallit, MAX_TOKENIA, kiintea, tarve, lisavaraus_merkit, _VARAUS_USD, suojattu)


def yhdistelman_mallit(malli: str, roolit: Mapping[str, str] | None) -> list[str]:
    return [malli] + [m for m in (roolit or {}).values() if m != malli]


def yhdistelman_lisavaraus(yhdistelma_nimi: str) -> int:
    return 0 if yhdistelma_nimi == yhdistelma.OLETUS else YHDISTELMA_LISAVARAUS


def katkesi_pituusrajaan(data: Any) -> bool:
    """True, jos OpenRouterin vastauksen ensimmainen valinta paattyi pituusrajaan (finish_reason == "length")."""
    try:
        return data["choices"][0].get("finish_reason") == "length"
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def kysy_openrouterilta(
    muisti: str,
    historia: list[dict[str, Any]],
    ohjeet: str = "",
    *,
    malli: str,
    avain_tiedosto: str = OLETUS_AVAIN,
    kulutila: str | None = None,
    avaa: Callable[..., Any] | None = None,
    nyt: Callable[[], datetime] | None = None,
    ilmoita: Callable[[str], Any] | None = None,
    **lisa: Any,
) -> str:
    """Yksityisen tilan vastaus OpenRouterin avoimelta mallilta. Nostaa aina YksityinenVirhe (turvallinen viesti)."""
    tarkista_malli(malli)
    viestit = yksityinen.muodosta_viestit(muisti, historia, ohjeet, KEHOTE, HISTORIA_YLARAJA,
                                         historian_merkkiraja(malli, muisti, ohjeet, historia))
    return _kysy_viestit(malli, viestit, avain_tiedosto=avain_tiedosto, kulutila=kulutila, avaa=avaa, nyt=nyt,
                         ilmoita=ilmoita, ylaraja_s=CHAT_AIKARAJA_S, huomauta_katkeamisesta=True, **lisa)


def kysy_yhdistelmalla(
    muisti: str,
    historia: list[dict[str, Any]],
    ohjeet: str = "",
    *,
    malli: str,
    yhdistelma_nimi: str = yhdistelma.OLETUS,
    roolit: Mapping[str, str] | None = None,
    kello: Callable[[], float] | None = None,
    ajattelija_aika_s: float = yhdistelma.AJATTELIJA_AIKA_OLETUS_S,
    **kw: Any,
) -> "yhdistelma.Tulos":
    """Usean mallin yhdistelma (yhdistelma.aja). Jokainen osakutsu kulkee _kysy_viestit-funktion kautta."""
    tarkista_malli(malli)
    for m in (roolit or {}).values():
        tarkista_malli(m)
    raja = historian_merkkiraja(yhdistelman_mallit(malli, roolit), muisti, ohjeet, historia,
                                yhdistelman_lisavaraus(yhdistelma_nimi))
    viestit = yksityinen.muodosta_viestit(muisti, historia, ohjeet, KEHOTE, HISTORIA_YLARAJA, raja)

    def kysy(m: str, v: list[dict[str, Any]], aikaraja_s: float | None = None, max_tokens: int | None = None) -> str:
        return _kysy_viestit(m, v, aikaraja_s=aikaraja_s, max_tokens=max_tokens, **kw)
    return yhdistelma.aja(yhdistelma_nimi, roolit or {}, malli, viestit, kysy, ajattelija_aika_s=ajattelija_aika_s,
                          **({"kello": kello} if kello is not None else {}))


class PaivakattoTaynna(YksityinenVirhe):
    """Yhteinen 10 EUR/vrk katto on taynna tai kirjanpito ei kelpaa: kutsua ei tehty eika kulua syntynyt."""


def tiivistyksen_malli(malli: str) -> str:
    """Tiivistelman `malli`-kentan arvo (enintaan 100 merkkia; tiivistelma.py tarkistaa)."""
    return ("zdr:" + tarkista_malli(malli))[:100]


def kysy_tiivistys(
    ohje: str,
    data: str,
    *,
    malli: str,
    avain_tiedosto: str = OLETUS_AVAIN,
    kulutila: str | None = None,
    avaa: Callable[..., Any] | None = None,
    nyt: Callable[[], datetime] | None = None,
) -> str:
    """Yksityisen alueen keskusteluosan tiivistys OpenRouterin avoimella mallilla (ZDR pakotettu).
    `ohje` on jarjestelmaviesti ja `data` keskusteluosa. Virheet: YksityinenVirhe (viestissa ei sisaltoa eika avainta);
    katon tayttyminen: PaivakattoTaynna."""
    tarkista_malli(malli)
    avain = lue_avain(avain_tiedosto)                     # ennen varausta: puuttuva avain ei jata varausta
    laheta = tee_kuljetin(avain, avaa)
    viestit = [{"role": "system", "content": ohje}, {"role": "user", "content": data}]
    try:
        vastaus = openrouter_kulut.kutsu(
            malli, viestit, laheta, tehtava=TIIVISTYS_TEHTAVA, nyt=nyt, tila=kulutila,
            max_tokens=TIIVISTYS_MAX_TOKENIA, temperature=0.2, stream=False, usage={"include": True},
            yksityinen_chat=True)
    except openrouter_kulut.KutsuEstetty:
        raise PaivakattoTaynna("OpenRouterin p\u00e4iv\u00e4katto on t\u00e4ynn\u00e4 tai kulukirjanpito ei kelpaa; kutsua ei tehty") from None
    except openrouter_kulut.ZdrVirhe:
        raise YksityinenVirhe("ZDR-s\u00e4\u00e4nt\u00f6 est\u00e4\u00e4 pyynn\u00f6n; kutsua ei tehty") from None
    return vastauksen_teksti(vastaus)


def kysy_taustatyo(
    malli: str,
    viestit: list[dict[str, Any]],
    *,
    aikaraja_s: float,
    avain_tiedosto: str = OLETUS_AVAIN,
    kulutila: str | None = None,
    avaa: Callable[..., Any] | None = None,
    nyt: Callable[[], datetime] | None = None,
) -> str:
    """Taustaajon yksi mallikutsu (ajattelija tai keskustelija) OpenRouterin avoimella mallilla, ZDR pakotettu.
    `aikaraja_s` voi vain lyhentaa TAUSTA_AIKARAJA_S:aa. Virheet: YksityinenVirhe (viestissa ei sisaltoa eika avainta);
    katon tayttyminen: PaivakattoTaynna."""
    tarkista_malli(malli)
    avain = lue_avain(avain_tiedosto)                     # ennen varausta: puuttuva avain ei jata varausta
    laheta = tee_kuljetin(avain, avaa, aikaraja_s, ylaraja_s=TAUSTA_AIKARAJA_S)
    try:
        vastaus = openrouter_kulut.kutsu(
            malli, viestit, laheta, tehtava=TAUSTA_TEHTAVA, nyt=nyt, tila=kulutila,
            max_tokens=MAX_TOKENIA, temperature=0.3, stream=False, usage={"include": True},
            yksityinen_chat=True)
    except openrouter_kulut.KutsuEstetty:
        raise PaivakattoTaynna("OpenRouterin p\u00e4iv\u00e4katto on t\u00e4ynn\u00e4 tai kulukirjanpito ei kelpaa; kutsua ei tehty") from None
    except openrouter_kulut.ZdrVirhe:
        raise YksityinenVirhe("ZDR-s\u00e4\u00e4nt\u00f6 est\u00e4\u00e4 pyynn\u00f6n; kutsua ei tehty") from None
    teksti = vastauksen_teksti(vastaus)                    # tyhja + "length" -> VastausKatkesi
    if katkesi_pituusrajaan(vastaus):
        print("yksityinen_or: taustatyon vastaus katkesi pituusrajaan (max_tokens=%d)" % MAX_TOKENIA, file=sys.stderr)
        return teksti + "\n\n" + TAUSTA_KATKENNUT_HUOMAUTUS
    return teksti

def tarkastajan_lahderaja(tarkastaja: str) -> int:
    """Tarkastajan lahteiden merkkiraja: tarkastajamallin syoteraja (kontekstiraja.syote_merkit, vastaukselle
    itsetarkistus.TARKISTUS_MAX_TOKENIA, sama kiintea varaus kuin chatissa) - tarkastajan ohje, vastaus ja rakenne."""
    syote = kontekstiraja.syote_merkit(tarkastaja, itsetarkistus.TARKISTUS_MAX_TOKENIA, _VARAUS_USD)
    kiintea = (itsetarkistus.TARKASTAJA_OHJE_MAX_MERKKIA + itsetarkistus.VASTAUS_MAX_MERKKIA + 2 * kontekstiraja.VIESTI_LISA
               + kontekstiraja.JARJESTELMA_LISA)
    return max(0, syote - kiintea)


def korjauksen_raja(vastaaja: str) -> int:
    """Korjauskehotteen (perusviestit + korjauksen lisasyote) merkkiraja vastaajamallin kontekstista."""
    return kontekstiraja.syote_merkit(vastaaja, MAX_TOKENIA, _VARAUS_USD)


def tarkista_vastaus(
    muisti: str,
    historia: list[dict[str, Any]],
    ohjeet: str,
    vastaus: str,
    *,
    vastaaja: str,
    tarkastaja: str | None = None,
    kaytetyt: int = 1,
    avain_tiedosto: str = OLETUS_AVAIN,
    kulutila: str | None = None,
    avaa: Callable[..., Any] | None = None,
    nyt: Callable[[], datetime] | None = None,
) -> "itsetarkistus.Tulos":
    """Itsetarkistus (itsetarkistus.aja) samalla kehotteella, jolla vastaus syntyi. `tarkastaja` puuttuu ->
    vastaajan malli. Molemmat mallit tarkistetaan avoin_malli()-funktiolla ennen kutsua. Kutsun virheet eivat nouse:
    ne nakyvat merkintana ja alkuperainen vastaus sailyy."""
    tarkista_malli(vastaaja)
    tarkastaja = tarkista_malli(tarkastaja or vastaaja)
    # Historiaraja vastaajan mallin mukaan (korjaus menee vastaajalle) ja korjauksen lisasyotteelle varattu tila.
    # Tarkastaja ei saa koko kehotetta vaan oman rajansa (tarkastajan_lahderaja), viitatut lahteet ensin.
    viestit = yksityinen.muodosta_viestit(muisti, historia, ohjeet, KEHOTE, HISTORIA_YLARAJA,
                                         historian_merkkiraja(vastaaja, muisti, ohjeet, historia,
                                                              itsetarkistus.KORJAUS_LISAVARAUS))

    def kysy(m: str, v: list[dict[str, Any]], max_tokens: int | None = None, aikaraja_s: float | None = None) -> str:
        ylaraja = VASTAUS_AIKARAJA_S if max_tokens is not None else CHAT_AIKARAJA_S     # korjaus: kuten chat
        return _kysy_viestit(m, v, avain_tiedosto=avain_tiedosto, kulutila=kulutila, avaa=avaa, nyt=nyt,
                             max_tokens=max_tokens, ylaraja_s=ylaraja, aikaraja_s=aikaraja_s,
                             tehtava=TARKISTUS_TEHTAVA)
    return itsetarkistus.aja(vastaus, viestit, kysy, tarkastaja=tarkastaja, vastaaja=vastaaja, kaytetyt=kaytetyt,
                             lahteet_raja=tarkastajan_lahderaja(tarkastaja), korjaus_raja=korjauksen_raja(vastaaja))
