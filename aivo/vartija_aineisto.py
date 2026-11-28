"""Synteettinen testiaineisto vuotovartijalle (aivo/vartija.py). Ei verkkoa, ei oikeita tietoja, toistettava siemenluvulla.

Aineisto: 50 turvallista tekstia (ohjelmointi, teknologia), 50 tekstia keksityin arkaluonteisin elementein, 10 vaikeaa
tapausta (kiertoilmaukset, valilyonneilla pilkotut numerot, aakkoset) ja 20 estotyyppien tekstia (yksityiset IP-osoitteet
myos lyhennettyina, tailnet-nimet, uudet avainmuodot, ulkomaiset IBANit). Estotyyppien tekstit arvotaan omalla
siemenellaan (siemen + ESTO_SIEMEN_LISA), joten 110 ensimmaista tekstia pysyvat ennallaan. Jokainen teksti on 200-500 sanaa, ja jokaisella on
totuustieto: mitka tyypit ja missa kohdassa (alku, loppu merkkeina).

Keksityt tiedot ovat varattuja tai mahdottomia:
  * sahkopostit vain verkkotunnuksissa example.com, example.org ja test.org;
  * IP-osoitteet vain dokumentaatioalueilta 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 ja 2001:db8::/32;
  * henkilotunnukset 1800-luvun syntymaajoilla (valimerkki +);
  * IBAN-muotoiset numerot ja avaimet arvotaan satunnaisesti (ei kenenkaan oikeita);
  * henkilot ja paikat vain paikkamerkkeina [ETUNIMI], [SUKUNIMI], [KAUPUNKI];
  * yksityiset IP-osoitteet (tyyppi yksityinen-ip) arvotaan satunnaisesti yksityisilta alueilta, ja ne kootaan
    oktettilukuina (test_repo hylkaa sisaverkon osoitteet kirjaimellisina). Tunnetut kotiverkon aliverkot jaavat pois;
  * tailnet-nimet vain muodossa <kone>.example-tailnet + .ts.net (kootaan paloista, test_repo).
Avainten etuliitteet kootaan paloista, jotta repossa ei ole avaimen nakoista merkkijonoa (test_repo).

Kaytto: python3 -m aivo.vartija_aineisto --ulos HAKEMISTO [--siemen N]
  -> HAKEMISTO/<tunnus>.txt, <tunnus>.totuus.json ja luettelo.json"""
import argparse
import json
import os
import random
import string
import sys

SIEMEN = 413
TURVALLISIA = 50
ARKALUONTEISIA = 50
ESTOTEKSTEJA = 30
ESTO_SIEMEN_LISA = 1
SANAT_MIN, SANAT_MAX = 200, 500

TURVALLINEN = "turvallinen"
ARKALUONTEINEN = "arkaluonteinen"
VAIKEA = "vaikea"

# Totuuden tyypit. Ryhma kertoo, mika vartijan syy vastaa tyyppia (aivo/vartija_mittaus.py).
TYYPIT = ("sahkoposti", "ip", "yksityinen-ip", "tailnet", "hetu", "iban", "ssh-yksityisavain", "yksityisavain",
          "ssh-julkisavain", "api-avain", "avainsana-arvo", "nimi", "paikka")

DOMAINIT = ("example.com", "example.org", "test.org")
IP4_ALUEET = ("192.0.2.", "198.51.100.", "203.0.113.")
HETU_TARKISTE = "0123456789ABCDEFHJKLMNPRSTUVWXY"
B64 = string.ascii_letters + string.digits + "+/"
ALNUM = string.ascii_letters + string.digits
SAHKOPOSTI_NIMET = ("matti.meikalainen", "anna.esimerkki", "kayttaja42", "pekka.testinen", "tiimi", "info",
                    "liisa.koe", "palaute")

