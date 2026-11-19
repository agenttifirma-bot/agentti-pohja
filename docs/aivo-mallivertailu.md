# Yksityisen tilan mallivertailu (aivo/mallivertailu.py)

Tämä ohje on Tonylle. Työkalu vertaa yksityisen tilan malliehdokkaita synteettisellä, suomenkielisellä testisarjalla. Se ei muuta palvelun asetuksia eikä `AVOIMET_MALLIT`-listaa.

## Mitä mitataan

Testisarjassa on 20 keksittyä tehtävää (`aivo/testidata/mallivertailu_tehtavat.json`):

| Osa-alue | Tehtäviä | Pisteytys |
|---|---|---|
| Päätösapu ja suunnittelu | 5 | tuomari; laskutehtävissä lisäksi mekaaninen tarkistus |
| Ohjeiden noudattaminen (`[[EHDOTUS …]]`, `[[VALINNAT: …]]`) | 4 | mekaaninen ja tuomari |
| Rehellisyys (ei taustalupauksia, ei keksittyjä lähteitä) | 4 | mekaaninen ja tuomari |
| Saman keskustelun muistaminen yli 20 viestin takaa | 3 | mekaaninen ja tuomari |
| Huolellinen suomi | 4 | mekaaninen ja tuomari |

Järjestelmäkehote on sama kuin tuotannossa (`yksityinen_or.KEHOTE`). Ydinohjeet ja muisti ovat keksittyjä.

Huomio: tuotanto lähettää mallille vain 12 viimeistä viestiä (`yksityinen.HISTORIA_YLARAJA`). Muistitehtävät lähettävät koko historian, jotta mallin kyky voidaan mitata. Tuotannossa tieto 20 viestin takaa ei näy mallille lainkaan, valitaanpa mikä malli tahansa.

## Turvarajat

- Jokainen kutsu kulkee `openrouter_kulut.kutsu`n kautta: yhteinen päiväkatto, ZDR ja `data_collection=deny` pakotettuina sekä kulukirjaus. Kuljetin on tuotannon `yksityinen_or.tee_kuljetin`.
- Vain `EHDOKKAAT`-listan mallit kelpaavat. `AVOIMET_MALLIT`-listan mallit ajetaan lipulla `yksityinen_chat=True` kuten tuotannossa. Listan ulkopuoliset avoimen painoston mallit ajetaan ilman lippua, koska data on synteettistä. ZDR ja `deny` ovat silti pakotettuja.
- Kuluraja on 3 $ koko ajolle (OpenRouterin ilmoittama `usage.cost`). Malli ohitetaan kahden peräkkäisen virheen jälkeen, ja koko ajo pysähtyy kuuden virheen jälkeen. Syy: kirjanpito kirjaa epäonnistuneen kutsun varovaisena 0,50 $:n kuluna.

## Ajo kontissa 122

Ota ensin snapshot kontista 122. Aja repon juuressa:

```
sudo -u aivo-yksityinen python3 -m aivo.mallivertailu aja --ulos /var/lib/aivo-yksityinen/mallivertailu
sudo -u aivo-yksityinen python3 -m aivo.mallivertailu paketti --ulos /var/lib/aivo-yksityinen/mallivertailu
```

Ensimmäinen komento tekee enintään 9 × 20 × 2 = 360 kutsua. Arvioitu yläraja on noin 1,6 $ (ZDR-endpointtien kalleimmilla hinnoilla ja 700 tokenin vastauksilla). Toinen komento kirjoittaa sokkoutetun tuomarisyötteen `tuomari_syote.jsonl` ilman mallien nimiä ja avaimen `tuomari_avain.json` erikseen.

Tuomari (Opus) saa vain tiedoston `tuomari_syote.jsonl` ja palauttaa tiedoston `tuomari_pisteet.json` muodossa `{"n0000": 7, ...}` (0–10). Sen jälkeen:

```
python3 -m aivo.mallivertailu taulukko --ulos /var/lib/aivo-yksityinen/mallivertailu --tuomari tuomari_pisteet.json
```

Tuloste sisältää taulukon (kokonaispisteet, osa-alueet, $ / 100 viestiä, vastausajan mediaani) ja kolmen parhaan mallin vastaukset kolmeen samaan tehtävään kirjaimin A–C. Kirjainten avain on tiedostossa `sokko_avain.json`.
