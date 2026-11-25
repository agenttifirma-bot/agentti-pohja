# Aivon hakuvälittäjä: rajapinta ja käyttöönotto

Hakuvälittäjä on hakukontin (CT123) ainoa kontin ulkopuolelle näkyvä palvelu. Se ottaa vastaan hakuja ja sivupyyntöjä vain kontilta 122, tekee ne Torin kautta ja palauttaa tulokset siivottuna tekstinä. Koodi on vain Pythonin vakiokirjastoa.

Pohja: suunnitelma `claude-jono/suunnitelmat/aivo-verkkohaku.md` (kohdat 3.3, 4, 8 ja 10, PR 2) ja Tonyn päätökset A1101 (25.11.2026). Hakukontin asennus on ohjeessa `docs/aivo-hakukontti.md` (PR 1).

**RAJATTU:** palvelu avaa yhteyksiä verkkoon (Torin kautta). Tony ottaa sen käyttöön itse.

## Tiedostot

| Tiedosto | Asennuspaikka hakukontissa | Tarkoitus |
|---|---|---|
| `isanta/hakukontti/hakuvalittaja.py` | `/usr/local/lib/hakukontti/hakuvalittaja.py` | Palvelu, käynnistystarkistus (`--tarkista`) ja koekutsu (`--koe`) |
| `isanta/hakukontti/aivo-haku.service` | `/etc/systemd/system/aivo-haku.service` | systemd-yksikkö tiukoin suojin |
| `isanta/hakukontti/test_hakuvalittaja.py` | ei asenneta | Testit valepalvelimella ilman oikeaa verkkoa |

## Rajapinta

Kuuntelu ja asiakkaat: välittäjä kuuntelee vain asetuksessa annetussa osoitteessa (`--kuuntele IP:PORTTI`, kontin oma sisäverkon tai tailnet-osoite). Osoitteet `0.0.0.0` ja `::` sekä nimet hylätään, eikä palvelu käynnisty ilman asetusta. Yhteydet muista kuin sallituista osoitteista (`--salli`, Aivon kontin osoite) suljetaan ilman vastausta ennen kuin pyyntöä luetaan. Lokiin kirjataan rivi `hylatty_osoite` ilman asiakkaan osoitetta. Tämä on toinen kerros palomuurin (nftables ja Proxmox) rinnalla: rajaus pysyy, vaikka palomuurisääntö puuttuisi. Osoitteet ovat tiedostossa `/etc/aivo-haku/osoitteet.env` (`HAKU_KUUNTELE`, `HAKU_SALLITUT`), joka kirjoitetaan asennuksessa komennoilla. Repossa ei ole osoitteita.

Tunnistus: otsake `Authorization: Bearer <avain>`. Avain on tiedostossa `/etc/aivo-haku/avain` (PR 1:n kohta 9). Vertailu on vakioaikainen (`hmac.compare_digest`). Pyynnön runko on JSON, enintään 8 kt.

- `POST /haku {lauseke, reitti, tunnus}` → `{tulokset: [{otsikko, url, ote, moottori}], estaneet: [moottori, ...]}`
  - Enintään 10 tulosta. Vain `https://`-osoitteet, jotka läpäisevät samat osoitesäännöt kuin `/sivu`. Ote on enintään 300 merkkiä ja otsikko 200 merkkiä.
  - `estaneet` on lista moottoreista, jotka eivät vastanneet (esim. Tor-esto). Sitä käytetään VPN-mittariin.
  - Ennen jokaista hakua välittäjä pyytää Torilta uuden piirin (`SIGNAL NEWNYM`), koska SearXNG ei lähetä SOCKS-tunnusta. Tor toteuttaa signaalin enintään noin 10 sekunnin välein, joten nopeasti peräkkäiset haut voivat jakaa piirin.
