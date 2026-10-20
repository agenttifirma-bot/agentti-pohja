"""Tapahtumaloki (SQLite): agenttien ja tyon havainnot, ehdotukset ja Tonyn palaute.

Tarkoitus: oppiva silmukka (doc 34). Loki on vain lisaava: `tapahtuma` ja `palaute` -riveja ei
voi muokata (trigger estaa UPDATE:n); vain vanhentuminen poistaa (`siivoa`). `ehdotus`-rivin
ainoat muuttuvat kentat ovat tila ja tulos.

Turva: tiedostoon 0600; salaisuuden nakoiset merkkijonot poistetaan ennen tallennusta; tiedot_json
rajataan; ei verkkoa; vain stdlib. Arkaluonteisia aiheita (perhe, terveys, talous) ei kerata:
kutsuja valitsee mita kirjaa.
"""
import json
import os
import re
import sqlite3
import time

SKEEMA = """
CREATE TABLE IF NOT EXISTS tapahtuma(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  aika REAL NOT NULL, lahde TEXT NOT NULL, agentti TEXT NOT NULL, tyyppi TEXT NOT NULL,
  tulos TEXT NOT NULL, kulu_usd REAL, tiedot_json TEXT);
CREATE TABLE IF NOT EXISTS ehdotus(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  aika REAL NOT NULL, otsikko TEXT NOT NULL, perustelu TEXT NOT NULL, esitutkimus TEXT,
  mittari TEXT, tila TEXT NOT NULL DEFAULT 'ehdotettu', tulos TEXT);
CREATE TABLE IF NOT EXISTS palaute(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ehdotus_id INTEGER NOT NULL REFERENCES ehdotus(id), aika REAL NOT NULL,
  paatos TEXT NOT NULL, huomio TEXT);
CREATE INDEX IF NOT EXISTS tapahtuma_aika ON tapahtuma(aika);
CREATE TRIGGER IF NOT EXISTS tapahtuma_ei_muutosta BEFORE UPDATE ON tapahtuma
  BEGIN SELECT RAISE(ABORT, 'tapahtumaloki on vain lisaava'); END;
CREATE TRIGGER IF NOT EXISTS palaute_ei_muutosta BEFORE UPDATE ON palaute
  BEGIN SELECT RAISE(ABORT, 'palaute on vain lisaava'); END;
"""

TILAT = ("ehdotettu", "kokeilussa", "onnistui", "epaonnistui", "hyvaksytty", "hylatty")
PAATOKSET = ("hyvaksy", "hylkaa")
TIEDOT_MAX = 4000
TEKSTI_MAX = 1000
SALAISUUS = re.compile(
    r"(sk-[A-Za-z0-9_-]{10,}|Bearer\s+\S+|\d{8,}:[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,})")


def puhdista(teksti, raja=TEKSTI_MAX):
    """Poistaa salaisuuden nakoiset osat ja ohjausmerkit, rajaa pituuden."""
    if teksti is None:
        return None
    siisti = SALAISUUS.sub("[poistettu]", str(teksti))
    siisti = "".join(c for c in siisti if c in "\n\t" or (c >= " " and c != "\x7f"))
    return siisti.strip()[:raja]


def avaa(polku):
    """Avaa (tai luo) tietokannan; uusi tiedosto saa oikeudet 0600."""
    uusi = polku != ":memory:" and not os.path.exists(polku)
    if uusi:
        os.close(os.open(polku, os.O_CREAT | os.O_WRONLY, 0o600))
    yht = sqlite3.connect(polku)
    yht.execute("PRAGMA foreign_keys = ON")
    yht.executescript(SKEEMA)
    return yht


def kirjaa(yht, lahde, agentti, tyyppi, tulos, kulu_usd=None, tiedot=None, nyt=None):
    """Lisaa tapahtuman ja palauttaa sen id:n. tiedot: JSON-muotoon sopiva sanakirja."""
    for nimi, arvo in (("lahde", lahde), ("agentti", agentti), ("tyyppi", tyyppi), ("tulos", tulos)):
        if not isinstance(arvo, str) or not arvo.strip():
            raise ValueError("%s puuttuu" % nimi)
    if kulu_usd is not None and (isinstance(kulu_usd, bool) or not isinstance(kulu_usd, (int, float)) or kulu_usd < 0):
        raise ValueError("kulu_usd")
    teksti = None
    if tiedot is not None:
        teksti = puhdista(json.dumps(tiedot, ensure_ascii=True, sort_keys=True), TIEDOT_MAX)
    rivi = (time.time() if nyt is None else nyt, puhdista(lahde, 60), puhdista(agentti, 60),
            puhdista(tyyppi, 60), puhdista(tulos, 200), kulu_usd, teksti)
    with yht:
        return yht.execute("INSERT INTO tapahtuma(aika,lahde,agentti,tyyppi,tulos,kulu_usd,tiedot_json) "
                           "VALUES(?,?,?,?,?,?,?)", rivi).lastrowid


