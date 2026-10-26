#!/usr/bin/env bash
# =============================================================================
# asenna-julkaise.sh - asentaa julkaisukomennon Proxmox-isannalle (root) agentti-pohjan paketista.
#
# AJO (yksi komento):
#     bash asenna-julkaise.sh <agentti-pohja-paketti.tgz> <sha256> <commit40> [--vain-tarkista]
# Paketti tehdaan isanta/paketoi.sh:lla (tai git archive). Skripti tarkistaa sha256:n ja paketin commitin,
# poimii vain isanta/julkaise.sh, isanta/paketoi.sh ja isanta/julkaisu/*.conf, varmuuskopioi eroavat nykyiset
# ja asentaa: /root/julkaise.sh (0700), /root/paketoi.sh (0700), /root/julkaisu/*.conf (0600). Ajaa lopuksi
# julkaise.sh --itsetesti. Ei kosketa kontteihin, tiloihin eika konfiguraatioihin. Peruutus: *.ennen-<aika>.
# =============================================================================
set -u -o pipefail
EPA='EP\xc3\x84ONNISTUI'
KOHDE_JUURI=${JULKAISU_ASENNUSKOHDE:-/root}
TS=$(date +%Y%m%d-%H%M%S)
VAIN_TARKISTA=0
POS=()
for a in "$@"; do
  case "$a" in
    --vain-tarkista) VAIN_TARKISTA=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    --*) echo "Tuntematon valitsin: $a"; exit 2 ;;
    *) POS+=("$a") ;;
  esac
done
[ "${#POS[@]}" -eq 3 ] || { sed -n '2,12p' "$0"; exit 2; }
PAKETTI="${POS[0]}"; SHA="${POS[1]}"; COMMIT="${POS[2]}"
T=$(mktemp -d "${TMPDIR:-/tmp}/asenna-julkaise.XXXXXX"); trap 'rm -rf "$T"' EXIT
info() { echo "[$(date +%H:%M:%S)] $*"; }
epa() { echo; echo "Esitarkistus ei lapaissyt: $*"; echo "Mitaan ei muutettu."; echo; printf "$EPA: esitarkistus: %s\n" "$*"; exit 1; }

[ "$KOHDE_JUURI" != /root ] || [ "$(id -u)" = 0 ] || epa "aja rootina Proxmox-isannalla"
for t in git tar gzip sha256sum; do command -v "$t" >/dev/null 2>&1 || epa "puuttuu: $t"; done
[ -f "$PAKETTI" ] && [ ! -L "$PAKETTI" ] || epa "paketti ei ole tavallinen tiedosto: $PAKETTI"
[[ "$SHA" =~ ^[0-9a-f]{64}$ ]] && [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || epa "sha256 (64) tai commit (40) virheellinen"
[ "$(sha256sum "$PAKETTI" | cut -d' ' -f1)" = "$SHA" ] || epa "paketin sha256 ei tasmaa"
[ "$(gzip -dc "$PAKETTI" 2>/dev/null | git get-tar-commit-id 2>/dev/null || true)" = "$COMMIT" ] || epa "paketin commit ei ole annettu commit"
LISTA=$(tar tzf "$PAKETTI" 2>/dev/null) || epa "paketin luettelo ei onnistu"
grep -qE '^/|(^|/)\.\.(/|$)' <<< "$LISTA" && epa "paketissa on vaarallisia polkuja"
grep -qE '/isanta/julkaise\.sh$' <<< "$LISTA" || epa "paketista puuttuu isanta/julkaise.sh"
info "paketti ok: sha256 tasmaa, commit ${COMMIT:0:12}."
tar xzf "$PAKETTI" -C "$T" --strip-components=1 --no-same-owner --wildcards '*/isanta/julkaise.sh' '*/isanta/paketoi.sh' '*/isanta/julkaisu/*.conf' || epa "purku epaonnistui"
[ -f "$T/isanta/julkaise.sh" ] || epa "julkaise.sh puuttuu purusta"
bash -n "$T/isanta/julkaise.sh" || epa "julkaise.sh:n syntaksi ei kelpaa"
KONFIT=$(ls "$T"/isanta/julkaisu/*.conf 2>/dev/null || true)
[ -n "$KONFIT" ] || epa "paketissa ei ole konfiguraatioita (isanta/julkaisu/*.conf)"
info "asennettaisiin: $KOHDE_JUURI/julkaise.sh, $KOHDE_JUURI/paketoi.sh, $(wc -l <<< "$KONFIT") konfiguraatiota -> $KOHDE_JUURI/julkaisu/"
if [ "$VAIN_TARKISTA" = 1 ]; then echo; echo "OK: esitarkistukset lapaisty (--vain-tarkista): mitaan ei muutettu."; exit 0; fi

mkdir -p "$KOHDE_JUURI/julkaisu" && chmod 700 "$KOHDE_JUURI/julkaisu"
asenna() {   # asenna <lahde> <kohde> <mode>
  if [ -f "$2" ] && ! cmp -s "$1" "$2"; then cp -p "$2" "$2.ennen-$TS"; info "varmuuskopio: $2.ennen-$TS"; fi
  install -m "$3" "$1" "$2"
}
asenna "$T/isanta/julkaise.sh" "$KOHDE_JUURI/julkaise.sh" 700
[ -f "$T/isanta/paketoi.sh" ] && asenna "$T/isanta/paketoi.sh" "$KOHDE_JUURI/paketoi.sh" 700
for f in $KONFIT; do asenna "$f" "$KOHDE_JUURI/julkaisu/$(basename "$f")" 600; done
echo
echo "Asennetut tiedostot (sha256):"
sha256sum "$KOHDE_JUURI/julkaise.sh" "$KOHDE_JUURI/julkaisu/"*.conf | sed 's/^/    /'
if JULKAISU_HAKEMISTO="$KOHDE_JUURI/julkaisu" bash "$KOHDE_JUURI/julkaise.sh" --itsetesti > "$T/itsetesti.txt" 2>&1; then
  tail -2 "$T/itsetesti.txt" | sed 's/^/    /'
else
  sed 's/^/    /' "$T/itsetesti.txt"
  echo
  echo "PERUUTUS: palauta edelliset: mv $KOHDE_JUURI/julkaise.sh.ennen-$TS $KOHDE_JUURI/julkaise.sh (jos varmuuskopio syntyi)"
  printf "$EPA: %s\n" "itsetesti ei mennyt lapi"
  exit 1
fi
echo
echo "PERUUTUS: palauta varmuuskopiot (*.ennen-$TS) takaisin; tiedostot eivat vaikuta kontteihin."
echo "OK: julkaisukomento asennettu ($KOHDE_JUURI/julkaise.sh, commit ${COMMIT:0:12}); aja ensin kuiva-ajo: bash $KOHDE_JUURI/julkaise.sh <kohde> <paketti> <commit> <sha256> --kuiva"
