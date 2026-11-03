# Claude-jono

Pilvi-Claude ei pääse Tailscale-verkkoon, mutta molemmat pääsevät GitHubiin. Siksi tehtävät kulkevat docs-repon (`agenttifirma-docs`) kautta:

1. Pilvi-Claude kirjoittaa tehtävän `claude-jono/tehtavat/YYYY-MM-DD-NN-nimi.md`.
2. CT115:n ajastin (10 min edellisen ajon päättymisestä) ajaa `python3 -m claudejono ajo`: hakee repon, ottaa vanhimman tehtävän ilman tulosta, ajaa `claude -p` (tilaus), kirjoittaa `claude-jono/tulokset/<sama nimi>.md` ja pushaa vain sen. Yhteenveto Telegramiin, jos `/etc/yojono/telegram.env` on olemassa.
3. Pilvi-Claude lukee tulokset ja kirjoittaa seuraavat tehtävät (ajastettu tehtävä 3×/vrk).
4. **Itsesuunnittelu** (Tony hyväksyi 30.10.2026): kun jono on tyhjä, CT115:n Claude ehdottaa jatkotehtävät (`suunnittelu.md`). Ajuri nimeää ne `<pvm>-NN-auto-<nimi>.md`, rajaa enintään 2 / ajo ja 30 / vrk (`AUTO_MAX_PAIVA`, koodissa) ja kirjaa Tonyn päätettävät `claude-jono/tonylle.md`:hen. Pois päältä: `Environment=CLAUDEJONO_ITSESUUNNITTELU=0`. Tyhjän kierroksen jälkeen suunnittelu pitää tauon (oletus 3 h, `CLAUDEJONO_SUUNNITTELU_TAUKO_S`), ellei uusi tulos ole tullut.

Rajat (Tony hyväksyi 30.10.2026, doc 71): PR-taso, ei mergeä, ei katto-/oikeusmuutoksia, ei salaisuuksia, ei poistoja. Kehote: `kehote.md`. Ajuri committaa vain tulostiedostot, `-auto-`-tehtävät ja `tonylle.md`:n (testattu).

## Käyttöönotto CT115:ssä (Tony, kerran)

1. `claude` → `/status`: kirjautuminen tilauksella (ei API-avainta).
2. Deploy key: `install -d -m 700 /etc/claude-jono && ssh-keygen -t ed25519 -N '' -f /etc/claude-jono/deploy_key -C claude-jono-ct115`. Lisää `deploy_key.pub` GitHubissa: agenttifirma-docs → Settings → Deploy keys → **Allow write access**.
3. Klooni: `install -d /var/lib/claude-jono && GIT_SSH_COMMAND='ssh -i /etc/claude-jono/deploy_key -o IdentitiesOnly=yes' git clone git@github.com:tonyweckstrom1987/agenttifirma-docs.git /var/lib/claude-jono/docs` ja `git -C /var/lib/claude-jono/docs config user.name claude-jono-ct115`, `git -C /var/lib/claude-jono/docs config core.sshCommand 'ssh -i /etc/claude-jono/deploy_key -o IdentitiesOnly=yes'` + `user.email` (botin osoite).
4. Koodi: `git clone https://github.com/tonyweckstrom1987/agentti-pohja /opt/agentti-pohja` (tai päivitä).
5. Lupatila: aja kerran käsin `cd /opt/agentscope && claude -p "aja: git -C /opt/agentti-pohja log -1 --oneline" --output-format json --max-turns 3` ja katso, pysähtyykö komento lupakyselyyn. Jos pysähtyy, lisää palveluun `Environment=CLAUDEJONO_LUPATILA=<tila>` (esim. `auto`, jos versio tukee sitä headless-ajossa) ja testaa uudelleen.
6. Kuivakoe: `cd /opt/agentti-pohja && CLAUDEJONO_REPO=/var/lib/claude-jono/docs GIT_SSH_COMMAND='ssh -i /etc/claude-jono/deploy_key -o IdentitiesOnly=yes' python3 -m claudejono seuraava`.
7. Asenna: kopioi `systemd/*.mall` → `/etc/systemd/system/` ilman `.mall`-päätettä, `systemctl daemon-reload`, `systemctl start claude-jono.service` (yksi ajo, katso `journalctl -u claude-jono`), sitten `systemctl enable --now claude-jono.timer`.

## Oma käyttäjä (Tonyn päätös 30.10.2026)

Ajuri jää rootiksi (git, deploy key, Telegram), mutta agentti ajetaan käyttäjänä `claudejono` (`CLAUDEJONO_KAYTTAJA`, `runuser`). Agentti kirjoittaa vain `/opt/agentscope/tyo`:hon ja kotiinsa; se ei lue deploy keytä, botin tunnusta eikä voi muuttaa yöjonon kattoja. PR:t avataan `sudo -u prbotti /usr/local/sbin/claudejono-pr`:llä: `prbotti` yksin lukee tunnuksen, ja haarat haetaan sen omaan tilapäisrepoon, jotta agentin `.git/config` ei aja komentoja prbottina.

