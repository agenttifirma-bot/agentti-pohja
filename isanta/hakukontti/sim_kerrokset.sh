#!/bin/bash
# Kahden kerroksen verkkosimulaatio (vain testit, test_wireguard.py). Ajetaan omassa kayttaja- ja verkkonimiavaruudessa:
#   unshare -rn bash sim_kerrokset.sh HAKEMISTO
# HAKEMISTO sisaltaa: isanta.nft (taytetty isannan taulu), kontti.nft (kontin palomuuri, kayttajat numeroina) ja
# sim_apu.py. Ymparisto: IPT (iptables-legacy-komento), LAN_IP, TS_ISANTA, TS_VERTAINEN, TS_VERKKO (rakennetaan
# testissa numeroista). Osoitteet ovat dokumentaatio- ja testialueilta (RFC 5737, RFC 2544), eivat infran osoitteita.
#
# Topologia (juurinimiavaruus = isanta):
#   kontti123 eth0 198.18.0.3 -- vmbr3 (silta, 198.18.0.1) isanta vmbr0 198.51.100.1 -- 198.51.100.2 ulko
#   isanta tailscale0 (TS_ISANTA) -- TS_VERTAINEN tailnet-vertainen
#   kontti123 wg0 192.0.2.2 -- 192.0.2.1 ulko (simuloitu VPN-tunneli; salaus ei kuulu testiin)
#   ulko: WireGuard-palvelin 203.0.113.10, verkkopalvelin 203.0.113.80, lahiverkon laite LAN_IP
# Tulosrivit: "TULOS nimi arvo". Testi vertaa niita odotettuihin.
set -u
H=$1
APU="python3 -I $H/sim_apu.py"
read -r -a IPTK <<< "$IPT"
export XTABLES_LOCKFILE="$H/xtables.lock"
LOKI_ULKO="$H/ulko.loki"
LOKI_TS="$H/ts.loki"
: > "$LOKI_ULKO"; : > "$LOKI_TS"

pids=()
lopeta() { kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null; }
trap lopeta EXIT

uusi_ns() {
	unshare -n sleep 900 >/dev/null 2>&1 &
	local p=$!
	pids+=("$p")
	for _ in $(seq 50); do
		[ "$(readlink "/proc/$p/ns/net")" != "$(readlink /proc/self/ns/net)" ] && break
		sleep 0.05
	done
	echo "$p"
}
n() { local p=$1; shift; nsenter -t "$p" -n -- "$@"; }
tulos() { echo "TULOS $1 $2"; }

CT=$(uusi_ns); ULKO=$(uusi_ns); TS=$(uusi_ns)
# uusi_ns ajetaan alikuoressa, joten prosessit lisataan lopetuslistaan tassa.
pids+=("$CT" "$ULKO" "$TS")

ip link set lo up
ip link add name vmbr3 type bridge
ip addr add 198.18.0.1/24 dev vmbr3
ip link set vmbr3 up
ip link add name veth123 type veth peer name eth0 netns "$CT"
ip link set veth123 master vmbr3 up
ip link add name vmbr0 type veth peer name e0 netns "$ULKO"
ip addr add 198.51.100.1/24 dev vmbr0
ip link set vmbr0 up
ip link add name tailscale0 type veth peer name t0 netns "$TS"
ip addr add "$TS_ISANTA/24" dev tailscale0
ip link set tailscale0 up
ip route add default via 198.51.100.2
# Kuten isannalla: ip_forward=0, reititys vain liitannoittain (tailscale0 mukana, jotta Tailscalen reititys mitataan).
echo 0 > /proc/sys/net/ipv4/ip_forward
for l in vmbr3 vmbr0 tailscale0; do echo 1 > "/proc/sys/net/ipv4/conf/$l/forwarding"; done

n "$CT" ip link set lo up
n "$CT" ip addr add 198.18.0.3/24 dev eth0
n "$CT" ip link set eth0 up
n "$CT" ip link add name wg0 type veth peer name tun0 netns "$ULKO"
n "$CT" ip addr add 192.0.2.2/30 dev wg0
n "$CT" ip link set wg0 up
# Kuten wg-quick: kaikki wg0:aan, paitsi WireGuard-palvelin eth0:n kautta. Varareitti eth0:aan mallintaa tilannetta,
# jossa wg0 on alhaalla (liikenne yrittaisi eth0:aan, ja kill switch estaa sen).
n "$CT" ip route add 203.0.113.10/32 via 198.18.0.1 dev eth0
n "$CT" ip route add default via 192.0.2.1 dev wg0 metric 10
n "$CT" ip route add default via 198.18.0.1 dev eth0 metric 100

