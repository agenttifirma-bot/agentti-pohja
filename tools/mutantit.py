#!/usr/bin/env python3
"""Mutanttitestaus: muuttaa koodia pienin virhein ja tarkistaa, etta testit huomaavat sen.

Jokaisesta moduulista tehdaan mutantteja (AST-muutokset: vertailuoperaattori, and/or, not, totuusarvo,
kokonaisluku +1, + / -, * / /, if-ehdon kaanto, `return x` -> `return None`). Mutantti ajetaan siina kopiossa
repoa, jossa vain se yksi muutos on tehty, moduulin omilla testeilla. Testit kaatuvat tai aika loppuu
= mutantti "kaatuu" (hyva). Testit menevat lapi = mutantti "selviaa": testeista puuttuu tarkistus
(tai mutantti on vastaava eli ei muuta kayttaytymista).

Kayto:
    python tools/mutantit.py agentti/kulu.py agentti/rajat.py
    python tools/mutantit.py --kaikki                 # kaikki moduulit, joilla on testitiedosto
    python tools/mutantit.py agentti/kulu.py --rinnakkain 4 --json tulos.json

Poistumiskoodi 0 = kaikki kaatuivat (tai selvisivat vain sallitut, tai --ala-kaadu), 1 = selviytyjia,
2 = virhe (alkutilan testit punaisella, tuntematon moduuli).
Vastaavat mutantit (jotka eivat muuta kayttaytymista) kirjataan tiedostoon tools/mutantit.sallitut.txt perusteluineen.
Vain Pythonin vakiokirjasto. Ei kosketa alkuperaiseen puuhun: ajot tehdaan tilapaishakemistojen kopioissa.
"""
import argparse
import ast
import concurrent.futures
import copy
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

JUURI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALLITUT_OLETUS = os.path.join(JUURI, "tools", "mutantit.sallitut.txt")
MODUULI_NIMI = re.compile(r"^(agentti|yojono|tools)/[a-z][a-z0-9_]*\.py$")
HYLATYT_HAKEMISTOT = {".git", "__pycache__", "tila", ".venv", "node_modules"}

_VERTAILU = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BINOP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
_BOOLOP = {ast.And: ast.Or, ast.Or: ast.And}


def _koodi(solmu):
    try:
        return ast.unparse(solmu)
    except Exception:  # pragma: no cover - unparse ei saisi kaatua validille solmulle
        return type(solmu).__name__


class Mutaattori(ast.NodeTransformer):
    """Kay puun lapi samassa jarjestyksessa joka kerta; muuttaa vain kohteen numero `kohde`.

    kohde=None: ei muuta mitaan, vain laskee ehdokkaat (`self.ehdokkaat`: kuvaukset).
    """

    def __init__(self, kohde=None):
        self.kohde = kohde
        self.laskuri = 0
        self.ehdokkaat = []

    def _ehdokas(self, rivi, laji, vanha, uusi):
        """Kirjaa ehdokkaan; palauttaa True jos tama on valittu kohde."""
        i = self.laskuri
        self.laskuri += 1
        self.ehdokkaat.append((rivi, laji, vanha, uusi))
        return self.kohde == i

    def visit_Assign(self, node):
        # VERSAALIT = 123: asetusvakioita ei mutatoida (testit viittaavat niihin nimella, joten +1 ei kerro mitaan)
        if all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets):
            return node
        self.generic_visit(node)
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            uusi_op = _VERTAILU.get(type(op))
            if uusi_op is None:
                continue
            uusi = copy.deepcopy(node)
            uusi.ops[i] = uusi_op()
            if self._ehdokas(node.lineno, "vertailu", _koodi(node), _koodi(uusi)):
                return ast.copy_location(uusi, node)
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        uusi_op = _BOOLOP[type(node.op)]
        uusi = copy.deepcopy(node)
        uusi.op = uusi_op()
        if self._ehdokas(node.lineno, "and/or", _koodi(node), _koodi(uusi)):
            return ast.copy_location(uusi, node)
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            if self._ehdokas(node.lineno, "not pois", _koodi(node), _koodi(node.operand)):
                return ast.copy_location(node.operand, node)
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        uusi_op = _BINOP.get(type(node.op))
        if uusi_op is not None:
            uusi = copy.deepcopy(node)
            uusi.op = uusi_op()
            if self._ehdokas(node.lineno, "aritmetiikka", _koodi(node), _koodi(uusi)):
                return ast.copy_location(uusi, node)
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            uusi = ast.Constant(value=not node.value)
        elif isinstance(node.value, int):
            uusi = ast.Constant(value=node.value + 1)
        else:
            return node
        if self._ehdokas(node.lineno, "vakio", _koodi(node), _koodi(uusi)):
            return ast.copy_location(uusi, node)
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        uusi_ehto = ast.UnaryOp(op=ast.Not(), operand=node.test)
        if self._ehdokas(node.lineno, "if-ehto", _koodi(node.test), _koodi(uusi_ehto)):
            node.test = ast.copy_location(uusi_ehto, node.test)
        return node

    def visit_Return(self, node):
        self.generic_visit(node)
        if node.value is None or (isinstance(node.value, ast.Constant) and node.value.value is None):
            return node
        if self._ehdokas(node.lineno, "return None", _koodi(node), "return None"):
            return ast.copy_location(ast.Return(value=ast.Constant(value=None)), node)
        return node


