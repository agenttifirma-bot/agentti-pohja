#!/usr/bin/env bash
# =============================================================================
# varmuuskopio-drive.sh - vzdump-varmuuskopiot salattuna Google Driveen (rclone crypt).
#
# Kaytto (Proxmox-isannalla, root; cron klo 3.30 vzdumpin jalkeen):
#     varmuuskopio-drive.sh              ajaa synkronoinnin
#     varmuuskopio-drive.sh --kuiva      rclone --dry-run: ei muuta mitaan, ei pingia
#     varmuuskopio-drive.sh --palautustesti
#                                        hakee pienimman uusimman dumpin Drivesta,
#                                        purkaa salauksen ja vertaa sha256-tiivistetta
#
# Asetukset ymparistomuuttujista tai tiedostosta ASETUS_TIEDOSTO (oletus
# /etc/varmuuskopio-drive.env, oltava ei-ryhma/muu-kirjoitettava). Salaisuudet (rclone.conf,
# Uptime Kuman push-osoite) eivat kuulu repoon. Skripti ei tulosta niita.
#   DUMP_DIR      /var/lib/vz/dump        paikallinen vzdump-hakemisto
#   REMOTE        drive-crypt:proxmox     rclone crypt -kohde
#   BWLIMIT       8M                      rclone --bwlimit
#   SAILYTA       3                       uusinta kopiota per kontti/VM (>=1)
#   MAX_POISTO    20                      rclone --max-delete (suoja massapoistoa vastaan)
#   LOKI          /var/log/varmuuskopio-drive.log
#   LUKKO         /run/varmuuskopio-drive.lock
#   KUMA_PUSH_URL (valinnainen)           Uptime Kuma push-osoite ilman kyselyosaa
#   RCLONE        rclone                  rclone-ohjelma
# =============================================================================
set -u -o pipefail

TILA=sync
case "${1:-}" in
  "") ;;
  --kuiva) TILA=kuiva ;;
  --palautustesti) TILA=palautus ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac

ASETUS_TIEDOSTO="${ASETUS_TIEDOSTO:-/etc/varmuuskopio-drive.env}"
if [ -f "$ASETUS_TIEDOSTO" ]; then
  # shellcheck disable=SC1090
  if [ -n "$(find "$ASETUS_TIEDOSTO" -perm /022 2>/dev/null)" ]; then
    echo "EPAONNISTUI: $ASETUS_TIEDOSTO on ryhman tai muiden kirjoitettavissa" >&2; exit 1
  fi
  . "$ASETUS_TIEDOSTO"
fi

DUMP_DIR="${DUMP_DIR:-/var/lib/vz/dump}"
REMOTE="${REMOTE:-drive-crypt:proxmox}"
BWLIMIT="${BWLIMIT:-8M}"
SAILYTA="${SAILYTA:-3}"
MAX_POISTO="${MAX_POISTO:-20}"
LOKI="${LOKI:-/var/log/varmuuskopio-drive.log}"
LUKKO="${LUKKO:-/run/varmuuskopio-drive.lock}"
KUMA_PUSH_URL="${KUMA_PUSH_URL:-}"
RCLONE="${RCLONE:-rclone}"

loki() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOKI" 2>/dev/null || true; printf '%s\n' "$*"; }

TMP=""
ONNISTUI=0
ping_kuma() {  # $1 = up|down, $2 = viesti; vain tila, ei salaisuuksia lokiin
  [ -n "$KUMA_PUSH_URL" ] || return 0
  [ "$TILA" = sync ] || return 0
  curl -fsS -m 20 -G --data-urlencode "status=$1" --data-urlencode "msg=$2" "$KUMA_PUSH_URL" >/dev/null 2>&1 \
    || loki "VAROITUS: Uptime Kuma -pingi epaonnistui"
}
siivous() {
  local koodi=$?
  [ -n "$TMP" ] && rm -rf "$TMP"
  if [ "$ONNISTUI" != 1 ]; then
    loki "EPAONNISTUI (tila=$TILA, koodi=$koodi)"
    ping_kuma down "epaonnistui"
    [ "$koodi" -eq 0 ] && koodi=1
  fi
  exit "$koodi"
}
trap siivous EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$SAILYTA" =~ ^[0-9]+$ ]] && [ "$SAILYTA" -ge 1 ] || { loki "SAILYTA ei kelpaa: $SAILYTA"; exit 1; }
[[ "$MAX_POISTO" =~ ^[0-9]+$ ]] || { loki "MAX_POISTO ei kelpaa"; exit 1; }
command -v "$RCLONE" >/dev/null 2>&1 || { loki "rclonea ei loydy"; exit 1; }
command -v flock >/dev/null 2>&1 || { loki "flock puuttuu"; exit 1; }
[ -d "$DUMP_DIR" ] || { loki "dump-hakemistoa ei ole: $DUMP_DIR"; exit 1; }

