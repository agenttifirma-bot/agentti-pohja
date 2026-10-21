# agentti-pohja

Yhteinen runko ajastetuille tekoälyagenteille: päivittäinen tiivistäjä, uutisseuranta, raportti, mikä tahansa "kerää dataa, tiivistä mallilla, lähetä Telegramiin" -agentti. Vain Pythonin standardikirjasto, ei riippuvuuksia, ei `pip install` -vaihetta palvelimella.

Pohja koostuu osista, jotka jokainen agentti tarvitsee ja jotka on helppo tehdä väärin:

| Osa | Tiedosto | Mitä se takaa |
| --- | --- | --- |
| Kulukatto | `kulu.py`, `rajat.py` | Päivä- ja kuukausikatto sekä kutsuraja. Kulu varataan **ennen** kutsua, joten katto pitää myös virhetilanteessa. Rikkinäinen kirjanpito pysäyttää kutsut eikä nollaudu hiljaa. |
| LLM-asiakas | `llm.py` | OpenAI-yhteensopiva (esim. LiteLLM). Ei työkaluja, `max_tokens`-katto, ei uudelleenohjausten seurantaa (avain ei karkaa), virheet koodeina: `llm_aikakatkaisu`, `llm_http_429`, `llm_vastaus_katkaistu`... |
| "En tiedä" | `tulos.py`, `skeema.py` | Vastaus on `ok` tai `ei_tietoa` + syy. Molemmat ovat normaaleja lopputuloksia. Muu kuin skeemaan sopiva vastaus hylätään. |
| Epäluotettava data | `data.py` | Ulkoinen data annetaan mallille `<data>`-lohkossa, jota sen sisältö ei voi sulkea, ja mallilla ei ole työkaluja. Prompt injection voi korkeintaan vääristää tekstiä. |
| Lähetys | `telegram.py`, `ajo.py` | Vastaanottaja tulee vain ympäristömuuttujasta, ei datasta tai mallilta. Lähetys korkeintaan kerran päivässä, ja epäonnistunut lähetys ei kuluta päivän lähetystä. |
| Valvonta | `sydan.py`, `ajo.py` | Virhe antaa paluukoodin 1, ja sydämenlyönti (esim. Uptime Kuma push) pingataan vain onnistuneen ajon jälkeen. |
| Ajastus | `systemd/*.mall` | Kovennettu oneshot-palvelu ja ajastin: oma käyttäjä, `ProtectSystem=strict`, ei oikeuksia, vain yksi kirjoitettava hakemisto. |

## Periaatteet

1. **Koodi on laki.** Rahaa ja turvallisuutta koskevat rajat ovat `rajat.py`:ssä kovakoodattuina, eivät prompteissa. Agentti, malli tai komentorivi ei voi muuttaa niitä; muutos vaatii omistajan luvan ja oman commitin.
2. **"En tiedä" on kelvollinen vastaus.** Pakotettu arvaus on huonompi kuin rehellinen `ei_tietoa`.
3. **Oletus on kuiva-ajo.** Verkkoa ja rahaa käytetään vasta, kun `--llm` ja `--send` annetaan erikseen.
4. **Vika näkyy.** Virheessä lähtee varaviesti raakadatasta ja virhekoodista, ja ajo päättyy koodiin 1.

## Pikakokeilu

Vaatii Python 3.10+ (Linux tai macOS; kulukirjanpito käyttää `flock`-lukkoa).

```bash
python -m agentti                 # kuiva-ajo: kerää datan, ei verkkoa
python -m unittest discover -s . -t . -p 'test_*.py'
```

Mallin kanssa (`LLM_BASE_URL` ja `LLM_API_KEY` ympäristössä tai `--env`-tiedostossa):

```bash
python -m agentti --llm           # kutsuu mallia, kulukatto voimassa
python -m agentti --llm --send    # lisäksi Telegramiin (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
```

