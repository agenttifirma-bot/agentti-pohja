# Tyopaikkaseuranta (agentti.tyopaikat)

Henkilokohtainen seuranta: hakee avoimia ilmoituksia julkisista lahteista, suodattaa hakusanoilla, poistaa jo nahdyt
ja laheta uudet Telegramiin `agentti.ilmoita`-polun kautta (sama tunnustiedosto kuin muilla ilmoituksilla, ei uusia tunnuksia).

## Lahdeselvitys (31.10.2026)

| Lahde | Tulos | Ehdot |
|---|---|---|
| Greenhouse `boards-api.greenhouse.io/v1/boards/<tunnus>/jobs` | toimii, ei tunnistautumista (testattu 200 JSON) | per yritys; tunnus = urasivun osoitteen loppuosa; robots.txt sallii |
| Lever `api.lever.co/v0/postings/<tunnus>?mode=json` | toimii, ei tunnistautumista (200 JSON) | per yritys; robots.txt: Allow, Crawl-delay 1 |
| Ashby `api.ashbyhq.com/posting-api/job-board/<tunnus>` | toimii, ei tunnistautumista (200 JSON) | per yritys; ei hakua/suodatusta rajapinnassa, suodatus tehdaan tassa |
| Yleinen RSS/Atom (yritysten omat feedit) | tuettu | vain https; DOCTYPE hylataan |
| Tyomarkkinatori hakurajapinta | EI kaytossa | vaatii organisaation Y-tunnuksen, KEHA-keskuksen hyvaksynnan ja kayttoehdot (tunnukset KIPA-alustan kautta); henkilolle ei sovellu. Julkisen sivuston `/api/` on robots.txt:ssa kielletty. Vanhat rajapinnat poistuvat toukokuussa 2027 |
| Duunitori | EI kaytossa | robots.txt: `User-agent: *` / `Disallow: /`; `/rss` antaa 404. Seurataan kasin tai Duunitorin omilla hakuvahdeilla |
| LinkedIn | EI kaytossa | scrapingin kielto |

Rajoite: ATS-rajapinnat kattavat vain ne yritykset, jotka listaat asetuksiin. Tunnuksia ei ole arvattu: etsi yrityksen urasivu
(`boards.greenhouse.io/<tunnus>`, `jobs.lever.co/<tunnus>`, `jobs.ashbyhq.com/<tunnus>`) ja lisaa se.

## Asetukset (tyopaikat.json)

```json
{
  "lahteet": [
    {"tyyppi": "greenhouse", "nimi": "Esimerkki Oy", "tunnus": "esimerkki"},
    {"tyyppi": "lever", "nimi": "Toinen Oy", "tunnus": "toinen"},
    {"tyyppi": "ashby", "nimi": "Kolmas Oy", "tunnus": "kolmas"},
    {"tyyppi": "rss", "nimi": "Nelja Oy", "osoite": "https://example.com/careers.rss"}
  ],
  "hakusanat": ["llmops", "mlops", "devops", "platform", "backend", "python", "healthtech", "harjoittelu"],
  "paikat": ["helsinki", "finland", "remote"]
}
```

`hakusanat` ja `paikat` ovat valinnaisia (oletushakusanat koodissa; ilman `paikat`-kenttaa sijaintia ei suodateta).
Haku kohdistuu otsikkoon ja tiimiin/osastoon, skandit ja isot kirjaimet ei haittaa.

## Kayttoonotto (Tony tekee itse; systemd/ on suojattu polku, siksi mallit ovat tassa)

1. Kokeile kuivana (ei lahetysta, ei kirjausta): `python3 -m agentti.tyopaikat --asetukset tyopaikat.json --tila /tmp/tp.json`
2. Asenna esim. `/opt/agentit/tyopaikat/` (koodi) ja `/etc/agentti/tyopaikat.json` (asetukset), tila `/var/lib/agentti/tyopaikat/`.
3. Ilmoita-polku lukee tunnukset `ILMOITA_TUNNUKSET` (oletus `/etc/yojono/telegram.env`) ja kirjaa rajatilan `ILMOITA_TILA`
   (oletus `/var/lib/yojono/ilmoita-tila.json`, kirjoitettava ajokayttajalle). Ilmoita-raja: 30 viestia/h. Yhdella ajolla
   lahetetaan enintaan 40 osumaa; loput tulevat seuraavalla ajolla.

`/etc/systemd/system/tyopaikat.service`:

```ini
[Unit]
Description=Tyopaikkaseuranta
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=agentti
Group=agentti
WorkingDirectory=/opt/agentit/tyopaikat
Environment=ILMOITA_TUNNUKSET=/etc/yojono/telegram.env
Environment=ILMOITA_TILA=/var/lib/agentti/tyopaikat/ilmoita-tila.json
ExecStart=/usr/bin/python3 -B -m agentti.tyopaikat --asetukset /etc/agentti/tyopaikat.json --tila /var/lib/agentti/tyopaikat/nahdyt.json --laheta
TimeoutStartSec=300
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agentti/tyopaikat
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
CapabilityBoundingSet=
```

`/etc/systemd/system/tyopaikat.timer` (aikavyohyke on UTC: 06:30 UTC = 08:30 Suomen talviaikaa):

```ini
[Unit]
Description=Tyopaikkaseuranta: paivittainen ajo

[Timer]
OnCalendar=*-*-* 06:30:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

Huom: `telegram.env`:n pitaa olla luettavissa `agentti`-kayttajalle (tai vaihda `User=`). Aktivointi: `systemctl daemon-reload && systemctl enable --now tyopaikat.timer`.
