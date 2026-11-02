Itsesuunnittelu (Tony hyvaksyi 30.10.2026): jono on tyhja. Ala tee tyota nyt, vaan suunnittele seuraavat tehtavat.

RAJAUS (kompassi, osio "Tyonvalinta, laatu ja prosessit"): lue osio ennen suunnittelua. Tony ja pilvi-Claude suunnittelevat tyon yhdessa viikkosuunnittelussa. Itsesuunnittelu rajataan (1) korjauksiin, (2) yllapitoon ja (3) viikkosuunnitelman aukkojen taytolle. Ala ehdota muuta.

TEHTAVAN MUOTO (ajuri hylkaa tehtavan ennen ajoa, jos jokin puuttuu): jokaisessa tehtavassa on omalla rivillaan
- "Hyoty: ..."
- "Pisteet: hyoty 1-5, varmuus 1-5, vaiva <h>" (jarjestys: hyoty x varmuus / vaiva)
- "Todennus: <miten tulos todennetaan kaytossa, esim. testi ajetaan oikealla tiedostolla>"
- "Valmis kun: ..."
Tehtavassa ei saa olla kelloporttia ("vasta klo", "aja vasta"). Hylatty tehtava ei tuota mitaan ja kuluttaa vain suunnittelukierroksen.

Lue: /var/lib/claude-jono/docs/claude-jono/tulokset/ (viimeisimmat raportit ja niiden avoimet kohdat), /var/lib/claude-jono/docs/claude-jono/tonylle.md, /var/lib/yojono/tila.json ja /var/lib/yojono/raportit/ (viimeiset 2 vrk) seka systemd-ajastinten tila (`systemctl list-units --failed`).

Lue myos /var/lib/claude-jono/docs/claude-jono/tulostaulu.md. Tonyn paatavoite on ura AI-infran kautta ja infrasta henkilokohtainen tyokalu; tulos mitataan tulostaulun mittareilla 1-5, ei PR-maarilla.

TAVOITTEET JA PALAUTE (Tonyn paatos 1.11.2026). Lue aina ensin:
- /var/lib/claude-jono/docs/claude-jono/kompassi.md: Tonyn suunta ja ylimpana "Viikon painopiste". Vahintaan puolet tehtavista palvelee viikon painopistetta, jos se on asetettu. Perustele jokainen tehtava silla, mihin kompassin onnistumisen kohtaan (1-4) se vie.
- /var/lib/claude-jono/docs/claude-jono/valitavoitteet.md: Tonyn pitkan aikavalin tavoitteet (10/2027) ja kvartaalin valitavoitteet. Jokaisen tehtavan Hyoty-rivissa mainitaan, mita valitavoitetta se edistaa. Jos tehtava ei edista mitaan valitavoitetta eika korjaa vikaa, ala ehdota sita.
- /var/lib/claude-jono/docs/claude-jono/palaute.md: Tonyn viikkopalaute tuloksista (hyodyllinen / turha / ei luettu). Suosi tehtavatyyppeja, jotka ovat saaneet merkinnan "hyodyllinen". Ala toista "turha"-tyyppeja. "Ei luettu" -tyyppeja tee harvemmin ja tiiviimmin.

TONYN KAISTA: Tony on pullonkaula. Laske tuloksista ja tonylle.md:sta, montako valmista luonnosta (LinkedIn, artikkeli, issue, julkaisuohje) odottaa Tonya kasittelematta. Jos niita on 5 tai enemman, ala ehdota uusia luonnoksia, vaan tehtavia jotka eivat vaadi Tonyn aikaa tai jotka purkavat jonoa (esim. yhdistetty "valmiina julkaistavaksi" -lista parhaimmista).

Jokaiseen tehtavaan rivi 'Hyoty: <kuka kayttaa tulosta ja milloin, esim. "Tony lukee aamulla ennen koulua" tai "rekrytoija nakee READMEsta">'. Jos et osaa kirjoittaa tata rivia, ala ehdota tehtavaa.

PAINOTUSSAANTO (Tonyn paatos 30.10.2026): vahintaan joka toinen ehdottamasi tehtava palvelee jotain mittaria 1-5: ulospain nakyva tyo (tapaustutkimus, demo-ohje, julkaistava dokumentaatio, ulkoisen repon issue- tai PR-luonnos Tonyn lahetettavaksi, LinkedIn-luonnos) tai Tonya arjessa auttava tyo. Merkitse jokaiseen tehtavaan rivi 'Mittari: <1-5 tai yllapito>'. Muut tehtavat: arvokkaimmat korjattavat tai jatkettavat asiat. Hyva tehtava: konkreettinen, PR-tasoinen tai pelkka diagnoosi, valmis 10-40 minuutissa, sisaltaa tavoitteen, askeleet ja "Valmis kun" -lauseen seka muistutuksen: koodityot vain /opt/agentscope/tyo/<repo>, PR:t pr_kutsulla, viimeinen viesti on taydellinen raportti. Ala ehdota tehtavaa, joka toistaa jo tehdyn tai tuloksissa avoimena odottavan Tonyn paatoksen.

HUKAN KARSINTA (Tonyn paatos 1.11.2026, yolla 1.11. viisi tehtavaa pysahtyi heti): ala ehdota tehtavaa, joka saa alkaa vasta tiettyna kellonaikana tai tietyn ajon jalkeen ("aja vasta klo X jalkeen", "jos ajo ei ole tapahtunut, lopeta"). Jono ajaa tehtavan heti, joten kelloportti vain polttaa budjettia. Odota, etta ajo on tapahtunut, ja suunnittele seurantatehtava vasta sitten. Ala myoskaan ehdota tehtavaa, jonka tulos jaa PR:tta repoon, joka ei ole REPOT-listalla (katso /opt/agentti-pohja/agentti/pr_kutsu.py); kirjaa tarve kenttaan "tonylle". Ala ehdota samaa aihetta kahdesti saman vuorokauden aikana.

Asiat, jotka vaativat Tonyn paatosta (katot, budjetit, oikeudet, kayttoonotot, rahankaytto), kirjoita kenttaan "tonylle" eika tehtaviksi. Jos jarkevaa tehtavaa ei ole, palauta tyhja lista.

Viimeinen viestisi on PELKKA JSON-olio, ei muuta tekstia:
{"tehtavat": [{"nimi": "lyhyt-nimi-pienilla", "sisalto": "# Otsikko\n\nTavoite...\n\nValmis kun: ..."}], "tonylle": "lyhyet kohdat tai tyhja"}
