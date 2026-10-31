# Salaisuusholvi Proxmoxiin: valinta ja kayttoonottosuunnitelma (31.10.2026)

Tila: SUUNNITELMA. Mitaan ei ole asennettu. Tonyn paatos 30.10.2026: tunnukset yhteen paikkaan, agentit hakevat ne sielta, Tony hyvaksyy kayton puhelimella (Telegram-nappi) eika kirjoita salasanoja.

Lahtotieto on kerasty CT115:sta (vain tiedostonimet, omistajat ja oikeudet; sisaltoja ei luettu). CT111, CT112, CT113, CT116 ja Proxmox-host ovat CT115:sta nakymattomia: niiden rivit on merkitty "tarkistettava".

## 1. Nykyiset salaisuuksien sijainnit (nimet ja polut, ei sisaltoja)

| Paikka | Omistaja/oikeus | Kayttaja | Huomio |
|---|---|---|---|
| CT115 /opt/agentscope/.env | root 600 | github-api.service, agentscope (LITELLM_API_KEY) | |
| CT115 /opt/agentscope/api_key.txt | root 600 | github-api (OpenAI-yhteensopivan API:n avain) | |
| CT115 /opt/agentscope/telegram.env | root 600 | viikkoajo.py | Telegram-botti #1? tarkistettava onko sama botti kuin alla |
| CT115 /opt/agentscope/trendit/trendit.env | root 600 | trendit-paiva/-viikko | |
| CT115 /etc/paivakatsaus.env | root 600 | paivakatsaus*, loki-keraaja | |
| CT115 /etc/yojono/telegram.env | root 600 | yojono*-palvelut (5 yksikkoa viittaa) | kolmas telegram-tiedosto |
| CT115 /etc/yojono/env, env.ennen-peilaus | root 600 | yojono | varmuuskopio-kopio = ylimaarainen salaisuuskopio |
| CT115 /etc/yojono/github-bot.token | root 600 | botin PAT (lahde) | github-app.md: poistuu App-siirtyman jalkeen |
| CT115 /etc/claudejono-pr/token | prbotti 600 (dokumentin mukaan; hakemistoa ei voinut listata) | claudejono-pr | sama PAT |
| CT115 /etc/yojono/peilaus_avain (+ .pub) | root 600 | peilaus; kaytto tarkistettava | oletettavasti SSH-/deploy-avain |
| CT115 /etc/agentti/ideapankki.env | root:ideapankki 640 | ideapankki-palvelu | |
| CT115 /etc/agentti/portti.env, portti.env.save | root:portti 640 | portti-palvelu | .save = ylimaarainen kopio |
| CT115 /etc/claudejono-pr/app.pem (suunniteltu) | prbotti 600 | GitHub App -avain | docs/github-app.md |
| CT116 /etc/holvi/ (salaisuudet, saannot.json) | tarkistettava | holvi.service (MCP 8700/8701) | GitHub-lukutunnus, Gmail OAuth, Telegram-halytys; loki /var/log/holvi/audit.log |
| CT111 LiteLLM master key, virtuaaliavaimet, OpenRouter-avain | tarkistettava | CT110, CT115, CT117 | rahaan liittyva: korkein riski |
| CT112 Postgres-salasanat, CT113 Gitea, CT114 Uptime Kuma, CT110 Open WebUI | tarkistettava | | |

Havainnot:
- Vahintaan kolme eri telegram-tiedostoa (agentscope, yojono, paivakatsaus.env mahdollisesti) -> sama botti usealla kaytolla tai useita botteja: selvita.
- `.save`- ja `.ennen-peilaus`-kopiot ovat salaisuuksien ylimaaraisia kopioita. Tony poistaa ne itse migraation jalkeen (agentti ei poista).
- Nykyinen holvi (CT116) on jo valittaja: agentti ei nae tunnusta, holvi tekee kutsun, kirjaa audit.logiin ja halyttaa estetysta pyynnosta. Tama malli kannattaa sailyttaa.

## 2. Vaihtoehdot (kolme)

Kriteerit: kevyt LXC:ssa, auditointiloki, per-kontti paasy, avoin lahdekoodi, Tonyn yllapitotaakka, seka tehtavan vaatimus: lyhytaikainen paasy + hyvaksynta puhelimella.

