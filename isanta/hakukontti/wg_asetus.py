#!/usr/bin/env python3
"""WireGuard-asetuksen (wg0.conf) tarkistus ja palomuurin osoitteet hakukonttia varten. Ohje: docs/aivo-hakukontti.md.

Ajetaan Proxmox-isannalla rootina asennuksen aikana. Ohjelma ei koskaan tulosta avaimia: tulosteessa on vain
palvelimen osoite, portti ja virheiden tunnisteet. Kaikki toiminnot lukevat tiedoston itse, joten avainta ei tarvitse
kopioida komentoriville.

Alikomennot:
  tarkista TIEDOSTO                 tarkistaa vaatimukset (yksi palvelin, IPv4-Endpoint, ei DNS:aa, ei IPv6:ta,
                                    ei komentokoukkuja, FwMark puuttuu tai on 51820). Paluuarvo 0 = OK, 1 = virhe.
  siivoa SISAAN ULOS                kirjoittaa Mullvadin tiedostosta version ilman DNS-rivia ja IPv6-osoitteita
                                    (tila 600). Ei tulosta sisaltoa.
  nft TIEDOSTO                      tulostaa kontin palomuurin maarittelyt WG_PALVELIN ja WG_PORTTI.
  isanta TIEDOSTO --mall M --pohja P --asetukset A
                                    tulostaa isannan taulun (pohja M) taytettyna: osoitteet asetustiedostosta A,
                                    kielletyt alueet kontin palomuuripohjasta P ja WireGuard-palvelin tiedostosta.
"""
import argparse
import ipaddress
import os
import re
import sys

FWMARK = 51820
SALLITUT_INTERFACE = {"privatekey", "address", "listenport", "fwmark", "mtu", "table"}
SALLITUT_PEER = {"publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive"}
KOUKUT = {"preup", "postup", "predown", "postdown", "saveconfig"}
ASETUKSET_AVAIMET = ("SILTA", "SISASILTA", "IP122", "IP123")
NIMI_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


class AsetusVirhe(Exception):
    """Virheen tunniste on args[0]. Viestissa ei ole tiedoston sisaltoa."""


def jasenna(teksti):
    """Palauttaa listan osioista: (nimi, [(avain_pienella, arvo, alkuperainen_rivi)])."""
    osiot = []
    for rivi in teksti.splitlines():
        puhdas = rivi.split("#", 1)[0].strip()
        if not puhdas:
            continue
        if puhdas.startswith("[") and puhdas.endswith("]"):
            osiot.append((puhdas[1:-1].strip().lower(), []))
            continue
        if "=" not in puhdas or not osiot:
            raise AsetusVirhe("rivi_ei_kelpaa")
        avain, arvo = puhdas.split("=", 1)
        osiot[-1][1].append((avain.strip().lower(), arvo.strip(), rivi))
    return osiot


def _arvot(rivit, avain):
    return [a for k, a, _ in rivit if k == avain]


def _lista(arvo):
    return [o.strip() for o in arvo.split(",") if o.strip()]


def tarkista(teksti):
    """Palauttaa (palvelin, portti). Nostaa AsetusVirhe-poikkeuksen, jos tiedosto ei tayta vaatimuksia."""
    osiot = jasenna(teksti)
    interface = [r for n, r in osiot if n == "interface"]
    peer = [r for n, r in osiot if n == "peer"]
    if len(interface) != 1 or any(n not in ("interface", "peer") for n, _ in osiot):
        raise AsetusVirhe("osiot")
    if len(peer) != 1:
        raise AsetusVirhe("peer_maara")
    iface, pr = interface[0], peer[0]
    for k, _, _ in iface + pr:
        if k in KOUKUT:
            raise AsetusVirhe("komentokoukku")
        if k == "dns":
            raise AsetusVirhe("dns_rivi")
    if any(k not in SALLITUT_INTERFACE for k, _, _ in iface) or any(k not in SALLITUT_PEER for k, _, _ in pr):
        raise AsetusVirhe("tuntematon_avain")
    if len(_arvot(iface, "privatekey")) != 1 or len(_arvot(pr, "publickey")) != 1:
        raise AsetusVirhe("avain_puuttuu")
    osoitteet = sum((_lista(a) for a in _arvot(iface, "address")), [])
    if not osoitteet:
        raise AsetusVirhe("address_puuttuu")
    for o in osoitteet:
        try:
            verkko = ipaddress.ip_interface(o)
        except ValueError:
            raise AsetusVirhe("address_ei_kelpaa") from None
        if verkko.version != 4:
            raise AsetusVirhe("ipv6_osoite")
    sallitut = sum((_lista(a) for a in _arvot(pr, "allowedips")), [])
    try:
        sallitut_verkot = [ipaddress.ip_network(a, strict=False) for a in sallitut]
    except ValueError:
        raise AsetusVirhe("allowedips_ei_kelpaa") from None
    if any(v.version != 4 for v in sallitut_verkot):
        raise AsetusVirhe("ipv6_allowedips")
    if sallitut_verkot != [ipaddress.ip_network("0.0.0.0/0")]:
        raise AsetusVirhe("allowedips_ei_kaikki")
    merkki = _arvot(iface, "fwmark")
    if merkki and (len(merkki) != 1 or merkki[0].lower() not in (str(FWMARK), hex(FWMARK))):
        raise AsetusVirhe("fwmark")
    taulu = _arvot(iface, "table")
    if taulu and taulu != ["auto"]:
        raise AsetusVirhe("table")
    endpoint = _arvot(pr, "endpoint")
    if len(endpoint) != 1:
        raise AsetusVirhe("endpoint_puuttuu")
    m = re.match(r"^([0-9.]+):([0-9]{1,5})$", endpoint[0])
    if not m:
        raise AsetusVirhe("endpoint_ei_ipv4")
    try:
        palvelin = ipaddress.IPv4Address(m.group(1))
    except ValueError:
        raise AsetusVirhe("endpoint_ei_ipv4") from None
    portti = int(m.group(2))
    if not 1 <= portti <= 65535:
        raise AsetusVirhe("endpoint_portti")
    if not palvelin.is_global:
        raise AsetusVirhe("endpoint_ei_julkinen")
    return str(palvelin), portti


