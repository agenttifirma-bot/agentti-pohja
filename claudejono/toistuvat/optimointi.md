# Viikoittainen optimointikierros: kulut, kestot, kaatumiset ja Tonyn aika

Pisteet: hyöty 4, varmuus 4, vaiva 3 h
Suunta: jatkoa (kompassi, Itsekehittyvä infra: jatkuva optimointi)
Hyöty: Tony lukee viikkosuunnittelussa sunnuntaina, mikä jonoissa hukkaa aikaa ja rahaa ja mitkä pienet korjaukset on jo tehty PR:inä.
Todennus: jokainen ehdotus perustuu lokiin tai kulukirjanpitoon, ja luvut ovat raportissa lähteineen.

Tämä on toistuva tehtävä (toisto 7 päivää). Pohjana on tulos 2026-11-02-43 (parannus- ja optimointikartoitus). Lue ensin sen raportti ja virheloki.md, ja vertaa tämän viikon lukuja edelliseen kierrokseen.

Askeleet:
1. Kerää viimeisen 7 vuorokauden data: claude-jonon ja yöjonon tehtävät (kesto, kierrokset, onnistuiko, kaatumisen syy), LiteLLM-kulut tehtävätyypeittäin, uudelleenajot ja tyhjät kierrokset, Tonyn aika (montako PR:ää ja kysymystä päivässä, palaute.md). Lähteet: docs-repon tulokset, /var/lib/yojono/ (vain luku) ja `systemctl list-units --failed`.
2. Tunnista 3-5 suurinta hukkaa tai pullonkaulaa: epäonnistuneet ajot, kalliit mallit rutiinissa, toistuvat samat virheet, PR:t joita Tony ei ehdi katsoa, liian isot tai pienet tehtävät, laatuotoksen löytämät toistuvat virheet.
3. Jokaiselle ehdotus: mitä muutetaan, arvioitu säästö (raha, aika, Tonyn minuutit), riski ja kuka päättää.
4. Toteuta PR:nä vain selvästi turvalliset pienet korjaukset (testit, dokumentaatio, lokien selkeys, turhan toiston poisto). Loput ovat päätöksiä Tonylle sunnuntaisuunnitteluun.
5. Raportin alkuun viiden rivin tiivistelmä: mikä parani edellisestä viikosta, mikä paheni, mitä Tonylta tarvitaan.

Rajat: ei kulukattojen, oikeuksien, mallien vaihtojen eikä ajastusten muutoksia. Ehdota ne raportissa. Ei mergeä. Ei julkaisua.
Valmis kun: priorisoitu lista, mahdolliset PR-linkit ja rivi "Todennettu käytössä: miten".
