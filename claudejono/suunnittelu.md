Itsesuunnittelu (Tony hyvaksyi 30.10.2026): jono on tyhja. Ala tee tyota nyt, vaan suunnittele seuraavat tehtavat.

Lue: /var/lib/claude-jono/docs/claude-jono/tulokset/ (viimeisimmat raportit ja niiden avoimet kohdat), /var/lib/claude-jono/docs/claude-jono/tonylle.md, /var/lib/yojono/tila.json ja /var/lib/yojono/raportit/ (viimeiset 2 vrk) seka systemd-ajastinten tila (`systemctl list-units --failed`).

Lue myos /var/lib/claude-jono/docs/claude-jono/tulostaulu.md. Tonyn paatavoite on ura AI-infran kautta ja infrasta henkilokohtainen tyokalu; tulos mitataan tulostaulun mittareilla 1-5, ei PR-maarilla.

PAINOTUSSAANTO (Tonyn paatos 30.10.2026): vahintaan joka toinen ehdottamasi tehtava palvelee jotain mittaria 1-5: ulospain nakyva tyo (tapaustutkimus, demo-ohje, julkaistava dokumentaatio, ulkoisen repon issue- tai PR-luonnos Tonyn lahetettavaksi, LinkedIn-luonnos) tai Tonya arjessa auttava tyo. Merkitse jokaiseen tehtavaan rivi 'Mittari: <1-5 tai yllapito>'. Muut tehtavat: arvokkaimmat korjattavat tai jatkettavat asiat. Hyva tehtava: konkreettinen, PR-tasoinen tai pelkka diagnoosi, valmis 10-40 minuutissa, sisaltaa tavoitteen, askeleet ja "Valmis kun" -lauseen seka muistutuksen: koodityot vain /opt/agentscope/tyo/<repo>, PR:t pr_kutsulla, viimeinen viesti on taydellinen raportti. Ala ehdota tehtavaa, joka toistaa jo tehdyn tai tuloksissa avoimena odottavan Tonyn paatoksen.

Asiat, jotka vaativat Tonyn paatosta (katot, budjetit, oikeudet, kayttoonotot, rahankaytto), kirjoita kenttaan "tonylle" eika tehtaviksi. Jos jarkevaa tehtavaa ei ole, palauta tyhja lista.

Viimeinen viestisi on PELKKA JSON-olio, ei muuta tekstia:
{"tehtavat": [{"nimi": "lyhyt-nimi-pienilla", "sisalto": "# Otsikko\n\nTavoite...\n\nValmis kun: ..."}], "tonylle": "lyhyet kohdat tai tyhja"}
