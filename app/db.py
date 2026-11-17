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
    # 7: Unterrichtszeitraum einer Klasse (z. B. Ausschulung der Fachstufe 3 vor dem Halbjahr). Leer = ganzes Schuljahr.
    """
    ALTER TABLE klasse ADD COLUMN beginn TEXT;
    ALTER TABLE klasse ADD COLUMN ende TEXT
    """,
    # 8: Sonderstundenplan (z. B. Einfuehrungswoche): eine Version mit Enddatum gilt nur von ab bis sonder_bis und dort
    #    statt des normalen Plans. Ein Sonderplan darf am selben Tag beginnen wie eine normale Version, deshalb faellt
    #    UNIQUE (lehrkraft_id, ab) weg (die Regeln prueft jetzt der Code).
    (True, """
    CREATE TABLE stundenplan_version_neu (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        ab TEXT NOT NULL,
        sonder_bis TEXT,
        name TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL);
    INSERT INTO stundenplan_version_neu (id, lehrkraft_id, ab, name, erstellt) SELECT id, lehrkraft_id, ab, name, erstellt FROM stundenplan_version;
    DROP TABLE stundenplan_version;
    ALTER TABLE stundenplan_version_neu RENAME TO stundenplan_version;
    CREATE INDEX stundenplan_version_lk ON stundenplan_version (lehrkraft_id, ab)
    """),
    # 9: Kalender-Abos (ICS-Links): der Schule (lehrkraft_id NULL, vom Admin; art ferien oder termine) und eigene
    #    (z. B. Outlook). Abgerufene Termine liegen in abo_termin, Ferien aus einem Abo in ferien mit abo_id.
    """
    CREATE TABLE kalender_abo (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER REFERENCES lehrkraft(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('ferien', 'termine')),
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        abgerufen TEXT,
        fehler TEXT NOT NULL DEFAULT '',
        anzahl INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL);
    CREATE TABLE abo_termin (
        id INTEGER PRIMARY KEY,
        abo_id INTEGER NOT NULL REFERENCES kalender_abo(id) ON DELETE CASCADE,
        titel TEXT NOT NULL,
        datum TEXT NOT NULL,
        bis TEXT,
        beginn TEXT,
        ende TEXT,
        ort TEXT NOT NULL DEFAULT '');
    CREATE INDEX abo_termin_datum ON abo_termin (abo_id, datum);
    ALTER TABLE ferien ADD COLUMN abo_id INTEGER REFERENCES kalender_abo(id) ON DELETE CASCADE
    """,
    # 10: Stufe D1: Schuelerlisten (privat je Lehrkraft und Klasse), Feedbackbogen-Vorlagen, Pruefungen (fester Termin,
    #     belegt als festgesetztes Thema Bloecke in der Planung, oder Fenster mit Frist) und Bewertungen. Gespeichert
    #     werden Punkte bzw. Stufen; Prozent und Note entstehen erst ueber den Notenschluessel.
    """
    CREATE TABLE schueler (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id) ON DELETE SET NULL,
        nachname TEXT NOT NULL,
        vorname TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE INDEX schueler_klasse ON schueler (lehrkraft_id, klasse_id);
    CREATE TABLE vorlage (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        art TEXT NOT NULL,
        struktur TEXT NOT NULL,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL);
    CREATE TABLE pruefung (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id),
        schuljahr_id INTEGER NOT NULL REFERENCES schuljahr(id),
        titel TEXT NOT NULL,
        art TEXT NOT NULL,
        form TEXT NOT NULL CHECK (form IN ('termin', 'fenster')),
        datum TEXT,
        beginn TEXT,
        bloecke INTEGER NOT NULL DEFAULT 1,
        fenster_von TEXT,
        fenster_bis TEXT,
        erfassung TEXT NOT NULL CHECK (erfassung IN ('aufgaben', 'gesamt', 'bogen')),
        struktur TEXT NOT NULL DEFAULT '{"bereiche": []}',
        max_punkte REAL,
        notenschluessel_id INTEGER REFERENCES notenschluessel(id) ON DELETE SET NULL,
        lernfeld_id INTEGER REFERENCES lernfeld(id) ON DELETE SET NULL,
        stand TEXT NOT NULL DEFAULT 'geplant',
        schluessel_fest TEXT,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL);
    CREATE INDEX pruefung_strang ON pruefung (lehrkraft_id, klasse_id, schuljahr_id);
    CREATE TABLE bewertung (
        id INTEGER PRIMARY KEY,
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        werte TEXT NOT NULL DEFAULT '{}',
        fehlt INTEGER NOT NULL DEFAULT 0,
        notiz TEXT NOT NULL DEFAULT '',
        geaendert TEXT NOT NULL,
        UNIQUE (pruefung_id, schueler_id));
    ALTER TABLE plan_thema ADD COLUMN pruefung_id INTEGER REFERENCES pruefung(id) ON DELETE CASCADE
    """,
    # 11: Thema ist der Ordner (mit Umfang als Budget), Lernsituationen liegen darin und werden zum Thema entwickelt.
    #     Planung: neue Tabelle plan_ls; die alte Zuordnung "Thema gehoert zu LS" (ls_titel) entfaellt, Eintraege, die
    #     als ganze LS uebernommen wurden (titel = ls_titel), sind jetzt Themen. Bibliothek: ls_id heisst eltern_id, die
    #     Arten werden getauscht (bisherige LS ohne Eltern -> Thema, bisherige Themen in einer LS -> LS).
    """
    CREATE TABLE plan_ls (
        id INTEGER PRIMARY KEY,
        thema_id INTEGER NOT NULL REFERENCES plan_thema(id) ON DELETE CASCADE,
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        titel TEXT NOT NULL,
        bloecke INTEGER NOT NULL DEFAULT 1,
        hinweis TEXT NOT NULL DEFAULT '',
        baustein_id INTEGER REFERENCES baustein(id) ON DELETE SET NULL,
        erstellt TEXT NOT NULL);
    CREATE INDEX plan_ls_thema ON plan_ls (thema_id, reihenfolge);
    UPDATE plan_thema SET ls_titel = '' WHERE ls_titel = titel;
    ALTER TABLE baustein RENAME COLUMN ls_id TO eltern_id;
    UPDATE baustein SET art = 'thema' WHERE art = 'ls' AND eltern_id IS NULL;
    UPDATE baustein SET art = 'ls' WHERE art = 'thema' AND eltern_id IS NOT NULL
    """,
    # 12: Gruppen sind keine eigenen Planungsstraenge mehr: eine Themenfolge je Klasse, Gruppenstunden desselben Tages
    #     bilden gemeinsam einen Schritt. Bisherige Gruppen-Themen und -Pruefungen werden verworfen (so entschieden).
    #     Pruefungen schreiben zusammen (ein Termin) oder getrennt (Termin je Gruppe in pruefung_termin).
    """
    DELETE FROM plan_ls WHERE thema_id IN (SELECT id FROM plan_thema WHERE gruppe_id IS NOT NULL
        OR pruefung_id IN (SELECT id FROM pruefung WHERE gruppe_id IS NOT NULL));
    DELETE FROM plan_thema WHERE gruppe_id IS NOT NULL OR pruefung_id IN (SELECT id FROM pruefung WHERE gruppe_id IS NOT NULL);
    DELETE FROM bewertung WHERE pruefung_id IN (SELECT id FROM pruefung WHERE gruppe_id IS NOT NULL);
    DELETE FROM pruefung WHERE gruppe_id IS NOT NULL;
    ALTER TABLE pruefung ADD COLUMN teilung TEXT NOT NULL DEFAULT 'zusammen';
    CREATE TABLE pruefung_termin (
        id INTEGER PRIMARY KEY,
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        gruppe_id INTEGER NOT NULL REFERENCES gruppe(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        beginn TEXT NOT NULL,
        UNIQUE (pruefung_id, gruppe_id))
    """,
    # 13: Stufe D2a: Erfassung "checkliste" (Laborreihen: Versuche mit Haken und Punkten). Die Pruefungstabelle wird ohne
    #     festen CHECK fuer die Erfassung neu aufgebaut (geprueft wird im Code). Teams je Pruefung: Bereiche mit
    #     "team": true gelten fuer alle Mitglieder (Werte in pruefung_team.werte).
    (True, """
    CREATE TABLE pruefung_neu (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id),
        schuljahr_id INTEGER NOT NULL REFERENCES schuljahr(id),
        titel TEXT NOT NULL,
        art TEXT NOT NULL,
        form TEXT NOT NULL CHECK (form IN ('termin', 'fenster')),
        datum TEXT,
        beginn TEXT,
        bloecke INTEGER NOT NULL DEFAULT 1,
        fenster_von TEXT,
        fenster_bis TEXT,
        erfassung TEXT NOT NULL,
        struktur TEXT NOT NULL DEFAULT '{"bereiche": []}',
        max_punkte REAL,
        notenschluessel_id INTEGER REFERENCES notenschluessel(id) ON DELETE SET NULL,
        lernfeld_id INTEGER REFERENCES lernfeld(id) ON DELETE SET NULL,
        stand TEXT NOT NULL DEFAULT 'geplant',
        schluessel_fest TEXT,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL,
        teilung TEXT NOT NULL DEFAULT 'zusammen');
    INSERT INTO pruefung_neu (id, lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, titel, art, form, datum, beginn, bloecke, fenster_von,
        fenster_bis, erfassung, struktur, max_punkte, notenschluessel_id, lernfeld_id, stand, schluessel_fest, erstellt, geaendert, teilung)
        SELECT id, lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, titel, art, form, datum, beginn, bloecke, fenster_von,
        fenster_bis, erfassung, struktur, max_punkte, notenschluessel_id, lernfeld_id, stand, schluessel_fest, erstellt, geaendert, teilung
        FROM pruefung;
    DROP TABLE pruefung;
    ALTER TABLE pruefung_neu RENAME TO pruefung;
    CREATE INDEX pruefung_strang ON pruefung (lehrkraft_id, klasse_id, schuljahr_id);
    CREATE TABLE pruefung_team (
        id INTEGER PRIMARY KEY,
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        reihenfolge INTEGER NOT NULL DEFAULT 0,
        werte TEXT NOT NULL DEFAULT '{}',
        geaendert TEXT NOT NULL);
    CREATE TABLE pruefung_team_mitglied (
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES pruefung_team(id) ON DELETE CASCADE,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        PRIMARY KEY (pruefung_id, schueler_id))
    """),
    # 14: Stufe D2b Pruefungsmodus: Einstellungen je Pruefung (Minuten je Schueler, Vorwarnung, Gesamtzeit, Fragen je
    #     Schueler, Gewicht der Fragen), Beginn/Ende je Schueler (Dauer), Fragenpool und Protokoll der gezogenen bzw.
    #     spontanen Fragen mit Einschaetzung (Stufe 0-4).
    """
    ALTER TABLE pruefung ADD COLUMN einstellungen TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE bewertung ADD COLUMN beginn TEXT;
    ALTER TABLE bewertung ADD COLUMN ende TEXT;
    CREATE TABLE pruefung_frage (
        id INTEGER PRIMARY KEY,
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        kategorie TEXT NOT NULL DEFAULT '',
        reihenfolge INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE pruefung_protokoll (
        id INTEGER PRIMARY KEY,
        pruefung_id INTEGER NOT NULL REFERENCES pruefung(id) ON DELETE CASCADE,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        frage_id INTEGER REFERENCES pruefung_frage(id) ON DELETE SET NULL,
        text TEXT NOT NULL,
        stufe INTEGER,
        zeit TEXT NOT NULL);
    CREATE INDEX pruefung_protokoll_schueler ON pruefung_protokoll (pruefung_id, schueler_id)
    """,
    # 15: Stufe F1 Formularcenter: Unterschrift und Paraphe je Konto (gezeichnet, PNG), Schul-Vorlagen der Formulare
    #     (vom Admin hochgeladen, nicht im Repo) und die Ablage der erzeugten Formulare mit Stand.
    """
    ALTER TABLE lehrkraft ADD COLUMN unterschrift BLOB;
    ALTER TABLE lehrkraft ADD COLUMN paraphe BLOB;
    CREATE TABLE formularvorlage (
        art TEXT PRIMARY KEY,
        pdf BLOB NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        hochgeladen TEXT NOT NULL);
    CREATE TABLE formular (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        art TEXT NOT NULL,
        betrifft TEXT NOT NULL DEFAULT '',
        von TEXT,
        bis TEXT,
        daten TEXT NOT NULL DEFAULT '{}',
        pdf BLOB NOT NULL,
        stand TEXT NOT NULL DEFAULT 'erstellt',
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL);
    CREATE INDEX formular_lehrkraft ON formular (lehrkraft_id, von)
    """,
    # 16: Stufe F2 Unterrichtsbesuche (aus dem alten Lehrerkalender, Schema wie dort): Einstellungen, Kategorien, Phasen,
    #     Beratungsschwerpunkte, Anwaerter, Besuche mit Schwerpunkten, Eintraege; Fotos/Skizzen als Blob. Das Modul
    #     schaltet jede Lehrkraft fuer sich ein (lehrkraft.ub_an).
    """
    ALTER TABLE lehrkraft ADD COLUMN ub_an INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE ub_einstellung (
        lehrkraft_id INTEGER PRIMARY KEY REFERENCES lehrkraft(id) ON DELETE CASCADE,
        standard_ordnung TEXT NOT NULL DEFAULT 'chronologisch');
    CREATE TABLE ub_kategorie (
        id INTEGER PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT 'auge', farbe TEXT NOT NULL DEFAULT '#00639C',
        spalte TEXT NOT NULL DEFAULT 'verlauf', position INTEGER NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE ub_phase (
        id INTEGER PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE ub_kriterium (
        id INTEGER PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE ub_anwaerter (
        id INTEGER PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '', faecher TEXT NOT NULL DEFAULT '', seminar TEXT NOT NULL DEFAULT '',
        notiz TEXT NOT NULL DEFAULT '', aktiv INTEGER NOT NULL DEFAULT 1, erstellt TEXT NOT NULL);
    CREATE TABLE ub_besuch (
        id INTEGER PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        anwaerter_id INTEGER NOT NULL REFERENCES ub_anwaerter(id) ON DELETE CASCADE,
        datum TEXT NOT NULL DEFAULT '', beginn TEXT NOT NULL DEFAULT '', ende TEXT NOT NULL DEFAULT '',
        klasse TEXT NOT NULL DEFAULT '', raum TEXT NOT NULL DEFAULT '', thema TEXT NOT NULL DEFAULT '',
        lernziele TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'geplant', reflexion TEXT NOT NULL DEFAULT '',
        vereinbarungen TEXT NOT NULL DEFAULT '', erstellt TEXT NOT NULL, geaendert TEXT NOT NULL);
    CREATE INDEX ub_besuch_lehrkraft ON ub_besuch (lehrkraft_id, datum);
    CREATE TABLE ub_schwerpunkt (
        id INTEGER PRIMARY KEY, besuch_id INTEGER NOT NULL REFERENCES ub_besuch(id) ON DELETE CASCADE,
        kriterium_id INTEGER, position INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE ub_eintrag (
        id INTEGER PRIMARY KEY, besuch_id INTEGER NOT NULL REFERENCES ub_besuch(id) ON DELETE CASCADE,
        art TEXT NOT NULL DEFAULT 'eintrag', zeit TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
        phase_id INTEGER, kategorie_id INTEGER, text TEXT NOT NULL DEFAULT '', kriterium_id INTEGER,
        wertung TEXT NOT NULL DEFAULT '', bezug_id INTEGER, foto_uuid TEXT NOT NULL DEFAULT '', foto_name TEXT NOT NULL DEFAULT '',
        skizze_json TEXT NOT NULL DEFAULT '', skizze_uuid TEXT NOT NULL DEFAULT '', skizze_name TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL);
    CREATE INDEX ub_eintrag_besuch ON ub_eintrag (besuch_id);
    CREATE TABLE ub_datei (
        uuid TEXT PRIMARY KEY, lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        name TEXT NOT NULL, mime TEXT NOT NULL, daten BLOB NOT NULL, erstellt TEXT NOT NULL)
    """,
    # 17: Unterrichtsinhalt (Text fuers Klassenbuch in WebUntis) und eigene Notizen je gehaltener Stunde. Wie beim Ist
    #     ist (Lehrkraft, Datum, Beginn) eindeutig; Klasse/Gruppe zum Wiederfinden der Vorstunde.
    """
    CREATE TABLE stunde_eintrag (
        id INTEGER PRIMARY KEY,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        beginn TEXT NOT NULL,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id),
        gruppe_id INTEGER REFERENCES gruppe(id) ON DELETE SET NULL,
        inhalt TEXT NOT NULL DEFAULT '',
        notizen TEXT NOT NULL DEFAULT '',
        geaendert TEXT NOT NULL,
        UNIQUE (lehrkraft_id, datum, beginn));
    CREATE INDEX stunde_eintrag_klasse ON stunde_eintrag (lehrkraft_id, klasse_id, datum)
    """,
    # 18: Stufe F3 Dokumente: Paperless-Verbindung je Konto (JSON mit AES-GCM verschluesselt, Schluessel im Datenordner,
    #     siehe app/paperless.py)
    """
    ALTER TABLE lehrkraft ADD COLUMN paperless TEXT
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
