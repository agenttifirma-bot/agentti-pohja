"""Agentit. Jokainen agentti on moduuli, jossa on:

NIMI      lyhyt tunniste (sama kuin tiedostonimi)
MALLI     LiteLLM-mallin nimi
SKEEMA    JSON-skeema 'sisalto'-kentalle (ks. agentti/skeema.py)
kerays()            -> data (mika tahansa merkkijonoksi muutettava)
viestit(data)       -> LLM-viestilista (kayta data.data_lohko ja data.SYSTEM_SAANNOT)
render(sisalto)     -> Telegram-teksti onnistuneesta tuloksesta
render_kuiva(data)  -> teksti ilman LLM:aa (kuiva-ajo ja varaviesti virhetilanteessa)
"""
