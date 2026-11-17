# Aivon oma keskustelusivu (A705–A706)

Yksityinen tila ja ydinohjeet: katso `docs/aivo-yksityinen.md`.

Tämä ohje on Tonylle. Chat on asennettu omaan konttiinsa (Tonyn päätös A976). Kontti on Debianin minimiasennus, jossa komentoja ajetaan root-käyttäjänä eikä `sudoa` ole; käyttäjänä ajo tehdään komennolla `runuser -u KÄYTTÄJÄ -- KOMENTO`. Sivu on pieni oma palvelu (`aivo/chat.py`, vain Pythonin vakiokirjasto). Claude on kirjoittanut koodin, ja Tony ottaa sen käyttöön itse: palvelu on uusi, se koskee Aivon oikeuksia ja siinä on salasana. Tony asettaa salasanan itse. Mitään salaisuutta ei ole repossa.

## Mitä sivu tekee

- Tony kirjautuu salasanallaan ja keskustelee Aivon kanssa. Sivu toimii puhelimen selaimessa (kapea asettelu, tumma ja vaalea teema).
- Vastaus tulee vain Claudelta suoraan (`claude -p`, ei työkaluja). LiteLLM:ää, OpenRouteria tai kilpailutusta ei käytetä (A329).
- Ennen jokaista vastausta Aivo lukee muistinsa: päätöskirjaston, kompassin, haastattelut ja faktat. Tiedostot luetaan kirjaston kansiosta tässä järjestyksessä (nimi sisältää `paatos`, `kompassi`, `haastattel`, `fakta`, sitten muut `.md`- ja `.txt`-tiedostot). Yläraja on noin 300 kt; ylimenevät tiedostot jäävät pois.
- Aivo merkitsee muistista otetut väitteet muodossa `[lähde: tiedosto]`. Palvelin tarkistaa viitteet: jos tiedostoa ei ole muistissa, viite saa merkinnän `EI LÖYDY MUISTISTA`.
- Keskustelut tallentuvat isännälle tiedostoihin (`/var/lib/aivo/chat/*.jsonl`, oikeudet 600). Mitään ei lähetetä GitHubiin.
- **Päätösehdotus (A997):** kun Tony sanoo selvästi päättävänsä jotain, Aivo voi lisätä vastauksensa viimeiselle riville merkinnän `[[PAATOS n]]` (n = Tonyn viestin numero). Palvelin poistaa merkinnän näkyvästä tekstistä ja palauttaa kentän `paatosehdotus`, jos n on saman keskustelun Tonyn viesti; muuten ehdotus hylätään hiljaa. Sivu näyttää vastauksen alla kortin "Kirjaanko päätökseksi: '…'?" (Tonyn viesti sanasta sanaan) ja napit kyllä / ei. Vain kyllä kutsuu `/api/paatos`-reittiä, ja kirjataan edelleen vain Tonyn oma viesti. Aivo ei kirjaa mitään itse. Kehote (`KEHOTE`) opastaa ehdotuksen vain työkalutilassa; yksityisessä tilassa merkintä käsitellään samoin, mutta sen ohjeet ovat isännän ydinohjeissa, joita tämä muutos ei koske.
- **Päätökset:** jokaisessa Tonyn viestissä on painike "Kirjaa päätökseksi". Painikkeen painallus liittää Tonyn viestin sanasta sanaan lainauksena kirjaston tiedostoon `aivo-paatoskirjasto.md` ja pushaa kirjaston Giteaan. Sivu näyttää "Kirjattu" vain, kun push onnistui (työkalutila) tai päätös kirjattiin yksityiseen muistiin (yksityinen tila). Jos push epäonnistuu, palvelin vastaa virhekoodilla 502 ja sivu kertoo, ettei päätöstä kirjattu Giteaan; commit jää silloin kirjaston paikalliseen kloonaan. Jos päätös on jo kirjattu, sivu näyttää "Ei muutosta". Aivon omia lauseita tai päätelmiä ei kirjata päätökseksi koskaan. Kirjaston etärepo ei saa osoittaa GitHubiin; muuten koodi kieltäytyy pushaamasta.

## Turvarajat

