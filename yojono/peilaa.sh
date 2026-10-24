#!/bin/sh
# peilaa.sh: vie siivotut yojono-raportit yksityiseen repoon (kansio raportit-palvelin/), josta Claude lukee ne pilvessa.
# Kaytto: peilaa.sh   (ymparisto: PEILAA_URL, PEILAA_AVAIN, PEILAA_PERUS, PEILAA_PYTHON, YOJONO_AJURI, PEILAA_KANSIO)
# Oletukset: URL git@github.com:tonyweckstrom1987/agenttifirma-docs.git, deploy-avain /etc/yojono/peilaus_avain (vain taman repon kirjoitusoikeus).
# Virhe ei kaada yojonoa: skripti palauttaa 1 ja ajuri ohittaa sen.
set -eu
URL="${PEILAA_URL:-git@github.com:tonyweckstrom1987/agenttifirma-docs.git}"
AVAIN="${PEILAA_AVAIN:-/etc/yojono/peilaus_avain}"
BASE="${PEILAA_PERUS:-/var/lib/yojono}"
AJURI="${YOJONO_AJURI:-/opt/yojono-ajuri}"
PYTHON="${PEILAA_PYTHON:-/opt/agentscope/bin/python}"
KANSIO="${PEILAA_KANSIO:-raportit-palvelin}"
TYO="${PEILAA_TYO:-/var/tmp/yojono-tyo}"
case "$KANSIO" in ""|/*|*..*|*[!A-Za-z0-9_./-]*) echo "peilaa.sh: virheellinen PEILAA_KANSIO" >&2; exit 2 ;; esac
mkdir -p "$TYO"
TMP=$(mktemp -d "$TYO/peilaa.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM
export GIT_TERMINAL_PROMPT=0
if [ -f "$AVAIN" ]; then
  export GIT_SSH_COMMAND="ssh -i $AVAIN -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$TYO/known_hosts_peilaus"
fi
git clone -q --depth 1 "$URL" "$TMP/r"
mkdir -p "$TMP/r/$KANSIO"
( cd "$AJURI" && "$PYTHON" -B -m agentti.peilaus "$BASE" "$TMP/r/$KANSIO" 14 )
cd "$TMP/r"
git add -A
if git diff --cached --quiet; then echo "peilaa.sh: ei muutoksia"; exit 0; fi
git -c user.name=yojono -c user.email=yojono@localhost -c core.hooksPath=/dev/null commit -q -m "yojono: raportit $(date +%F' '%H:%M)"
git push -q origin HEAD
echo "peilaa.sh: pushattu ($KANSIO)"
