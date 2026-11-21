# Muutosfragmentit

Jokainen PR lisaa oman tiedostonsa tahan hakemistoon (nimi = haaran nimi, esim. `yojono-ajopaiva.md`) ja kirjoittaa siihen yhden tai useamman rivin muodossa `- aihe: mita muuttui ja miksi`. CHANGELOG.md:aan ei kosketa PR:ssa, joten rinnakkaiset PR:t eivat konfliktoi.

Kokoaja `python3 tools/changelog_kokoa.py` lisaa fragmentit CHANGELOG.md:n Unreleased-listan loppuun ja poistaa ne (`--kuiva` esikatselee). Aja se julkaisun yhteydessa tai viikoittain.

Suora CHANGELOG.md-muutos hylataan: `python3 tools/changelog_tarkista.py [--pohja REF]` (ajetaan `tools/tarkista-ja-pushaa.sh`:ssa ennen pushia ja CI:n `changelog`-tyossa). Poikkeus on kokoaja-PR, joka muuttaa CHANGELOG.md:ta ja poistaa samalla fragmentteja. `.gitattributes`-rivi `merge=union` ei auta GitHubissa, koska verkkoyhdistaminen ei kayta omia yhdistamisajureita.
