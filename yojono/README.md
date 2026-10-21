# Yöjono

Aikataulutettu ajuri, joka ajaa jonotiedoston tehtävät peräkkäin kulukaton sisällä ja kertoo tuloksen. Tarkoitus: kone tekee hyödyllistä, tarkistettavaa työtä (nyt koodikatselmointeja), vaikka kukaan ei ole paikalla. Ajuri ei merge, ei pushaa eikä ota mitään käyttöön: tuotos on aina raportti, jonka ihminen katselmoi.

Vain standardikirjasto, Python 3.10+. Testit: `python -m unittest discover -s . -t . -p 'test_*.py'` (repon juuresta).

## Mitä se tekee

1. Lukee `jono.json`-tiedoston ja tarkistaa jokaisen kentän (id, repo-nimi, budjetti).
2. Ohittaa valmiit tehtävät. Epäonnistunutta yritetään uudelleen vain myöhempänä päivänä ja enintään kaksi kertaa.
3. Varaa ennen jokaista tehtävää sen koko budjetin päiväkatosta. Jos jäljellä on vähemmän, tehtävä ohitetaan (pienempi voi mahtua).
4. Kutsuu tehtävätyypin skriptiä (`katselmointi` = `katselmoi.sh <repo> <budjetti>`), ilman shelliä, aikarajalla (30 min / tehtävä, 3 h / yö).
5. Lukee todellisen kulun skriptin tuottamasta JSON:sta (`total_cost_usd`), myös epäonnistuneesta ajosta. Jos ajo alkoi mutta kulua ei saada selville (aikakatkaisu, rikkinäinen JSON), kirjataan koko budjetti: katto ei saa alittua arvauksella.
6. Kirjaa tilan `tila.json`:iin heti jokaisen tehtävän jälkeen (atominen kirjoitus), joten katkennut ajo ei hukkaa kulukirjanpitoa.
7. Tulostaa yhteenvedon ja lähettää sen Telegramiin, jos `YOJONO_TELEGRAM_TOKEN` ja `YOJONO_TELEGRAM_CHAT` on asetettu. Telegram-tunnuksia ei anneta alaprosessille.

Lukko estää kaksi ajoa yhtä aikaa.

## Komennot

    python3 -B -m yojono kuiva   # näyttää mitä ajettaisiin, ei kutsu mitään, ei kirjoita tilaa
    python3 -B -m yojono ajo     # ajaa jonon
    python3 -B -m yojono tila    # tulostaa tila.json:n

Ympäristö: `YOJONO_PERUS` (oletus `/var/lib/yojono`), `YOJONO_KATSELMOI` (oletus `/opt/yojono/katselmoi.sh`).

## Jonotiedosto

Katso `jono.esimerkki.json`. `paivakatto` on USD:tä (0-50), tehtävän `budjetti` ei saa ylittää sitä. Valinnainen `kuukausikatto` (USD, vähintään päiväkatto, enintään 2000) pysäyttää ajon, kun kuukauden kulut + tehtävän budjetti ylittäisivät sen; kulut lasketaan tila.json:n päiväkirjanpidosta. `repo` on GitHub-repon nimi (vain kirjaimet, numerot, `_`, `.`, `-`). Tehtävätyypit: `kehitys` (`kehitys.sh`, `YOJONO_KEHITYS`; vaatii `aihe`-kentän `readme`/`testit`/`riippuvuudet`, repo PR-sallittujen listalta, katso `KEHITYS.md`), `katselmointi` (`katselmoi.sh`, ympäristö `YOJONO_KATSELMOI`) ja `ideointi` (`ideoi.sh`, `YOJONO_IDEOI`). Jokainen skripti kutsutaan `<skripti> <repo> <budjetti>` ja tuottaa `raportit/`-hakemistoon JSON:n (`total_cost_usd`) ja Markdown-raportin: `katselmointi` nimellä `<pvm>-<repo>`, muut nimellä `<pvm>-<tyyppi>-<repo>`. Ideointitehtävässä `repo` on aihealueen nimi (esim. `agenttifirma`).

Valinnainen `toisto_pv` (kokonaisluku 1-365) tekee tehtävästä toistuvan: valmis tehtävä ajetaan uudelleen, kun edellisestä valmiista ajosta on vähintään niin monta päivää. Ilman sitä valmis tehtävä ei aja koskaan uudelleen.

Huom: ajurin päiväkatto laskee kalenteripäivän. LiteLLM-avaimen oma budjetti nollautuu omassa tahdissaan ja on kova yläraja (se pysäyttää kutsut, vaikka ajuri erehtyisi). Pidä ajurin `paivakatto` enintään avaimen budjetin suuruisena.

## Käyttöönotto (ihminen tekee, ei automaattista)

Esimerkki CT115:ssä. Ota snapshot ensin (`pct snapshot 115 ennen-yojono-ajuri`, isännällä).

    git clone https://github.com/tonyweckstrom1987/agentti-pohja /opt/yojono-ajuri
    cp /opt/yojono-ajuri/yojono/jono.esimerkki.json /var/lib/yojono/jono.json
    cd /opt/yojono-ajuri && YOJONO_PERUS=/var/lib/yojono python3 -B -m yojono kuiva

Kun kuiva-ajo näyttää odotetut tehtävät, kokeile käsin yhdellä tehtävällä (pienennä jono ensin) ja tarkista raportti ja `tila`. Telegram on valinnainen: luo `/etc/yojono/telegram.env` (chmod 600) riveillä `YOJONO_TELEGRAM_TOKEN=...` ja `YOJONO_TELEGRAM_CHAT=...`. Älä lisää tiedostoa versionhallintaan.

Ajastus: kopioi `systemd/yojono.service.mall` ja `systemd/yojono.timer.mall` nimillä `yojono.service` ja `yojono.timer` hakemistoon `/etc/systemd/system/`, sitten `systemctl daemon-reload && systemctl enable --now yojono.timer`. Seuraava ajo: `systemctl list-timers 'yojono*' --no-pager`. Pysäytys: `systemctl disable --now yojono.timer`.

## Rajat

- Ei merge-, push- eikä käyttöönottotyyppejä. Uusi tehtävätyyppi vaatii oman suorittajan ja testit.
- Ajuri ei näe salaisuuksia: katselmoi.sh lukee ne itse omasta tiedostostaan.
