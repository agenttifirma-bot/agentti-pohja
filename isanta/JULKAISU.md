# Julkaisukomento (`isanta/julkaise.sh`)

Yksi skripti Proxmox-isännälle (root), jolla julkaistaan ja peruutetaan kolme kohdetta: **kauppatiimi** (CT119), **infra-automaatio** (CT118) ja **yojono-ajuri / agentti-pohja** (CT115). Isäntä ohjaa kaiken `pct`-komennoilla: kontteihin ei tule uusia skriptejä, oikeuksia, avaimia tai salaisuuksia.

## Periaate: koodi, tila ja konfiguraatio erillään

Julkaisu ja peruutus vaihtavat **vain koodihakemiston** (sisarhakemisto + `mv`, polut ennallaan). Tilakansio ja konfiguraatio eivät muutu: niiden sha256-tiiviste (sisältö, nimet, oikeudet, ei aikaleimoja) lasketaan ennen ja jälkeen, ja ero keskeyttää ajon (`TILAKANSIO MUUTTUI`). Konfiguraation sisältöä ei lueta tulosteisiin eikä kopioida.

| Kohde | CT | Koodi (vaihdetaan) | Tila (ei muutu) | Konfiguraatio (ei muutu) |
|---|---|---|---|---|
| `kauppatiimi` | 119 | `/srv/kauppa/k1` | `/srv/kauppa/data`, `/srv/kauppa/logs` | `/srv/kauppa/.env`, `llm.env` |
| `infra-automaatio` | 118 | `/opt/infra-automaatio` | `/var/lib/infra-automaatio` | `/etc/infra-automaatio/` |
| `yojono-ajuri` | 115 | `/opt/yojono-ajuri` | `/var/lib/yojono` | `/etc/yojono/` |

Kohdekohtaiset asetukset ovat tiedostoissa `isanta/julkaisu/<kohde>.conf` (asennus: `/root/julkaisu/`). Ne ovat pelkkää dataa: skripti lukee ne rivi riviltä (ei `source`), sallii vain tunnetut avaimet ja turvalliset merkit, eikä niihin kuulu salaisuuksia.

## Paketti

`julkaise.sh` vaatii paketin, jossa on **commit-tunniste** (`git archive` tallentaa sen tar-otsikkoon) ja **tasan yksi ylätason hakemisto**. Muu paketti hylätään.

    git -C <repo> -c core.autocrlf=false -c core.eol=lf archive --format=tar --prefix="<kohde>-<commit8>/" <commit40> | gzip -n > <kohde>-<commit8>.tgz

Sama komento valmiina: `isanta/paketoi.sh <repo> <commit|ref> <kohde> [ulos-hakemisto]`. Se tulostaa commitin, sha256:n ja ajokomennot. Tarkistus: `gzip -dc paketti.tgz | git get-tar-commit-id` palauttaa täsmälleen commitin ja `tar tzf` näyttää vain etuliitteen `<kohde>-<commit8>/`. Kohteen nimi: `kauppatiimi`, `infra-automaatio` tai `yojono-ajuri` (jälkimmäisen repo on agentti-pohja). Private-repon (infra-automaatio) paketti tehdään muualla kuin isännällä, koska isäntä ei saa lukea sitä ilman uutta tunnusta.

## Käyttö

    scp <kohde>-<commit8>.tgz root@<isanta>:/root/
    bash /root/julkaise.sh <kohde> /root/<kohde>-<commit8>.tgz <commit40> <sha256> --kuiva
    bash /root/julkaise.sh <kohde> /root/<kohde>-<commit8>.tgz <commit40> <sha256>

Ensimmäinen julkaisu kullekin kohteelle vaatii lisäksi `--ensijulkaisu` (kohteella ei vielä ole julkaisumanifestia). Silloin nykyinen koodi siirtyy `…prev-<aika>`-kansioon manifestin kanssa, ja peruutus palauttaa sen. Yojonolla se tarkoittaa, että git-klooni siirtyy prev-kansioon ja `git pull` -päivitys lakkaa (tarkoituksella).

