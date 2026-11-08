#!/usr/bin/env bash
# Aja KONTIN SISALLA (root). Asentaa Ollaman, rajaa kuuntelun sisaverkon osoitteeseen,
# asettaa muistirajan ja palomuurin (nftables): sisaan paasee vain SISAVERKKO_CIDR ja TAILNET_CIDR.
# Kaytto: asennus-kontissa.sh ASETUSTIEDOSTO SHA256_TIIVISTE
set -euo pipefail
asetukset="${1:?kayta: asennus-kontissa.sh ASETUSTIEDOSTO SHA256}"
tiiviste="${2:?anna tarkistussumma (Ollaman julkaisun sha256sum.txt)}"
. "$asetukset"
for v in OLLAMA_VERSIO KONTTI_OSOITE SISAVERKKO_CIDR OLLAMA_PORTTI MUISTI_MB; do
  [ -n "${!v:-}" ] || { echo "puuttuu asetus: $v" >&2; exit 2; }
done
osoite="${KONTTI_OSOITE%%/*}"
apt-get update -qq && apt-get install -y -qq curl zstd nftables ca-certificates
tmp="$(mktemp -d)"
curl -fsSL -o "$tmp/ollama.tar.zst" \
  "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSIO}/ollama-linux-amd64.tar.zst"
echo "$tiiviste  $tmp/ollama.tar.zst" | sha256sum -c -
tar -C /usr/local --zstd -xf "$tmp/ollama.tar.zst"
rm -rf "$tmp"
id ollama >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -m -d /var/lib/ollama ollama
cat > /etc/systemd/system/ollama.service <<UNIT
[Unit]
Description=Ollama (paikallinen mallipalvelin)
After=network-online.target nftables.service
Wants=network-online.target

[Service]
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Environment=OLLAMA_HOST=${osoite}:${OLLAMA_PORTTI}
Environment=OLLAMA_KEEP_ALIVE=10m
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_NOPRUNE=1
MemoryMax=$((MUISTI_MB - 512))M
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/ollama
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
tailnet_rivi=""
[ -n "${TAILNET_CIDR:-}" ] && tailnet_rivi="ip saddr ${TAILNET_CIDR} tcp dport ${OLLAMA_PORTTI} accept"
cat > /etc/nftables.conf <<NFT
#!/usr/sbin/nft -f
flush ruleset
table inet suodatin {
  chain input {
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif lo accept
    ip protocol icmp accept
    ip saddr ${SISAVERKKO_CIDR} tcp dport ${OLLAMA_PORTTI} accept
    ${tailnet_rivi}
  }
  chain forward { type filter hook forward priority 0; policy drop; }
}
NFT
nft -c -f /etc/nftables.conf
systemctl enable --now nftables ollama
echo "valmis. Tarkista: ss -ltn | grep ${OLLAMA_PORTTI}  (kuuntelun pitaa olla vain ${osoite})"
