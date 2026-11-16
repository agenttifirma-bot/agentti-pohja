# Aivon yksityinen tila OpenRouterin avoimella mallilla (A984)

Tämä ohje on Tonylle. Rajattu ulkoinen mallipalvelu (A728). Tonyn sha-sidottu kyllä tarvitaan ennen käyttöönottoa.

## Mitä muuttuu

- Yksityisellä tilalla on kaksi taustapäätä. Oletus on edelleen paikallinen mallipalvelin (loopback). Uusi vaihtoehto on OpenRouterin avoin malli: `--yksityinen-taustapaa openrouter`.
- Muisti, keskustelut, ydinohjeet ja ehdotukset pysyvät kontissa 122. OpenRouterille lähtee vain kulloinenkin kehote (ydinohjeet, muistista valitut otteet ja keskusteluhistoria).
- Jokainen kutsu kulkee `openrouter_kulut.kutsu`n kautta. Se tarkistaa päiväkatkaisimen (10 €/vrk), rakentaa pyynnön `openrouter_zdr.rakenna_runko`lla (ZDR ja `data_collection=deny` pakotettuina) ja kirjaa kulun. Kuljetin kieltäytyy lähettämästä, jos ZDR puuttuu rungosta.
- Mallin pitää kuulua avoimiin perheisiin (`AVOIMET_MALLIT` tiedostossa `aivo/yksityinen_or.py`). Suljetut mallit, `:free`-versiot ja `:online`-liitteet hylätään. Oletusmallia ei ole.
- Avain luetaan tiedostosta, jonka omistaa palvelun käyttäjä ja jonka oikeudet ovat 0600. Ympäristömuuttujaa ei lueta. Avain luetaan joka kutsulla, joten sen voi vaihtaa ilman uudelleenkäynnistystä.
- Puuttuva tai väärin suojattu avain antaa selkeän virheen (HTTP 502 ja teksti "OpenRouter-avain puuttuu…"), eikä päiväkattovarausta kirjata.
- Työkalutila ei käytä tätä taustapäätä. Testit tarkistavat sen.
- Kehote kertoo mallille totuudenmukaisesti, että kehote kulkee OpenRouterin kautta nollasäilytyksellä. Sivun valinta on nimeltään "Yksityinen (avoin malli, ei tallennusta)".

## Suositeltu malli ja kustannusarvio

Hinnat on haettu OpenRouterin julkisesta mallilistasta ja ZDR-päätepisteiden listasta 16.11.2026. Hinnat muuttuvat, joten tarkista ne ennen käyttöönottoa.

| Malli | Listahinta (sisään / ulos, $ per miljoona tokenia) | ZDR-päätepisteitä | ZDR-hintahaarukka |
|---|---|---|---|
| `qwen/qwen3-235b-a22b-2507` (suositus) | 0,14 / 0,80 | 6 | 0,07–0,20 / 0,44–0,83 |
| `meta-llama/llama-3.3-70b-instruct` | 0,71 / 0,71 | 9 | 0,20–0,72 / 0,52–1,20 |

Suomen kieltä ei ole mitattu. Valitse malli Tonyn oman kokeilun mukaan.

Oletukset: yksi OpenRouter-kutsu per Tonyn viesti, keskustelu on 20 viestiä, kurssi 0,92 €/$ (sama vakio kuin kulukirjanpidossa). Historia on enintään 12 viestiä. Tyypillinen kutsu on 6 000 tokenia sisään ja 350 ulos, raskas 14 000 sisään ja 700 ulos (muistiraja 16 000 merkkiä ja ydinohjeraja 20 000 merkkiä täynnä). Laskennassa käytetään ZDR-ylärajaa (0,20 / 0,825) Qwenille ja listahintaa Llamalle.