- `POST /sivu {url, reitti, tunnus}` → `{teksti, merkkeja, katkaistu, sha256, sisaltotyyppi, tila, url, ohjauksia}`
  - `sha256` lasketaan raakadatasta, `url` on lopullinen osoite ohjausten jälkeen.
  - SOCKS-käyttäjänimi on `tunnus-<prosessin satunnaisosa>-<järjestysnumero>`, joten jokainen sivuhaku saa oman Tor-piirin (`IsolateSOCKSAuth`), eikä uudelleenkäynnistys kierrätä vanhoja nimiä. Nimi lähetetään Torille (socks5h), eikä hakukontti ratkaise sitä itse.
- `reitti`: `tor` (oletus). `vpn` palauttaa virheen `reitti_ei_kaytossa`, kunnes VPN-reitti on toteutettu (PR 4).
- `tunnus`: satunnainen tehtävätunnus, 8–64 merkkiä `[A-Za-z0-9_-]`. Se ei saa sisältää tehtävän tekstiä.

Rajoja ei ole tehtävää kohden (A1101). Tekniset rajat ovat koodin vakioita, ja konstruktorin arvot voivat vain pienentää niitä.

| Raja | Arvo |
|---|---|
| Protokolla ja portti | vain `https`, portti 443 |
| Uudelleenohjaukset | enintään 3, jokainen tarkistetaan samoin säännöin |
| Raakadata | enintään 2 Mt (ilmoitettu suurempi koko hylätään, virta katkaistaan rajalla) |
| Aikaraja | 30 s koko sivuhaulle (ajastin katkaisee myös hitaan lähettäjän) ja haulle |
| Sisältötyypit | `text/html`, `application/xhtml+xml`, `text/plain` (ei pakkausta) |
| Teksti | enintään 30 000 merkkiä |
| Samanaikaiset pyynnöt | 4 (muuten `kiireinen`) |

Osoitesäännöt: hylätään literaali-IP:t, jotka eivät ole julkisia (yksityiset, silmukka, linkkipaikalliset, CGNAT/tailnet, monilähetys, myös IPv4-mapatut IPv6-osoitteet), numeromuotoiset nimet (esim. `127.1`, `2130706433`, `0x7f.0.0.1`), `localhost`, yksiosaiset nimet, päätteet `.onion`, `.local`, `.internal`, `.lan`, `.home.arpa`, `.ts.net` ja muut paikalliset, käyttäjätiedot (`user@`) ja ohjausmerkit. Lisäksi Torin ulostulosolmu ei yhdistä yksityisiin osoitteisiin, ja hakukontin nftables estää Toria pääsemästä lähiverkkoihin.

Siivous ennen palautusta: sisältötyyppi luetaan raakaotsakkeesta (puuttuva otsake hylätään), ja merkistö valitaan sallitulistasta (muuten UTF-8). HTML jäsennetään (`html.parser`). Pois jäävät `script`, `style`, `noscript`, `iframe`, `svg`, `form`, `nav`, `template` ja vastaavat sekä piilotetut elementit (`hidden`, `aria-hidden="true"`, `display:none`, `visibility:hidden`). Teksti normalisoidaan (NFKC), näkymättömät ohjaus- ja muotoilumerkit muutetaan näkyviksi (`​`), ja merkkijonot `[[`, `]]`, `<<<` ja `>>>` poistetaan. Siksi sivu ei voi tuottaa `[[EHDOTUS]]`-lohkoja eikä sulkea DATA-kehystä. Piilotetun tekstin tunnistus on paras mahdollinen yritys, ei takuu (esim. CSS-luokilla tai `opacity:0`:lla piilotettu teksti jää jäljelle), joten sivun teksti on aina dataa eikä ohjeita. Teksti katkaistaan ennen normalisointia, joten muistin ja ajan käyttö pysyy rajattuna.