1. `sh /opt/agentti-pohja/claudejono/asenna-kayttaja.sh` (tulostaa tarkistuksen).
2. `runuser -l claudejono -c 'curl -fsSL https://claude.ai/install.sh | bash'` ja `runuser -l claudejono -c '~/.local/bin/claude'` → `/login` tilauksella.
3. Päivitä palvelu mallista (`CLAUDEJONO_KAYTTAJA`, `CLAUDEJONO_CLAUDE`), `systemctl daemon-reload`.

Peruutus: `systemctl disable --now claude-jono.timer` ja poista deploy key GitHubista.

## Korjaaja: kaatuminen käynnistää diagnoosin (Tonyn toive 31.10.2026)

Valvottu autonomia: agentti **diagnosoi ja ehdottaa, Tony hyväksyy**. Ei uudelleenkäynnistyksiä, ei asetusmuutoksia, ei mergeä.

Ketju: valvottu yksikkö kaatuu → `OnFailure=korjaaja@%n.service` → `python3 -m claudejono.korjaaja <yksikkö>` (root) →
1. tarkistukset: nimi, valvottujen lista (`claude-jono`, `yojono`, `trendit-paiva`, `trendit-viikko`, `kauppatiimi-*`), silmukan esto,
2. toistoraja: sama yksikkö enintään 1 diagnoosi / 6 h; päiväkatto 8 diagnoosia / vrk yhteensä (kustannuskatto). Raja kirjataan *ennen* ajoa (`/var/lib/korjaaja/tila.json`), joten kaatuva diagnoosi ei kierrä sitä,
3. ajuri kerää rootina `journalctl -u <yksikkö> -n 80`, puhdistaa (ohjausmerkit pois, rivi max 400 merkkiä, yht. 16 kt, `<loki>`-tagit neutraloitu) ja antaa tekstinä. Agentti ei saa journal-oikeuksia tätä varten. Loki on **dataa**: kehote kieltää noudattamasta sen sisältämiä ohjeita,
4. Claude ajetaan käyttäjänä `claudejono` (runuser, kuten claude-jono), aikaraja 10 min (prosessiryhmä tapetaan), max 20 kierrosta,
5. tulos: `claude-jono/korjaukset/<pvm>-<yksikkö>.md` docs-repoon (ajuri committaa vain tämän polkumuodon, `ajuri.sallittu_polku` ei muutu) + Telegram-tiivistelmä. Selvä koodivika: agentti avaa korjaus-PR:n normaalisti `claudejono-pr`:llä.

Silmukan esto kolmessa kerroksessa: `korjaaja@.service`:llä ei ole `OnFailure=`-riviä; koodi hylkää `korjaaja*`-yksiköt; valvottujen lista ei sisällä niitä.

### Asennus (Tony, kerran; ei tehdä automaattisesti)
```
cp claudejono/systemd/korjaaja@.service.mall /etc/systemd/system/korjaaja@.service
for u in claude-jono yojono trendit-paiva trendit-viikko; do
  install -d /etc/systemd/system/$u.service.d
  cp claudejono/systemd/korjaaja-onfailure.conf.mall /etc/systemd/system/$u.service.d/korjaaja.conf
done
systemctl daemon-reload
```
Huom: `yojono.service.d` ja `trendit-*.service.d` sisältävät jo `OnFailure=virheilmoitus@%N.service`; useampi `OnFailure=` kertyy listaksi, molemmat laukeavat. Kuivakoe: `systemctl start korjaaja@trendit-paiva.service.service` (trendit-paiva on nyt `failed`).
Peruutus: poista drop-in-tiedostot ja `systemctl daemon-reload`.

Huom turvallisuudesta: `asenna-kayttaja.sh` lisää `claudejono`n ryhmään `systemd-journal` (diagnostiikkaan). Korjaaja ei sitä tarvitse; ryhmän voi poistaa Tonyn päätöksellä (ehdotus, ei muutettu tässä PR:ssä).

### Muut kontit (suunnitelma)
CT116/CT117 jne. eivät näy CT115:n systemd:lle. Vaihtoehto: kunkin CT:n oma `OnFailure`-yksikkö kirjoittaa lokin (rajattu, puhdistettu) docs-repon `claude-jono/korjaukset/syote/`-kansioon tai kutsuu tätä samaa moduulia SSH:n yli vain luku -avaimella. Päätös Tonylle; tässä PR:ssä vain CT115.

