# Aivo: eristettyjen agenttien ajuri (kontti 122)

Ajuri ajaa yksityisen tilan agenttitehtävät omana käyttäjänään `aivo-agentti`. Agentti ei näe muistia, keskusteluja eikä ydinohjeita: se saa vain tehtävän tekstin ja pyynnön mukana tulevat liitteet. Agenttiydin ja mallikytkentä ovat paketissa `aivo/agentti/`. Ajuri on moduuli `aivo/agentti_ajuri.py`, ja yksikkömalli on tiedostossa `systemd/aivo-agentit.service.mall`.

Tämä ohje asentaa vain ajurin. Chat ei vielä kirjoita jonoon eikä näytä tuloksia; se tulee myöhemmässä muutoksessa. Siihen asti tehtävän voi lisätä jonoon käsin (kohta 8).

## Miten ajuri toimii

- Palvelu `aivo-agentit.service` lukee kansiota `/var/lib/aivo-agentit/jono/` kymmenen sekunnin välein ja ajaa vanhimman pyynnön. Tehtäviä ajetaan yksi kerrallaan. Lukko (`ajuri.lukko`) estää toisen ajurin käynnistymisen.
- Ajuri siirtää pyynnön kansioon `kasitellyt/`, luo työkansion `tyo/<tunnus>/` (0700) ja kopioi liitteet sinne samoilla polku-, pääte- ja kokosäännöillä kuin agentin `kirjoita`-työkalu.
- Tehtävä ajetaan aliprosessina (`python3 -m aivo.agentti_ajuri lapsi`). Ajuri lopettaa aliprosessin, jos se kestää yli 21 minuuttia: agenttiytimen 20 minuutin aikaraja ja minuutin vara. Tulos on silloin `keskeytetty`.
- Tulos kirjoitetaan tiedostoon `tulokset/<tunnus>.json` (0640, ryhmä `aivo-agentit`).
- Ajuri ei poista mitään. Pyynnöt, työkansiot ja tulokset jäävät talteen, ja niiden siivous on oma päätöksensä.
- Jos ajuri pysähtyy kesken tehtävän, se kirjoittaa seuraavalla käynnistyksellä tulokseksi `keskeytetty` ja syyksi `ajuri pysahtyi kesken tehtavan`.
- Lokiin (journald) tulee vain tunnus, tila, luvut ja virheen tyyppi, ei tehtävän sisältöä.

### Rajat

Ajuri ei lisää uusia kulu-, budjetti- tai askelrajoja (Tonyn päätös A1072). Voimassa ovat agenttiytimen rajat: 30 mallikutsua tehtävää kohden ja 20 minuuttia. Kaikki kutsut kulkevat funktion `openrouter_kulut.kutsu` kautta ZDR-pakotuksella, ja ne kirjataan samaan kulukirjanpitoon kuin chatin kutsut. Yhteinen 10 €:n päiväkatto pysäyttää myös agentit.

### Pyynnön muoto

Pyyntö on JSON-tiedosto `jono/<tunnus>.json`, jossa tunnus on 12 pientä heksamerkkiä (esim. `secrets.token_hex(6)`). Kirjoittaja tekee ensin väliaikaisen tiedoston, jonka nimi alkaa pisteellä, ja nimeää sen lopuksi. Ajuri lukee vain kelvolliset nimet. Pyynnön oikeuksien pitää olla 0640; ryhmä `aivo-agentit` periytyy kansiosta. Jos kirjoittajan palvelussa on `UMask=0077`, kirjoittaja asettaa oikeudet itse, muuten ajuri ei voi lukea pyyntöä.

```json
{"versio": 1, "teksti": "Tehtävän kuvaus", "liitteet": [{"nimi": "aineisto/a.md", "sisalto": "..."}], "keskustelu": "abc123"}
```

`liitteet` ja `keskustelu` ovat valinnaisia. Tuntematon kenttä, väärä versio, liian pitkä teksti (yli 20 000 merkkiä), yli 50 liitettä tai kelvoton liitteen nimi antavat tuloksen `virhe` ilman mallikutsuja.

