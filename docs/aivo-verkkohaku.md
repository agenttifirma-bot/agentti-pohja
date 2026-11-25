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
- Ei tehtäväkohtaisia haku- tai sivukiintiöitä (A1101). Hakutyöt eivät kuluta taustaajon ajattelijatöiden päivärajaa (`PAIVARAJA`, oletus 5/vrk), eikä niillä ole omaa määrärajaa. Rajoina ovat yhteinen 10 €/vrk päiväkatto, agentin silmukkasuojat (30 kutsua, 20 min), työn aikaraja ja enintään kaksi mallikutsua työtä kohden. Yksi taustaajon ajo aloittaa enintään 20 työtä (`AJON_TYORAJA`); loput jäävät jonoon seuraavaan ajoon minuutin päästä. Raja koskee vain yhden ajon kestoa (systemd `TimeoutStartSec`), ei töiden määrää vuorokaudessa. Ajattelijatöiden päiväraja, päiväkatto ja silmukkasuojat eivät muuttuneet.
- Valmis hakuvastaus tallennetaan keskusteluhistoriaan DATA-kehyksessä (satunnainen tunnus, `[[`, `]]`, `<<<` ja `>>>` rikottu). Merkintä `[Verkkohaku valmis]` on kehyksen ulkopuolella. Seuraavan vuoron malli näkee vastauksen datana eikä ohjeina.
- `Hae silti (<sha8>)`: odottava haku varataan atomisesti (tiedoston uudelleennimeäminen) ennen jonotusta. Kaksi samanaikaista vahvistusta jonottaa haun vain kerran; toinen saa vastauksen ”jo vahvistettu tai käsitelty”. Jos jonotus epäonnistuu, odottava haku palautetaan, ja Tony voi vahvistaa sen uudelleen.
- **Hakuloki:** päiväkohtainen JSONL yksityisessä kansiossa (0700, tiedostot 0600). Rivillä on vain `aika`, `tunnus`, `toiminto` ja `tila`. Lausekkeita, osoitteita eikä sisältöä ei kirjata. Yli 30 päivää vanhat lokitiedostot poistetaan automaattisesti (A1101). Yksityinen tila kirjoittaa kansioon `/var/lib/aivo-yksityinen/haku`, agentit kansioon `/var/lib/aivo-agentit/hakuloki`.
- Lausekkeet näkyvät Tonylle: chatin vastauksessa ja hakutuloksen viestissä sekä agenttikortissa.

## Asetukset

| Palvelu | Asetus | Arvo |
|---|---|---|
| `aivo-chat` | `AIVO_HAKU_JONO` (tai `--haku-jono`) | taustaajon jono, esim. `/var/lib/aivo-yksityinen/tyot` |
| `aivo-taustaajo` | `AIVO_HAKU_OSOITE` | `http://` + hakukontin osoite (kohta 2, muuttuja `IP123`) + `:8890` |
| `aivo-taustaajo` | `AIVO_HAKU_AVAIN` | oletus `/var/lib/aivo-yksityinen/haku-avain` (0600, taustaajon käyttäjä) |
| `aivo-taustaajo` | `AIVO_HAKU_LOKI`, `AIVO_VARTIJA_LISTAT` | oletukset `/var/lib/aivo-yksityinen/haku` ja `/var/lib/aivo-yksityinen/luovutukset/vartija` |
| `aivo-agentit` | `AIVO_HAKU_OSOITE` (tai `--haku-osoite`) | sama osoite kuin taustaajolla |
| `aivo-agentit` | avain | `/var/lib/aivo-agentit/haku-avain` (0600, `aivo-agentti`) |

### Vartijamalli ja "kysy"-tila

Chatin hakulausekkeet tarkistaa vartijamalli (rooli `vartija`). Jos vartijamallia ei ole asetettu, jokainen haku menee "kysy"-tilaan (syy `vartijamalli ei tarkistanut`): haku käynnistyy vasta, kun Tony valitsee `Hae silti (<sha8>)`. Tämä on turvallinen oletus, ei vika.