n "$ULKO" ip link set lo up
n "$ULKO" ip addr add 198.51.100.2/24 dev e0
n "$ULKO" ip link set e0 up
n "$ULKO" ip addr add 192.0.2.1/30 dev tun0
n "$ULKO" ip link set tun0 up
n "$ULKO" ip link add name d0 type dummy
n "$ULKO" ip addr add 203.0.113.10/32 dev d0
n "$ULKO" ip addr add 203.0.113.80/32 dev d0
n "$ULKO" ip addr add "$LAN_IP/32" dev d0
n "$ULKO" ip link set d0 up
n "$ULKO" ip route add 198.18.0.0/24 via 198.51.100.1
n "$ULKO" ip route add "$TS_VERKKO" via 198.51.100.1

n "$TS" ip link set lo up
n "$TS" ip addr add "$TS_VERTAINEN/24" dev t0
n "$TS" ip link set t0 up
n "$TS" ip route add default via "$TS_ISANTA"

n "$ULKO" $APU kuuntele "$LOKI_ULKO" tcp:443 tcp:22 tcp:80 udp:51820 udp:51821 udp:53 >/dev/null 2>&1 &
pids+=("$!")
n "$TS" $APU kuuntele "$LOKI_TS" tcp:80 >/dev/null 2>&1 &
pids+=("$!")
for _ in $(seq 100); do grep -q valmis "$LOKI_ULKO" && grep -q valmis "$LOKI_TS" && break; sleep 0.05; done

# Isannan kerrokset: Tailscalen iptables-legacy-saannot (kuten tailscaled ne luo) ja oma nft-taulu.
"${IPTK[@]}" -N ts-forward && "${IPTK[@]}" -A FORWARD -j ts-forward \
	&& "${IPTK[@]}" -A ts-forward -i tailscale0 -j MARK --set-xmark 0x40000/0xff0000 \
	&& "${IPTK[@]}" -A ts-forward -m mark --mark 0x40000/0xff0000 -j ACCEPT \
	&& "${IPTK[@]}" -A ts-forward -s 100.64.0.0/10 -o tailscale0 -j DROP \
	&& "${IPTK[@]}" -A ts-forward -o tailscale0 -j ACCEPT \
	&& "${IPTK[@]}" -t nat -N ts-postrouting && "${IPTK[@]}" -t nat -A POSTROUTING -j ts-postrouting \
	&& "${IPTK[@]}" -t nat -A ts-postrouting -m mark --mark 0x40000/0xff0000 -j MASQUERADE
tulos legacy_ladattu $?
nft -f "$H/isanta.nft"
tulos isanta_nft_ladattu $?

ts_nat() { "${IPTK[@]}" -t nat -L ts-postrouting -v -n -x | awk '/MASQUERADE/ {print $1; exit}'; }
lahettajat() { grep -c "^$1 $2 $3\$" "$LOKI_ULKO"; }

