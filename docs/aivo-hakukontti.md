# Aivon hakukontti: asennusohje (SearXNG + Tor + kill switch)

Tämä ohje asentaa erillisen hakukontin (CT123), jossa pyörivät SearXNG ja Tor. Kontissa ei ole yksityistä dataa. Myöhemmin (PR 2) samaan konttiin tulee hakuvälittäjä, joka on ainoa kontin ulkopuolelle näkyvä palvelu ja vain kontille 122.

Pohja: suunnitelma `claude-jono/suunnitelmat/aivo-verkkohaku.md` (kohdat 2, 3 ja 10) ja Tonyn päätökset A1101 (25.11.2026).

**RAJATTU:** ohje luo uuden kontin, uuden ulosmenoreitin (Tor) ja palomuurisäännöt. Tony tekee asennuksen itse.

## Mitä tiedostoja ohje käyttää

Pohjat ovat hakemistossa `isanta/hakukontti/`:

| Tiedosto | Asennuspaikka hakukontissa | Tarkoitus |
|---|---|---|
| `torrc` | `/etc/tor/torrc` | Tor pelkkänä asiakkaana, SOCKS vain silmukkaosoitteeseen, piirien eristys |
| `nftables.conf` | `/etc/nftables.conf` | Palomuuri ja kill switch käyttäjäkohtaisesti |
| `searxng-settings.yml` | `/etc/searxng/settings.yml` | SearXNG vain silmukkaosoitteeseen, ulosmeno `socks5h`:lla Torin kautta |
| `searxng.service` | `/etc/systemd/system/searxng.service` | SearXNG:n systemd-yksikkö kovennuksineen |
| `journald-hakukontti.conf` | `/etc/systemd/journald.conf.d/hakukontti.conf` | Lokien säilytys 30 päivää |
| `mittaa_moottorit.py` | `/usr/local/lib/hakukontti/mittaa_moottorit.py` | Moottorien esto- ja tulosmittaus Torin kautta |

Osoitteita ei ole repossa. Ohje selvittää ne komennoilla ja kirjoittaa ne tiedostoihin isännällä.

## Periaatteet

- **Kill switch:** jos Tor ei ole ylhäällä, haku epäonnistuu. Käyttäjät `searxng`, `aivo-haku` ja `_apt` pääsevät vain silmukkaosoitteen Tor-porttiin. Vain `debian-tor` saa ottaa yhteyden internetiin, ja vain TCP:llä, koska Tor ei tarvitse UDP:tä. Nimipalvelua (portti 53) ei sallita kenellekään, ei myöskään UDP:llä `debian-tor`ille.
- **Ei yksityisiin osoitteisiin:** ulosmeno kaikkiin yksityisiin ja erikoisosoitteisiin on estetty kaikilta käyttäjiltä, myös rootilta ja `debian-tor`ilta. Alueet ovat `nftables.conf`:n määrittelyissä `KIELLETYT4` (RFC 1918 -alueet, CGNAT/tailnet, linkkipaikallinen, silmukka muualle kuin `lo`-liitäntään, `0.0.0.0/8`, IETF-protokollatehtävien alue `192.0.0.0/24`, suorituskykytestien alue `198.18.0.0/15`, monilähetys ja varatut) ja `KIELLETYT6` (ULA, linkkipaikallinen, silmukka, IPv4-mapatut, NAT64 ja monilähetys). Ne kattavat myös reitittimen takana olevat yksityiset verkot. IPv6-ulosmeno on estetty kokonaan (Tor käyttää IPv4:ää), koska reitittimen jakama IPv6-etuliite antaisi lähiverkon laitteille globaaleja osoitteita, joita yksityisten alueiden lista ei kata. Lisäksi estetään asennuksessa lasketut `LAHIVERKOT4`. Ainoa poikkeus on vastausliikenne kontille 122 hakuvälittäjän portista 8890, ja vain jo avatussa yhteydessä. IPv6-naapurinhaun ICMPv6-viestit sallitaan, koska IPv6 ei toimi ilman niitä.
- **Tor ei avaa sisäisiä osoitteita:** `torrc`:ssä `ClientRejectInternalAddresses 1` ja `ClientDNSRejectInternalAddresses 1`. SOCKS-pyyntö yksityiseen osoitteeseen tai nimeen, joka ratkeaa yksityiseksi, hylätään jo Torissa.
- **SearXNG vain Torin kautta:** kaikki ulosmeno kulkee `socks5h://127.0.0.1:9050`:n kautta. Palomuuri sallii käyttäjälle `searxng` vain silmukan Tor-portin, ja yksikön `IPAddressDeny=any` + `IPAddressAllow=localhost` on toinen kerros.
- **Ei suoraa ulosmenoa:** alkuasennuksen jälkeen myös pakettipäivitykset kulkevat Torin kautta (`apt-transport-tor`, lähteet `tor+https://`). Vain `tor`, `apt-transport-tor` ja `nftables` asennetaan suoraan, ennen kuin kontissa on mitään hakuihin liittyvää.
- **Sisään vain kontista 122:** sekä kontin oma nftables että Proxmox-palomuuri sallivat vain kontin 122 hakuvälittäjän porttiin 8890.
- **Ei sisältöä lokeihin:** SearXNG:n palvelin (Granian) ei kirjoita pääsylokia, Torissa on `SafeLogging 1`, ja journald säilyttää lokit 30 päivää.
- **Avaimet:** SearXNG:n `secret_key` ja hakuvälittäjän jaettu avain luodaan komennoilla, jotka eivät tulosta niitä.

