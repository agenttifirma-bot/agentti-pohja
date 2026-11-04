# Salattu varmuuskopio Google Driveen (rclone crypt)

Skripti `varmuuskopio-drive.sh` lähettää Proxmoxin vzdump-varmuuskopiot öisin Google Driveen salattuina. Sisältö ja tiedostonimet salataan jo isännällä, joten Google näkee vain sekavaa dataa. Ennen tätä ainoa kopio oli isännän levyllä: levyvika olisi vienyt kaiken.

Asennus vie noin tunnin (ensimmäinen siirto kestää tunteja, mutta sen aikana ei tarvitse tehdä mitään). Jokainen askel on yksi komento ja sen odotettu tuloste. Aja komennot yksi kerrallaan ja jatka vasta, kun tuloste täsmää. Jos tuloste poikkeaa, lopeta ja kysy.

## Mihin salaisuudet kuuluvat

| Salaisuus | Missä on | Missä ei saa olla |
|---|---|---|
| Crypt-salasana ja suola (kaksi eri satunnaista salasanaa) | Tonyn salasanamanageri **ja** isännän `/root/.config/rclone/rclone.conf` (600, root) | repo, Git, tämä PR, chat, lokit |
| Driven OAuth-lupa | isännän `rclone.conf` | repo, lokit |
| Uptime Kuman push-osoite | isännän `/etc/varmuuskopio-drive.env` (600, root) | repo, lokit |

Jos crypt-salasana tai suola katoaa, Driven kopiot ovat pysyvästi käyttökelvottomia. Salasanamanageri on siksi ainoa paikka, josta ne saa takaisin, jos isäntä menee. Skripti kieltäytyy ajosta, jos `rclone.conf` tai asetustiedosto on ryhmän tai muiden luettavissa.

Mitään tässä ohjeessa ei tarvitse tehdä sudoersiin tai käyttäjiin. Kaikki ajetaan isännällä rootina, paitsi osa A (Tonyn oma kone).

## Osa A: Google-lupa Tonyn omalla koneella

**A1. Asenna rclone omalle koneellesi** (ohje: rclone.org/install) ja tarkista:

```
rclone version
```

Odotettu (versio saa olla uudempi): ensimmäinen rivi alkaa tekstillä `rclone v1.`

**A2. Hae Drive-lupa.** Pyydämme vain `drive.file`-oikeuden: rclone näkee Drivessä vain tiedostot, jotka se on itse luonut, ei Tonyn muita tiedostoja.

```
rclone authorize "drive" --drive-scope drive.file
```

Odotettu: selain avautuu. Kirjaudu omalla Google-tililläsi ja hyväksy. Terminaali tulostaa lopuksi:

```
Paste the following into your remote machine --->
{"access_token":"...","token_type":"Bearer",...}
<---End paste
```

Kopioi aaltosulkeiden välinen teksti leikepöydälle. Se on salaisuus: älä liitä sitä muualle kuin askeleeseen B4. Tyhjennä leikepöytä sen jälkeen.

## Osa B: isäntä (root)

**B1. Tarkista dump-hakemisto.**

```
grep -A4 '^dir: local' /etc/pve/storage.cfg
```

Odotettu: rivi `path /var/lib/vz` ja rivi `content` jossa sana `backup`. Jos polku on muu, lisää B13:n asetustiedostoon rivi `DUMP_DIR=<polku>/dump`.

**B2. Asenna rclone.**

```
apt install -y rclone
```

Odotettu: asennus päättyy ilman `E:`-rivejä. Tarkista:

```
rclone version
```

Odotettu: ensimmäinen rivi alkaa tekstillä `rclone v1.`

**B3. Tuo skripti isännälle.** Aja Tonyn omalla koneella repon kansiossa (osoite on se, jolla kirjaudut isännälle SSH:lla):

```
scp isanta/varmuuskopio-drive.sh root@ISANNAN_OSOITE:/root/
```

Tämä on ainoa komento, jossa on Tonyn oma arvo: kirjoita `ISANNAN_OSOITE`:n tilalle isännän osoite. Odotettu: rivi, jossa tiedostonimi ja `100%`.

Asenna skripti isännällä:

```
install -m 700 -o root -g root /root/varmuuskopio-drive.sh /usr/local/sbin/varmuuskopio-drive.sh
```

Odotettu: ei tulostetta.

**B4. Luo Drive-kohde.**

```
rclone config
```

Vastaa kehotteisiin näin (sanamuoto voi vaihdella hieman versiosta toiseen):

| Kehote | Vastaus |
|---|---|
| `n/s/q>` | `n` |
| `name>` | `drive` |
| `Storage>` | `drive` |
| `client_id>` ja `client_secret>` | pelkkä Enter |
| `scope>` | `3` (`drive.file`) |
| `service_account_file>` | pelkkä Enter |
| `Edit advanced config?` | `n` |
| `Use web browser to automatically authenticate...?` | `n` |
| `config_token>` | liitä A2:n aaltosulkeiden sisältö |
| `Configure this as a Shared Drive?` | `n` |
| `y/e/d>` | `y` |
| `e/n/d/r/c/s/q>` | älä lopeta vielä, siirry B5:een |