# Tavallinen tekninen teksti. Osa lauseista on tarkoituksella vartijan rajoilla (versiot, aikaleimat, tiivisteet,
# silmukkaosoite, MAC-osoite, sanat key ja token), jotta vaarat halytykset nakyvat mittauksessa.
TAYTE = (
    "Testit ajetaan jokaisessa pull requestissa nelj\u00e4ll\u00e4 Python-versiolla.",
    "Funktio palauttaa listan sanakirjoja, ja jokaisessa on alku, loppu ja syy.",
    "S\u00e4\u00e4nn\u00f6llinen lauseke k\u00e4\u00e4nnet\u00e4\u00e4n kerran moduulin latauksen yhteydess\u00e4.",
    "V\u00e4limuisti nopeuttaa toistuvia hakuja, mutta se tyhjennet\u00e4\u00e4n aina uuden version j\u00e4lkeen.",
    "Lokiin kirjoitetaan vain poikkeuksen tyyppi, ei koko viesti\u00e4.",
    "Rajapinta noudattaa OpenAI-yhteensopivaa muotoa, joten asiakkaaksi k\u00e4y mik\u00e4 tahansa tavallinen kirjasto.",
    "Systemd-palvelussa on kovennukset, kuten ProtectSystem ja NoNewPrivileges.",
    "Konttien v\u00e4linen liikenne rajataan palomuurilla, ja sovellus tarkistaa oikeudet lis\u00e4ksi itse.",
    "Kehitt\u00e4j\u00e4 kirjoittaa ensin kaatuvan testin ja korjaa koodin vasta sen j\u00e4lkeen.",
    "Refaktoroinnin j\u00e4lkeen moduulin rivim\u00e4\u00e4r\u00e4 puolittui eik\u00e4 yksik\u00e4\u00e4n testi rikkoutunut.",
    "Tiedosto kirjoitetaan ensin v\u00e4liaikaiseen polkuun ja siirret\u00e4\u00e4n sitten atomisesti paikalleen.",
    "Jono k\u00e4sittelee teht\u00e4v\u00e4t yksi kerrallaan, jotta kaksi ajoa ei muokkaa samaa haaraa.",
    "Dokumentaatio kertoo, miten palvelu asennetaan ja miten sen tila tarkistetaan.",
    "Kirjasto ei tarvitse ulkoisia riippuvuuksia, koska kaikki tehd\u00e4\u00e4n standardikirjastolla.",
    "Virheenk\u00e4sittely erottaa verkkovirheet, aikakatkaisut ja kelvottomat vastaukset toisistaan.",
    "Koodikatselmoinnissa huomattiin, ett\u00e4 silmukka luki saman tiedoston kahdesti.",
    "Tietokantakysely rajataan indeksill\u00e4, joten haku pysyy nopeana my\u00f6s suurella aineistolla.",
    "Komentorivity\u00f6kalu tulostaa taulukon, jonka voi liitt\u00e4\u00e4 suoraan raporttiin.",
    "Merkkijonon pituus tarkistetaan ennen tallennusta, ja liian pitk\u00e4 sy\u00f6te hyl\u00e4t\u00e4\u00e4n.",
    "Rinnakkaiset pyynn\u00f6t suojataan lukolla, ja toinen pyynt\u00f6 saa vastauksen 429.",
    "Mittari laskee keskim\u00e4\u00e4r\u00e4isen l\u00e4pimenoajan ja mediaanin erikseen.",
    "Asetustiedosto luetaan k\u00e4ynnistyksess\u00e4, ja puuttuva arvo korvataan oletuksella.",
    "Generaattori tuottaa saman aineiston aina, kun siemenluku on sama.",
    "Haaran k\u00e4rki tarkistetaan ennen pushia, jotta kenenk\u00e4\u00e4n muun ty\u00f6 ei katoa.",
    "K\u00e4ytt\u00f6liittym\u00e4 n\u00e4ytt\u00e4\u00e4 merkinn\u00e4t korostettuina, mutta ei muuta teksti\u00e4.",
    "Ajastin k\u00e4ynnist\u00e4\u00e4 viikkoajon maanantaina, ja tulos tallentuu omaan hakemistoonsa.",
    "Palvelu kuuntelee osoitteessa 127.0.0.1:8800, joten se ei n\u00e4y verkkoon.",
    "Testiss\u00e4 palvelin sidotaan osoitteeseen 0.0.0.0 vain hiekkalaatikossa.",
    "Versio 2.0.9 julkaistiin 20.11.2026 klo 12:30:45, ja muutokset ovat muutoslokissa.",
    "Commit a37009d6 korjasi virheen, jossa tyhj\u00e4 sy\u00f6te kaatoi j\u00e4sentimen.",
    "Ajon tunniste on 123e4567-e89b-12d3-a456-426614174000, ja se n\u00e4kyy lokissa.",
    "Token bucket -algoritmi rajoittaa kutsut 300 kutsuun p\u00e4iv\u00e4ss\u00e4.",
    "Redis on avain-arvo-varasto eli key-value store, joka pit\u00e4\u00e4 tiedot muistissa.",
    "Uusi avainpari luodaan komennolla ssh-keygen -t ed25519.",
    "Aikaleima 1700000000 on Unix-aikaa sekunteina.",
    "Kutsu palauttaa HTTP 404, jos polkua ei ole, ja 429, jos raja on t\u00e4ynn\u00e4.",
    "Ymp\u00e4rist\u00f6muuttuja OPENROUTER_API_KEY luetaan tiedostosta, eik\u00e4 sen arvoa tulosteta.",
    "CI-matriisi kattaa Python-versiot 3.10, 3.11, 3.12 ja 3.13.",
    "Verkkokortin MAC-osoite 00:1A:2B:3C:4D:5E n\u00e4kyy komennon ip link tulosteessa.",
    "V\u00e4limuistin key on build-2026-11-25-linux-py312, ja se vaihtuu joka p\u00e4iv\u00e4.",
    "Testisarjassa on 3780 testi\u00e4, ja ne menev\u00e4t l\u00e4pi 6,03 sekunnissa.",
    "Docker-kuvan tiiviste sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 kiinnitet\u00e4\u00e4n.",
    "JSON Web Tokenin rakenne on otsake, sis\u00e4lt\u00f6 ja allekirjoitus pisteill\u00e4 erotettuina.",
    "Paketti scikit-learn eli sk-learn asennetaan vain kehitysymp\u00e4rist\u00f6\u00f6n.",
    "Tunnusta GITHUB_TOKEN k\u00e4ytet\u00e4\u00e4n vain luku -oikeuksin.",
    "Portit 8700 ja 8701 on rajattu eri konteille.",
)