### Tuloksen muoto

Kentät järjestyksessä: `versio`, `tunnus`, `keskustelu`, `tila` (`valmis`, `kesken`, `keskeytetty` tai `virhe`), `syy`, `raportti`, `tarkastus` (`arvio` ja `perustelu`), `tiedostot` (polku ja koko), `kutsuja`, `askelia`, `kesto_s`, `kulu_eur`, `kulu_tuntematon`, `mallit`, `rajat`, `loki` ja `valmistui` (UTC).

### Käyttäjät, ryhmät ja kansiot

| Kohde | Omistaja ja ryhmä | Oikeudet | Kuka käyttää |
|---|---|---|---|
| `/var/lib/aivo-agentit` | `aivo-agentti:aivo-agentit` | 0750 | ajuri; ryhmä pääsee alikansioihin |
| `jono/` | `aivo-agentti:aivo-agentit` | 2770 | kirjoittaja (myöhemmin chat) kirjoittaa, ajuri lukee ja siirtää |
| `kasitellyt/`, `tyo/` | `aivo-agentti:aivo-agentti` | 0700 | vain ajuri |
| `tulokset/` | `aivo-agentti:aivo-agentit` | 2750 | ajuri kirjoittaa, ryhmä lukee |
| `openrouter-avain` | `aivo-agentti:aivo-agentti` | 0600 | vain ajuri; chatin avainta ei hyväksytä |
| `/var/lib/claude-jono` | nykyinen omistaja, ryhmä `aivo-kulut` | ryhmälle `rwx` ja sticky-bitti (`t`) | chat ja ajuri |
| kulukirjanpidon kolme tiedostoa | chatin käyttäjä, ryhmä `aivo-kulut` | 0660 | chat ja ajuri |

Kulukirjanpidon moduuli vaatii kirjoitusoikeuden koko kansioon `/var/lib/claude-jono`, ei vain tiedostoihin. Siksi yksikön `ReadWritePaths` sisältää kansion. Sticky-bitin ansiosta ajurin käyttäjä ei voi poistaa, nimetä uudelleen eikä korvata chatin omistamia kulutiedostoja, vaikka se voi kirjoittaa niihin ryhmän kautta.

`aivo-agentti` ei kuulu ryhmiin `aivo-yksityinen`, `aivo-tyokalu` eikä `aivo-tyokalu-socket`. Lisäksi yksikön `InaccessiblePaths` piilottaa kansiot `/var/lib/aivo-yksityinen`, `/var/lib/aivo` ja `/var/lib/aivo-tyokalu`.

### Verkko

`IPAddressAllow` ei sovellu, koska OpenRouterin osoitteet vaihtuvat (CDN). Verkkoa rajaavat nyt kaksi kerrosta: agentilla ei ole verkkotyökalua (rakennetesti), ja ainoa ulospäin menevä kutsu on `openrouter_kulut.kutsu`, jossa ZDR on pakotettu. Nimipohjainen välityspalvelin kolmanneksi kerrokseksi on oma päätöksensä, eikä sitä tehdä tässä.

## Käyttöönotto

Komennot ajetaan kontissa 122 pääkäyttäjänä (`sudo`), ellei toisin mainita. Jokaisen tarkistuksen jälkeen on Odotettu-rivi. Jos tulos poikkeaa, pysähdy äläkä jatka seuraavaan kohtaan.

### 0. Snapshot

Isännällä:

```
pct snapshot 122 ennen-aivo-agentit
pct listsnapshot 122
pct config 122 | grep -E '^(unprivileged|features)'
```

Odotettu: listassa on `ennen-aivo-agentit`. Jos kontti on `unprivileged: 1`, rivillä `features` pitää olla `nesting=1`, koska yksikön eristysasetukset tarvitsevat sitä. Jos se puuttuu, älä lisää sitä tämän ohjeen perusteella, vaan kirjaa tilanne ja pyydä päätös.