## Komentojen käyttö

- Aja komennot yksi kerrallaan ja vertaa tulosta Odotettu-riviin. Jos tulos poikkeaa, pysähdy.
- Isännän komennot ajetaan Proxmox-isännällä rootina **samassa pääteistunnossa**, koska osa komennoista asettaa muuttujia (esim. `IP122`). Jos istunto katkeaa, aja kohdan 1 muuttujakomennot uudelleen.
- Kontin komennot ajetaan isännältä muodossa `pct exec 123 -- ...`, joten kontin sisään ei tarvitse kirjautua.

## 0. Esitarkistukset (isäntä)

```bash
pct status 123
```
Odotettu: virheilmoitus, että kontin 123 asetustiedostoa ei ole. Jos kontti on olemassa, pysähdy ja valitse uusi numero (koko ohjeen 123 vaihdetaan).

```bash
pct list
```
Odotettu: konttilista, jossa näkyvät 110–122 eikä 123:a.

```bash
free -m
```
Odotettu: `available`-sarakkeessa vähintään 1 500 Mt (kontti tarvitsee 1 Gt ja varaa jää).

```bash
pve-firewall status
```
Odotettu: `Status: enabled/running` tai `Status: disabled/running`. Jos tila on `disabled`, Proxmox-palomuuri (kohta 9) ei vaikuta, ja suoja on kontin oma nftables. **Älä kytke Proxmox-palomuuria päälle tämän ohjeen takia**, koska se vaikuttaa koko isäntään. Päätös on erillinen.

## 1. Osoitteet ja asetukset komennoilla (isäntä)

Kontti 122 on ainoa sallittu asiakas. Sen osoite ja verkkoasetukset luetaan sen omista asetuksista.

```bash
IP122=$(pct config 122 | sed -n 's/^net0:.*ip=\([0-9.]*\)\/.*/\1/p'); echo "$IP122"
```
Odotettu: yksi IPv4-osoite. Jos tulos on tyhjä, kontti 122 käyttää DHCP:tä: pysähdy, koska palomuurisäännöt tarvitsevat kiinteän osoitteen.

```bash
ETULIITE=$(pct config 122 | sed -n 's/^net0:.*ip=[0-9.]*\/\([0-9]*\).*/\1/p'); echo "$ETULIITE"
```
Odotettu: verkon etuliite, esim. `24`.

```bash
YHDYSKAYTAVA=$(pct config 122 | sed -n 's/^net0:.*gw=\([0-9.]*\).*/\1/p'); echo "$YHDYSKAYTAVA"
```
Odotettu: yksi IPv4-osoite (oletusyhdyskäytävä).

```bash
SILTA=$(pct config 122 | sed -n 's/^net0:.*bridge=\([A-Za-z0-9]*\).*/\1/p'); echo "$SILTA"
```
Odotettu: sillan nimi, esim. `vmbr0`.

```bash
TALLENNUS=$(pct config 122 | sed -n 's/^rootfs: \([^:]*\):.*/\1/p'); echo "$TALLENNUS"
```
Odotettu: tallennustilan nimi (sama, jota kontti 122 käyttää).

Hakukontin osoitteeksi ehdotetaan kontin 122 seuraavaa osoitetta. Se tarkistetaan vapaaksi kahdella komennolla.

```bash
IP123=$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]) + 1)' "$IP122"); echo "$IP123"
```
Odotettu: kontin 122 osoite plus yksi.

```bash
grep -l "ip=$IP123/" /etc/pve/lxc/*.conf /etc/pve/qemu-server/*.conf 2>/dev/null | wc -l
```
Odotettu: `0` (mikään kontti tai virtuaalikone ei käytä osoitetta).

```bash
ping -c 2 -W 1 "$IP123" >/dev/null 2>&1 && echo VARATTU || echo VAPAA
```
Odotettu: `VAPAA`. Jos tulos on `VARATTU`, kokeile seuraavaa osoitetta: `IP123=$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]) + 1)' "$IP123"); echo "$IP123"` ja aja kaksi edellistä tarkistusta uudelleen.