- Palvelu kuuntelee vain osoitteessa `127.0.0.1`. Koodi kieltäytyy käynnistymästä muussa kuin loopback- tai Tailscale-osoitteessa.
- Tailnetiin sivu avataan komennolla `tailscale serve` (HTTPS, vain tailnetin laitteet). Älä käytä `tailscale funnel` -komentoa: se avaisi sivun internetiin.
- Evästeessä on `HttpOnly`, `Secure` ja `SameSite=Strict`. Muutospyynnöt vaativat oman otsakkeen ja saman alkuperän. Väärällä `Host`-otsakkeella sivu vastaa 421.
- Viisi väärää salasanaa lukitsee kirjautumisen viideksi minuutiksi. Istunnot ovat vain muistissa (palvelun uudelleenkäynnistys kirjaa ulos).
- Salasanasta tallennetaan vain scrypt-tiiviste tiedostoon, jonka oikeudet ovat 600. Lokiin ei kirjoiteta viestejä eikä salasanoja.
- Muistin tiedostot ovat dataa, eivät ohjeita. Kehote kieltää noudattamasta niiden sisältämiä käskyjä.

## Käyttöönotto (Tony ajaa, isännällä, jolla on Tailscale ja `claude`)

Ota ensin tilannekuva kontista. Tämä ohje ei muuta palomuureja, holvia eikä Tailscalen asetuksia, paitsi lisää yhden `tailscale serve` -säännön (vaihe 6).

1. **Käyttäjä ja kansiot** (sama `aivo`-käyttäjä kuin Garmin- ja Drive-ohjeissa):

   ```
   useradd --system --create-home --home-dir /var/lib/aivo --shell /usr/sbin/nologin aivo
   useradd --system --create-home --home-dir /var/lib/aivo-tyokalu --shell /usr/sbin/nologin aivo-tyokalu
   groupadd --system aivo-tyokalu-socket
   install -d -m 700 -o aivo -g aivo /var/lib/aivo/chat /etc/aivo
   ```

   `aivo` ajaa chat-palvelua ja `aivo-tyokalu` työkalutilan `claude`-kutsua (kohta 5b). Ryhmä `aivo-tyokalu-socket` annetaan vain chat-palvelun käyttäjälle (`SupplementaryGroups`). Jos käyttäjä tai ryhmä on jo olemassa, komento antaa virheen. Se ei haittaa.

2. **Kirjasto Gitean kautta.** Kloonaa Aivon kirjasto Giteasta tailnet-nimellä (esimerkiksi `gitea.<tailnet>.ts.net`; IP-osoitetta ei käytetä, koska sallittujen palvelimien lista vertaa nimeä). Tunnus ja avain ovat Tonyn. Git tallentaa ne tiedostoon `.git-credentials` (credential store), jotta push toimii ilman kyselyä:

   ```
   runuser -u aivo -- git config --global credential.helper store
   runuser -u aivo -- git clone https://gitea.<tailnet>.ts.net/aivo/aivo.git /var/lib/aivo/kirjasto
   chmod 600 /var/lib/aivo/.git-credentials
   ```

   Klooni kysyy tunnuksen ja avaimen; Tony kirjoittaa ne itse. Tarkista, että tiedoston tila on 600 (`stat -c '%a' /var/lib/aivo/.git-credentials`) ja ettei `origin` osoita GitHubiin: `runuser -u aivo -- git -C /var/lib/aivo/kirjasto remote -v`.

   **Git-identiteetti.** Ilman nimeä ja sähköpostiosoitetta `git commit` kaatuu, eikä päätös mene perille. Aseta ne kirjaston omaan asetukseen (kloonin jälkeen, ei riipu kotihakemiston ympäristömuuttujista) ja tarkista:

   ```
   runuser -u aivo -- git -C /var/lib/aivo/kirjasto config user.name "Aivo"
   runuser -u aivo -- git -C /var/lib/aivo/kirjasto config user.email "aivo@localhost"
   runuser -u aivo -- git -C /var/lib/aivo/kirjasto config --get-regexp '^user\.'
   ```

3. **Salasana.** Aja itse ja kirjoita salasana kahdesti (vähintään 12 merkkiä). Mitään ei tulostu:

   ```
   runuser -u aivo -- env PYTHONPATH=/opt/agentti-pohja python3 -m aivo.chat aseta-salasana
   ```

   Onnistuessaan komento tulostaa: `Salasanan tiiviste tallennettu (600). Salasanaa ei tallennettu.` Tiedosto on `/etc/aivo/chat-salasana`. `PYTHONPATH` osoittaa agentti-pohjan juureen.