def _arvo(rng, merkit, n):
    return "".join(rng.choice(merkit) for _ in range(n))


def _k(*osat):
    return "".join(osat)


# --- Keksityt elementit -----------------------------------------------------------------------------

def sahkoposti(rng):
    return "%s@%s" % (rng.choice(SAHKOPOSTI_NIMET), rng.choice(DOMAINIT))


def ip4(rng):
    return rng.choice(IP4_ALUEET) + str(rng.randint(1, 254))


def ip6_taysi(rng):
    return "2001:db8:" + ":".join("%x" % rng.randint(0, 0xffff) for _ in range(6))


def ip6_lyhyt(rng):
    return "2001:db8:%x::%x" % (rng.randint(1, 0xffff), rng.randint(1, 0xffff))


def yksityinen_ip4(rng):
    """Keksitty osoite RFC 1918- tai CGNAT-alueelta. 192.168.0-1.x ja Tailscalen 100.87.x jaavat pois."""
    laji = rng.randrange(4)
    if laji == 0:
        o = (10, rng.randint(0, 255), rng.randint(0, 255), rng.randint(1, 254))
    elif laji == 1:
        o = (172, rng.randint(16, 31), rng.randint(0, 255), rng.randint(1, 254))
    elif laji == 2:
        o = (192, 168, rng.randint(2, 254), rng.randint(1, 254))
    else:
        o = (100, rng.choice([n for n in range(64, 128) if n != 87]), rng.randint(0, 255), rng.randint(1, 254))
    return "%d.%d.%d.%d" % o