def luo_mutantit(lahde):
    """Palauttaa listan mutantteja: dict(id, rivi, laji, vanha, uusi, avain)."""
    puu = ast.parse(lahde)
    laskuri = Mutaattori()
    laskuri.visit(puu)
    nahdyt = {}
    tulos = []
    for i, (rivi, laji, vanha, uusi) in enumerate(laskuri.ehdokkaat):
        kolmikko = (laji, vanha, uusi)
        n = nahdyt.get(kolmikko, 0)
        nahdyt[kolmikko] = n + 1
        tulos.append({"id": i, "rivi": rivi, "laji": laji, "vanha": vanha, "uusi": uusi,
                      "toisto": n, "kolmikko": kolmikko})
    return tulos


def mutoi(lahde, id_):
    puu = ast.parse(lahde)
    m = Mutaattori(kohde=id_)
    puu = m.visit(puu)
    ast.fix_missing_locations(puu)
    return ast.unparse(puu) + "\n"


def sallittu_avain(moduuli, mutantti):
    """Vakaa avain sallittujen listaan: ei riipu rivinumerosta, joten rivien siirtyminen ei riko listaa."""
    laji, vanha, uusi = mutantti["kolmikko"]
    return "{}|{}|{}|{}|{}".format(moduuli, laji, vanha.replace("\n", " "), uusi.replace("\n", " "),
                                   mutantti["toisto"])


def lue_sallitut(polku):
    avaimet = set()
    if not polku or not os.path.exists(polku):
        return avaimet
    with open(polku, encoding="utf-8") as f:
        for rivi in f:
            rivi = rivi.rstrip("\n")
            if not rivi.strip() or rivi.lstrip().startswith("#"):
                continue
            avaimet.add(rivi.split("  # ", 1)[0].rstrip())
    return avaimet


# Moduulit, joiden testit ovat muun nimisessa tiedostossa kuin test_<nimi>.py (testimoduulin polku suhteessa juureen).
LISATESTIT = {
    "agentti/data.py": ["test/test_apurit.py"],
    "agentti/sydan.py": ["test/test_apurit.py"],
    "agentti/telegram.py": ["test/test_apurit.py"],
    "agentti/skeema.py": ["test/test_skeema_tulos.py"],
    "agentti/tulos.py": ["test/test_skeema_tulos.py"],
    "agentti/snapshot_kutsu.py": ["test/test_snapshot.py"],
}


def testimoduulit(moduuli, juuri=JUURI):
    """agentti/x.py -> test/test_x.py; yojono/x.py -> yojono/test_x.py; lisaksi LISATESTIT. Palauttaa pistemuotoiset nimet."""
    hak, tied = os.path.split(moduuli)
    nimi = tied[:-3]
    ehdokkaat = [os.path.join("test", "test_" + nimi + ".py"), os.path.join(hak, "test_" + nimi + ".py")]
    ehdokkaat += [os.path.normpath(p) for p in LISATESTIT.get(moduuli.replace(os.sep, "/"), [])]
    return [p[:-3].replace(os.sep, ".") for p in ehdokkaat if os.path.exists(os.path.join(juuri, p))]


