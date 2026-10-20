# Changelog

Muoto perustuu [Keep a Changelogiin](https://keepachangelog.com/fi/1.0.0/).

## [Julkaisematon]

### Lisätty

- Agenttimaaritys (`agentti/maaritys.py`, `maaritys.esimerkki.json`): yksi JSON-tiedosto kuvaa agentin (ohjetiedosto, malli, budjetti, tokenit, datavyohyke, oikeustaso, tyokalut, lahteet, tulosmuoto, mittari, ajastus, halytys). Tarkistus nostaa kaikki virheet kerralla; kovakoodatut rajat (`rajat.py`) ovat katto, vyohyke 2 ei saa lukea ulkopuolista sisaltoa eika kayttaa verkkohakua, vain sallitut tyokalut. Vain tarkistus: ei suorita mitaan, eika `luo.py` kayta sita viela. 9 testia.
- Lokikerays (`agentti/loki_keraaja.py`): siirtaa agentin tekstilokin rivit tapahtumalokiin lukija/kirjoittaja-erottelulla, jotta agentti (esim. paivakatsaus, kovennettu ei-root-kayttaja) ei tarvitse oikeutta tietokantaan. Jasentaa rivit `ISO KOMPONENTTI avain=arvo`, ohittaa hiljaiset rutiinirivit (`tapahtuma=tyhja`), tulos `virhe` kun `virhekoodi` on, tavusiirtyma tilatiedostossa (ei tuplakirjauksia, kesken kirjoituksen oleva rivi odottaa, kierto luetaan alusta), 2000 rivia/ajo. Ajo: `TAPAHTUMALOKI=db python3 -m agentti.loki_keraaja LOKI TILA LAHDE AGENTTI`. 12 testia.
- Tapahtumalokin kaytto: komentorivi `TAPAHTUMALOKI=polku python3 -m agentti.tapahtumaloki kirjaa LAHDE AGENTTI TYYPPI TULOS [KULU]` / `yhteenveto [PAIVAA]` (skripteille ja terminal-Claudelle), ja yojono kirjaa jokaisen tehtavan lokiin, jos `YOJONO_LOKI` on asetettu (virhe ei koskaan kaada ajoa). Ei kayttoonottoa ennen Tonyn hyvaksyntaa. 5 testia.
- Tapahtumaloki (`agentti/tapahtumaloki.py`, SQLite): vain lisaava loki tapahtumille, ehdotuksille ja Tonyn palautteelle (oppiva silmukka, doc 34). Trigger estaa tapahtumien ja palautteen muokkauksen, raakadata vanhenee (`siivoa`, oletus 90 pv), tiedosto 0600, salaisuuden nakoiset merkkijonot poistetaan ennen tallennusta, `yhteenveto` antaa viikkoraportin luvut (tapahtumat, kulu, hyvaksymis-%). Ei verkkoa, ei kayttoonottoa: mitaan ei kerata ennen kuin Tony hyvaksyy kirjattavat asiat. 10 testia.
- Ilmoitus Tonylle (`agentti/ilmoita.py`): `python3 -m agentti.ilmoita valmis|virhe|paatos OTSIKKO [TEKSTI]` lahettaa lyhyen kiinteamuotoisen Telegram-viestin tyon tuloksesta, jotta tuloksia ei tarvitse liittaa chattiin kasin. Vastaanottaja ja tunnus luetaan tunnustiedostosta (`/etc/yojono/telegram.env`), ei argumenteista; teksti puhdistetaan ja rajataan; enintaan 30 viestia tunnissa. 10 testia.
- LLM-asiakas tunnistaa katkenneen vastauksen myös `native_finish_reason`-kentasta (LiteLLM/OpenRouter voi normalisoida `MAX_TOKENS`-lopetuksen muotoon `stop`). Sama virhekoodi `llm_vastaus_katkaistu`, ei uusia riippuvuuksia. Sama logiikka on kirjastossa `llm-stopcheck`.
- Sandbox-asiakas (`agentti/sandbox_kutsu.py`): lähettää repon tai luonnoshakemiston eristettyyn sandboxiin ssh:lla pakotetun komennon kautta. Vain `https://github.com/omistaja/repo`-osoitteet, ref-tarkistus, tar ilman symlinkkejä ja raskaita hakemistoja, kokoraja, aikaraja. Ei salaisuuksia: vain avaintiedoston polku.
- Automerge-koe 20.10.2026: tama rivi lisattiin PR:lla, jonka pitaisi yhdistya itsestaan.
- Automaattinen yhdistaminen pienille muutoksille (`.github/workflows/automerge.yml`, `tools/automerge.py`): kytkee GitHubin auto-mergen (squash) vain kun PR sisaltaa pelkkia dokumentteja (`*.md`) tai testeja (`test/*.py`), enintaan 20 tiedostoa ja 200 rivia, eika kosketa suojattuja polkuja (`.github/`, `tools/`, `isanta/`, `systemd/`, config, rajat, avaintiedostot). Yhdistyy vasta kun pakolliset tarkistukset ovat vihreat. Paatos tehdaan luotetusta paahaaran koodista (`pull_request_target`), PR:n koodia ei suoriteta. Kelpaamattomaksi muuttuneelta PR:lta auto-merge poistetaan. 12 testia.
- Snapshot-oikeus CT115:lle (`isanta/`, `agentti/snapshot_kutsu.py`): isannan pakotettu ssh-komento sallii vain `listaa` ja `snapshot ennen-<nimi>` kontille 115 (enintaan 20 snapshotia, 10 ottoa/vrk, ei poistoa eika rollbackia). Asennus isannalla: `isanta/asenna.sh` (idempotentti). Asiakas: `python3 -m agentti.snapshot_kutsu listaa | ota ennen-<nimi>`. 16 testia.
- Testit sandbox-asiakkaalle (`test/test_sandbox_kutsu.py`).
- `aja_git(repo, ref)` ja CLI `python -m agentti.sandbox_kutsu git <repo> [ref]`: testaa git-haaran sandboxissa lähettämällä vain haaran seurattavat tiedostot (`git archive`). Seuraamattomat tiedostot (`.env`, tilatiedostot) ja symlinkit eivät lähde. Tarkoitettu yo/-haarojen testaukseen ennen katselmointia.
- Yöjono (`yojono/`): jonotiedostosta ajettava, kulukattoinen tehtäväajuri (nyt vain koodikatselmointi). Varaa budjetin ennen tehtävää, lukee todellisen kulun, laskuttaa koko budjetin jos kulu on tuntematon, kirjaa tilan heti, lukko estää rinnakkaisajon, valinnainen Telegram-yhteenveto. Systemd-mallit ja käyttöönotto-ohje (`yojono/README.md`), 30 testiä.

## [0.1.0] - 2026-10-16

### Lisätty

- Kulukirjanpito (`kulu.py`): varaus ennen kutsua, päivä- ja kuukausikatto sekä kutsuraja, flock-lukko, vikatilassa pysäytys (fail closed).
- LLM-asiakas (`llm.py`): OpenAI-yhteensopiva, ei työkaluja, `max_tokens`-katto, ei uudelleenohjausten seurantaa, virheet koodeina.
- Tulos (`tulos.py`, `skeema.py`): `ok` tai `ei_tietoa` (ei tiedä on aina sallittu), vastaus hyväksytään vain skeemaa vasten.
- Telegram (`telegram.py`), sydämenlyönti (`sydan.py`), ulkoisen datan `<data>`-lohko (`data.py`).
- Ajon kulku (`ajo.py`) ja komentorivi (`python -m agentti`): oletuksena kuiva-ajo, `--llm`, `--send` (kerran päivässä).
- Esimerkkiagentti, `luo.py` (uusi agentti pohjasta), kovennetut systemd-pohjat, DEPLOY.md.
- Testit (yli 80) ja CI (Python 3.10-3.13).