def yksityinen_ip(rng):
    """(osoite, muoto): IPv4, nollilla taytetty IPv4, ULA, Tailscalen IPv6, link-local tai IPv4-upotettu IPv6."""
    laji = rng.randrange(6)
    if laji == 0:
        return yksityinen_ip4(rng), "ipv4"
    if laji == 1:
        return ".".join("%03d" % int(o) for o in yksityinen_ip4(rng).split(".")), "ipv4-nollat"
    if laji == 2:
        return "fd%02x:%x:%x::%x" % (rng.randint(0, 255), rng.randint(1, 0xffff), rng.randint(1, 0xffff),
                                     rng.randint(1, 0xffff)), "ipv6-lyhyt"
    if laji == 3:
        return "fd7a:115c:a1e0::%x:%x" % (rng.randint(1, 0xffff), rng.randint(1, 0xffff)), "ipv6-tailnet"
    if laji == 4:
        return "fe80::%x:%x:%x:%x" % tuple(rng.randint(1, 0xffff) for _ in range(4)), "ipv6-link-local"
    return "::ffff:" + yksityinen_ip4(rng), "ipv6-upotettu"


def tailnet_nimi(rng):
    return _k(rng.choice(("kone", "palvelin", "nas", "rpi", "kannettava")), str(rng.randint(1, 99)),
              ".example-tailnet", ".ts", ".net")


def hetu(rng):
    """1800-luvulla syntyneen keksitty henkilotunnus (valimerkki +), tarkiste laskettu oikein."""
    pv, kk, vv = rng.randint(1, 28), rng.randint(1, 12), rng.randint(0, 99)
    yksilo = rng.randint(2, 899)
    alku = "%02d%02d%02d" % (pv, kk, vv)
    return "%s+%03d%s" % (alku, yksilo, HETU_TARKISTE[int(alku + "%03d" % yksilo) % 31])


def _iban_tarkiste(maa, bban):
    luku = "".join(str(int(c, 36)) for c in bban + maa + "00")
    return "%02d" % (98 - int(luku) % 97)


def iban_fi(rng, valit=True):
    bban = _arvo(rng, string.digits, 14)
    s = "FI" + _iban_tarkiste("FI", bban) + bban
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4)) if valit else s


def iban_ulkomaa(rng):
    maa, n = rng.choice((("DE", 18), ("SE", 20)))
    bban = _arvo(rng, string.digits, n)
    s = maa + _iban_tarkiste(maa, bban) + bban
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def iban_maa(rng, maa, pituus):
    bban = _arvo(rng, string.digits, pituus - 4)
    return maa + _iban_tarkiste(maa, bban) + bban


def yksityisavain(rng):
    laji = rng.choice(("PGP ", "", "ENCRYPTED "))
    loppu = " BLOCK" if laji == "PGP " else ""
    rivit = [_arvo(rng, B64, 64) for _ in range(3)]
    return "\n".join([_k("-----BEGIN ", laji, "PRIVATE", " KEY", loppu, "-----")] + rivit
                     + [_k("-----END ", laji, "PRIVATE", " KEY", loppu, "-----")])


UUSIA_AVAINMUOTOJA = 7


