"""HTTPS-haku stdlibilla. Vain https, kokoraja, aikaraja. Virheesta kerrotaan vain tyyppi ja HTTP-tila."""
import urllib.error
import urllib.request

MAX_TAVUA = 40 * 1024 * 1024
AIKARAJA = 90
AGENTTI = "agentti-pohja-uhkatieto/1 (julkinen tutkimuskeraaja; ei kaupallinen)"


class HakuVirhe(Exception):
    """Viesti on turvallinen tulostaa: sisaltaa vain tyypin ja tilakoodin."""


def hae(url):
    if not url.startswith("https://"):
        raise HakuVirhe("vain https sallittu")
    pyynto = urllib.request.Request(url, headers={"User-Agent": AGENTTI, "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(pyynto, timeout=AIKARAJA) as vastaus:
            if not vastaus.geturl().startswith("https://"):
                raise HakuVirhe("uudelleenohjaus ei-https")
            data = vastaus.read(MAX_TAVUA + 1)
    except urllib.error.HTTPError as e:
        raise HakuVirhe("HTTPError %s" % e.code) from None
    except HakuVirhe:
        raise
    except Exception as e:  # verkko-, aikaraja- ja SSL-virheet: vain tyypin nimi
        raise HakuVirhe(type(e).__name__) from None
    if len(data) > MAX_TAVUA:
        raise HakuVirhe("vastaus liian suuri")
    return data