Lähiverkot, joihin hakukontista ei saa ottaa yhteyttä: kaikki isännän suoraan liitetyt aliverkot ja Tailscalen osoitealue (laskettu isännän Tailscale-osoitteesta).

```bash
LAHI4=$(ip -4 route show proto kernel | awk '{print $1}' | sort -u | paste -sd, -); echo "$LAHI4"
```
Odotettu: pilkuin eroteltu lista aliverkkoja (vähintään kotiverkko).

```bash
TS10=$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_network(sys.argv[1] + "/10", strict=False))' "$(tailscale ip -4 | head -n 1)"); echo "$TS10"
```
Odotettu: yksi aliverkko, jonka etuliite on `/10`. Jos isännällä ei ole Tailscalea, komento antaa virheen: aseta silloin `TS10=` (tyhjä) ja jatka.

```bash
LAHIVERKOT=$(printf '%s\n' "$LAHI4" "$TS10" 169.254.0.0/16 | grep -v '^$' | paste -sd, -); echo "$LAHIVERKOT"
```
Odotettu: edellisten yhdistelmä pilkuin eroteltuna ja lopussa linkkipaikallinen alue `169.254.0.0/16`.

## 2. Pohjatiedostot isännälle (isäntä)

Tiedostot haetaan agentscope-kontin (115) ajurikloonista, kun tämä muutos on yhdistetty päähaaraan.

```bash
pct exec 115 -- git -C /opt/agentti-pohja log -1 --format='%h %s' -- isanta/hakukontti
```
Odotettu: commit, jonka viesti mainitsee hakukontin. Jos tuloste on tyhjä, muutos ei ole vielä ajurikloonissa: pysähdy.

```bash
mkdir -p /root/hakukontti && for f in torrc nftables.conf searxng-settings.yml searxng.service journald-hakukontti.conf mittaa_moottorit.py; do pct pull 115 "/opt/agentti-pohja/isanta/hakukontti/$f" "/root/hakukontti/$f" || echo "PUUTTUU $f"; done; ls /root/hakukontti
```
Odotettu: kuusi tiedostoa, ei yhtään `PUUTTUU`-riviä.

```bash
printf 'define CT122 = %s\ndefine LAHIVERKOT4 = { %s }\n' "$IP122" "$LAHIVERKOT" > /root/hakukontti/hakukontti-osoitteet.nft; cat /root/hakukontti/hakukontti-osoitteet.nft
```
Odotettu: kaksi `define`-riviä, joissa ovat kontin 122 osoite ja lähiverkot.

## 3. Kontin luonti (isäntä)

```bash
pveam update
```
Odotettu: `update successful`.

```bash
POHJA=$(pveam available --section system | awk '{print $2}' | grep '^debian-1[2-9]-standard' | sort -V | tail -n 1); echo "$POHJA"
```
Odotettu: uusimman Debian-pohjan tiedostonimi, esim. `debian-13-standard_..._amd64.tar.zst`.

```bash
pveam list local | grep -q "$POHJA" && echo ON || pveam download local "$POHJA"
```
Odotettu: `ON` tai latauksen lopussa `download of ... finished`.

```bash
pct config 122 | grep '^features' || echo "ei features-riviä"
```
Odotettu: tieto, onko kontilla 122 `nesting=1`. Hakukonttiin tulee `nesting=1`, koska Torin ja SearXNG:n systemd-kovennukset (esim. `ProtectSystem`, `PrivateTmp`, `PrivateDevices`) luovat palvelulle oman mount-nimiavaruuden. Ilman `nesting=1`:tä unprivileged-kontissa ne kaatuvat virheeseen `226/NAMESPACE`, eikä Debianin `tor@default` käynnisty. Vaihtoehto olisi poistaa kovennukset, mikä heikentäisi eristystä enemmän kuin `nesting=1`. Kontti on silti unprivileged (käyttäjänimiavaruus rajaa rootin), siinä ei ajeta Dockeria, eikä siihen anneta `keyctl`- tai `fuse`-ominaisuuksia.

```bash
pct create 123 "local:vztmpl/$POHJA" --hostname hakukontti --unprivileged 1 --features nesting=1 --cores 1 --memory 1024 --swap 512 --rootfs "$TALLENNUS:8" --net0 "name=eth0,bridge=$SILTA,ip=$IP123/$ETULIITE,gw=$YHDYSKAYTAVA,firewall=1" --onboot 1 --description "Aivon hakukontti: SearXNG ja Tor, ei yksityista dataa"
```
Odotettu: luonti päättyy ilman virhettä (viimeisillä riveillä mm. `Creating SSH host key`).

```bash
pct start 123 && sleep 5 && pct exec 123 -- ip -4 -o addr show dev eth0
```
Odotettu: rivi, jossa näkyy `$IP123`.

## 4. Alkuasennus suoraan: vain Tor ja palomuuri (kontti)