def uusi_api_avain(rng, laji=None):
    """(avain, muoto) uusista muodoista. Etuliitteet kootaan paloista (test_repo)."""
    laji = rng.randrange(UUSIA_AVAINMUOTOJA) if laji is None else laji
    if laji == 0:
        return _k("ts", "key-auth-") + _arvo(rng, ALNUM, 12) + "-" + _arvo(rng, ALNUM, 28), "tskey"
    if laji == 1:
        return _k("AI", "za") + _arvo(rng, ALNUM + "_-", 35), "google"
    if laji == 2:
        return _k(rng.choice(("s", "r")), "k_live_") + _arvo(rng, ALNUM, 24), "stripe"
    if laji == 3:
        return _k("gl", "pat-") + _arvo(rng, ALNUM, 20), "gitlab"
    if laji == 4:
        return _k("h", "f_") + _arvo(rng, ALNUM, 34), "huggingface"
    if laji == 5:
        b64u = ALNUM + "_-"
        return (_k("ey", "J") + _arvo(rng, b64u, 33) + "." + _k("ey", "J") + _arvo(rng, b64u, 60) + "."
                + _arvo(rng, b64u, 43)), "jwt"
    return _k("gh", "p_") + _arvo(rng, ALNUM, 36), "etuliite"


def ssh_yksityisavain(rng):
    laji = rng.choice(("OPENSSH ", "RSA "))
    rivit = [_arvo(rng, B64, 70) for _ in range(3)]
    return "\n".join([_k("-----BEGIN ", laji, "PRIVATE", " KEY-----")] + rivit
                     + [_k("-----END ", laji, "PRIVATE", " KEY-----")])


def ssh_julkisavain(rng):
    if rng.random() < 0.5:
        return "ssh-ed25519 " + _k("AAAA", "C3NzaC1lZDI1NTE5AAAAI") + _arvo(rng, B64, 43)
    return "ssh-rsa " + _k("AAAA", "B3NzaC1yc2EAAAADAQABAAABgQ") + _arvo(rng, B64, 120)


def api_avain(rng):
    laji = rng.randrange(6)
    if laji == 0:
        return _k("sk", "-or-v1-") + _arvo(rng, "0123456789abcdef", 64)
    if laji == 1:
        return _k("sk", "-proj-") + _arvo(rng, ALNUM, 40)
    if laji == 2:
        return _k("gh", "p_") + _arvo(rng, ALNUM, 36)
    if laji == 3:
        return _k("github", "_pat_") + _arvo(rng, ALNUM, 22) + "_" + _arvo(rng, ALNUM, 59)
    if laji == 4:
        return _k("xo", "xb-") + _arvo(rng, string.digits, 12) + "-" + _arvo(rng, ALNUM, 24)
    return _k("AK", "IA") + _arvo(rng, string.ascii_uppercase + string.digits, 16)


def avainsana_etu(rng):
    return rng.choice(("API_KEY=", "token: ", "secret on ", "salasana: ", "client_secret = "))


# --- Lauseet: palat (teksti, tyyppi tai None, muoto) ------------------------------------------------

def _p(teksti):
    return (teksti, None, None)


