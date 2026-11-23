# Aivon taustaajo (yksityinen tila)

Taustaajo tuo hitaan ajattelijamallin vastauksen keskusteluun myöhemmin. Keskustelu ei odota ajattelijaa. Koodi on tiedostossa `aivo/taustaajo.py`. Tämä muutos ei asenna mitään: alla olevat yksiköt ovat ohje, ja ylläpitäjä luo ne itse.

## Kulku

1. Keskustelija tai tiimi-yhdistelmä kirjoittaa työn jonoon funktiolla `taustaajo.kirjoita_tyo(jono, keskustelu, tehtava)`. Työssä on keskustelun tunnus, tehtävä englanniksi ja tehtävän sha-256. Kutsuja kertoo käyttäjälle, että syvempi analyysi on tulossa (`taustaajo.TULOSSA_TEKSTI`).
2. Ajastin käynnistää ajurin (`python3 -m aivo.taustaajo`). Ajuri ottaa työt vanhin ensin. Ajattelija vastaa englanniksi, ja keskustelija muotoilee vastauksen suomeksi.
3. Valmis vastaus lisätään keskustelun jsonl-tiedostoon rivinä, jonka rooli on `aivo` ja jossa on kenttä `tausta`. Teksti alkaa merkinnällä `[Syvempi analyysi valmis]`.
4. Chat-sivu kysyy reittiä `GET /api/tausta?keskustelu=ID&alkaen=N` 30 sekunnin välein, kun yksityinen keskustelu on auki ja välilehti näkyvissä. Uudet taustaviestit näkyvät keskustelussa.
5. Jos työ epäonnistuu, keskusteluun tulee merkintä `[Syvempi analyysi epäonnistui]` ja syy: aikaraja, päiväraja, kulukatto, mallivirhe, keskeytynyt ajo tai virheellinen työ.

Työtiedostoja ei poisteta. Ne siirretään jonon alikansioihin `kesken/`, `valmiit/` ja `epaonnistuneet/`.
Jos siirto ei onnistu (esimerkiksi levy on täynnä), lokiin tulee rivi `siirto epaonnistui: <tunnus> (<virheen tyyppi>, <kansio>)`, ja ajo jatkuu seuraavaan työhön. Jos työtä ei saada siirrettyä `kesken/`-kansioon, sitä ei ajeta eikä päiväpaikkaa varata. Työ jää jonoon, ja seuraava ajo yrittää sitä uudelleen.

## Kansiot

| Polku | Oikeudet | Sisältö |
|---|---|---|
| `/var/lib/aivo-yksityinen/tyot/` | 0700, palvelun käyttäjä | odottavat työt `<tunnus>.json` (0600) |
| `.../tyot/kesken/`, `valmiit/`, `epaonnistuneet/` | 0700 | työn tila |
| `.../tyot/tila.json` | 0600 | päivälaskuri (Europe/Helsinki) |
| `.../tyot/taustaajo.log` | 0600 | loki: vain tunnus, tulos ja virheen tyyppi |

Ajuri kieltäytyy toimimasta, jos jono tai keskustelukansio on linkki, kuuluu toiselle käyttäjälle tai on laajemmin kuin 0700. Työkalutilan käyttäjä (`aivo-tyokalu`) ei siksi pääse jonoon, eikä työkalutilan koodi tunne jonon polkua.

## Rajat

- Enintään `AIVO_TAUSTA_PAIVARAJA` työtä vuorokaudessa (oletus 5). Asetus ei voi ylittää koodin ylärajaa 20. Työ varataan laskuriin ennen ensimmäistä mallikutsua.
- Työn kokonaisaikaraja `AIVO_TAUSTA_AIKARAJA_S` (oletus 600 s, yläraja 900 s). Kukin kutsu saa enintään jäljellä olevan ajan. Yksittäisen kutsun yläraja on `yksityinen_or.TAUSTA_AIKARAJA_S` (600 s). Chatin oma 120 sekunnin raja ei muutu.
- Enintään kaksi mallikutsua työtä kohden.
- Kutsut kulkevat vain funktion `yksityinen_or.kysy_taustatyo` kautta. Malli tarkistetaan funktiolla `avoin_malli()`, ZDR ja `data_collection=deny` pakotetaan, ja yhteinen päiväkatto (10 €/vrk, A1005) tarkistetaan ennen kutsua. Kulut kirjataan tehtävätunnuksella `aivo-yksityinen-tausta`. Vastauksen enimmäispituus on sama kuin chatissa (`yksityinen.MAX_TOKENIA`).
- Taustavastaus ei voi tehdä ehdotuksia eikä päätöksiä, koska kaikki `[[ ]]`-merkinnät poistetaan.
- Uusia verkkokohteita ei ole.

