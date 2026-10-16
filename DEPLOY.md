# Käyttöönotto

Esimerkissä agentin nimi on `uutiset`. Vaihda se omaksesi. Komennot ajetaan palvelimella (esim. LXC-kontissa) root-käyttäjänä, ellei toisin mainita. **Salaisuudet kirjoittaa omistaja itse**; älä liitä niitä chattiin, tikettiin tai commitiin.

## 1. Tee pohjasta oma agentti

Omalla koneella:

```bash
python luo.py uutiset
python -m unittest discover -s . -t . -p 'test_*.py'
python -m agentti --agentti uutiset      # kuiva-ajo
```

## 2. Käyttäjä ja hakemistot

```bash
useradd --system --no-create-home --shell /usr/sbin/nologin agentti
install -d -o root -g root -m 755 /opt/agentit/uutiset
install -d -o agentti -g agentti -m 700 /var/lib/agentti/uutiset
install -d -o root -g root -m 755 /etc/agentti
```

Kopioi hakemisto `agentti/` (agentin oma moduuli mukana) kohteeseen `/opt/agentit/uutiset/agentti/`. Koodin omistaa root, jotta agentti ei voi muokata omaa koodiaan. `luo.py`, `test/` ja `systemd/` eivät kuulu palvelimelle (systemd-tiedostot kopioidaan kohdassa 5).

## 3. Salaisuudet

Luo `/etc/agentti/uutiset.env` itse editorilla ja aseta oikeudet:

```
LLM_BASE_URL=http://<litellm-osoite>:4000/v1
LLM_API_KEY=<agentin oma virtuaaliavain>
TELEGRAM_BOT_TOKEN=<botin token>
TELEGRAM_CHAT_ID=<oma chat-id>
SYDAN_URL=<valinnainen: Uptime Kuma push-osoite>
```

```bash
chown root:root /etc/agentti/uutiset.env && chmod 600 /etc/agentti/uutiset.env
```

Suositus: anna agentille oma LiteLLM-virtuaaliavain, jolla on vain tarvittava malli ja oma budjetti. Koodin kulukatto (`rajat.py`) on toinen, riippumaton suoja.

## 4. Ensimmäinen ajo: kuiva-ajosta lähetykseen

Ajo samoilla rajoitteilla kuin ajastettu palvelu:

```bash
systemd-run --wait --pipe --collect -p User=agentti -p WorkingDirectory=/opt/agentit/uutiset \
  -p EnvironmentFile=/etc/agentti/uutiset.env -p NoNewPrivileges=true -p ProtectSystem=strict \
  -p ReadWritePaths=/var/lib/agentti/uutiset -p PrivateTmp=true \
  /usr/bin/python3 -B -m agentti --agentti uutiset --tila /var/lib/agentti/uutiset
```

Etene järjestyksessä ja tarkista tulos jokaisen jälkeen:

1. ilman lippuja: kuiva-ajo, ei verkkoa
2. `--llm`: yksi oikea mallikutsu (kuluu senttejä); tarkista, että tulos on järkevä tai `ei_tietoa`
3. `--llm --send`: lähtee Telegramiin kerran päivässä
4. vasta sitten ajastin

## 5. Ajastin

```bash
cp systemd/agentti-uutiset.service systemd/agentti-uutiset.timer /etc/systemd/system/
timedatectl                      # tarkista aikavyöhyke: OnCalendar käyttää palvelimen aikaa
systemctl daemon-reload
systemctl enable --now agentti-uutiset.timer
systemctl list-timers agentti-uutiset.timer
```

Seuraa lokia: `journalctl -u agentti-uutiset.service --no-pager | tail -40`.

## 6. Valvonta (valinnainen mutta suositeltu)

Tee Uptime Kumassa Push-monitori, jonka heartbeat-väli on hieman ajastusväliä pidempi (päivittäiselle agentille esim. 26 h), ja laita sen osoite `SYDAN_URL`-muuttujaan. Pingi lähtee vain onnistuneen ajon jälkeen, joten puuttuva ping tarkoittaa ongelmaa.

## Palautus ja pysäytys

- Pysäytä heti: `systemctl disable --now agentti-uutiset.timer`
- Palauta koodi: kopioi edellinen versio `/opt/agentit/uutiset`-hakemistoon (ota kontista tilannekuva ennen jokaista päivitystä).
- Kulutilanne: `cat /var/lib/agentti/uutiset/kulu.json`
- Katon ylittyessä agentti lähettää varaviestin virhekoodilla `kulukatto_*`. Älä nosta rajoja ennen kuin tiedät, miksi kulu kasvoi.
