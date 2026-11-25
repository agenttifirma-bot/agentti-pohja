"""Docs-viennin siivottu kopio: agenttien tulokset, tehtavat ja paatokset Gitean repoon tony/agenttidata.

Suunnitelma: claude-jono/suunnitelmat/aivo-tietolahde-1-tulokset.md (vaihtoehto a, Tonyn paatos A1003).
Vain nimetyt polut (allowlist), siivous ennen kopiota, push vain sallittuun osoitteeseen. Ei muuta mitaan muualle.

Lahde (docs-repon kopio, vain luku):  claude-jono/tulokset/*.md, claude-jono/tehtavat/*.md, claude-jono/pohdinta-vastaukset.md
                                     (perusajo, 15 min valein) seka claude-jono/kompassi.md ja claude-jono/faktat.md
                                     (--aivo, kerran tunnissa; Tonyn paatos 19.11.2026, tehtava "Aivo: agenttidatan vientiin kompassi...").
Kohde (tyoklooni): tulokset/, tehtavat/, pohdinta-vastaukset.md, kompassi.md, faktat.md.
Kumpikin ajo hallitsee vain omia polkujaan: perusajo ei koske kompassiin eika faktoihin, --aivo ei koske tuloksiin.
Samaan tyoklooniin ajetaan yksi vienti kerrallaan (lukko <tyo>.lukko).

Siivous: tulos- tai tehtavatiedosto, jossa on avaimen muotoinen merkkijono (sk-, ghp_, github_pat_, Telegram-token,
yksityisen avaimen otsake), jatetaan kokonaan pois (kirjataan vain nimi). YKSITTAISET-tiedostosta (pohdinta-vastaukset.md)
jatetaan pois vain se merkinta ("- **A..."-merkinta tai ensimmaista merkintaa edeltava alku), jossa avaimen muotoinen
merkkijono tai avaimen runko (perakkaisia base64-riveja ilman BEGIN/END-rivia) on; jos merkinnassa on BEGIN ilman
END-rivia, poistetaan myos seuraava merkinta, ja jos END ilman BEGIN-rivia, myos edellinen; tilalle tulee rivi "[merkinta poistettu: ...]" ja ohitettuihin kirjataan vain lukumaara, ei sisaltoa.
Kaikesta poistetaan lisaksi avain=arvo-parit seka IPv4-osoitteet ja *.ts.net-nimet.
Koko: tulokset ja tehtavat yli MAX_TAVUA (200 kt) jatetaan pois. YKSITTAISET-tiedostosta yli YKSITTAISET_MAX_TAVUA (4 Mt)
viedaan loppuosa merkinnan alusta alkaen, ja alkuun lisataan rivi "[alku jatetty pois: N tavua]" (lukija lukee vain lopun).
Raja tarkistetaan korvausten ja siivouksen jalkeen; jos korvausrivit kasvattavat tekstin yli rajan, luetaan lyhyempi loppuosa.
Lopputarkistus (avaimen muotoinen merkkijono tai runko) koskee koko vietavaa tekstia: osuma ohittaa koko tiedoston.
Symbolisia linkkeja ei seurata. Jos mikaan ei muuttunut, committia ei tehda.

Kaytto: python3 -m agentti.docs_vienti [--aivo] [--kuiva]
Ymparisto: DOCS_VIENTI_LAHDE (/opt/agenttifirma-docs), DOCS_VIENTI_TYO (/var/lib/docs-vienti/agenttidata),
DOCS_VIENTI_OSOITE (PAKOLLINEN: ssh://git@<Gitean IP>[:portti]/tony/agenttidata.git), DOCS_VIENTI_ISANTA (PAKOLLINEN: tasmalleen Gitean IPv4-osoite;
osoitteen isannan pitaa olla sama), DOCS_VIENTI_AVAIN (/etc/docs-vienti/avain).
Virheista tulostetaan vain tyypin nimi tai lyhyt syy, ei gitin tulostetta (voi sisaltaa salaisuuksia).
"""
import argparse
import contextlib
import fcntl
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .tilannekuva import SALAISUUDET

OLETUS_LAHDE = "/opt/agenttifirma-docs"
OLETUS_TYO = "/var/lib/docs-vienti/agenttidata"
OLETUS_AVAIN = "/etc/docs-vienti/avain"