### 1. Lähtötilanne

```
systemctl show -p User,WorkingDirectory aivo-chat
ls -l /var/lib/claude-jono/openrouter-kulut.jsonl /var/lib/claude-jono/openrouter-katto.jsonl /var/lib/claude-jono/openrouter-kulut.lock
stat -c '%A %U:%G %n' /var/lib/claude-jono
```

Kirjoita tulokset muistiin peruutusta varten. Odotettu: `User=` on chatin käyttäjä (`aivo-yksityinen` tai `aivo`), ja `WorkingDirectory=` on repon polku (tässä ohjeessa `/opt/agentti-pohja`). Kulutiedostoja voi puuttua; ne luodaan kohdassa 3.

### 2. Käyttäjä, ryhmät ja kansiot

```
sudo groupadd --system aivo-agentit
sudo groupadd --system aivo-kulut
sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --user-group aivo-agentti
sudo usermod -aG aivo-agentit,aivo-kulut aivo-agentti
sudo install -d -m 0750 -o aivo-agentti -g aivo-agentit /var/lib/aivo-agentit
sudo install -d -m 2770 -o aivo-agentti -g aivo-agentit /var/lib/aivo-agentit/jono
sudo install -d -m 2750 -o aivo-agentti -g aivo-agentit /var/lib/aivo-agentit/tulokset
sudo install -d -m 0700 -o aivo-agentti -g aivo-agentti /var/lib/aivo-agentit/tyo /var/lib/aivo-agentit/kasitellyt
id aivo-agentti
sudo ls -la /var/lib/aivo-agentit
```

Odotettu: `id` näyttää ryhmät `aivo-agentti`, `aivo-agentit` ja `aivo-kulut`, mutta ei ryhmiä `aivo-yksityinen`, `aivo-tyokalu` tai `aivo-tyokalu-socket`. Listauksessa on `drwxrws---` (jono), `drwxr-s---` (tulokset) ja `drwx------` (tyo, kasitellyt).

### 3. Kulukirjanpidon ryhmäoikeus

Agentit ja chat käyttävät samaa kirjanpitoa ja samaa päiväkattoa. Kulumoduuli vaatii kirjoitusoikeuden kansioon, joten kansio annetaan ryhmälle `aivo-kulut` ja siihen lisätään sticky-bitti. Tiedostot luodaan valmiiksi chatin käyttäjän omistamina, jotta kumpikaan palvelu ei luo niitä omilla oikeuksillaan. `CHAT` on kohdan 1 käyttäjä.

```
CHAT=$(systemctl show -p User --value aivo-chat); [ -n "$CHAT" ] && echo "CHAT=$CHAT" || echo "CHAT PUUTTUU: pysähdy"
sudo usermod -aG aivo-kulut "$CHAT"
sudo chgrp aivo-kulut /var/lib/claude-jono
sudo chmod g+rwx,+t /var/lib/claude-jono
cd /var/lib/claude-jono
for f in openrouter-kulut.jsonl openrouter-katto.jsonl openrouter-kulut.lock; do
  [ -e "$f" ] || sudo install -m 0660 -o "$CHAT" -g aivo-kulut /dev/null "$f"
  sudo chgrp aivo-kulut "$f" && sudo chmod 0660 "$f"
done
stat -c '%A %U:%G %n' /var/lib/claude-jono openrouter-kulut.jsonl openrouter-katto.jsonl openrouter-kulut.lock
sudo -u aivo-agentti test -w /var/lib/claude-jono && sudo -u aivo-agentti test -w openrouter-kulut.jsonl && echo KIRJOITUS-OK
sudo systemctl restart aivo-chat
```

Odotettu: rivi `CHAT=<käyttäjä>`. Kansion oikeuksien lopussa on `t` (esim. `drwxrwx--T` tai `drwxrwx--t`), ja ryhmä on `aivo-kulut`. Kaikilla kolmella tiedostolla on `-rw-rw---- <chat-käyttäjä>:aivo-kulut`. Viimeinen tarkistusrivi on `KIRJOITUS-OK`. Chat käynnistetään uudelleen, jotta uusi ryhmä tulee voimaan, jos chat ei omista kansiota. Kokeile chatin yksityistä tilaa yhdellä viestillä: vastauksen pitää tulla kuten ennenkin.

