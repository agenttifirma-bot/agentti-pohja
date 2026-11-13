"""PR:n CI-tila yhdelle riville (vain luku). Kaytto: python3 -m agentti.ci_tila <repo> <pr-numero>

Tulostaa yhden ASCII-rivin, esim. `pr=285 sha=72f000f ci=vihrea (3/3)`, `ci=punainen (nimi: test)`, `ci=kesken` tai `ci=ei-ajoja`.
Paluukoodit: 0 vihrea, 1 punainen, 2 kesken tai ei ajoja, 3 haku epaonnistui (tulostetaan vain virhetyyppi ja HTTP-tila).
Kayttaa autonomia.ci_tulos-luokitusta ja pr_laatu._oletushaku-hakua (sama todennus); enintaan 2 API-kutsua."""
import sys

from . import autonomia, pr_laatu
from .pr_kutsu import REPOT


def tila(repo, nro, hae=None):
    """Palauttaa (rivi, paluukoodi). `hae(url)` palauttaa JSON-olion; oletus pr_laatu._oletushaku."""
    hae = hae or pr_laatu._oletushaku
    try:
        sha = str(((hae(autonomia.API % repo + "pulls/%d" % nro) or {}).get("head") or {}).get("sha") or "")
        if not sha:
            return "pr=%d ci=haku-epaonnistui (ei head-sha:ta)" % nro, 3
        vastaus = hae(autonomia.API % repo + "commits/%s/check-runs?per_page=100" % sha)
    except Exception as virhe:
        return "pr=%d ci=haku-epaonnistui (%s)" % (nro, pr_laatu._virhe_tiiviisti(virhe)), 3
    alku = "pr=%d sha=%s" % (nro, sha[:7])
    ajot = (vastaus or {}).get("check_runs") or []
    tulos = autonomia.ci_tulos(vastaus)
    if tulos == "ok":
        return "%s ci=vihrea (%d/%d)" % (alku, len(ajot), len(ajot)), 0
    if tulos == "virhe":
        nimet = ", ".join(str(a.get("name")) for a in ajot if a.get("conclusion") in autonomia.CI_VIRHE)
        return "%s ci=punainen (nimi: %s)" % (alku, nimet), 1
    return "%s ci=%s" % (alku, "kesken" if ajot else "ei-ajoja"), 2


def main(argv=None, hae=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in REPOT or not argv[1].isdigit():
        print("kaytto: python3 -m agentti.ci_tila <repo> <pr-numero>")
        return 3
    rivi, koodi = tila(argv[0], int(argv[1]), hae)
    print(rivi)
    return koodi


if __name__ == "__main__":
    sys.exit(main())
