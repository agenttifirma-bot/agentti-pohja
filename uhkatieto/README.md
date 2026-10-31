# uhkatieto: tietoturvadatan keraaja

Vaihe 1 (Tonyn paatos 30.10.2026): vain **kerataan** julkista tietoturvadataa talteen. Ei raportteja, ei Telegram-lahetyksia,
ei LLM-kutsuja: keraaja ei anna syotteiden tekstia millekaan mallille. Syotteiden sisalto on dataa, ei ohjeita
(tallennetaan sellaisenaan, ohjausmerkit siivotaan, url hyvaksytaan vain http(s)). Ei Tor-verkkoa eika dark web -lahteita.

## Mita kerataan

| Lahde | Osoite | Tila |
|---|---|---|
| CISA KEV (kayttoon jo hyodynnetyt haavoittuvuudet) | cisa.gov known_exploited_vulnerabilities.json | kaytossa, ~1 800 rivia |
| MITRE ATLAS (AI-hyokkaystekniikat, lievennykset, tapaukset) | github.com/mitre-atlas/atlas-data, dist/v6/ATLAS-latest.yaml | kaytossa, ~340 rivia |
| NVD uudet CVE:t, hakusanat LLM, AI, agent, MCP | services.nvd.nist.gov REST 2.0 | kaytossa, ~150 CVE:ta / viikko |
| abuse.ch URLhaus / ThreatFox | urlhaus.abuse.ch, threatfox.abuse.ch (API-osoitteet tarkistetaan avaimen kanssa) | **vain suunnitelma** (ks. alla) |
| AlienVault OTX, Have I Been Pwned | otx.alienvault.com, haveibeenpwned.com | **vain suunnitelma**, vaativat avaimen |

Havainnot 31.10.2026 (testattu):
- abuse.ch:n vanhat avoimet lataukset (`urlhaus.abuse.ch/downloads/...`, `threatfox.abuse.ch/export/json/recent/`) palauttavat **410 Gone**
  ja dokumentaation mukaan nykyinen API/export vaatii Auth-Keyn. Tehtavan rajan mukaan avaimia vaativia lahteita ei toteuteta
  ilman Tonyn omaa avainta, joten abuse.ch jai tekematta. Kun Tony on rekisteroinyt ilmaisen avaimen (abuse.ch Community Hub),
  lisataan jasenninkohdat samalla mallilla (jasentimet.py + fixture + testi); avain luetaan EnvironmentFile:sta, ei koskaan koodista.
- ATLAS: vanha `dist/ATLAS.yaml` on merkitty vanhentuneeksi (v5.6.0). Keraaja lukee `dist/v6/ATLAS-latest.yaml`, joka on git-symlink
  (raw-palvelu palauttaa vain kohteen nimen); nimi validoidaan regexilla ennen toista hakua.
- PyYAMLia ei ole, joten ATLAS luetaan rivipohjaisella lukijalla, joka tuntee vain osiot techniques, mitigations, case-studies
  ja kentat name, created-date. Raaka YAML talletetaan aina, joten muodon muuttuessa data ei katoa, vain normalisointi pitaa korjata.
  Rivimaaran tarkistus: ajon "atlas: ok, N rivia" pitaa vastata `grep -c` -laskentaa (31.10.: 342 = 342).
- NVD: avaimeton raja on 5 pyyntoa / 30 s, joten pyyntojen valissa odotetaan 7 s. Ikkuna oletuksena 7 paivaa (`--nvd-paivia`, enint. 120 = NVD:n raja);
  paallekkaisyys on tarkoituksellista, duplikaatit estetaan. NVD:n avainta ei kayteta (ei tarvetta 4 pyynnolle/vrk).
  Hakusana `AI` ja `agent` osuvat myos asiaan kuulumattomiin CVE:ihin: rivit saavat tagin `kw-<hakusana>`, suodatus tehdaan vasta hyodyntamisvaiheessa.

## Tallennus

`--tila HAKEMISTO` (palvelussa /var/lib/uhkatieto):
- `raaka/PVM/<lahde>.gz`: raakavastaukset gzipattuna. Jos sisalto on sama kuin edellisella talletuksella (sha256), uutta tiedostoa ei kirjoiteta.
- `uhkatieto.sqlite`: taulu `uhkat(lahde, id, pvm, otsikko, tagit, url, haettu)`, PRIMARY KEY (lahde, id) = duplikaattiesto.
  Toistuva rivi ei luo uutta, mutta tagit yhdistetaan (esim. sama CVE loytyy hakusanoilla LLM ja MCP). Lisaksi `ajot` (ajokirjanpito) ja `raaka` (tiivisteet).
- Yksi lahde voi epaonnistua muiden estamatta; poistumiskoodi on silloin 1 ja lokiin tulee vain virheen tyyppi / HTTP-tila.