def kaikki_moduulit(juuri=JUURI):
    tulos = []
    for hak in ("agentti", "yojono", "tools"):
        polku = os.path.join(juuri, hak)
        if not os.path.isdir(polku):
            continue
        for nimi in sorted(os.listdir(polku)):
            if not nimi.endswith(".py") or nimi.startswith(("test_", "__")) or nimi == "mutantit.py":
                continue
            moduuli = hak + "/" + nimi
            if testimoduulit(moduuli, juuri):
                tulos.append(moduuli)
    return tulos


def kopioi_puu(lahde, kohde):
    def ohita(hak, nimet):
        return [n for n in nimet if n in HYLATYT_HAKEMISTOT or n.endswith(".pyc")]
    shutil.copytree(lahde, kohde, ignore=ohita)


def aja_testit(hakemisto, moduulit, aikaraja):
    """(onnistui, kesto_s, loppu). Aikaraja ylittyy = ei onnistunut."""
    alku = time.monotonic()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "-q", "-f", *moduulit], cwd=hakemisto, env=env,
                           capture_output=True, text=True, timeout=aikaraja)
        ok = p.returncode == 0
        loppu = (p.stdout + p.stderr)[-600:]
    except subprocess.TimeoutExpired:
        ok, loppu = False, "aikaraja"
    return ok, time.monotonic() - alku, loppu


def ajaa_mutantti(tyohakemisto, moduuli, lahde, mutantti, moduulit, aikaraja):
    """Kirjoittaa mutantin tyokopioon, ajaa testit, palauttaa alkuperaisen takaisin. True = kaatui."""
    polku = os.path.join(tyohakemisto, moduuli)
    with open(polku, "w", encoding="utf-8") as f:
        f.write(mutoi(lahde, mutantti["id"]))
    try:
        ok, _, _ = aja_testit(tyohakemisto, moduulit, aikaraja)
    finally:
        with open(polku, "w", encoding="utf-8") as f:
            f.write(lahde)
    return not ok


def aja_moduuli(moduuli, args, juuri=JUURI, sallitut=frozenset()):
    """Palauttaa tulos-dictin tai nostaa RuntimeErrorin, jos alkutilan testit eivat mene lapi."""
    with open(os.path.join(juuri, moduuli), encoding="utf-8") as f:
        lahde = f.read()
    moduulit = testimoduulit(moduuli, juuri)
    if not moduulit:
        raise RuntimeError("moduulille {} ei loydy testitiedostoa".format(moduuli))
    mutantit = luo_mutantit(lahde)
    if args.otos and len(mutantit) > args.otos:
        satunnainen = random.Random(args.siemen)
        mutantit = sorted(satunnainen.sample(mutantit, args.otos), key=lambda m: m["id"])
    tulos = {"moduuli": moduuli, "testit": moduulit, "mutantteja": len(mutantit),
             "kaatui": 0, "selvisi": [], "sallittu": []}
    if not mutantit:
        return tulos
    tmp = tempfile.mkdtemp(prefix="mutantit-")
    try:
        tyot = []
        for i in range(max(1, args.rinnakkain)):
            kopio = os.path.join(tmp, "k{}".format(i))
            kopioi_puu(juuri, kopio)
            tyot.append(kopio)
        ok, kesto, loppu = aja_testit(tyot[0], moduulit, args.alkuaikaraja)
        if not ok:
            raise RuntimeError("alkutilan testit eivat mene lapi ({}):\n{}".format(moduuli, loppu))
        aikaraja = max(args.vahimmaisaika, kesto * args.aikakerroin)

        vapaat = list(tyot)
        lukko = threading.Lock()

        def tyo(m):
            with lukko:
                hak = vapaat.pop()
            try:
                return m, ajaa_mutantti(hak, moduuli, lahde, m, moduulit, aikaraja)
            finally:
                with lukko:
                    vapaat.append(hak)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tyot)) as pooli:
            for m, kaatui in pooli.map(tyo, mutantit):
                if kaatui:
                    tulos["kaatui"] += 1
                    continue
                kuvaus = {"rivi": m["rivi"], "laji": m["laji"], "vanha": m["vanha"], "uusi": m["uusi"],
                          "avain": sallittu_avain(moduuli, m)}
                (tulos["sallittu"] if kuvaus["avain"] in sallitut else tulos["selvisi"]).append(kuvaus)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return tulos