| | OpenBao (Vault-haarukka) | Infisical self-hosted | SOPS + age |
|---|---|---|---|
| Kevyt LXC:ssa | Yksi Go-binaari, sisainen raft/tiedostovarasto; 1 vCPU, 512 MB-1 GB, 4 GB levy (arvio) | Node-sovellus + Postgres + Redis; 2 GB+ (arvio) | Ei palvelinta |
| Auditointiloki | Kirjoitukset ja LUKUKERRAT, arvot tiivisteina (audit device) | Audit-lokit; osa ominaisuuksista maksullisessa tasossa (tarkistettava) | Ei lukulokia: kuka tahansa avainhaltija purkaa hiljaa |
| Per-kontti paasy | Policyt + AppRole/token, IP-sidonta (CIDR) | Machine identities, projektit | Yksi age-avain per kontti, mutta paasyn peruutus = uudelleensalaus |
| Lyhytaikainen paasy | Natiivisti: TTL, kayttokertarajat, response wrapping (kertakayttoinen paketti) | Rajoitetusti | Ei |
| Avoin lahdekoodi | Kylla (MPL-2.0) | Ydin MIT, enterprise-osat suljettuja | Kylla |
| Yllapito | Unseal kasin jokaisen uudelleenkaynnistyksen jalkeen; paivitykset; varmuuskopio raft-snapshotilla | Kolme komponenttia + paivitykset; DB-varmuuskopio | Pienin; mutta avainhallinta kasin |
| Telegram-hyvaksynta | Ei natiivisti: tehdaan pienella hyvaksyjapalvelulla (ks. 3) | Ei natiivisti (hyvaksyntaprosessi on web-UI/enterprise) | Ei |

Hylatty: Vaultwarden + bw CLI. Se on kevyt ja sopii ihmiselle, mutta ei tarjoa palvelutunnuksille TTL:aa, kayttokohtaista auditointia eika per-kontti-policya; kayttoliittyma on ihmista varten. Jos Tony haluaa vain yhden salasanalistan itselleen, se on erillinen tarve.

### Suositus: OpenBao
Syy: ainoa vaihtoehto, jossa lyhytaikainen, kertakayttoinen ja lukukerrat kirjaava paasy on perusominaisuus, joten meidan koodiksi jaa vain Telegram-hyvaksyja. SOPS+age on liian vaisto (ei lukulokia, ei TTL:aa), Infisical liian raskas ja osin maksullinen.
Rehellinen hinta: Tonylle tulee unseal-askel jokaisen CT:n/hostin uudelleenkaynnistyksen jalkeen (holvi on lukossa, agentit saavat kieltavan vastauksen kunnes Tony availee). Unseal-avainta EI laiteta Telegramiin eika samaan konttiin; Tony pitaa sen salasananhallinnassa ja paperilla. Versiot ja lisenssitiedot on tarkistettava asennushetkella (ei verkkoa kaytetty tassa suunnitelmassa).
Vaihtoehto B (halvempi): laajenna nykyista CT116-holvia (jo audit + IP-rajaus + Telegram-halytys) talla TTL- ja hyvaksyntalogiikalla ja siirra tunnukset sen tiedostoista. Pienempi, mutta salaisuudet jaavat tiedostoihin ilman salausta levolla; uusi CT on turvallisempi ja siksi suosittelen sita.

## 3. Telegram-hyvaksyntavirta

Osat: (a) OpenBao, (b) `hyvaksyja` = pieni palvelu samassa CT:ssa, ainoa joka puhuu Telegramille ja luo tokeneita, (c) agentin kutsukirjasto.