Esimerkkikysely: `sqlite3 /var/lib/uhkatieto/uhkatieto.sqlite "select pvm,id,otsikko from uhkat where lahde='kev' order by pvm desc limit 10"`

## Levytila-arvio (mitattu 31.10.2026)

- KEV raaka gzip ~200 kt, muuttuu lahes joka paiva: ~73 Mt/vuosi.
- ATLAS raaka gzip ~270 kt, muuttuu noin kuukausittain: ~3-4 Mt/vuosi.
- NVD (4 hakusanaa) ~80 kt/ajo, mutta sisalto vaihtelee paivittain: pahimmillaan ~30 Mt/vuosi.
- SQLite: ~2 300 rivia nyt (~1 Mt), kasvu ~100-200 riv/vrk -> alle 30 Mt/vuosi.
- **Yhteensa ~100-150 Mt/vuosi.** 2 Gt levy riittaa vuosiksi. Poisto/arkistointi tehdaan kasin (keraaja ei poista mitaan).

## Kayttoonotto (Tonylle; mitaan ei ole asennettu)

Ehdotus: **uusi pieni oma CT (esim. CT118 "uhkatieto")**, ei CT115. Syy: syotteet ovat epaluotettavaa dataa ja CT115:ssa on agentit ja holviyhteys;
keraaja ei tarvitse yhtaan salaisuutta, vain ulosmenevan HTTPS:n (443) neljaan osoitteeseen. Vaihtoehto: CT115, jos uutta konttia ei haluta (silloin oma kayttaja `uhkatieto`).

1. Tony ottaa tarvittaessa snapshotin hostilta ja luo CT:n (esim. Debian, 1 vCPU, 512 Mt, 4 Gt levy). Ei Tailscalea eika holviyhteytta tarvita.
2. Kayttaja ja kansiot (CT:ssa, roottina):
   `useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin uhkatieto`
   `install -d -o uhkatieto -g uhkatieto -m 750 /var/lib/uhkatieto`
3. Koodi: kloonaa agentti-pohja kansioon `/opt/agentit/agentti-pohja` (vain luku kayttajalle uhkatieto).
4. Kokeile kasin: `cd /opt/agentit/agentti-pohja && sudo -u uhkatieto python3 -B -m uhkatieto --tila /var/lib/uhkatieto`
   (odotus: kolme rivia "ok", ensimmainen ajo ~1 min NVD-odotusten takia).
5. Ajastus: kopioi `uhkatieto/ajastus/uhkatieto.service.mall` ja `.timer.mall` nimilla `uhkatieto.service` / `uhkatieto.timer` hakemistoon `/etc/systemd/system/`,
   sitten `systemctl daemon-reload && systemctl enable --now uhkatieto.timer`. Tarkista `timedatectl` (ajo 03:30 palvelimen aikaa) ja `systemctl list-timers uhkatieto.timer`.
6. Seuranta: `journalctl -u uhkatieto.service -n 20` ja `sqlite3 ... "select * from ajot order by aika desc limit 6"`.
7. Palomuuri: salli ulos vain cisa.gov, raw.githubusercontent.com, services.nvd.nist.gov (huom: palomuurimuutokset teet itse).

## Testit

Ei verkkoa: jasentimet ja keraaja testataan fixture-tiedostoilla (`testit/fixtures/`) ja valehaulla.
`python3 -m unittest discover -s uhkatieto -t . -p 'test_*.py' -v` (repon juuresta). Vain stdlib.

## 5 ideaa datan hyodyntamiseen myohemmin

1. **Oma riippuvuusvahti:** vertaa KEV/NVD-rivien tuotetageja Tonyn kontteihin ja pakettilistoihin (dpkg, pip) ja nosta vain osumat esiin.
2. **MCP/LLM-haavoittuvuuskartta:** NVD-rivit `kw-mcp` / `kw-llm` -> trendi kuukausittain (mika luokka kasvaa: injektio, polkuhyokkays, autentikointi) portfolion blogipostaukseen.
3. **ATLAS-vastaavuus omiin agentteihin:** kay ATLAS-tekniikat lapi omaa agenttijarjestelmaa vasten (esim. prompt injection, tool poisoning) ja kirjaa, mika on jo estetty koodissa (liittyy injektio-/hiekkalaatikkotesteihin).
4. **Viikkokatsaus ilman LLM:aa:** SQL-yhteenveto "uudet KEV-rivit + uudet AI-CVE:t" viikkoajon liitteeksi; LLM mukaan vasta, kun syotteet on eristetty injektiota vastaan.
5. **Opintoharjoitukset / ura:** valitse viikon KEV-rivi, lue CVE ja korjaus, kirjoita lyhyt analyysi (mika luokka, miksi hyodynnetaan, miten puolustetaan) - tietoturva-alan portfolio.
