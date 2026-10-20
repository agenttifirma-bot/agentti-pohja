#!/bin/bash
# Ajetaan Proxmox-isannalla (root). Idempotentti. Asentaa CT115:lle snapshot-oikeuden:
# avain sallii vain komennot listaa | snapshot ennen-<nimi> (ks. snapshot_isanta.py).
set -euo pipefail
CT=115
SRC=/opt/yojono-ajuri/isanta/snapshot_isanta.py
pct pull "$CT" "$SRC" /root/snapshot-kutsu.py
chmod 700 /root/snapshot-kutsu.py
pct exec "$CT" -- bash -c '[ -f /root/.ssh/snapshot_key ] || ssh-keygen -q -t ed25519 -N "" -C agentscope-snapshot -f /root/.ssh/snapshot_key'
AVAIN=$(pct exec "$CT" -- cat /root/.ssh/snapshot_key.pub | awk '{print $1" "$2}')
IP=$(pct exec "$CT" -- hostname -I | awk '{print $1}')
mkdir -p /root/.ssh && touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
if grep -qF "$AVAIN" /root/.ssh/authorized_keys; then
  echo "authorized_keys: rivi on jo olemassa"
else
  echo "from=\"$IP\",restrict,command=\"/root/snapshot-kutsu.py\" $AVAIN agentscope-snapshot" >> /root/.ssh/authorized_keys
  echo "authorized_keys: rivi lisatty (from=$IP)"
fi
echo "Valmis. Testi CT115:sta: python3 -m agentti.snapshot_kutsu listaa"
