# Gitea: GitHub-peilit ja yksityisen työn koti

Tila 2.11.2026. Tämä on ohje Tonylle. Dokumentti ja skripti on kirjoitettu agenttikontissa, eikä Giteaa ole avattu eikä sille ole ajettu mitään. Kaikki ajot tekee Tony itse.

Todennettu käytössä: ei vielä. Ohje on kirjoituspöytätarkistettu (paikkamerkit `<GITEA-KONTTI>`, `<PG-KONTTI>`, `<GITEA-OSOITE>`, `<ADMIN>`, `<OMISTAJA>` korvataan omilla arvoilla), mutta komentoja ei ole ajettu oikeassa Giteassa. Tony todentaa ne ajo-ohjeen kohdissa 1–7.

## Lähtötiedot

- Gitea on omassa kontissaan (`<GITEA-KONTTI>`, osoite `<GITEA-OSOITE>`, 2 ydintä, 2 Gt, 8 Gt levy, ylläpitäjä `<ADMIN>`). Tietokanta `gitea` on Postgres-kontissa (`<PG-KONTTI>`). Kontti- ja osoitetiedot ovat yksityisessä infrastruktuuriohjeessa.
- Gitean versiota ei löytynyt infrastruktuuriohjeesta eikä agentti-pohjan isäntäskripteistä. Tarkista se isännältä:

  ```
  pct exec <GITEA-KONTTI> -- gitea --version
  ```

  Jos komento ei löydä ohjelmaa, kokeile selaimella tai `curl`illa osoitetta `<gitea>/api/v1/version`.
- Gitea on tarkoitus avata Tailscale-osoitteen kautta (sääntö: Tailscale per palvelukontti, `tailscale serve`). Kontin tarkkaa Tailscale-nimeä ei ole kirjattu tähän; tässä ohjeessa sen paikalla on `GITEA`.
- Peilit ovat vain luku -kopioita. Gitea hakee muutokset GitHubista tunnin välein. Peileihin ei kirjoiteta Giteasta päin.

## a) Pull-peilit kaikista julkisista repoista

Skripti `tools/gitea_peilit.py` (vain vakiokirjasto). Huom: `tools/` on PR-kutsun suojattu polku, joten agentti ei voinut lisätä skriptiä tähän PR:ään. Se on valmiina ja testattuna haarassa `yo/gitea-peilit-skripti`. Tony tuo sen käsin (`git cherry-pick`) tai hyväksyy toisen paikan. Skripti:

1. Listaa käyttäjän `tonyweckstrom1987` julkiset repot GitHubin rajapinnasta. Tunnusta ei tarvita. Forkit jätetään pois, ellei anna valitsinta `--forkit`.
2. Tarkistaa, onko repo jo Giteassa, ja ohittaa sen. Skriptin voi siis ajaa uudelleen.
3. Luo puuttuvat peilit kutsulla `POST /api/v1/repos/migrate` (`mirror: true`, `mirror_interval: 1h0m0s`).
4. Peilit luodaan yksityisinä. Julkisuussääntö pysyy ennallaan: GitHub on julkinen näyteikkuna, Gitea on koti.

Turvallisuus:

- Kuiva-ajo on oletus. Se ei kirjoita Giteaan mitään. Peilit luodaan vasta valitsimella `--aja`.
- Gitea-token luetaan vain ympäristömuuttujasta `GITEA_TOKEN`. Skripti ei tulosta sitä, eikä sitä anneta komentoriville.
- Virheistä tulostetaan vain tyyppi ja HTTP-tila.
- Tokenin oikeudeksi riittää `write:repository`. Luo se Giteassa: Asetukset, Sovellukset. Älä anna sille ylläpitäjän oikeuksia.

Yksityiset repot (esimerkiksi docs-repo) vaativat GitHub-tokenin, jonka Gitea tallentaisi peilin asetuksiin. Tämä on Tonyn päätös, eikä skripti tee sitä. Vaihtoehto on siirtää yksityinen repo kokonaan Giteaan (kohta b), jolloin GitHub-tokenia ei tarvita.

### Tonyn ajo-ohje (7 komentoa)

