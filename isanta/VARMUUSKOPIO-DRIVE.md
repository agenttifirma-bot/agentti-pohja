# Salattu varmuuskopio Google Driveen (rclone crypt)

Skripti `varmuuskopio-drive.sh` lähettää Proxmoxin vzdump-varmuuskopiot öisin Google Driveen salattuina. Tiedostojen sisältö ja nimet salataan jo isännällä, joten Google näkee vain sekavaa dataa. Asennus vie noin 15 minuuttia ja on kymmenen askelta.

**Tärkeää:** salausavain ja suola (`password` ja `password2`) ovat ainoa tapa purkaa kopiot. Jos ne katoavat, kopiot ovat pysyvästi käyttökelvottomia. Älä tallenna niitä repoon.

## Asennus

1. **Tarkista vzdumpin polku isännällä.** Skripti olettaa polun `/var/lib/vz/dump`.
   `grep -A4 '^dir: local' /etc/pve/storage.cfg` näyttää `path`-rivin, jos polku on muu. Silloin lisää asetustiedostoon `DUMP_DIR` (askel 8).
2. **Asenna rclone isännälle.** `apt install rclone` tai ohjeen mukaan osoitteesta rclone.org. Tarkista `rclone version`.
3. **Hae Google-lupa omalla koneellasi.** Asenna rclone myös omalle koneellesi ja aja `rclone authorize "drive"`. Selain avautuu. Kirjaudu ja hyväksy. Terminaali tulostaa `{"access_token": ...}`-tekstin. Kopioi koko aaltosulkeiden sisältö ja käsittele sitä kuin salasanaa.
4. **Luo Drive-kohde isännällä.** Aja `rclone config`: `n` (uusi), nimeksi `drive`, tyypiksi `drive`, scope `1` (täysi pääsy; kohde rajautuu silti kansioon `proxmox-salattu`), loput oletuksina. Kohdassa "Use web browser to automatically authenticate" vastaa `n` ja liitä askeleen 3 teksti, kun sitä kysytään.
5. **Luo salauskohde.** Samassa `rclone config` -ohjelmassa: `n`, nimeksi `drive-crypt`, tyypiksi `crypt`, `remote` = `drive:proxmox-salattu`, `filename_encryption` = `standard`. Valitse **Generate random password** sekä salasanalle että suolalle (vähintään 128 bittiä).
6. **Tallenna avain ja suola heti.** Aja `rclone config show drive-crypt`. Kopioi `password`- ja `password2`-rivit salasanamanageriisi **ja** tulosta ne paperille. Säilytä paperi erillään koneesta. Tyhjennä terminaalin historia: `history -c`.
7. **Lisää skripti isännälle.** Kopioi tiedosto repon hakemistosta `isanta/` ja suojaa se:
   `install -m 700 varmuuskopio-drive.sh /usr/local/sbin/`
8. **Luo asetustiedosto.** Tiedosto `/etc/varmuuskopio-drive.env` (oikeudet 600, omistaja root) voi sisältää esimerkiksi rivit `SAILYTA=3`, `BWLIMIT=8M` ja `KUMA_PUSH_URL=<Kuman push-osoite, katso askel 10>`. Pelkästään tarvittavat rivit riittävät. Skripti kieltäytyy tiedostosta, jos ryhmä tai muut voivat kirjoittaa siihen.
9. **Kokeile kuivana, sitten oikeasti.**
   `varmuuskopio-drive.sh --kuiva` ei muuta mitään. Lue loki `/var/log/varmuuskopio-drive.log`. Jos rivit näyttävät oikeilta, aja `varmuuskopio-drive.sh` ja odota. Ensimmäinen siirto on suuri ja kestää tunteja. Tarkista sitten `rclone ls drive-crypt:proxmox` ja `rclone ls drive:proxmox-salattu` (jälkimmäisessä tiedostonimet ovat sekavia).
10. **Ajasta ja hälytä.**
    - Luo Uptime Kumassa **Push**-monitori. Heartbeat Interval on 93600 sekuntia (26 tuntia), Retries on 0. Kopioi push-osoite (ilman `?status=...`-osaa) askeleen 8 tiedostoon.
    - Lisää `/etc/cron.d/varmuuskopio-drive`:
      ```
      30 3 * * * root /usr/local/sbin/varmuuskopio-drive.sh
      0 5 1 * * root /usr/local/sbin/varmuuskopio-drive.sh --palautustesti
      ```
      Kellonajat ovat isännän aikavyöhykkeen mukaan. Tarkista `timedatectl`, ja että vzdump-työ päättyy ennen 3.30.

Skripti ilmoittaa Kumalle vain onnistuneesta synkronoinnista. Jos ilmoitusta ei tule 26 tunnin sisällä, Kuma hälyttää. Epäonnistuminen lähettää heti tilan `down`.

## Mitä skripti tekee

- Synkronoi `DUMP_DIR`-hakemiston kohteeseen `drive-crypt:proxmox` (`rclone sync`, nopeusrajoitus `BWLIMIT`).
- Säilyttää enintään `SAILYTA` uusinta kopiota per kontti tai virtuaalikone. Vanhemmat jäävät lähettämättä ja poistuvat Drivesta.
- Kieltäytyy synkronoinnista, jos lähdehakemistossa ei ole vzdump-tiedostoja. Muuten tyhjä lähde tyhjentäisi Drive-kopion.
- `--max-delete` (oletus 20) estää massapoiston. Lukko estää päällekkäiset ajat. Loki on tiedostossa `/var/log/varmuuskopio-drive.log`.

## Palautustesti

Kuukausittainen cron-ajo (`--palautustesti`) hakee pienimmän uusimmista dumpeista, purkaa salauksen väliaikaiseen hakemistoon ja vertaa `sha256`-tiivistettä alkuperäiseen. Tulos on lokissa (`palautustesti OK` tai `EPAONNISTUI`). Aja se käsin kerran asennuksen jälkeen.

Täydellinen palautus uudelle koneelle: asenna rclone, luo `drive`- ja `drive-crypt`-kohteet askelten 3–5 mukaan **samalla salasanalla ja suolalla** (askel 6), ja aja `rclone copy drive-crypt:proxmox /palautus`.
