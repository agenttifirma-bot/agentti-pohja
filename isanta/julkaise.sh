#!/usr/bin/env bash
# =============================================================================
# julkaise.sh - yleistetty julkaisukomento Proxmox-isannalle (root):
#   kauppatiimi (CT119), infra-automaatio (CT118), yojono-ajuri (CT115).
#
# Periaate: koodi, tila ja konfiguraatio ovat erillaan. Julkaisu ja peruutus vaihtavat VAIN koodihakemiston
# (sisarhakemisto + mv; polut ennallaan). Tilakansio ja konfiguraatio eivat muutu: niiden sha256-tiiviste
# lasketaan ennen ja jalkeen, ja ero keskeyttaa ajon. Isanta ohjaa kaiken pct-komennoilla; kontteihin ei tule
# uusia skripteja, oikeuksia eika avaimia. Kohdekohtaiset asetukset: /root/julkaisu/<kohde>.conf (vain data).
#
# KAYTTO (aina yksi komento):
#   julkaise.sh <kohde> <paketti.tgz> <commit40> <sha256> [--kuiva] [--kanaria]
#                       [--ensijulkaisu] [--uudelleen] [--salli-ei-karki] [--paivita-skriptit]
#   julkaise.sh <kohde> --peruuta [--kuiva]                 palauttaa VAIN koodin (tila ei muutu)
#   julkaise.sh <kohde> --katastrofi-tila --snapshot NIMI   kopioi tilan talteen ENNEN pct rollbackia
#                                                           ja kertoo, mita palautus tuhoaisi (ei aja rollbackia)
#   julkaise.sh <kohde> --katastrofi-palauta KANSIO         palauttaa kopioidun tilan rollbackin jalkeen
#   julkaise.sh <kohde> --tila                              nykytila (vain luku)
#   julkaise.sh --itsetesti                                 tarkistaa tyokalut ja konfiguraatiot
#
# Paketti: git archive -tgz (isanta/paketoi.sh); commit luetaan paketista (git get-tar-commit-id).
# Esitarkistukset (kova exit 1, myos yolla; poikkeus --peruuta varoittaa ajastinikkunasta mutta jatkaa):
#   paketin sha256, paketin commit = annettu commit, julkisilla repoilla commit = main:n karki (ohitus vain
#   --salli-ei-karki, kirjataan lokiin), turvallinen paketti, kohteen koodi = oma manifestinsa (puhdas),
#   palvelut/lukot/prosessit vapaana, ajastinikkuna, snapshotteja alle 20, levytila, ei edellisen ajon jaanteita.
# --kuiva: tekee esitarkistukset ja paketin tarkistuksen, ei muuta mitaan (kaikki muutokset kulkevat muuta()-kautta).
# --paivita-skriptit: paivittaa lopuksi kohteen skriptikopiot (SKRIPTIT_HAKEMISTO) paketin skripteista, mutta VAIN
#   tiedostot, jotka ovat jo kohteessa ja eroavat paketista (uusia ei luoda). Ennen kopiointia varmuuskopio
#   <skripti>.ennen-<kohde>-<commit8>-<aika>; oikeudet ja omistaja kopioidaan vanhasta, tiiviste tarkistetaan. Virhe kumoaa
#   skriptit ja koodin; onnistumisen jalkeen peruutusohje tulostuu (--peruuta ei palauta skripteja). Oletuksena pois.
# --kanaria: lisaa tahallaan rikkinaisen esitarkistuksen ja todistaa, etta ajo keskeytyy ilman kirjoituksia.
# Loppurivi on aina "OK: ..." tai "EPAONNISTUI: ...". Loki: /root/julkaisu/loki.log ja ajo/<kohde>-<aika>.log
# =============================================================================
set -u -o pipefail
export LC_ALL=C.UTF-8

PCT=${PCT:-pct}
JH=${JULKAISU_HAKEMISTO:-/root/julkaisu}
YKSIKKOHAKEMISTO=${JULKAISU_YKSIKKOHAKEMISTO:-/etc/systemd/system}
ASENTAJAHAK=${JULKAISU_ASENTAJAHAKEMISTO:-/usr/local/sbin}      # kauppa-asenna / kauppa-palauta (vaihe 1)
SNAPSHOT_RAJA=20
PAKETTI_MAX_TAVUA=$((50 * 1024 * 1024))
PAKETTI_MAX_TIEDOSTOJA=3000

KUIVA=0; KANARIA=0; ENSIJULKAISU=0; UUDELLEEN=0; SALLI_EI_KARKI=0; PAIVITA_SKRIPTIT=0; SKRIPTIT_KUMOTTAVAT=()
TOIMI=julkaise; KOHDE=""; SNAP_VALINTA=""; KATASTROFI_KANSIO=""; POS=()
MUUTOKSIA=0                  # kasvaa jokaisesta muuta()-kutsusta; 0 = mitaan ei ole muutettu
VAIHDETTU=0; UUSI_LUOTU=0; YKSIKOT_ASENNETTU=0; PERUUTUS_TEHTY=0
TS=${JULKAISU_TS:-$(date +%Y%m%d-%H%M%S)}
T=""                         # isannan valiaikaishakemisto
AJASTIN_PYSAYTETTY=()
LOKI_LISA=""

# ---- aputoiminnot ---------------------------------------------------------------
info()    { echo "[$(date +%H:%M:%S)] $*"; }
varoita() { echo "[$(date +%H:%M:%S)] VAROITUS: $*"; }
laji()    { echo; echo "== $* =="; }
ok_loppu()  { palauta_ajastimet; echo; echo "OK: $*"; exit 0; }
epa_loppu() { palauta_ajastimet; echo; printf 'EP\xc3\x84ONNISTUI: %s\n' "$*"; exit 1; }   # loppurivin A tuotetaan escapella: lahdekoodi pysyy ASCII:na

# Jokainen muutos kulkee taman kautta: --kuivassa ei suoriteta mitaan.
muuta() {
  local kuvaus="$1"; shift
  if [ "$KUIVA" = 1 ]; then info "KUIVA: ei suoriteta: $kuvaus"; return 0; fi
  MUUTOKSIA=$((MUUTOKSIA + 1))
  "$@"
}

ct()  { "$PCT" exec "$CT" -- "$@"; }
# aja hakemistossa DIR (kayttajana U, jos annettu): ajaku_hak U DIR komento...
# sh -c: $0=hakemisto, $1=kayttaja, $2...=komento; shift poistaa vain kayttajan ($0 ei ole $@:ssa)
ajaku_hak() {
  local u="$1" d="$2"; shift 2
  if [ -n "$u" ]; then
    ct sh -c 'd="$0"; u="$1"; shift; cd "$d" && exec runuser -u "$u" -- "$@"' "$d" "$u" "$@"
  else
    ct sh -c 'cd "$0" && exec "$@"' "$d" "$@"
  fi
}

kirjaa_loki() {   # kirjaa_loki <rivi>  (vain oikeissa ajoissa)
  [ "$KUIVA" = 1 ] && return 0
  mkdir -p "$JH" && chmod 700 "$JH" 2>/dev/null
  printf '%s %s %s\n' "$(date '+%F %T')" "${KOHDE:--}" "$*" >> "$JH/loki.log" 2>/dev/null || true
}

lopputoimet() {
  palauta_ajastimet
  [ -n "$T" ] && rm -rf "$T"
  sleep 0.2          # tee ehtii kirjoittaa loppurivin
}
trap lopputoimet EXIT

# ---- virheenkasittely -----------------------------------------------------------
peruutusohje() {
  echo
  echo "PERUUTUS:"
  if [ "$TOIMI" = julkaise ] && [ "$MUUTOKSIA" -gt 0 ]; then
    echo "  Koodi (tila ei muutu):  julkaise.sh $KOHDE --peruuta"
    local sk
    for sk in "${SKRIPTIT_KUMOTTAVAT[@]:-}"; do
      [ -n "$sk" ] && echo "  Skripti takaisin:       pct exec $CT -- mv -f ${sk##*|} ${sk%%|*}"
    done
    [ -n "${SNAP_NIMI:-}" ] && echo "  Koko kontti (TUHOAA tilan!): ensin julkaise.sh $KOHDE --katastrofi-tila --snapshot $SNAP_NIMI, sitten pct rollback $CT $SNAP_NIMI"
  else
    echo "  Mitaan ei muutettu: peruutusta ei tarvita."
  fi
  [ -n "${LOKITIEDOSTO:-}" ] && echo "  Loki: $LOKITIEDOSTO"
}

# Esitarkistusvirhe (ennen muutoksia): keskeytys.
vika() {
  echo
  echo "Esitarkistus ei lapaissyt: $*"
  [ "$MUUTOKSIA" -eq 0 ] && echo "Mitaan ei muutettu."
  kirjaa_loki "ESITARKISTUS EPAONNISTUI: $*"
  epa_loppu "esitarkistus: $*"
}

# Virhe muutosten aikana: kumoa keskenerainen, kerro peruutus.
virhe() {
  echo
  echo "Virhe: $*"
  local tulos="mitaan ei muutettu"
  if [ "$PERUUTUS_TEHTY" = 1 ]; then
    tulos="PERUUTUS ON TEHTY: koodi vaihdettu edelliseen versioon, tilaa ei muutettu, mitaan ei kumottu - tarkista kasin"
  elif [ "$MUUTOKSIA" -gt 0 ]; then
    tulos="keskenerainen muutos kumottu"
    kumoa_kesken || tulos="AUTOMAATTINEN KUMOUS EI ONNISTUNUT - tarkista kasin"
  fi
  peruutusohje
  kirjaa_loki "EPAONNISTUI: $* ($tulos)"
  epa_loppu "$* ($tulos)"
}

