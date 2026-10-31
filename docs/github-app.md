# GitHub App PAT:n tilalle - suunnitelma (30.10.2026)

Tavoite: agenttifirma-botin PR-ketju ei enaa tarvitse pitkaikaista PAT:ia. Lyhytikaiset (1 h) asennustunnukset haetaan tarvittaessa, eika Tonyn tarvitse kierratta tunnuksia kasin.

## 1. Nykytila (vain polut ja kayttotarkoitus)
| Paikka | Mihin | Huomio |
|---|---|---|
| /etc/yojono/github-bot.token | alkuperainen PAT (root) | lahde; kopioidaan asennuksessa |
| /etc/claudejono-pr/token (600 prbotti) | PAT, jota `claudejono-pr` kayttaa | claudejono-kayttaja ei lue |
| agentti/pr_kutsu.py (`lue_tunnus`, `_git_ymparisto`) | push botin forkkiin (askpass), forkin synkkaus (`merge-upstream`, `synkkaa_fork`), PR:n avaus (`avaa_pr`) | kaikki samalla PAT:lla |
| claudejono/claudejono-pr, asenna-kayttaja.sh | sudo -u prbotti -kaare, asettaa `YOJONO_BOT_TUNNUS` | |
| yojono-ajuri (`fork_valmis`) | forkin esisynkkaus ennen mallikutsua | OLETUS_TUNNUS-polku |
| .github/workflows/automerge.yml | kayttaa repon omaa `GITHUB_TOKEN`ia, EI PAT:ia | mutta tunnistaa botin kirjautumisnimesta `agenttifirma-bot` |

PAT:ia ei kayteta muualla (grep: ei `secrets.*PAT`-viittauksia Actionseissa).

## 2. Oikeudet minimiin
Kaksi asennusta, koska fork on botti-tilin ja PR:n kohde Tonyn:
- **Asennus A (botti-tili agenttifirma-bot, valitut repot = forkit):** Contents: write (push, merge-upstream), Metadata: read. Ei Workflows, ei Pull requests.
- **Asennus B (Tonyn tili, valitut repot = REPOT-lista: agentti-pohja, mcp-model-router, ai-pr-reviewer-action, llm-stopcheck, ideapankki, evalkit, kauppatiimi):** Pull requests: write, Metadata: read. EI Contents-oikeutta, joten botti ei voi kirjoittaa Tonyn repoihin (nykyinen "ei oikeuksia" -periaate sailyy).
- Koodi pyytaa tokenin lisaksi rajattuna: `repositories:[yksi repo]` + vain roolin oikeus.
- Avoin tarkistus (vaihe 2): riittaako pelkka pull_requests:write PR:n avaamiseen julkisesta forkista; jos ei, selvita pienin lisaoikeus ennen kuin laajennat mitaan.

## 3. Tokenin haku
- Yksityinen avain: /etc/claudejono-pr/app.pem, 600, omistaja prbotti (sama hakemisto 700 kuin nykyinen token). Vain prbotti lukee; claudejono ja agentit eivat.
- Asetukset (ei salaisuus): /etc/claudejono-pr/app.json = app_id, avainpolku, asennus_fork, asennus_pr.
- Haku: JWT (RS256, 9 min, allekirjoitus `openssl dgst -sha256 -sign`, avainta ei lueta Pythonissa) -> POST /app/installations/ID/access_tokens -> `ghs_`-tunnus.
- Valimuisti: /var/lib/claudejono-pr/app-ASENNUS-REPO-ROOLI.json (600). Uusitaan, kun jaljella < 10 min.
- Vanheneminen kesken ajon: yksi `claudejono-pr`-ajo kestaa minuutteja ja saa tunnuksen, jossa on >= 10 min jaljella, joten vanheneminen ajon aikana on kaytannossa poissuljettu. Jos GitHub silti hylkaa (401), ajo epaonnistuu siististi ("push epaonnistui"/"HTTP 401"), eika vaaraa jaa; seuraava ajo hakee uuden. Hakuvirhe -> PAT-vara (kunnes PAT poistetaan).

