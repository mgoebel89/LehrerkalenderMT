"""Gemeinsame Schuelerliste je Klasse (0.24.0).

Eine Liste je Klasse fuer alle Lehrkraefte der Klasse: Name, E-Mail und "in der Klasse" (aktiv) sind gemeinsam; jede
Lehrkraft der Klasse darf Schueler anlegen, aendern, einlesen und auf "nicht mehr in der Klasse" stellen. Privat
bleiben die Gruppeneinteilung (schueler_gruppe, je Lehrkraft) sowie Pruefungen und Noten.

Zugriff auf die Liste einer Klasse hat
  - der Admin (alle Klassen),
  - wer die Klasse in einer eigenen Stundenplan-Version hat (auch einer vergangenen),
  - wer in der Klasse eigene Pruefungen hat oder dort Schueler angelegt hat (z. B. aus der Zeit der privaten Listen).

Grundregel wie bisher: ein Import legt nur neue Schueler an und aendert nie Namen.
"""
import csv
import io
import re
import unicodedata

from . import db


class SchuelerFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def normalisiert(text):
    """Namen robust vergleichen: Umlaute ausschreiben, Akzente weg, nur Buchstaben, klein."""
    t = (text or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss").replace("ı", "i").replace("ł", "l")
    t = unicodedata.normalize("NFKD", t)
    return re.sub(r"[^a-z]", "", "".join(c for c in t if not unicodedata.combining(c)))


def _namensschluessel(z):
    return normalisiert(z["nachname"]) + "|" + normalisiert(z["vorname"])


def _id(wert):
    if wert in (None, "", 0, "0"):
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise SchuelerFehler("Ungültige Auswahl.")


def _text(wert, feld, max_len, pflicht=True):
    wert = wert.strip() if isinstance(wert, str) else ""
    if pflicht and not wert:
        raise SchuelerFehler("Bitte %s angeben." % feld)
    if len(wert) > max_len:
        raise SchuelerFehler("%s darf höchstens %d Zeichen haben." % (feld[0].upper() + feld[1:], max_len))
    return wert


def _name(z):
    return z["nachname"] + (", " + z["vorname"] if z["vorname"] else "")


# --- Zugriff ---

def _ist_admin(con, lid):
    z = con.execute("SELECT rolle FROM lehrkraft WHERE id = ?", (lid,)).fetchone()
    return bool(z) and z["rolle"] == "admin"


def klassen_der_lehrkraft(con, lid):
    """Ids der Klassen, deren Liste die Lehrkraft nutzen darf (ohne die Admin-Regel)."""
    return {z[0] for z in con.execute(
        "SELECT e.klasse_id FROM stundenplan_eintrag e JOIN stundenplan_version v ON v.id = e.version_id WHERE v.lehrkraft_id = ? "
        "UNION SELECT klasse_id FROM pruefung WHERE lehrkraft_id = ? "
        "UNION SELECT klasse_id FROM schueler WHERE erstellt_von = ?", (lid, lid, lid)) if z[0] is not None}


def darf_klasse(con, lid, kid):
    return _ist_admin(con, lid) or kid in klassen_der_lehrkraft(con, lid)


def klasse_pruefen(con, lid, kid):
    if kid is None or con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
        raise SchuelerFehler("Bitte eine Klasse wählen.")
    if not darf_klasse(con, lid, kid):
        raise SchuelerFehler("Die Schülerliste dieser Klasse sehen nur die Lehrkräfte, die in der Klasse unterrichten.")
    return kid


def klassen(con, lid):
    """Klassen, deren Liste die Lehrkraft nutzen darf: [{id, name, aktiv, meine, schueler}]; meine = laut eigenem
    Stundenplan. Der Admin bekommt alle Klassen."""
    admin = _ist_admin(con, lid)
    erlaubt = klassen_der_lehrkraft(con, lid)
    stundenplan = {z[0] for z in con.execute("SELECT e.klasse_id FROM stundenplan_eintrag e JOIN stundenplan_version v "
                                             "ON v.id = e.version_id WHERE v.lehrkraft_id = ?", (lid,))}
    anzahl = {z[0]: z[1] for z in con.execute("SELECT klasse_id, COUNT(*) FROM schueler WHERE aktiv = 1 GROUP BY klasse_id")}
    liste = [{"id": k["id"], "name": k["name"], "aktiv": bool(k["aktiv"]), "meine": k["id"] in stundenplan,
              "schueler": anzahl.get(k["id"], 0)}
             for k in con.execute("SELECT id, name, aktiv FROM klasse ORDER BY name") if admin or k["id"] in erlaubt]
    return [k for k in liste if k["aktiv"] or k["meine"] or k["schueler"] or not admin]


# --- Lesen ---

def liste(con, lid, kid, nur_aktive=False):
    """Alle Schueler der Klasse mit der Gruppe DIESER Lehrkraft (gruppe_id, gruppe)."""
    klasse_pruefen(con, lid, kid)
    zeilen = con.execute(
        "SELECT s.*, sg.gruppe_id, g.name AS gruppe, l.name AS angelegt_von FROM schueler s "
        "LEFT JOIN schueler_gruppe sg ON sg.schueler_id = s.id AND sg.lehrkraft_id = ? "
        "LEFT JOIN gruppe g ON g.id = sg.gruppe_id LEFT JOIN lehrkraft l ON l.id = s.erstellt_von "
        "WHERE s.klasse_id = ?" + (" AND s.aktiv = 1" if nur_aktive else ""), (lid, kid)).fetchall()
    ergebnis = [{"id": z["id"], "nachname": z["nachname"], "vorname": z["vorname"], "email": z["email"], "gruppe_id": z["gruppe_id"],
                 "gruppe": z["gruppe"], "aktiv": bool(z["aktiv"]), "name": _name(z), "angelegt_von": z["angelegt_von"] or ""}
                for z in zeilen]
    ergebnis.sort(key=lambda s: (not s["aktiv"], normalisiert(s["nachname"]), normalisiert(s["vorname"])))
    return ergebnis


def zeile(con, lid, sid):
    """Rohzeile eines Schuelers, wenn die Lehrkraft die Liste seiner Klasse nutzen darf."""
    z = con.execute("SELECT * FROM schueler WHERE id = ?", (sid,)).fetchone()
    if z is None or not darf_klasse(con, lid, z["klasse_id"]):
        raise SchuelerFehler("Diesen Schüler gibt es nicht.")
    return z


# --- Aendern ---

def _gruppe_setzen(con, lid, sid, kid, gid):
    if gid is not None and con.execute("SELECT 1 FROM gruppe WHERE id = ? AND lehrkraft_id = ? AND klasse_id = ?",
                                       (gid, lid, kid)).fetchone() is None:
        raise SchuelerFehler("Diese Gruppe gehört nicht zur Klasse.")
    con.execute("DELETE FROM schueler_gruppe WHERE lehrkraft_id = ? AND schueler_id = ?", (lid, sid))
    if gid is not None:
        con.execute("INSERT INTO schueler_gruppe (lehrkraft_id, schueler_id, gruppe_id) VALUES (?, ?, ?)", (lid, sid, gid))


def speichern(con, lid, daten, sid=None):
    """Schueler anlegen bzw. aendern. Die Gruppe (gruppe_id) gilt nur fuer die eigene Einteilung dieser Lehrkraft."""
    if sid is None:
        kid = klasse_pruefen(con, lid, _id(daten.get("klasse_id")))
    else:
        kid = zeile(con, lid, sid)["klasse_id"]
    nachname = _text(daten.get("nachname"), "den Nachnamen", 80)
    vorname = _text(daten.get("vorname"), "den Vornamen", 80, pflicht=False)
    email = _text(daten.get("email"), "die E-Mail", 120, pflicht=False)
    aktiv = 0 if daten.get("aktiv") is False else 1
    if sid is None:
        sid = con.execute("INSERT INTO schueler (klasse_id, nachname, vorname, email, aktiv, erstellt, erstellt_von) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)", (kid, nachname, vorname, email, aktiv, db.jetzt(), lid)).lastrowid
    else:
        con.execute("UPDATE schueler SET nachname = ?, vorname = ?, email = ?, aktiv = ? WHERE id = ?",
                    (nachname, vorname, email, aktiv, sid))
    if "gruppe_id" in daten:
        _gruppe_setzen(con, lid, sid, kid, _id(daten.get("gruppe_id")))
    return sid


def loeschen(con, lid, sid):
    z = zeile(con, lid, sid)
    if con.execute("SELECT 1 FROM bewertung WHERE schueler_id = ? AND (werte != '{}' OR fehlt = 1 OR notiz != '')", (sid,)).fetchone():
        raise SchuelerFehler("Für diesen Schüler gibt es Bewertungen (auch von Kolleginnen und Kollegen). "
                             "Bitte stattdessen auf „nicht mehr in der Klasse“ stellen.")
    con.execute("DELETE FROM schueler WHERE id = ?", (sid,))
    return z


SPALTEN = {
    "vorname": ("vorname", "firstname", "first name"), "nachname": ("nachname", "lastname", "last name", "surname", "name"),
    "email": ("emailadresse", "email", "emailaddress", "mail"),
}


def moodle_csv(con, lid, kid, text):
    """Teilnehmerliste aus Moodle (CSV) in die gemeinsame Liste einlesen: neue Schueler anlegen, vorhandene (gleiche
    E-Mail oder gleicher Name) nur erkennen, nie umbenennen. Rueckgabe {neu: [namen], vorhanden: [namen], leer: anzahl}."""
    kid = klasse_pruefen(con, lid, kid)
    text = (text or "").lstrip("﻿")
    if not text.strip():
        raise SchuelerFehler("Die Datei ist leer.")
    erste = text.splitlines()[0]
    trenner = ";" if erste.count(";") > erste.count(",") else ("\t" if erste.count("\t") > erste.count(",") else ",")
    leser = csv.reader(io.StringIO(text), delimiter=trenner)
    kopf = [re.sub(r"[^a-z ]", "", (k or "").lower().replace("-", "")).strip() for k in next(leser, [])]
    spalte = {}
    for feld, namen in SPALTEN.items():
        for i, k in enumerate(kopf):
            if k.replace(" ", "") in [n.replace(" ", "") for n in namen] and feld not in spalte:
                spalte[feld] = i
    if "nachname" not in spalte:
        raise SchuelerFehler("In der Datei fehlt die Spalte „Nachname“ (Moodle: Teilnehmer/innen → Download als CSV).")
    vorhanden = liste(con, lid, kid)
    nach_mail = {s["email"].lower(): s for s in vorhanden if s["email"]}
    nach_name = {_namensschluessel(s): s for s in vorhanden}
    ergebnis = {"neu": [], "vorhanden": [], "leer": 0}
    for z in leser:
        wert = lambda f: z[spalte[f]].strip() if f in spalte and spalte[f] < len(z) else ""   # noqa: E731
        nachname, vorname, email = wert("nachname"), wert("vorname"), wert("email")
        if not nachname:
            ergebnis["leer"] += 1
            continue
        treffer = nach_mail.get(email.lower()) if email else None
        treffer = treffer or nach_name.get(normalisiert(nachname) + "|" + normalisiert(vorname))
        if treffer:
            if email and not treffer["email"]:   # nur fehlende E-Mail ergaenzen, Namen bleiben
                con.execute("UPDATE schueler SET email = ? WHERE id = ?", (email[:120], treffer["id"]))
                treffer["email"] = email[:120]
            ergebnis["vorhanden"].append(treffer["name"])
            continue
        neu = speichern(con, lid, {"klasse_id": kid, "nachname": nachname, "vorname": vorname, "email": email})
        s = {"id": neu, "nachname": nachname, "vorname": vorname, "email": email, "name": nachname + (", " + vorname if vorname else "")}
        nach_name[normalisiert(nachname) + "|" + normalisiert(vorname)] = s
        if email:
            nach_mail[email.lower()] = s
        ergebnis["neu"].append(s["name"])
    return ergebnis


# --- Doppelungen und Zusammenfuehren ---

def doppelungen(con, lid, kid):
    """Moegliche Doppelungen in der Klasse: gleicher Name oder gleiche E-Mail, nicht als "verschieden" bestaetigt.
    [{a: schueler, b: schueler}]"""
    alle = liste(con, lid, kid)
    verschieden = {(z[0], z[1]) for z in con.execute("SELECT a, b FROM schueler_verschieden")}
    paare = []
    for i, x in enumerate(alle):
        for y in alle[i + 1:]:
            gleich = _namensschluessel(x) == _namensschluessel(y) or (x["email"] and x["email"].lower() == (y["email"] or "").lower())
            a, b = sorted((x["id"], y["id"]))
            if gleich and (a, b) not in verschieden:
                paare.append({"a": x if x["id"] == a else y, "b": y if x["id"] == a else x})
    return paare


def verschieden_markieren(con, lid, a, b):
    za, zb = zeile(con, lid, a), zeile(con, lid, b)
    if za["klasse_id"] != zb["klasse_id"] or a == b:
        raise SchuelerFehler("Ungültige Auswahl.")
    a, b = sorted((a, b))
    con.execute("INSERT OR IGNORE INTO schueler_verschieden (a, b) VALUES (?, ?)", (a, b))


def _tabellen_mit_schueler(con):
    """Alle Tabellen mit einer Spalte schueler_id (auch kuenftige, z. B. Beobachtungen)."""
    namen = [z[0] for z in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return [t for t in namen if any(s[1] == "schueler_id" for s in con.execute("PRAGMA table_info(%s)" % t))]


def _zusammen(con, ziel, quelle):
    """quelle in ziel aufgehen lassen: alle Verweise umhaengen, E-Mail ergaenzen, aktiv wenn einer aktiv war."""
    for tabelle, art in (("bewertung", "Bewertungen"), ("pruefung_team_mitglied", "Teams")):
        if con.execute("SELECT 1 FROM %s a JOIN %s b ON a.pruefung_id = b.pruefung_id WHERE a.schueler_id = ? AND b.schueler_id = ?"
                       % (tabelle, tabelle), (ziel, quelle)).fetchone():
            raise SchuelerFehler("Beide stehen in derselben Prüfung (%s) – zusammenführen geht dann nicht." % art)
    # eigene Gruppe: die des Ziels gilt, sonst die der Quelle
    con.execute("DELETE FROM schueler_gruppe WHERE schueler_id = ? AND lehrkraft_id IN "
                "(SELECT lehrkraft_id FROM schueler_gruppe WHERE schueler_id = ?)", (quelle, ziel))
    for tabelle in _tabellen_mit_schueler(con):
        con.execute("UPDATE %s SET schueler_id = ? WHERE schueler_id = ?" % tabelle, (ziel, quelle))
    z, q = (con.execute("SELECT * FROM schueler WHERE id = ?", (i,)).fetchone() for i in (ziel, quelle))
    con.execute("UPDATE schueler SET email = ?, aktiv = ? WHERE id = ?",
                (z["email"] or q["email"], 1 if (z["aktiv"] or q["aktiv"]) else 0, ziel))
    con.execute("DELETE FROM schueler WHERE id = ?", (quelle,))


def zusammenfuehren(con, lid, ziel, quelle):
    """Zwei Eintraege derselben Klasse zu einem machen (Name und Angaben von ziel bleiben)."""
    z, q = zeile(con, lid, ziel), zeile(con, lid, quelle)
    if z["klasse_id"] != q["klasse_id"] or ziel == quelle:
        raise SchuelerFehler("Zusammenführen geht nur mit zwei Schülern derselben Klasse.")
    _zusammen(con, ziel, quelle)
    return z


def migration_zusammenfuehren(con):
    """Migration 24: die frueheren privaten Listen einer Klasse zusammenfuehren. Ein Paar gilt als derselbe Schueler bei
    gleicher E-Mail oder gleichem Namen, wenn sich keine zwei verschiedenen E-Mails widersprechen. Gruppen mit zwei
    Eintraegen derselben Lehrkraft bleiben getrennt (die zeigt die Liste dann als moegliche Doppelung)."""
    for (kid,) in con.execute("SELECT DISTINCT klasse_id FROM schueler").fetchall():
        zeilen = [dict(z) for z in con.execute("SELECT * FROM schueler WHERE klasse_id = ? ORDER BY id", (kid,))]
        gruppen = []                      # [[zeilen]]
        for z in zeilen:
            mail = z["email"].strip().lower()
            passend = [g for g in gruppen if any((mail and mail == y["email"].strip().lower()) or _namensschluessel(y) == _namensschluessel(z)
                                                 for y in g)]
            mails = {y["email"].strip().lower() for g in passend for y in g if y["email"].strip()} | ({mail} if mail else set())
            if len(passend) == 1 and len(mails) <= 1:
                passend[0].append(z)
            else:
                gruppen.append([z])
        for g in gruppen:
            lehrkraefte = [y["erstellt_von"] for y in g]
            if len(g) < 2 or len(set(lehrkraefte)) < len(lehrkraefte):
                continue
            ziel = g[0]["id"]
            for y in g[1:]:
                _zusammen(con, ziel, y["id"])
        db.protokoll(con, "system", "schuelerlisten_zusammengefuehrt", klasse_id=kid,
                     vorher=len(zeilen), nachher=con.execute("SELECT COUNT(*) FROM schueler WHERE klasse_id = ?", (kid,)).fetchone()[0])
