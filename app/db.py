"""Datenbank (SQLite): Verbindung, Schema-Migrationen, Zeit und Protokoll (Bauweise wie Lernbuero MT).

Jede Aenderung an gemeinsamen Grunddaten landet zusaetzlich als Zeile in `protokoll` (nur anhaengen, nie aendern), damit
der Admin sieht, wer wann was geaendert hat.
"""
import datetime
import json
import os
import sqlite3

try:
    from zoneinfo import ZoneInfo
    ZONE = ZoneInfo("Europe/Berlin")
except Exception:   # Windows ohne tzdata (lokales Testen): Ortszeit des Rechners
    ZONE = None

DATEINAME = "lehrerkalender.sqlite"


def jetzt():
    """Aktuelle Zeit in Berlin als ISO-Text ohne Zeitzone, sekundengenau (so steht sie in der Datenbank)."""
    t = datetime.datetime.now(ZONE) if ZONE else datetime.datetime.now()
    return t.replace(tzinfo=None, microsecond=0).isoformat()


def heute():
    return datetime.date.fromisoformat(jetzt()[:10])


def verbinden(pfad):
    con = sqlite3.connect(pfad, timeout=10, isolation_level=None)   # Autocommit; Transaktionen mit transaktion()
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


class transaktion:
    """with transaktion(con): ... -> BEGIN IMMEDIATE / COMMIT, bei Fehler ROLLBACK."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, art, wert, spur):
        self.con.execute("COMMIT" if art is None else "ROLLBACK")
        return False


MIGRATIONEN = [
    # 1: Stufe A: Konten mit Einladung und zweitem Faktor, Grunddaten (Bildungsgaenge, Stufen, Lernfelder/Module,
    #    Zeitraster, Ferien, Klassen), Notenschluessel, Protokoll
    """
    CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
    CREATE TABLE lehrkraft (
        id INTEGER PRIMARY KEY,
        kuerzel TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        rolle TEXT NOT NULL CHECK (rolle IN ('admin', 'lehrkraft')),
        pw TEXT NOT NULL,
        pw_vorlaeufig INTEGER NOT NULL DEFAULT 1,
        gesperrt INTEGER NOT NULL DEFAULT 0,
        stand INTEGER NOT NULL DEFAULT 1,
        totp TEXT NOT NULL DEFAULT '',
        totp_zuletzt INTEGER NOT NULL DEFAULT 0,
        ersatzcodes TEXT NOT NULL DEFAULT '[]',
        erstellt TEXT NOT NULL);
    CREATE TABLE abgemeldet (signatur TEXT PRIMARY KEY, ablauf INTEGER NOT NULL);
    CREATE TABLE einladung (
        id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        rolle TEXT NOT NULL CHECK (rolle IN ('admin', 'lehrkraft')),
        gueltig_bis TEXT NOT NULL,
        notiz TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL,
        erstellt_von INTEGER REFERENCES lehrkraft(id),
        eingeloest TEXT,
        eingeloest_von INTEGER REFERENCES lehrkraft(id));
    CREATE TABLE bildungsgang (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        kuerzel TEXT NOT NULL DEFAULT '',
        einheit TEXT NOT NULL DEFAULT 'lernfeld' CHECK (einheit IN ('lernfeld', 'modul')),
        aktiv INTEGER NOT NULL DEFAULT 1,
        reihenfolge INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE stufe (
        id INTEGER PRIMARY KEY,
        bildungsgang_id INTEGER NOT NULL REFERENCES bildungsgang(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        UNIQUE (bildungsgang_id, name));
    CREATE TABLE lernfeld (
        id INTEGER PRIMARY KEY,
        bildungsgang_id INTEGER NOT NULL REFERENCES bildungsgang(id) ON DELETE CASCADE,
        stufe_id INTEGER REFERENCES stufe(id) ON DELETE SET NULL,
        nummer TEXT NOT NULL,
        name TEXT NOT NULL,
        stunden INTEGER NOT NULL DEFAULT 0,
        aktiv INTEGER NOT NULL DEFAULT 1,
        UNIQUE (bildungsgang_id, nummer));
    CREATE TABLE lernfeld_anteil (
        lernfeld_id INTEGER NOT NULL REFERENCES lernfeld(id) ON DELETE CASCADE,
        stufe_id INTEGER NOT NULL REFERENCES stufe(id) ON DELETE CASCADE,
        stunden INTEGER NOT NULL,
        PRIMARY KEY (lernfeld_id, stufe_id));
    CREATE TABLE zeitblock (
        id INTEGER PRIMARY KEY,
        bildungsgang_id INTEGER REFERENCES bildungsgang(id) ON DELETE CASCADE,
        bezeichnung TEXT NOT NULL,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL);
    CREATE TABLE ferien (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        quelle TEXT NOT NULL DEFAULT 'hand' CHECK (quelle IN ('hand', 'abo')));
    CREATE TABLE notenschluessel (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        system TEXT NOT NULL CHECK (system IN ('tendenz', 'zehntel', 'punkte')),
        art TEXT NOT NULL CHECK (art IN ('konferenz', 'eigen')),
        bildungsgang_id INTEGER REFERENCES bildungsgang(id) ON DELETE SET NULL,
        besitzer_id INTEGER REFERENCES lehrkraft(id) ON DELETE CASCADE,
        grenzen TEXT NOT NULL,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL);
    CREATE UNIQUE INDEX ein_konferenzschluessel ON notenschluessel (bildungsgang_id) WHERE art = 'konferenz';
    CREATE TABLE klasse (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        bildungsgang_id INTEGER NOT NULL REFERENCES bildungsgang(id),
        stufe_id INTEGER REFERENCES stufe(id) ON DELETE SET NULL,
        notenschluessel_id INTEGER REFERENCES notenschluessel(id) ON DELETE SET NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE protokoll (
        id INTEGER PRIMARY KEY,
        zeit TEXT NOT NULL,
        wer TEXT NOT NULL,
        art TEXT NOT NULL,
        daten TEXT NOT NULL DEFAULT '{}')
    """,
    # 2: Stufe B: Stundenplan je Lehrkraft mit Versionen (gelten ab einem Datum) und A/B-Wochen, einmalige Aenderungen
    #    (Ausfall, vertreten werden, Verschieben, Vertretung, Zusatzstunde), eigene Termine und Merker.
    #    Bloecke stehen mit ihren Uhrzeiten drin (nicht als Verweis), damit alte Versionen ihre Zeiten behalten.
    """
    CREATE TABLE stundenplan_version (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        ab TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL,
        UNIQUE (lehrkraft_id, ab));
    CREATE TABLE stundenplan_eintrag (
        id INTEGER PRIMARY KEY,
        version_id INTEGER NOT NULL REFERENCES stundenplan_version(id) ON DELETE CASCADE,
        wochentag INTEGER NOT NULL CHECK (wochentag BETWEEN 1 AND 6),
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        woche TEXT NOT NULL DEFAULT 'alle' CHECK (woche IN ('alle', 'A', 'B')),
        UNIQUE (version_id, wochentag, beginn, woche));
    CREATE TABLE aenderung (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('ausfall', 'vertreten', 'verschoben', 'vertretung', 'zusatz')),
        datum TEXT NOT NULL,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL,
        klasse_id INTEGER REFERENCES klasse(id),
        klasse_text TEXT NOT NULL DEFAULT '',
        ziel_datum TEXT,
        ziel_beginn TEXT,
        ziel_ende TEXT,
        wer TEXT NOT NULL DEFAULT '',
        grund TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL);
    CREATE INDEX aenderung_datum ON aenderung (lehrkraft_id, datum);
    CREATE INDEX aenderung_ziel ON aenderung (lehrkraft_id, ziel_datum);
    CREATE TABLE termin (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('dienst', 'privat', 'merker')),
        datum TEXT NOT NULL,
        bis TEXT,
        beginn TEXT,
        ende TEXT,
        klasse_id INTEGER REFERENCES klasse(id) ON DELETE CASCADE,
        titel TEXT NOT NULL,
        notiz TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL);
    CREATE INDEX termin_datum ON termin (lehrkraft_id, datum)
    """,
    # 3: Gruppen einer Klasse, die jede Lehrkraft fuer sich anlegt (z. B. Gr. 1 / Gr. 2). Ein Stundenplan-Eintrag oder
    #    eine Zusatzstunde ohne Gruppe gilt fuer die ganze Klasse (in der Planung ein eigener Strang).
    """
    CREATE TABLE gruppe (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        UNIQUE (lehrkraft_id, klasse_id, name));
    ALTER TABLE stundenplan_eintrag ADD COLUMN gruppe_id INTEGER REFERENCES gruppe(id);
    ALTER TABLE aenderung ADD COLUMN gruppe_id INTEGER REFERENCES gruppe(id)
    """,
    # 4: Stufe C1: Schuljahre (Admin), Bibliothek (Lernsituationen und Themen je Lernfeld, im Bildungsgang sichtbar),
    #    Themenfolge je Strang (Klasse + Gruppe/ganze Klasse) und Schuljahr, optionales Lernfeld am Stundenplan-Block
    """
    CREATE TABLE schuljahr (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL);
    CREATE TABLE baustein (
        id INTEGER PRIMARY KEY,
        lernfeld_id INTEGER NOT NULL REFERENCES lernfeld(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('ls', 'thema')),
        ls_id INTEGER REFERENCES baustein(id) ON DELETE CASCADE,
        titel TEXT NOT NULL,
        bloecke INTEGER NOT NULL DEFAULT 0,
        hinweis TEXT NOT NULL DEFAULT '',
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        besitzer_id INTEGER REFERENCES lehrkraft(id) ON DELETE SET NULL,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL);
    CREATE INDEX baustein_lf ON baustein (lernfeld_id, ls_id);
    CREATE TABLE plan_thema (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id),
        schuljahr_id INTEGER NOT NULL REFERENCES schuljahr(id),
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        titel TEXT NOT NULL,
        bloecke INTEGER NOT NULL DEFAULT 1,
        lernfeld_id INTEGER REFERENCES lernfeld(id) ON DELETE SET NULL,
        ls_titel TEXT NOT NULL DEFAULT '',
        baustein_id INTEGER REFERENCES baustein(id) ON DELETE SET NULL,
        hinweis TEXT NOT NULL DEFAULT '',
        fest_datum TEXT,
        fest_beginn TEXT,
        erstellt TEXT NOT NULL);
    CREATE INDEX plan_thema_strang ON plan_thema (lehrkraft_id, klasse_id, schuljahr_id);
    ALTER TABLE stundenplan_eintrag ADD COLUMN lernfeld_id INTEGER REFERENCES lernfeld(id) ON DELETE SET NULL
    """,
    # 5: Stufe C2: Ist-Stand je gehaltenem Block (wie geplant / braucht 1 Block mehr / schon fertig). Eine Lehrkraft
    #    haelt zu einer Zeit nur eine Stunde, deshalb ist (Lehrkraft, Datum, Beginn) eindeutig.
    """
    CREATE TABLE ist (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        beginn TEXT NOT NULL,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id),
        thema_id INTEGER REFERENCES plan_thema(id) ON DELETE SET NULL,
        stand TEXT NOT NULL CHECK (stand IN ('ok', 'mehr', 'fertig')),
        geaendert TEXT NOT NULL,
        UNIQUE (lehrkraft_id, datum, beginn))
    """,
    # 6: Vertretung, die das geplante Thema weiterfuehrt: die Stunde zaehlt dann in der Planung als gehalten
    """
    ALTER TABLE aenderung ADD COLUMN thema_weiter INTEGER NOT NULL DEFAULT 0
    """,
]


def migrieren(con):
    """Bringt das Schema auf den neuesten Stand (PRAGMA user_version = Anzahl angewandter Migrationen).
    Ein Eintrag als Tupel (OHNE_FK, sql) baut eine Tabelle neu auf: dafuer ist die Fremdschluessel-Pruefung kurz aus,
    danach muss PRAGMA foreign_key_check leer sein, sonst wird alles zurueckgerollt."""
    stand = con.execute("PRAGMA user_version").fetchone()[0]
    for nummer in range(stand, len(MIGRATIONEN)):
        eintrag = MIGRATIONEN[nummer]
        ohne_fk = isinstance(eintrag, tuple)
        sql = eintrag[1] if ohne_fk else eintrag
        if ohne_fk:
            con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN IMMEDIATE")
        try:
            for befehl in sql.split(";"):
                if befehl.strip():
                    con.execute(befehl)
            if ohne_fk and con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migration %d: Fremdschluessel verletzt" % (nummer + 1))
            con.execute("PRAGMA user_version = %d" % (nummer + 1))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            if ohne_fk:
                con.execute("PRAGMA foreign_keys = ON")


def pfad(daten_dir):
    return os.path.join(daten_dir, DATEINAME)


def oeffnen(daten_dir):
    """Datenbank im Datenordner oeffnen und migrieren."""
    os.makedirs(daten_dir, exist_ok=True)
    con = verbinden(pfad(daten_dir))
    con.execute("PRAGMA journal_mode = WAL")
    migrieren(con)
    return con


def protokoll(con, wer, art, **daten):
    """Haengt eine Zeile ans Aenderungsprotokoll. wer: Kuerzel (oder 'system')."""
    con.execute("INSERT INTO protokoll (zeit, wer, art, daten) VALUES (?, ?, ?, ?)",
                (jetzt(), wer, art, json.dumps(daten, ensure_ascii=False)))


def einstellung(con, schluessel, vorgabe=None):
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,)).fetchone()
    return zeile[0] if zeile else vorgabe


def einstellung_setzen(con, schluessel, wert):
    con.execute("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert", (schluessel, wert))
