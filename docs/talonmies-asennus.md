# Talonmies, vaihe 1: ajastus (Tonyn asennus)

Tämä on ohje Tonylle. Mitään tästä ei aja automaatio. Vaihe 1 on pelkkä ehdotustila: ajo lukee tilan eikä muuta mitään.
Ei sudoers-, ssh-avain- eikä kulukattomuutoksia.

## Tarvittavat oikeudet
Ajo lukee `systemctl --failed`, `df` ja `apt list --upgradable` sekä isännän tilan komennolla `python3 -m agentti.snapshot_kutsu tila`. Viimeinen vaatii CT115:n snapshot-avaimen. Jos ajoa ei tehdä käyttäjänä, jolla avain on, raportin huomautuksiin tulee `isännän tila: ei luettavissa (SnapshotVirhe)`, ja varmuuskopioiden tuoreutta ei tarkisteta. Valitse silloin käyttäjä, jolla avain on (esimerkiksi sama käyttäjä, joka ajaa nykyisiä ajastimia).

## Kokeilu käsin
```
python3 -m agentti.talonmies ajo /var/lib/yojono/talonmies
```
Raportti: `/var/lib/yojono/talonmies/raportit/PVM.md`.

## Päätös ehdotukseen
```
python3 -m agentti.talonmies paata /var/lib/yojono/talonmies <tunniste> kylla
python3 -m agentti.talonmies mittari /var/lib/yojono/talonmies
```

## Pysäytys
```
touch /var/lib/yojono/talonmies/PYSAYTA
```
Poista tiedosto, kun ajo saa jatkua.

## Ajastus (vaiheen 1 jälkeen, kun Tony on tyytyväinen raporttiin)
Päivittäinen systemd-ajastin, esimerkiksi klo 05:30 UTC ennen aamukoostetta. Aamukoosteeseen liittäminen on oma pieni muutoksensa.