# Sallittu isanta: vain yksi, asetuksella DOCS_VIENTI_ISANTA annettu kirjaimellinen IPv4-osoite (ei verkkoalueita, ei nimia eli ei DNS-kikkoja).
# Asetus ei saa olla julkinen, loopback-, linkki- tai monilahetysosoite; asetukset kirjoitetaan /etc/docs-vienti/asetukset.env, ei repoon.
SALLITTU_POLKU = "/tony/agenttidata.git"
HAARA = "main"
MAX_TAVUA = 200_000
# pohdinta-vastaukset.md kasvaa koko ajan (yli 200 000 tavua 25.11.2026). Aivon lukija (aivo/agenttidata_kehote.py,
# LUKU_YLARAJA) lukee siita vain lopun, joten raja on sama 4 Mt kuin lukijalla.
YKSITTAISET_MAX_TAVUA = 4_000_000
GIT_AIKARAJA_S = 120
NIMI_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$")

LAHDE_KANSIO = "claude-jono"
KANSIOT = ("tulokset", "tehtavat")
YKSITTAISET = ("pohdinta-vastaukset.md",)
# Aivon kirjaston tiedostot (--aivo, kerran tunnissa). Viedaan sellaisinaan siivouksen jalkeen.
AIVO = ("kompassi.md", "faktat.md")
LUKKO_ODOTUS_S = 60

# Avaimen muotoiset merkkijonot: tiedosto jatetaan pois kokonaan. sk-: ei sanan keskelta (risk-assessment-framework).
AVAIN_MUOTOISET = [
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
PEM_ALKU = AVAIN_MUOTOISET[-1]
# Yksityisen avaimen runko ilman BEGIN/END-rivia (avain jakautuu merkintojen rajalle tai otsake katkeaa):
# vahintaan RUNKO_MIN_RIVEJA perakkaista rivia, joissa on vain 40-80 base64-merkkia (+ enintaan kaksi =-merkkia).
# Pelkat heksarivit (esim. git-tiivisteiden lista) eivat yksinaan riita: jaksossa pitaa olla ainakin yksi ei-heksarivi.
RUNKO_RIVI = re.compile(r"[ \t>]*([A-Za-z0-9+/]{40,80}={0,2})[ \t]*\r?")
HEKSA = re.compile(r"[0-9A-Fa-f]+")
RUNKO_MIN_RIVEJA = 3
# Pohdinta-vastausten merkinnan alku (sama kuin aivo/agenttidata_kehote.py:n MERKINTA_RE); tavuversio vaatii rivinvaihdon eteen.
MERKINTA_RE = re.compile(r"(?m)^[ \t]*[-*][ \t]+\*\*A[0-9]{1,6}\b")
MERKINTA_RE_B = re.compile(rb"\n([ \t]*[-*][ \t]+\*\*A[0-9]{1,6}\b)")
# Merkintakohtaisessa poistossa myos yksityisen avaimen loppurivi (jos otsake jaisi eri osaan).
PEM_LOPPU = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
ALKU_POIS = "[alku j\u00e4tetty pois: %d tavua]\n"
MERKINTA_POIS = "[merkint\u00e4 poistettu: avaimen muotoinen merkkijono]\n"
IPV4 = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9])")
TAILNET = re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+ts\.net\b")


class ViennitVirhe(Exception):
    """Vienti pysaytetty (esim. kielletty osoite); viesti on lyhyt eika sisalla salaisuuksia."""


def isanta_kelvollinen(isanta):
    """Tosi vain, jos asetus on yksi IPv4-osoite, joka ei ole julkinen eika loopback-, linkki-, monilahetys- tai maarittamaton osoite."""
    try:
        ip = ipaddress.IPv4Address(str(isanta))
    except ValueError:
        return False
    return not (ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified)


def osoite_sallittu(osoite, isanta):
    """Tosi vain, jos osoite on ssh://git@<isanta>[:portti]/tony/agenttidata.git ja <isanta> on asetuksen yksi tarkka IPv4-osoite."""
    if not isanta_kelvollinen(isanta):
        return False
    try:
        u = urlparse(str(osoite))
        port = u.port
        host = ipaddress.IPv4Address(u.hostname or "")
    except ValueError:
        return False
    return (u.scheme == "ssh" and u.username == "git" and u.password is None and host == ipaddress.IPv4Address(str(isanta))
            and (port is None or port > 0) and u.path == SALLITTU_POLKU and not u.query and not u.fragment)


