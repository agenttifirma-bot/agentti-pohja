import datetime
import json
import zoneinfo

TZ = zoneinfo.ZoneInfo("Europe/Helsinki")


def kello(vuosi=2026, kk=10, paiva=16, tunti=8):
    return lambda: datetime.datetime(vuosi, kk, paiva, tunti, 0, tzinfo=TZ)


def llm_vastaus(sisalto, finish="stop", kaytto=None):
    return {"choices": [{"message": {"content": sisalto}, "finish_reason": finish}],
            "usage": kaytto or {"prompt_tokens": 100, "completion_tokens": 50}}


OK_JSON = json.dumps({"tila": "ok", "sisalto": {"yhteenveto": "Kaikki hyvin.", "huomiot": []}})
EI_TIETOA_JSON = json.dumps({"tila": "ei_tietoa", "syy": "Data ei riita."})

ENV = {"LLM_BASE_URL": "http://litellm.example:4000/v1", "LLM_API_KEY": "testiavain",
       "TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