# Vaihe A: vain isannan kerros (kontin palomuuria ei ole viela, kuten asennuksen alussa).
tulos A_wg_udp "$(n "$CT" $APU udp 203.0.113.10 51820)"
tulos A_wg_vaara_portti "$(n "$CT" $APU udp 203.0.113.10 51821)"
n "$CT" ip link set wg0 down
tulos A_tcp_443_ilman_asennusta "$(n "$CT" $APU tcp 203.0.113.80 443)"
nft add element inet aivo_hakuverkko asennus "{ 198.18.0.3 timeout 10m }"
tulos A_tcp_443_asennus "$(n "$CT" $APU tcp 203.0.113.80 443)"
tulos A_tcp_22_asennus "$(n "$CT" $APU tcp 203.0.113.80 22)"
tulos A_lan_asennus "$(n "$CT" $APU tcp "$LAN_IP" 80)"
tulos A_tailnet_asennus "$(n "$CT" $APU tcp "$TS_VERTAINEN" 80)"
tulos A_isanta "$(n "$CT" $APU tcp 198.18.0.1 22)"
nft delete element inet aivo_hakuverkko asennus "{ 198.18.0.3 }"
tulos A_tcp_443_asennus_poistettu "$(n "$CT" $APU tcp 203.0.113.80 443)"
sleep 0.5
tulos A_wg_lahettaja_isanta "$(lahettajat udp 51820 198.51.100.1)"
tulos A_wg_vaara_portti_perilla "$(grep -c '^udp 51821 ' "$LOKI_ULKO")"
tulos A_ts_nat_ennen "$(ts_nat)"
# Tailscalen oma reititys: tailnet-vertainen internetiin (ts-forward + ts-postrouting) toimii nft-taulun rinnalla.
tulos A_tailnet_internetiin "$(n "$TS" $APU tcp 203.0.113.80 443)"
tulos A_ts_nat_jalkeen "$(ts_nat)"
tulos A_tailnet_lahettaja_isanta "$(lahettajat tcp 443 198.51.100.1)"
tulos A_tailnet_konttiin "$(n "$TS" $APU tcp 198.18.0.3 80)"
tulos A_kotiverkko_tailnetiin "$(n "$ULKO" $APU tcp "$TS_VERTAINEN" 80)"
tulos A_kotiverkko_konttiin "$(n "$ULKO" $APU tcp 198.18.0.3 80)"
tulos A_laskuri_lahiverkko "$(nft list table inet aivo_hakuverkko | grep 'ei lahiverkkoon' | sed -n 's/.*packets \([0-9]*\).*/\1/p')"
tulos A_laskuri_isanta "$(nft list table inet aivo_hakuverkko | grep 'silta ei paase isantaan' | sed -n 's/.*packets \([0-9]*\).*/\1/p')"

# Vaihe B: kontin palomuuri (kill switch) paalle. Kayttaja debian-tor on simulaatiossa root (uid 0), koska
# nimiavaruudessa on vain yksi kayttaja.
n "$CT" ip link set wg0 up
n "$CT" ip route replace default via 192.0.2.1 dev wg0 metric 10
n "$CT" nft -f "$H/kontti.nft"
tulos B_kontti_nft_ladattu $?
: > "$LOKI_ULKO.b"
tulos B_udp_ilman_merkkia "$(n "$CT" $APU udp 203.0.113.10 51820)"
tulos B_wg_merkitty "$(n "$CT" $APU udp 203.0.113.10 51820 0xca6c)"
tulos B_wg_merkitty_vaara_portti "$(n "$CT" $APU udp 203.0.113.10 51821 0xca6c)"
tulos B_wg_merkitty_vaara_osoite "$(n "$CT" $APU udp 203.0.113.80 51820 0xca6c)"
tulos B_tor_wg0 "$(n "$CT" $APU tcp 203.0.113.80 443)"
tulos B_tor_udp_wg0 "$(n "$CT" $APU udp 203.0.113.80 53)"
tulos B_tor_lan "$(n "$CT" $APU tcp "$LAN_IP" 80)"
sleep 0.5
tulos B_tunnelin_lahettaja "$(lahettajat tcp 443 192.0.2.2)"
eth0_esto() { n "$CT" nft list chain inet hakukontti output | grep 'eth0: vain WireGuard' | sed -n 's/.*packets \([0-9]*\).*/\1/p'; }
isanta_muu() { nft list table inet aivo_hakuverkko | grep 'muu sillasta ulos' | sed -n 's/.*packets \([0-9]*\).*/\1/p'; }
ennen=$(eth0_esto)
isanta_ennen=$(isanta_muu)
data_ennen=$(grep -c '^data 443 ' "$LOKI_ULKO")
tulos B_vuoto "$(n "$CT" $APU vuoto 203.0.113.80 443 wg0)"
tulos B_vuoto_esto_kasvoi "$([ "$(eth0_esto)" -gt "$ennen" ] && echo kylla || echo ei)"
# Isannan laskuri: jos kontista lahtisi paketti eth0:aan, isanta hylkaisi sen (lahdeosoite ei ole kontin 123).
tulos B_vuoto_isannalle "$(( $(isanta_muu) - isanta_ennen ))"
tulos B_vuoto_data_perilla "$(( $(grep -c '^data 443 ' "$LOKI_ULKO") - data_ennen ))"
nft add element inet aivo_hakuverkko asennus "{ 198.18.0.3 timeout 10m }"
tulos B_wg0_alhaalla_tcp "$(n "$CT" $APU tcp 203.0.113.80 443)"
tulos B_wg0_alhaalla_dns "$(n "$CT" $APU udp 9.9.9.9 53)"
tulos valmis 0