### Seuraava porras (Tonyn päätettäväksi, EI toteutettu)
Sallittu lista turvallisia toimia, esim. `systemctl reset-failed <yksikkö>` + **yksi** uudelleenkäynnistys, vain valvottujen listan yksiköille, ajurin (ei agentin) suorittamana ja vain kun agentin diagnoosi on luokiteltu tyyppiin "ohimenevä" (esim. verkkovirhe). Edellytys mittareille: vähintään ~10 diagnoosia, joista Tony on merkinnyt osuneiksi ≥ 80 % (lisää `korjaukset/`-tiedostoon rivi "Osuiko: kyllä/ei"), eikä yhtään väärää toimintaehdotusta. Toimi kirjataan lokiin ja rajataan 1 / yksikkö / vrk. Tämä on oikeusmuutos, joten se vaatii Tonyn nimenomaisen luvan erikseen.

## Aamukooste ja ilmoitusten rajaus

**Aamukooste** (`python3 -m claudejono.aamukooste`) kokoaa yhden Telegram-viestin: enintään viisi riviä (tehty, tarvitaan sinulta, opittu, hälytykset, kulut) ja linkit. Lähteet ovat edellisen vuorokauden tulokset, `tonylle.md`:n uudet kohdat, avoimet PR:t (GitHubin julkinen API, ei tunnuksia), yöjonon tila (`tila.json`, `jono.json`, vain luku) ja systemd:n failed-yksiköt. Napit ovat GitHub-linkkejä: mergattavien PR:ien sivut (merge-painike on PR-sivulla). Jos GitHub-haku epäonnistuu (esim. 60 haun tuntiraja), rivi kertoo sen eikä näytä tyhjää listaa onnistumisena.

Kuiva-ajo (ei lähetä): `cd /opt/agentti-pohja && python3 -B -m claudejono.aamukooste`. Lähetys vain lipulla `--laheta`. Testibotti: aseta `YOJONO_TELEGRAM_TOKEN` ja `YOJONO_TELEGRAM_CHAT` testibotin arvoiksi tilapäisessä ympäristötiedostossa ennen ensimmäistä lähetystä.

**Ilmoitusten rajaus** (`CLAUDEJONO_ILMOITUKSET`): oletus `heti` säilyttää nykyisen käytöksen (kaikki viestit lähtevät heti). Arvolla `kooste` heti lähtevät vain viestit, jotka alkavat sanalla `HALYTYS` tai `PAATOS` (kaatumishälytys, yöjonon hälytysrivi, päätöstä vaativat asiat, `agentti.ilmoita virhe|paatos`). Muut tulos- ja raporttiviestit jäävät pois ja näkyvät aamukoosteessa. Tuntematon arvo tulkitaan arvoksi `heti`. Rajaus on yhdessä paikassa (`yojono.ajuri.laheta_telegram`), ja aamukooste ohittaa sen itse (`pakota=True`). Muut lähettäjät (`agentti.aamupaketti --laheta`, `agentti.ajo`) eivät noudata asetusta.

**Viikkoehdotus** (`python3 -m claudejono.viikkoehdotus`) kirjoittaa tiedoston `<vvvv-vv>-ehdotus.md` (hyöty × varmuus / vaiva). Ehdokkaat tulevat jonon tehtävistä, joilla ei ole tulosta ja joilla on `Pisteet:`-rivi, viimeisen 7 vuorokauden epäonnistuneista tai hylätyistä tehtävistä sekä valinnaisesta tiedostosta `claude-jono/ehdokkaat.md` (rivi: `- nimi | hyöty | varmuus | vaiva h | tavoite`). Pisteitä ei keksitä: välitavoite, jolle ei ole pisteytettyä ehdokasta, listataan erikseen aukkona. Oletushakemisto on `/var/lib/claude-jono/viikko` eli docs-kloonin ulkopuolella, koska ajuri saa committaa vain sallitut polut (`sallittu_polku`). Jos tiedoston haluaa docs-repoon, polkulistan laajennus on Tonyn päätös.

### Asennus (Tony)

```
install -d /var/lib/claude-jono/viikko
cd /opt/agentti-pohja/claudejono/systemd
for n in claude-aamukooste claude-viikkoehdotus; do
  cp $n.service.mall /etc/systemd/system/$n.service
  cp $n.timer.mall /etc/systemd/system/$n.timer
done
systemctl daemon-reload
systemctl start claude-aamukooste.service     # yksi testilähetys (testibotilla tai omaan chattiin)
systemctl enable --now claude-aamukooste.timer claude-viikkoehdotus.timer
systemctl list-timers 'claude-*'
```

Ajastus on Helsingin aikaa (`OnCalendar=... Europe/Helsinki`), joten kesäaika ei siirrä kellonaikaa vaikka palvelimen aikavyöhyke on UTC. Kääntäminen päälle: lisää `Environment=CLAUDEJONO_ILMOITUKSET=kooste` tiedostoon `claude-jono.service` (ja yojono-palveluun), `daemon-reload`. Peruutus: poista rivi tai aseta arvoksi `heti`.