def siivoa(teksti):
    """Poistaa DNS-rivit ja IPv6-osoitteet (Address, AllowedIPs). Muut rivit sailyvat sellaisinaan."""
    ulos = []
    for rivi in teksti.splitlines():
        puhdas = rivi.split("#", 1)[0].strip()
        avain = puhdas.split("=", 1)[0].strip().lower() if "=" in puhdas else ""
        if avain == "dns":
            continue
        if avain in ("address", "allowedips"):
            nimi = puhdas.split("=", 1)[0].strip()
            jaljella = [o for o in _lista(puhdas.split("=", 1)[1]) if ":" not in o]
            if not jaljella:
                continue
            rivi = "%s = %s" % (nimi, ", ".join(jaljella))
        ulos.append(rivi)
    return "\n".join(ulos) + "\n"


def lue(polku):
    with open(polku, encoding="utf-8") as f:
        return f.read()


def kirjoita_600(polku, teksti):
    fd = os.open(polku, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(teksti)


def nft_maaritykset(palvelin, portti):
    return "define WG_PALVELIN = %s\ndefine WG_PORTTI = %d\n" % (palvelin, portti)


def lue_asetukset(teksti):
    arvot = {}
    for rivi in teksti.splitlines():
        if "=" in rivi and not rivi.lstrip().startswith("#"):
            k, v = rivi.split("=", 1)
            arvot[k.strip()] = v.strip()
    puuttuvat = [k for k in ASETUKSET_AVAIMET if not arvot.get(k)]
    if puuttuvat:
        raise AsetusVirhe("asetus_puuttuu_" + puuttuvat[0])
    for k in ("SILTA", "SISASILTA"):
        if not NIMI_RE.match(arvot[k]):
            raise AsetusVirhe("asetus_nimi_" + k)
    for k in ("IP122", "IP123"):
        try:
            ipaddress.IPv4Address(arvot[k])
        except ValueError:
            raise AsetusVirhe("asetus_osoite_" + k) from None
    return arvot


def kielletyt4(pohja_teksti):
    m = re.search(r"^define KIELLETYT4 = \{ (.*) \}$", pohja_teksti, re.MULTILINE)
    if not m:
        raise AsetusVirhe("kielletyt4_puuttuu")
    verkot = [str(ipaddress.IPv4Network(o.strip())) for o in m.group(1).split(",")]
    return ", ".join(verkot)


def tayta_isanta(mall, asetukset, palvelin, portti, kielletyt):
    arvot = {"SILTA": asetukset["SILTA"], "SISASILTA": asetukset["SISASILTA"], "IP122": asetukset["IP122"],
             "IP123": asetukset["IP123"], "WG_PALVELIN": palvelin, "WG_PORTTI": str(portti), "KIELLETYT4": kielletyt}
    tulos = re.sub(r"%([A-Z0-9_]+)%", lambda m: arvot[m.group(1)] if m.group(1) in arvot else m.group(0), mall)
    jaljella = re.findall(r"%[A-Z0-9_]+%", tulos)
    if jaljella:
        raise AsetusVirhe("paikkamerkki_jai")
    return tulos


def main(argv=None):
    p = argparse.ArgumentParser(description="WireGuard-asetuksen tarkistus hakukonttia varten (ei tulosta avaimia).")
    ali = p.add_subparsers(dest="komento", required=True)
    t = ali.add_parser("tarkista")
    t.add_argument("tiedosto")
    s = ali.add_parser("siivoa")
    s.add_argument("sisaan")
    s.add_argument("ulos")
    n = ali.add_parser("nft")
    n.add_argument("tiedosto")
    i = ali.add_parser("isanta")
    i.add_argument("tiedosto")
    i.add_argument("--mall", required=True)
    i.add_argument("--pohja", required=True)
    i.add_argument("--asetukset", required=True)
    a = p.parse_args(argv)
    try:
        if a.komento == "siivoa":
            puhdas = siivoa(lue(a.sisaan))
            palvelin, portti = tarkista(puhdas)
            kirjoita_600(a.ulos, puhdas)
            print("WG_ASETUS: SIIVOTTU palvelin %s portti %d" % (palvelin, portti))
            return 0
        palvelin, portti = tarkista(lue(a.tiedosto))
        if a.komento == "tarkista":
            print("WG_ASETUS: OK palvelin %s portti %d" % (palvelin, portti))
        elif a.komento == "nft":
            sys.stdout.write(nft_maaritykset(palvelin, portti))
        else:
            asetukset = lue_asetukset(lue(a.asetukset))
            sys.stdout.write(tayta_isanta(lue(a.mall), asetukset, palvelin, portti, kielletyt4(lue(a.pohja))))
        return 0
    except AsetusVirhe as e:
        print("WG_ASETUS: VIRHE %s" % e.args[0], file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print("WG_ASETUS: VIRHE tiedosto %s" % type(e).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