Tämä on ainoa vaihe, jossa kontti käyttää suoraa yhteyttä. Siinä ladataan vain Debian-paketit.

```bash
pct exec 123 -- apt-get update
```
Odotettu: lopussa `Reading package lists... Done` ilman `Err:`-rivejä.

```bash
pct exec 123 -- env DEBIAN_FRONTEND=noninteractive apt-get install -y tor apt-transport-tor nftables
```
Odotettu: asennus päättyy ilman virhettä.

## 5. Käyttäjät ja Tor (kontti)

```bash
pct exec 123 -- useradd --system --home-dir /usr/local/searxng --create-home --shell /usr/sbin/nologin searxng
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- useradd --system --no-create-home --shell /usr/sbin/nologin --groups debian-tor aivo-haku
```
Odotettu: ei tulostetta. Ryhmä `debian-tor` antaa hakuvälittäjälle (PR 2) luvan käyttää Torin hallintasokettia `/run/tor/control` ja lukea sen evästeen: välittäjä tarkistaa ennen jokaista pyyntöä, että Tor-piiri on ylhäällä, ja pyytää haulle uuden piirin. Ryhmä ei anna `debian-tor`-käyttäjän verkkooikeuksia, koska palomuuri tunnistaa käyttäjän (`skuid`), ei ryhmää. Riski: hallintasoketin kautta voi muuttaa Torin asetuksia. Palomuuri rajaa silti Torin ulosmenon internetiin ja sisääntulon porttiin 8890.

```bash
pct push 123 /root/hakukontti/torrc /etc/tor/torrc --perms 0644
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- sh -c 'tor --verify-config -f /etc/tor/torrc --defaults-torrc /usr/share/tor/tor-service-defaults-torrc'
```
Odotettu: `Configuration was valid`.

```bash
pct exec 123 -- systemctl restart tor@default
```
Odotettu: ei tulostetta.

```bash
sleep 30; pct exec 123 -- journalctl -u tor@default --since "-2 min" --no-pager | grep -c "Bootstrapped 100%"
```
Odotettu: `1` tai suurempi. Jos tulos on `0`, odota hetki ja aja uudelleen. Jos palvelu ei käynnisty ja `systemctl status tor@default` näyttää `226/NAMESPACE`, pysähdy (kontin `nesting`-asetus).

## 6. Kill switch päälle (kontti)

```bash
pct exec 123 -- mkdir -p /etc/nftables.d
```
Odotettu: ei tulostetta.

```bash
pct push 123 /root/hakukontti/hakukontti-osoitteet.nft /etc/nftables.d/hakukontti-osoitteet.nft --perms 0644 && pct push 123 /root/hakukontti/nftables.conf /etc/nftables.conf --perms 0644
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- nft -c -f /etc/nftables.conf && echo SAANNOT_OK
```
Odotettu: `SAANNOT_OK`. Virhe `unknown user` tarkoittaa, että jokin käyttäjä (kohta 5) puuttuu.

```bash
pct exec 123 -- systemctl enable --now nftables
```
Odotettu: viesti symbolisen linkin luonnista, ei virhettä.

```bash
pct exec 123 -- nft list chain inet hakukontti output
```
Odotettu: ketju, jonka `policy drop` ja säännöt vastaavat tiedostoa `nftables.conf`.

```bash
pct exec 123 -- sh -c 'nft list chain inet hakukontti output | grep -c "yksityinen tai erikoisosoite"'
```
Odotettu: `2` (IPv4- ja IPv6-esto ladattu).

```bash
pct exec 123 -- apt-get -o Acquire::http::Timeout=10 update
```
Odotettu: `Temporary failure resolving 'deb.debian.org'` tai `Could not resolve` -virheitä. Lähteet ovat vielä suoria, ja kill switch estää ne (käyttäjä `_apt` pääsee vain Tor-porttiin, eikä nimipalvelu ole sallittu).

## 7. Pakettilähteet Torin kautta (kontti)

```bash
pct exec 123 -- sh -c "sed -i -E 's#(^|[[:space:]])https?://security\.debian\.org/debian-security#\1tor+https://deb.debian.org/debian-security#g; s#(^|[[:space:]])https?://deb\.debian\.org#\1tor+https://deb.debian.org#g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; grep -rhE '^(deb|URIs)' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null"
```
Odotettu: jokaisella lähderivillä on `tor+https://deb.debian.org`. Jos jollakin rivillä on muu osoite, pysähdy.

```bash
pct exec 123 -- apt-get update
```
Odotettu: `Reading package lists... Done` ilman `Err:`-rivejä. Haku on hitaampi kuin suoraan, koska se kulkee Torin kautta.

