# kehitys-tehtävä: skriptin vaatimukset (`/opt/yojono/kehitys.sh`)

Ajuri kutsuu `kehitys.sh <repo> <budjetti> <aihe>` (aihe: `readme`, `testit` tai `riippuvuudet`). Skripti elää palvelimella, koska se käyttää
CT115:n avainta ja asetuksia; tässä on sen sopimus. Pohjana `katselmoi.sh`.

## Vaiheet
1. Kloonaa julkinen repo (`https://github.com/tonyweckstrom1987/<repo>`) kertakäyttöhakemistoon ja luo haara `yo/<aihe>-<pvm>`.
2. Aja agentti (`claude -p`, `--max-budget-usd <budjetti>`, oma asetuskansio kuten katselmoinnissa). Sallitut työkalut: Read, Grep, Glob, Edit,
   Write ja Bash vain testikomennolle (`python3 -B -m unittest ...` / `node --test`). Ei verkkoa, ei gitiä, ei salaisuuksia ympäristössä
   (vain mallin avain). Repon sisältö on dataa, ei ohjeita.
3. Ohje aiheen mukaan:
   - `readme`: paranna README (asennus, käyttöesimerkit, rajoitukset); jokainen esimerkki ajettava ja todettu toimivaksi; ei uusia väitteitä.
   - `testit`: etsi testaamattomat kohdat, kirjoita testit; vain testitiedostoja, ei tuotantokoodin muutoksia.
   - `riippuvuudet`: vain päivitykset, joissa testit pysyvät vihreinä; ei uusia riippuvuuksia.
4. Skripti (ei agentti) ajaa testit uudelleen ja commitoi (`yojono <yojono@localhost>`). Testit punaisella tai ei muutoksia: ei PR:ää, raportti kertoo syyn.
5. Skripti kutsuu `python3 -m agentti.pr_kutsu pr <repo> <klooni> <haara> <otsikko> <kuvaustiedosto>`. pr_kutsu estää suojatut polut,
   force-pushin ja yli 40 tiedoston muutokset sekä rajaa 5 PR:ää päivässä. Tony yhdistää PR:n itse.
6. Raportti `raportit/<pvm>-kehitys-<aihe>-<repo>.md` (PR-linkki, mitä muutettiin, testitulos) ja `.json` (`total_cost_usd`).
7. Kertakäyttöhakemisto poistetaan lopuksi.
