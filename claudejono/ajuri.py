"""Clauden tehtavajono GitHubin yli (doc 71, Tonyn hyvaksynta 30.10.2026).

Pilvi-Claude kirjoittaa tehtavat docs-repoon `claude-jono/tehtavat/<id>.md`. Tama ajuri (CT115, systemd-ajastin) hakee repon,
ottaa vanhimman tehtavan jolla ei ole tulosta, ajaa sen `claude -p`:lla ja pushaa tuloksen `claude-jono/tulokset/<id>.md`.
Yksi tehtava per ajo. Ajuri ei koskaan committaa mitaan muuta kuin oman tulostiedostonsa.

Raja (koodissa, ei vain kehotteessa): tehtava saa avata PR:n, mutta ei mergea, ei muuta katto- tai oikeusarvoja eika kasittele salaisuuksia.
Kehote kertoo rajan agentille; CT115:n .claude/settings.json estaa salaisuustiedostot; ajuri rajaa commitin polun.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TEHTAVA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-[a-z0-9-]{1,60}\.md$")
TEHTAVA_MAX_TAVUA = 20000
TULOS_MAX_TAVUA = 60000
OLETUS_AIKARAJA_S = 45 * 60
OLETUS_MAX_KIERROKSET = 60
JONO = "claude-jono"
KEHOTE = Path(__file__).resolve().parent / "kehote.md"


class JonoVirhe(RuntimeError):
    pass


def kelvollinen_nimi(nimi):
    return bool(TEHTAVA_RE.match(nimi))


def seuraava_tehtava(repo):
    """Vanhin (nimen mukaan) kelvollinen tehtava, jolla ei ole tulosta. None jos jono on tyhja."""
    teht = Path(repo) / JONO / "tehtavat"
    tul = Path(repo) / JONO / "tulokset"
    if not teht.is_dir():
        return None
    for p in sorted(teht.iterdir()):
        if p.is_file() and kelvollinen_nimi(p.name) and not (tul / p.name).exists():
            return p
    return None


def rakenna_kehote(tehtava_polku, kehote_polku=KEHOTE):
    data = Path(tehtava_polku).read_bytes()
    if len(data) > TEHTAVA_MAX_TAVUA:
        raise JonoVirhe(f"tehtava yli {TEHTAVA_MAX_TAVUA} tavua")
    return Path(kehote_polku).read_text(encoding="utf-8") + "\n\n<tehtava>\n" + data.decode("utf-8") + "\n</tehtava>\n"


def claude_komento(kehote, env):
    kom = [env.get("CLAUDEJONO_CLAUDE", "claude"), "-p", kehote, "--output-format", "json",
           "--max-turns", str(int(env.get("CLAUDEJONO_MAX_KIERROKSET", OLETUS_MAX_KIERROKSET)))]
    if env.get("CLAUDEJONO_LUPATILA"):
        kom += ["--permission-mode", env["CLAUDEJONO_LUPATILA"]]
    return kom


def tulkitse(stdout, koodi):
    """(ok, teksti) claude -p --output-format json -tulosteesta. Lukukelvoton tuloste = epaonnistui."""
    try:
        d = json.loads(stdout)
    except (ValueError, TypeError):
        return False, f"lukukelvoton tuloste (koodi {koodi})"
    teksti = d.get("result") if isinstance(d.get("result"), str) else ""
    ok = koodi == 0 and d.get("is_error") is not True and d.get("subtype", "success") == "success"
    if not ok and not teksti:
        teksti = f"claude epaonnistui (subtype: {d.get('subtype', '?')})"
    return ok, teksti


def kirjoita_tulos(repo, nimi, ok, teksti, nyt=None):
    nyt = nyt or datetime.now().astimezone()
    polku = Path(repo) / JONO / "tulokset" / nimi
    polku.parent.mkdir(parents=True, exist_ok=True)
    runko = teksti.encode("utf-8")[:TULOS_MAX_TAVUA].decode("utf-8", "ignore")
    polku.write_text(f"# Tulos: {nimi}\n\n- Tila: {'VALMIS' if ok else 'EPAONNISTUI'}\n- Aika: {nyt.isoformat(timespec='minutes')}\n\n{runko}\n",
                     encoding="utf-8")
    return polku


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, timeout=300)
    if check and r.returncode != 0:
        raise JonoVirhe(f"git {args[0]} epaonnistui ({r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def julkaise(repo, polku):
    """Committaa ja pushaa VAIN tulostiedoston. Jos indeksissa on jotain muuta, ei tehda mitaan."""
    suht = str(Path(polku).relative_to(repo))
    if not suht.startswith(f"{JONO}/tulokset/"):
        raise JonoVirhe("vain tulostiedoston saa committaa")
    git(repo, "add", "--", suht)
    staged = [r for r in git(repo, "diff", "--cached", "--name-only").stdout.splitlines() if r]
    if staged != [suht]:
        git(repo, "reset", "-q", check=False)
        raise JonoVirhe(f"indeksissa muuta kuin tulos: {staged[:5]}")
    git(repo, "commit", "-q", "-m", f"claude-jono: tulos {Path(polku).name}")
    for _ in range(3):
        if git(repo, "push", "-q", "origin", "HEAD", check=False).returncode == 0:
            return True
        git(repo, "pull", "-q", "--rebase", "origin", "main", check=False)
    return False


def aja(repo, tyohak, env=None, suorita=subprocess.run, laheta=None):
    env = dict(os.environ if env is None else env)
    git(repo, "pull", "-q", "--rebase", "origin", "main")
    t = seuraava_tehtava(repo)
    if t is None:
        return "jono tyhja"
    kehote = rakenna_kehote(t)
    alaenv = {k: v for k, v in env.items() if not k.startswith(("YOJONO_TELEGRAM_", "CLAUDEJONO_GIT"))}
    try:
        r = suorita(claude_komento(kehote, env), cwd=str(tyohak), capture_output=True, text=True,
                    timeout=int(env.get("CLAUDEJONO_AIKARAJA_S", OLETUS_AIKARAJA_S)), env=alaenv, check=False)
        ok, teksti = tulkitse(r.stdout, r.returncode)
    except subprocess.TimeoutExpired:
        ok, teksti = False, "aikakatkaisu"
    polku = kirjoita_tulos(repo, t.name, ok, teksti)
    pushattu = julkaise(repo, polku)
    viesti = f"claude-jono: {t.name} {'VALMIS' if ok else 'EPAONNISTUI'}" + ("" if pushattu else " (push epaonnistui)")
    if laheta:
        laheta(viesti + "\n" + teksti[:1500])
    return viesti


def main(argv=None):
    p = argparse.ArgumentParser(description="Clauden tehtavajono (GitHub)")
    p.add_argument("komento", choices=["ajo", "seuraava"])
    a = p.parse_args(argv)
    repo = Path(os.environ.get("CLAUDEJONO_REPO", "/var/lib/claude-jono/docs"))
    tyohak = Path(os.environ.get("CLAUDEJONO_TYOHAK", "/opt/agentscope"))
    if a.komento == "seuraava":
        try:
            git(repo, "pull", "-q", "--rebase", "origin", "main")
        except JonoVirhe as virhe:
            print(f"claude-jono virhe: {virhe}", file=sys.stderr)
            return 1
        t = seuraava_tehtava(repo)
        print(t.name if t else "jono tyhja")
        return 0
    with open(repo.parent / "lukko", "w") as lukko:
        try:
            fcntl.flock(lukko, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("toinen ajo kaynnissa")
            return 0
        try:
            from yojono.ajuri import laheta_telegram
        except Exception:
            laheta_telegram = None
        try:
            print(aja(repo, tyohak, laheta=laheta_telegram))
        except JonoVirhe as virhe:
            print(f"claude-jono virhe: {type(virhe).__name__}: {str(virhe)[:200]}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
