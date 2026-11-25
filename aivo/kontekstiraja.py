"""Yksityisen tilan OpenRouter-taustapaan kehoteraja mallin kontekstin mukaan (Tonyn paatos A1106).

Paikallisen loopback-mallin rajat (yksityinen.MUISTI_YLARAJA, HISTORIA_YLARAJA, HISTORIA_MERKIT_YLARAJA) eivat
muutu. OpenRouterin avoimilla malleilla muisti, agenttidata ja keskusteluhistoria saavat tayttaa kehotteen mallin
kontekstipituuteen asti, josta varataan:
  * vastaukselle `vastausvaraus` tokenia (yksityinen_or.MAX_TOKENIA = 8 000; pienella mallilla enintaan neljannes
    kontekstista, jotta kehotteelle jaa tilaa),
  * turvamarginaali MARGINAALI (10 %) kontekstista, koska merkki-token-muunnos on arvio.

Merkit tokeneiksi: MERKKIA_PER_TOKEN = 2,5. Suomen teksti on noin 3 merkkia/token, mutta koodi, JSON, luettelot ja
pitkat yhdyssanat pilkkoutuvat tiheammin. Alakanttiin arvioitu suhde tarkoittaa, etta kehote jaa mieluummin vajaaksi
kuin ylittaa kontekstin (ylitys = HTTP 400 ja koko vastaus puuttuu). Lokiin kirjataan seka arvio etta OpenRouterin
ilmoittama toteutunut prompt_tokens, joten suhteen voi tarkistaa kaytosta.

Kulu: kutsuja (yksityinen_or) antaa parametrina `varaus_usd` = kulukatkaisimen kiintea varaus
(openrouter_kulut.VARAUS_USD). Kehotteen arvioitu hinta (KONTEKSTIT-taulukon ylin ZDR-hinta) pidetaan enintaan sen
suuruisena, jotta yksi kutsu ei ylita omaa varaustaan. Tama moduuli ei tuo OpenRouter-moduuleja (rakennevartija
test_yksityinen_or) eika muuta paivakattoa, varausta tai kulukirjausta.

Taulukko KONTEKSTIT: lahde OpenRouterin julkiset rajapinnat /api/v1/models ja /api/v1/endpoints/zdr (haettu
25.11.2026). Arvo on konteksti, jota vahintaan puolet mallin ZDR-endpointeista tukee (ei pienimman endpointin raja,
mutta ei myoskaan yksittaisen suuren endpointin raja, jotta reititykselle jaa varaendpointteja), enintaan
KONTEKSTI_KATTO. Hinnat ovat ZDR-endpointtien ylimmat (USD / miljoona tokenia, sisaan ja ulos), ja niita kaytetaan
vain arvioon ja kehotteen kokorajaan, ei kulukirjaukseen. Tuntematon malli (ei taulukossa, esim. ei ZDR-endpointtia
hakuhetkella) saa varovaisen oletuksen OLETUS_KONTEKSTI ja korkean oletushinnan.

Vain stdlib, ei verkkoa eika tiedostoja."""
from __future__ import annotations

import math
from typing import Iterable

MARGINAALI = 0.10
MERKKIA_PER_TOKEN = 2.5
OLETUS_KONTEKSTI = 32_768
KONTEKSTI_KATTO = 262_144            # suurempi konteksti (1 M) olisi yhden endpointin varassa ja kallis
OLETUSHINTA_USD_MTOK = (2.0, 8.0)    # tuntematon malli: taulukon kalleinta tasoa (varovainen)
VASTAUS_OSUUS_YLARAJA = 4            # vastausvaraus enintaan 1/4 kontekstista
HISTORIA_VAHIMMAISOSUUS = 0.25       # muisti ei syrjayta keskusteluhistoriaa: historialle jaa aina vahintaan 25 %
JARJESTELMA_LISA = 200               # muodosta_viestit-otsikot (YDINOHJEET, MUISTI) ja rivinvaihdot
VIESTI_LISA = 16                     # yhden viestin rooli ja rakenne merkkeina (arvio)