| Komento | Mitä tekee |
|---|---|
| `julkaise.sh <kohde> <paketti> <commit> <sha256>` | julkaisu |
| `… --kuiva` | esitarkistukset + paketin tarkistus, ei muuta mitään (ei kontissa, ei lokia, ei snapshotia) |
| `… --kanaria` | lisää tahallaan rikkinäisen esitarkistuksen ja todistaa, että ajo keskeytyy ilman kirjoituksia (`OK: KANARIA …`) |
| `… --uudelleen` | asentaa saman commitin uudelleen (muuten `jo asennettu`) |
| `… --salli-ei-karki` | julkisella repolla sallii commitin, joka ei ole `main`:n kärki; kirjataan lokiin (`POIKKEUS=salli-ei-karki`) |
| `julkaise.sh <kohde> --peruuta` | palauttaa vain koodin edelliseen versioon; tila ei muutu; varoittaa ajastinikkunasta mutta jatkaa (toimii myös yöllä ja kun snapshot-raja on täynnä) |
| `julkaise.sh <kohde> --katastrofi-tila --snapshot NIMI` | kopioi tilan isännälle ENNEN `pct rollback`:ia ja kertoo, mitä palautus tuhoaisi; ei aja rollbackia |
| `julkaise.sh <kohde> --katastrofi-palauta KANSIO` | palauttaa kopioidun tilan rollbackin jälkeen (vain tila; nykyinen tila säilyy `*.ennen-palautusta-<aika>`) |
| `julkaise.sh <kohde> --tila` | nykytila vain luku |
| `julkaise.sh --itsetesti` | tarkistaa työkalut ja konfiguraatiot |

Loppurivi on aina `OK: …` tai `EPÄONNISTUI: …`. Loki: `/root/julkaisu/loki.log` ja `ajo/<kohde>-<aika>.log`.

## Esitarkistukset (kova `exit 1`, myös yöllä; ennen kuin mitään muutetaan)

- paketin sha256 = annettu, paketin commit = annettu commit, julkisilla repoilla commit = `main`:n kärki (ohitus vain `--salli-ei-karki`, kirjataan lokiin; private-repolla vain paketin commit),
- paketti turvallinen: ei linkkejä tai laitetiedostoja, ei `/`-alkuisia tai `..`-polkuja, yksi ylätason hakemisto, enintään 50 Mt ja 3000 tiedostoa, vaaditut tiedostot mukana, ei salaisuuden näköisiä tiedostoja (`*.env`, `*.pem`, `*.key`, `id_rsa*`, …) eikä yksityistä avainta (PEM-otsikko + base64-runko),
- kohteen koodi vastaa omaa manifestiaan (ei paikallisia muutoksia); ensimmäinen julkaisu vaatii `--ensijulkaisu` (git-kloonilla lisäksi puhdas työpuu),
- palvelut eivät käynnissä, ei kohteen prosessia, lukot vapaana, ajastin ei laukea ikkunan (`IKKUNA_S`) sisällä,
- snapshotteja alle 20 (raja täynnä keskeyttää ennen muutosta), levytila, ei edellisen ajon jäänteitä (`<koodi>.uusi`), kohdenimi `<koodi>.prev-<aika>` ei ole jo olemassa (aikaleima on sekuntitarkka: kaksi julkaisua samalla sekunnilla keskeytetään ennen muutoksia, jottei vanha koodi siirry prev-kansion sisään), CT ja testikontti käynnissä,
- tilan ja konfiguraation tiiviste otetaan talteen.

## Julkaisun kulku

snapshot (`pre-<kohde>-<commit8>-<HHMM>`) → paketti kontille ja sha256-tarkistus → purku `<koodi>.uusi`:iin, manifestin tarkistus → testit → ajastimet pysäytetään vaihdon ajaksi → `mv` (`<koodi>` → `<koodi>.prev-<aika>`, `.uusi` → `<koodi>`) → savukoe (moduulien tuonti) → jälkitarkistukset (manifesti, **tila ja konfiguraatio ennallaan**, palvelut vapaina) → ajastimet takaisin → vanhimmat prev-versiot pois (säilytetään 3). Palveluiden ja lukkojen tarkistus toistetaan ajastimien pysäytyksen jälkeen (virhe poistaa `.uusi`:n) ja vaihdon jälkeen (virhe palauttaa edellisen koodin). Virheessä keskeneräinen muutos kumotaan automaattisesti (`.viallinen-<aika>`); jos tila tai konfiguraatio muuttui, ajo päättyy kovaan virheeseen.

**Testit:** kauppatiimi ja yojono ajetaan kontissa uuden koodin kopiolla ennen vaihtoa. **infra-automaatio:** testejä ei ajeta tuotantokontissa CT118, vaan CT115:n tilapäishakemistossa (`TESTI_TAPA=ct115`). CT115:n koko testisarja kaatuu ympäristöeroihin (root, node puuttuu), joten yojono ajaa vain `test.test_pr_kutsu`, `yojono.test_ajuri` ja `test.test_viikkoraportti`.

