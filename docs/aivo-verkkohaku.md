# Aivon verkkohaku kontissa 122: yksityinen tila ja agentit

Tämä on verkkohaun PR 3 (suunnitelma `claude-jono/suunnitelmat/aivo-verkkohaku.md`, Tonyn päätökset A1101 25.11.2026). PR 1 (#438) toi hakukontin ohjeen ja PR 2 (#440) hakuvälittäjän. Tämä muutos kytkee hakuvälittäjän yksityiseen chattiin, taustaajoon ja eristettyihin agentteihin.

**RAJATTU:** uusi datavirta yksityisestä kontista hakukonttiin ja agenttien uudet työkalut. Tony ottaa muutoksen käyttöön itse. Ei automergeä.

Mikään ei muutu ennen käyttöönottoa: ilman asetuksia `AIVO_HAKU_JONO` ja `AIVO_HAKU_OSOITE` haku ei ole käytössä, eikä verkkoyhteyttä avata.

## Kulku

1. **Yksityinen chat:** keskustelija kirjoittaa vastauksen loppuun `[[HAKU: hakulauseke]]`. Palvelin poistaa merkinnän ja tarkistaa lausekkeen heti (`aivo/hakukytkenta.py`):
   - mekaaninen esitarkistus ja vuotovartija (`aivo/vartija.py`, sama koodi kuin luovutuksissa, hakuun sopiva ohje)
   - **esto** (salaisuustyypit, A1096): hakua ei tehdä, ja vastaukseen tulee syyt tyyppeinä. Estoa ei voi ohittaa.
   - **kysy**: hakua ei tehdä. Tony näkee lausekkeen ja syyt sekä valinnat `Hae silti (<sha8>)` ja `Älä hae`. Vain Tonyn oma viesti `Hae silti (<sha8>)` samassa keskustelussa käynnistää haun. Mekaaninen esto lasketaan silloin uudelleen.
   - **turvallinen**: haku menee taustaajon jonoon (työtyyppi `haku`).
2. **Taustaajo** (`aivo/taustaajo.py`): hakuvälittäjän `/haku` → ajattelija valitsee luettavat tulokset (`SIVUT: 1, 3`) → `/sivu` vain näille tuloksille → keskustelija vastaa suomeksi DATA-kehystetystä tekstistä lähdenumeroin `[n]`. Palvelin lisää lausekkeen ja lähdeluettelon (`[n] otsikko – URL`). Vastaus tulee keskusteluun merkinnällä `[Verkkohaku valmis]`. Mallikutsuja on enintään kaksi, kuten muissakin taustatöissä.
3. **Agentit** (`aivo/agentti/`): tekijä saa työkalut `hae {"lauseke"}` ja `sivu {"url"}`, kun ajurilla on hakuosoite. Jokainen lauseke kulkee saman vartijan kautta. Vartijamallina on tarkastajan malli (rooli `vartija`), ja kutsu kulkee samaa reittiä ja saman 30 kutsun askelrajan sisällä kuin muut roolit. Agentti ei voi kysyä Tonylta, joten tulos `kysy` ei hae. Lausekkeet ja haetut osoitteet tiloineen tallentuvat tuloksen kenttään `verkko`, ja ne näkyvät agenttikortissa.

## Säännöt (koodi on laki)

- `aivo/verkkohaku.py` on ainoa moduuli, joka avaa yhteyden hakuvälittäjään. Kuljetin hyväksyy vain asetetun osoitteen (`http://isäntä:portti`) ja polut `/haku` ja `/sivu`. Se ei seuraa uudelleenohjauksia eikä käytä välityspalvelimia, ja vastauksen koko on rajattu (512 kt).
- Sivun saa hakea vain, jos sen osoite on saman tehtävän hakutuloksissa täsmälleen samassa muodossa. Mallin keksimä tai muokkaama osoite hylätään ennen verkkoa (`url_ei_tuloksissa`).
- Hakuvälittäjälle lähtee satunnainen istuntotunnus, ei tehtävän tunnusta eikä tekstiä.
- Haettu teksti on dataa: `[[`, `]]`, `<<<` ja `>>>` rikotaan, ja teksti kehystetään satunnaisella tunnuksella.
- Ei tehtäväkohtaisia haku- tai sivukiintiöitä (A1101). Rajoina ovat yhteinen 10 €/vrk päiväkatto, agentin silmukkasuojat (30 kutsua, 20 min) ja taustaajon olemassa olevat rajat (päiväraja ja aikaraja). Näitä ei muutettu.
- **Hakuloki:** päiväkohtainen JSONL yksityisessä kansiossa (0700, tiedostot 0600). Rivillä on vain `aika`, `tunnus`, `toiminto` ja `tila`. Lausekkeita, osoitteita eikä sisältöä ei kirjata. Yli 30 päivää vanhat lokitiedostot poistetaan automaattisesti (A1101). Yksityinen tila kirjoittaa kansioon `/var/lib/aivo-yksityinen/haku`, agentit kansioon `/var/lib/aivo-agentit/hakuloki`.
- Lausekkeet näkyvät Tonylle: chatin vastauksessa ja hakutuloksen viestissä sekä agenttikortissa.

## Asetukset

| Palvelu | Asetus | Arvo |
|---|---|---|
| `aivo-chat` | `AIVO_HAKU_JONO` (tai `--haku-jono`) | taustaajon jono, esim. `/var/lib/aivo-yksityinen/tyot` |
| `aivo-taustaajo` | `AIVO_HAKU_OSOITE` | `http://<hakukontin osoite>:8890` |
| `aivo-taustaajo` | `AIVO_HAKU_AVAIN` | oletus `/var/lib/aivo-yksityinen/haku-avain` (0600, `aivo`) |
| `aivo-taustaajo` | `AIVO_HAKU_LOKI`, `AIVO_VARTIJA_LISTAT` | oletukset `/var/lib/aivo-yksityinen/haku` ja `/var/lib/aivo-yksityinen/luovutukset/vartija` |
| `aivo-agentit` | `AIVO_HAKU_OSOITE` (tai `--haku-osoite`) | `http://<hakukontin osoite>:8890` |
| `aivo-agentit` | avain | `/var/lib/aivo-agentit/haku-avain` (0600, `aivo-agentti`) |

## Käyttöönotto (Tony)

Esiehdot: hakukontti ja hakuvälittäjä on otettu käyttöön (#438 ja #440), taustaajo on käytössä (`docs/aivo-taustaajo.md`), ja tämä muutos on yhdistetty ja päivittynyt kontin 122 klooniin. Aja komennot yksi kerrallaan. Jos tulos poikkeaa Odotettu-rivistä, pysähdy.

### 1. Snapshot

```bash
pct snapshot 122 ennen-verkkohaku
```
Odotettu: ei virhettä.

### 2. Palomuuri (RAJATTU, Tonyn päätös)

Salli Proxmox-palomuurissa vain kontista 122 hakukontin porttiin 8890 (TCP). PR 1:n ohjeen kohta Proxmox-säännöistä koskee tätä. Muita sääntöjä ei muuteta.

```bash
pct exec 122 -- python3 -c 'import socket; s=socket.create_connection(("<hakukontin osoite>", 8890), 5); print("YHTEYS OK")'
```
Odotettu: `YHTEYS OK`.

### 3. Avain konttiin 122 (ei tulosteta)

```bash
pct pull 123 /etc/aivo-haku/avain /root/.haku-avain.tmp
pct push 122 /root/.haku-avain.tmp /var/lib/aivo-yksityinen/haku-avain --user aivo --group aivo --perms 0600
pct push 122 /root/.haku-avain.tmp /var/lib/aivo-agentit/haku-avain --user aivo-agentti --group aivo-agentti --perms 0600
shred -u /root/.haku-avain.tmp
pct exec 122 -- stat -c '%a %U %s' /var/lib/aivo-yksityinen/haku-avain /var/lib/aivo-agentit/haku-avain
```
Odotettu: kaksi riviä `600 aivo 44` ja `600 aivo-agentti 44` (koko tavuina, ei sisältöä).

### 4. Asetukset

```bash
pct exec 122 -- systemctl edit aivo-chat
```
Lisää `[Service]`-osioon `Environment=AIVO_HAKU_JONO=/var/lib/aivo-yksityinen/tyot`. Tee sama `aivo-taustaajo`-yksikölle rivillä `Environment=AIVO_HAKU_OSOITE=http://<hakukontin osoite>:8890` ja `aivo-agentit`-yksikölle samalla rivillä. Sen jälkeen:

```bash
pct exec 122 -- systemctl daemon-reload
pct exec 122 -- systemctl restart aivo-chat aivo-agentit
pct exec 122 -- systemctl is-active aivo-chat aivo-agentit
```
Odotettu: kaksi riviä `active`.

### 5. Käytöstesti

Kirjoita yksityisessä chatissa: "Hae verkosta, mikä on Pythonin uusin vakaa versio." Odotettu: vastauksessa on `[Haku: ”…”. Verkkohaku on käynnistetty. …]`, ja muutaman minuutin päästä keskusteluun tulee `[Verkkohaku valmis]` ja lähdeluettelo.

```bash
pct exec 122 -- sh -c 'ls -l /var/lib/aivo-yksityinen/haku/ && tail -n 3 /var/lib/aivo-yksityinen/haku/haku-*.jsonl'
```
Odotettu: tiedosto `haku-VVVV-KK-PP.jsonl` oikeuksin `-rw-------`, ja riveillä on vain `aika`, `tunnus`, `toiminto` ja `tila` (ei lauseketta eikä osoitetta).

Kill switch: pysäytä Tor hakukontissa (`pct exec 123 -- systemctl stop tor@default`) ja pyydä uusi haku. Odotettu: `[Verkkohaku epäonnistui] Syy: verkkohaku ei onnistunut.` Käynnistä Tor uudelleen (`pct exec 123 -- systemctl start tor@default`).

### 6. Peruutus

Poista lisätyt `Environment`-rivit (`systemctl edit`) ja käynnistä palvelut uudelleen. Haku on silloin pois käytöstä. Tarvittaessa `pct rollback 122 ennen-verkkohaku` (Tonyn päätös).

## Testit

`aivo/test_verkkohaku.py` (54 testiä, ei oikeaa verkkoa): vartijan kolme lopputulosta, sallintalista, väärennetty vartijatulos, kuljetin silmukkaosoitteen valehakuvälittäjää vasten (avain, virhekoodit, ei uudelleenohjauksia, ei välityspalvelinta, kokoraja), hakuloki ja säilytysaika, taustaajon hakutyö valekuljettimella, chatin `[[HAKU]]`-merkintä ja Tonyn vahvistus sekä agenttien `hae` ja `sivu` valemallilla. Rakennetestit varmistavat, että hakuvälittäjän polut ovat vain moduulissa `verkkohaku.py` ja että agenttien työkalut kutsuvat vain hakuistuntoa.