# malli: (konteksti tokeneina, hinta sisaan USD/Mtok, hinta ulos USD/Mtok)
KONTEKSTIT: dict[str, tuple[int, float, float]] = {
    "deepseek/deepseek-chat": (163_840, 0.32, 0.89),
    "deepseek/deepseek-chat-v3-0324": (131_072, 1.0, 2.625),
    "deepseek/deepseek-chat-v3.1": (163_840, 0.5, 1.5),
    "deepseek/deepseek-r1-0528": (163_840, 0.5, 2.15),
    "google/gemma-2-27b-it": (8_192, 0.65, 0.65),
    "google/gemma-3-12b-it": (131_072, 0.35, 0.45),
    "google/gemma-3-27b-it": (131_072, 0.12, 0.45),
    "google/gemma-3-4b-it": (131_072, 0.075, 0.15),
    "meta-llama/llama-3.1-70b-instruct": (131_072, 0.72, 0.72),
    "meta-llama/llama-3.1-8b-instruct": (131_072, 0.22, 0.22),
    # meta-llama/llama-3.2-1b-instruct: ei ZDR-endpointtia 25.11.2026 -> OLETUS_KONTEKSTI
    "meta-llama/llama-3.2-3b-instruct": (131_072, 0.05, 0.33),
    "meta-llama/llama-3.3-70b-instruct": (131_072, 0.72, 2.253),
    "meta-llama/llama-4-maverick": (262_144, 0.35, 1.0),
    "meta-llama/llama-4-scout": (262_144, 0.15, 0.45),
    "mistralai/mistral-nemo": (131_072, 0.15, 0.15),
    "mistralai/mistral-small-24b-instruct-2501": (32_768, 0.05, 0.08),
    "mistralai/mistral-small-2603": (262_144, 0.165, 0.66),
    "mistralai/mistral-small-3.1-24b-instruct": (128_000, 0.351, 0.555),
    "mistralai/mistral-small-3.2-24b-instruct": (128_000, 0.1125, 0.3),
    "mistralai/mixtral-8x22b-instruct": (65_536, 2.2, 6.6),
    "qwen/qwen2.5-vl-72b-instruct": (128_000, 0.8, 1.0),
    "qwen/qwen3-14b": (40_960, 0.18, 0.36),
    "qwen/qwen3-235b-a22b-2507": (262_144, 0.15, 0.825),
    "qwen/qwen3-235b-a22b-thinking-2507": (128_000, 0.45, 3.5),
    "qwen/qwen3-30b-a3b": (40_960, 0.18, 0.75),
    "qwen/qwen3-30b-a3b-instruct-2507": (262_144, 0.1, 0.3),
    "qwen/qwen3-32b": (40_960, 0.14, 0.42),
    "qwen/qwen3-coder": (262_144, 0.35, 1.5),
    "qwen/qwen3-coder-30b-a3b-instruct": (262_144, 0.15, 0.6),
    "qwen/qwen3-coder-next": (262_144, 0.12, 0.8),
    "qwen/qwen3-next-80b-a3b-instruct": (262_144, 0.135, 1.65),
    "qwen/qwen3-vl-235b-a22b-instruct": (131_072, 0.21, 1.9),
    "qwen/qwen3-vl-30b-a3b-instruct": (262_144, 0.15, 0.6),
    "qwen/qwen3-vl-8b-instruct": (262_144, 0.25, 0.75),
    # qwen/qwen3.5-122b-a10b: ei ZDR-endpointtia 25.11.2026 -> OLETUS_KONTEKSTI
    "qwen/qwen3.5-27b": (262_144, 0.39, 3.9),
    "qwen/qwen3.5-35b-a3b": (262_144, 0.15, 1.0),
    "qwen/qwen3.5-397b-a17b": (262_144, 0.75, 4.5),
    "qwen/qwen3.5-9b": (262_144, 0.17, 0.25),
    "qwen/qwen3.6-27b": (262_144, 0.6, 6.0),
    "qwen/qwen3.6-35b-a3b": (262_144, 0.19, 1.7),
    "qwen/qwen3.8-2.4t-a95b": (262_144, 2.0, 6.0),
    "qwen/qwen3.8-27b": (262_144, 0.99, 3.2),
}


def _mallit(mallit: str | Iterable[str]) -> list[str]:
    lista = [mallit] if isinstance(mallit, str) else [m for m in mallit if isinstance(m, str)]
    return lista or [""]


