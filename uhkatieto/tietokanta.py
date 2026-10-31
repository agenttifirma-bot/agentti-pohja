"""Normalisoitu SQLite: yksi taulu uhkat (lahde, id, pvm, otsikko, tagit, url) + ajokirjanpito + raakatiedostojen tiivisteet."""
import sqlite3

SKEEMA = """
CREATE TABLE IF NOT EXISTS uhkat (
  lahde TEXT NOT NULL, id TEXT NOT NULL, pvm TEXT NOT NULL, otsikko TEXT NOT NULL,
  tagit TEXT NOT NULL, url TEXT NOT NULL, haettu TEXT NOT NULL,
  PRIMARY KEY (lahde, id)
);
CREATE INDEX IF NOT EXISTS uhkat_pvm ON uhkat (pvm);
CREATE TABLE IF NOT EXISTS ajot (aika TEXT NOT NULL, lahde TEXT NOT NULL, tila TEXT NOT NULL, uudet INTEGER NOT NULL, rivit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS raaka (lahde TEXT NOT NULL, pvm TEXT NOT NULL, sha256 TEXT NOT NULL);
"""


def avaa(polku):
    yhteys = sqlite3.connect(polku)
    yhteys.executescript(SKEEMA)
    return yhteys


def tallenna(yhteys, rivit, haettu):
    """Tallentaa rivit. Duplikaatti (lahde, id) ei luo uutta rivia; tagit yhdistetaan. Palauttaa uusien rivien maaran."""
    uudet = 0
    with yhteys:
        for r in rivit:
            tagit = ",".join(r["tagit"])
            vanha = yhteys.execute("SELECT tagit FROM uhkat WHERE lahde=? AND id=?", (r["lahde"], r["id"])).fetchone()
            if vanha is None:
                yhteys.execute("INSERT INTO uhkat (lahde, id, pvm, otsikko, tagit, url, haettu) VALUES (?,?,?,?,?,?,?)",
                               (r["lahde"], r["id"], r["pvm"], r["otsikko"], tagit, r["url"], haettu))
                uudet += 1
            else:
                yhdistetty = list(dict.fromkeys([t for t in vanha[0].split(",") if t] + r["tagit"]))[:20]
                if ",".join(yhdistetty) != vanha[0]:
                    yhteys.execute("UPDATE uhkat SET tagit=? WHERE lahde=? AND id=?", (",".join(yhdistetty), r["lahde"], r["id"]))
    return uudet


def kirjaa_ajo(yhteys, aika, lahde, tila, uudet, rivit):
    with yhteys:
        yhteys.execute("INSERT INTO ajot VALUES (?,?,?,?,?)", (aika, lahde, tila, uudet, rivit))


def viimeinen_tiiviste(yhteys, lahde):
    r = yhteys.execute("SELECT sha256 FROM raaka WHERE lahde=? ORDER BY rowid DESC LIMIT 1", (lahde,)).fetchone()
    return r[0] if r else None


def kirjaa_tiiviste(yhteys, lahde, pvm, sha):
    with yhteys:
        yhteys.execute("INSERT INTO raaka VALUES (?,?,?)", (lahde, pvm, sha))
