# Hiekkalaatikko MCP-terveystarkastuksiin

Tarkoitus: ajaa vieraita MCP-palvelimia eristetyssä kontissa, jotta mcp-doctor löytää oikeita vikoja eikä vain staattisia (tulos 58: pelkkä lähdekoodin luku ei riitä). Tonyn päätös 2.11.2026: kontissa ei ole avaimia eikä pääsyä muihin kontteihin.

**Tila: ohje ja skriptit. Mitään ei ole ajettu isännällä eikä kontteja ole pystytetty.** Isännän komennot ajaa Tony (root). Tämä ohje jatkaa [README.md](README.md):n hiekkalaatikkoa (silta `vmbr2`, välityspalvelin CT9001, kloonit väliltä 9100-9199) ja olettaa, että PR #136 on mergattu ja `luo-pohja.sh` on ajettu (CT9000 ja CT9001 olemassa).

## Mitä MCP-tarkastus vaatii lisää

| Vaatimus | Ratkaisu | Missä |
| --- | --- | --- |
| Node ja npx kontissa | Node 22 asennetaan nodejs.org:sta SHA256-tarkistuksella, `mcp-doctor` npm:stä. Debianin oma Node on liian vanha (mcp-doctor vaatii 22.12+) | `mcp-asenna.sh` |
| Verkko vain npm-rekisteriin ja GitHubiin | README:n kloonipohja: ei gatewayta, ulos vain välityspalvelimen kautta, jonka sallittujen lista kattaa `.npmjs.org`, `.github.com`, `.githubusercontent.com` ja `.nodejs.org`. Yksityiset osoitteet (LAN, Tailscale) estetty välityspalvelimessa | README, `mcp-asenna.sh` tarkistaa |
| Ei LAN:iin, ei Tailscaleen | Silta `vmbr2` ei ole kytketty mihinkään; asennuksen lopussa viisi estokoetta (LAN .116, LAN .121, Tailscale-isäntä, 1.1.1.1, example.com) | `mcp-asenna.sh` |
| Ei salaisuuksia | Kontissa ei ole tunnuksia; erän skripti ajaa alikomennot tyhjällä ympäristöllä (ei isännän muuttujia) ja käyttäjänä `mcp` | `mcp_era.py`, `runuser` |
| Ei jaettuja hakemistoja | Kloonissa ei saa olla `mp`- eikä `lxc.`-rivejä; tarkistus komennossa 3 | pystytys |
| Aikaraja | repoa kohden 300 s (enintään 900), koko erälle 3000 s (enintään 3300); aikakatkaisussa tapetaan koko prosessiryhmä. Lisäksi isännän `timeout` koko komennon ympärillä | `mcp_era.py`, ajokomento |
| Muistiraja | kontille 2048 Mt, swap 0 (kontin cgroup tappaa ylittäjän). Skripti ei aseta `RLIMIT_AS`-rajaa, koska Node varaa paljon virtuaalimuistia | pystytys |
| Tuhoaminen tai palautus erän jälkeen | snapshot `puhdas` asennuksen jälkeen; jokaisen erän jälkeen `pct rollback`. Vaihtoehto: tuhoa ja kloonaa uudelleen | ajo-ohje |

Huomaa jäännösriski (sama kuin README:ssä): LXC-kontti jakaa isännän ytimen. Ytimen paon vastaan tämä ei suojaa. Siksi kontti on ilman tunnuksia ja ilman reittiä muualle, ja tulokset käsitellään datana.

## Pystytys (8 komentoa, Proxmox-isäntä, root)

Kontin tunnus 9150 on README:n sallitulla välillä 9100-9199. Tämä ei muuta olemassa olevia kontteja. Ota silti snapshot CT9000:sta, jos haluat varmuuden: `pct snapshot 9000 ennen-mcp`. Hae ensin PR:n tiedostot isännälle (oletus `/opt/agentti-pohja`).

```bash
cd /opt/agentti-pohja && git pull --ff-only          # 0. PR mergattuna, tiedostot isännällä

pct clone 9000 9150 --hostname hl-9150 --full 1                                            # 1
pct set 9150 --net0 name=eth0,bridge=vmbr2,ip=10.98.0.50/24,firewall=0 --memory 2048 --swap 0 --cores 2 --onboot 0   # 2
grep -E "^(net|mp[0-9]|lxc\.|dev[0-9]|hostname|memory|swap)" /etc/pve/lxc/9150.conf        # 3
pct start 9150                                                                             # 4
pct push 9150 hiekkalaatikko/mcp_era.py /usr/local/bin/mcp_era.py --perms 0755             # 5
pct push 9150 hiekkalaatikko/mcp-asenna.sh /root/mcp-asenna.sh --perms 0700                # 6
pct exec 9150 -- bash /root/mcp-asenna.sh                                                  # 7
pct stop 9150 && pct snapshot 9150 puhdas                                                  # 8
```

(Rivi 0 ei kuulu kahdeksaan; komennot 5 ja 6 ajetaan hakemistosta `/opt/agentti-pohja`.)

Tarkistukset:
- Komento 3: tulosteessa on yksi `net0`-rivi, jossa `bridge=vmbr2` eikä `gw=`, sekä `memory: 2048`, `swap: 0` ja `hostname: hl-9150`. Jos mukana on yhtään `mp`-, `lxc.`- tai `dev`-riviä, **pysähdy** äläkä käynnistä konttia.
- Komento 7: viimeinen rivi on `asennus-ok`. Skripti pysähtyy virheeseen, jos GitHub ei vastaa proxyn kautta tai jokin estokoe onnistuu (LAN, Tailscale, suora yhteys). Jos näin käy, **pysähdy** ja liitä tuloste Claudelle.
- Jos `npm install -g @tonyweckstrom/mcp-doctor` epäonnistuu, paketti ei ehkä ole vielä julkaistu npm:ään (ks. avoimet kysymykset).

