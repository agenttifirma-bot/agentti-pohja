# Valvottu autonomia: mittarit ja portaat

Periaate (Tony 30.10.2026): mita paremmin agenttien tyota valvotaan, sita enemman ne saavat toimia itsenaisesti.

## Mittarit (toteutettu: `python3 -m agentti.autonomia`)

Kaytto: `python3 -m agentti.autonomia [--valimuisti POLKU] [--loki POLKU] [--kirjoita POLKU] [PAIVIA]` (oletus 60 vrk).

- Agentit: `yojono`, `claude-jono`, `pilvi`, `muu`. Tunnistus botin (`agenttifirma-bot`) PR:n otsikosta, kuvauksesta ja haarasta (heuristiikka; jos agentit merkitsevat PR:t eri tavalla, muuta `agentti_prsta`).
- Muutosluokat tiedostolistasta: `dokumentaatio`, `testit`, `riippuvuus-patch`, `pieni-korjaus` (enint. 50 rivia, 3 tiedostoa), `suurempi`, `suojattu` (mika tahansa suojattu polku, `pr_kutsu.suojattu` ja `yojono/`).
- Per ryhma: mergatut/suljetut/auki, mergaus-%, revertit (PR jonka otsikko on `Revert ...` ja viittaa #N), punainen CI (PR:n haaran ja mergecommitin check-runit), katselmoinnin loydokset (muiden kuin Tonyn ja PR:n tekijan rivikommentit) ja Tonyn kommentit.
- `--loki`: tapahtumalokin yhteenveto agenteittain (avataan vain luku -tilassa).
- `--valimuisti`: suljetut PR:t eivat muutu, joten niiden rikastus tallennetaan. Tunnistamaton GitHub-API sallii 60 pyyntoa/h, joten ilman muistia raportti on vajaa ja sanoo sen itse.

## Autonomiaportaat: ehdotus (EI kaytossa, Tony paattaa)

Luokan PR:t mergataan automaattisesti vain, kun kaikki ehdot tayttyvat saman agentin ja saman luokan osalta:

| Luokka | Kynnys (perakkaisia hyvaksyttyja) | Lisaehdot |
|---|---|---|
| dokumentaatio | 20 | nykyinen automerge-saanto pysyy; kynnys toimii pudotuksen vertailuna |
| testit | 20 | sama |
| riippuvuus-patch | 25 | vain x.y.Z -> x.y.Z+n; nyt automergen suojalistalla, siirto vaatii erillisen paatoksen |
| pieni-korjaus | 40 | max 50 rivia ja 3 tiedostoa; katselmointi ilman avoimia loydoksia |
| suurempi | ei koskaan | Tony katselmoi aina |
| suojattu | ei koskaan | suojatut polut eivat siirry |

- "Hyvaksytty" = mergattu, ei revertia, eika CI ole punainen PR:n haarassa tai mergecommitissa.
- Katko = hylkays, revert tai punainen CI. Putki alkaa alusta katkon jalkeen, ja uuden nousun ehto on lisaksi 14 vrk rauhoitusaika katkosta.
- Putoaminen: jos automergessa olevalla luokalla on katko 14 vrk sisalla, raportti nayttaa `PUDOTA` ja ehdottaa Tonylle luokan palauttamista katselmoitavaksi. Raportti ei muuta saantoja itse.
- Kaikki kynnykset ovat aloitusarvoja (`KYNNYKSET`, `RAUHOITUS_PAIVAA`); muutos on Tonyn paatos.

## Rajoitteet

- Revert tunnistetaan vain PR:sta, ei suorasta commitista. Ensimmaiset 100 PR:aa per repo.
- Rikastus (tiedostot, CI, kommentit) tehdaan enintaan 150 pyynnolla per ajo.
- Automerge-luokkien nykytila (`NYKYINEN_AUTOMERGE`) on peilattu kasin tools/automerge.py:sta.