def avaimen_runko(teksti):
    """Onko tekstissa yksityisen avaimen runko: RUNKO_MIN_RIVEJA perakkaista base64-rivia, joista ainakin yksi ei ole pelkkaa heksaa."""
    jakso, kaikki_heksaa = 0, True
    for rivi in teksti.split("\n"):
        m = RUNKO_RIVI.fullmatch(rivi)
        if not m:
            jakso, kaikki_heksaa = 0, True
            continue
        jakso += 1
        kaikki_heksaa = kaikki_heksaa and HEKSA.fullmatch(m.group(1)) is not None
        if jakso >= RUNKO_MIN_RIVEJA and not kaikki_heksaa:
            return True
    return False


def avainmuotoinen(teksti):
    return any(p.search(teksti) for p in AVAIN_MUOTOISET) or avaimen_runko(teksti)


def lue_loppuosa(polku, raja):
    """Palauttaa (teksti, pois_tavua). Jos tiedosto on yli `raja` tavua, luetaan loppu niin, etta tulos
    alkuriveineen on enintaan `raja` tavua, ja se alkaa ensimmaisen kokonaisen merkinnan alusta (ilman merkintoja
    ensimmaisen kokonaisen rivin alusta). Puolikasta rivia ei koskaan palauteta."""
    with open(polku, "rb") as f:
        koko = os.fstat(f.fileno()).st_size
        if koko <= raja:
            return f.read(raja + 1).decode("utf-8", "replace"), 0
        luku = max(raja - len((ALKU_POIS % koko).encode("utf-8")), 0)
        f.seek(koko - luku - 1)                      # yksi tavu lisaa: nahdaan, alkaako luettu osa rivin alusta
        data = f.read(luku + 1)
    m = MERKINTA_RE_B.search(data)
    if m:
        alku = m.start(1)
    else:
        rv = data.find(b"\n")
        alku = rv + 1 if rv >= 0 else len(data)
    return data[alku:].decode("utf-8", "replace"), koko - (len(data) - alku)


def poista_avainmerkinnat(teksti):
    """Korvaa jokaisen merkinnan (ja merkintoja edeltavan alun), jossa on avaimen muotoinen merkkijono, avaimen runko
    tai PEM-loppurivi, rivilla MERKINTA_POIS. Jos merkinnassa on BEGIN-rivi ilman sita seuraavaa END-rivia, poistetaan
    myos seuraava merkinta; jos END-rivi ilman sita edeltavaa BEGIN-rivia, myos edellinen (avain jakautuu kahteen
    merkintaan). Palauttaa (teksti, poistettujen maara)."""
    alut = [0] + [m.start() for m in MERKINTA_RE.finditer(teksti) if m.start() > 0]
    osat = [teksti[a:b] for a, b in zip(alut, alut[1:] + [len(teksti)])]
    pois = [False] * len(osat)
    for i, osa in enumerate(osat):
        if not (avainmuotoinen(osa) or PEM_LOPPU.search(osa)):
            continue
        pois[i] = True
        alut_ = [m.end() for m in PEM_ALKU.finditer(osa)]
        loput = [m.start() for m in PEM_LOPPU.finditer(osa)]
        if alut_ and not any(l >= alut_[-1] for l in loput) and i + 1 < len(osat):
            pois[i + 1] = True                       # BEGIN ilman END:ia: runko jatkuu seuraavaan merkintaan
        if loput and not any(a <= loput[0] for a in alut_) and i > 0:
            pois[i - 1] = True                       # END ilman BEGIN:ia: otsake on edellisessa merkinnassa
    tulos = [MERKINTA_POIS if p else osa for osa, p in zip(osat, pois)]
    return "".join(tulos), sum(pois)