Hakulausekkeen mekaaniset salaisuustyypit estetään aina (A1096): avaimet ja tokenit, henkilötunnus, IBAN, ei-julkiset IP-osoitteet ja tailnet-nimet. Vastaus on `lauseke_estetty` ja tyyppi, ei osumaa. Sama tarkistus (ilman yleistä pitkän merkkijonon sääntöä) koskee sivun osoitetta. Tämä on toinen kerros: ensisijainen tarkistus ja vuotovartija ovat kontissa 122 (PR 3).

Virhekoodit (`{"virhe": koodi}`): `tunnistus` 401, `tunnus_ei_kelpaa`, `lauseke_*`, `url_ei_kelpaa`, `reitti_*` 400, `vain_https`, `portti_ei_sallittu`, `osoite_ei_sallittu`, `url_ei_sallittu`, `url_estetty` 403, `pyynto_liian_suuri` 413, `vain_json` 415, `liian_suuri`, `liian_monta_ohjausta`, `ohjaus_ilman_kohdetta`, `sisaltotyyppi_ei_sallittu`, `pakkaus_ei_tuettu`, `http_tila` (+ `tila`), `tls_virhe`, `sivu_ei_saatavilla`, `searxng_virhe` 502, `reitti_poikki`, `kiireinen` 503 ja `aikaraja` 504.

**Kill switch sovellustasolla:** ennen jokaista pyyntöä välittäjä tunnistautuu Torin hallintasokettiin (`/run/tor/control`, eväste `/run/tor/control.authcookie`, ryhmä `debian-tor`) ja vaatii `status/circuit-established=1`. Tarkistus tehdään myös jokaisen uudelleenohjauksen jälkeen. SearXNG:n vastauksen uudelleenohjauksia ei seurata. Jos tarkistus epäonnistuu tai SOCKS-portti ei vastaa, vastaus on `reitti_poikki`. Suoraa yhteyttä ei avata missään tilanteessa. Kielletty osoite tai estetty lauseke hylätään jo ennen reitin tarkistusta, joten se ei avaa yhteyttä edes Toriin.

**Lokit:** journaldiin yksi JSON-rivi pyyntöä kohden: `toiminto`, `tunnus`, `tila`, `virhe`, `kesto_ms` ja `tavuja`. Aika tulee journaldista. Lausekkeita, osoitteita eikä sisältöä ei kirjata. Säilytys on 30 päivää (PR 1:n journald-asetus, A1101).

## systemd-yksikkö

`aivo-haku.service` ajaa palvelun käyttäjänä `aivo-haku` (lisäryhmä `debian-tor` hallintasokettia varten). Osoitteet tulevat tiedostosta `EnvironmentFile=/etc/aivo-haku/osoitteet.env` (pakollinen, ilman `-`-etuliitettä), ja käynnistystarkistus saa samat `--kuuntele`- ja `--salli`-arvot kuin palvelu.

Miksi `debian-tor`-ryhmä: välittäjä tarkistaa ennen jokaista pyyntöä Torin hallintasoketista, että piiri on ylhäällä, ja pyytää haulle uuden piirin (`SIGNAL NEWNYM`). Socket `/run/tor/control` ja eväste ovat Debianissa vain ryhmän `debian-tor` luettavissa. Ryhmä ei anna Torin verkkooikeuksia, koska nftables tunnistaa käyttäjän (`skuid`), ei ryhmää: `aivo-haku` pääsee edelleen vain silmukan portteihin 8888 ja 9050. Riski on se, että hallintasoketin kautta voi muuttaa Torin asetuksia. Palomuuri rajaa silti Torin ulosmenon internetiin ilman yksityisiä osoitteita ja sisääntulon porttiin 8890 kontista 122. Vaihtoehdot (TCP-hallintaportti salasanalla tai reitin tarkistuksen poisto) olisivat heikompia: TCP-portti näkyisi kaikille kontin käyttäjille, ja ilman tarkistusta sovellustason kill switch puuttuisi. Suojat: `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateDevices`, tyhjä `CapabilityBoundingSet`, `RestrictAddressFamilies=AF_INET AF_UNIX`, `SystemCallFilter=@system-service`, `MemoryDenyWriteExecute`, `RestrictSUIDSGID`, `RestrictNamespaces`, `UMask=0077`, `MemoryMax=200M` ja `TasksMax=64`.

