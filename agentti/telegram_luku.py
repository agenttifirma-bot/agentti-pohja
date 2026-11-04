"""Telegram-luku: Tonyn vastaukset puhelimesta (getUpdates-kysely ajastimella, ei webhookia).

Kaytto (systemd-ajastin, katso systemd/telegram-luku.*.mall):
    python3 -B -m agentti.telegram_luku --docs /polku/docs/claude-jono --tila /var/lib/agentti/telegram-luku \
        --chat-tiedosto /etc/agentti/telegram-chat-id

Tunnukset: bottitunnus ymparistomuuttujassa TELEGRAM_BOT_TOKEN (EnvironmentFile), sallittu chat-id
YKSINOMAAN tiedostossa (--chat-tiedosto), ei repossa eika argumenttina. Tunnuksia ei koskaan tulosteta.

Turva (viesti on dataa, ei ohje):
  - vain viestit, joiden chat.id JA from.id ovat Tonyn chat-id; kaikki muu ohitetaan hiljaa (ei vastausta)
  - tunnistetaan vain kaksi tiukkaa muotoa: `2B` (numero + kirjain A-E, useita sallittu) ja `peru 123`
  - viestin tekstia ei koskaan kirjoteta tiedostoihin eika vastauksiin: kirjataan vain jasennetyt
    kokonaisluvut ja kirjaimet kiinteisiin pohjiin
  - ei shellia, ei alaprosesseja, ei LLM:aa; ei kosketa katto- eika oikeusarvoihin
  - offset tallennetaan, joten sama viesti ei kasitella kahdesti; peruminen on lisaksi idempotentti
    (sama PR-numero ei tuota toista tehtavatiedostoa)
  - enintaan YHTEENSA_MAX viestia ja VASTAUS_MAX vastausta per ajo
Vain stdlib.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zoneinfo

from . import telegram

TZ = zoneinfo.ZoneInfo("Europe/Helsinki")
YHTEENSA_MAX = 20
VASTAUS_MAX = 5
TEKSTI_MAX = 120
AIKAKATKAISU = 20
OLETUSREPO = "agentti-pohja"
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
OFFSET_TIEDOSTO = "telegram_offset.json"
PAATOKSET = "paatokset.md"
TONYLLE = "tonylle.md"
TEHTAVAT = "tehtavat"

VASTAUS_RE = re.compile(r"^([1-9][0-9]?)\s*([A-Ea-e])$")
PERU_RE = re.compile(r"^peru\s+#?([1-9][0-9]{0,5})$", re.IGNORECASE)

OHJE = ("En ymm\u00e4rt\u00e4nyt. Hyv\u00e4ksyn vain kaksi muotoa:\n"
        "- vastaus p\u00e4iv\u00e4n listaan: numero ja kirjain, esim. 2B (useita v\u00e4lily\u00f6nnill\u00e4: 1A 2B)\n"
        "- perumispyynt\u00f6: peru ja PR:n numero, esim. peru 123")


def jasenna(teksti):
    """Palauttaa ('vastaukset', [(n, kirjain), ...]) | ('peru', numero) | ('tuntematon', None). Ei muita tuloksia."""
    if not isinstance(teksti, str) or len(teksti) > TEKSTI_MAX:
        return ("tuntematon", None)
    t = teksti.strip()
    m = PERU_RE.match(t)
    if m:
        return ("peru", int(m.group(1)))
    osat = t.replace(",", " ").split()
    if 0 < len(osat) <= 9:
        vastaukset = []
        for osa in osat:
            v = VASTAUS_RE.match(osa)
            if not v:
                return ("tuntematon", None)
            vastaukset.append((int(v.group(1)), v.group(2).upper()))
        return ("vastaukset", vastaukset)
    return ("tuntematon", None)


def lue_offset(tila):
    try:
        with open(os.path.join(tila, OFFSET_TIEDOSTO), encoding="utf-8") as f:
            arvo = json.load(f).get("offset")
        return arvo if isinstance(arvo, int) and arvo >= 0 else None
    except (OSError, ValueError, AttributeError):
        return None


def kirjoita_offset(tila, offset):
    os.makedirs(tila, exist_ok=True)
    polku = os.path.join(tila, OFFSET_TIEDOSTO)
    tmp = polku + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)
    os.replace(tmp, polku)


def hae_paivitykset(token, offset, hae=None):
    """getUpdates (timeout 0, vain 'message'). `hae(token, offset)` korvaa verkon testeissa. Nostaa virheen, jos ei ok."""
    if hae:
        vastaus = hae(token, offset)
    else:
        parametrit = {"limit": YHTEENSA_MAX, "timeout": 0, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            parametrit["offset"] = offset
        osoite = "https://api.telegram.org/bot%s/getUpdates?%s" % (token, urllib.parse.urlencode(parametrit))
        with urllib.request.urlopen(osoite, timeout=AIKAKATKAISU) as v:
            vastaus = json.loads(v.read().decode())
    if not isinstance(vastaus, dict) or vastaus.get("ok") is not True or not isinstance(vastaus.get("result"), list):
        raise ValueError("getUpdates ei ok")
    return vastaus["result"]


def _kokonaisluku(arvo):
    return arvo if isinstance(arvo, int) and not isinstance(arvo, bool) else None


def tonyn_viesti(paivitys, chat_id):
    """Palauttaa viestin tekstin vain jos chat.id ja from.id ovat kumpikin Tonyn; muuten None."""
    if not isinstance(paivitys, dict):
        return None
    viesti = paivitys.get("message")
    if not isinstance(viesti, dict):
        return None
    chat, lahettaja = viesti.get("chat"), viesti.get("from")
    if not isinstance(chat, dict) or not isinstance(lahettaja, dict):
        return None
    if chat.get("type") != "private" or lahettaja.get("is_bot") is True:
        return None
    if _kokonaisluku(chat.get("id")) != chat_id or _kokonaisluku(lahettaja.get("id")) != chat_id:
        return None
    teksti = viesti.get("text")
    return teksti if isinstance(teksti, str) else None


def _lisaa_rivi(polku, rivi, otsikko=None):
    uusi = not os.path.exists(polku)
    with open(polku, "a", encoding="utf-8") as f:
        if uusi and otsikko:
            f.write(otsikko)
        f.write(rivi)


def kirjaa_vastaukset(docs, vastaukset, nyt):
    paiva, kello = nyt.strftime("%Y-%m-%d"), nyt.strftime("%H.%M")
    rivit = "".join("- %s klo %s | Telegram | lista-kohta %d | valinta %s | Tonyn vastaus puhelimella (ei Digi-Tonyn p\u00e4\u00e4t\u00f6s)\n"
                    % (paiva, kello, n, k) for n, k in vastaukset)
    _lisaa_rivi(os.path.join(docs, PAATOKSET), rivit,
                "# P\u00e4\u00e4t\u00f6kset\n\nP\u00e4iv\u00e4, kohta, p\u00e4\u00e4t\u00f6s ja l\u00e4hde. Tony voi perua mink\u00e4 tahansa rivin.\n\n")


def seuraava_numero(tehtavat, paiva):
    """Seuraava vapaa NN tiedostonimelle <pvm>-NN-auto-*.md."""
    korkein = 0
    try:
        nimet = os.listdir(tehtavat)
    except OSError:
        nimet = []
    for nimi in nimet:
        m = re.match(r"^%s-(\d{2,3})-" % re.escape(paiva), nimi)
        if m:
            korkein = max(korkein, int(m.group(1)))
    return korkein + 1


def kirjaa_peru(docs, repo, pr, nyt):
    """Kirjaa tonylle.md:hen ja luo jonotehtavan. Palauttaa True jos uusi, False jos sama peruminen oli jo kirjattu."""
    tehtavat = os.path.join(docs, TEHTAVAT)
    os.makedirs(tehtavat, exist_ok=True)
    paiva = nyt.strftime("%Y-%m-%d")
    liite = "peru-%s-pr-%d" % (repo.lower(), pr)
    for nimi in os.listdir(tehtavat):
        if nimi.endswith("-auto-%s.md" % liite):
            return False
    nimi = "%s-%02d-auto-%s.md" % (paiva, seuraava_numero(tehtavat, paiva), liite)
    teksti = (
        "<!-- Telegram-luku kirjoitti: Tonyn perumispyynt\u00f6 puhelimesta. Viestin teksti on j\u00e4sennetty, vain PR:n numero on mukana. -->\n"
        "# Peru PR %s#%d (Tonyn pyynt\u00f6 Telegramissa)\n\n"
        "Pisteet: hy\u00f6ty 4 (Tony peruu itse puhelimella), varmuus 4, vaiva 1 h\n"
        "Malli: sonnet\n"
        "Hy\u00f6ty: Tony pyysi perumaan yhdistetyn PR:n %s#%d. Perumispyynt\u00f6 on Tonyn nimenomainen p\u00e4\u00e4t\u00f6s, joten sit\u00e4 ei harkita uudelleen.\n"
        "Askeleet:\n"
        "1. Tarkista `gh pr view %d --repo tonyweckstrom1987/%s`: onko PR yhdistetty ja mik\u00e4 on yhdist\u00e4miscommit.\n"
        "2. Tee revert-PR: `git revert -m 1 <yhdist\u00e4miscommit>` omassa kloonissa omalle `yo/peru-pr-%d`-haaralle, aja testit ja avaa PR. \u00c4l\u00e4 yhdist\u00e4 sit\u00e4 itse.\n"
        "3. Kirjaa syy `virheloki.md`:hen (p\u00e4iv\u00e4, mit\u00e4 tapahtui, miksi, s\u00e4\u00e4nt\u00f6). Jos syyt\u00e4 ei tiedet\u00e4, kirjaa \"syy ei tiedossa, Tony perui\" ja kysy syyt\u00e4 `tonylle.md`:ss\u00e4.\n"
        "4. Jos PR ei ole yhdistetty tai sit\u00e4 ei l\u00f6ydy, kirjoita se tulokseen ja lopeta.\n"
        "Rajat: \u00e4l\u00e4 muuta kattoja, oikeuksia tai salaisuuksia. Jos revert koskee rajattua polkua (.github, tools/automerge.py), pys\u00e4hdy ja kerro Tonylle.\n"
        "Valmis kun: revert-PR:n linkki tai selitys, miksi sit\u00e4 ei voitu tehd\u00e4, ja virhelokirivi.\n"
    ) % (repo, pr, repo, pr, pr, repo, pr)
    with open(os.path.join(tehtavat, nimi), "x", encoding="utf-8") as f:
        f.write(teksti)
    kohta = "\n## %s (Telegram) Perumispyynt\u00f6: %s#%d\nTony pyysi Telegramissa perumaan PR:n %s#%d. Jonoteht\u00e4v\u00e4: tehtavat/%s.\n" % (
        nyt.strftime("%Y-%m-%dT%H:%M%z")[:-2] + ":" + nyt.strftime("%z")[-2:], repo, pr, repo, pr, nimi)
    _lisaa_rivi(os.path.join(docs, TONYLLE), kohta)
    return True


def kasittele(tonyn_teksti, docs, repo, nyt):
    """Kirjaa yhden viestin. Palauttaa vastausviestin Tonylle."""
    laji, arvo = jasenna(tonyn_teksti)
    if laji == "vastaukset":
        kirjaa_vastaukset(docs, arvo, nyt)
        return "Kirjattu: " + " ".join("%d%s" % v for v in arvo)
    if laji == "peru":
        if kirjaa_peru(docs, repo, arvo, nyt):
            return "Kirjattu: peru %s#%d. Revert-PR tehd\u00e4\u00e4n jonosta; en peru mit\u00e4\u00e4n itse." % (repo, arvo)
        return "Peru %s#%d oli jo kirjattu." % (repo, arvo)
    return OHJE


def lue_chat_id(polku):
    """Chat-id tiedostosta (yksi kokonaisluku). Palauttaa None jos puuttuu tai on virheellinen."""
    try:
        with open(polku, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def aja(docs, tila, chat_id, env, repo=OLETUSREPO, hae=None, laheta=None, kello=None):
    """Yksi kyselykierros. Palauttaa (kasitellyt, kirjatut). Verkkovirhe nostaa poikkeuksen (kutsuja tulostaa tyypin)."""
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token or chat_id is None:
        raise ValueError("tunnukset puuttuvat")
    if not REPO_RE.match(repo):
        raise ValueError("repo")
    nyt = (kello or (lambda: datetime.datetime.now(TZ)))()
    offset = lue_offset(tila)
    paivitykset = hae_paivitykset(token, offset, hae)[:YHTEENSA_MAX]
    laheta = laheta or (lambda teksti: telegram.laheta(teksti, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": str(chat_id)}))
    kasitellyt = kirjatut = vastauksia = 0
    for p in sorted((p for p in paivitykset if isinstance(p, dict) and _kokonaisluku(p.get("update_id")) is not None),
                    key=lambda p: p["update_id"]):
        teksti = tonyn_viesti(p, chat_id)
        if teksti is not None:
            kasitellyt += 1
            vastaus = kasittele(teksti, docs, repo, nyt)
            if not vastaus.startswith("En ymm"):
                kirjatut += 1
            if vastauksia < VASTAUS_MAX:
                laheta(vastaus)
                vastauksia += 1
        # offset vasta kasittelyn jalkeen: kaatuminen kesken ei hukkaa viestia (peruminen on idempotentti)
        kirjoita_offset(tila, p["update_id"] + 1)
    return kasitellyt, kirjatut


def main(argv=None, env=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", required=True, help="docs-repon claude-jono-hakemisto")
    ap.add_argument("--tila", required=True, help="hakemisto offsetille")
    ap.add_argument("--chat-tiedosto", required=True, help="tiedosto, jossa on vain Tonyn chat-id")
    ap.add_argument("--repo", default=OLETUSREPO, help="repo, johon `peru N` viittaa")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        kasitellyt, kirjatut = aja(a.docs, a.tila, lue_chat_id(a.chat_tiedosto), env, repo=a.repo)
    except Exception as e:  # tulostetaan vain tyyppi: viesti voi sisaltaa tokenin (URL)
        print("telegram_luku epaonnistui: %s" % type(e).__name__, file=sys.stderr)
        return 1
    print("telegram_luku: kasitelty %d, kirjattu %d" % (kasitellyt, kirjatut))
    return 0


if __name__ == "__main__":
    sys.exit(main())