### 4. Koodi ja avaintiedosto

Päivitä repo kuten chatin päivityksessä, kun muutos on mainissa. Tarkista, että ajuri on mukana ja ajurin käyttäjä pääsee lukemaan koodin:

```
sudo -u aivo-agentti env PYTHONPATH=/opt/agentti-pohja /usr/bin/python3 -c "import aivo.agentti_ajuri; print('TUONTI-OK')"
```

Odotettu: `TUONTI-OK`.

Kirjoita oma OpenRouter-avain itse. Avain ei saa olla sama tiedosto kuin chatin avain, ja sen kannattaa olla oma avain, jotta agenttien kulut näkyvät OpenRouterissa erikseen. Ohje ei tulosta avainta.

```
sudo install -m 0600 -o aivo-agentti -g aivo-agentti /dev/null /var/lib/aivo-agentit/openrouter-avain
sudo nano /var/lib/aivo-agentit/openrouter-avain
sudo stat -c '%a %U %s' /var/lib/aivo-agentit/openrouter-avain
```

Odotettu: `600 aivo-agentti` ja koko yli 0.

### 5. Ennakkotarkistus

```
cd /opt/agentti-pohja
sudo -u aivo-agentti env PYTHONPATH=/opt/agentti-pohja /usr/bin/python3 -m aivo.agentti_ajuri tarkista --roolit qwen/qwen3-235b-a22b-2507
```

Odotettu: viimeinen rivi on `OK`. Tarkistus kattaa kansiot, kulukirjanpidon ja mallin. Jos riveillä on `VIRHE`, korjaa oikeudet kohdan 2 tai 3 mukaan. Palvelu tekee saman tarkistuksen käynnistyessään, ja virheen sattuessa se ei aja tehtäviä. Käytä samaa avointa mallia kuin chatissa; mallin pitää olla listalla `AVOIMET_MALLIT`.

### 6. Asennus

```
sudo cp /opt/agentti-pohja/systemd/aivo-agentit.service.mall /etc/systemd/system/aivo-agentit.service
sudo systemd-analyze verify /etc/systemd/system/aivo-agentit.service
sudo systemctl daemon-reload
sudo systemctl enable --now aivo-agentit
```

Jos repo ei ole polussa `/opt/agentti-pohja` tai Python ei ole polussa `/usr/bin/python3`, muuta rivit `WorkingDirectory`, `Environment` ja `ExecStart` ennen `daemon-reload`-komentoa. Malli vaihdetaan `ExecStart`-rivin valitsimella `--roolit`. Yhden mallin sijaan voi antaa kaikki kolme roolia: `--roolit suunnittelija:m1,tekija:m2,tarkastaja:m3`.

Odotettu: `systemd-analyze verify` ei tulosta yhtään riviä, jossa mainitaan `aivo-agentit.service`. Ajastinta ei ole, joten NEXT-aikaa ei tarkisteta: palvelu on käynnissä jatkuvasti.

### 7. Tarkistus

```
systemctl is-active aivo-agentit
journalctl -u aivo-agentit -n 20 --no-pager
systemctl show -p User,SupplementaryGroups,InaccessiblePaths,ReadWritePaths aivo-agentit
sudo -u aivo-agentti ls /var/lib/aivo-yksityinen/chat
sudo -u aivo-tyokalu ls /var/lib/aivo-agentit/tyo
sudo systemd-analyze security aivo-agentit --no-pager | tail -n 1
```

