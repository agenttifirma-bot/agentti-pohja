#!/usr/bin/env bash
# Luo mallipalvelimen LXC-kontin. Aja Proxmox-isannalla (root) VASTA, kun PR on yhdistetty
# ja Tony on ottanut snapshotin. Oletuksena tulostaa vain komennot (kuiva-ajo).
# Kaytto: luo-kontti.sh ASETUSTIEDOSTO [--toteuta]
set -euo pipefail
asetukset="${1:?kayta: luo-kontti.sh ASETUSTIEDOSTO [--toteuta]}"
toteuta=0
[ "${2:-}" = "--toteuta" ] && toteuta=1
# shellcheck disable=SC1090
. "$asetukset"
for v in CTID KONTTI_NIMI SILTA KONTTI_OSOITE YHDYSKAYTAVA TALLENNUS LEVY_GT YDINTA MUISTI_MB SWAP_MB; do
  [ -n "${!v:-}" ] || { echo "puuttuu asetus: $v" >&2; exit 2; }
done
case "$CTID" in *[!0-9]*) echo "CTID ei ole numero" >&2; exit 2;; esac
if [ "$toteuta" = 1 ] && command -v pct >/dev/null && pct status "$CTID" >/dev/null 2>&1; then
  echo "kontti $CTID on jo olemassa: ei kosketa" >&2; exit 3
fi
# Ei julkista porttia: ei portinohjausta, ei firewall=0-ohitusta; silta on sisaverkon silta.
komennot=(
  "pct create $CTID local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst --hostname $KONTTI_NIMI --unprivileged 1 --cores $YDINTA --memory $MUISTI_MB --swap $SWAP_MB --rootfs $TALLENNUS:$LEVY_GT --net0 name=eth0,bridge=$SILTA,ip=$KONTTI_OSOITE,gw=$YHDYSKAYTAVA,firewall=1 --onboot 1 --features nesting=0"
)
for k in "${komennot[@]}"; do
  if [ "$toteuta" = 1 ]; then eval "$k"; else echo "[kuiva-ajo] $k"; fi
done
echo "Seuraavaksi: pct push $CTID asennus-kontissa.sh /root/asennus-kontissa.sh ja aja kontissa (katso README.md)."