**B5. Luo salauskohde.** Luo ensin salasanamanagerissa kaksi uutta satunnaista salasanaa, joissa on vähintään 30 merkkiä: nimeksi `rclone crypt salasana` ja `rclone crypt suola`. Niiden pitää olla eri salasanoja. Tallenna ne manageriin ennen kuin jatkat. Samassa `rclone config` -ohjelmassa:

| Kehote | Vastaus |
|---|---|
| `e/n/d/r/c/s/q>` | `n` |
| `name>` | `drive-crypt` |
| `Storage>` | `crypt` |
| `remote>` | `drive:proxmox-salattu` |
| `filename_encryption>` | `1` (`standard`) |
| `directory_name_encryption>` | `1` (`true`) |
| `Password or pass phrase for encryption.` | `y` (Type in my own password), liitä manageristä `rclone crypt salasana`, vahvista samalla |
| `Password or pass phrase for salt.` | `y`, liitä manageristä `rclone crypt suola`, vahvista samalla |
| `Edit advanced config?` | `n` |
| `y/e/d>` | `y` |
| `e/n/d/r/c/s/q>` | `q` |

Salasanat eivät tulostu ruudulle eivätkä jää komentohistoriaan. Tallennus tapahtuu `rclone.conf`-tiedostoon rclonen peitetyssä (`obscure`) muodossa. Peitto ei ole salaus, joten tiedoston oikeudet ovat varsinainen suoja.

**B6. Tarkista tiedoston oikeudet.**

```
chmod 600 /root/.config/rclone/rclone.conf
```

Odotettu: ei tulostetta. Sitten:

```
stat -c '%a %U' /root/.config/rclone/rclone.conf
```

Odotettu: `600 root`

**B7. Kokeile yhteyttä.**

```
rclone mkdir drive-crypt:proxmox
```

Odotettu: ei tulostetta (Driveen syntyy kansio `proxmox-salattu`). Sitten:

```
rclone lsd drive-crypt:
```

Odotettu: yksi rivi, jonka lopussa on `proxmox`. Sitten:

```
rclone lsd drive:
```

Odotettu: yksi rivi, jonka lopussa on `proxmox-salattu`.

**B8. Kuiva-ajo ilman tunnuksia.** Tämä komento ei käytä rclonea eikä verkkoa. Se vain listaa, mitkä tiedostot kopioitaisiin:

```
varmuuskopio-drive.sh --luettelo
```

Odotettu: yksi rivi per tiedosto, muotoa `KOPIOIDAAN vzdump-lxc-110-2026_11_04-02_00_01.tar.zst (123456789 tavua)`. Kolmea uusinta kopiota vanhemmat per kontti näkyvät riveinä `OHITETAAN (yli 3 uusinta) ...`. Tarkista, että jokaisesta kontista ja virtuaalikoneesta on rivejä ja että luettelo on kohtuullinen.

**B9. Kuiva-ajo rclonella.** Tämä käyttää Drive-yhteyttä mutta ei siirrä mitään:

```
varmuuskopio-drive.sh --kuiva
```

Odotettu: rivit `alku tila=kuiva lahde=/var/lib/vz/dump kohde=drive-crypt:proxmox sailyta=3 vanhoja_ryhmia=...` ja `valmis tila=kuiva`. Tarkista loki:

```
grep -c 'dry-run' /var/log/varmuuskopio-drive.log
```

Odotettu: luku, joka on suurempi kuin 0 (rclone kertoo jokaisesta ohitetusta kopioinnista).

**B10. Ensimmäinen oikea ajo.** Se kestää tunteja. Ajetaan taustalla, jotta SSH-yhteyden katkeaminen ei keskeytä sitä:

```
systemd-run --unit=varmuuskopio-eka /usr/local/sbin/varmuuskopio-drive.sh
```

Odotettu: `Running as unit: varmuuskopio-eka.service.` Seuraa tilaa:

```
systemctl is-active varmuuskopio-eka
```

Odotettu: `active` ajon aikana, sen jälkeen `inactive`. Kun ajo on päättynyt:

```
grep -c 'valmis tila=sync' /var/log/varmuuskopio-drive.log
```

Odotettu: `1`. Jos tulos on `0`, katso loppu: `tail -n 20 /var/log/varmuuskopio-drive.log` (rivi `EPAONNISTUI` kertoo vaiheen).

**B11. Tarkista Drive.**

```
rclone ls drive-crypt:proxmox
```

Odotettu: tiedostot selväkielisinä nimineen ja kokoineen, samat kuin B8:n `KOPIOIDAAN`-rivit. Sitten:

```
rclone ls drive:proxmox-salattu
```

Odotettu: sama määrä tiedostoja, mutta nimet ovat sekavaa merkkijonoa eikä `vzdump`-sanaa näy.

