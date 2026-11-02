# Kauppatiimin hiekkalaatikko (CT121)

Paperikauppakopio vapaaseen kokeiluun (doc 68 osa 1). Isannan komennot ajaa Tony (root, `ssh root@100.87.110.22`); mitaan avainta tai salaisuutta ei kirjoiteta tahan eika liiteta keskusteluun. **Tuotantoon (CT119) ei kosketa**: ainoa lukukosketus on markkinadatan kopiointi (vaihe 8).

## Mita rakennetaan

| Asia | Arvo |
|---|---|
| Kontti | CT121 `kauppa-sandbox` (CT120 on jo `searxng`) |
| Pohja | CT119:n snapshot `pre-kauppatiimi-c9d0331c-1631`, **taysi** kopio (`--full 1`) tallennustilaan `konttilevy` |
| Verkko | vain `vmbr1` (eristetty silta, ei fyysisia portteja), `10.99.0.3/24`, **ei gatewayta**; ulos vain proxyn `sandbox-proxy` (CT211, `10.99.0.2:3128`) kautta |
| Sallitut osoitteet | proxyn `allowed`-lista: nykyiset (`.github.com`, `.githubusercontent.com`, `.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `.debian.org`, `.nodejs.org`) + `.openrouter.ai`. Binancea ja Telegramia **ei** sallita |
| Koodi | `github.com/agenttifirma-bot/kauppa-sandbox` (julkinen, ei fork: ei PR-reittia tuotantoon) |
| Data | markkinadata (julkista hintadataa) kopioidaan kasin CT119:sta; salkut ja lokit alkavat tyhjasta |
| Salaisuudet | ei CT119:n `.env`/`llm.env`:ia; oma OpenRouter-avain (<= 2 USD/vko), jonka Tony asettaa itse vaiheessa 11 |
| Ajastimet | pois paalta (ajot kasin) |

Miksi verkko on rajattu proxylla eika palomuurilla: isannan palomuuri on pois paalta ja kaikki kontit ovat samassa `vmbr0`-verkossa; sen kayttoonotto vaikuttaisi kaikkiin kontteihin. CT121:lla on vain `vmbr1`-kortti ilman reittia, joten se ei paase mihinkaan muualle kuin proxyyn (ja proxy paastaa vain listatut verkkotunnukset).

## Esitarkistukset (vain luku)

```
pct config 121 2>&1 | head -2              # pitaa sanoa: Configuration file ... does not exist
pct listsnapshot 119 | grep pre-kauppatiimi-c9d0331c-1631
grep -l vmbr1 /etc/pve/lxc/*.conf          # nyt vain 211.conf
```

## 1. Kloonaus (taysi kopio snapshotista, ei kaynnista)

```
pct clone 119 121 --snapname pre-kauppatiimi-c9d0331c-1631 --full 1 --storage konttilevy --hostname kauppa-sandbox --description "kauppatiimin hiekkalaatikko (doc 68), EI tuotanto"
pct set 121 --onboot 0
```

## 2. Verkko vain vmbr1:lle (ENNEN ensimmaista kaynnistysta)

```
pct set 121 --net0 name=eth0,bridge=vmbr1,ip=10.99.0.3/24,firewall=0
grep -E "^(net|mp[0-9]|lxc\.|dev[0-9]|hostname)" /etc/pve/lxc/121.conf
```

Tarkistus: tulosteessa on **vain** yksi `net0`-rivi, jossa `bridge=vmbr1` eika `gw=`; ei yhtaan `mp`-, `lxc.`- tai `dev`-rivia (ne voisivat avata isannan hakemistoja tai laitteita kontille). Muuten **pysahdy** ja liita tuloste Claudelle.

## 3. Salaisuuksien ja tilan siivous (ENNEN ensimmaista kaynnistysta)

Kloonin levylla on CT119:n salaisuudet (`.env`, `llm.env`) ja tuotantosalkut. Ne poistetaan, kun kontti on viela sammuksissa, jottei mikaan ehdi kayttaa niita:

```
pct mount 121
R=/var/lib/lxc/121/rootfs
rm -f $R/srv/kauppa/.env $R/srv/kauppa/llm.env
rm -f $R/srv/kauppa/data/salkku_*.db $R/srv/kauppa/data/tapahtumat.jsonl $R/srv/kauppa/data/PYSAYTYS
rm -f $R/srv/kauppa/logs/* 2>/dev/null
rm -f $R/etc/systemd/system/timers.target.wants/kauppa-*.timer
ls $R/srv/kauppa $R/srv/kauppa/data
grep -rIlE "(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_|[0-9]{8,}:[A-Za-z0-9_-]{30,})" $R/srv $R/etc $R/root 2>/dev/null
```

Viimeisen komennon pitaa tulostaa **ei mitaan** (se listaa vain tiedostonimet, ei sisaltoa). Jos nimia tulee, **pysahdy**, ala kaynnista konttia ja liita nimet Claudelle. Jos kaikki on kunnossa:

```
pct unmount 121
```

(Vanha koodi `/srv/kauppa/k1` jaa toistaiseksi paikoilleen; se korvataan vaiheessa 7.)

## 4. Proxyn allowlist (CT211): lisaa OpenRouter

Muutos koskee kaikkia `10.99.0.0/24`-asiakkaita; nyt niita ei ole muita kuin CT121.

```
pct exec 211 -- cp -p /etc/squid/squid.conf /etc/squid/squid.conf.ennen-openrouter
pct exec 211 -- sed -i 's/^\(acl allowed dstdomain .*\)$/\1 .openrouter.ai/' /etc/squid/squid.conf
pct exec 211 -- grep "^acl allowed" /etc/squid/squid.conf
pct exec 211 -- squid -k parse 2>&1 | tail -3
pct exec 211 -- systemctl reload squid
```

`grep` nayttaa listan lopussa `.openrouter.ai`; `squid -k parse` ei saa antaa virheita. Peruutus: `pct exec 211 -- cp -p /etc/squid/squid.conf.ennen-openrouter /etc/squid/squid.conf` ja `systemctl reload squid`.

## 5. Kaynnistys ja proxy kontille

```
pct start 121
pct exec 121 -- sh -c 'mkdir -p /etc/systemd/system.conf.d && printf "[Manager]\nDefaultEnvironment=\"HTTPS_PROXY=http://10.99.0.2:3128\" \"HTTP_PROXY=http://10.99.0.2:3128\" \"NO_PROXY=127.0.0.1,localhost\"\n" > /etc/systemd/system.conf.d/proxy.conf && systemctl daemon-reexec'
pct exec 121 -- systemctl list-timers --all | grep -c kauppa
```

Viimeisen rivin pitaa tulostaa `0` (yksikaan kauppa-ajastin ei ole aktiivinen).

## 6. Verkkokoe (ei avainta tarvita)

```
pct exec 121 -- python3 - <<'EOF'
import urllib.request as u
def kokeile(nimi, url, proxy=True):
    h = u.ProxyHandler({"https": "http://10.99.0.2:3128"} if proxy else {})
    try:
        r = u.build_opener(h).open(url, timeout=8)
        print(nimi, "->", r.status)
    except Exception as e:
        print(nimi, "->", type(e).__name__, str(e)[:60])
kokeile("github proxylla (pitaa olla 200)", "https://github.com")
kokeile("openrouter proxylla (200 tai 4xx, ei 403 proxylta)", "https://openrouter.ai/api/v1/models")
kokeile("example.com proxylla (pitaa kaatua: 403)", "https://example.com")
kokeile("binance proxylla (pitaa kaatua: 403)", "https://data.binance.vision", True)
kokeile("github ILMAN proxya (pitaa kaatua: ei reittia)", "https://github.com", False)
EOF
```

Hyvaksyntaehto: ensimmainen onnistuu; `example.com`, `binance` ja suora yhteys epaonnistuvat. Jos `example.com` tai suora yhteys onnistuu, verkon rajaus ei toimi: **pysahdy ja ala laita avainta konttiin**.

## 7. Koodi kauppa-sandbox-repoista

```
pct exec 121 -- git --version
pct exec 121 -- sh -c 'mv /srv/kauppa/k1 /srv/kauppa/k1.alkup && runuser -u kauppa -- env HTTPS_PROXY=http://10.99.0.2:3128 git clone https://github.com/agenttifirma-bot/kauppa-sandbox.git /srv/kauppa/k1'
pct exec 121 -- runuser -u kauppa -- git -C /srv/kauppa/k1 log --oneline -1
```

Jos `git --version` ei toimi, kerro Claudelle: koodi viedaan silloin paketilla (`git archive` + `pct push`). Kloonaus ei vaadi tunnusta (julkinen repo). Muutosten vienti takaisin repoon vaatisi botin tunnuksen: se on erillinen paatos, ei tehda nyt.

## 8. Markkinadatan kopiointi CT119:sta (vain luku)

Hinnat ovat julkista dataa; kopio otetaan sqlite-varmuuskopiona, jotta kesken kirjoituksen oleva tiedosto ei hajoa. CT119:aan ei kirjoiteta muuta kuin tama valiaikainen kopio.

```
pct exec 119 -- python3 -c "import sqlite3; s=sqlite3.connect('file:/srv/kauppa/data/markkina.db?mode=ro', uri=True); d=sqlite3.connect('/tmp/markkina-sandbox.db'); s.backup(d); d.close()"
pct pull 119 /tmp/markkina-sandbox.db /root/markkina-sandbox.db
pct exec 119 -- rm /tmp/markkina-sandbox.db
pct push 121 /root/markkina-sandbox.db /srv/kauppa/data/markkina.db
pct exec 121 -- chown kauppa:kauppa /srv/kauppa/data/markkina.db
pct exec 121 -- ls -l /srv/kauppa/data
```

(`rm` poistaa vain edella luodun valiaikaisen kopion.) Sandboxin data vanhenee, koska se ei voi ladata Binancesta; paivita kopio tarvittaessa uudelleen samalla tavalla ennen viikkoajoa.

## 9. Perus-snapshot ja palautusharjoitus

Palautus on ehto kayttoonotolle (doc 68): harjoitellaan ENNEN avainta.

```
pct snapshot 121 perus-puhdas
pct exec 121 -- sh -c 'echo sotku > /srv/kauppa/k1/SOTKU; rm /srv/kauppa/data/markkina.db'
pct stop 121
pct rollback 121 perus-puhdas
pct start 121
pct exec 121 -- sh -c 'ls /srv/kauppa/k1/SOTKU 2>&1; ls -l /srv/kauppa/data/markkina.db'
```

Hyvaksyntaehto: `SOTKU` ei loydy (`No such file`) ja `markkina.db` on takaisin. `pct rollback` poistaa kaiken snapshotin jalkeisen, ja niin sen pitaakin sandboxissa.

## 10. Snapshot ennen jokaista viikkoajoa

```
pct snapshot 121 pre-viikko-$(date +%Y%m%d)
```

Pida snapshotteja korkeintaan 10 per kontti; vanhojen poisto (`pct delsnapshot`) on Tonyn paatos.

## 11. OpenRouter-avain (vasta kun vaiheet 1-9 ovat OK)

Tama vaihe tehdaan vasta, kun Claude on sanonut. Avain luodaan OpenRouterissa (viikkoraja 2 USD), ja Tony kirjoittaa sen konttiin itse (`pct enter 121`, tiedosto `/srv/kauppa/llm.env`, oikeudet `kauppa:kauppa 600`). Avainta ei liiteta keskusteluun, repoon eika tahan tiedostoon.

## Peruutus (jos jokin menee pieleen)

CT121 on erillinen: `pct stop 121; pct destroy 121` poistaa vain hiekkalaatikon (Tonin paatos; ei kuulu automaatioon). Proxyn muutos perutaan vaiheen 4 peruutuskomennolla. CT119 ja CT211:n muu konfiguraatio eivat muutu.

## Ehdot (doc 68 osa 1) ja missa ne tayttyvat

- erillinen kontti, ei tuotannon salaisuuksia, ei paasya CT119:aan: vaiheet 1-3 ja 6 (ei reittia, mp/lxc-rivit tarkistettu)
- verkon rajaus vain OpenRouter + GitHub: vaiheet 4-6
- palautusharjoitus: vaihe 9
- snapshotti ennen jokaista viikkoajoa: vaihe 10
- omat budjettikatot (<= 2 USD/vko): vaihe 11
