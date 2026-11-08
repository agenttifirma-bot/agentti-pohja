# Mallipalvelin yksityiselle tilalle

Tämä kansio valmistelee paikallisen mallipalvelimen (Ollama) omaan LXC-konttiinsa. **PR on rajattu: uusi kontti ja palvelu. Tony yhdistää. Käyttöönotto on erillinen vaihe.** Tämä PR ei asenna mitään.

## Sisältö
- `asetukset.esimerkki.env`: muuttujat (osoitteet, muistiraja). Oikeat arvot vain paikalliseen `asetukset.env`-tiedostoon, jota ei viedä repoon.
- `luo-kontti.sh`: luo kontin isännällä. Oletuksena kuiva-ajo, oikea ajo vaatii `--toteuta`.
- `asennus-kontissa.sh`: asennus kontin sisällä. Tarkistaa latauksen tarkistussumman, sitoo kuuntelun kontin sisäverkon osoitteeseen, asettaa muistirajan ja nftables-palomuurin.
- `mallit.json`: kolme ehdokasmallia (kaksi 8B-mallia ja yksi 4B-vertailumalli).
- `tapaukset.json`: keksityt testitapaukset tehtävän 06-32 mittauksiin.
- `mittaa.py`: mittausskripti.

## Suojaukset
- Ei julkista porttia: kontille ei tehdä portinohjausta.
- Ollama kuuntelee vain kontin omassa sisäverkon osoitteessa, ei kaikissa osoitteissa.
- Palomuuri päästää sisään vain `SISAVERKKO_CIDR`- ja `TAILNET_CIDR`-alueet. Muu liikenne pudotetaan.
- Kontti on vähäoikeuksinen (unprivileged), `nesting` on pois, muistiraja asetetaan sekä kontille että palvelulle.
- Tailscalea ei asenneta konttiin eikä sen asetuksia muuteta. Tailnetistä pääsy kulkee isännän kautta, jos Tony niin päättää.

## Käyttöönotto (Tony, vasta PR:n yhdistämisen jälkeen)
1. Kontti on uusi, joten snapshotia ei tarvita sitä varten. Tarkista levytila ja vapaa muisti isännällä: `lvs` ja `free -m`.
2. Kopioi `asetukset.esimerkki.env` nimelle `asetukset.env` ja täytä arvot. Valitse `OLLAMA_VERSIO` Ollaman julkaisusivulta ja ota tarkistussumma julkaisun `sha256sum.txt`-tiedostosta.
3. Kuiva-ajo: `bash luo-kontti.sh asetukset.env`. Lue tuloste. Sitten `bash luo-kontti.sh asetukset.env --toteuta`.
4. Debian-pohjan nimi skriptissä on `debian-12-standard_12.12-1_amd64.tar.zst`. Nimi on todennettu Proxmoxin julkisesta luettelosta, ei isännältä. Näet ajantasaisen nimen isännällä: `pveam update && pveam available --section system | grep debian-12`. Lataa pohja komennolla `pveam download local <nimi>` ja tarkista se komennolla `pveam list local`. Jos nimi on muuttunut, korjaa se skriptiin.
5. Kopioi `asennus-kontissa.sh` ja `asetukset.env` konttiin (`pct push`) ja aja: `bash asennus-kontissa.sh asetukset.env <sha256>`.
6. Lataa mallit kontissa: `ollama pull qwen3:8b` jne. (Tunnisteet on tarkistettava, katso `mallit.json`.)

## Mittaus (06-32)
```
MALLIPALVELIN_URL=http://<kontin-osoite>:11434 python3 -I -m isanta.mallipalvelin.mittaa qwen3:8b llama3.1:8b gemma3:4b
```
Skripti hylkää osoitteet, jotka eivät ole yksityisiä, tailnetin tai loopback-osoitteita. Se tulostaa taulukon (ohjeet, yksityisyys, sanaa sekunnissa) ja perään JSON-tulokset. Tapaukset ovat keksittyjä. Tulos on karkea suodatin: suomen kielen laatua se ei arvioi, vaan sen arvioi Tony tai tarkastaja lukemalla vastaukset.

Testit: `python3 -m unittest test.test_mallipalvelin`