**B12. Ensimmäinen palautustesti.** Skripti hakee pienimmän uusimmista dumpeista Drivesta väliaikaiseen hakemistoon, purkaa salauksen ja vertaa `sha256`-tiivistettä alkuperäiseen. Väliaikaishakemisto on `/tmp`, joten sen tilan pitää riittää pienimmän dumpin kokoon (`df -h /tmp`).

```
varmuuskopio-drive.sh --palautustesti
```

Odotettu:

```
palautustesti: vzdump-lxc-...tar.zst (... tavua)
palautustesti OK: sha256 tasmaa (64 merkin tiiviste)
```

Jos viimeinen rivi on `palautustesti EPAONNISTUI`, älä luota kopioon: kysy ennen kuin teet mitään muuta.

**B13. Uptime Kuma -hälytys.** Luo Uptime Kumassa **Push**-monitori: nimi `varmuuskopio-drive`, Heartbeat Interval `93600` sekuntia (26 tuntia), Retries `0`. Kopioi push-osoite ilman `?status=...`-osaa. Luo asetustiedosto tyhjänä oikeuksilla 600:

```
install -m 600 -o root -g root /dev/null /etc/varmuuskopio-drive.env
```

Odotettu: ei tulostetta. Avaa se ja kirjoita sinne rivi `KUMA_PUSH_URL=` ja heti sen perään push-osoite (muut rivit ovat valinnaisia, katso skriptin alun kommentit):

```
nano /etc/varmuuskopio-drive.env
```

Tarkista oikeudet:

```
stat -c '%a %U' /etc/varmuuskopio-drive.env
```

Odotettu: `600 root`

**B14. Ajasta.** Tarkista ensin, että vzdump-työ päättyy ennen kello 3.30 (kellonajat ovat isännän aikavyöhykkeen mukaan):

```
cat /etc/pve/jobs.cfg
```

Odotettu: `vzdump`-työ, jonka `starttime` on selvästi ennen 03:30 (esimerkiksi `02:00`). Jos vzdump alkaa myöhemmin, älä jatka vaan kysy. Luo cron-tiedosto:

```
printf '30 3 * * * root /usr/local/sbin/varmuuskopio-drive.sh\n0 5 1 * * root /usr/local/sbin/varmuuskopio-drive.sh --palautustesti\n' > /etc/cron.d/varmuuskopio-drive
```

Odotettu: ei tulostetta. Tarkista:

```
cat /etc/cron.d/varmuuskopio-drive
```

Odotettu: kaksi riviä: päivittäinen synkronointi 3.30 ja kuukauden ensimmäisen päivän palautustesti 5.00.

**B15. Seuraavana päivänä** tarkista, että yöajo onnistui ja Kuma on vihreä:

```
tail -n 3 /var/log/varmuuskopio-drive.log
```

Odotettu: viimeinen rivi on `... valmis tila=sync`. Uptime Kumassa monitori näyttää `Up`. Kuukauden ensimmäisen päivän jälkeen:

```
grep 'palautustesti' /var/log/varmuuskopio-drive.log | tail -n 2
```

Odotettu: rivi `palautustesti OK: sha256 tasmaa (...)`.

## Mitä skripti tekee

- Synkronoi `DUMP_DIR`-hakemiston kohteeseen `drive-crypt:proxmox` (`rclone sync`, nopeusrajoitus `BWLIMIT`, oletus 8 Mt/s).
- Säilyttää enintään `SAILYTA` (oletus 3) uusinta kopiota per kontti tai virtuaalikone. Vanhemmat jäävät lähettämättä ja poistuvat Drivesta.
- Kieltäytyy synkronoinnista, jos lähdehakemistossa ei ole vzdump-tiedostoja. Muuten tyhjä lähde tyhjentäisi Drive-kopion.
- `--max-delete` (oletus 20) estää massapoiston. Lukko estää päällekkäiset ajot. Loki on tiedostossa `/var/log/varmuuskopio-drive.log`.
- Kieltäytyy ajosta, jos `rclone.conf` tai asetustiedosto on ryhmän tai muiden luettavissa.
- Ilmoittaa Kumalle vain onnistuneesta synkronoinnista. Jos ilmoitusta ei tule 26 tunnin sisällä, Kuma hälyttää. Epäonnistuminen lähettää heti tilan `down`.

## Täydellinen palautus uudelle koneelle

Asenna rclone ja luo `drive`- ja `drive-crypt`-kohteet osan B askelten B4–B5 mukaan. Käytä **samoja** crypt-salasanaa ja suolaa salasanamanagerista. Aja Google-lupa uudelleen (A2). Sitten:

```
rclone copy drive-crypt:proxmox /palautus
```

Huomio: `drive.file`-lupa näkee vain tiedostot, jotka luotiin samalla rclonen OAuth-asiakkaalla. Tässä ohjeessa käytetään rclonen oletusasiakasta, joten uusi kone näkee ne. Jos joskus vaihdat asiakastunnuksen (`client_id`), vanhat tiedostot eivät näy `drive.file`-luvalla. Silloin käytä väliaikaisesti laajempaa lupaa (`scope` = `1`) vain palautukseen.