4. **Claude-kirjautuminen `aivo-tyokalu`-käyttäjälle.** Tämän ohjeen mukaisessa socket-mallissa vain `aivo-tyokalu` ajaa `claude`:a (kohta 5b), joten vain sen tarvitsee kirjautua. Tee kirjautuminen kerran: `runuser -u aivo-tyokalu -- env HOME=/var/lib/aivo-tyokalu claude`. Chat-palvelun käyttäjä `aivo` ei tarvitse omaa kirjautumista. Jos jätät socketin pois (`AIVO_TYOKALU_SOCKET` ei ole asetettu), `claude` ajetaan suoraan käyttäjänä `aivo`, ja silloin kirjautuminen tehdään sille samalla komennolla (`HOME=/var/lib/aivo`). Tarkista, että kirjautuminen toimii:

   ```
   echo "sano kyllä" | runuser -u aivo-tyokalu -- env HOME=/var/lib/aivo-tyokalu claude -p --tools "" --max-turns 1
   ```

5. **Palvelu (systemd).** Tallenna tiedostoon `/etc/systemd/system/aivo-chat.service`:

   ```
   [Unit]
   Description=Aivon keskustelusivu
   After=network-online.target

   [Service]
   User=aivo
   WorkingDirectory=/opt/agentti-pohja
   Environment=HOME=/var/lib/aivo PYTHONPATH=/opt/agentti-pohja
   Environment=AIVO_CLAUDE=/KOKO/POLKU/claude
   Environment=AIVO_TYOKALU_SOCKET=/run/aivo-tyokalu.sock
   Environment=AIVO_SALLITUT_ETAISANNAT=gitea.<tailnet>.ts.net
   ExecStart=/usr/bin/python3 -m aivo.chat palvele --host TAILNET-NIMI
   Restart=on-failure
   SupplementaryGroups=aivo-tyokalu-socket
   NoNewPrivileges=true
   ProtectSystem=strict
   ReadWritePaths=/var/lib/aivo
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   ```

   Vaihda `AIVO_CLAUDE` oikeaan polkuun (`command -v claude`) ja `TAILNET-NIMI` palvelun täydelliseen tailnet-nimeen (`tailscale status --self --json`, kenttä `DNSName`, ilman loppupistettä). `--host` vaatii täsmällisen nimen: jokerimerkintä (`.pääte`) hylätään käynnistyksessä, ja ilman `--host`-valitsinta sallitaan vain `localhost`. Tämä pienentää DNS-rebinding-riskiä, koska toisen tailnetin nimet eivät kelpaa.

   **`NoNewPrivileges=true` pysyy.** Jos käytät yksityisen tilan ohjeen mukaista työkalukäyttäjää (`aivo-tyokalu`), ei tarvita `sudoa` eikä sudoers-riviä. Työkalutilan `claude` ajetaan erillisenä systemd-palveluna omana käyttäjänään, ja chat-palvelu puhuu sille unix-socketin kautta. Ohje on kohdassa 5b. Jos et käytä työkalukäyttäjää, jätä `AIVO_TYOKALU_SOCKET` ja `SupplementaryGroups`-rivi pois, jolloin `claude` ajetaan suoraan chat-palvelun käyttäjänä (`aivo`).

   Kaksi ympäristömuuttujaa yksikössä:

   - `AIVO_TYOKALU_SOCKET` on työkalutilan socketin polku (kohta 5b). Ilman sitä työkalutilan `claude` ajetaan chat-palvelun omana käyttäjänä.
   - `AIVO_SALLITUT_ETAISANNAT` on pilkuilla erotettu lista palvelimista (tarkka tailnet-nimi), joille kirjasto saa pushata. **Ilman sitä push kieltäytyy**: päätöstä ei julkaista, tulos on `ei-etaa` ja sivu näyttää virheen eikä "Kirjattu". Arvon pitää vastata kirjaston `origin`-osoitteen palvelinta.