def ehdota(yht, otsikko, perustelu, esitutkimus=None, mittari=None, nyt=None):
    for nimi, arvo in (("otsikko", otsikko), ("perustelu", perustelu)):
        if not isinstance(arvo, str) or not arvo.strip():
            raise ValueError("%s puuttuu" % nimi)
    with yht:
        return yht.execute("INSERT INTO ehdotus(aika,otsikko,perustelu,esitutkimus,mittari) VALUES(?,?,?,?,?)",
                           (time.time() if nyt is None else nyt, puhdista(otsikko, 200), puhdista(perustelu),
                            puhdista(esitutkimus), puhdista(mittari))).lastrowid


def paivita_ehdotus(yht, ehdotus_id, tila=None, tulos=None):
    """Muuttaa vain tilan ja/tai tuloksen. Tuntematon id tai tila nostaa ValueErrorin."""
    if tila is not None and tila not in TILAT:
        raise ValueError("tila: " + " | ".join(TILAT))
    with yht:
        if not yht.execute("SELECT 1 FROM ehdotus WHERE id=?", (ehdotus_id,)).fetchone():
            raise ValueError("ehdotusta ei ole")
        if tila is not None:
            yht.execute("UPDATE ehdotus SET tila=? WHERE id=?", (tila, ehdotus_id))
        if tulos is not None:
            yht.execute("UPDATE ehdotus SET tulos=? WHERE id=?", (puhdista(tulos), ehdotus_id))


def kirjaa_palaute(yht, ehdotus_id, paatos, huomio=None, nyt=None):
    """Tonyn paatos (hyvaksy|hylkaa); asettaa samalla ehdotuksen tilan."""
    if paatos not in PAATOKSET:
        raise ValueError("paatos: hyvaksy | hylkaa")
    paivita_ehdotus(yht, ehdotus_id, tila="hyvaksytty" if paatos == "hyvaksy" else "hylatty")
    with yht:
        return yht.execute("INSERT INTO palaute(ehdotus_id,aika,paatos,huomio) VALUES(?,?,?,?)",
                           (ehdotus_id, time.time() if nyt is None else nyt, paatos, puhdista(huomio))).lastrowid


def siivoa(yht, ika_paivaa=90, nyt=None):
    """Poistaa vanhat tapahtumat (raakadata vanhenee). Palauttaa poistettujen maaran."""
    raja = (time.time() if nyt is None else nyt) - ika_paivaa * 86400
    with yht:
        return yht.execute("DELETE FROM tapahtuma WHERE aika < ?", (raja,)).rowcount


def yhteenveto(yht, paivaa=7, nyt=None):
    """Viikkoraportin raakaluvut: tapahtumat tyypeittain, kulu, ehdotusten tilat ja hyvaksymis-%."""
    alku = (time.time() if nyt is None else nyt) - paivaa * 86400
    tyypit = {t: n for t, n in yht.execute(
        "SELECT tyyppi||'/'||tulos, COUNT(*) FROM tapahtuma WHERE aika>=? GROUP BY 1", (alku,))}
    kulu = yht.execute("SELECT COALESCE(SUM(kulu_usd),0) FROM tapahtuma WHERE aika>=?", (alku,)).fetchone()[0]
    tilat = {t: n for t, n in yht.execute("SELECT tila, COUNT(*) FROM ehdotus GROUP BY tila")}
    paatetyt = tilat.get("hyvaksytty", 0) + tilat.get("hylatty", 0)
    osuus = round(100.0 * tilat.get("hyvaksytty", 0) / paatetyt, 1) if paatetyt else None
    return {"tapahtumat": tyypit, "kulu_usd": round(kulu, 6), "ehdotukset": tilat, "hyvaksymis_pros": osuus}


def main(argv=None):
    """Komentorivi: kirjaa | yhteenveto. Tietokannan polku: ymparistomuuttuja TAPAHTUMALOKI.

        python3 -m agentti.tapahtumaloki kirjaa LAHDE AGENTTI TYYPPI TULOS [KULU_USD]
        python3 -m agentti.tapahtumaloki yhteenveto [PAIVAA]
    """
    import sys
    argv = sys.argv[1:] if argv is None else argv
    polku = os.environ.get("TAPAHTUMALOKI")
    if not polku or not argv:
        print("kaytto: TAPAHTUMALOKI=polku python3 -m agentti.tapahtumaloki kirjaa|yhteenveto ...", file=sys.stderr)
        return 2
    yht = avaa(polku)
    try:
        if argv[0] == "kirjaa" and len(argv) in (5, 6):
            kulu = float(argv[5]) if len(argv) == 6 else None
            print("kirjattu: %d" % kirjaa(yht, argv[1], argv[2], argv[3], argv[4], kulu_usd=kulu))
            return 0
        if argv[0] == "yhteenveto" and len(argv) in (1, 2):
            print(json.dumps(yhteenveto(yht, int(argv[1]) if len(argv) == 2 else 7), sort_keys=True))
            return 0
    except ValueError as e:
        print("tapahtumaloki: %s" % e, file=sys.stderr)
        return 2
    finally:
        yht.close()
    print("tapahtumaloki: tuntematon komento", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
