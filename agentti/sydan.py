"""Sydamenlyonti (esim. Uptime Kuma push-monitori): pingataan vain onnistuneen ajon jalkeen.
Jos ping puuttuu, monitori halyttaa. Ei nosta poikkeusta."""
import urllib.parse
import urllib.request

from . import rajat


def ping(env, hae=None):
    osoite = env.get("SYDAN_URL")
    if not osoite or urllib.parse.urlparse(osoite).scheme not in ("http", "https"):
        return False
    try:
        if hae:
            return bool(hae(osoite))
        with urllib.request.urlopen(osoite, timeout=rajat.SYDAN_AIKAKATKAISU) as v:
            return 200 <= v.status < 300
    except Exception:
        return False