def arkaluonteinen_lause(rng):
    """Yksi lause, jossa on 1-3 keksittya arkaluonteista elementtia."""
    laji = rng.randrange(12)
    if laji == 0:
        return [_p("Yhteyshenkil\u00f6 on "), ("[ETUNIMI]", "nimi", "paikkamerkki"), _p(" "),
                ("[SUKUNIMI]", "nimi", "paikkamerkki"), _p(", ja h\u00e4nen osoitteensa on "),
                (sahkoposti(rng), "sahkoposti", "tavallinen"), _p(".")]
    if laji == 1:
        return [_p("L\u00e4het\u00e4 raportti osoitteeseen "), (sahkoposti(rng), "sahkoposti", "tavallinen"), _p(".")]
    if laji == 2:
        return [_p("Kotikone on osoitteessa "), (ip4(rng), "ip", "ipv4"), _p(", ja varakone on "),
                (ip4(rng), "ip", "ipv4"), _p(".")]
    if laji == 3:
        if rng.random() < 0.5:
            return [_p("IPv6-osoite on "), (ip6_taysi(rng), "ip", "ipv6"), _p(".")]
        return [_p("Palvelin vastaa IPv6-osoitteessa "), (ip6_lyhyt(rng), "ip", "ipv6-lyhyt"), _p(".")]
    if laji == 4:
        return [("[ETUNIMI]", "nimi", "paikkamerkki"), _p(" asuu kaupungissa "),
                ("[KAUPUNKI]", "paikka", "paikkamerkki"), _p(", ja h\u00e4nen henkil\u00f6tunnuksensa on "),
                (hetu(rng), "hetu", "1800-luku"), _p(".")]
    if laji == 5:
        if rng.random() < 0.75:
            return [_p("Laskun tilinumero on "), (iban_fi(rng, rng.random() < 0.7), "iban", "fi"), _p(".")]
        return [_p("Ulkomainen tili on "), (iban_ulkomaa(rng), "iban", "ulkomaa"), _p(".")]
    if laji == 6:
        return [_p("Vahingossa liitetty yksityisavain:\n"), (ssh_yksityisavain(rng), "ssh-yksityisavain", "otsikko"),
                _p("\n")]
    if laji == 7:
        return [_p("Lis\u00e4\u00e4 authorized_keys-tiedostoon rivi "), (ssh_julkisavain(rng), "ssh-julkisavain", "tavallinen"),
                _p(" ja k\u00e4ynnist\u00e4 palvelu uudelleen.")]
    if laji in (8, 9):
        return [_p("Asetuksissa oli avain "), (api_avain(rng), "api-avain", "etuliite"), _p(", joka pit\u00e4\u00e4 vaihtaa.")]
    if laji == 10:
        return [_p("Konfiguraatiossa luki " + avainsana_etu(rng)), (_arvo(rng, ALNUM, 32), "avainsana-arvo", "satunnainen"),
                _p(" ennen korjausta.")]
    return [("[ETUNIMI]", "nimi", "paikkamerkki"), _p(" muutti kaupunkiin "), ("[KAUPUNKI]", "paikka", "paikkamerkki"),
            _p(" ja vaihtoi tiliksi "), (iban_fi(rng), "iban", "fi"), _p(".")]


def vaikeat(rng):
    """Kymmenen vaikeaa tapausta: kukin on yksi lause yhdella elementilla (muoto kertoo, miksi vaikea)."""
    nimi = rng.choice(SAHKOPOSTI_NIMET)
    h = hetu(rng)
    i = iban_fi(rng, valit=False)
    ip = ip4(rng)
    avain = _k("gh", "p_") + _arvo(rng, ALNUM, 36)
    return [
        [_p("S\u00e4hk\u00f6posti on nimi "), ("miukumauku at example piste com", "sahkoposti", "kiertoilmaus"),
         _p(", kirjoita se itse oikein.")],
        [_p("Ota yhteytt\u00e4: "), (nimi + "(at)example.org", "sahkoposti", "kiertoilmaus"), _p(" tai soita.")],
        [_p("Osoite kirjaimin v\u00e4leill\u00e4: "), (" ".join(nimi.split(".")[0] + "@test.org"), "sahkoposti", "pilkottu"),
         _p(".")],
        [_p("Henkil\u00f6tunnus v\u00e4leill\u00e4: "), (" ".join([h[:2], h[2:4], h[4:6], "+", h[7:10], h[10]]), "hetu", "pilkottu"),
         _p(".")],
        [_p("Tilinumero ep\u00e4tavallisin v\u00e4lein: "), (" ".join([i[:4], i[4:10], i[10:]]), "iban", "pilkottu"), _p(".")],
        [_p("Kone l\u00f6ytyy osoitteesta "), (" . ".join(ip.split(".")), "ip", "pilkottu"), _p(".")],
        [_p("IP sanoin: "), (" piste ".join(ip.split(".")), "ip", "kiertoilmaus"), _p(".")],
        [_p("P\u00e4\u00e4k\u00e4ytt\u00e4j\u00e4n osoite on "), ("\u00e4ij\u00e4l\u00e4.p\u00e4\u00e4k\u00e4ytt\u00e4j\u00e4@" + rng.choice(DOMAINIT), "sahkoposti", "aakkoset"),
         _p(".")],
        [_p("Avain jaettuna nelj\u00e4n merkin ryhmiin: "),
         (" ".join(avain[j:j + 4] for j in range(0, len(avain), 4)), "api-avain", "pilkottu"), _p(".")],
        [_p("Salasana on "), ("\u00d6lymp1a\u00c4\u00e4net" + _arvo(rng, ALNUM, 14), "avainsana-arvo", "aakkoset"),
         _p(", \u00e4l\u00e4 kerro sit\u00e4 kenellek\u00e4\u00e4n.")],
    ]


