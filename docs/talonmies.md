# Talonmies: rutiinihuolto agentille vaiheittain

Tavoite: kaatuneet palvelut, levytila, varmuuskopioiden tuoreus ja tietoturvapäivitykset eivät vie Tonyn aikaa, mutta mistään ei voi syntyä peruuttamatonta vahinkoa. Tony 2.11.2026: "Sitähän mä juuri haluan, mutta niin että se ei ole mulle vahingollista."

**Tila nyt: vaihe 1, vain ehdotustila.** Koodi (`agentti/talonmies.py`) lukee tilan ja kirjoittaa ehdotuksia. Se ei tee yhtään muutosta.

## Tasot

| Taso | Mitä se tarkoittaa |
|---|---|
| A | Saa tehdä itse ja raportoi aamukoosteessa. |
| B | Snapshot ensin, terveystarkistus perään, automaattinen peruutus epäonnistuessa. |
| C | Vain ehdotus Tonylle. Tony tekee itse. |

### Toimenpidelista

| Toimenpide | Taso | Ehto ja rajaus |
|---|---|---|
| Kaatuneen palvelun uudelleenkäynnistys | A | Kerran per palvelu ja vuorokausi. Terveystarkistus 60 s kuluttua. Toinen kaatuminen: ei uutta yritystä, hälytys Telegramiin. LXC:n kohinayksiköt (`tmp.mount` ym.) ohitetaan. |
| Lokien ja väliaikaistiedostojen siivous | A | Levy yli 80 %. Vain listattu siivousskripti: `journalctl --vacuum-time`, `/tmp`-tiedostot yli 7 vrk. Dataa ei poisteta. |
| Levy yli 90 % | C | Hälytys. Siivous ei riitä tai vaatii päätöksen. |
| Varmuuskopion tuoreustarkistus | A (vain lukua) | Uusin vzdump yli 36 h vanha tai puuttuu: hälytys (C). Varmuuskopiota ei käynnistetä itse. |
| Palautustesti kuukausittain | C, myöhemmin B | Palautus uuteen väliaikaiseen kontti-ID:hen. Vanhaa konttia ei kosketa. Kunnes Tony on valinnut testille varatun ID:n, vain muistutus. |
| Tietoturvapäivitykset ei-kriittisiin kontteihin | B | Snapshot ensin (CT118:n työkalun rajat: 20 snapshotia, 10 ottoa/vrk), vain listatut paketit, terveystarkistus, peruutus epäonnistuessa. Ei-kriittisten konttien lista on Tonyn päätös. Kunnes lista on, kaikki C. |
| Tavalliset (ei tietoturva) päivitykset | C | Tony valitsee ajan. |

### Kielletty aina (ei ehdotuksina eikä toimenpiteinä automaattisesti)
- Isännän root ja isännän asetukset.
- Palomuuri (nftables), holvi ja Tailscale.
- Avaimet ja salaisuudet.
- Kulukatot ja budjetit.
- Kauppatiimin oikea raha.
- Datan poisto, snapshotien ja varmuuskopioiden poisto.
- Käyttäjät ja oikeudet (sudoers, authorized_keys).

## Turvarakenteet (vaiheesta 2 alkaen)
1. **Vain listatut skriptit.** Jokainen toimenpide on oma pieni skripti ilman argumentteja tai kiinteällä nimilistalla. Kutsu kulkee kapean pakotetun komennon kautta kuten CT118:n snapshot-oikeus (`isanta/CT118-asennus.md`): ei vapaita komentoja, ei shell-syötettä.
2. **Vuorokausiraja per toimenpide.** Esimerkiksi uudelleenkäynnistys 1 per palvelu, siivous 1, päivitys 1. Raja on koodissa, eikä agentti voi muuttaa sitä.
3. **Pysäytystiedosto.** Tiedosto `<tila>/PYSAYTA` estää kaiken (ajo tulostaa vain ilmoituksen). Tony luo sen komennolla `touch`.
4. **Aamukooste.** Jokainen ehdotus ja toimenpide näkyy aamukoosteessa. Raportti: `<tila>/raportit/PVM.md`.
5. **Hälytys.** Virheet ja taso C -hälytykset menevät Telegramiin. Muu kulkee aamukoosteessa (kompassi: Telegramiin vain hälytykset).
6. **Snapshot ensin (B).** Jos snapshotin otto epäonnistuu tai thin pool on yli 80 %, toimenpidettä ei tehdä.

Vaiheessa 1 ei muuteta oikeuksia, sudoersia, ssh-avaimia eikä kulukattoja. Niihin tarvittavat muutokset kirjoitetaan jälkeenpäin Tonille ohjeeksi ohjeeksi (docs/talonmies-asennus.md; isanta/-hakemisto on PR-työkalun suojaama).

## Vastuun kasvatus
1. **Vaihe 1 (2–4 viikkoa): pelkkä ehdotustila.** Ajo kerran päivässä. Tony vastaa ehdotuksiin `kylla` tai `ei`.
2. **Vaihe 2: A-tason toimenpide kerrallaan.** Toimenpide siirtyy automaattiseksi vasta, kun mittari ylittää rajan. Raja on **Tonyn päätös**, eikä koodi sisällä oletusarvoa.
3. **Vaihe 3: B-taso.** Vasta kun A-tason toimenpiteet ovat toimineet ilman peruutuksia ja snapshot-ketju on todennettu.

Ehdotus mittarin rajaksi (Tony päättää): vähintään 10 ratkaistua ehdotusta toimenpidettä kohti ja niistä vähintään 80 % hyväksytty. Perustelu: alle 10 ehdotuksen otoksessa yksi hylkäys heiluttaa osuutta yli 10 prosenttiyksikköä, ja 80 % tarkoittaa, että enintään yksi viidestä on turha.

## Hyväksyntöjen kirjanpito
Kaksi tiedostoa tilahakemistossa, molemmat vain liitettäviä (JSON-rivejä):
- `ehdotukset.jsonl`: jokainen ehdotus kerran (tunniste, pvm, taso, toimenpide, kohde, syy).
- `paatokset.jsonl`: Tonyn `kylla` tai `ei` ja valinnainen huomio (enintään 300 merkkiä). Myöhempi päätös samaan tunnisteeseen korvaa aiemman.

Päätös kirjataan yhdellä komennolla (tunniste näkyy raportissa):
```
python3 -m agentti.talonmies paata <tila> <tunniste> kylla
```
Mittari:
```
python3 -m agentti.talonmies mittari <tila> --raja 0.8 --min 10
```
Se laskee toimenpiteittäin `osuus = kylla / (kylla + ei)`. Vastaamattomat ehdotukset raportoidaan erikseen, eivätkä ne muuta osuutta. Kenttä `kypsa` on tosi vasta, kun otos ja raja täyttyvät. Ilman `--raja`-valitsinta se on aina epätosi.

Rajoitus: osuus mittaa, pitikö Tony ehdotusta järkevänä, ei sitä, olisiko toimenpide onnistunut. Onnistuminen mitataan vasta vaiheessa 2 (peruutukset ja terveystarkistusten tulokset).