def raportti(tulokset):
    rivit = []
    for t in tulokset:
        kaikki = t["mutantteja"]
        rivit.append("{}: {} mutanttia, {} kaatui, {} selvisi, {} sallittua".format(
            t["moduuli"], kaikki, t["kaatui"], len(t["selvisi"]), len(t["sallittu"])))
        for s in t["selvisi"]:
            rivit.append("  SELVISI rivi {} [{}]: {}  ->  {}".format(s["rivi"], s["laji"], s["vanha"], s["uusi"]))
            rivit.append("    sallitut-avain: " + s["avain"])
    return "\n".join(rivit)


def markdown(tulokset):
    rivit = ["| moduuli | mutantteja | kaatui | selvisi | sallittu |", "|---|---:|---:|---:|---:|"]
    for t in tulokset:
        rivit.append("| `{}` | {} | {} | {} | {} |".format(t["moduuli"], t["mutantteja"], t["kaatui"],
                                                       len(t["selvisi"]), len(t["sallittu"])))
    for t in tulokset:
        if t["selvisi"]:
            rivit += ["", "### Selviytyjat: `{}`".format(t["moduuli"]), ""]
            for s in t["selvisi"]:
                rivit.append("- rivi {} ({}): `{}` -> `{}`".format(s["rivi"], s["laji"], s["vanha"].replace("`", "'"),
                                                                    s["uusi"].replace("`", "'")))
    return "\n".join(rivit) + "\n"


def lue_argumentit(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("moduulit", nargs="*", help="esim. agentti/kulu.py")
    p.add_argument("--kaikki", action="store_true", help="kaikki moduulit, joilla on testitiedosto")
    p.add_argument("--rinnakkain", type=int, default=1, help="rinnakkaisia ajoja (jokaisella oma repokopio)")
    p.add_argument("--otos", type=int, default=0, help="aja vain N satunnaista mutanttia moduulia kohden")
    p.add_argument("--siemen", type=int, default=1, help="otoksen satunnaissiemen")
    p.add_argument("--sallitut", default=SALLITUT_OLETUS, help="vastaavien mutanttien lista")
    p.add_argument("--json", help="kirjoita tulos JSON-tiedostoon")
    p.add_argument("--markdown", help="kirjoita yhteenveto markdown-tiedostoon (esim. $GITHUB_STEP_SUMMARY)")
    p.add_argument("--listaa", action="store_true", help="tulosta moduulilista JSON:ina (matriisia varten) ja lopeta")
    p.add_argument("--ala-kaadu", action="store_true", help="selviytyjat eivat anna poistumiskoodia 1 (vain raportti)")
    p.add_argument("--alkuaikaraja", type=int, default=900, help="alkutilan testien aikaraja (s)")
    p.add_argument("--aikakerroin", type=float, default=5.0, help="mutantin aikaraja = alkutilan kesto * kerroin")
    p.add_argument("--vahimmaisaika", type=float, default=20.0, help="mutantin aikarajan alaraja (s)")
    return p.parse_args(argv)


def paa(argv=None, juuri=JUURI):
    args = lue_argumentit(argv)
    moduulit = kaikki_moduulit(juuri) if args.kaikki else args.moduulit
    if not moduulit:
        print("anna moduuleja tai --kaikki", file=sys.stderr)
        return 2
    for m in moduulit:
        if not MODUULI_NIMI.match(m) or not os.path.isfile(os.path.join(juuri, m)):
            print("VIRHE: tuntematon moduuli: {!r}".format(m), file=sys.stderr)
            return 2
    if args.listaa:
        print(json.dumps(moduulit))
        return 0
    sallitut = lue_sallitut(args.sallitut)
    tulokset = []
    try:
        for m in moduulit:
            t = aja_moduuli(m, args, juuri=juuri, sallitut=sallitut)
            tulokset.append(t)
            print(raportti([t]), flush=True)
    except RuntimeError as e:
        print("VIRHE: {}".format(e), file=sys.stderr)
        return 2
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(tulokset, f, ensure_ascii=False, indent=2)
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as f:
            f.write(markdown(tulokset))
    if args.ala_kaadu:
        return 0
    return 1 if any(t["selvisi"] for t in tulokset) else 0


if __name__ == "__main__":
    sys.exit(paa())