## 4. Siirtyma
1. (Tony) Luo GitHub App (ks. 6) ja asenna kahdelle tilille.
2. (Tony) Tallenna avain ja app.json prbotille (ks. 6).
3. Rinnakkaiskaytto: merge tama PR -> `claudejono-pr` ottaa Appin kayttoon heti kun /etc/claudejono-pr/app.json on olemassa (wrapperiin yksi rivi, ks. 6). PAT pysyy paikallaan varana.
4. Testaa: yksi docs-PR koe-haarasta; tarkista PR:n tekija ja ettei stderrissa ole "PAT-varaa".
5. Automerge/PR-laatu: PR:n tekija on nyt `APPSLUG[bot]` eika `agenttifirma-bot`. tools/automerge.py, automerge.yml ja agentti/pr_laatu.py tunnistavat vain jalkimmaisen (turvallinen tila: automerge ei laukea). Jos haluat automergen tai tilastot ennallaan, se on erillinen turvasaantomuutos (kovakoodattu kirjautumisnimi); en muuta sita itse.
6. Viikon kuluttua: jos kaikki PR:t ovat kulkeneet Appilla, poista PAT (Tony: GitHub -> botin Settings -> Tokens -> revoke; ja `/etc/claudejono-pr/token`, `/etc/yojono/github-bot.token`).

## 5. Peruutus
- Poista (tai nimea) /etc/claudejono-pr/app.json -> wrapper ei aseta `YOJONO_APP_ASETUKSET`, ketju kayttaa PAT:ia heti. Ei koodimuutosta.
- Vakavammassa: revert tama PR; PAT-polku on koskematon.
- Avainvuoto: GitHub App -> Private keys -> Delete; luo uusi, korvaa app.pem.

## 6. Tonyn kasin tehtavat (numeroituna)
1. GitHub -> agenttifirma-bot-tilin Settings -> Developer settings -> GitHub Apps -> New. Nimi esim. `agenttifirma-pr`. Webhook pois. Oikeudet: Repository: Contents RW, Pull requests RW, Metadata R. Ei muita. "Only on this account" riittaa asennukselle A; jotta Tonyn tilille voi asentaa, valitse "Any account".
2. Asenna App botin tilille (A): vain forkit (kaikki REPOT-listan forkit). Asenna se Tonyn tilille (B): vain REPOT-listan repot. Jos haluat Contentsin vain A:lle, voit pienentaa B:n oikeudet asennuksen hyvaksynnassa vain jos GitHub sallii; muuten pida Contents pois Appin oikeuksista ja kokeile ensin pelkalla pull_requests-oikeudella (kohta 2, avoin tarkistus).
3. Generoi Private key (.pem). Siirra se CT115:een ilman, etta se kulkee agentin nakyviin: `install -o prbotti -g prbotti -m 600 /polku/avain.pem /etc/claudejono-pr/app.pem`; poista alkuperainen lataus.
4. Hae App ID ja molemmat installation ID:t (asennuksen URL: .../settings/installations/NUMERO). Luo /etc/claudejono-pr/app.json: `{"app_id": N, "avain": "/etc/claudejono-pr/app.pem", "asennus_fork": A, "asennus_pr": B}` (600 prbotti).
5. Wrapperiin (`/usr/local/sbin/claudejono-pr`, root) rivi ennen python-kutsua: `[ -r /etc/claudejono-pr/app.json ] && export YOJONO_APP_ASETUKSET=/etc/claudejono-pr/app.json` (ja lisaa se claudejono/claudejono-pr -lahteeseen). Ota CT115:sta snapshot ennen.
6. Kun testi-PR on mennyt Appilla: revokoi PAT (kohta 4.6).