5b. **Työkalutila omana käyttäjänään (ei sudoa).** Käyttäjämalli:

   | Rooli | Käyttäjä | Oikeus socketille |
   |---|---|---|
   | Chat-palvelu (`aivo-chat.service`) | `aivo` (yksityisen tilan ohjeessa `aivo-yksityinen`) | kuuluu ryhmään `aivo-tyokalu-socket` (`SupplementaryGroups`), tila 0660 |
   | Socketin omistaja | `root`, ryhmä `aivo-tyokalu-socket` | omistaja ja ryhmä saavat lukea ja kirjoittaa, muut eivät mitään |
   | Työkalutilan kääre (`aivo-tyokalu@.service`) | `aivo-tyokalu` | ei ole ryhmässä eikä pääse socketille itse; systemd antaa sille yhteyden vain `StandardInput=socket`-kautta |

   Ryhmään kuuluu vain chat-palvelun käyttäjä. Näin chat-palvelun käyttäjä voi vaihtua (`aivo` tai `aivo-yksityinen`) ilman, että socketin oikeuksia tarvitsee avata muille. Ryhmä luodaan kerran: `groupadd --system aivo-tyokalu-socket` (ks. kohta 1). Kaksi tiedostoa. Komento on kiinteä yksikkötiedostossa: chat-palvelu voi lähettää socketille vain tekstiä, ei valitsimia eikä komentoja.

   `/etc/systemd/system/aivo-tyokalu.socket`:

   ```
   [Unit]
   Description=Aivon tyokalutilan Claude-socket

   [Socket]
   ListenStream=/run/aivo-tyokalu.sock
   Accept=yes
   MaxConnections=2
   SocketUser=root
   SocketGroup=aivo-tyokalu-socket
   SocketMode=0660

   [Install]
   WantedBy=sockets.target
   ```

   `/etc/systemd/system/aivo-tyokalu@.service`:

   ```
   [Unit]
   Description=Aivon tyokalutilan Claude (yksi kutsu)

   [Service]
   User=aivo-tyokalu
   Environment=HOME=/var/lib/aivo-tyokalu
   StandardInput=socket
   StandardOutput=socket
   StandardError=journal
   ExecStart=/usr/bin/python3 /KOKO/POLKU/aivo/tyokalu_kaares.py /KOKO/POLKU/claude -p --output-format text --max-turns 1 --tools ""
   RuntimeMaxSec=250
   NoNewPrivileges=yes
   ProtectSystem=strict
   ReadWritePaths=/var/lib/aivo-tyokalu
   PrivateTmp=yes
   PrivateDevices=yes
   ```

   `tyokalu_kaares.py` ajaa saman kiinteän `claude`-komennon ja lisää vastauksen perään päätösrivin `\x00AIVO-EXIT <koodi>`. Chat näyttää nollasta poikkeavasta koodista lyhyen virheen (`Työkalu epäonnistui (koodi 1), katso journalctl -u aivo-tyokalu@*`) tyhjän vastauksen sijaan. Puuttuva päätösrivi (katkennut yhteys, aikaraja) raportoidaan myös virheenä. `claude`:n stderr jää lokiin eikä kulje socketin yli. Kääreskripti ei saa olla `aivo-tyokalu`-käyttäjän kirjoitettavissa (omistajaksi root). Päivitys: vanha yksikkö ilman käärettä antaa nyt aina virheen, koska päätösrivi puuttuu.

   Komento on koko polulla (`command -v claude`). Sitten `systemctl daemon-reload && systemctl enable --now aivo-tyokalu.socket`. Chat-palvelun yksikössä (kohta 5) on jo rivi `Environment=AIVO_TYOKALU_SOCKET=/run/aivo-tyokalu.sock`. Vain `aivo-tyokalu-socket`-ryhmän jäsenet (chat-palvelun käyttäjä) pääsevät socketille (tila 0660, ei oikeuksia muille). Vanha `AIVO_TYOKALU_KAYTTAJA`-asetus on poistettu: koodi kieltäytyy käynnistämästä kutsua, jos se on asetettu, jotta eristys ei heikkene huomaamatta.

   Jos chat-palvelun käyttäjä lisätään ryhmään vasta nyt, käynnistä chat-palvelu uudelleen, jotta ryhmä tulee voimaan.

   Tarkistus (ryhmä annetaan `-g`-valitsimella, koska `runuser -u` ei muuten lisää lisäryhmää): `runuser -u aivo -g aivo-tyokalu-socket -- python3 -c "import socket;s=socket.socket(socket.AF_UNIX);s.connect('/run/aivo-tyokalu.sock');s.sendall('sano kyllä'.encode());s.shutdown(socket.SHUT_WR);print(s.recv(200))"` tulostaa vastauksen. Merkkijonon pitää olla `'sano kyllä'.encode()`: `b'sano kyllä'` on `SyntaxError`, koska bytes-literaalissa ei saa olla ASCII-merkkien ulkopuolisia merkkejä. Toisena käyttäjänä (`runuser -u nobody -- ...`) yhteys antaa `PermissionError`.

   Sitten:

   ```
   systemctl daemon-reload && systemctl enable --now aivo-chat
   ```

