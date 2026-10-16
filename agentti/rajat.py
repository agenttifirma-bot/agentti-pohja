"""LAKI: kovakoodatut rajat.

Nama arvot eivat tule ymparistomuuttujista eivatka komentorivilta. Agentti, prompt tai
LLM-vastaus ei voi muuttaa niita. Muutos vaatii omistajan nimenomaisen luvan ja oman
commitin. Testi (test_rajat.py) varmistaa, etta rajat ovat jarkeva kokonaisuus.
"""

KULU_PAIVA_USD = 0.05        # paivan kulukatto
KULU_KUUKAUSI_USD = 1.00     # kuukauden kulukatto (alle 31 x paivakatto, jotta se on oikeasti voimassa)
KUTSUT_PAIVA = 3             # LLM-kutsuja enintaan paivassa
KUTSU_ARVIO_USD = 0.015      # pessimistinen varaus ennen jokaista kutsua

MAX_TOKENS = 2000            # vastauksen katto per kutsu
LLM_AIKAKATKAISU = 120       # sekuntia

TELEGRAM_MAX_MERKKEJA = 3500
TELEGRAM_AIKAKATKAISU = 20
SYDAN_AIKAKATKAISU = 10

# Hinnat USD / miljoona tokenia: malli -> (syote, tuloste). Tyhja = ei tunneta,
# jolloin kirjanpitoon jaa pessimistinen varaus. Hinnaston muutos = lakimuutos.
HINNAT_USD_PER_MILJOONA = {}