## Roolit ja mallit

Ajuri lukee samat asetukset kuin chat:

- `AIVO_OPENROUTER_MALLIT` (tai `AIVO_OPENROUTER_MALLI`): sallitut avoimet mallit.
- `AIVO_YKSITYINEN_ROOLIT`: ajuri lukee vain roolit `keskustelija` ja `ajattelija`. Muut roolit se ohittaa. Puuttuva rooli käyttää listan ensimmäistä mallia. Roolin mallin pitää olla sallittujen listalla.
- `AIVO_OPENROUTER_AVAIN`: sama avaintiedosto kuin chatilla (0600, palvelun käyttäjän oma).

Ajuri toimii vain OpenRouter-taustapäällä. Jos `AIVO_YKSITYINEN_TAUSTAPAA=loopback`, se päättyy virheeseen.

## Yksiköt (ohje, ei asennettu)

Käyttäjän pitää olla sama kuin `aivo-chat.service`-palvelun `User=` (kontissa `aivo`), koska jono, keskustelut ja avain tarkistetaan palvelun käyttäjän omiksi. Tarkista: `systemctl show -p User aivo-chat`.

1. **Kuiva-ajo** (ei mallikutsuja):

   ```
   runuser -u aivo -- env PYTHONPATH=/opt/agentti-pohja AIVO_OPENROUTER_MALLI=qwen/qwen3-235b-a22b-2507 python3 -m aivo.taustaajo --kuiva
   ```

   Odotettu tulos: rivit `ajettaisiin <tunnus>` tai ei mitään, jos jono on tyhjä.

2. **Yksikkö** `/etc/systemd/system/aivo-taustaajo.service`:

   ```
   [Unit]
   Description=Aivon taustaajo (yksityinen tila, OpenRouter ZDR)

   [Service]
   Type=oneshot
   User=aivo
   WorkingDirectory=/opt/agentti-pohja
   Environment=PYTHONPATH=/opt/agentti-pohja
   Environment=AIVO_YKSITYINEN_TAUSTAPAA=openrouter
   Environment=AIVO_OPENROUTER_MALLIT=qwen/qwen3-235b-a22b-2507
   Environment=AIVO_YKSITYINEN_ROOLIT=keskustelija:qwen/qwen3-235b-a22b-2507,ajattelija:qwen/qwen3-235b-a22b-2507
   Environment=AIVO_TAUSTA_PAIVARAJA=5
   Environment=AIVO_TAUSTA_AIKARAJA_S=600
   ExecStart=/usr/bin/python3 -m aivo.taustaajo
   TimeoutStartSec=20min
   NoNewPrivileges=true
   ProtectSystem=strict
   ProtectHome=yes
   ReadWritePaths=/var/lib/aivo-yksityinen /var/lib/claude-jono
   PrivateTmp=true
   ```

   Vaihda mallit samoiksi kuin `aivo-chat.service`-tiedostossa. `/var/lib/claude-jono` on mukana, koska kulukirjanpito ja päiväkatto ovat siellä. Ilman sitä jokainen kutsu estyy (fail closed). Kaksi ajoa yhtä aikaa on turvallista: toinen huomaa lukon (`taustaajo.lukko`) ja päättyy.

3. **Ajastin** `/etc/systemd/system/aivo-taustaajo.timer` (minuutti edellisen ajon päättymisestä):

   ```
   [Unit]
   Description=Aivon taustaajo minuutin valein

   [Timer]
   OnBootSec=2min
   OnUnitInactiveSec=1min

   [Install]
   WantedBy=timers.target
   ```

4. **Käyttöönotto ja tarkistus:**

   ```
   systemctl daemon-reload && systemctl enable --now aivo-taustaajo.timer
   systemctl list-timers aivo-taustaajo.timer
   journalctl -u aivo-taustaajo --since "10 min ago" --no-pager
   ```

   Odotettu tulos: ajastin näkyy listassa. Journaalissa on rivejä `valmis: <tunnus>, kutsuja 2` tai `epaonnistui: <tunnus> (<syy>)`, tai ei rivejä, jos jono oli tyhjä. Kulut näkyvät viikkoraportissa: `python3 -m aivo.openrouter_kulut viikko`.

## Riippuvuus

Työn kirjoittaja on tiimi-yhdistelmä (keskustelija, ajattelija ja kevyt malli). Ennen kuin se on käytössä, `kirjoita_tyo` on valmis rajapinta, mutta chat ei vielä kutsu sitä. Ajuri ja `/api/tausta` toimivat ilman sitä.
