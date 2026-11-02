# Claude-jono

Pilvi-Claude ei pääse Tailscale-verkkoon, mutta molemmat pääsevät GitHubiin. Siksi tehtävät kulkevat docs-repon (`agenttifirma-docs`) kautta:

1. Pilvi-Claude kirjoittaa tehtävän `claude-jono/tehtavat/YYYY-MM-DD-NN-nimi.md`.
2. CT115:n ajastin (10 min edellisen ajon päättymisestä) ajaa `python3 -m claudejono ajo`: hakee repon, ottaa vanhimman tehtävän ilman tulosta, ajaa `claude -p` (tilaus), kirjoittaa `claude-jono/tulokset/<sama nimi>.md` ja pushaa vain sen. Yhteenveto Telegramiin, jos `/etc/yojono/telegram.env` on olemassa.
3. Pilvi-Claude lukee tulokset ja kirjoittaa seuraavat tehtävät (ajastettu tehtävä 3×/vrk).
4. **Itsesuunnittelu** (Tony hyväksyi 30.10.2026): kun jono on tyhjä, CT115:n Claude ehdottaa jatkotehtävät (`suunnittelu.md`). Ajuri nimeää ne `<pvm>-NN-auto-<nimi>.md`, rajaa enintään 2 / ajo ja 30 / vrk (`AUTO_MAX_PAIVA`, koodissa) ja kirjaa Tonyn päätettävät `claude-jono/tonylle.md`:hen. Pois päältä: `Environment=CLAUDEJONO_ITSESUUNNITTELU=0`. Tyhjän kierroksen jälkeen suunnittelu pitää tauon (oletus 3 h, `CLAUDEJONO_SUUNNITTELU_TAUKO_S`), ellei uusi tulos ole tullut.

Rajat (Tony hyväksyi 30.10.2026, doc 71): PR-taso, ei mergeä, ei katto-/oikeusmuutoksia, ei salaisuuksia, ei poistoja. Kehote: `kehote.md`. Ajuri committaa vain tulostiedostot, `-auto-`-tehtävät ja `tonylle.md`:n (testattu).

## Itsekehittyvä silmukka (Tonyn linjaus 2.11.2026 klo 16.10)

Kolme osaa, joiden koodi on `silmukka.py` ja `laatu.py`. Ne eivät muuta kulukattoja, oikeuksia eivätkä polkurajoja (`AUTO_MAX_PAIVA`, `AUTO_PER_AJO`, `sallittu_polku` ovat ennallaan).

1. **Jono ei tyhjene.** Kun avoimia tehtäviä on alle 5 (`silmukka.AVOIMIA_ALARAJA`), ajuri kutsuu itsesuunnittelua jo ennen kuin jono on tyhjä, ja ajaa silti vuorossa olevan tehtävän. Suunnittelun kaatuminen ei estä tehtävää. Suunnittelija kirjoittaa pisteytetyt tehtävät (`Pisteet:`- ja `Suunta:`-rivi). **Porttitarkistin** hylkää tehtävän, jos rivit puuttuvat. Tarkistin ohjaa tehtävän Tonyn sunnuntaiehdotuksiin (`tonylle.md`, rivi alkaa `Sunnuntaiehdotus (syy)`), jos se koskee julkaisua, rahaa, oikeuksia, kulukattoja, ajastuksia tai uutta suuntaa. Tarkistin on karkea sanalista, ja kieltolauseet ("ei saa muuttaa kattoja") ohitetaan. Se on lisävartija, ei ainoa raja: tehtävän suorittajaa sitovat silti kehotteen rajat ja ajurin polkuraja.
2. **Viikoittainen optimointikierros.** Pohja `toistuvat/optimointi.md` (tehtävä 43). Ajuri luo siitä tehtävän `<pvm>-NN-auto-optimointi.md`, kun edellisestä on 7 päivää eikä edellinen odota ajoa. Luonti ei tarvitse uutta ajastinta: se tapahtuu `claude-jono.service`-ajon alussa. Tehtävä kuuluu itse keksittyjen tehtävien päivärajaan.
3. **Päivittäinen laatuotos.** `python3 -m claudejono laatu` valitsee 2–3 satunnaista eilistä tulosta. Eri `claude -p` -istunto tarkistaa ne lähteitä vasten työkaluilla `Read`, `Grep` ja `Glob` (`--tools`, `--no-session-persistence`). Tulos kirjataan tiedostoon `$CLAUDEJONO_TYOHAK/laatu-tila.json` (ei docs-repoon). Vakava virhe vaatii todisteen (lähteen polku ja lainaus), muuten se lasketaan lieväksi. `python3 -m claudejono mittari` tulostaa aamukoosteen mittaririvin: otoksen tulos, hyväksytyt ja hylätyt PR:t, uudet virhelokimerkinnät ja puuttuvat "Todennettu käytössä" -rivit.
4. **Pysäytysehto.** Jos laatuotos löytää vakavan virheen kahtena kalenteripäivänä peräkkäin, itsesuunnittelu ja toistuvat tehtävät pysähtyvät ja Telegramiin lähtee `HALYTYS`-viesti. Pysäytys poistuu vain komennolla `python3 -m claudejono vapauta`. Jo jonossa olevat tehtävät ajetaan edelleen.

**Käyttöönotto (Tony, ajastinmuutos):** kopioi `systemd/claude-laatu.service.mall` ja `claude-laatu.timer.mall` hakemistoon `/etc/systemd/system/` ilman `.mall`-päätettä, aja `systemctl daemon-reload` ja `systemctl enable --now claude-laatu.timer`. Kokeile ensin: `systemctl start claude-laatu.service` ja `journalctl -u claude-laatu -n 20 --no-pager`. Aamukoosteen (PR #160) valmistuttua mittaririvin voi liittää koosteeseen kutsulla `claudejono.laatu.mittaririvi(tyohak, repo, nyt)`.

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
