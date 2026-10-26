#!/usr/bin/env bash
# =============================================================================
# paketoi.sh - tekee julkaisupaketin (git archive, .tgz) ja tulostaa julkaise.sh-komennon.
#
# Kaytto (omalla koneella tai pilvessa, jossa repo on kloonattuna):
#     paketoi.sh <repo-hakemisto> <commit|ref> <kohde> [ulos-hakemisto]
# Esim.: paketoi.sh ~/infra-automaatio origin/main infra-automaatio .
#
# Paketti: <kohde>-<commit8>.tgz, ylatason hakemisto <kohde>-<commit8>/, commit-tunniste tallennettu
# tar-otsikkoon (git get-tar-commit-id), deterministinen gzip (-n), riippumaton paikallisesta core.autocrlf-asetuksesta. Ei koske repoon eika verkkoon (paitsi
# valinnainen origin/main-karjen vertailu). Salaisuuksia ei lisata; paketti on sellaisenaan repon sisalto.
# =============================================================================
set -u -o pipefail
EPA='EP\xc3\x84ONNISTUI'
loppu_epa() { echo; printf "$EPA: %s\n" "$*"; exit 1; }

[ $# -ge 3 ] && [ $# -le 4 ] || { sed -n '2,12p' "$0"; exit 2; }
REPO="$1"; REF="$2"; KOHDE="$3"; ULOS="${4:-.}"
[[ "$KOHDE" =~ ^[a-z0-9-]+$ ]] || loppu_epa "kohteen nimi ei kelpaa: $KOHDE"
command -v git >/dev/null 2>&1 && command -v gzip >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1 || loppu_epa "git, gzip tai sha256sum puuttuu"
[ -d "$REPO/.git" ] || [ -f "$REPO/HEAD" ] || loppu_epa "$REPO ei ole git-repo"
[ -d "$ULOS" ] || loppu_epa "kohdehakemistoa ei ole: $ULOS"

COMMIT=$(git -C "$REPO" rev-parse --verify --quiet "$REF^{commit}") || loppu_epa "commitia/refia '$REF' ei loydy repossa $REPO"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || loppu_epa "commit-tunniste ei ole 40 hex-merkkia"
PAKETTI="$ULOS/$KOHDE-${COMMIT:0:8}.tgz"
git -C "$REPO" -c core.autocrlf=false -c core.eol=lf archive --format=tar --prefix="$KOHDE-${COMMIT:0:8}/" "$COMMIT" | gzip -n > "$PAKETTI" || loppu_epa "git archive epaonnistui"
SHA=$(sha256sum "$PAKETTI" | cut -d' ' -f1)
LUETTU=$(gzip -dc "$PAKETTI" | git get-tar-commit-id 2>/dev/null || true)
[ "$LUETTU" = "$COMMIT" ] || loppu_epa "paketin commit-tunniste ($LUETTU) ei vastaa commitia ($COMMIT)"
TIEDOSTOJA=$(tar tzf "$PAKETTI" | grep -vc '/$' || true)

KARKI=$(git -C "$REPO" ls-remote origin refs/heads/main 2>/dev/null | awk '{print $1}')
if [ -z "$KARKI" ]; then KARKI_TEKSTI="main-karkea ei voitu tarkistaa (ei yhteytta origin-etapalvelimeen)"
elif [ "$KARKI" = "$COMMIT" ]; then KARKI_TEKSTI="commit on origin/main:n karki"
else KARKI_TEKSTI="HUOM: commit EI ole origin/main:n karki (${KARKI:0:12}); julkisilla repoilla julkaise.sh vaatii karjen tai --salli-ei-karki"; fi

echo "paketti  : $PAKETTI ($TIEDOSTOJA tiedostoa)"
echo "commit   : $COMMIT"
echo "sha256   : $SHA"
echo "tarkistus: $KARKI_TEKSTI"
echo
echo "Isannalle (yksi scp):"
echo "  scp $PAKETTI \${ISANTA:-root@<isanta>}:/root/"
echo "Julkaisu isannalla (kuiva-ajo ensin):"
echo "  bash /root/julkaise.sh $KOHDE /root/$(basename "$PAKETTI") $COMMIT $SHA --kuiva"
echo "  bash /root/julkaise.sh $KOHDE /root/$(basename "$PAKETTI") $COMMIT $SHA"
echo
echo "OK: paketti tehty ($KOHDE, ${COMMIT:0:12}), sha256 ${SHA:0:16}..."