`PrivateDevices`, `ProtectSystem` ja `ProtectHome` tarvitsevat mount-nimiavaruuden. Hakukontti saa `nesting=1`:n PR 1:n ohjeessa. Jos palvelu kaatuu virheeseen `226/NAMESPACE`, kirjaa se raporttiin äläkä poista suojia ilman päätöstä.

Kontin 122 käyttöönoton opit (virheloki 25.11.2026) on otettu huomioon:
- Ei tmpfs:ää sticky-bitillä: yksikössä ei ole `PrivateTmp`- eikä `TemporaryFileSystem`-asetusta. Palvelu ei kirjoita tiedostoja lainkaan, joten koko tiedostojärjestelmä on sille vain luku -tilassa.
- Ei setgid-chmodia: yksikkö ei muuta oikeuksia, eikä ohje käytä setgid-bittejä (`RestrictSUIDSGID` estäisi ne).
- Käynnistystarkistus (`ExecStartPre=... --tarkista`) ajetaan samana käyttäjänä ja samassa hiekkalaatikossa kuin palvelu. Se avaa avaimen ja evästeen samalla funktiolla ja samoilla lipuilla (`O_RDONLY|O_NOFOLLOW|O_CLOEXEC`) kuin palvelu. `os.access`-tarkistusta ei käytetä. Tarkistus ei vaadi valmista Tor-piiriä, joten käynnistys ei kaadu, vaikka Tor on vielä muodostamassa yhteyttä.
- Kontin sisällä ei ajeta komentoja `systemd-run`-kääreellä, ja jokaisella tarkistuksella on näkyvä Odotettu-tulos.

## Käyttöönotto (Tony, isännällä)

Esiehto: hakukontti on asennettu ohjeen `docs/aivo-hakukontti.md` mukaan (kohdat 0–9), ja tämä muutos on yhdistetty päähaaraan ja päivittynyt agentscope-kontin ajurikloonin hakemistoon `/opt/agentti-pohja`. Aja komennot yksi kerrallaan. Jos tulos poikkeaa Odotettu-rivistä tai tuloste on tyhjä, pysähdy.

### 1. Esitarkistukset ja snapshot

```bash
pct exec 123 -- systemctl is-active tor@default searxng
```
Odotettu: kaksi riviä `active`.

```bash
pct exec 123 -- id -nG aivo-haku
```
Odotettu: `aivo-haku debian-tor`.

```bash
pct exec 123 -- stat -c '%a %U:%G %s' /etc/aivo-haku/avain
```
Odotettu: `640 root:aivo-haku 44` (koko tavuina, ei sisältöä).

```bash
pct exec 123 -- python3 -c 'import sys; print(sys.version_info >= (3, 10))'
```
Odotettu: `True`.

```bash
pct snapshot 123 ennen-hakuvalittaja && pct listsnapshot 123 | grep -c ennen-hakuvalittaja
```
Odotettu: `1`.

### 2. Tiedostot

```bash
pct exec 115 -- git -C /opt/agentti-pohja log -1 --format='%h %s' -- isanta/hakukontti/hakuvalittaja.py
```
Odotettu: commit, jonka viesti mainitsee hakuvälittäjän. Tyhjä tuloste: muutos ei ole vielä ajurikloonissa, pysähdy.

```bash
mkdir -p /root/hakukontti && for f in hakuvalittaja.py aivo-haku.service; do pct pull 115 "/opt/agentti-pohja/isanta/hakukontti/$f" "/root/hakukontti/$f" || echo "PUUTTUU $f"; done; ls /root/hakukontti | grep -c -E '^(hakuvalittaja\.py|aivo-haku\.service)$'
```
Odotettu: `2`, ei yhtään `PUUTTUU`-riviä.