Odotettu:
- `active`.
- Lokissa ei ole rivejä `kansiovirhe`, `asetusvirhe` eikä `status=226/NAMESPACE`.
- `User=aivo-agentti` ja `SupplementaryGroups=aivo-agentit aivo-kulut`.
- Kumpikin `ls` antaa `Permission denied`. Jos kansiota `/var/lib/aivo-yksityinen/chat` tai käyttäjää `aivo-tyokalu` ei ole, tulos on `No such file or directory` tai `unknown user`, mikä on myös hyväksyttävä.
- `systemd-analyze security` antaa pisteet ja arvion. Kirjaa ne raporttiin. Pienempi on parempi; arvio `OK` tai `MEDIUM` on odotettu.

Jos palvelu kaatuu tilaan `226/NAMESPACE`, kontti ei tue jotain eristysasetusta. Älä poista asetuksia itse, vaan kirjaa lokin rivi ja pyydä korjausta.

### 8. Käytöstesti

Pieni tehtävä oikealla mallilla. Kulu on muutamia senttejä, ja se kirjautuu yhteiseen päiväkattoon.

```
T=$(python3 -c "import secrets; print(secrets.token_hex(6))")
echo '{"versio": 1, "teksti": "Kirjoita tiedosto tervehdys.md, jossa on yksi rivi: hei."}' | sudo tee /var/lib/aivo-agentit/jono/.$T.tmp >/dev/null
sudo chmod 0640 /var/lib/aivo-agentit/jono/.$T.tmp
sudo mv /var/lib/aivo-agentit/jono/.$T.tmp /var/lib/aivo-agentit/jono/$T.json
```

Odota noin minuutti ja tarkista:

```
journalctl -u aivo-agentit -n 5 --no-pager
sudo python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['tila'], d['kutsuja'], d['kulu_eur'], [f['polku'] for f in d['tiedostot']])" /var/lib/aivo-agentit/tulokset/$T.json
sudo stat -c '%a %G' /var/lib/aivo-agentit/tulokset/$T.json
sudo tail -n 4 /var/lib/claude-jono/openrouter-kulut.jsonl
```

Odotettu:
- Lokissa on rivi `aivo-agentit: tunnus=<T> tila=valmis kutsuja=<n> ...` eikä tehtävän tekstiä.
- Tulosrivi on esimerkiksi `valmis 4 0.002 ['_suunnitelma.md', 'tervehdys.md']`. Tila `kesken` tarkoittaa, että tarkastaja ei hyväksynyt raporttia. Se on toimiva ajo mutta heikko vastaus.
- `640 aivo-agentit`.
- Kulukirjanpidossa on rivejä tehtävätunnisteilla `aivo-agentti:suunnittelija`, `aivo-agentti:tekija` ja `aivo-agentti:tarkastaja`.

Jos tulos on `virhe` ja syy mainitsee avaimen, tarkista kohta 4. Jos syy on `paivakatto tai kulukirjanpito`, tarkista kohta 3 tai päivän kulut.

### 9. Peruutus

```
sudo systemctl disable --now aivo-agentit
sudo rm /etc/systemd/system/aivo-agentit.service
sudo systemctl daemon-reload
```

Palauta kansion `/var/lib/claude-jono` ja kulutiedostojen ryhmä ja oikeudet kohdassa 1 kirjatuiksi (esim. `sudo chgrp <vanha ryhmä> <polku>`, `sudo chmod 0644 <tiedosto>` ja kansiolle kirjattu tila, esim. `sudo chmod 0755 /var/lib/claude-jono`). Käyttäjä, ryhmät ja `/var/lib/aivo-agentit` jäävät paikalleen, koska niissä voi olla tuloksia. Niiden poisto on oma päätöksensä. Koko kontin voi palauttaa isännällä komennolla `pct rollback 122 ennen-aivo-agentit`, mutta se kumoaa myös kaikki muut snapshotin jälkeiset muutokset.

## Testit

`python3 -m unittest aivo.test_agentti_ajuri` (kansioiden oikeudet ja polut, jonosta luku, yksi tehtävä kerrallaan, aikaraja, tulostiedoston muoto, yksikkömalli ja rakennetesti). Testit eivät käytä verkkoa.