# ---- konfiguraatio (vain data, ei koskaan source) -------------------------------
SALLITUT_AVAIMET="KOHDE CT REPO REPO_URL JULKINEN HAARA KOODI KOODI_OMISTAJA KOODI_MODE KOODI_GIT TILA KONFIG PALVELUT AJASTIMET PROSESSI_KUVIO LUKOT IKKUNA_S ASENTAJA PALAUTTAJA POIS VAADITUT TESTI_TAPA TESTI_CT TESTI_KAYTTAJA TESTI_ARGUMENTIT SAVU_KAYTTAJA SAVU_MODUULIT TERVEYS_KOMENTO YKSIKOT_ASENNUS YKSIKKOKANSIO PREV_MAARA LEVY_MIN_MT SKRIPTIT_HAKEMISTO SKRIPTIT_PAKETISSA"

nollaa_konf() {
  local k; for k in $SALLITUT_AVAIMET; do printf -v "$k" '%s' ""; done
  JULKINEN=0; HAARA=main; KOODI_MODE=755; KOODI_GIT=0; IKKUNA_S=120; ASENTAJA=yleinen; PREV_MAARA=3
  TESTI_TAPA=kontti; YKSIKOT_ASENNUS=0; LEVY_MIN_MT=300
}

lataa_konf() {   # lataa_konf <kohde>
  local f="$JH/$1.conf" rivi k v
  [[ "$1" =~ ^[a-z0-9-]+$ ]] || vika "virheellinen kohteen nimi: $1"
  [ -f "$f" ] && [ ! -L "$f" ] || vika "konfiguraatiota ei loydy: $f"
  if [ "$PCT" = pct ]; then
    [ "$(stat -c %U "$f")" = root ] && [ -z "$(find "$f" -perm /022)" ] || vika "$f: omistajan pitaa olla root eika muiden kirjoitettavissa"
  fi
  nollaa_konf
  while IFS= read -r rivi || [ -n "$rivi" ]; do
    rivi="${rivi%%#*}"
    rivi="${rivi#"${rivi%%[![:space:]]*}"}"; rivi="${rivi%"${rivi##*[![:space:]]}"}"
    [ -z "$rivi" ] && continue
    [[ "$rivi" =~ ^([A-Z0-9_]+)=(.*)$ ]] || vika "$f: virheellinen rivi"
    k="${BASH_REMATCH[1]}"; v="${BASH_REMATCH[2]}"
    v="${v#\"}"; v="${v%\"}"
    case " $SALLITUT_AVAIMET " in *" $k "*) ;; *) vika "$f: tuntematon avain $k" ;; esac
    [[ "$v" =~ ^[A-Za-z0-9_./:@%+=,\ -]*$ ]] || vika "$f: kielletty merkki arvossa $k"
    [[ "$v" == *..* ]] && vika "$f: '..' ei sallittu ($k)"
    printf -v "$k" '%s' "$v"
  done < "$f"
  [ "$KOHDE" = "$1" ] || vika "$f: KOHDE ($KOHDE) ei vastaa tiedoston nimea"
  [[ "$CT" =~ ^[0-9]{3}$ ]] || vika "$f: CT pitaa olla kolminumeroinen"
  # Tuotannossa polut rajataan tunnettuihin juuriin; testitilassa (PCT ylikirjoitettu) sallitaan mika tahansa turvallinen absoluuttinen polku.
  polku_ok() { if [ "$PCT" != pct ] && [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ ]]; then return 0; fi; [[ "$1" =~ $2 ]]; }
  polku_ok "$KOODI" '^/(opt|srv)/[a-z0-9._/-]+$' || vika "$f: KOODI-polku ei kelpaa"
  local p; for p in $TILA; do polku_ok "$p" '^/(var/lib|srv|opt)/[a-z0-9._/-]+$' || vika "$f: TILA-polku ei kelpaa: $p"; done
  [ -n "$TILA" ] || vika "$f: TILA puuttuu"
  for p in $KONFIG; do polku_ok "$p" '^/(etc|srv|opt)/[A-Za-z0-9._/-]+$' || vika "$f: KONFIG-polku ei kelpaa: $p"; done
  for p in $LUKOT; do polku_ok "$p" '^/(var/lib|srv|opt|run)/[A-Za-z0-9._/-]+$' || vika "$f: LUKOT-polku ei kelpaa: $p"; done
  for p in $SKRIPTIT_HAKEMISTO; do polku_ok "$p" '^/(opt|srv)/[A-Za-z0-9._/-]+$' || vika "$f: SKRIPTIT_HAKEMISTO ei kelpaa"; done
  [[ "$IKKUNA_S" =~ ^[0-9]+$ ]] && [[ "$PREV_MAARA" =~ ^[1-9]$ ]] && [[ "$LEVY_MIN_MT" =~ ^[0-9]+$ ]] || vika "$f: numeroarvo virheellinen"
  case "$ASENTAJA" in yleinen|kauppa-asenna) ;; *) vika "$f: ASENTAJA pitaa olla yleinen tai kauppa-asenna" ;; esac
  case "$TESTI_TAPA" in kontti|ct115|ei) ;; *) vika "$f: TESTI_TAPA virheellinen" ;; esac
  [ "$TESTI_TAPA" != ct115 ] || [[ "$TESTI_CT" =~ ^[0-9]{3}$ ]] || vika "$f: TESTI_CT puuttuu"
  [ "$TESTI_TAPA" != ct115 ] || [ "$TESTI_CT" != "$CT" ] || vika "$f: TESTI_CT ei saa olla sama kuin CT (testeja ei ajeta tuotantokontissa)"
  [ -n "$SAVU_MODUULIT" ] || vika "$f: SAVU_MODUULIT puuttuu"
  return 0
}

# ---- argumentit -----------------------------------------------------------------
kaytto() { sed -n '2,32p' "$0"; }
[ $# -ge 1 ] || { kaytto; exit 2; }
case "$1" in
  -h|--help) kaytto; exit 0 ;;
  --itsetesti) TOIMI=itsetesti; shift ;;
  *) KOHDE="$1"; shift ;;
esac
while [ $# -gt 0 ]; do
  case "$1" in
    --kuiva) KUIVA=1 ;;
    --kanaria) KANARIA=1 ;;
    --ensijulkaisu) ENSIJULKAISU=1 ;;
    --uudelleen) UUDELLEEN=1 ;;
    --salli-ei-karki) SALLI_EI_KARKI=1 ;;
    --paivita-skriptit) PAIVITA_SKRIPTIT=1 ;;
    --peruuta) TOIMI=peruuta ;;
    --tila) TOIMI=tila ;;
    --katastrofi-tila) TOIMI=katastrofi-tila ;;
    --katastrofi-palauta) TOIMI=katastrofi-palauta; shift; KATASTROFI_KANSIO="${1:-}" ;;
    --snapshot) shift; SNAP_VALINTA="${1:-}" ;;
    -h|--help) kaytto; exit 0 ;;
    --*) echo "Tuntematon valitsin: $1 (kayta --help)"; exit 2 ;;
    *) POS+=("$1") ;;
  esac
  shift
done

# Tee ajokohtainen loki vain oikeissa muutosajoissa.
if [ "$KUIVA" != 1 ] && [ "$KANARIA" != 1 ]; then
  case "$TOIMI" in
    julkaise|peruuta|katastrofi-tila|katastrofi-palauta)
      mkdir -p "$JH/ajo" 2>/dev/null && chmod 700 "$JH" "$JH/ajo" 2>/dev/null
      LOKITIEDOSTO="$JH/ajo/${KOHDE:-x}-$TS.log"
      exec > >(tee -a "$LOKITIEDOSTO") 2>&1 ;;
  esac
fi

# ---- yleiset esitarkistukset (vain luku) ------------------------------------------
tyokalut_isanta() {
  [ "$PCT" != pct ] || [ "$(id -u)" = 0 ] || vika "aja rootina Proxmox-isannalla"
  command -v "$PCT" >/dev/null 2>&1 || vika "$PCT-komentoa ei loydy (aja Proxmox-isannalla, ei kontissa)"
  local t; for t in git tar gzip sha256sum flock find sort awk; do command -v "$t" >/dev/null 2>&1 || vika "isannalta puuttuu komento: $t"; done
}

ct_kaynnissa() {   # ct_kaynnissa <ct>
  local s; s=$("$PCT" status "$1" 2>/dev/null || true)
  grep -q running <<< "$s" || vika "CT$1 ei ole kaynnissa"
}

tyokalut_kontti() {
  local t; for t in sh tar gzip sha256sum find sort xargs python3 flock pgrep systemctl df awk; do
    ct sh -c "command -v $t >/dev/null 2>&1" || vika "CT$CT:sta puuttuu komento: $t"
  done
  if [ -n "$TESTI_KAYTTAJA$SAVU_KAYTTAJA" ]; then ct sh -c 'command -v runuser >/dev/null 2>&1' || vika "CT$CT:sta puuttuu runuser"; fi
}

palvelut_vapaana() {   # palvelut_vapaana [virhe]: "virhe" = muutosten jalkeen, kumoaa keskenerainen (virhe), muuten esitarkistus (vika)
  local p s f=vika
  [ "${1:-}" = virhe ] && f=virhe
  for p in $PALVELUT; do
    s=$(ct systemctl is-active "$p.service" 2>/dev/null || true)
    case "$s" in inactive|failed|"") ;; *) "$f" "palvelu $p.service on '$s' (odotettu inactive); odota ajon valmistumista" ;; esac
  done
  if [ -n "$PROSESSI_KUVIO" ]; then
    if ct pgrep -f -- "$PROSESSI_KUVIO" >/dev/null 2>&1; then "$f" "kohteen prosessi on kaynnissa (kuvio $PROSESSI_KUVIO)"; fi
  fi
  local l; for l in $LUKOT; do
    ct sh -c 'exec 9>>"$0" && flock -n 9' "$l" >/dev/null 2>&1 || "$f" "lukko on varattu: $l (ajo kesken)"
  done
  info "palvelut ja lukot vapaana."
}