```bash
pct exec 123 -- install -d -m 0755 /usr/local/lib/hakukontti && pct push 123 /root/hakukontti/hakuvalittaja.py /usr/local/lib/hakukontti/hakuvalittaja.py --perms 0644 && pct push 123 /root/hakukontti/aivo-haku.service /etc/systemd/system/aivo-haku.service --perms 0644 && pct exec 123 -- stat -c '%a %U %n' /usr/local/lib/hakukontti/hakuvalittaja.py /etc/systemd/system/aivo-haku.service
```
Odotettu: kaksi riviä, joissa `644 root` ja tiedoston polku.

### 3. Osoitteet

Välittäjä kuuntelee vain hakukontin omassa osoitteessa ja palvelee vain kontin 122 osoitetta. Osoitteet luetaan konttien asetuksista.

```bash
IP122=$(pct config 122 | sed -n 's/^net0:.*ip=\([0-9.]*\)\/.*/\1/p'); echo "$IP122"
```
Odotettu: yksi IPv4-osoite (kontti 122). Tyhjä tuloste: pysähdy.

```bash
IP123=$(pct config 123 | sed -n 's/^net0:.*ip=\([0-9.]*\)\/.*/\1/p'); echo "$IP123"
```
Odotettu: yksi IPv4-osoite (hakukontti). Tyhjä tuloste: pysähdy.

```bash
printf 'HAKU_KUUNTELE=%s:8890\nHAKU_SALLITUT=%s\n' "$IP123" "$IP122" > /root/hakukontti/osoitteet.env && pct push 123 /root/hakukontti/osoitteet.env /etc/aivo-haku/osoitteet.env --perms 0644 && pct exec 123 -- cat /etc/aivo-haku/osoitteet.env
```
Odotettu: kaksi riviä, `HAKU_KUUNTELE=` hakukontin osoitteella ja portilla 8890 sekä `HAKU_SALLITUT=` kontin 122 osoitteella. Tiedostossa ei ole salaisuuksia.

### 4. Käynnistystarkistus ja palvelu

Käynnistystarkistus palvelun käyttäjänä (ilman systemd:tä) samoilla osoitteilla kuin palvelu:

```bash
pct exec 123 -- sh -c 'set -a; . /etc/aivo-haku/osoitteet.env; set +a; setpriv --reuid=aivo-haku --regid=aivo-haku --init-groups python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --kuuntele "$HAKU_KUUNTELE" --salli "$HAKU_SALLITUT" --tarkista'
```
Odotettu: `TARKISTUS: OK`. Virhetilanteessa tuloste on muotoa `TARKISTUS: VIRHE <vaihe> <tyyppi>` (vaihe `osoitteet`, `avain`, `evaste` tai `hallinta`).

```bash
pct exec 123 -- systemd-analyze verify /etc/systemd/system/aivo-haku.service; echo "paluuarvo $?"
```
Odotettu: `paluuarvo 0`. Varoitukset muista yksiköistä voi ohittaa, mutta `aivo-haku.service`-alkuiset rivit kirjataan raporttiin.

Hakuvälittäjä vaatii palomuurin (`Requires=nftables.service`): jos sääntöjen lataus epäonnistuu, palvelu ei käynnisty, ja palomuurin pysäytys pysäyttää sen. Tarkista ennen käynnistystä, että palomuuri on myös itsenäisesti käytössä kontin käynnistyessä.

```bash
pct exec 123 -- systemctl is-enabled nftables
```
Odotettu: `enabled`. Jos tulos on muu, pysähdy. `Requires=` käynnistää palomuurin palvelun mukana, mutta Tor ja muut palvelut eivät vaadi sitä, joten ilman `enabled`-tilaa kontti voi käynnistyä ilman kill switchiä. Huomaa myös: jos säännöt poistetaan käsin (`nft flush ruleset`), `nftables.service` pysyy aktiivisena, eikä systemd pysäytä palvelua. Sääntöjä ei siksi poisteta käsin palveluiden ollessa käynnissä.