```bash
pct exec 123 -- env DEBIAN_FRONTEND=noninteractive apt-get install -y curl tcpdump torsocks git python3 python3-venv python3-dev build-essential libxslt1-dev zlib1g-dev libffi-dev libssl-dev
```
Odotettu: asennus päättyy ilman virhettä (kestää useita minuutteja Torin kautta).

## 8. SearXNG (kontti)

Lähdekoodi ja Python-paketit haetaan käyttäjänä `searxng` Torin kautta (`torsocks`).

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups env HOME=/usr/local/searxng torsocks git clone --depth 1 https://github.com/searxng/searxng /usr/local/searxng/searxng-src
```
Odotettu: `Cloning into '/usr/local/searxng/searxng-src'...` ilman virhettä.

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups env HOME=/usr/local/searxng python3 -m venv /usr/local/searxng/searx-pyenv
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups env HOME=/usr/local/searxng torsocks /usr/local/searxng/searx-pyenv/bin/pip install -U pip setuptools wheel pyyaml msgspec typing_extensions granian
```
Odotettu: lopussa `Successfully installed ...`.

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups env HOME=/usr/local/searxng sh -c 'cd /usr/local/searxng/searxng-src && torsocks /usr/local/searxng/searx-pyenv/bin/pip install --use-pep517 --no-build-isolation -e .'
```
Odotettu: lopussa `Successfully installed searxng-...`.

```bash
pct exec 123 -- install -d -m 0750 -o root -g searxng /etc/searxng
```
Odotettu: ei tulostetta.

```bash
pct push 123 /root/hakukontti/searxng-settings.yml /etc/searxng/settings.yml --perms 0640 --group searxng
```
Odotettu: ei tulostetta.

SearXNG:n `secret_key` luodaan seuraavalla komennolla suoraan tiedostoon. Komento ei tulosta avainta.

```bash
pct exec 123 -- sh -c 'k=$(python3 -c "import secrets; print(secrets.token_hex(32))") && sed -i "s/@SALAINEN_AVAIN@/$k/" /etc/searxng/settings.yml && unset k; grep -c "@SALAINEN_AVAIN@" /etc/searxng/settings.yml'
```
Odotettu: `0` (paikkamerkki on korvattu).

```bash
pct exec 123 -- stat -c '%a %U:%G' /etc/searxng/settings.yml
```
Odotettu: `640 root:searxng`.

```bash
pct push 123 /root/hakukontti/searxng.service /etc/systemd/system/searxng.service --perms 0644 && pct exec 123 -- systemctl daemon-reload
```
Odotettu: ei tulostetta.

SearXNG vaatii palomuurin (`Requires=nftables.service`): jos sääntöjen lataus epäonnistuu, palvelu ei käynnisty, ja palomuurin pysäytys pysäyttää sen. Tarkista ennen käynnistystä, että palomuuri on myös itsenäisesti käytössä kontin käynnistyessä.

```bash
pct exec 123 -- systemctl is-enabled nftables
```
Odotettu: `enabled`. Jos tulos on muu, pysähdy. `Requires=` käynnistää palomuurin palvelun mukana, mutta Tor ja muut palvelut eivät vaadi sitä, joten ilman `enabled`-tilaa kontti voi käynnistyä ilman kill switchiä. Huomaa myös: jos säännöt poistetaan käsin (`nft flush ruleset`), `nftables.service` pysyy aktiivisena, eikä systemd pysäytä palvelua. Sääntöjä ei siksi poisteta käsin palveluiden ollessa käynnissä.

```bash
pct exec 123 -- systemctl enable --now searxng
```
Odotettu: viesti symbolisen linkin luonnista, ei virhettä. SearXNG tarkistaa käynnistyessään Tor-yhteyden. Jos Tor ei ole vielä valmis (esim. heti kontin käynnistyksen jälkeen), palvelu voi hetken olla tilassa `failed`, ja `Restart=on-failure` käynnistää sen uudelleen 10 sekunnin välein.

Debianin pohjassa voi olla valmiina SSH- ja postipalvelin. Hakukontti ei tarvitse niitä (komennot ajetaan `pct exec`illä).

```bash
pct exec 123 -- sh -c 'for u in ssh.socket ssh.service postfix.service; do systemctl disable --now "$u" 2>/dev/null; done; echo PALVELUT_POIS'
```
Odotettu: `PALVELUT_POIS`.

```bash
sleep 20; pct exec 123 -- ss -ltnp
```
Odotettu: kuuntelevat portit ovat vain `127.0.0.1:8888` (SearXNG) ja `127.0.0.1:9050` (Tor). Yksikään portti ei kuuntele osoitteessa `0.0.0.0` tai `*`.

## 9. Lokit, avain ja Proxmox-palomuuri

```bash
pct exec 123 -- mkdir -p /etc/systemd/journald.conf.d && pct push 123 /root/hakukontti/journald-hakukontti.conf /etc/systemd/journald.conf.d/hakukontti.conf --perms 0644 && pct exec 123 -- systemctl restart systemd-journald
```
Odotettu: ei tulostetta.

Hakuvälittäjän jaettu avain luodaan hakukonttiin valmiiksi. Komento ei tulosta avainta. Avain kopioidaan konttiin 122 vasta PR 3:n käyttöönotossa, jotta konttiin 122 ei nyt kosketa.

```bash
pct exec 123 -- sh -c 'install -d -m 0750 -o root -g aivo-haku /etc/aivo-haku && umask 027 && python3 -c "import secrets; print(secrets.token_urlsafe(32))" > /etc/aivo-haku/avain && chgrp aivo-haku /etc/aivo-haku/avain && stat -c "%a %U:%G %s" /etc/aivo-haku/avain'
```
Odotettu: `640 root:aivo-haku 44` (koko tavuina, ei sisältöä).

Proxmox-palomuuri hakukontille: sisään vain kontista 122 porttiin 8890, ulos ei lähiverkkoihin, tailnetiin eikä muihin yksityisiin osoitteisiin. Yksityiset IPv4-alueet luetaan pohjan `nftables.conf`:sta, joten lista on yhdessä paikassa.

```bash
KIELLETYT4=$(sed -n 's/^define KIELLETYT4 = { \(.*\) }$/\1/p' /root/hakukontti/nftables.conf | tr -d ' '); echo "$KIELLETYT4"
```
Odotettu: pilkuin eroteltu lista, jossa on 11 aluetta ja ensimmäisenä `0.0.0.0/8`. Tyhjä tuloste: pysähdy.

```bash
test -e /etc/pve/firewall/123.fw && echo "ON JO" || printf '[OPTIONS]\nenable: 1\npolicy_in: DROP\npolicy_out: ACCEPT\nipfilter: 1\nlog_level_in: nolog\nlog_level_out: nolog\n\n[RULES]\nIN ACCEPT -source %s -p tcp -dport 8890 # hakuvalittaja vain kontille 122\nOUT DROP -dest %s # ei lahiverkkoihin eika tailnetiin\nOUT DROP -dest %s # ei yksityisiin eika erikoisosoitteisiin\nOUT DROP -dest fc00::/7 # ei paikallisia IPv6-osoitteita\n' "$IP122" "$LAHIVERKOT" "$KIELLETYT4" > /etc/pve/firewall/123.fw
```
Odotettu: ei tulostetta. Jos tuloste on `ON JO`, pysähdy ja tarkista tiedoston sisältö.

```bash
cat /etc/pve/firewall/123.fw
```
Odotettu: `[OPTIONS]`- ja `[RULES]`-osiot, kontin 122 osoite IN-säännössä sekä lähiverkot ja yksityiset alueet OUT-säännöissä. Proxmox-palomuuri on tilallinen, joten vastaukset kontille 122 kulkevat avatussa yhteydessä.

```bash
pve-firewall compile 2>&1 >/dev/null | grep -i -e error -e warn || echo KAANNOS_OK
```
Odotettu: `KAANNOS_OK`. Jos komento tulostaa virhe- tai varoitusrivejä, jokin sääntö on ohitettu: pysähdy. Jos kohdan 0 tila oli `disabled`, tiedosto on valmiina mutta ei vaikuta, ennen kuin Tony erikseen päättää Proxmox-palomuurista.

## 10. Käyttöönoton testit (suunnitelman kohta 3.3)

Testi 1. Tor-reitti toimii käyttäjänä `searxng`.

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups curl -sS -m 60 --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```
Odotettu: JSON, jossa on `"IsTor":true`.

