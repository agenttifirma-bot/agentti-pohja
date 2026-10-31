#!/bin/sh
# claude-jono omalle kayttajalleen (Tonyn paatos 30.10.2026). Aja CT115:ssa rootina: sh asenna-kayttaja.sh
# Idempotentti. Ei poista mitaan. Tilauskirjautuminen tehdaan lopuksi kasin (ohje tulostetaan).
#  - claudejono: agentti. Kirjoittaa vain /opt/agentscope/tyo:hon ja omaan kotiinsa /var/lib/claudejono.
#  - prbotti: lukee botin tunnuksen, avaa PR:t (claudejono-pr). Ei kotia, ei kuorta.
# Ajuri (claude-jono.service) jaa rootiksi: git, deploy key ja Telegram eivat nay agentille.
set -eu
[ "$(id -u)" = 0 ] || { echo "aja rootina" >&2; exit 1; }
LAHDE=$(cd "$(dirname "$0")" && pwd)
command -v sudo >/dev/null 2>&1 || { echo "sudo puuttuu: aja ensin 'apt-get install -y sudo' ja sitten tama skripti uudelleen" >&2; exit 1; }

id claudejono >/dev/null 2>&1 || useradd --system --home-dir /var/lib/claudejono --create-home --shell /bin/bash claudejono
id prbotti >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin prbotti
getent group systemd-journal >/dev/null && usermod -aG systemd-journal claudejono   # lokien luku diagnostiikkaan

install -d -o claudejono -g claudejono -m 755 /opt/agentscope/tyo
chown -R claudejono:claudejono /opt/agentscope/tyo
install -d -o prbotti -g prbotti -m 700 /etc/claudejono-pr /var/lib/claudejono-pr
install -o prbotti -g prbotti -m 600 /etc/yojono/github-bot.token /etc/claudejono-pr/token
install -o root -g root -m 755 "$LAHDE/claudejono-pr" /usr/local/sbin/claudejono-pr
install -o root -g root -m 440 "$LAHDE/sudoers.claudejono" /etc/sudoers.d/claudejono.uusi
visudo -cf /etc/sudoers.d/claudejono.uusi && mv /etc/sudoers.d/claudejono.uusi /etc/sudoers.d/claudejono

# claude-jonon oma avain vain rootille. /etc/yojono:n oikeuksiin ei kosketa (muut palvelut voivat lukea sita):
# tarkistus alla kertoo, mita agentti sielta nakee.
chmod 700 /etc/claude-jono
chmod -R go-rwx /etc/claude-jono

echo
echo "Tarkistus:"
for p in /etc/yojono/github-bot.token /etc/claude-jono/deploy_key /etc/claudejono-pr/token; do
  if runuser -u claudejono -- test -r "$p"; then echo "  VIRHE: claudejono lukee $p"; else echo "  ok: claudejono ei lue $p"; fi
done
if runuser -u claudejono -- test -w /var/lib/yojono/jono.json; then echo "  VIRHE: claudejono voi muuttaa katot"; else echo "  ok: claudejono ei voi muuttaa kattoja"; fi
for f in /etc/yojono/* /etc/paivakatsaus.env /opt/agentscope/api_key.txt; do
  [ -e "$f" ] && runuser -u claudejono -- test -r "$f" && echo "  HUOM: claudejono lukee $f (tarkista: chmod o-r, jos se on salaisuus)"
done
echo
echo "Seuraavaksi (kasin):"
echo "  runuser -l claudejono -c 'curl -fsSL https://claude.ai/install.sh | bash'"
echo "  runuser -l claudejono -c '~/.local/bin/claude'   # /login tilauksella, sitten /exit"
echo "  palvelu: Environment=CLAUDEJONO_KAYTTAJA=claudejono ja CLAUDEJONO_CLAUDE=/var/lib/claudejono/.local/bin/claude (systemd-malli)"