Paluukoodit: `0` ok, `1` ajo epäonnistui (virhekoodi stderriin), `2` käyttövirhe.

## Uusi agentti

```bash
python luo.py uutiset
```

Tämä luo `agentti/agentit/uutiset.py` (kopio esimerkistä) ja `systemd/agentti-uutiset.service` + `.timer`. Muokkaa agentin moduulista viisi asiaa:

- `kerays()` hakee datan (tähän tulee agentin oma työ)
- `viestit(data)` rakentaa mallille viestit; käytä `data.data_lohko()` ja `data.SYSTEM_SAANNOT`
- `SKEEMA` kuvaa, mitä `sisalto`-kentässä saa olla
- `render(sisalto)` ja `render_kuiva(data)` tekevät Telegram-tekstin

Kirjoita jokaiselle uudelle agentille testit ennen käyttöönottoa. Mallina `test/test_ajo.py`.

## Itsenäinen työ: yöjono ja PR-kutsu

Pohjan päälle on rakennettu osat, joilla agentit tekevät tarkistettavaa työtä ilman että kukaan on paikalla. Jokainen osa on rajattu kovakoodatuin säännöin, ja ihminen katselmoi tulokset:

| Osa | Tiedosto | Mitä se tekee |
| --- | --- | --- |
| Yöjono | `yojono/` ([ohje](yojono/README.md)) | Ajaa jonotiedoston tehtävät peräkkäin päivä- ja kuukausikaton sisällä. Tyypit: `katselmointi` ja `ideointi` (vain raportti), `kehitys` (muutos haaraan ja PR, ks. [KEHITYS.md](yojono/KEHITYS.md)). |
| PR-kutsu | `agentti/pr_kutsu.py` | Pushaa `yo/<nimi>`-haaran botin forkkiin ja avaa PR:n. Sallittu repo-lista, ei force-pushia, suojatut polut (`.github/`, `tools/`, salaisuuden nimiset) estetty, enintään 40 tiedostoa ja 5 PR:ää päivässä. Tunnus annetaan gitille vain tilapäisen apuskriptin kautta. |
| Tapahtumaloki | `agentti/tapahtumaloki.py`, `loki_keraaja.py` | Vain lisäävä SQLite-loki tapahtumille ja palautteelle; salaisuuden näköiset merkkijonot poistetaan ennen tallennusta. |
| Viikkoraportti | `agentti/viikkoraportti.py` | Lukee lokin ja tulostaa kulut agenteittain, virheet ja sääntöpohjaiset vihjeet (ei mallikutsua). |
| Automerge | `tools/automerge.py` | Yhdistää automaattisesti vain pienet dokumentti- ja testimuutokset sekä botin `yo/readme-*`-PR:t, joissa on pelkkiä `.md`-tiedostoja. Koodi, työnkulut ja suojatut polut jäävät aina ihmiselle. |

Periaate on sama kuin pohjassa: koodi on laki. Raja ei ole kehotteessa vaan tarkistuksessa, ja jokainen automaattinen muutos on katselmoitavissa PR:nä.

## Käyttöönotto palvelimella

Katso [DEPLOY.md](DEPLOY.md): käyttäjä, hakemistot, salaisuudet, ajastin ja käyttöönottojärjestys (kuiva-ajo → `--llm` → `--send` → ajastin).

## Rajaukset

- Vain Linux/macOS (flock).
- Ei työkaluja malleille tarkoituksella. Jos agentti tarvitsee työkaluja, tee se omana, erikseen katselmoituna lisänä.
- Hinnasto (`HINNAT_USD_PER_MILJOONA`) on oletuksena tyhjä: tuntemattomalle mallille kirjanpitoon jää pessimistinen varaus (`KUTSU_ARVIO_USD`). Lisää mallin hinta vasta, kun olet tarkistanut sen palveluntarjoajalta.

## Lisenssi

MIT