Testi 2. Suora yhteys on estetty käyttäjältä `searxng` (myös nimipalvelu).

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups curl -sS -m 10 https://example.com; echo "paluuarvo $?"
```
Odotettu: `Could not resolve host` ja paluuarvo `6` (tai aikakatkaisu, paluuarvo `28`). Ei HTML:ää.

Testi 3. Suora yhteys on estetty käyttäjältä `aivo-haku`, eikä `debian-tor` voi lähettää UDP:tä.

```bash
pct exec 123 -- setpriv --reuid=aivo-haku --regid=aivo-haku --init-groups curl -sS -m 10 https://example.com; echo "paluuarvo $?"
```
Odotettu: kuten testissä 2.

```bash
pct exec 123 -- setpriv --reuid=debian-tor --regid=debian-tor --init-groups python3 -c 'import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b"x", ("9.9.9.9", 53)); print("UDP_LAHTI")'; echo "paluuarvo $?"
```
Odotettu: `PermissionError: [Errno 1] Operation not permitted` ja paluuarvo `1`. Palomuuri hylkää UDP-paketin jo lähettäessä. Tuloste `UDP_LAHTI` tarkoittaa, että Tor-käyttäjä pääsee ulos UDP:llä: pysähdy.

Testi 4. Kontista ei pääse lähiverkkoon (esim. kotireitittimen hallintasivu yhdyskäytävän osoitteessa). Tarkistus tehdään Tor-käyttäjänä, rootina ja Torin SOCKS-portin kautta.

```bash
pct exec 123 -- setpriv --reuid=debian-tor --regid=debian-tor --init-groups curl -sS -m 10 -o /dev/null "http://$YHDYSKAYTAVA/"; echo "paluuarvo $?"
```
Odotettu: paluuarvo `7` tai `28` (yhteys estetty tai aikakatkaisu).

```bash
pct exec 123 -- curl -sS -m 10 -o /dev/null "http://$YHDYSKAYTAVA/"; echo "paluuarvo $?"
```
Odotettu: paluuarvo `7` tai `28`. Myös root on estetty.

```bash
pct exec 123 -- setpriv --reuid=debian-tor --regid=debian-tor --init-groups curl -sS -m 10 -o /dev/null "http://$IP122/"; echo "paluuarvo $?"
```
Odotettu: paluuarvo `7` tai `28`. Kontti 122 on sallittu vain vastauksille hakuvälittäjän portista, ei uusille yhteyksille.

```bash
pct exec 123 -- setpriv --reuid=searxng --regid=searxng --init-groups curl -sS -m 30 -o /dev/null --socks5-hostname 127.0.0.1:9050 "http://$YHDYSKAYTAVA/"; echo "paluuarvo $?"
```
Odotettu: SOCKS-virhe ja paluuarvo `97` (vanhemmassa curlissa `7`). Tor hylkää sisäisen osoitteen (`ClientRejectInternalAddresses`). Paluuarvo `0` tarkoittaa, että pyyntö meni läpi: pysähdy.

```bash
pct exec 123 -- sh -c 'nft list chain inet hakukontti output | grep "yksityinen tai erikoisosoite"'
```
Odotettu: kaksi riviä. IPv4-rivin `counter packets` on suurempi kuin `0` (edelliset kolme testiä).

Testi 5. Haku toimii SearXNG:n kautta.

```bash
pct exec 123 -- sh -c 'curl -sS -m 90 "http://127.0.0.1:8888/search?q=photosynthesis&format=json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d[\"results\"]), d[\"unresponsive_engines\"])"'
```
Odotettu: tulosten määrä on suurempi kuin `0`. Lista kertoo, mitkä moottorit eivät vastanneet.

Testi 6. Kill switch: kun Tor on pysäytetty, haku epäonnistuu eikä kontista lähde yhtään pakettia ulos.

```bash
pct exec 123 -- systemctl stop tor@default
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- sh -c 'sleep 30; timeout 60 tcpdump -ni eth0 -Q out -w /tmp/killswitch.pcap "udp or (ip6 and not icmp6) or (tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0)" 2>/dev/null & sleep 2; curl -sS -m 50 "http://127.0.0.1:8888/search?q=photosynthesis&format=json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(\"tuloksia\", len(d[\"results\"]))"; wait'
```
Odotettu: `tuloksia 0` (kaikki moottorit vastaamattomina).

```bash
pct exec 123 -- sh -c 'tcpdump -nr /tmp/killswitch.pcap 2>/dev/null | wc -l; rm -f /tmp/killswitch.pcap'
```
Odotettu: `0` (yhtään uutta lähtevää yhteyttä ei syntynyt). Suodatin laskee vain uudet TCP-yhteydet (SYN), UDP:n ja IPv6:n, koska Torin pysäytyksen jälkeen vanhoista yhteyksistä voi vielä lähteä sulkupaketteja.

```bash
pct exec 123 -- systemctl start tor@default
```
Odotettu: ei tulostetta. Odota noin 30 sekuntia ennen seuraavaa testiä.

Testi 7. Hylätyt yhteydet näkyvät laskurissa.

```bash
pct exec 123 -- sh -c 'nft list chain inet hakukontti output | grep "kill switch"'
```
Odotettu: rivi, jossa `counter packets` on suurempi kuin `0` (testit 2 ja 3).

Testi 8. Hakulausekkeita ei ole lokeissa.

```bash
pct exec 123 -- sh -c 'journalctl --since "-1 hour" --no-pager | grep -c photosynthesis'
```
Odotettu: `0`.

Testi 9. Kontti 115 ei pääse hakukonttiin (vain kontti 122 on sallittu).

```bash
pct exec 115 -- curl -sS -m 5 "http://$IP123:8890/"; echo "paluuarvo $?"
```
Odotettu: paluuarvo `28` (aikakatkaisu, paketit hylätään) tai `7`.

Testi 10. SearXNG-palvelun kovennus.

```bash
pct exec 123 -- systemd-analyze security searxng.service --no-pager | tail -n 1
```
Odotettu: kokonaisarvio `OK` tai `MEDIUM`. Kirjaa arvo raporttiin.

## 11. Moottorien mittaus

Mittaus kertoo, mitkä moottorit estävät Torin. Se kestää noin 10–20 minuuttia oletusarvoilla (6 moottoria, 10 lausetta kullekin, 3–8 sekunnin välit).

```bash
pct exec 123 -- install -d -m 0755 /usr/local/lib/hakukontti && pct push 123 /root/hakukontti/mittaa_moottorit.py /usr/local/lib/hakukontti/mittaa_moottorit.py --perms 0644
```
Odotettu: ei tulostetta.

```bash
pct exec 123 -- setpriv --reuid=aivo-haku --regid=aivo-haku --init-groups python3 -I /usr/local/lib/hakukontti/mittaa_moottorit.py --json /tmp/moottorit.json
```
Odotettu: taulukko, jossa on rivi jokaiselle moottorille. Sarakkeet: `esto%` (Tor-estot) ja `alle3%` (haut, joissa alle 3 tulosta).

```bash
pct pull 123 /tmp/moottorit.json /root/hakukontti/moottorit-$(date +%F).json && pct exec 123 -- rm -f /tmp/moottorit.json
```
Odotettu: ei tulostetta. JSON-tiedostossa ei ole hakulausekkeita eikä osoitteita, joten sen voi liittää raporttiin.

```bash
pct exec 123 -- sh -c 'journalctl --since "-1 hour" --no-pager | grep -c -i -e photosynthesis -e "linux file permissions" -e "baltic sea"'
```
Odotettu: `0`. Jos tulos on suurempi, SearXNG kirjoittaa moottorivirheiden yhteydessä hakuosoitteita lokiin: pysähdy ja kirjaa asia raporttiin (korjaus PR 2:ssa, esim. lokitason rajaus).

Tulkinta: moottori, jonka `esto%` on yli 50, poistetaan `searxng-settings.yml`:n `keep_only`-listalta tai siirretään myöhemmin VPN-reitille (A1102). Jos yli 30 % kaikista hauista palauttaa alle 3 tulosta, Tony päättää VPN-varareitistä (suunnitelman kohta 3.2).

## 12. Snapshot

```bash
pct snapshot 123 hakukontti-asennettu --description "SearXNG, Tor ja kill switch asennettu ja testattu"
```
Odotettu: ei virhettä. `pct listsnapshot 123` näyttää snapshotin.

## Pakettipäivitykset jatkossa

Päivitykset kulkevat Torin kautta, koska lähteet ovat `tor+https://` ja `_apt` pääsee vain Tor-porttiin.