| Malli ja kuorma | Per keskustelu (20 viestiä) | Kuukausi, 20 viestiä/pv | Kuukausi, 50 viestiä/pv |
|---|---|---|---|
| Qwen3 235B, tyypillinen | 0,04 € | 1,10 € | 2,76 € |
| Qwen3 235B, raskas | 0,07 € | 2,15 € | 5,36 € |
| Llama 3.3 70B, tyypillinen | 0,12 € | 3,49 € | 8,72 € |
| Llama 3.3 70B, raskas | 0,23 € | 6,76 € | 16,90 € |

Päiväkatto 10 €/vrk on huomattavasti suurempi kuin yksityisen tilan odotettu kulu (alle 0,6 €/vrk raskaimmassakin laskelmassa). Virheellinen tai aikakatkaistu kutsu kirjataan varovaisesti 0,50 $:n kuluna, joten toistuvat virheet näkyvät kirjanpidossa.

## Käyttöönotto (Tony tekee kontissa 122)

Ota ensin snapshot kontista 122. Käyttäjänimi `aivo-yksityinen` on sama kuin yllä olevassa ohjeessa.

1. **Kulukirjanpidon kansio.**

   ```
   sudo install -d -m 700 -o aivo-yksityinen -g aivo-yksityinen /var/lib/aivo-yksityinen/kulut
   ```

2. **Avaintiedosto.** Kirjoita avain itse. Tämä komento kysyy sen piilotettuna eikä jätä sitä komentohistoriaan:

   ```
   sudo -u aivo-yksityinen sh -c 'umask 077; printf "Avain: "; stty -echo; read -r K; stty echo; printf "%s" "$K" > /var/lib/aivo-yksityinen/openrouter-avain'
   ls -l /var/lib/aivo-yksityinen/openrouter-avain
   ```

   Tiedoston pitää olla `-rw-------` ja omistajan `aivo-yksityinen`. Luo avain OpenRouterissa omalla, vain tätä käyttöä varten tehdyllä avaimella ja aseta sille tarvittaessa kulutuskatto OpenRouterin puolella.

3. **Palvelun asetukset.** Lisää `aivo-chat.service`-tiedoston `ExecStart`-riville: `--yksityinen-taustapaa openrouter --openrouter-malli qwen/qwen3-235b-a22b-2507` (muut valitsimet: `--openrouter-avain-tiedosto`, `--openrouter-kulutila`). Lisää `/var/lib/aivo-yksityinen/kulut` kohtaan `ReadWritePaths`, koska `ProtectSystem=strict` estää kirjoituksen muuten. Kontin 122 pitää päästä HTTPS-yhteydellä osoitteeseen `openrouter.ai`. Palomuuria ei muuteta tämän muutoksen mukana, joten tarkista saanti itse.

4. **Uudelleenkäynnistys ja testi.**

   ```
   sudo systemctl daemon-reload
   sudo systemctl restart aivo-chat
   sudo systemctl status aivo-chat --no-pager
   ```

   Avaa Aivo, valitse Yksityinen ja lähetä viesti. Odotettu tulos: vastaus tulee muutamassa sekunnissa, ja kulutiedostoon ilmestyy rivi: `sudo tail -n 2 /var/lib/aivo-yksityinen/kulut/openrouter-kulut.jsonl` (rivillä on vain malli, aika ja luvut). Jos avain puuttuu, sivu näyttää virheen "OpenRouter-avain puuttuu".

5. **Takaisin paikalliseen malliin.** Poista `--yksityinen-taustapaa`-valitsin (oletus on `loopback`) ja käynnistä palvelu uudelleen.

## Avoimet kohdat

- Päiväkatkaisin on yhteinen vain, jos kaikki Aivon OpenRouter-kutsut käyttävät samaa kulukansiota. Tässä kansio on `/var/lib/aivo-yksityinen/kulut`, kun taas ajurin oma kirjanpito on isännän `/var/lib/claude-jono`. Ne ovat siis erilliset 10 €:n katot.
- Mallin suomen kielen laatua ei ole mitattu.