exec 9>"$LUKKO" || { loki "lukkotiedostoa ei voi avata"; exit 1; }
if ! flock -n 9; then loki "toinen ajo kaynnissa, ohitetaan"; ONNISTUI=1; exit 0; fi

TMP=$(mktemp -d) || exit 1

# Dump-tiedostot: vzdump-<lxc|qemu>-<id>-<aika>.<paate>. Ryhmitys tunnuksen mukaan.
mapfile -t TIEDOSTOT < <(find "$DUMP_DIR" -maxdepth 1 -type f -name 'vzdump-*' -printf '%f\n' | sort)
PERUSNIMET=$(printf '%s\n' "${TIEDOSTOT[@]:-}" \
  | sed -nE 's/^(vzdump-(lxc|qemu)-([0-9]+)-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2})\..*$/\3 \1/p' \
  | sort -u)
# Tyhja lahde + sync = koko Drive-kopio tyhjenisi. Kieltaydytaan.
[ -n "$PERUSNIMET" ] || { loki "dump-hakemistossa ei ole vzdump-tiedostoja, ei synkronoida tyhjaa"; exit 1; }

# Vanhat: per tunnus kaikki paitsi SAILYTA uusinta (aikaleima jarjestaa nimet).
echo "$PERUSNIMET" | sort -k1,1 -k2,2r \
  | awk -v n="$SAILYTA" '{ if ($1 != e) { e=$1; k=0 } k++; if (k>n) print "/" $2 ".*" }' > "$TMP/vanhat.txt"
VANHOJA=$(wc -l < "$TMP/vanhat.txt")

BASE=("$RCLONE" --bwlimit "$BWLIMIT" --log-file "$LOKI" --log-level NOTICE --stats 0 --retries 3 --low-level-retries 5)

if [ "$TILA" = palautus ]; then
  # Uusimmista dumpeista pienin (nopea testi). Haetaan, puretaan crypt ja verrataan sha256.
  UUSIMMAT=$(echo "$PERUSNIMET" | sort -k1,1 -k2,2r | awk '$1!=e{e=$1; print $2}')
  VALINTA=""; KOKO=""
  while read -r pn; do
    for f in "$DUMP_DIR/$pn".*; do
      [ -f "$f" ] || continue
      case "$f" in *.log|*.notes) continue ;; esac
      k=$(stat -c %s "$f"); if [ -z "$KOKO" ] || [ "$k" -lt "$KOKO" ]; then KOKO=$k; VALINTA=$f; fi
    done
  done <<< "$UUSIMMAT"
  [ -n "$VALINTA" ] || { loki "palautustestiin ei loytynyt dump-tiedostoa"; exit 1; }
  NIMI=$(basename "$VALINTA")
  loki "palautustesti: $NIMI ($KOKO tavua)"
  mkdir "$TMP/palautus"
  "${BASE[@]}" copyto "$REMOTE/$NIMI" "$TMP/palautus/$NIMI" || { loki "palautustesti: haku Drivesta epaonnistui"; exit 1; }
  A=$(sha256sum < "$VALINTA" | cut -d' ' -f1); B=$(sha256sum < "$TMP/palautus/$NIMI" | cut -d' ' -f1)
  if [ "$A" = "$B" ]; then loki "palautustesti OK: sha256 tasmaa ($A)"; ONNISTUI=1; exit 0; fi
  loki "palautustesti EPAONNISTUI: sha256 ei tasmaa"; exit 1
fi

KUIVA=()
[ "$TILA" = kuiva ] && KUIVA=(--dry-run)
loki "alku tila=$TILA lahde=$DUMP_DIR kohde=$REMOTE sailyta=$SAILYTA vanhoja_ryhmia=$VANHOJA"

# 1) Synkronoi: vanhat (yli SAILYTA) jaavat pois, .partial-tiedostot ohitetaan.
"${BASE[@]}" "${KUIVA[@]}" sync "$DUMP_DIR" "$REMOTE" \
  --exclude-from "$TMP/vanhat.txt" --exclude '*.tmp' --exclude '*.partial' \
  --max-delete "$MAX_POISTO" --transfers 2 --checkers 4 || { loki "sync epaonnistui"; exit 1; }

# 2) Poista Drivesta vanhat (sync ei koske suodattimella poissuljettuihin). Vain tasmaavat nimet.
if [ "$VANHOJA" -gt 0 ]; then
  "${BASE[@]}" "${KUIVA[@]}" delete "$REMOTE" --include-from "$TMP/vanhat.txt" --max-delete "$MAX_POISTO" \
    || { loki "vanhojen poisto epaonnistui"; exit 1; }
fi

ONNISTUI=1
loki "valmis tila=$TILA"
ping_kuma up "OK"
exit 0
