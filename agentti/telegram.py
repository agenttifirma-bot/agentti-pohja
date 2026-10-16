"""Telegram-lahetys. Vastaanottaja on AINA env-muuttuja TELEGRAM_CHAT_ID, ei koskaan LLM:n
tai datan antama. Ei nosta poikkeusta eika tulosta tokenia."""
import json
import urllib.parse
import urllib.request

from . import rajat


def laheta(teksti, env, hae=None):
    """Palauttaa True/False. env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID."""
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    teksti = teksti[:rajat.TELEGRAM_MAX_MERKKEJA]
    try:
        if hae:
            return bool(hae(token, chat, teksti))
        data = urllib.parse.urlencode({"chat_id": chat, "text": teksti}).encode()
        osoite = "https://api.telegram.org/bot%s/sendMessage" % token
        with urllib.request.urlopen(osoite, data=data, timeout=rajat.TELEGRAM_AIKAKATKAISU) as v:
            return json.loads(v.read().decode()).get("ok") is True
    except Exception:
        return False