ajastin_ikkuna() {   # kova virhe; --peruuta: vain varoitus
  [ -n "$AJASTIMET" ] || return 0
  local s
  s=$(ct python3 -c 'import json, subprocess, sys, time
r = subprocess.run(["systemctl", "list-timers", "--all", "--output=json"], capture_output=True, text=True)
try:
    d = json.loads(r.stdout or "[]")
except ValueError:
    print("VIRHE"); sys.exit(0)
want = set(sys.argv[1:]); now = time.time(); best = None
for t in d:
    if t.get("unit") in want and t.get("next"):
        v = t["next"] / 1e6 - now
        best = v if best is None else min(best, v)
print("-" if best is None else int(max(best, 0)))' $AJASTIMET 2>/dev/null) || s="VIRHE"
  case "$s" in
    VIRHE|"") if [ "$TOIMI" = peruuta ]; then varoita "ajastinten seuraavaa ajoa ei saatu selville; jatketaan (peruutus)"; return 0; fi
              vika "ajastinten seuraavaa ajoa ei saatu selville" ;;
    -) info "ei ajastettua seuraavaa ajoa (ajastimia ei aktiivisena)." ;;
    *) if [ "$s" -lt "$IKKUNA_S" ]; then
         if [ "$TOIMI" = peruuta ]; then varoita "ajastin laukeaa ${s} s kuluttua (ikkuna $IKKUNA_S s); peruutus jatkuu, koska se pitaa toimia myos yolla"
         else vika "ajastin laukeaa ${s} s kuluttua (vaaditaan vahintaan $IKKUNA_S s); yrita uudelleen ajon jalkeen"; fi
       else info "seuraava ajastettu ajo ${s} s paasta (ikkuna $IKKUNA_S s)."; fi ;;
  esac
}

snapshot_maara() { local l; l=$("$PCT" listsnapshot "$CT" 2>/dev/null || true); grep -vc current <<< "$l" || true; }
snapshot_on() { local l; l=$("$PCT" listsnapshot "$CT" 2>/dev/null || true); grep -qE -- "-> $1( |\$)" <<< "$l"; }

snapshot_raja_tarkista() {
  local n; n=$(snapshot_maara)
  [[ "$n" =~ ^[0-9]+$ ]] || vika "snapshotien maaraa ei saatu selville"
  [ "$n" -lt "$SNAPSHOT_RAJA" ] || vika "CT$CT:lla on $n snapshotia (raja $SNAPSHOT_RAJA taynna): siivoa kasin ennen julkaisua"
  info "snapshotteja $n / $SNAPSHOT_RAJA."
}

levy_tarkista() {
  local v; v=$(ct df -Pm "$(dirname "$KOODI")" 2>/dev/null | awk 'NR==2{print $4}')
  [[ "$v" =~ ^[0-9]+$ ]] || vika "levytilaa ei saatu luettua"
  [ "$v" -ge "$LEVY_MIN_MT" ] || vika "levya vapaana vain ${v} Mt (vaaditaan $LEVY_MIN_MT)"
  local h; h=$(df -Pm "$T" 2>/dev/null | awk 'NR==2{print $4}')
  [[ "$h" =~ ^[0-9]+$ ]] && [ "$h" -ge 200 ] || vika "isannan tilapaislevya liian vahan"
  info "levya vapaana: kontti ${v} Mt, isanta ${h} Mt."
}

# Tiiviste (sisalto + nimet + oikeudet, ei aikaleimoja): tila ja konfiguraatio eivat saa muuttua.
tiiviste_polut() {
  ct sh -s -- "$@" <<'EOS'
for p in "$@"; do
  if [ ! -e "$p" ]; then echo "PUUTTUU:$p"; continue; fi
  echo "== $p"
  find "$p" -xdev -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum
  find "$p" -xdev \( -type f -o -type d \) -printf '%P|%y|%m|%U|%G\n' | LC_ALL=C sort
done | sha256sum | cut -c1-64
EOS
}

koodi_tarkista() {   # kohteen nykyinen koodi = oma manifestinsa (puhdas); ensijulkaisu erikseen
  ct test -d "$KOODI" || vika "koodikansiota $KOODI ei ole"
  NYKYINEN_COMMIT=$(ct sh -c 'sed -n "s/^commit=//p" "$0/.julkaisu-tieto" 2>/dev/null | head -1' "$KOODI" || true)
  if ct test -f "$KOODI/.julkaisu-manifesti"; then
    ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti >/dev/null 2>&1' "$KOODI" || vika "kohteen koodi poikkeaa julkaisumanifestistaan (paikallisia muutoksia?); tarkista $KOODI"
    info "nykyinen julkaisu: commit ${NYKYINEN_COMMIT:-?}; koodi vastaa manifestiaan (puhdas)."
    [ "$ENSIJULKAISU" = 0 ] || varoita "--ensijulkaisu annettu, vaikka manifesti on jo olemassa"
  else
    [ "$ENSIJULKAISU" = 1 ] || vika "kohteella ei ole julkaisumanifestia (ensimmainen julkaisu): anna --ensijulkaisu"
    if [ "$KOODI_GIT" = 1 ] && ct sh -c 'command -v git >/dev/null 2>&1 && test -d "$0/.git"' "$KOODI"; then
      local m; m=$(ct git -C "$KOODI" status --porcelain --untracked-files=no 2>/dev/null || echo "?")
      [ -z "$m" ] || vika "git-tyopuu ei ole puhdas: $(echo "$m" | head -3 | tr '\n' ' ')"
      NYKYINEN_COMMIT=$(ct git -C "$KOODI" rev-parse HEAD 2>/dev/null || true)
      info "ensijulkaisu: git-tyopuu puhdas, HEAD ${NYKYINEN_COMMIT:0:8}."
    else
      info "ensijulkaisu: lahtotilan manifesti luodaan nykyisesta koodista (puhtautta ei voi verrata mihinkaan)."
    fi
  fi
  ct test ! -e "$KOODI.uusi" || vika "edellisen ajon jaanne $KOODI.uusi on olemassa: tarkista ja poista kasin"
}

