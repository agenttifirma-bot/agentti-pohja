# Digi-Tony päättää työnvalintakysymyksiä

Tonyn lisähöllennys 3.11.2026: kun agentti tai itsesuunnittelu kysyisi Tonylta työnvalintakysymyksen, Digi-Tony vastaa, jos varmuus on riittävä. Muuten vastaus on "en tiedä" ja kysymys menee Tonylle.

## Käyttö
```
python3 -m agentti.digitony_paatos kysy <tila> "<kysymys>" "<vaihtoehto 1>" "<vaihtoehto 2>"
```
Päätösmuisti luetaan ympäristömuuttujasta `DIGITONY_MUISTI` (JSONL, yksityistä dataa, ei koskaan julkiseen repoon). Vastaus on JSON, jonka `tila` on `paatetty`, `en_tieda` tai `tonylle`.

## Rajat (koodissa)
- Vain luokka työnvalinta. Raha, kulut, oikeudet, tietoturva ja julkaisu menevät aina Tonylle. Avainsanatarkistus ylikattaa luokittelun, ja yksikin osuma riittää. Se estää myös joitakin harmittomia kysymyksiä (esimerkiksi sana "nostetaanko" sisältää merkkijonon "osto"); virhe on tarkoituksella turvallisempaan suuntaan.
- Varmuus vähintään 0,6 (varjotilan raja on 0,25) ja vähintään kaksi työnvalintapäätöstä perusteena.
- Arkaluonteinen teksti (henkilötunnus, avain, terveys) menee Tonylle eikä kirjaudu.
- Jos viimeisestä viidestä päätöksestä vähintään kaksi on kumottu, Digi-Tony lopettaa päättämisen, kunnes Tony on katsonut tilanteen.
- Pysäytys: `touch <tila>/PYSAYTA`.

## Kirjanpito ja kumoaminen
Jokainen vastaus (myös "en tiedä") kirjataan tiedostoon `<tila>/digitony-paatokset.jsonl` (vain liitto, oikeudet 0600). Aamukoosteen linkkiosa näyttää rivin "Digi-Tony päätti: …, kumoa: …" valmiine komentoineen:
```
python3 -m agentti.digitony_paatos kumoa <tila> <tunniste> "syy"
```
Kumoaminen ei muuta jo tehtyä työtä itsestään; se kirjaa Tonyn linjan ja vaikuttaa pysäytysrajaan.

## Rajoitus
Takautuva testi (tulos 2026-11-03-03) ei todistanut, että moduuli voittaa yksinkertaisen perustason. Kynnys 0,6 on siksi tiukka: käytännössä Digi-Tony päättää vain kysymyksiä, jotka muistuttavat selvästi aiemmin kirjattua päätöstä. Uusi aihe tuottaa "en tiedä".
