# Changelog

Muoto perustuu [Keep a Changelogiin](https://keepachangelog.com/fi/1.0.0/).

## [Julkaisematon]

### Lisätty

- Sandbox-asiakas (`agentti/sandbox_kutsu.py`): lähettää repon tai luonnoshakemiston eristettyyn sandboxiin ssh:lla pakotetun komennon kautta. Vain `https://github.com/omistaja/repo`-osoitteet, ref-tarkistus, tar ilman symlinkkejä ja raskaita hakemistoja, kokoraja, aikaraja. Ei salaisuuksia: vain avaintiedoston polku.
- Testit sandbox-asiakkaalle (`test/test_sandbox_kutsu.py`).

## [0.1.0] - 2026-10-16

### Lisätty

- Kulukirjanpito (`kulu.py`): varaus ennen kutsua, päivä- ja kuukausikatto sekä kutsuraja, flock-lukko, vikatilassa pysäytys (fail closed).
- LLM-asiakas (`llm.py`): OpenAI-yhteensopiva, ei työkaluja, `max_tokens`-katto, ei uudelleenohjausten seurantaa, virheet koodeina.
- Tulos (`tulos.py`, `skeema.py`): `ok` tai `ei_tietoa` (ei tiedä on aina sallittu), vastaus hyväksytään vain skeemaa vasten.
- Telegram (`telegram.py`), sydämenlyönti (`sydan.py`), ulkoisen datan `<data>`-lohko (`data.py`).
- Ajon kulku (`ajo.py`) ja komentorivi (`python -m agentti`): oletuksena kuiva-ajo, `--llm`, `--send` (kerran päivässä).
- Esimerkkiagentti, `luo.py` (uusi agentti pohjasta), kovennetut systemd-pohjat, DEPLOY.md.
- Testit (yli 80) ja CI (Python 3.10-3.13).