```bash
pct exec 123 -- systemctl daemon-reload && pct exec 123 -- systemctl enable --now aivo-haku && pct exec 123 -- systemctl is-active aivo-haku
```
Odotettu: `active`. Jos tulos on `failed` tai `activating`, aja seuraava komento ja pysähdy.

```bash
pct exec 123 -- journalctl -u aivo-haku -n 5 --no-pager -o cat
```
Odotettu: rivi `TARKISTUS: OK` (ExecStartPre samassa hiekkalaatikossa) ja JSON-rivi, jossa `"toiminto": "kaynnistys"`.

```bash
pct exec 123 -- ss -ltn 'sport = :8890'
```
Odotettu: yksi `LISTEN`-rivi, jonka osoite on hakukontin oma osoite ja portti 8890 (sama kuin `$IP123`). Jos osoite on `0.0.0.0` tai `*`, pysähdy.

```bash
pct exec 123 -- systemd-analyze security aivo-haku --no-pager | tail -n 1
```
Odotettu: rivi `→ Overall exposure level for aivo-haku.service: <luku> ...`. Kirjaa luku raporttiin. Jos luku on yli 5,0, pysähdy.

### 5. Käyttöönoton testit

Koekutsut (`--koe`) ajetaan kontissa rootina samassa prosessissa kuin välittäjän koodi, ei HTTP:n kautta, koska palvelu ei vastaa kontin omasta osoitteesta. Ne käyttävät samaa SearXNG:tä, Tor-porttia ja hallintasokettia kuin palvelu. Ne tulostavat vain tilan ja määrät, eivät sisältöä eivätkä avainta. Lausekkeet ovat neutraaleja.

Testi 1. Haku Torin kautta.

```bash
pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe haku "open source metasearch engine"
```
Odotettu: `KOE haku: tila 200, tuloksia <n>, estaneet <m>`, jossa n on vähintään 1.

Testi 2. Sivu Torin kautta.

```bash
pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe sivu https://en.wikipedia.org/wiki/Tor_(network)
```
Odotettu: `KOE sivu: tila 200, http 200, merkkeja <n>, ...`, jossa n on yli 1000.

Testi 3. Salaamaton ja sisäinen osoite hylätään.

```bash
pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe sivu http://example.com/
```
Odotettu: `KOE sivu: tila 403, virhe vain_https`.

```bash
pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe sivu https://127.0.0.1/
```
Odotettu: `KOE sivu: tila 403, virhe osoite_ei_sallittu`.

Testi 4. Kill switch: Tor pysäytetään, ja haku epäonnistuu.

```bash
pct exec 123 -- systemctl stop tor@default && pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe haku "open source metasearch engine"
```
Odotettu: `KOE haku: tila 503, virhe reitti_poikki`.

```bash
pct exec 123 -- python3 -I /usr/local/lib/hakukontti/hakuvalittaja.py --koe sivu https://en.wikipedia.org/
```
Odotettu: `KOE sivu: tila 503, virhe reitti_poikki`.

```bash
pct exec 123 -- systemctl start tor@default && pct exec 123 -- systemctl is-active tor@default
```
Odotettu: `active`. Toista sen jälkeen testi 1, kunnes tulos on `tila 200` (Tor muodostaa piirin yleensä alle minuutissa). Jos tulos ei ole 200 kahden minuutin kuluttua, pysähdy.

Testi 5. Hakuvälittäjä vastaa kontista 122. Pyyntö ilman avainta riittää: vastaus `401` osoittaa, että yhteys ja osoiterajaus päästävät kontin 122 läpi. Avainta ei kopioida konttiin 122 tässä vaiheessa.

```bash
pct exec 122 -- python3 -c 'import sys, http.client as h; c = h.HTTPConnection(sys.argv[1], 8890, timeout=10); c.request("POST", "/haku", b"{}"); print(c.getresponse().status)' "$IP123"
```
Odotettu: `401`.