# ---- paketti (isannalla) ----------------------------------------------------------
paketti_tarkista() {   # PAKETTI COMMIT SHA -> tiedostolista, sisalto
  [ -f "$PAKETTI" ] && [ ! -L "$PAKETTI" ] || vika "paketti ei ole tavallinen tiedosto: $PAKETTI"
  [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || vika "commit pitaa olla 40 hex-merkkia"
  [[ "$SHA" =~ ^[0-9a-f]{64}$ ]] || vika "sha256 pitaa olla 64 hex-merkkia"
  local koko; koko=$(stat -c %s "$PAKETTI")
  [ "$koko" -le "$PAKETTI_MAX_TAVUA" ] || vika "paketti on liian suuri (${koko} tavua, raja $PAKETTI_MAX_TAVUA)"
  local s; s=$(sha256sum "$PAKETTI" | cut -d' ' -f1)
  [ "$s" = "$SHA" ] || vika "paketin sha256 ei tasmaa (laskettu ${s:0:16}..., annettu ${SHA:0:16}...)"
  gzip -t "$PAKETTI" 2>/dev/null || vika "paketti ei ole kelvollinen gzip"
  local pc; pc=$(gzip -dc "$PAKETTI" 2>/dev/null | git get-tar-commit-id 2>/dev/null || true)
  [ -n "$pc" ] || vika "pakettiin ei ole tallennettu commit-tunnistetta (tee paketti: git archive / isanta/paketoi.sh)"
  [ "$pc" = "$COMMIT" ] || vika "paketin commit (${pc:0:12}) ei ole annettu commit (${COMMIT:0:12})"
  info "paketti: sha256 tasmaa, commit ${COMMIT:0:12} = annettu commit."
  # sisallon turvallisuus
  local lista tyypit
  lista=$(tar tzf "$PAKETTI" 2>/dev/null) || vika "paketin luettelo ei onnistu"
  tyypit=$(tar tvzf "$PAKETTI" 2>/dev/null | cut -c1) || vika "paketin luettelo ei onnistu"
  grep -qE '[lhcbp]' <<< "$tyypit" && vika "paketissa on linkkeja tai laitetiedostoja (ei sallittu)"
  local n; n=$(wc -l <<< "$lista")
  [ "$n" -le "$PAKETTI_MAX_TIEDOSTOJA" ] || vika "paketissa liikaa tiedostoja ($n)"
  grep -qE '^/|(^|/)\.\.(/|$)' <<< "$lista" && vika "paketissa on vaarallisia polkuja (/-alku tai ..)"
  local ylat; ylat=$(cut -d/ -f1 <<< "$lista" | LC_ALL=C sort -u)
  [ "$(wc -l <<< "$ylat")" = 1 ] || vika "paketin pitaa sisaltaa tasan yksi ylatason hakemisto"
}

paketti_normalisoi() {   # purkaa, poistaa POIS, tekee manifestin ja tiedot, pakkaa deterministisesti -> $T/norm.tgz
  local pura="$T/pura"; mkdir -p "$pura"
  tar xzf "$PAKETTI" -C "$pura" --no-same-owner --no-same-permissions || vika "paketin purku epaonnistui"
  local top; top=$(ls "$pura"); NORM="$pura/$top"
  local p; for p in $POIS; do [[ "$p" =~ ^[A-Za-z0-9._-]+$ ]] || vika "POIS-nimi ei kelpaa: $p"; rm -rf "${NORM:?}/$p"; done
  for p in $VAADITUT; do [ -f "$NORM/$p" ] || vika "paketista puuttuu vaadittu tiedosto: $p"; done
  # salaisuuksien nimet ja yksityiset avaimet
  local huono; huono=$(find "$NORM" -type f \( -name '*.env' -o -name '.env*' -o -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'known_hosts' -o -name '*.p12' -o -name '*.pfx' \) 2>/dev/null | head -3)
  [ -z "$huono" ] || vika "paketissa on salaisuuden nakoisia tiedostoja: $(sed "s#$NORM/##" <<< "$huono" | tr '\n' ' ')"
  # oikea PEM-avain: otsikon jalkeen heti base64-runko (testifixtuurin pelkka otsikkorivi ei laukaise)
  if grep -rIlPz -e '-----BEGIN [A-Z ]*PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{40,}' "$NORM" >/dev/null 2>&1; then vika "paketissa on yksityisen avaimen lohko"; fi
  ( cd "$NORM" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum ) > "$T/manifesti"
  [ -s "$T/manifesti" ] || vika "paketti on tyhja"
  cp "$T/manifesti" "$NORM/.julkaisu-manifesti"
  {
    echo "kohde=$KOHDE"; echo "commit=$COMMIT"; echo "paketti_sha256=$SHA"
    echo "aika=$(date '+%F %T')"; echo "julkaisija=julkaise.sh"
  } > "$NORM/.julkaisu-tieto"
  ( cd "$pura" && tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='2026-01-01 00:00:00' -cf - "$top" | gzip -n > "$T/norm.tgz" ) || vika "paketin uudelleenpakkaus epaonnistui"
  NSHA=$(sha256sum "$T/norm.tgz" | cut -d' ' -f1)
  info "paketti normalisoitu: $(wc -l < "$T/manifesti") tiedostoa, poistettu: ${POIS:-ei mitaan}, sha256 ${NSHA:0:16}..."
}

karki_tarkista() {   # julkisilla repoilla commit = paakarki
  if [ "$JULKINEN" != 1 ]; then info "yksityinen repo: main-karkea ei voi tarkistaa isannalta (tarkistettu vain paketin commit)."; return 0; fi
  local url="${REPO_URL:-https://github.com/$REPO.git}" k
  k=$(git ls-remote "$url" "refs/heads/$HAARA" 2>/dev/null | awk '{print $1}')
  if [ "$k" = "$COMMIT" ]; then info "commit on $HAARA:n karki ($REPO)."; return 0; fi
  if [ "$SALLI_EI_KARKI" = 1 ]; then
    varoita "commit ${COMMIT:0:12} EI ole $HAARA:n karki (${k:0:12}${k:+...}); jatketaan, koska --salli-ei-karki annettu (kirjataan lokiin)"
    LOKI_LISA=" POIKKEUS=salli-ei-karki karki=${k:-tuntematon}"
    return 0
  fi
  vika "annettu commit ${COMMIT:0:12} ei ole $HAARA:n karki (${k:-ei luettavissa}); kayta karkea tai --salli-ei-karki (kirjataan lokiin)"
}

raportoi_erot() {   # varoituksia: yksikot ja skriptikopiot (ei muutoksia)
  local f d
  if [ -n "$YKSIKKOKANSIO" ] && [ -d "$NORM/$YKSIKKOKANSIO" ]; then
    for f in "$NORM/$YKSIKKOKANSIO"/*.service "$NORM/$YKSIKKOKANSIO"/*.timer; do
      [ -f "$f" ] || continue
      if ! ct sh -c 'cat "$0" 2>/dev/null' "$YKSIKKOHAKEMISTO/$(basename "$f")" | cmp -s - "$f"; then
        [ "$YKSIKOT_ASENNUS" = 1 ] && info "yksikko $(basename "$f") paivitetaan asennuksessa." || varoita "yksikko $(basename "$f") eroaa asennetusta: asenna kasin (ei automaattista)"
      fi
    done
  fi
  if [ -n "$SKRIPTIT_HAKEMISTO" ] && [ -n "$SKRIPTIT_PAKETISSA" ] && [ -d "$NORM/$SKRIPTIT_PAKETISSA" ]; then
    for f in "$NORM/$SKRIPTIT_PAKETISSA"/*.sh; do
      [ -f "$f" ] || continue
      d=$(ct sh -c 'sha256sum "$0" 2>/dev/null | cut -d" " -f1' "$SKRIPTIT_HAKEMISTO/$(basename "$f")" || true)
      if [ -z "$d" ]; then varoita "skripti $(basename "$f") puuttuu kohteesta $SKRIPTIT_HAKEMISTO"
      elif [ "$d" != "$(sha256sum "$f" | cut -d' ' -f1)" ]; then if [ "$PAIVITA_SKRIPTIT" = 1 ]; then info "skripti $(basename "$f") eroaa kohteen kopiosta $SKRIPTIT_HAKEMISTO: paivitetaan lopuksi (--paivita-skriptit)"; else varoita "skripti $(basename "$f") eroaa kohteen kopiosta $SKRIPTIT_HAKEMISTO (ei paiviteta tassa; --paivita-skriptit paivittaa)"; fi; fi
    done
  fi
}

paivita_skriptit() {   # --paivita-skriptit: vain jo olemassa olevat, eroavat skriptikopiot; varmuuskopio, tiiviste, kumottavissa
  [ "$PAIVITA_SKRIPTIT" = 1 ] || return 0
  if [ -z "$SKRIPTIT_HAKEMISTO" ] || [ -z "$SKRIPTIT_PAKETISSA" ]; then varoita "--paivita-skriptit: konfiguraatiossa ei SKRIPTIT_HAKEMISTO/SKRIPTIT_PAKETISSA; ei skriptipaivityksia"; return 0; fi
  local f n dst bak uusi sha nyt
  for f in "$NORM/$SKRIPTIT_PAKETISSA"/*.sh; do
    [ -f "$f" ] || continue
    n=$(basename "$f"); dst="$SKRIPTIT_HAKEMISTO/$n"
    ct test -f "$dst" || { info "skripti $n puuttuu kohteesta: uutta ei luoda."; continue; }
    sha=$(sha256sum "$f" | cut -d' ' -f1)
    nyt=$(ct sh -c 'sha256sum "$0" | cut -d" " -f1' "$dst")
    [ "$nyt" != "$sha" ] || continue
    bak="$dst.ennen-$KOHDE-${COMMIT:0:8}-$TS"; uusi="$dst.julkaisu-uusi"
    muuta "skriptin varmuuskopio $n" ct cp -p "$dst" "$bak" || virhe "skriptin $n varmuuskopiointi epaonnistui"
    SKRIPTIT_KUMOTTAVAT+=("$dst|$bak")
    muuta "skripti kontille $n" "$PCT" push "$CT" "$f" "$uusi" --perms 600 || virhe "skriptin $n siirto kontille epaonnistui"
    muuta "skriptin vaihto $n" ct sh -c 'chmod --reference="$1" "$0" && chown --reference="$1" "$0" && mv -f "$0" "$1"' "$uusi" "$dst" || virhe "skriptin $n vaihto epaonnistui"
    ct sh -c 'echo "$1  $0" | sha256sum -c --quiet -' "$dst" "$sha" || virhe "skriptin $n tiiviste ei tasmaa vaihdon jalkeen"
    info "skripti $dst paivitetty (varmuuskopio: $bak)."
  done
  if [ "${#SKRIPTIT_KUMOTTAVAT[@]}" -gt 0 ]; then kirjaa_loki "SKRIPTIT PAIVITETTY: ${SKRIPTIT_KUMOTTAVAT[*]}"; fi
}

# ---- ajastimet ja kumous --------------------------------------------------------
pysayta_ajastimet() {
  local a
  for a in $AJASTIMET; do
    if [ "$(ct systemctl is-active "$a" 2>/dev/null || true)" = active ]; then
      muuta "pysayta $a" ct systemctl stop "$a" || virhe "ajastimen $a pysaytys epaonnistui"
      [ "$KUIVA" = 1 ] || AJASTIN_PYSAYTETTY+=("$a")     # kuivassa ei pysaytetty, joten ei palauteta
    fi
  done
}
palauta_ajastimet() {
  local a
  for a in "${AJASTIN_PYSAYTETTY[@]:-}"; do
    [ -n "$a" ] || continue
    "$PCT" exec "$CT" -- systemctl start "$a" >/dev/null 2>&1 && info "ajastin $a kaynnistetty uudelleen." || echo "VAROITUS: ajastimen $a kaynnistys epaonnistui: kaynnista kasin: pct exec $CT -- systemctl start $a"
  done
  AJASTIN_PYSAYTETTY=()
}

tyhjenna_kontin_tmp() { "$PCT" exec "$CT" -- sh -c 'rm -f "$0"' "${KONTTI_PAKETTI:-/nonexistent}" >/dev/null 2>&1 || true; }

kumoa_kesken() {
  local ok=0 sk
  for sk in "${SKRIPTIT_KUMOTTAVAT[@]:-}"; do
    [ -n "$sk" ] || continue
    ct sh -c 'rm -f "$0.julkaisu-uusi"; [ -f "$1" ] && mv -f "$1" "$0"' "${sk%%|*}" "${sk##*|}" && info "skripti palautettu: ${sk%%|*}" || ok=1
  done
  SKRIPTIT_KUMOTTAVAT=()
  if [ "$VAIHDETTU" = 1 ]; then
    if ct sh -c 'mv "$1" "$1.viallinen-$3" && mv "$2" "$1"' sh "$KOODI" "${PREV:-/nonexistent}" "$TS"; then
      info "koodi palautettu edelliseen versioon (viallinen: $KOODI.viallinen-$TS)."; VAIHDETTU=0
      if [ "$YKSIKOT_ASENNETTU" = 1 ]; then asenna_yksikot palauta || ok=1; fi
    else ok=1; fi
  fi
  if [ "$UUSI_LUOTU" = 1 ]; then ct rm -rf "$KOODI.uusi" || ok=1; UUSI_LUOTU=0; fi
  tyhjenna_kontin_tmp
  return $ok
}

asenna_yksikot() {   # asenna_yksikot [palauta]: kopioi muuttuneet yksikot KOODIsta /etc/systemd/system ja daemon-reload
  [ "$YKSIKOT_ASENNUS" = 1 ] || return 0
  local d="$KOODI${YKSIKKOKANSIO:+/$YKSIKKOKANSIO}"
  [ "$YKSIKKOKANSIO" = "." ] && d="$KOODI"
  if ! ct test -d "$d"; then info "yksikkokansiota $d ei ole (ei yksikoita asennettavaksi)."; return 0; fi
  muuta "yksikot" ct sh -c 'cd "$0" || exit 1; muut=0
for u in *.service *.timer; do
  [ -f "$u" ] || continue
  cmp -s "$u" "$1/$u" 2>/dev/null || { cp "$u" "$1/$u" && muut=1; }
done
[ "$muut" = 1 ] && systemctl daemon-reload
exit 0' "$d" "$YKSIKKOHAKEMISTO" || return 1
  YKSIKOT_ASENNETTU=1
}

# ---- yhteiset jalkitarkistukset --------------------------------------------------
tarkista_tila_ennallaan() {   # tarkista_tila_ennallaan <tila_ennen> <konfig_ennen>
  local t k
  t=$(tiiviste_polut $TILA); k=$(tiiviste_polut $KONFIG)
  [ "$t" = "$1" ] || virhe "TILAKANSIO MUUTTUI (tiiviste ${1:0:12} -> ${t:0:12}); tilaa ei saa muuttaa julkaisussa tai peruutuksessa"
  [ "$k" = "$2" ] || virhe "KONFIGURAATIO MUUTTUI (tiiviste ${2:0:12} -> ${k:0:12})"
  info "tila ja konfiguraatio ennallaan (tiiviste ${t:0:12} / ${k:0:12})."
}

savukoe() {
  local snip='import importlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
for m in sys.argv[2:]:
    importlib.import_module(m)
print("savu OK")'
  local out; out=$(ajaku_hak "$SAVU_KAYTTAJA" "$KOODI" python3 -B -c "$snip" "$KOODI" $SAVU_MODUULIT 2>&1) || { echo "$out" | tail -3 | sed 's/^/    /'; return 1; }
  [ "$out" = "savu OK" ] || { echo "$out" | tail -3 | sed 's/^/    /'; return 1; }
  info "savukoe ok ($SAVU_MODUULIT)."
}

# Toiminnallinen terveystarkistus (valinnainen, TERVEYS_KOMENTO): komento ajetaan asennetun koodin hakemistossa (SAVU_KAYTTAJA:na),
# aikarajalla 60 s; poistumiskoodi 0 = ok. Epaonnistuminen kumoaa koodin (virhe -> kumoa_kesken). Komennon pitaa olla vain luku (tila ja
# konfiguraatio tarkistetaan tiivisteella heti perassa). Tyhja arvo = ei tarkistusta.
terveystarkistus() {
  [ -n "$TERVEYS_KOMENTO" ] || return 0
  local out; out=$(ajaku_hak "$SAVU_KAYTTAJA" "$KOODI" timeout 60 $TERVEYS_KOMENTO 2>&1) || { echo "$out" | tail -3 | sed 's/^/    /'; return 1; }
  info "terveystarkistus ok ($TERVEYS_KOMENTO)."
}

# =============================================================================
# TOIMINNOT
# =============================================================================
paketti_ja_kohde_esitarkistukset() {
  ct_kaynnissa "$CT"
  tyokalut_kontti
  palvelut_vapaana
  ajastin_ikkuna
}

julkaise_toimi() {
  [ "${#POS[@]}" -eq 3 ] || { kaytto; echo; echo "Julkaisu vaatii: <kohde> <paketti.tgz> <commit40> <sha256>"; exit 2; }
  PAKETTI="${POS[0]}"; COMMIT="${POS[1]}"; SHA="${POS[2]}"
  T=$(mktemp -d "${TMPDIR:-/tmp}/julkaise.XXXXXX")
  laji "1/6 Esitarkistukset (vain luku)"
  [ "$KUIVA" = 1 ] && info "KUIVA-AJO: mitaan ei muuteta."
  [ "$KANARIA" = 1 ] && info "KANARIA-AJO: lopuksi lisataan tahallaan rikkinainen esitarkistus."
  info "kohde $KOHDE (CT$CT), koodi $KOODI, ASENTAJA=$ASENTAJA, $(date '+%F %T')"
  tyokalut_isanta
  paketti_tarkista
  karki_tarkista
  paketti_ja_kohde_esitarkistukset
  paketti_normalisoi
  koodi_tarkista
  if [ -n "${NYKYINEN_COMMIT:-}" ] && [ "$NYKYINEN_COMMIT" = "$COMMIT" ] && [ "$UUDELLEEN" = 0 ]; then
    ok_loppu "commit ${COMMIT:0:12} on jo asennettu kohteessa $KOHDE (mitaan ei muutettu; --uudelleen pakottaa)"
  fi
  snapshot_raja_tarkista
  levy_tarkista
  raportoi_erot
  TILA_ENNEN=$(tiiviste_polut $TILA); KONFIG_ENNEN=$(tiiviste_polut $KONFIG)
  info "tilan tiiviste ennen: ${TILA_ENNEN:0:16}..., konfiguraation: ${KONFIG_ENNEN:0:16}..."
  if [ "$TESTI_TAPA" = ct115 ]; then ct_kaynnissa "$TESTI_CT"; fi

  if [ "$KANARIA" = 1 ]; then
    echo; echo "Esitarkistus ei lapaissyt (tahallinen kanaria): kanaria-esitarkistus on aina rikki."
    if [ "$MUUTOKSIA" -eq 0 ]; then
      ok_loppu "KANARIA: tahallisesti rikkinainen esitarkistus keskeytti ajon, mitaan ei muutettu (kirjoituksia: 0)"
    fi
    epa_loppu "KANARIA: ajo ei pysahtynyt ennen muutoksia (kirjoituksia: $MUUTOKSIA)"
  fi

  PREV="$KOODI.prev-$TS"
  if [ "$ASENTAJA" = yleinen ]; then
    ct test ! -e "$PREV" || vika "kohdenimi $PREV on jo olemassa (edellinen ajo samalla sekunnilla); odota sekunti ja aja uudelleen"
  fi
  SNAP_NIMI="pre-$KOHDE-${COMMIT:0:8}-$(date +%H%M)"
  KONTTI_PAKETTI="/tmp/julkaisu-$KOHDE-$TS.tgz"
  if [ "$KUIVA" = 1 ]; then
    laji "SUUNNITELMA (kuiva-ajo, ei suoriteta)"
    info "snapshot $SNAP_NIMI; paketti -> CT$CT:$KONTTI_PAKETTI"
    if [ "$ASENTAJA" = yleinen ]; then info "pura $KOODI.uusi, testit ($TESTI_TAPA), vaihto $KOODI -> $PREV"; else info "asentaja: $ASENTAJAHAK/kauppa-asenna"; fi
    info "ajastimet pysaytetaan vaihdon ajaksi: ${AJASTIMET:-ei ajastimia}; savukoe: $SAVU_MODUULIT; tila/konfiguraatio tarkistetaan tiivisteella."
    ok_loppu "KUIVA-AJO: esitarkistukset lapaisty ja paketti tarkistettu; mitaan ei muutettu."
  fi

  laji "2/6 Snapshot ja paketti kontille"
  kirjaa_loki "JULKAISU ALKAA commit=${COMMIT:0:12} paketti_sha=${SHA:0:12} flags: ensijulkaisu=$ENSIJULKAISU uudelleen=$UUDELLEEN$LOKI_LISA"
  muuta "snapshot" "$PCT" snapshot "$CT" "$SNAP_NIMI" --description "julkaisu $KOHDE ${COMMIT:0:8}" >/dev/null || virhe "snapshotin otto epaonnistui"
  snapshot_on "$SNAP_NIMI" || virhe "snapshotia $SNAP_NIMI ei loydy oton jalkeen"
  info "snapshot $SNAP_NIMI otettu."
  muuta "paketti kontille" "$PCT" push "$CT" "$T/norm.tgz" "$KONTTI_PAKETTI" --perms 600 || virhe "paketin siirto kontille epaonnistui"
  ct sh -c 'echo "$1  $0" | sha256sum -c --quiet -' "$KONTTI_PAKETTI" "$NSHA" || virhe "paketin sha256 ei tasmaa kontissa"
  info "paketti kontissa, sha256 tasmaa."

  laji "3/6 Asennus (ajastimet pysaytettyna vaihdon ajan)"
  if [ "$ASENTAJA" = yleinen ]; then
    asenna_yleinen
  else
    asenna_delegoitu
  fi

  laji "4/6 Jalkitarkistukset"
  ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti' "$KOODI" >/dev/null || virhe "asennetun koodin manifesti ei tasmaa"
  info "asennettu koodi vastaa manifestia (${COMMIT:0:12})."
  tarkista_tila_ennallaan "$TILA_ENNEN" "$KONFIG_ENNEN"
  palvelut_vapaana virhe
  paivita_skriptit
  palauta_ajastimet

  laji "5/6 Siivous"
  tyhjenna_kontin_tmp
  if [ "$ASENTAJA" = yleinen ]; then
    muuta "vanhojen prev-versioiden poisto" ct sh -c 'ls -d "$0".prev-* 2>/dev/null | LC_ALL=C sort -r | tail -n +$(( $1 + 1 )) | xargs -r rm -rf' "$KOODI" "$PREV_MAARA"
    info "prev-versioita sailytetaan $PREV_MAARA."
  fi

  laji "6/6 Valmis"
  kirjaa_loki "JULKAISU OK commit=${COMMIT:0:12}"
  peruutusohje
  ok_loppu "$KOHDE: commit ${COMMIT:0:12} asennettu (CT$CT, $KOODI), tila ja konfiguraatio ennallaan. Snapshot: $SNAP_NIMI."
}

asenna_yleinen() {
  local u="$KOODI.uusi"
  muuta "pura uusi koodi" ct sh -c 'set -e; rm -rf "$1"; mkdir -p "$1"; tar xzf "$0" -C "$1" --strip-components=1 --no-same-owner' "$KONTTI_PAKETTI" "$u" || virhe "paketin purku kontissa epaonnistui"
  UUSI_LUOTU=1
  if [ -n "$KOODI_OMISTAJA" ]; then muuta "omistaja" ct chown -R "$KOODI_OMISTAJA" "$u" || virhe "chown epaonnistui"; fi
  muuta "oikeudet" ct chmod "$KOODI_MODE" "$u" || virhe "chmod epaonnistui"
  ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti' "$u" >/dev/null || virhe "puretun koodin manifesti ei tasmaa"
  info "uusi koodi purettu: $u, manifesti ok."

  case "$TESTI_TAPA" in
    kontti)
      info "ajetaan testit kontissa ($u): python3 -B -m unittest $TESTI_ARGUMENTIT"
      local out rc
      out=$(muuta "testit" ajaku_hak "$TESTI_KAYTTAJA" "$u" python3 -B -m unittest $TESTI_ARGUMENTIT 2>&1); rc=$?
      echo "$out" | tail -3 | sed 's/^/    /'
      { [ "$rc" -eq 0 ] && grep -q '^OK' <<< "$out"; } || virhe "testit eivat mene lapi (koodia ei vaihdettu)" ;;
    ct115)
      info "ajetaan testit CT$TESTI_CT:n tilapaishakemistossa (EI CT$CT:ssa)"
      local out rc tpaketti="/tmp/julkaisu-testi-$KOHDE-$TS.tgz"
      muuta "testipaketti" "$PCT" push "$TESTI_CT" "$T/norm.tgz" "$tpaketti" --perms 600 || virhe "testipaketin siirto CT$TESTI_CT:hen epaonnistui"
      out=$(muuta "testit" "$PCT" exec "$TESTI_CT" -- sh -c 'd=$(mktemp -d /tmp/julkaisu-testi.XXXXXX) && tar xzf "$0" -C "$d" --strip-components=1 --no-same-owner && cd "$d" && python3 -B -m unittest "$@"; rc=$?; cd /; rm -rf "$d" "$0"; exit $rc' "$tpaketti" $TESTI_ARGUMENTIT 2>&1); rc=$?
      echo "$out" | tail -3 | sed 's/^/    /'
      { [ "$rc" -eq 0 ] && grep -q '^OK' <<< "$out"; } || virhe "testit eivat mene lapi CT$TESTI_CT:ssa (koodia ei vaihdettu)" ;;
    ei) info "testeja ei ajeta (TESTI_TAPA=ei)." ;;
  esac

  # ensijulkaisu: nykyisen koodin manifesti talteen ennen vaihtoa
  if [ "$ENSIJULKAISU" = 1 ] && ! ct test -f "$KOODI/.julkaisu-manifesti"; then
    muuta "lahtotilan manifesti" ct sh -c 'cd "$0" && find . -type f -not -path "./.git/*" -not -path "*/__pycache__/*" -not -name "*.pyc" -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum > "$1"' "$KOODI" "$KOODI.lahtomanifesti.tmp" || virhe "lahtotilan manifestin luonti epaonnistui"
  fi

  pysayta_ajastimet
  palvelut_vapaana virhe     # uusintatarkistus ajastimien pysaytyksen jalkeen (kumoaa .uusi:n)
  muuta "koodin vaihto" ct sh -c 'mv "$1" "$2" && { mv "$3" "$1" || { mv "$2" "$1"; exit 1; }; }' sh "$KOODI" "$PREV" "$u" || virhe "koodihakemiston vaihto epaonnistui"
  VAIHDETTU=1; UUSI_LUOTU=0
  info "koodi vaihdettu: $KOODI (uusi), edellinen: $PREV"
  if [ "$ENSIJULKAISU" = 1 ] && ct test -f "$KOODI.lahtomanifesti.tmp"; then
    muuta "lahtotilan manifesti prev-kansioon" ct sh -c 'mv "$0" "$1/.julkaisu-manifesti" && printf "kohde=%s\ncommit=%s\nlahtotila=ensijulkaisu\n" "$2" "${3:-tuntematon}" > "$1/.julkaisu-tieto"' "$KOODI.lahtomanifesti.tmp" "$PREV" "$KOHDE" "${NYKYINEN_COMMIT:-}" || varoita "lahtotilan manifestin siirto prev-kansioon epaonnistui"
  fi
  asenna_yksikot || virhe "yksikoiden asennus epaonnistui"
  savukoe || virhe "savukoe epaonnistui (paluu edelliseen versioon)"
  terveystarkistus || virhe "terveystarkistus epaonnistui (paluu edelliseen versioon)"
}

asenna_delegoitu() {
  info "asentaja: $ASENTAJAHAK/kauppa-asenna (vaihe 1; ajaa testit, vaihdon, savukokeen ja yksikot itse)"
  ct test -x "$ASENTAJAHAK/kauppa-asenna" || virhe "kauppa-asenna puuttuu kontista"
  pysayta_ajastimet
  palvelut_vapaana
  local out rc
  out=$(muuta "kauppa-asenna" ct "$ASENTAJAHAK/kauppa-asenna" "$KONTTI_PAKETTI" "${COMMIT:0:8}" 2>&1); rc=$?
  echo "$out" | tail -4 | sed 's/^/    /'
  if [ "$rc" -ne 0 ] || ! grep -q 'ASENNUS OK' <<< "$out"; then
    # kauppa-asenna kumoaa itse epaonnistuneen asennuksen (k1 ei muutu tai paluu edelliseen)
    virhe "kauppa-asenna epaonnistui (koodi $rc)"
  fi
  VAIHDETTU=0   # vaihdon kumoaa kauppa-asenna itse; jalkitarkistukset varmistavat lopputuloksen
  PREV=$(ct sh -c 'ls -d "$0".prev-* 2>/dev/null | LC_ALL=C sort | tail -n 1' "$KOODI" || true)
}

peruuta_toimi() {
  T=$(mktemp -d "${TMPDIR:-/tmp}/julkaise.XXXXXX")
  laji "1/4 Esitarkistukset (vain luku)"
  [ "$KUIVA" = 1 ] && info "KUIVA-AJO: mitaan ei muuteta."
  info "kohde $KOHDE (CT$CT), peruutus: vain koodihakemisto $KOODI; tila ei muutu."
  tyokalut_isanta; ct_kaynnissa "$CT"; tyokalut_kontti
  palvelut_vapaana
  ajastin_ikkuna
  PREV=$(ct sh -c 'ls -d "$0".prev-* 2>/dev/null | LC_ALL=C sort | tail -n 1' "$KOODI" || true)
  [ -n "$PREV" ] || vika "edellista versiota ($KOODI.prev-*) ei ole"
  ct test -d "$PREV" || vika "edellinen versio $PREV ei ole hakemisto"
  if ct test -f "$PREV/.julkaisu-manifesti"; then
    ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti >/dev/null 2>&1' "$PREV" || vika "edellinen versio $PREV ei vastaa manifestiaan (eheys)"
    local pc; pc=$(ct sh -c 'sed -n "s/^commit=//p" "$0/.julkaisu-tieto" 2>/dev/null | head -1' "$PREV" 2>/dev/null | cut -c1-12 || true)
    info "edellinen versio $PREV: eheys ok (commit ${pc:-?})."
  else
    varoita "edellisella versiolla ei ole manifestia: eheytta ei voi tarkistaa"
  fi
  ct test ! -e "$KOODI.palautettu-$TS" || vika "kohdenimi $KOODI.palautettu-$TS on jo olemassa"
  TILA_ENNEN=$(tiiviste_polut $TILA); KONFIG_ENNEN=$(tiiviste_polut $KONFIG)
  info "tilan tiiviste ennen: ${TILA_ENNEN:0:16}..., konfiguraation: ${KONFIG_ENNEN:0:16}..."
  if [ "$KUIVA" = 1 ]; then
    laji "SUUNNITELMA (kuiva-ajo, ei suoriteta)"
    info "vaihdettaisiin: $KOODI -> $KOODI.palautettu-$TS ja $PREV -> $KOODI; tilakansiota ei kosketa."
    ok_loppu "KUIVA-AJO: peruutuksen esitarkistukset lapaisty; mitaan ei muutettu."
  fi
  kirjaa_loki "PERUUTUS ALKAA prev=$(basename "$PREV")"
  laji "2/4 Vaihto (ajastimet pysaytettyna)"
  pysayta_ajastimet
  palvelut_vapaana
  if [ "$ASENTAJA" = kauppa-asenna ] && ct test -x "$ASENTAJAHAK/kauppa-palauta"; then
    local out; out=$(muuta "kauppa-palauta" ct "$ASENTAJAHAK/kauppa-palauta" 2>&1) || virhe "kauppa-palauta epaonnistui: $out"
    echo "$out" | tail -2 | sed 's/^/    /'
    asenna_yksikot || virhe "yksikoiden palautus epaonnistui"
  else
    muuta "koodin palautus" ct sh -c 'mv "$1" "$1.palautettu-$3" && { mv "$2" "$1" || { mv "$1.palautettu-$3" "$1"; exit 1; }; }' sh "$KOODI" "$PREV" "$TS" || virhe "koodin palautus epaonnistui (koodi ennallaan)"
    asenna_yksikot palauta || virhe "yksikoiden palautus epaonnistui"
  fi
  PERUUTUS_TEHTY=1
  laji "3/4 Jalkitarkistukset"
  if ct test -f "$KOODI/.julkaisu-manifesti"; then
    ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti' "$KOODI" >/dev/null || virhe "palautettu koodi ei vastaa manifestiaan"
    info "palautettu koodi vastaa manifestiaan."
  fi
  tarkista_tila_ennallaan "$TILA_ENNEN" "$KONFIG_ENNEN"
  savukoe || virhe "savukoe palautetulla koodilla epaonnistui (peruutus itse onnistui)"
  palauta_ajastimet
  laji "4/4 Valmis"
  kirjaa_loki "PERUUTUS OK koodi=$(basename "$PREV")"
  echo
  echo "PERUUTUS: seuraava peruutus palauttaisi uudelleen edellisen version; poistettu versio on $KOODI.palautettu-$TS."
  ok_loppu "$KOHDE: koodi palautettu ($PREV -> $KOODI); tila ja konfiguraatio ennallaan."
}

# ---- katastrofi: tila talteen ennen pct rollbackia -----------------------------------
snapshot_aika() {   # snapshot_aika <nimi> -> epoch tai tyhja
  local l rivi pvm kello
  l=$("$PCT" listsnapshot "$CT" 2>/dev/null || true)
  rivi=$(grep -E -- "-> $1 " <<< "$l" | head -1)
  pvm=$(awk '{for(i=1;i<=NF;i++) if ($i ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/) {print $i; exit}}' <<< "$rivi")
  kello=$(awk '{for(i=1;i<=NF;i++) if ($i ~ /^[0-9]{2}:[0-9]{2}:[0-9]{2}$/) {print $i; exit}}' <<< "$rivi")
  [ -n "$pvm" ] && [ -n "$kello" ] && date -d "$pvm $kello" +%s
}

katastrofi_tila_toimi() {
  T=$(mktemp -d "${TMPDIR:-/tmp}/julkaise.XXXXXX")
  laji "1/5 Esitarkistukset (vain luku)"
  [ "$KUIVA" = 1 ] && info "KUIVA-AJO: mitaan ei kopioida."
  tyokalut_isanta; ct_kaynnissa "$CT"; tyokalut_kontti
  [ -n "$SNAP_VALINTA" ] || { echo "Kohteen CT$CT snapshotit:"; "$PCT" listsnapshot "$CT" | sed 's/^/    /'; vika "anna palautettava snapshot: --snapshot NIMI"; }
  [[ "$SNAP_VALINTA" =~ ^[A-Za-z][A-Za-z0-9_-]{0,39}$ ]] || vika "snapshotin nimi ei kelpaa"
  snapshot_on "$SNAP_VALINTA" || vika "snapshotia '$SNAP_VALINTA' ei ole kohteella CT$CT"
  local epoch; epoch=$(snapshot_aika "$SNAP_VALINTA") || true
  [[ "$epoch" =~ ^[0-9]+$ ]] || vika "snapshotin aikaa ei saatu selville"
  info "snapshot $SNAP_VALINTA otettu $(date -d "@$epoch" '+%F %T')."
  local s p aktiivinen=""
  for p in $PALVELUT; do s=$(ct systemctl is-active "$p.service" 2>/dev/null || true); case "$s" in inactive|failed|"") ;; *) aktiivinen="$aktiivinen $p" ;; esac; done
  [ -z "$aktiivinen" ] || varoita "palvelut kaynnissa:$aktiivinen. Kopio otetaan silti (varmuuskopio on parempi kuin ei mitaan), mutta tietokannat voivat olla epajohdonmukaisia."
  local kohdekansio="$JH/katastrofi/$KOHDE-$TS"
  local tilaa_tarvitaan; tilaa_tarvitaan=$(ct du -sk $TILA 2>/dev/null | awk '{s+=$1} END{print s+0}')
  local vapaa_host vapaa_ct
  vapaa_host=$(df -Pk "$(dirname "$JH")" 2>/dev/null | awk 'NR==2{print $4}'); vapaa_ct=$(ct df -Pk /tmp 2>/dev/null | awk 'NR==2{print $4}')
  [[ "$vapaa_host" =~ ^[0-9]+$ ]] && [ "$vapaa_host" -gt $((tilaa_tarvitaan * 2 + 10240)) ] || vika "isannalla ei ole tarpeeksi levytilaa tilan kopioon (tila ${tilaa_tarvitaan} kB)"
  [[ "$vapaa_ct" =~ ^[0-9]+$ ]] && [ "$vapaa_ct" -gt $((tilaa_tarvitaan + 10240)) ] || vika "kontin /tmp:ssa ei ole tarpeeksi tilaa (tila ${tilaa_tarvitaan} kB)"
  info "tilan koko ${tilaa_tarvitaan} kB; levytilaa isanta ${vapaa_host} kB, kontti /tmp ${vapaa_ct} kB."

  laji "2/5 Mita palautus tuhoaisi (vain luku)"
  RAPORTTI="$T/raportti.txt"
  ct python3 -c 'import os, sys, time
epoch = int(sys.argv[1]); koodi = sys.argv[2]; tilat = sys.argv[3].split(); konfig = sys.argv[4].split()
def uudet(polut):
    n = 0; koko = 0; lista = []; uusia = []
    for p in polut:
        for kansio, _, tiedostot in os.walk(p):
            for f in tiedostot:
                fp = os.path.join(kansio, f)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if st.st_mtime > epoch:
                    n += 1; koko += st.st_size; lista.append((st.st_size, fp, st.st_ctime > epoch and st.st_mtime >= st.st_ctime - 1))
    return n, koko, sorted(lista, reverse=True)
n, koko, lista = uudet(tilat)
print("TILA: %d tiedostoa muuttunut tai syntynyt snapshotin jalkeen (%.1f Mt) - kaikki nama TUHOUTUISIVAT rollbackissa:" % (n, koko / 1048576.0))
for s, fp, _ in lista[:15]:
    print("   %9d t  %s" % (s, fp))
if n > 15:
    print("   ... ja %d muuta" % (n - 15))
n2, _, lista2 = uudet(konfig)
print("KONFIGURAATIO: %d tiedostoa muuttunut snapshotin jalkeen (rollback palauttaisi vanhat sisallot; sisaltoja ei kopioida, koska ne voivat olla salaisuuksia):" % n2)
for s, fp, _ in lista2[:15]:
    print("   %s" % fp)
rel = []
base = koodi.rstrip("/")
d = os.path.dirname(base); nimi = os.path.basename(base)
for e in sorted(os.listdir(d)):
    if e == nimi or e.startswith(nimi + "."):
        fp = os.path.join(d, e)
        try:
            if os.lstat(fp).st_mtime > epoch:
                rel.append(e)
        except OSError:
            pass
print("KOODI: %d koodihakemistoa luotu tai muuttunut snapshotin jalkeen: %s" % (len(rel), ", ".join(rel) if rel else "ei yhtaan"))
' "$epoch" "$KOODI" "$TILA" "$KONFIG" > "$RAPORTTI" 2>&1 || vika "analyysi epaonnistui"
  sed 's/^/    /' "$RAPORTTI"
  if [ "$KUIVA" = 1 ]; then
    ok_loppu "KUIVA-AJO: tilaa ei kopioitu; ylla nakyy, mita palautus tuhoaisi."
  fi

  laji "3/5 Tilan kopiointi hostille"
  mkdir -p "$kohdekansio" && chmod 700 "$JH" "$JH/katastrofi" "$kohdekansio" || vika "kohdekansion luonti epaonnistui"
  local ktgz="/tmp/katastrofi-$KOHDE-$TS.tgz"
  MUUTOKSIA=$((MUUTOKSIA + 1))
  ct sh -c 'o="$0"; n=$#; i=0; while [ "$i" -lt "$n" ]; do p="$1"; shift; set -- "$@" "${p#/}"; i=$((i + 1)); done; tar czf "$o" --numeric-owner -p -C / "$@"' "$ktgz" $TILA || { rm -rf "$kohdekansio"; vika "tilan pakkaus epaonnistui"; }
  "$PCT" pull "$CT" "$ktgz" "$kohdekansio/tila.tgz" || { rm -rf "$kohdekansio"; vika "tilan siirto isannalle epaonnistui"; }
  local ksha_ct ksha_host
  ksha_ct=$(ct sha256sum "$ktgz" | cut -d' ' -f1); ksha_host=$(sha256sum "$kohdekansio/tila.tgz" | cut -d' ' -f1)
  ct rm -f "$ktgz" >/dev/null 2>&1 || true
  [ "$ksha_ct" = "$ksha_host" ] || { rm -rf "$kohdekansio"; vika "kopion sha256 ei tasmaa kontin ja isannan valilla"; }
  tiiviste_polut $TILA > "$kohdekansio/tila.tiiviste"
  ct sh -c 'for p in "$@"; do find "$p" -xdev -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum; done' sh $TILA > "$kohdekansio/tila-manifesti.txt"
  echo "$ksha_host  tila.tgz" > "$kohdekansio/tila.tgz.sha256"
  cp "$RAPORTTI" "$kohdekansio/raportti.txt"
  local akt_teksti="${aktiivinen# }"; akt_teksti="${akt_teksti:-ei}"
  { echo "kohde=$KOHDE"; echo "snapshot=$SNAP_VALINTA"; echo "aika=$(date '+%F %T')"; echo "tila=$TILA"; echo "palvelut_kaynnissa=${akt_teksti}"; } > "$kohdekansio/tiedot.txt"
  tar tzf "$kohdekansio/tila.tgz" >/dev/null || vika "kopioitu arkisto ei ole luettavissa"
  local tn mn; tn=$(tar tzf "$kohdekansio/tila.tgz" | grep -vc '/$'); mn=$(wc -l < "$kohdekansio/tila-manifesti.txt")
  [ "$tn" = "$mn" ] || vika "arkiston tiedostomaara ($tn) ei vastaa manifestia ($mn)"
  chmod -R go-rwx "$kohdekansio"
  info "kopioitu: $kohdekansio ($tn tiedostoa, sha256 ${ksha_host:0:16}...)."
  kirjaa_loki "KATASTROFI-TILA kopio=$kohdekansio snapshot=$SNAP_VALINTA tiedostoja=$tn"

  laji "4/5 Seuraavat askeleet (EI suoritettu)"
  echo "  1. Rollback (TUHOAA ylla listatut muutokset): pct rollback $CT $SNAP_VALINTA"
  echo "  2. Palauta tila kopiosta (vain tilakansio, koodi ja konfiguraatio jaavat snapshotin mukaisiksi):"
  echo "     julkaise.sh $KOHDE --katastrofi-palauta $kohdekansio"
  laji "5/5 Valmis"
  ok_loppu "$KOHDE: tila kopioitu ($tn tiedostoa) kansioon $kohdekansio; pct rollbackia EI ajettu. Palautus tuhoaisi: ks. raportti ylla."
}

katastrofi_palauta_toimi() {
  T=$(mktemp -d "${TMPDIR:-/tmp}/julkaise.XXXXXX")
  laji "1/4 Esitarkistukset (vain luku)"
  [ "$KUIVA" = 1 ] && info "KUIVA-AJO: mitaan ei palauteta."
  tyokalut_isanta; ct_kaynnissa "$CT"; tyokalut_kontti
  local k="$KATASTROFI_KANSIO"
  [ -n "$k" ] || vika "anna kansio: --katastrofi-palauta <kansio>"
  k=$(readlink -f "$k" 2>/dev/null || echo "$k")
  case "$k" in "$JH/katastrofi/$KOHDE-"*) ;; *) vika "kansion pitaa olla $JH/katastrofi/$KOHDE-..." ;; esac
  [ -d "$k" ] && [ -f "$k/tila.tgz" ] && [ -f "$k/tila.tgz.sha256" ] && [ -f "$k/tila-manifesti.txt" ] || vika "kansiosta puuttuu tila.tgz, sha256 tai manifesti"
  [ "$(stat -c %U "$k")" = root ] || [ "$PCT" != pct ] || vika "kansion omistajan pitaa olla root"
  ( cd "$k" && sha256sum -c --quiet tila.tgz.sha256 ) >/dev/null 2>&1 || vika "kopion sha256 ei tasmaa (arkisto vioittunut?)"
  info "kopio $k: sha256 tasmaa."
  local p s
  for p in $PALVELUT; do s=$(ct systemctl is-active "$p.service" 2>/dev/null || true); case "$s" in inactive|failed|"") ;; *) vika "palvelu $p.service on '$s': pysayta ensin" ;; esac; done
  for p in $AJASTIMET; do [ "$(ct systemctl is-active "$p" 2>/dev/null || true)" = active ] && varoita "ajastin $p on aktiivinen: pysayta se ennen palautusta, jotta mikaan ei kirjoita tilaan"; done
  local nyt; nyt=$(tiiviste_polut $TILA)
  info "nykyisen tilan tiiviste ${nyt:0:16}..."
  if [ "$KUIVA" = 1 ]; then ok_loppu "KUIVA-AJO: palautus tehtaisiin kopiosta $k; nykyinen tila siirrettaisiin sivuun (.ennen-palautusta-$TS); mitaan ei muutettu."; fi
  kirjaa_loki "KATASTROFI-PALAUTUS ALKAA kopio=$k"
  laji "2/4 Palautus"
  local kpaketti="/tmp/katastrofi-palautus-$KOHDE-$TS.tgz"
  muuta "arkisto kontille" "$PCT" push "$CT" "$k/tila.tgz" "$kpaketti" --perms 600 || virhe "arkiston siirto kontille epaonnistui"
  # puretaan valiaikaiseen juureen, sijoitetaan vasta tarkistuksen jalkeen; nykyinen tila sailytetaan sivussa
  muuta "palautus" ct sh -c 'set -e
arkisto="$0"; ts="$1"; shift 2
t=$(mktemp -d /var/tmp/katastrofi-palautus.XXXXXX)
tar xzf "$arkisto" -C "$t" --numeric-owner -p
for p in "$@"; do
  r="$t$p"
  [ -e "$r" ] || { echo "arkistosta puuttuu $p"; rm -rf "$t"; exit 1; }
done
for p in "$@"; do
  if [ -e "$p" ]; then mv "$p" "$p.ennen-palautusta-$ts"; fi
  mv "$t$p" "$p"
done
rm -rf "$t" "$arkisto"' "$kpaketti" "$TS" x $TILA || virhe "palautus epaonnistui (nykyinen tila sailytetty sivussa .ennen-palautusta-$TS)"
  laji "3/4 Jalkitarkistukset"
  local jalki odotettu; jalki=$(tiiviste_polut $TILA)
  odotettu=$(cat "$k/tila.tiiviste")
  [ "$jalki" = "$odotettu" ] || virhe "palautettu tila ei vastaa kopion tiivistetta (${jalki:0:12} != ${odotettu:0:12}); sivuun siirretty tila: *.ennen-palautusta-$TS"
  info "palautettu tila vastaa kopion tiivistetta (${jalki:0:16}...)."
  laji "4/4 Valmis"
  kirjaa_loki "KATASTROFI-PALAUTUS OK kopio=$k"
  ok_loppu "$KOHDE: tila palautettu kopiosta $k; rollbackin jalkeinen tila sailytettiin hakemistoissa *.ennen-palautusta-$TS."
}

tila_toimi() {
  T=$(mktemp -d "${TMPDIR:-/tmp}/julkaise.XXXXXX")
  tyokalut_isanta; ct_kaynnissa "$CT"; tyokalut_kontti
  echo "kohde: $KOHDE (CT$CT)   koodi: $KOODI   tila: $TILA   konfiguraatio: ${KONFIG:-ei}"
  echo "julkaisu: $(ct sh -c 'sed -n "s/^commit=//p;s/^aika=/aika /p" "$0/.julkaisu-tieto" 2>/dev/null | tr "\n" " "' "$KOODI" || true)"
  if ct test -f "$KOODI/.julkaisu-manifesti"; then
    if ct sh -c 'cd "$0" && sha256sum -c --quiet .julkaisu-manifesti >/dev/null 2>&1' "$KOODI"; then echo "koodin eheys: ok (vastaa manifestia)"; else echo "koodin eheys: POIKKEAA MANIFESTISTA"; fi
  else echo "koodin eheys: ei manifestia (ensijulkaisu tekematta)"; fi
  echo "prev-versiot:"; ct sh -c 'ls -d "$0".prev-* 2>/dev/null | LC_ALL=C sort -r' "$KOODI" | sed 's/^/    /'
  echo "snapshotteja: $(snapshot_maara) / $SNAPSHOT_RAJA"
  local p; for p in $PALVELUT; do echo "palvelu $p: $(ct systemctl is-active "$p.service" 2>/dev/null || true)"; done
  for p in $AJASTIMET; do echo "ajastin $p: $(ct systemctl is-active "$p" 2>/dev/null || true) / $(ct systemctl is-enabled "$p" 2>/dev/null || true)"; done
  echo "tilan tiiviste: $(tiiviste_polut $TILA)"
  ok_loppu "$KOHDE: tila luettu (vain luku)."
}

itsetesti_toimi() {
  tyokalut_isanta_ilman_ct() { local t; for t in git tar gzip sha256sum flock find sort awk bash; do command -v "$t" >/dev/null 2>&1 || { echo "puuttuu: $t"; return 1; }; done; }
  tyokalut_isanta_ilman_ct || epa_loppu "isannalta puuttuu tyokaluja"
  info "isanta: $(hostname); bash ${BASH_VERSION%%(*}; git $(git --version | awk '{print $3}')"
  local f n=0 kohteet=""
  for f in "$JH"/*.conf; do
    [ -f "$f" ] || continue
    local nimi; nimi=$(basename "$f" .conf)
    ( lataa_konf "$nimi" ) >/dev/null 2>&1 || ( lataa_konf "$nimi" 2>&1 | tail -3; exit 1 ) || epa_loppu "konfiguraatio $nimi.conf ei kelpaa"
    kohteet="$kohteet $nimi"; n=$((n + 1))
    info "konfiguraatio $nimi.conf: ok (sha256 $(sha256sum "$f" | cut -c1-16)...)"
  done
  [ "$n" -gt 0 ] || epa_loppu "konfiguraatioita ei loydy kansiosta $JH"
  info "julkaise.sh sha256 $(sha256sum "$0" | cut -c1-16)..."
  ok_loppu "itsetesti lapaisty: $n konfiguraatiota:$kohteet"
}

# ---- paaohjelma -------------------------------------------------------------------
if [ "$TOIMI" = itsetesti ]; then itsetesti_toimi; fi
[ -n "$KOHDE" ] || { kaytto; exit 2; }
lataa_konf "$KOHDE"
case "$TOIMI" in
  julkaise) julkaise_toimi ;;
  peruuta) [ "${#POS[@]}" -eq 0 ] || { echo "--peruuta ei ota muita argumentteja"; exit 2; }; peruuta_toimi ;;
  katastrofi-tila) katastrofi_tila_toimi ;;
  katastrofi-palauta) katastrofi_palauta_toimi ;;
  tila) tila_toimi ;;
esac