Vartijamalli on käytössä vain OpenRouter-taustapäällä. Se asetetaan `aivo-chat`-yksikön asetuksilla:

- `AIVO_YKSITYINEN_TAUSTAPAA=openrouter` (loopback-taustapäällä vartijamallia ei käytetä, koska teksti ei muuten lähtisi palvelimelta),
- `AIVO_YKSITYINEN_ROOLIT` sisältää osan `vartija:<malli>`, esimerkiksi `keskustelija:qwen/qwen3-235b-a22b-2507,vartija:qwen/qwen3-235b-a22b-2507`. Ilman `vartija`-osaa käytetään `AIVO_OPENROUTER_MALLIT`-listan ensimmäistä mallia.

Mallin pitää olla sallittujen mallien listalla. Vartijan kutsu kulkee samaa reittiä kuin muut yksityisen tilan kutsut (ZDR ja yhteinen päiväkatto). Tarkistus kohdassa 6.

Hauissa sääntö on tiukempi kuin luovutuksissa: jos vartijamalli merkitsi lausekkeesta yhdenkin kohdan, tulos on "kysy" myös arviolla "pieni" (syy `vartijamalli merkitsi kohtia`).

## Käyttöönotto (Tony)

Esiehdot: hakukontti ja hakuvälittäjä on otettu käyttöön (#438 ja #440), taustaajo on käytössä (`docs/aivo-taustaajo.md`), ja tämä muutos on yhdistetty ja päivittynyt kontin 122 klooniin. Aja komennot isännällä yksi kerrallaan samassa pääteistunnossa, koska myöhemmät komennot käyttävät aiemmin asetettuja muuttujia. Jos tulos poikkeaa Odotettu-rivistä, pysähdy.

### 1. Snapshot

```bash
pct snapshot 122 ennen-verkkohaku
```
Odotettu: ei virhettä.

### 2. Hakukontin osoite ja palomuuri

Hakukontin osoite luetaan sen omista asetuksista, kuten #438:n ohjeessa.

```bash
IP123=$(pct config 123 | sed -n 's/^net0:.*ip=\([0-9.]*\)\/.*/\1/p'); echo "$IP123"
```
Odotettu: yksi IPv4-osoite. Jos tulos on tyhjä, pysähdy: hakukontilla pitää olla kiinteä osoite (#438, kohta 1).

Salli Proxmox-palomuurissa vain kontista 122 hakukontin porttiin 8890 (TCP). PR 1:n ohjeen kohta Proxmox-säännöistä koskee tätä. Muita sääntöjä ei muuteta (RAJATTU, Tonyn päätös).

```bash
pct exec 122 -- python3 -c 'import socket,sys; socket.create_connection((sys.argv[1], 8890), 5); print("YHTEYS OK")' "$IP123"
```
Odotettu: `YHTEYS OK`.

### 3. Palvelujen käyttäjät

Avaimen omistajan pitää olla sama käyttäjä, joka ajaa palvelun. Tarkista käyttäjät ennen avaimen siirtoa.

```bash
pct exec 122 -- systemctl show -p User aivo-chat
```
Odotettu: `User=aivo` tai `User=aivo-yksityinen` (yksityisen tilan ohje).

```bash
TAUSTA=$(pct exec 122 -- systemctl show -p User --value aivo-taustaajo); echo "$TAUSTA"
```
Odotettu: sama nimi kuin edellisen komennon `User=`-arvo. Chat kirjoittaa hakutyöt taustaajon jonoon (0700), joten käyttäjien pitää olla samat. Jos ne eroavat tai tulos on tyhjä, pysähdy.

```bash
TAUSTARYHMA=$(pct exec 122 -- id -gn "$TAUSTA"); echo "$TAUSTARYHMA"
```
Odotettu: käyttäjän pääryhmä, yleensä sama nimi kuin käyttäjällä.

```bash
pct exec 122 -- systemctl show -p User aivo-agentit
```
Odotettu: `User=aivo-agentti`.

### 4. Avain konttiin 122 (ei tulosteta)

Avain kopioidaan hakukontista isännän tilapäistiedoston kautta. Sisältöä ei tulosteta missään vaiheessa.

```bash
pct pull 123 /etc/aivo-haku/avain /root/.haku-avain.tmp
```
Odotettu: ei tulostetta.

```bash
pct push 122 /root/.haku-avain.tmp /var/lib/aivo-yksityinen/haku-avain --user "$TAUSTA" --group "$TAUSTARYHMA" --perms 0600
```
Odotettu: ei tulostetta.

```bash
pct push 122 /root/.haku-avain.tmp /var/lib/aivo-agentit/haku-avain --user aivo-agentti --group aivo-agentti --perms 0600
```
Odotettu: ei tulostetta.

```bash
shred -u /root/.haku-avain.tmp
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- stat -c '%a %U %s' /var/lib/aivo-yksityinen/haku-avain /var/lib/aivo-agentit/haku-avain
```
Odotettu: kaksi riviä, `600 <TAUSTA-käyttäjä> 44` ja `600 aivo-agentti 44` (koko tavuina, ei sisältöä).

### 5. Asetukset drop-in-tiedostoilla

Jokainen palvelu saa oman drop-in-tiedoston `verkkohaku.conf`. Alkuperäisiä yksikkötiedostoja ei muokata.

Chat:

```bash
pct exec 122 -- sh -c 'mkdir -p /etc/systemd/system/aivo-chat.service.d && printf "[Service]\nEnvironment=AIVO_HAKU_JONO=/var/lib/aivo-yksityinen/tyot\n" > /etc/systemd/system/aivo-chat.service.d/verkkohaku.conf && cat /etc/systemd/system/aivo-chat.service.d/verkkohaku.conf'
```
Odotettu: kaksi riviä, `[Service]` ja `Environment=AIVO_HAKU_JONO=/var/lib/aivo-yksityinen/tyot`.

Taustaajo:

```bash
pct exec 122 -- sh -c 'mkdir -p /etc/systemd/system/aivo-taustaajo.service.d && printf "[Service]\nEnvironment=AIVO_HAKU_OSOITE=http://%s:8890\n" "$1" > /etc/systemd/system/aivo-taustaajo.service.d/verkkohaku.conf && cat /etc/systemd/system/aivo-taustaajo.service.d/verkkohaku.conf' sh "$IP123"
```
Odotettu: kaksi riviä, `[Service]` ja `Environment=AIVO_HAKU_OSOITE=http://<kohdan 2 osoite>:8890`.

Agentit:

```bash
pct exec 122 -- sh -c 'mkdir -p /etc/systemd/system/aivo-agentit.service.d && printf "[Service]\nEnvironment=AIVO_HAKU_OSOITE=http://%s:8890\n" "$1" > /etc/systemd/system/aivo-agentit.service.d/verkkohaku.conf && cat /etc/systemd/system/aivo-agentit.service.d/verkkohaku.conf' sh "$IP123"
```
Odotettu: kaksi riviä, `[Service]` ja `Environment=AIVO_HAKU_OSOITE=http://<kohdan 2 osoite>:8890`.

```bash
pct exec 122 -- systemctl daemon-reload
```
Odotettu: ei tulostetta.

Chat käynnistetään uudelleen omana komentonaan:

```bash
pct exec 122 -- systemctl restart aivo-chat
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- systemctl is-active aivo-chat
```
Odotettu: `active`.

Taustaajo on ajastimen käynnistämä kertapalvelu, joten sitä ei käynnistetä uudelleen. Seuraava ajo lukee uuden asetuksen. Tarkista, että drop-in on voimassa:

```bash
pct exec 122 -- systemctl show -p DropInPaths aivo-taustaajo
```
Odotettu: rivi `DropInPaths=`, jossa on `/etc/systemd/system/aivo-taustaajo.service.d/verkkohaku.conf`.

Agentit käynnistetään uudelleen omana komentonaan:

```bash
pct exec 122 -- systemctl restart aivo-agentit
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- systemctl is-active aivo-agentit
```
Odotettu: `active`.

### 6. Vartijamallin tarkistus

```bash
pct exec 122 -- sh -c 'systemctl show -p Environment aivo-chat | tr " " "\n" | grep -E "^(Environment=)?AIVO_(YKSITYINEN_TAUSTAPAA|YKSITYINEN_ROOLIT|OPENROUTER_MALLIT)="'
```
Odotettu: `AIVO_YKSITYINEN_TAUSTAPAA=openrouter` ja mallirivit. Jos `AIVO_YKSITYINEN_TAUSTAPAA` puuttuu tai on `loopback`, vartijamallia ei ole, ja jokainen haku menee "kysy"-tilaan (katso kohta Vartijamalli ja "kysy"-tila).

### 7. Käytöstesti

Kirjoita yksityisessä chatissa: "Hae verkosta, mikä on Pythonin uusin vakaa versio." Odotettu: vastauksessa on `[Haku: ”…”. Verkkohaku on käynnistetty. …]`, ja muutaman minuutin päästä keskusteluun tulee `[Verkkohaku valmis]`, DATA-kehys ja sen sisällä lähdeluettelo. Jos vastauksessa on `Haetaanko silti?` ja syy `vartijamalli ei tarkistanut`, vartijamallia ei ole asetettu (kohta 6).

```bash
pct exec 122 -- ls -l /var/lib/aivo-yksityinen/haku/
```
Odotettu: tiedosto `haku-VVVV-KK-PP.jsonl` oikeuksin `-rw-------`.

```bash
pct exec 122 -- sh -c 'tail -n 3 /var/lib/aivo-yksityinen/haku/haku-*.jsonl'
```
Odotettu: riveillä on vain kentät `aika`, `tunnus`, `toiminto` ja `tila` (ei lauseketta eikä osoitetta).

Kill switch: pysäytä Tor hakukontissa.

```bash
pct exec 123 -- systemctl stop tor@default
```
Odotettu: ei tulostetta. Pyydä chatissa uusi haku. Odotettu: `[Verkkohaku epäonnistui] Syy: verkkohaku ei onnistunut.`

```bash
pct exec 123 -- systemctl start tor@default
```
Odotettu: ei tulostetta.

### 8. Peruutus

Poista drop-in-tiedostot yksi kerrallaan:

```bash
pct exec 122 -- rm /etc/systemd/system/aivo-chat.service.d/verkkohaku.conf
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- rm /etc/systemd/system/aivo-taustaajo.service.d/verkkohaku.conf
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- rm /etc/systemd/system/aivo-agentit.service.d/verkkohaku.conf
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- systemctl daemon-reload
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- systemctl restart aivo-chat
```
Odotettu: ei tulostetta.

```bash
pct exec 122 -- systemctl restart aivo-agentit
```
Odotettu: ei tulostetta. Haku on nyt pois käytöstä. Tarvittaessa `pct rollback 122 ennen-verkkohaku` (Tonyn päätös).

## Testit

`aivo/test_verkkohaku.py` (62 testiä, ei oikeaa verkkoa): vartijan kolme lopputulosta, sallintalista, väärennetty vartijatulos, kuljetin silmukkaosoitteen valehakuvälittäjää vasten (avain, virhekoodit, ei uudelleenohjauksia, ei välityspalvelinta, kokoraja), hakuloki ja säilytysaika, taustaajon hakutyö valekuljettimella, chatin `[[HAKU]]`-merkintä ja Tonyn vahvistus sekä agenttien `hae` ja `sivu` valemallilla. Rakennetestit varmistavat, että hakuvälittäjän polut ovat vain moduulissa `verkkohaku.py` ja että agenttien työkalut kutsuvat vain hakuistuntoa. Lisäksi: kuudes haku samana päivänä onnistuu ja kuudes ajattelijatyö estyy, ajon työraja jättää ylimääräiset työt jonoon, merkitty kohta antaa tuloksen "kysy" myös arviolla "pieni", hakuvastaus tallentuu DATA-kehyksessä, kaksi samanaikaista vahvistusta jonottaa haun kerran, ja ilman vartijamallia jokainen haku kysyy.