6. **Avaus tailnetiin** (HTTPS, vain tailnet). Komennon muoto riippuu Tailscalen versiosta; tarkista `tailscale serve --help`:

   ```
   tailscale serve --bg 8780
   tailscale serve status
   ```

   Tilan pitää näyttää osoite, jonka loppu on `.ts.net`, ja merkintä "tailnet only". Jos näet sanan "Funnel on", sammuta se: `tailscale funnel reset`.

## Todennus (Tonyn ajettavaksi, sen jälkeen riippumaton tarkastaja)

1. Avaa puhelimella (Tailscale päällä) tailnet-osoite, kirjaudu ja kysy "mitä tiedät minusta?". Vastauksessa pitää olla `[lähde: ...]`-viitteitä oikeisiin tiedostoihin.
2. Sulje puhelimen Tailscale (tai käytä mobiilidataa ilman Tailscalea) ja avaa sama osoite. Sivun ei pidä aueta.
3. Sano chatissa selvästi päättäväsi jotain (esimerkiksi "kyllä, tehdään X") ja tarkista, että vastauksen alle ilmestyy kortti "Kirjaanko päätökseksi". "Ei" sulkee kortin ilman kirjausta. Voit myös painaa yhden oman viestisi kohdalla "Kirjaa päätökseksi" ja tarkista, että `aivo-paatoskirjasto.md` sisältää viestin sanasta sanaan ja että muutos näkyy Giteassa (ei GitHubissa). Painikkeen pitää näyttää "Kirjattu" vasta, kun push on onnistunut. Jos push epäonnistuu (esimerkiksi `AIVO_SALLITUT_ETAISANNAT` puuttuu), painikkeen tekstin pitää olla "Ei kirjattu Giteaan: ...".
4. Isännällä: `ss -ltnp | grep 8780` näyttää vain `127.0.0.1:8780`.

## Keskustelumuisti: automaattinen tiivistys (Tony tekee kontissa 122)

Työkalutilan keskustelut tiivistetään kirjastoon, jotta Aivo muistaa ne 40 viestin jälkeenkin (A983 kohta A3). Tiivistys ajetaan komennolla `python3 -m aivo.tiivista --alue tyokalu`. Se tiivistää keskustelun, kun viimeisestä viestistä on kulunut vähintään 30 minuuttia, ja kutsuu Claudea samalla `aivo-tyokalu`-socketilla kuin chat. Päiväkatto on 10 tiivistystä vuorokaudessa (Europe/Helsinki). Katto on koodin vakio, eikä sitä voi muuttaa asetuksilla. Katon täyttyessä ajo lopettaa ja kirjoittaa syyn tiedostoon `/var/lib/aivo/indeksi/tiivista.log`. Yksityisen tilan keskusteluja ei lueta eikä lähetetä: komento hyväksyy vain alueen `tyokalu`.

Tiivistelmät tallentuvat kansioon `/var/lib/aivo/tiivistelmat` (0700, tiedostot 0600) ja luettelo tiedostoon `/var/lib/aivo/indeksi/indeksi.json`. Tonyn lainaukset on erotettu mallin tulkinnasta. Lainaus tarkistetaan sanasta sanaan Tonyn viestistä, ja virheellinen lainaus poistetaan. Uudet kohdat ovat aina tilassa `ehdotus`, ja vain Tonyn korjaus (`python3 -m aivo.tiivistelma`) vahvistaa ne. Chat liittää tiivistelmät työkalutilan kehotteeseen muun muistin rinnalle, enintään 60 kt. Osuvimmat ja uusimmat tulevat ensin. Yksityinen tila ei saa niitä koskaan.

Ota ensin snapshot kontista 122. Ajastin ei asennu itsestään: tämä on ohje, jonka Tony ajaa.

1. **Yhteys.** Avaa isännällä (Proxmox) kontin pääte ja varmista, että olet kontissa 122:

   ```
   pct enter 122
   hostname
   ```

   Odotettu tulos: komento `hostname` tulostaa kontin 122 nimen (ei isännän nimeä).

2. **Päivitä koodi ja käynnistä chat uudelleen**, jotta chat lukee tiivistelmät. Chatin palvelukäyttäjä selviää komennolla:

   ```
   systemctl show aivo-chat -p User
   ```

   Odotettu tulos: rivi `User=aivo`. Jos rivillä on muu nimi, käytä sitä nimeä alla kohdassa `User=` ja `runuser -u`-komennoissa.