Aja koneella, jolla on yhteys Giteaan (Tailscale päällä) ja tämä repo kloonattuna (skriptin haara yllä):

```
pct exec <GITEA-KONTTI> -- gitea --version           # 1. isännällä: versio talteen
pct exec <GITEA-KONTTI> -- df -h /                   # 2. isännällä: vapaa tila
read -rs GITEA_TOKEN && export GITEA_TOKEN           # 3. liitä token (ei näy ruudulla)
python3 tools/gitea_peilit.py --gitea https://GITEA  # 4. kuiva-ajo, lukee vain GitHubia
python3 tools/gitea_peilit.py --gitea https://GITEA --aja   # 5. luo peilit
unset GITEA_TOKEN                                    # 6. poista token ympäristöstä
pvesh get /cluster/backup --output-format json-pretty       # 7. isännällä: vzdump-työn sisältö
```

Komennot 1, 2 ja 7 ajetaan Proxmox-isännällä, komennot 3–6 koneella, jolla Gitea näkyy. Tarkista kuiva-ajon tuloste ennen komentoa 5.

## b) Yksityisen repon siirto Giteaan

Siirto ja käyttö:

1. Luo Giteaan tyhjä yksityinen repo (esimerkiksi `yksityinen-repo`). Älä käytä peiliä, koska peilistä ei voi työntää.
2. Työnnä sisältö omalta koneelta: `git remote add gitea https://GITEA/<OMISTAJA>/<repo>.git`, sitten `git push gitea --all` ja `git push gitea --tags`.
3. Kun Gitea-kopio on todennettu (`git ls-remote gitea` näyttää samat haarat), poista GitHub-repo vasta Tonyn omalla päätöksellä. Agentit eivät poista mitään.
4. Siirrä tämän jälkeen repon `origin` osoittamaan Giteaan: `git remote set-url origin https://GITEA/<OMISTAJA>/<repo>.git`.

Miten claude-jono ja prbotti käyttäisivät Giteaa (ehdotus, ei käytössä):

- Gitealle luodaan oma botti-käyttäjä (`agenttifirma-bot`, tavallinen käyttäjä, ei ylläpitäjä). Sillä on oma token, jonka oikeus on vain `write:repository`.
- Ei forkkeja. Botti lisätään yksittäisen repon yhteistyökumppaniksi kirjoitusoikeudella ja se työntää `yo/`-haaroja suoraan samaan repoon. Päähaara suojataan Giteassa: suora työntö kielletty, yhdistäminen vain Tonylle. Näin botti ei voi muuttaa päähaaraa, vaikka koodin tarkistus pettäisi.
- Pull request luodaan kutsulla `POST /api/v1/repos/{omistaja}/{repo}/pulls`.
- Osoite on Tailscale-osoite, ei julkinen. Agenttikontin pitää nähdä Gitea tailnetissä.
- Nykyinen `agentti/pr_kutsu.py` osaa vain GitHubin ja sen `REPOT`-lista on kovakoodattu. Giteatuki vaatii koodimuutoksen, ja se kuuluu "Koodi on laki" -alueeseen (repolista, polkurajaukset, päiväkatto). Siksi muutosta ei ole tehty tässä PR:ssä. Tony päättää erikseen, tehdäänkö se.

## c) Gitea Actions (act_runner) yksityisille testeille

Vaatimukset:

- Actions on otettava käyttöön Gitean asetuksissa (`app.ini`, osio `[actions]`, `ENABLED = true`). Tarkista, että versio tukee sitä; versio selviää kohdan a komennosta 1.
- Ajaja (`act_runner`) rekisteröidään Gitealle rekisteröintitunnuksella, jonka Tony luo itse Gitean ylläpitonäkymässä. Tunnusta ei kirjoiteta mihinkään tiedostoon, joka päätyy repoon.
- Ajajalle luodaan oma kontti (unprivileged), ei Gitea-konttiin. Docker kontin sisällä on vastoin arkkitehtuurisääntöä (natiiviasennukset), joten käytä ajajan `host`-tunnistetta: työt ajetaan suoraan ajajakontissa tavallisena käyttäjänä.

