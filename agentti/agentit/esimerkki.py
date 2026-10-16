"""Esimerkkiagentti: tiivistaa palvelimen levytilan ja kuorman. Toimii ilman verkkoa (kerays).

Kopioi tama (luo.py tekee sen) ja vaihda kerays(), viestit(), SKEEMA ja render()."""
import os
import shutil

from .. import data as d

NIMI = "esimerkki"
MALLI = "deepseek-flash"

SKEEMA = {
    "type": "object",
    "required": ["yhteenveto", "huomiot"],
    "properties": {
        "yhteenveto": {"type": "string", "maxLength": 400},
        "huomiot": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 200}},
    },
}


def kerays():
    levy = shutil.disk_usage("/")
    kuorma = os.getloadavg()
    return {
        "levy_kaytetty_prosenttia": round(100 * levy.used / levy.total, 1),
        "levy_vapaana_gt": round(levy.free / 1e9, 1),
        "kuorma_1_5_15_min": [round(x, 2) for x in kuorma],
    }


def viestit(data):
    return [
        {"role": "system", "content": d.SYSTEM_SAANNOT + " Tiivista palvelimen tila: "
         "kentat yhteenveto (1-2 lausetta) ja huomiot (korkeintaan 5, tyhja lista jos ei huomattavaa). "
         'Muoto: {"tila":"ok","sisalto":{"yhteenveto":"...","huomiot":[...]}}'},
        {"role": "user", "content": d.data_lohko("\n".join("%s: %s" % (k, v) for k, v in data.items()))},
    ]


def render(sisalto):
    rivit = ["Palvelimen tila", sisalto["yhteenveto"]]
    rivit += ["- " + h for h in sisalto["huomiot"]]
    return "\n".join(rivit)


def render_kuiva(data):
    return "Palvelimen tila (raakadata)\n" + "\n".join("%s: %s" % (k, v) for k, v in data.items())
