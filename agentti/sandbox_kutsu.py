"""Sandbox-asiakas: lahettaa luonnoksen tai repon eristettyyn sandboxiin ssh:lla.

Ajetaan CT115:ssa (agentit). Isannan pakotettu komento (/root/sandbox-kutsu.py)
sallii vain 'repo <url> [ref]' ja 'luonnos' (tar.gz stdinista).

  from agentti.sandbox_kutsu import aja_repo, aja_luonnos
  tulos = aja_luonnos("/polku/luonnos")      # dict: ok, vaihe, loki, ...
  tulos = aja_repo("https://github.com/o/r", ref="v1.0")
  tulos = aja_git("/polku/git-repo", ref="yo/haara")   # vain haaran seurattavat tiedostot

CLI: python -m agentti.sandbox_kutsu git <git-repo> [ref]

Asetukset ymparistomuuttujilla:
  SANDBOX_HOST (oletus 192.168.1.114), SANDBOX_KEY (oletus /root/.ssh/sandbox_key),
  SANDBOX_USER (oletus root), SANDBOX_KNOWN_HOSTS (valinnainen tiedosto).
Ei salaisuuksia: avaintiedoston polku vain, sisaltoa ei lueta.
"""
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

LUONNOS_RAJA = 900 * 1024
POIS = {"node_modules", ".git", ".venv", "__pycache__"}
URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


class SandboxVirhe(Exception):
    pass


def _ssh_perus():
    avain = os.environ.get("SANDBOX_KEY", "/root/.ssh/sandbox_key")
    isanta = os.environ.get("SANDBOX_HOST", "192.168.1.114")
    kayttaja = os.environ.get("SANDBOX_USER", "root")
    komento = ["ssh", "-i", avain, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "IdentitiesOnly=yes"]
    kh = os.environ.get("SANDBOX_KNOWN_HOSTS")
    if kh:
        komento += ["-o", "UserKnownHostsFile=" + kh, "-o", "StrictHostKeyChecking=yes"]
    return komento + ["%s@%s" % (kayttaja, isanta)]


def luonnos_tar(hakemisto):
    """Pakkaa hakemiston muistiin. Vain tavalliset tiedostot; ei symlinkkeja eika raskaita hakemistoja."""
    pohja = os.path.realpath(hakemisto)
    if not os.path.isdir(pohja):
        raise SandboxVirhe("luonnoshakemistoa ei loydy: " + str(hakemisto))
    puskuri = io.BytesIO()
    with tarfile.open(fileobj=puskuri, mode="w:gz") as tar:
        for juuri, hakemistot, tiedostot in os.walk(pohja):
            hakemistot[:] = sorted(d for d in hakemistot if d not in POIS)
            for nimi in sorted(tiedostot):
                polku = os.path.join(juuri, nimi)
                if os.path.islink(polku) or not os.path.isfile(polku):
                    continue
                tar.add(polku, arcname=os.path.relpath(polku, pohja), recursive=False)
    data = puskuri.getvalue()
    if len(data) > LUONNOS_RAJA:
        raise SandboxVirhe("luonnos liian suuri (%d tavua, raja %d)" % (len(data), LUONNOS_RAJA))
    return data


def _suorita(komento_osa, syote=None, aikaraja=900):
    try:
        r = subprocess.run(_ssh_perus() + [komento_osa], input=syote, capture_output=True,
                           timeout=aikaraja)
    except subprocess.TimeoutExpired:
        raise SandboxVirhe("sandbox-ajo ylitti aikarajan (%d s)" % aikaraja)
    ulos = r.stdout.decode("utf-8", "replace")
    virhe = r.stderr.decode("utf-8", "replace").strip()
    try:
        tulos = json.loads(ulos)
    except ValueError:
        raise SandboxVirhe("ei JSON-vastausta (koodi %s): %s" % (r.returncode, (virhe or ulos)[-300:]))
    if not isinstance(tulos, dict):
        raise SandboxVirhe("odottamaton vastaus")
    return tulos


def aja_repo(url, ref="", aikaraja=900):
    if not URL_RE.match(url):
        raise SandboxVirhe("vain https://github.com/omistaja/repo sallitaan")
    if ref and not REF_RE.match(ref):
        raise SandboxVirhe("virheellinen ref")
    return _suorita("repo %s%s" % (url, (" " + ref) if ref else ""), aikaraja=aikaraja)


def aja_luonnos(hakemisto, aikaraja=900):
    return _suorita("luonnos", syote=luonnos_tar(hakemisto), aikaraja=aikaraja)


def git_tiedostot(repo, ref, kohde):
    """Purkaa 'git archive'-tulosteen (vain seurattavat tiedostot) kohdehakemistoon.

    Ei seuraamattomia tiedostoja (.env, tilatiedostot), ei symlinkkeja, ei absoluuttisia
    eika '..'-polkuja. Palauttaa purettujen tiedostojen maaran."""
    if not REF_RE.match(ref):
        raise SandboxVirhe("virheellinen ref")
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SandboxVirhe("ei git-repo: " + str(repo))
    try:
        r = subprocess.run(["git", "-C", repo, "archive", "--format=tar", ref, "--"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SandboxVirhe("git archive epaonnistui: %s" % e)
    if r.returncode != 0:
        raise SandboxVirhe("git archive epaonnistui: " + r.stderr.decode("utf-8", "replace").strip()[-200:])
    pohja = os.path.realpath(kohde)
    maara = 0
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as tar:
        for jasen in tar:
            if not jasen.isfile():
                continue
            nimi = os.path.normpath(jasen.name)
            if os.path.isabs(nimi) or nimi == ".." or nimi.startswith(".." + os.sep):
                continue
            maali = os.path.join(pohja, nimi)
            os.makedirs(os.path.dirname(maali), exist_ok=True)
            with open(maali, "wb") as f:
                f.write(tar.extractfile(jasen).read())
            maara += 1
    if maara == 0:
        raise SandboxVirhe("git archive ei tuottanut tiedostoja")
    return maara


def aja_git(repo, ref="HEAD", aikaraja=900):
    """Testaa git-repon haaran (vain seurattavat tiedostot) sandboxissa."""
    with tempfile.TemporaryDirectory() as tmp:
        git_tiedostot(repo, ref, tmp)
        return aja_luonnos(tmp, aikaraja=aikaraja)


def tiivista(tulos, rivit=15):
    """Lyhyt teksti Telegram-yhteenvetoon: tila + lokin loppu."""
    tila = "LAPI" if tulos.get("ok") else "EI LAPI"
    otsikko = "%s (vaihe: %s, %s s)" % (tila, tulos.get("vaihe", "?"), tulos.get("kesto_s", "?"))
    if tulos.get("virhe"):
        otsikko += "\nvirhe: " + str(tulos["virhe"])
    loki = [str(r) for r in (tulos.get("loki") or [])][-rivit:]
    return otsikko + ("\n" + "\n".join(loki) if loki else "")


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) == 2 and a[0] == "luonnos":
        tulos = aja_luonnos(a[1])
    elif len(a) in (2, 3) and a[0] == "repo":
        tulos = aja_repo(a[1], a[2] if len(a) == 3 else "")
    elif len(a) in (2, 3) and a[0] == "git":
        tulos = aja_git(a[1], a[2] if len(a) == 3 else "HEAD")
    else:
        print("kaytto: python -m agentti.sandbox_kutsu luonnos <hakemisto> | repo <https://github.com/o/r> [ref] | git <git-repo> [ref]")
        return 2
    print(tiivista(tulos))
    return 0 if tulos.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