Testi 6. Hakuvälittäjä ei vastaa muualta kuin kontista 122, ei edes kontin omasta osoitteesta. Kontin root pääsee palomuurin läpi silmukan kautta, joten tämä testaa sovelluksen oman rajauksen.

```bash
pct exec 123 -- curl -sS -m 10 -o /dev/null -X POST "http://$IP123:8890/haku"; echo "paluuarvo $?"
```
Odotettu: `Empty reply from server` ja paluuarvo `52` tai `Connection reset by peer` ja paluuarvo `56`. Kumpikin tarkoittaa, että välittäjä sulki yhteyden vastaamatta. Paluuarvo `0` tai HTTP-vastaus tarkoittaa, että rajaus ei toimi: pysähdy.

Testi 7. Kontista 115 yhteys porttiin 8890 estyy palomuurissa.

```bash
pct exec 115 -- curl -sS -m 5 "http://$IP123:8890/"; echo "paluuarvo $?"
```
Odotettu: paluuarvo `28` (aikakatkaisu, paketit hylätään) tai `7`.

Testi 8. Lokeissa ei ole lausekkeita eikä osoitteita.

```bash
pct exec 123 -- sh -c 'journalctl -u aivo-haku --since "-30min" -o cat | grep -c -i -E "metasearch|wikipedia|example\.com"'
```
Odotettu: `0`.

```bash
pct exec 123 -- sh -c 'journalctl -u aivo-haku --since "-30min" -o cat | grep -c -e "\"toiminto\": \"hylatty_osoite\"" -e "\"virhe\": \"tunnistus\""'
```
Odotettu: vähintään `2` (testin 5 hylätty tunnistus ja testin 6 hylätty osoite). Rivit eivät sisällä asiakkaan osoitetta.

### Palautus

Jos jokin kohta epäonnistuu: `pct exec 123 -- systemctl disable --now aivo-haku` ja tarvittaessa `pct rollback 123 ennen-hakuvalittaja` (Tonyn päätös). Kontin 122 asetuksiin tämä ohje ei koske. Avain kopioidaan konttiin 122 vasta PR 3:n käyttöönotossa.

## Testit

```bash
python3 -m unittest isanta.hakukontti.test_hakuvalittaja -v
```
Odotettu: lopussa `OK` (osa TLS-testeistä voidaan ohittaa, jos `openssl` puuttuu).

Testit käyttävät valepalvelinta, vale-SOCKS5-palvelinta ja vale-Torin hallintasokettia silmukassa. Oikeaa verkkoa ei käytetä. Katetut tapaukset: kuunteluosoite (ei `0.0.0.0`, `::` eikä nimeä, asetus pakollinen), asiakasrajaus (muu osoite suljetaan ennen pyynnön lukemista, sallittu palvellaan, IPv4-mapattu osoite), tunnistus, SSRF-yritykset (sisäverkko, silmukka, linkkipaikallinen, CGNAT, IPv6, numeromuodot, käyttäjätiedot, väärät portit ja protokollat), `http://`, liian iso sivu (ilmoitettu ja virta), uudelleenohjausketju (3 sallitaan, 4 ei, ohjaus sisäverkkoon, silmukkaan tai `http://`:hen hylätään), injektiosivu (skriptit, piilotetut elementit, `[[ ]]`, `<<< >>>`, näkymättömät merkit), reitti poikki (ei piiriä, hallintasoketti puuttuu, väärä eväste, SOCKS-portti kiinni), piirin eristys ja socks5h, aikaraja, salaisuustyyppien esto, lokien sisällöttömyys, käynnistystarkistus (sama avaus, `O_NOFOLLOW`) ja yksikkötiedoston suojat. Jos `openssl` on asennettu, testit tarkistavat myös, että oletus-TLS hylkää itse allekirjoitetun ja väärän nimen varmenteen.
