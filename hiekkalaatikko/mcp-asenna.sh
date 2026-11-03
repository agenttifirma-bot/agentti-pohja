#!/usr/bin/env bash
# Ajetaan KONTIN SISALLA (pct exec <ID> -- bash /root/mcp-asenna.sh), ei isannalla eika agenttikontissa.
# Ymparisto: MCP_ERA_ESTETYT = valilyonnilla erotetut osoitteet (LAN, Tailscale), joiden pitaa olla estettyja; ne annetaan ajettaessa,
# eika niita kirjoiteta repoon (julkinen). Esim: MCP_ERA_ESTETYT="http://<lan-palvelu>:<portti> http://<tailscale-osoite>:<portti>"
# Asentaa Noden (nodejs.org, SHA256-tarkistus), mcp-doctorin (npm) ja kayttajan mcp. Lopuksi verkkokokeet.
set -euo pipefail
PROXY="${MCP_ERA_PROXY:?aseta MCP_ERA_PROXY (hiekkalaatikon proxy, http://<osoite>:3128)}"
ESTETYT="${MCP_ERA_ESTETYT:?aseta MCP_ERA_ESTETYT (valilyonnilla erotetut LAN- ja Tailscale-osoitteet, joiden pitaa olla estettyja)}"
NODE_VERSIO="${NODE_VERSIO:-v22.12.0}"
DOCTOR_VERSIO="${DOCTOR_VERSIO:-latest}"
export http_proxy="$PROXY" https_proxy="$PROXY" HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"

command -v xz >/dev/null 2>&1 || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xz-utils; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
tgz="node-${NODE_VERSIO}-linux-x64.tar.xz"
curl -fsS -m 120 -o "$tmp/$tgz" "https://nodejs.org/dist/${NODE_VERSIO}/${tgz}"
curl -fsS -m 30 -o "$tmp/SHASUMS256.txt" "https://nodejs.org/dist/${NODE_VERSIO}/SHASUMS256.txt"
(cd "$tmp" && grep -F " ${tgz}" SHASUMS256.txt | sha256sum -c -)
rm -rf /usr/local/node
mkdir -p /usr/local/node
tar -xJf "$tmp/$tgz" -C /usr/local/node --strip-components=1
export PATH="/usr/local/node/bin:$PATH"
node --version
npm install -g --no-audit --no-fund "@tonyweckstrom/mcp-doctor@${DOCTOR_VERSIO}"
ln -sf /usr/local/node/bin/mcp-doctor /usr/local/bin/mcp-doctor
id mcp >/dev/null 2>&1 || useradd --create-home --shell /bin/bash mcp
install -d -o mcp -g mcp -m 0700 /home/mcp/tyo /home/mcp/tulos
mcp-doctor --version

# Verkkokokeet: GitHub proxyn kautta kay, LAN, Tailscale ja suora ulospaasy eivat.
koe_ei() {  # nimi, komento...
  local nimi="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "VIRHE: $nimi onnistui, sen pitaisi olla estetty"; exit 1; fi
  echo "ok: $nimi estetty"
}
code="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' https://github.com || true)"
[ "$code" = "200" ] || { echo "VIRHE: github proxyn kautta palautti '$code'"; exit 1; }
echo "ok: github 200"
code="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' https://registry.npmjs.org/ || true)"
case "$code" in 2*|3*|4*) echo "ok: npm-rekisteri vastaa ($code)" ;; *) echo "VIRHE: npm-rekisteri '$code'"; exit 1 ;; esac
koe_ei "example.com proxyn kautta" curl -fsS -m 10 -o /dev/null https://example.com
koe_ei "suora yhteys 1.1.1.1" curl -fsS -m 6 --noproxy '*' -o /dev/null http://1.1.1.1
for osoite in $ESTETYT; do
  koe_ei "sisaverkko ($osoite)" curl -fsS -m 6 --noproxy '*' -o /dev/null "$osoite"
done
echo "asennus-ok"