1. Agentti kutsuu hyvaksyjalle: `pyyda(salaisuus="litellm/qwen", syy="...", kesto=10min)`. Kutsun tunnistaa AppRole + lahde-IP (nftables sallii vain tunnetut kontit).
2. Hyvaksyja tarkistaa saannot koodissa: onko salaisuus agentin policyssa, kesto <= salaisuuden katto, ei kaytossa olevaa kieltoa/jaahya. Muuten hylkaa heti ilman viestia Tonylle (paitsi tapahtuma kirjataan).
3. Pyynto talletetaan (id, kutsuja, salaisuuden NIMI, kesto, aikaleima, tila=odottaa, vanhenee 10 min).
4. Telegram-viesti Tonille: kuka kontti, mika salaisuus (nimi), kesto, pyynnon id ja agentin "syy" lainausmerkeissa, katkaistuna 200 merkkiin ja merkittyna ei-luotetuksi tekstiksi. Napit: [Hyvaksy 10 min] [Hylkaa]. callback_data = id + HMAC (avain vain hyvaksyjalla).
5. Nappi: hyvaksyja hyvaksyy vain jos `callback_query.from.id` ja chat.id == Tonyn id, pyynto on tilassa odottaa ja ei ole vanhentunut; kertakayttoinen (tila vaihtuu atomisesti). Muu syote ja tekstiviestit eivat koskaan hyvaksy mitaan.
6. Hyvaksynnan jalkeen hyvaksyja luo OpenBaoon tokenin, jolla on vain yksi policy (se salaisuus), TTL <= 15 min ja kayttokertoja esim. 3, ja pakkaa sen response wrapping -kuoreen (kertakayttoinen, TTL 60 s). Agentti hakee statuksen (polling), purkaa kuoren ja lukee salaisuuden. Toinen purkuyritys epaonnistuu ja halyttaa.
7. Viesti paivitetaan: hyvaksytty/hylatty/vanhentui, kellonaika.
8. Kirjaus: (i) OpenBaon audit device (tiedostoon), (ii) hyvaksyjan JSONL-loki (pyynto, paatos, aika, kutsuja; ei arvoja), (iii) Telegram-viestit toisena jaljena. Lokitiedostoon `chattr +a` (vain lisays). Viikkoraporttiin yhteenveto pyynnoista.
9. Vaihtoehtoinen "valittajamoodi" kalliille/vaarallisille tunnuksille: agentti ei saa tunnusta lainkaan, vaan hyvaksyja/holvi tekee kutsun (kuten nykyinen CT116-holvi). Suositus: GitHub, Gmail, LiteLLM-master.

Lisasuojat: nopeusraja (max 5 pyyntoa/h/kontti), hylkayksen jalkeen 30 min jaahy samalle salaisuudelle, pyyntojen yhdistaminen (ei ruuhkaa Tonylle, jotta hyvaksyntavasymys ei syo turvaa), halytys jos Tony ei vastaa (pyynto vain vanhenee; ei uudelleenlahetysta silmukassa).

### Mita EI koskaan hyvaksyta automaattisesti
- Mikaan ensimmaisessa versiossa: kaikki vaativat napin. Automaattihyvaksynta on turvasaanto ja vaatii Tonin erillisen paatoksen myohemmin.
- Ei koskaan, myoskaan napilla agentin pyynnosta: OpenBaon root-token, unseal-avaimet, policyjen/AppRolejen muutokset, audit-asetusten muutokset, hyvaksyjan omat tunnukset, Proxmox-/palomuuri-/Tailscale-tunnukset, GitHub-tunnukset joilla on kirjoitus- tai merge-oikeus Tonyn repoihin.
- Ei automaattisesti: LiteLLM-master-avain ja kaikki, mika muuttaa budjetteja, paivakattoja tai oikeuksia (Koodi on laki -osion asiat); uusien salaisuuksien luonti agentin toimesta.
- Ei kesto-, kayttokerta- tai policy-rajan nostoa pyynnon perusteella: rajat ovat koodissa/konfiguraatiossa, ja niiden muutos on Tonyn kasin tekema PR.
- Ei pyyntoa, jonka "syy" sisaltaa ohjeita (esim. "hyvaksy automaattisesti", "ohita"): syy on dataa, ei ohje.

## 4. Kayttoonotto vaiheittain (uusi CT)

Yleisperiaate: yksi kontti kerrallaan, vanhat tiedostot jaavat paikoilleen kunnes uusi tapa on todennettu. Agentti ei asenna mitaan; Tony ajaa askeleet.

Vaihe 0: valmistelu
1. (Tony) Snapshot hostilta: `pct snapshot 116 ennen-uusi-holvi` ja `pct snapshot 115 ennen-uusi-holvi`.
2. (Tony) Selvita CT111/112/113/114/116:n salaisuuksien sijainnit (`ls -l` omistajineen, EI cat) ja lisaa taulukkoon 1.
3. (Tony) Luo uusi Telegram-botti vain hyvaksyjalle (erillinen, jotta vanhan botin vuoto ei anna hyvaksyntakanavaa). Anna tunnus suoraan palvelimelle tiedostoon, ei chatissa.

