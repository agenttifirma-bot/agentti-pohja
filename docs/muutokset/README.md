# Muutosfragmentit

Jokainen PR lisaa oman tiedostonsa tahan hakemistoon (nimi = haaran nimi, esim. `yojono-ajopaiva.md`) ja kirjoittaa siihen yhden tai useamman rivin muodossa `- aihe: mita muuttui ja miksi`. CHANGELOG.md:aan ei kosketa PR:ssa, joten rinnakkaiset PR:t eivat konfliktoi.

Kokoaja `python3 tools/changelog_kokoa.py` lisaa fragmentit CHANGELOG.md:n Unreleased-listan loppuun ja poistaa ne (`--kuiva` esikatselee). Aja se julkaisun yhteydessa tai viikoittain.