**Yksiköt:** kauppatiimi asentaa muuttuneet `*.service`/`*.timer`-tiedostot (kuten nykyinen `kauppa-asenna`) ja palauttaa ne peruutuksessa koodin mukana; infra-automaatio ja yojono eivät asenna yksiköitä automaattisesti (lakimuutos/koventaminen), vaan raportoivat erot (`asenna käsin`). Skriptikopiot (`/opt/yojono/*.sh`) raportoidaan samoin.

## Peruutus ja katastrofi

`--peruuta` ei koske tilaan: tilan ja konfiguraation tiiviste tarkistetaan ennen ja jälkeen. Jos savukoe ei mene läpi palautetulla koodilla, loppurivi on `EPÄONNISTUI … PERUUTUS ON TEHTY` (koodi on palautettu, mitään ei kumota, tarkista käsin).

Koko kontin palautus (`pct rollback`) tuhoaa kaiken, mitä snapshotin jälkeen on tapahtunut, myös tilan. Ennen sitä: `--katastrofi-tila --snapshot NIMI` kopioi tilan (`/root/julkaisu/katastrofi/<kohde>-<aika>/`, root 0700: `tila.tgz`, sha256, manifesti, raportti) ja listaa tuhoutuvat tiedostot sekä muuttuneet konfiguraatiotiedostot (vain nimet; sisältöä ei kopioida). Rollbackin jälkeen `--katastrofi-palauta KANSIO` palauttaa tilan.

## Vaihe 1 / vaihe 2 (CT119)

`kauppatiimi.conf` käyttää vaiheessa 1 kontin olemassa olevaa `kauppa-asenna` / `kauppa-palauta` -asentajaa (`ASENTAJA=kauppa-asenna`); `julkaise.sh` tekee esi- ja jälkitarkistukset, snapshotin, tiivisteet ja ajastinkäsittelyn. Vaiheessa 2 asetus vaihdetaan `ASENTAJA=yleinen` ja käytetään yleistä asentajaa. Huom: `kauppa-palauta` valitsee edellisen version `ls -dt`:llä (muokka-aika), mikä voi valita väärän kansion; yleinen asentaja valitsee nimen (`prev-<aika>`) mukaan.

## Asennus isännälle

    bash asenna-julkaise.sh <agentti-pohja-paketti.tgz> <sha256> <commit40> [--vain-tarkista]

Tarkistaa paketin (sha256, commit), poimii `isanta/julkaise.sh`, `paketoi.sh` ja `julkaisu/*.conf`, varmuuskopioi eroavat nykyiset (`*.ennen-<aika>`), asentaa `/root/julkaise.sh` (0700) ja `/root/julkaisu/*.conf` (0600) ja ajaa `--itsetesti`. Ei koske kontteihin.

## Testit

`test/test_julkaise.py` ajaa skriptin hiekkalaatikossa (väärennetty `pct` ja `systemctl`, oikea git ja bash; vain Linux): esitarkistukset (jokainen keskeyttää ilman kirjoituksia), `--kuiva`, kanaria (myös jokaisen esitarkistusfunktion tahallinen rikkominen), julkaisu, peruutus (tilan tiiviste ennen/jälkeen), vikatilanteet, CT118-testit vain CT115:ssä, yksiköt, delegoitu asentaja, katastrofi-tila ja -palautus, `paketoi.sh` ja `asenna-julkaise.sh`.

## Skriptikopiot (`--paivita-skriptit`)
Konfiguraatio `SKRIPTIT_HAKEMISTO` + `SKRIPTIT_PAKETISSA` (yojono: `/opt/yojono` + `yojono`) kertoo, missä kohteen ajamat skriptikopiot ovat. Oletuksena julkaisu vain raportoi erot. Lisäämällä `--paivita-skriptit` julkaisu päivittää lopuksi (koodivaihdon, savukokeen ja tilatarkistuksen jälkeen) ne `*.sh`-tiedostot, jotka ovat jo kohteessa ja eroavat paketista; uusia tiedostoja ei luoda. Varmuuskopio: `<skripti>.ennen-<kohde>-<commit8>-<aika>`. Virhe kumoaa skriptit ja koodin. Skriptien palautus onnistuneen julkaisun jälkeen on käsin (komento tulostuu loppuun); `--peruuta` palauttaa vain koodin.