def konteksti(malli: str) -> int:
    """Mallin konteksti tokeneina (taulukosta, enintaan KONTEKSTI_KATTO); tuntematon -> OLETUS_KONTEKSTI."""
    arvo = KONTEKSTIT.get(malli)
    return min(arvo[0], KONTEKSTI_KATTO) if arvo else OLETUS_KONTEKSTI


def hinta(malli: str) -> tuple[float, float]:
    arvo = KONTEKSTIT.get(malli)
    return (arvo[1], arvo[2]) if arvo else OLETUSHINTA_USD_MTOK


def vastausvaraus(malli: str, max_tokenia: int) -> int:
    """Vastaukselle varattavat tokenit: max_tokenia, mutta enintaan neljannes kontekstista."""
    return max(1, min(int(max_tokenia), konteksti(malli) // VASTAUS_OSUUS_YLARAJA))


def syote_tokenit(malli: str, max_tokenia: int, varaus_usd: float | None = None) -> int:
    """Kehotteen (syotteen) tokenit: konteksti - marginaali - vastausvaraus. Jos `varaus_usd` on annettu, enintaan
    niin paljon, etta kutsun arvioitu ylin hinta mahtuu siihen (kulukatkaisimen kiintea varaus)."""
    vastaus = vastausvaraus(malli, max_tokenia)
    tila = int(konteksti(malli) * (1 - MARGINAALI)) - vastaus
    h_in, h_out = hinta(malli)
    if varaus_usd is not None and h_in > 0:
        tila = min(tila, int((float(varaus_usd) - vastaus * h_out / 1e6) * 1e6 / h_in))
    return max(0, tila)


def syote_merkit(mallit: str | Iterable[str], max_tokenia: int, varaus_usd: float | None = None) -> int:
    """Kehotteen merkkiraja; usealla mallilla (yhdistelma) pienimman mukaan."""
    return min(int(syote_tokenit(m, max_tokenia, varaus_usd) * MERKKIA_PER_TOKEN) for m in _mallit(mallit))


def arvioi_tokenit(merkit: int) -> int:
    return int(math.ceil(max(0, merkit) / MERKKIA_PER_TOKEN))


def arvioi_usd(malli: str, tokenit_in: int, tokenit_out: int) -> float:
    """Kutsun arvioitu ylin hinta USD (vain lokiin ja nayttoon; kulukirjaus kayttaa OpenRouterin ilmoittamaa kulua)."""
    h_in, h_out = hinta(malli)
    return (max(0, tokenit_in) * h_in + max(0, tokenit_out) * h_out) / 1e6


def viestien_merkit(viestit: Iterable[dict]) -> int:
    """Viestilistan arvioitu koko merkkeina (sisalto + rakenne)."""
    return sum(len(str(v.get("content", ""))) + VIESTI_LISA for v in viestit)


def muistiraja(mallit: str | Iterable[str], max_tokenia: int, kiintea_merkit: int, historia_tarve: int,
               lisavaraus_merkit: int = 0, varaus_usd: float | None = None) -> int:
    """Muistiosion (kirjasto, agenttidata, tiivistelmat) merkkiraja.

    `kiintea_merkit` = jarjestelmakehote + ydinohjeet, `historia_tarve` = keskusteluhistorian merkit kokonaan,
    `lisavaraus_merkit` = yhdistelman roolisyote (luonnokset). Muisti tayttaa tilan ensin, mutta historialle jaa aina
    vahintaan HISTORIA_VAHIMMAISOSUUS jaljella olevasta tilasta (tai koko historia, jos se on pienempi)."""
    jaljella = syote_merkit(mallit, max_tokenia, varaus_usd) - max(0, kiintea_merkit) - max(0, lisavaraus_merkit) - JARJESTELMA_LISA
    if jaljella <= 0:
        return 0
    historialle = min(max(0, historia_tarve), int(jaljella * HISTORIA_VAHIMMAISOSUUS))
    return max(0, jaljella - historialle)


def historiaraja(mallit: str | Iterable[str], max_tokenia: int, jarjestelma_merkit: int,
                 lisavaraus_merkit: int = 0, varaus_usd: float | None = None) -> int:
    """Historian viestien yhteismerkkiraja, kun jarjestelmaviesti (kehote, ydinohjeet, muisti) on jo koottu."""
    return max(0, syote_merkit(mallit, max_tokenia, varaus_usd) - max(0, jarjestelma_merkit) - max(0, lisavaraus_merkit))