def esto_lause(rng, laji=None, avainlaji=None):
    """Yksi lause, jossa on yksi estotyyppien elementti (uudet muodot)."""
    laji = rng.randrange(7) if laji is None else laji
    if laji in (0, 1):
        ip, muoto = yksityinen_ip(rng)
        return [_p("Sis\u00e4verkon kone vastaa osoitteessa "), (ip, "yksityinen-ip", muoto), _p(".")]
    if laji == 2:
        return [_p("Yhdist\u00e4 tailnetin kautta koneeseen "), (tailnet_nimi(rng), "tailnet", "ts-net"), _p(".")]
    if laji == 3:
        avain, muoto = uusi_api_avain(rng, avainlaji)
        return [_p("Asetuksissa oli tunnus "), (avain, "api-avain", muoto), _p(", joka pit\u00e4\u00e4 vaihtaa.")]
    if laji == 4:
        return [_p("Vahingossa liitetty avain:\n"), (yksityisavain(rng), "yksityisavain", "otsikko"), _p("\n")]
    if laji == 5:
        maa, n = rng.choice((("NO", 15), ("GB", 22), ("FR", 27), ("EE", 20), ("NL", 18)))
        i = iban_maa(rng, maa, n)
        if maa == "GB" or maa == "NL":         # pankkitunnus kirjaimin
            i = i[:4] + "".join(rng.choice(string.ascii_uppercase) for _ in range(4)) + i[8:]
            i = i[:2] + "00" + i[4:]
            i = i[:2] + _iban_tarkiste(maa, i[4:]) + i[4:]
        muoto = "ulkomaa"
        if rng.random() < 0.3:
            i, muoto = i.lower(), "pienet"
        return [_p("Maksu tilille "), (i, "iban", muoto), _p(" er\u00e4p\u00e4iv\u00e4n\u00e4.")]
    h = hetu(rng)
    return [_p("Lomakkeen tunniste oli "), (h.lower(), "hetu", "pienet"), _p(".")]


# --- Tekstin kokoaminen -----------------------------------------------------------------------------

def _sanoja(palat):
    return len("".join(p[0] for p in palat).split())


def _kokoa(rng, lauseet):
    """Taytelauseet ja annetut lauseet satunnaiseen jarjestykseen; sanamaara 200-500. Palauttaa (teksti, elementit)."""
    erikois = sum(_sanoja(l) for l in lauseet)
    tavoite = rng.randint(SANAT_MIN, SANAT_MAX)
    kaikki = [list(l) for l in lauseet]
    sanoja = erikois
    while True:
        lause = rng.choice(TAYTE)
        n = len(lause.split())
        if sanoja + n > tavoite and sanoja >= SANAT_MIN:
            break
        if sanoja + n > SANAT_MAX:
            break
        kaikki.append([_p(lause)])
        sanoja += n
    rng.shuffle(kaikki)
    teksti, elementit = [], []
    paikka = 0
    for j, lause in enumerate(kaikki):
        if j:
            erotin = "\n\n" if rng.random() < 0.15 else " "
            teksti.append(erotin)
            paikka += len(erotin)
        for pala, tyyppi, muoto in lause:
            if tyyppi:
                elementit.append({"tyyppi": tyyppi, "muoto": muoto, "alku": paikka, "loppu": paikka + len(pala),
                                  "kohta": pala})
            teksti.append(pala)
            paikka += len(pala)
    return "".join(teksti) + "\n", elementit


