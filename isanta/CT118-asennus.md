# CT118:n snapshot-oikeus isannalla (Tonyn asennus)

Tama on ohje Tonylle. Mitaan tasta ei aja automaatio: isannan skripti, authorized_keys ja avaimet ovat Tonyn toimia.
Kaikki komennot ajetaan Proxmox-isannalla (root), ellei toisin sanota. Aja yksi komento kerrallaan ja tarkista tulos ennen seuraavaa.
Testeja ei ajeta CT118:ssa.

Mita tama antaa: CT118 saa ottaa snapshotin VAIN itsestaan (nimi `ennen-<a-z0-9->`) ja listata omat snapshotinsa. Ei poistoa, ei rollbackia,
ei muita kontteja, ei `tila`-komentoa. Rajat: enintaan 10 snapshotia yhteensa (kasin otetut mukaan lukien), 3 ottoa/vrk, ei oteta jos kontin
thin pool (data tai metadata) on yli 80 % taynna. Loki: `/var/log/snapshot-kutsu.log` (CT118:n rivit `ct=118`).

## 0. Ennen asennusta
```
pct listsnapshot 118
```
Snapshotteja saa olla alle 10 (raja 10 yhteensa). Tarkista myos levytila:
```
lvs --noheadings -o lv_name,data_percent,metadata_percent konttilevy/konttilevy
```

## 1. Paivita isannan skripti (CT115:n nykyinen kayttaytyminen ei muutu)
Paivita ensin CT115:n `/opt/yojono-ajuri` tavallasi (kuten aiemmat isanta-muutokset). Sitten isannalla:
```
cp -p /root/snapshot-kutsu.py /root/snapshot-kutsu.py.edellinen
```
```
pct pull 115 /opt/yojono-ajuri/isanta/snapshot_isanta.py /root/snapshot-kutsu.py.uusi
```
```
sha256sum /root/snapshot-kutsu.py.uusi
```
Vertaa tiivistetta mergattuun tiedostoon (`sha256sum isanta/snapshot_isanta.py` repossa; rivinvaihdot LF). Sitten:
```
chmod 700 /root/snapshot-kutsu.py.uusi && mv /root/snapshot-kutsu.py.uusi /root/snapshot-kutsu.py
```
Tarkista, etta CT115 toimii ennallaan (aja CT115:ssa):
```
python3 -m agentti.snapshot_kutsu listaa
```
Olemassa olevaa CT115:n authorized_keys-rivia EI muuteta: rivi ilman argumenttia tarkoittaa edelleen CT115:ta.

## 2. Snapshot ennen avaimen asennusta
```
pct snapshot 118 ennen-snapshot-avain
```

## 3. Avain CT118:lle (vain Tony luo avaimen)
```
pct exec 118 -- ssh-keygen -q -t ed25519 -N "" -C infra-snapshot -f /etc/infra-automaatio/snapshot_key
```
```
pct exec 118 -- chown root:infra /etc/infra-automaatio/snapshot_key /etc/infra-automaatio/snapshot_key.pub
```
```
pct exec 118 -- chmod 640 /etc/infra-automaatio/snapshot_key
```
```
pct exec 118 -- chmod 644 /etc/infra-automaatio/snapshot_key.pub
```

## 4. Rivi isannan authorized_keys-tiedostoon
Varmuuskopio:
```
cp -p /root/.ssh/authorized_keys /root/.ssh/authorized_keys.ennen-118
```
CT118:n IP ja julkinen avain talteen:
```
IP=$(pct exec 118 -- hostname -I | awk '{print $1}'); echo "$IP"
```
```
AVAIN=$(pct exec 118 -- awk '{print $1" "$2}' /etc/infra-automaatio/snapshot_key.pub); echo "$AVAIN" | cut -c1-40
```
Lisaa rivi (kohde 118 tulee command=-argumentista, ei asiakkaalta):
```
echo "from=\"$IP\",restrict,command=\"/root/snapshot-kutsu.py 118\" $AVAIN infra-snapshot" >> /root/.ssh/authorized_keys
```
Tarkista, etta rivi on tasan yksi:
```
grep -c 'snapshot-kutsu.py 118' /root/.ssh/authorized_keys
```

## 5. Isannan host-avain CT118:lle (ei luottamusta ensikayttoon)
```
awk '{print "192.168.1.114 "$1" "$2}' /etc/ssh/ssh_host_ed25519_key.pub > /tmp/known_hosts.118
```
```
pct push 118 /tmp/known_hosts.118 /etc/infra-automaatio/known_hosts --perms 640
```
```
pct exec 118 -- chown root:infra /etc/infra-automaatio/known_hosts
```
```
rm /tmp/known_hosts.118
```

## 6. Testi (kayttajana infra, ei root)
Sallittu: omat snapshotit.
```
pct exec 118 -- runuser -u infra -- ssh -F /dev/null -i /etc/infra-automaatio/snapshot_key -o BatchMode=yes -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/infra-automaatio/known_hosts -o StrictHostKeyChecking=yes root@192.168.1.114 listaa
```
Pitaa nayttaa `{"ok": true, "snapshotit": [...]}` (CT118:n snapshotit). Kielletty: `tila` (odotettu `"ok": false`).
```
pct exec 118 -- runuser -u infra -- ssh -F /dev/null -i /etc/infra-automaatio/snapshot_key -o BatchMode=yes -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/infra-automaatio/known_hosts -o StrictHostKeyChecking=yes root@192.168.1.114 tila
```
Loki:
```
tail -3 /var/log/snapshot-kutsu.log
```
Rivien pitaa olla muotoa `<pvm> muu ok ct=118 listaa` ja `<pvm> muu virhe ct=118 tila`.

## Peruutus
Poista CT118:n rivi ja palauta edellinen skripti:
```
cp -p /root/.ssh/authorized_keys.ennen-118 /root/.ssh/authorized_keys
```
```
cp -p /root/snapshot-kutsu.py.edellinen /root/snapshot-kutsu.py
```
Avaimen voi poistaa CT118:sta: `pct exec 118 -- rm /etc/infra-automaatio/snapshot_key /etc/infra-automaatio/snapshot_key.pub /etc/infra-automaatio/known_hosts`.