def lue_yksittainen(polku, raja, yrityksia=8):
    """Lukee YKSITTAISET-tiedoston loppuosan, poistaa avainmerkinnat ja siivoaa. Raja tarkistetaan lopullisesta
    tekstista (korvausrivit ja siivous voivat kasvattaa sita); jos se ylittyy, luetaan lyhyempi loppuosa.
    Palauttaa (siivottu teksti tai None jos rajaan ei paasty, poistettujen merkintojen maara, vuoto). vuoto on tosi,
    jos siivoamattomassa tekstissa on yha avaimen muotoinen merkkijono, runko tai PEM-loppurivi (siivous poistaisi
    BEGIN-otsakkeen, joten tama tarkistetaan ennen sita)."""
    luku = raja
    for _ in range(yrityksia):
        teksti, pois = lue_loppuosa(polku, luku)
        teksti, poistettu = poista_avainmerkinnat(teksti)
        if pois:
            teksti = ALKU_POIS % pois + teksti
        vuoto = avainmuotoinen(teksti) or PEM_LOPPU.search(teksti) is not None
        teksti = siivoa(teksti)
        koko = len(teksti.encode("utf-8"))
        if koko <= raja:
            return teksti, poistettu, vuoto
        luku -= 2 * (koko - raja) + min(1024, luku // 10)   # varaa uusille korvausriveille
        if luku <= 0:
            break
    return None, 0, False


def siivoa(teksti):
    """Poistaa avain=arvo-parit, IPv4-osoitteet ja tailnet-nimet. Ei katkaise pituutta."""
    for s in SALAISUUDET:
        teksti = s.sub("[poistettu]", teksti)
    teksti = TAILNET.sub("[nimi-poistettu]", teksti)
    return IPV4.sub("[ip-poistettu]", teksti)


def _lahteet(lahde, aivo):
    """Palauttaa (suhteellinen kohdepolku, lahdepolku) vain allowlistasta; symlinkit ja epakelvot nimet ohitetaan."""
    perus = Path(lahde) / LAHDE_KANSIO
    tulos = []
    for kansio in (() if aivo else KANSIOT):
        k = perus / kansio
        if not k.is_dir() or k.is_symlink():
            continue
        for p in sorted(k.iterdir()):
            if NIMI_RE.match(p.name) and p.is_file() and not p.is_symlink():
                tulos.append((kansio + "/" + p.name, p))
    for nimi in (AIVO if aivo else YKSITTAISET):
        p = perus / nimi
        if p.is_file() and not p.is_symlink():
            tulos.append((nimi, p))
    return tulos


def _sallittu_kohde(polku, aivo):
    """Ajo saa muuttaa vain omia polkujaan: --aivo vain AIVO-tiedostoja, perusajo vain tuloksia, tehtavia ja YKSITTAISET."""
    if aivo:
        return polku in AIVO
    if polku in YKSITTAISET:
        return True
    osat = polku.split("/")
    return len(osat) == 2 and osat[0] in KANSIOT and bool(NIMI_RE.match(osat[1]))


def valmista(lahde, kohde, aivo=False):
    """Kirjoittaa siivotun kopion tyoklooniin (poistaa ensin taman ajon hallitut polut). Palauttaa (kopioitu, ohitetut: [(nimi, syy)])."""
    kohde = Path(kohde)
    for kansio in (() if aivo else KANSIOT):
        shutil.rmtree(kohde / kansio, ignore_errors=True)
    for nimi in (AIVO if aivo else YKSITTAISET):
        (kohde / nimi).unlink(missing_ok=True)
    kopioitu, ohitetut = 0, []
    for suht, p in _lahteet(lahde, aivo):
        yksittainen = suht in YKSITTAISET
        try:
            if yksittainen:
                teksti, poistettu, vuoto = lue_yksittainen(p, YKSITTAISET_MAX_TAVUA)
                if teksti is None:
                    ohitetut.append((suht, "yli %d tavua korvausten jalkeen" % YKSITTAISET_MAX_TAVUA))
                    continue
            elif p.stat().st_size > MAX_TAVUA:
                ohitetut.append((suht, "yli %d tavua" % MAX_TAVUA))
                continue
            else:
                teksti = p.read_text(encoding="utf-8", errors="replace")
        except OSError as virhe:
            ohitetut.append((suht, type(virhe).__name__))
            continue
        # Lopputarkistus koko vietavalle tekstille (YKSITTAISET: ennen ja jalkeen siivouksen): osuma ohittaa koko tiedoston.
        if avainmuotoinen(teksti) or (yksittainen and vuoto):
            ohitetut.append((suht, "avaimen muotoinen merkkijono"))
            continue
        if yksittainen and poistettu:
            ohitetut.append((suht, "merkinta poistettu (%d)" % poistettu))
        ulos = kohde / suht
        ulos.parent.mkdir(parents=True, exist_ok=True)
        ulos.write_text(teksti if yksittainen else siivoa(teksti), encoding="utf-8")
        kopioitu += 1
    return kopioitu, ohitetut


def _git(tyo, *args, env=None):
    """Ajaa gitin ilman tulosteen vuotoa; palauttaa (paluukoodi, stdout)."""
    e = dict(os.environ)
    e.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    e.update(env or {})
    r = subprocess.run(["git", "-C", str(tyo)] + list(args), capture_output=True, text=True, timeout=GIT_AIKARAJA_S, env=e)
    return r.returncode, r.stdout


def _ssh_env(avain, tyo):
    tiedot = str(Path(tyo).parent / "known_hosts")
    return {"GIT_SSH_COMMAND": "ssh -i %s -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
                               "-o UserKnownHostsFile=%s" % (avain, tiedot)}


@contextlib.contextmanager
def _lukko(tyo, odotus_s=LUKKO_ODOTUS_S):
    """Yksi vienti kerrallaan samaan tyoklooniin (perusajo ja --aivo voivat osua samaan aikaan). Lukko vapautuu prosessin paattyessa."""
    polku = Path(str(tyo) + ".lukko")
    polku.parent.mkdir(parents=True, exist_ok=True)
    with open(polku, "a") as f:
        loppu = time.monotonic() + odotus_s
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= loppu:
                    raise ViennitVirhe("toinen vienti on kaynnissa; yritetaan seuraavalla ajolla")
                time.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def vie(lahde, tyo, osoite, avain=OLETUS_AVAIN, aivo=False, kuiva=False, ssh=True, isanta="", lukko_odotus_s=LUKKO_ODOTUS_S):
    """Koko vienti. Palauttaa yhteenvetorivin. Nostaa ViennitVirhe, jos osoite on kielletty tai git epaonnistuu.

    Pushaus tehdaan suoraan tarkistettuun osoitteeseen (ei etakohteen nimen kautta), joten tyoklooniin
    asetettu `origin` ei voi ohjata dataa muualle.
    """
    if not isanta_kelvollinen(isanta):
        raise ViennitVirhe("DOCS_VIENTI_ISANTA puuttuu tai ei ole kelvollinen sisaverkon IPv4-osoite; ei pushata")
    if not osoite_sallittu(osoite, isanta):
        raise ViennitVirhe("osoite ei ole sallittu (isanta, kayttaja tai polku); ei pushata")
    tyo = Path(tyo)
    with _lukko(tyo, lukko_odotus_s):
        return _vie_lukittuna(lahde, tyo, osoite, avain, aivo, kuiva, ssh)


def _peru_kuiva(tyo, aivo):
    """Kuiva-ajo palauttaa tyoklooonin ennalleen: muuten sen kirjoittamat seuraamattomat tiedostot jaisivat
    tyoklooniin ja pysayttaisivat toisen ajon (perusajo/--aivo) allowlist-tarkistukseen."""
    _git(tyo, "reset", "-q")
    _git(tyo, "checkout", "-q", "--", ".")          # tyhjassa repossa ei mitaan palautettavaa (paluukoodi ohitetaan)
    _git(tyo, "clean", "-fdq", "--", *((AIVO) if aivo else (KANSIOT + YKSITTAISET)))


def _pushaa_aiempi(tyo, osoite, env):
    """Pushaa tyoklooonin HEADin tyhjaan etarepoon vain, jos jokainen sen polku on jommankumman ajon allowlistissa."""
    rc, puu = _git(tyo, "ls-tree", "-r", "--name-only", "HEAD")
    if rc != 0:
        raise ViennitVirhe("git ls-tree epaonnistui")
    polut = [n for n in puu.splitlines() if n]
    if any(not (_sallittu_kohde(n, False) or _sallittu_kohde(n, True)) for n in polut):
        raise ViennitVirhe("aiemmassa commitissa on allowlistin ulkopuolisia polkuja; ei pushata")
    rc, _ = _git(tyo, "push", "-q", osoite, "HEAD:refs/heads/" + HAARA, env=env)
    if rc != 0:
        raise ViennitVirhe("git push epaonnistui")


def _vie_lukittuna(lahde, tyo, osoite, avain, aivo, kuiva, ssh):
    """vie() lukon sisalla; osoite ja isanta on jo tarkistettu."""
    env = _ssh_env(avain, tyo) if ssh else {}
    if not (tyo / ".git").is_dir():
        tyo.mkdir(exist_ok=True)
        rc, _ = _git(tyo, "init", "-q", "-b", HAARA)
        if rc != 0:
            raise ViennitVirhe("git init epaonnistui")
    # Haetaan nykytila (tyhja repo: haara puuttuu, se on sallittu ensimmaisella kerralla).
    rc, nakyy = _git(tyo, "ls-remote", osoite, "refs/heads/" + HAARA, env=env)
    if rc != 0:
        raise ViennitVirhe("etarepon luku epaonnistui (git ls-remote)")
    if nakyy.strip():
        rc, _ = _git(tyo, "fetch", "-q", osoite, HAARA, env=env)
        if rc != 0:
            raise ViennitVirhe("git fetch epaonnistui")
        rc, _ = _git(tyo, "reset", "-q", "--hard", "FETCH_HEAD")
        if rc != 0:
            raise ViennitVirhe("git reset epaonnistui")
    kopioitu, ohitetut = valmista(lahde, tyo, aivo)
    _git(tyo, "add", "-A")
    rc, nimet = _git(tyo, "diff", "--cached", "--name-only")
    if rc != 0:
        raise ViennitVirhe("git diff epaonnistui")
    muuttuneet = [n for n in nimet.splitlines() if n]
    vaarat = [n for n in muuttuneet if not _sallittu_kohde(n, aivo)]
    if vaarat:
        _git(tyo, "reset", "-q")
        raise ViennitVirhe("allowlistin ulkopuolisia polkuja (%d); ei committia" % len(vaarat))
    ohit = "; ohitettu %d" % len(ohitetut) if ohitetut else ""
    if not muuttuneet:
        if not nakyy.strip() and not kuiva and _git(tyo, "rev-parse", "-q", "--verify", "HEAD")[0] == 0:
            # Etarepo on yha tyhja, mutta tyoklooonissa on aiemman ajon commit, jonka push epaonnistui
            # (esim. avain puuttui asennuksessa). Ilman tata sita ei pushattaisi ennen seuraavaa lahdemuutosta.
            _pushaa_aiempi(tyo, osoite, env)
            return "pushattu: aiempi commit tyhjaan etarepoon (kopioitu %d)%s" % (kopioitu, ohit)
        return "ei muutoksia (kopioitu %d)%s; ei committia" % (kopioitu, ohit)
    if kuiva:
        _peru_kuiva(tyo, aivo)
        return "kuiva-ajo: %d tiedostoa muuttuisi (kopioitu %d)%s; ei committia" % (len(muuttuneet), kopioitu, ohit)
    rc, _ = _git(tyo, "-c", "user.name=docs-vienti", "-c", "user.email=docs-vienti@localhost",
                 "commit", "-q", "-m", "docs-vienti%s: %d tiedostoa muuttui" % (" (aivo)" if aivo else "", len(muuttuneet)))
    if rc != 0:
        raise ViennitVirhe("git commit epaonnistui")
    rc, _ = _git(tyo, "push", "-q", osoite, "HEAD:refs/heads/" + HAARA, env=env)
    if rc != 0:
        raise ViennitVirhe("git push epaonnistui")
    return "pushattu: %d tiedostoa muuttui (kopioitu %d)%s" % (len(muuttuneet), kopioitu, ohit)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentti.docs_vienti", description="Siivottu kopio agenttien tuloksista Gitean repoon tony/agenttidata")
    p.add_argument("--aivo", action="store_true", help="vie vain Aivon tiedostot: claude-jono/kompassi.md ja faktat.md (ajastin kerran tunnissa)")
    p.add_argument("--kuiva", action="store_true", help="ala committaa eika pushaa")
    a = p.parse_args(argv)
    env = os.environ.get
    try:
        print("docs-vienti: " + vie(env("DOCS_VIENTI_LAHDE", OLETUS_LAHDE), env("DOCS_VIENTI_TYO", OLETUS_TYO),
                                    env("DOCS_VIENTI_OSOITE", ""), env("DOCS_VIENTI_AVAIN", OLETUS_AVAIN),
                                    a.aivo, a.kuiva, isanta=env("DOCS_VIENTI_ISANTA", "")))
    except ViennitVirhe as virhe:
        print("docs-vienti: VIRHE: %s" % virhe, file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as virhe:
        print("docs-vienti: VIRHE: %s" % type(virhe).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