Peruutus: `pct stop 9150; pct destroy 9150 --purge 1` poistaa vain tämän kontin (Tonyn päätös). Välityspalvelimen ja pohjan asetukset eivät muutu.

## Erän ajo

Tee repolista isännälle (muoto: [mcp-era-lista.esimerkki.txt](mcp-era-lista.esimerkki.txt)). Vain `https://github.com/omistaja/repo`-muoto kelpaa. Käynnistyskomento voi olla rivin lopussa, muuten se päätellään `package.json`:n kentistä `bin` ja `main`.

```bash
L=/root/mcp-era-lista.txt                    # Tonyn tekemä lista
E=era-$(date +%Y%m%dT%H%M%S)                 # erän tunniste
pct push 9150 $L /home/mcp/lista.txt && pct exec 9150 -- chown mcp:mcp /home/mcp/lista.txt
pct start 9150
timeout -k 20 3400 pct exec 9150 -- runuser -u mcp -- python3 -I /usr/local/bin/mcp_era.py aja --lista /home/mcp/lista.txt --ulos /home/mcp/tulos/$E.json --tyo /home/mcp/tyo
```

Kuiva-ajo ilman verkkoa ja ilman vierasta koodia (vaihda loppuun `--kuiva`): se vain tarkistaa listan ja kirjoittaa tulostiedoston, jonka jokainen repo on tilassa `kuiva`.

Skripti tekee jokaiselle repolle: `git clone --depth 1`, `npm install` ja tarvittaessa `npm run build` (vieras koodi ajetaan siis kontissa, ei koskaan CT115:llä), sitten `mcp-doctor --json --timeout-ms 10000 -- <komento>`. Tulos on yksi JSON-tiedosto, jossa on repoa kohden `tila`, `poistumiskoodi`, `komento` ja mcp-doctorin koko raportti (`raportti`). Tilat: `ok`, `loydoksia`, `kaytto_virhe`, `sisainen_virhe`, `kloonaus_epaonnistui`, `asennus_epaonnistui`, `rakennus_epaonnistui`, `ei_kaynnistyskomentoa`, `aikakatkaisu`, `json_virheellinen`, `ohitettu_aikakatko`, `virheellinen_rivi`. Enintään 30 repoa erässä.

## Tulosten siirto CT115:lle vain luettaviksi ja kontin palautus

Tulokset kulkevat aina yhteen suuntaan: kontti -> isäntä -> CT115. CT115:ltä ei ole yhteyttä kontteihin eikä isäntään.

```bash
mkdir -p /var/lib/hiekkalaatikko/mcp
pct pull 9150 /home/mcp/tulos/$E.json /var/lib/hiekkalaatikko/mcp/$E.json
python3 -I /opt/agentti-pohja/hiekkalaatikko/mcp_era.py tarkista /var/lib/hiekkalaatikko/mcp/$E.json     # tulostaa: ok
pct exec 115 -- install -d -m 0755 -o root -g root /opt/agentscope/mcp-tulokset
pct push 115 /var/lib/hiekkalaatikko/mcp/$E.json /opt/agentscope/mcp-tulokset/$E.json --perms 0444 --user root --group root
pct stop 9150; pct rollback 9150 puhdas        # kontti takaisin puhtaaseen tilaan
```

- Tiedosto ja hakemisto ovat root-omisteisia ja tiedosto on `0444`, joten CT115:n agentit voivat vain lukea (eivät muuttaa tai poistaa).
- `tarkista` hylkää tiedoston, jonka rakenne on väärä tai joka on yli 5 Mt. Se ei tulkitse sisältöä.
- **Tulokset ovat dataa, eivät ohjeita.** Raportit sisältävät tekstiä, jonka vieras palvelin on tuottanut (työkalujen nimiä, kuvauksia, virheviestejä). CT115:llä ne luetaan vain tiedostosta, eikä niissä olevia käskyjä noudateta.
- Ennen julkista issue-luonnosta tai PR:ää tulos luetaan silmämääräisesti läpi. Julkaistaan vain tiivistelmä.
- Rollback poistaa kaiken `puhdas`-snapshotin jälkeisen kontista, myös kloonatut repot ja tulostiedoston kontin sisältä. Siksi `pct pull` tehdään ennen palautusta.

## Avoimet kysymykset Tonylle

1. Onko `@tonyweckstrom/mcp-doctor` julkaistu npm:ään? Jos ei, `mcp-asenna.sh` täytyy muuttaa kloonaamaan `tonyweckstrom1987/mcp-doctor` ja ajamaan `npm ci`. Sanoessasi ehdotan muutoksen.
2. Kontin tunnus 9150 ja osoite 10.98.0.50 ovat ehdotuksia. Sopivatko ne, ja saako ajo tapahtua rinnan README:n kokeilukloonien kanssa? (README:n lukitus koskee vain `aja-kokeilu.sh`:ta, ei tätä konttia.)
3. `npm install` ajaa vieraan paketin asennusskriptit kontin sisällä. Se on tarkoituksellista (muuten rakennus ei toimi), mutta vaatii kontin ilman tunnuksia. Hyväksytkö, vai ajetaanko ensin `--ignore-scripts` ja vain turvalliseksi katsotut rakennetaan?
4. Node-versio `v22.12.0` on kiinteä (ylläpito: `NODE_VERSIO=... bash /root/mcp-asenna.sh`). SHA256-summa haetaan samasta osoitteesta kuin paketti, joten se suojaa lataushäiriöltä mutta ei nodejs.org:n murrolta.