def generoi(siemen=SIEMEN):
    """Lista {tunnus, luokka, teksti, sanoja, elementit}. Sama siemen -> sama aineisto."""
    rng = random.Random(siemen)
    ulos = []
    for n in range(TURVALLISIA):
        teksti, el = _kokoa(rng, [])
        ulos.append({"tunnus": "t%03d" % (n + 1), "luokka": TURVALLINEN, "teksti": teksti, "elementit": el})
    for n in range(ARKALUONTEISIA):
        lauseet = [arkaluonteinen_lause(rng) for _ in range(rng.randint(2, 4))]
        teksti, el = _kokoa(rng, lauseet)
        ulos.append({"tunnus": "a%03d" % (n + 1), "luokka": ARKALUONTEINEN, "teksti": teksti, "elementit": el})
    for n, lause in enumerate(vaikeat(rng)):
        teksti, el = _kokoa(rng, [lause])
        ulos.append({"tunnus": "v%03d" % (n + 1), "luokka": VAIKEA, "teksti": teksti, "elementit": el})
    rng = random.Random(siemen + ESTO_SIEMEN_LISA)
    for n in range(ESTOTEKSTEJA):
        lauseet = [esto_lause(rng) for _ in range(rng.randint(2, 4))]
        if n < UUSIA_AVAINMUOTOJA:          # jokainen uusi avainmuoto vahintaan kerran
            lauseet.append(esto_lause(rng, 3, n))
        teksti, el = _kokoa(rng, lauseet)
        ulos.append({"tunnus": "e%03d" % (n + 1), "luokka": ARKALUONTEINEN, "teksti": teksti, "elementit": el})
    for t in ulos:
        t["sanoja"] = len(t["teksti"].split())
    return ulos


def kirjoita(hakemisto, aineisto, siemen=SIEMEN):
    """<tunnus>.txt (teksti) ja <tunnus>.totuus.json (tyypit ja paikat) seka luettelo.json."""
    os.makedirs(hakemisto, exist_ok=True)
    for t in aineisto:
        with open(os.path.join(hakemisto, t["tunnus"] + ".txt"), "w", encoding="utf-8", newline="") as f:
            f.write(t["teksti"])
        totuus = {k: t[k] for k in ("tunnus", "luokka", "sanoja", "elementit")}
        with open(os.path.join(hakemisto, t["tunnus"] + ".totuus.json"), "w", encoding="utf-8") as f:
            json.dump(totuus, f, ensure_ascii=False, indent=1)
    luettelo = {"siemen": siemen, "tekstit": [t["tunnus"] for t in aineisto]}
    with open(os.path.join(hakemisto, "luettelo.json"), "w", encoding="utf-8") as f:
        json.dump(luettelo, f, ensure_ascii=False, indent=1)


def lue(hakemisto):
    with open(os.path.join(hakemisto, "luettelo.json"), encoding="utf-8") as f:
        luettelo = json.load(f)
    ulos = []
    for tunnus in luettelo["tekstit"]:
        with open(os.path.join(hakemisto, tunnus + ".txt"), encoding="utf-8", newline="") as f:
            teksti = f.read()
        with open(os.path.join(hakemisto, tunnus + ".totuus.json"), encoding="utf-8") as f:
            totuus = json.load(f)
        ulos.append(dict(totuus, teksti=teksti))
    return ulos


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vuotovartijan synteettinen testiaineisto (ei verkkoa).")
    ap.add_argument("--ulos", required=True, help="hakemisto, johon tekstit ja totuustiedostot kirjoitetaan")
    ap.add_argument("--siemen", type=int, default=SIEMEN)
    a = ap.parse_args(argv)
    aineisto = generoi(a.siemen)
    kirjoita(a.ulos, aineisto, a.siemen)
    print("kirjoitettu %d tekstia hakemistoon %s (siemen %d)" % (len(aineisto), a.ulos, a.siemen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
