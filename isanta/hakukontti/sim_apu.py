"""Verkkosimulaation apuohjelma (vain testit, test_wireguard.py). Vain stdlib. Ei kayteta hakukontissa.

  kuuntele LOKI tcp:PORTTI|udp:PORTTI ...   kirjaa yhteydet ja paketit tiedostoon (rivi: protokolla portti lahettaja)
  tcp OSOITE PORTTI                         avaa TCP-yhteyden; tulostaa OK tai ESTO <poikkeuksen tyyppi>
  udp OSOITE PORTTI [MERKKI]                lahettaa UDP-paketin (valinnainen SO_MARK); tulostaa OK tai ESTO <tyyppi>
  vuoto OSOITE PORTTI LIITANTA              avaa TCP-yhteyden, ottaa liitannan alas ja lahettaa dataa vanhassa yhteydessa
"""
import socket
import subprocess
import sys
import threading
import time

SO_MARK = 36
AIKARAJA = 2.0


def kirjaa(loki, rivi):
    with open(loki, "a", encoding="utf-8") as f:
        f.write(rivi + "\n")


def tcp_palvelin(loki, portti):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", portti))
    s.listen(16)
    while True:
        c, (osoite, _) = s.accept()
        kirjaa(loki, "tcp %d %s" % (portti, osoite))
        threading.Thread(target=lue_kaikki, args=(loki, portti, c), daemon=True).start()


def lue_kaikki(loki, portti, c):
    try:
        while True:
            d = c.recv(4096)
            if not d:
                break
            kirjaa(loki, "data %d %d" % (portti, len(d)))
    except OSError:
        pass


def udp_palvelin(loki, portti):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", portti))
    while True:
        _, (osoite, _) = s.recvfrom(2048)
        kirjaa(loki, "udp %d %s" % (portti, osoite))


def kuuntele(loki, maaritykset):
    for m in maaritykset:
        proto, portti = m.split(":")
        kohde = tcp_palvelin if proto == "tcp" else udp_palvelin
        threading.Thread(target=kohde, args=(loki, int(portti)), daemon=True).start()
    kirjaa(loki, "valmis")
    while True:
        time.sleep(3600)


def tcp(osoite, portti):
    try:
        with socket.create_connection((osoite, int(portti)), timeout=AIKARAJA):
            return "OK"
    except socket.timeout:
        return "ESTO timeout"
    except OSError as e:
        return "ESTO %s" % type(e).__name__


def udp(osoite, portti, merkki=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if merkki is not None:
            s.setsockopt(socket.SOL_SOCKET, SO_MARK, int(merkki, 0))
        s.sendto(b"x", (osoite, int(portti)))
        return "OK"
    except OSError as e:
        return "ESTO %s" % type(e).__name__
    finally:
        s.close()


def vuoto(osoite, portti, liitanta):
    try:
        c = socket.create_connection((osoite, int(portti)), timeout=AIKARAJA)
    except OSError as e:
        return "ESTO %s" % type(e).__name__
    subprocess.run(["ip", "link", "set", liitanta, "down"], check=True)
    try:
        c.send(b"vuoto" * 10)
        time.sleep(1.5)
        return "LAHETETTY"
    except OSError as e:
        return "ESTO %s" % type(e).__name__
    finally:
        c.close()


def main(argv):
    komento = argv[0]
    if komento == "kuuntele":
        kuuntele(argv[1], argv[2:])
    elif komento == "tcp":
        print(tcp(*argv[1:3]))
    elif komento == "udp":
        print(udp(*argv[1:4]))
    elif komento == "vuoto":
        print(vuoto(*argv[1:4]))
    else:
        raise SystemExit("tuntematon komento")


if __name__ == "__main__":
    main(sys.argv[1:])