```bash
pct exec 123 -- sh -c 'apt-get update && apt-get -y upgrade'
```
Odotettu: päivitykset asentuvat ilman `Err:`-rivejä.

SearXNG päivitetään käyttäjänä `searxng` `torsocks git pull` -komennolla lähdehakemistossa ja sen jälkeen `systemctl restart searxng`.

## Tunnetut rajoitukset ja jatko

- **Piirien eristys hauissa:** SearXNG ei lähetä SOCKS-tunnusta, joten saman minuutin aikana tehdyt haut voivat kulkea samaa piiriä samaan hakukoneeseen (`IsolateDestAddr` erottaa eri kohteet, `MaxCircuitDirtiness 60` vaihtaa piirin minuutin välein). Hakukohtainen piiri tehdään PR 2:ssa: hakuvälittäjä pyytää ennen hakua uuden piirin hallintasoketin kautta (`SIGNAL NEWNYM`). Sivuhaut (`/sivu`) käyttävät `IsolateSOCKSAuth`-eristystä tehtävätunnuksella.
- **Proxmox-palomuuri** vaikuttaa vain, jos se on päällä datacenter-tasolla. Ilman sitä suojana on kontin oma nftables. Kontin root voisi muuttaa sitä, mutta sovelluskäyttäjät eivät.
- **Lähiverkkolista:** kaikki yksityiset alueet ovat pohjassa (`KIELLETYT4`, `KIELLETYT6`), joten myös reitittimen takana olevat yksityiset verkot on estetty. Asennuksessa laskettu `LAHIVERKOT4` estää lisäksi isännän suorat verkot, jos jokin niistä olisi julkinen. Jos isäntään lisätään uusi silta, aja kohdan 1 komennot ja päivitä `hakukontti-osoitteet.nft` ja `123.fw`.
- **Hakuvälittäjä** (portti 8890) tulee PR 2:ssa. Siihen asti portissa ei kuuntele mikään, ja testi 9 mittaa vain palomuurin.

## Peruminen

Palvelut pysäytetään ja kontti jätetään talteen:

```bash
pct stop 123 && pct set 123 --onboot 0
```
Odotettu: ei tulostetta. Kontti ja sen snapshotit säilyvät. Kontin poistamisesta päättää Tony erikseen.