3. **Kuiva-ajo.** Se vain listaa tiivistettävät keskustelut eikä kutsu mallia:

   ```
   runuser -u aivo -- env PYTHONPATH=/opt/agentti-pohja python3 -m aivo.tiivista --alue tyokalu --kuiva
   ```

   Odotettu tulos: rivit `tiivistettaisiin <keskustelun tunnus> viestit 0-N`, yksi kutakin tiivistämätöntä ja yli 30 minuuttia hiljaista keskustelua kohti. Jos keskusteluja ei ole, ei tule mitään.

4. **Yksikkö.** Tallenna tiedostoon `/etc/systemd/system/aivo-tiivista.service`:

   ```
   [Unit]
   Description=Aivon keskustelujen tiivistys (tyokalutila)

   [Service]
   Type=oneshot
   User=aivo
   WorkingDirectory=/opt/agentti-pohja
   Environment=PYTHONPATH=/opt/agentti-pohja
   Environment=AIVO_TYOKALU_SOCKET=/run/aivo-tyokalu.sock
   ExecStart=/usr/bin/python3 -m aivo.tiivista --alue tyokalu
   SupplementaryGroups=aivo-tyokalu-socket
   NoNewPrivileges=true
   ProtectSystem=strict
   ReadWritePaths=/var/lib/aivo
   PrivateTmp=true
   ```

   Käyttäjä ja ryhmä ovat samat kuin `aivo-chat.service`-yksikössä. Kaksi ajoa yhtä aikaa on turvallista: toinen ajo huomaa lukon ja päättyy.

5. **Ajastin** (15 minuutin välein). Tallenna tiedostoon `/etc/systemd/system/aivo-tiivista.timer`:

   ```
   [Unit]
   Description=Aivon tiivistys 15 minuutin valein

   [Timer]
   OnBootSec=5min
   OnUnitActiveSec=15min

   [Install]
   WantedBy=timers.target
   ```

6. **Käyttöönotto ja tarkistus.**

   ```
   systemctl daemon-reload && systemctl enable --now aivo-tiivista.timer
   systemctl list-timers aivo-tiivista.timer
   ```

   Odotettu tulos: ajastin näkyy listassa, ja `NEXT`-sarakkeessa on aika enintään 15 minuutin päässä.

7. **Ensimmäisen ajon tulos.** Ajon jälkeen:

   ```
   journalctl -u aivo-tiivista --since "20 min ago" --no-pager
   ls -l /var/lib/aivo/tiivistelmat
   ```

   Odotettu tulos: journaalissa rivit `tiivistetty: <tunnus> viestit 0-N, kohtia K, hylattyja lainauksia X, pudotettuja kohtia Y`. Hakemistossa on tiedostoja `<tunnus>-0-N.json` oikeuksilla `-rw-------`.

8. **Tiivistelmän katselu ja korjaus.** Tonyn korjaus kirjoittaa tiivistelmään kentän `tony_korjaus` ja vahvistaa kohdan:

   ```
   runuser -u aivo -- env PYTHONPATH=/opt/agentti-pohja python3 -m aivo.tiivistelma --kansio /var/lib/aivo/tiivistelmat lista
   ```

   Odotettu tulos: tiivistelmien tunnukset, yksi riville. Komento `nayta <tunnus>` näyttää lainaukset ja Aivon tulkinnan erillään.

Jos päiväkatto täyttyy, loki sisältää rivin `lopetus: paivakatto 10/10 taynna, tiivistamatta N keskustelua`. Ajo jatkuu seuraavana vuorokautena. Jos tiivistys epäonnistuu, journaalissa on rivi `epaonnistui: ...` ja virheen tyyppi. Sama viestialue yritetään enintään kahdesti, joten rikkinäinen keskustelu ei kuluta koko päiväkattoa.

## Testit

```
python3 -m unittest aivo.test_chat aivo.test_tiivista
```

Testit kattavat salasanan tiivisteen ja lukituksen, osoite- ja Host-rajat, CSRF-suojan, muistin lukemisen (ei linkkejä kirjaston ulkopuolelle), lähdeviitteiden tarkistuksen, päätöksen kirjaamisen sanasta sanaan, GitHub-pushin eston ja sen, että Claude-kutsu ei käytä työkaluja eikä välittäjiä.