Riskit:

- Työn koodi ajetaan ajajalla. Kuka tahansa, joka voi työntää repoon työnkulun, voi ajaa koodia ajajakontissa. Siksi Actions kytketään päälle vain yksityisille repoille, joihin kirjoittaa vain Tony ja botti.
- Ei avaimia: ajajakonttiin ei laiteta holvin tunnuksia, LiteLLM-avaimia eikä GitHub-tunnuksia. Giteaan ei tallenneta tuotantosalaisuuksia (Actions-salaisuudet).
- Verkko: ajajakontilla ei ole Tailscalea eikä pääsyä muihin kontteihin. Palomuuri sallii liikenteen vain Giteaan (rekisteröinti ja työt) ja ulos pakettien latausta varten. Palomuurisäännöt on Tonyn muutettavissa, eivät agenttien.
- Testit eivät saa käyttää oikeaa rahaa tai kauppa-API:a. Kauppatiimin testit ajetaan vain vanhoilla aineistoilla.
- Ota snapshot ennen ajajan asennusta ja sen jälkeen.

## d) Varmuuskopio ja levytila

Varmuuskopiot (infrastruktuuriohje): yöllinen vzdump-työ "yo-varmuuskopio" klo 02:30 kattaa kaikki kontit (keep-last=3). Rclone-kopio lähtee klo 04:00 salattuna Google Driveen. Tämä pitäisi kattaa sekä Gitea-kontti (tiedostot, repot) että Postgres-kontti (Gitean tietokanta). Älä silti luota pelkkään dokumenttiin. Varmista asia komennolla 7:

- Työn `vmid`-kentässä pitää olla joko `all` tai sekä Gitea- että Postgres-kontin tunnus. Jos kentässä on luettelo, josta Gitea-kontti puuttuu, lisää se.
- Gitean repot ovat Gitea-kontissa ja metatiedot (käyttäjät, tiketit, PR:t) Postgres-kontin kannassa. Kummankin pitää olla samassa ajossa, jotta palautettu tila on yhtenäinen.
- Palautusta ei ole vielä kokeiltu oikeasti (docs: vain tarkistussumma). Kokeile palautusta kerran uuteen tunnukseen ennen kuin Giteaan siirretään ainoa kopio yksityisestä työstä.

Levytila-arvio (GitHubin `size`-kentästä, 2.11.2026, rajapinta `users/tonyweckstrom1987/repos`):

| Mitta | Arvo |
|---|---|
| Julkisia repoja (ei forkkeja) | 21 |
| GitHubin ilmoittama koko yhteensä | noin 7,5 Mt |
| Suurimmat | tonyweckstrom1987.github.io 3,1 Mt, software-developer-portfolio 1,6 Mt, agentti-pohja 0,8 Mt |
| Arvio Giteassa (kerroin 3: tietokannan merkinnät, pakkaamattomat objektit, kasvu) | noin 25 Mt |
| Gitea-kontin levy | 8 Gt |

`size` on likiarvo (ei sisällä esimerkiksi LFS-tiedostoja), mutta peilit mahtuvat reilusti: alle 1 % kontin levystä. Vzdump-arkisto kasvaa saman verran ja kolmen arkiston säilytys alle 100 Mt. Levytilaa kannattaa seurata muusta syystä: ohuen levypoolin (thin pool) snapshotit täyttävät sitä, ja infrastruktuuriohje mainitsee ylivarauksen. Tarkista vapaa tila komennolla 2 ja poolin käyttö ennen uusia snapshotteja.

## Avoimet kysymykset Tonylle

1. Gitean versio (komento 1) ja Tailscale-osoite.
2. Peilataanko myös yksityinen docs-repo (vaatii GitHub-tokenin Giteaan) vai siirretäänkö se kokonaan Giteaan?
3. Tehdäänkö botille Giteatuki `pr_kutsu.py`:hin (muutos "Koodi on laki" -alueelle, vaatii erillisen luvan)?
4. Rakennetaanko act_runner omaan konttiin heti vai vasta, kun ensimmäinen yksityinen testi tarvitsee sitä?