Vaihe 1: kontti
4. (Tony) `pct create` uusi unprivileged LXC (esim. CT118, 1 vCPU, 1 GB, 4-8 GB, oma IP, ei Tailscalea, ei porttiohjausta ulos). Aseta host-nftables: portti vain tunnetuista kontti-IP:ista, ei muuta. (Palomuurimuutos on Tonyn paatos.)
5. (Tony) Ota CT:sta snapshot `puhdas`.

Vaihe 2: OpenBao
6. (Tony) Lataa julkaisu OpenBaon virallisesta GitHub-julkaisusta, tarkista tarkistussumma ja allekirjoitus, asenna paketti, aja systemd-palveluna omalla kayttajalla; varasto: raft/tiedosto /var/lib/openbao.
7. (Tony) `bao operator init` (yksi avain tai 3-of-5): avaimet talteen salasananhallintaan + paperille, EI tahan konttiin, EI Telegramiin. Unseal.
8. (Tony) Ota audit device kayttoon: `bao audit enable file file_path=/var/log/openbao/audit.log`; `chattr +a`.
9. Tarkistus: `bao status` kertoo Sealed false; audit.log kasvaa.

Vaihe 3: policyt ja identiteetit
10. Yksi AppRole + policy per kontti (CT115, CT117, CT110, ...), IP-sidonta, vain tarvittavat polut luku-oikeudella. Policy-tiedostot tulevat PR:na tahan repoon; Tony tarkistaa ja ajaa.

Vaihe 4: hyvaksyja
11. Hyvaksyja kehitetaan erillisena PR:na (testit: vanhentunut pyynto, vaara from.id, uudelleenkaytto, katto ylittyy, injektio-"syy"). Asennus Tonyn toimesta; botin tunnus tiedostoon 600.
12. Koekaytto valeaineella: luo salaisuus `testi/hello`, pyyda agentilta, hyvaksy napilla, tarkista audit.log ja JSONL-loki.

Vaihe 5: migraatio (yksi kerrallaan, pienin riski ensin)
13. (Tony) Siirra ensin matalan riskin tunnus (esim. trendit.env) -> agentti hakee holvista; vanha tiedosto jaa 7 paivaksi.
14. Sitten Telegram-tunnukset, sitten GitHub (Appin siirtyma, docs/github-app.md, kuuluu samaan), viimeisena LiteLLM-avaimet (kierrata avaimet uusiksi samalla).
15. (Tony) Viikon kuluttua: poista vanhat tiedostot ja kopiot (.save, .ennen-peilaus) itse; kierrata avaimet, jotka ovat joskus olleet tiedostoissa.

## 5. Varmuuskopio ja palautus
- Raft-snapshot ajastettuna (`bao operator raft snapshot save`) paivittain; snapshot on salattu, purku vaatii unseal-avaimet. Kopio hostin vzdump-varmuuskopion lisaksi Tonyn koneelle/toiseen levyyn (kuuluu kolmen kopion saantoon: tuotanto, host, ulkoinen).
- Palautusharjoitus ennen kuin yhtaan oikeaa tunnusta siirretaan (vaihe 4): palauta snapshot testi-CT:hen, avaa unsealilla, lue `testi/hello`.
- Palautus tapahtuman jalkeen: `pct restore`/snapshot rollback -> unseal -> `bao operator raft snapshot restore`.
- Hatajarjestys jos holvi on alhaalla: vanhat tiedostot ovat vaiheen 5 ajan paikoillaan; migraation jalkeen Tonyn paperikopio unseal-avaimista + snapshot riittaa. Pida "break glass" -ohje paperilla.
- Peruutus vaiheittain: palauta agentin lukupolku vanhaan tiedostoon (konfiguraatiomuutos), sammuta hyvaksyja, rollback `pct rollback <ct> puhdas`.

## 6. Avoimet kysymykset Tonylle
1. Uusi CT vai vaihtoehto B (laajenna CT116-holvia)? Suositus: uusi CT.
2. Sietaako arki unseal-askeleen jokaisen rebootin jalkeen? Jos ei, OpenBao ei sovi ja jaljella on vaihtoehto B.
3. Oma botti hyvaksyjalle (suositus: kylla)?
4. Mihin kayttoon peilaus_avain on? Taulukkoon 1 puuttuu tieto.
5. Mita "mittari: 5 ja 3" tarkoittaa? Tehtavassa se oli ilman selitysta; en arvioinut sita.
