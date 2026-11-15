"""Gemeinsame Grunddaten, gepflegt vom Admin: Bildungsgaenge mit Stufen (Grund-/Fachstufe bzw. Semester), Lernfelder
bzw. Module mit Stundenansatz (Module optional mit Anteilen je Semester), Zeitraster (eines fuer die Schule, je
Bildungsgang ein abweichendes), Ferien und Klassen.

Lesen duerfen alle angemeldeten Lehrkraefte (Stundenplan und Planung brauchen die Daten), aendern nur Admins.
"""
import datetime
import re

from . import db

UHRZEIT = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
EINHEITEN = ("lernfeld", "modul")


def natuerlich(text):
    """Sortierschluessel, der Zahlen als Zahlen behandelt: LF 7 vor LF 10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text or "")]


class GrunddatenFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _text(wert, feld, min_len=1, max_len=80):
    wert = (wert or "").strip() if isinstance(wert, str) or wert is None else str(wert).strip()
    if not min_len <= len(wert) <= max_len:
        if min_len and not wert:
            raise GrunddatenFehler("Bitte %s angeben." % feld)
        raise GrunddatenFehler("%s darf höchstens %d Zeichen haben." % (feld[0].upper() + feld[1:], max_len))
    return wert


def _zahl(wert, feld, minimum=0, maximum=10000):
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        raise GrunddatenFehler("Bitte bei %s eine ganze Zahl angeben." % feld)
    if not minimum <= zahl <= maximum:
        raise GrunddatenFehler("%s muss zwischen %d und %d liegen." % (feld, minimum, maximum))
    return zahl


def _datum(wert, feld):
    try:
        return datetime.date.fromisoformat(str(wert or "")).isoformat()
    except ValueError:
        raise GrunddatenFehler("Bitte bei %s ein Datum angeben." % feld)


def _id_oder_none(wert):
    if wert in (None, "", 0, "0"):
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise GrunddatenFehler("Ungültige Auswahl.")


def _bildungsgang(con, bid):
    zeile = con.execute("SELECT * FROM bildungsgang WHERE id = ?", (bid,)).fetchone()
    if zeile is None:
        raise GrunddatenFehler("Diesen Bildungsgang gibt es nicht.")
    return zeile


def _stufe_im_bildungsgang(con, stufe_id, bildungsgang_id):
    if stufe_id is None:
        return None
    zeile = con.execute("SELECT id FROM stufe WHERE id = ? AND bildungsgang_id = ?", (stufe_id, bildungsgang_id)).fetchone()
    if zeile is None:
        raise GrunddatenFehler("Die Stufe gehört nicht zu diesem Bildungsgang.")
    return stufe_id


# --- Lesen: alles auf einmal (die Mengen sind klein) ---

def alles(con):
    bildungsgaenge = []
    for b in con.execute("SELECT * FROM bildungsgang ORDER BY reihenfolge, name"):
        stufen = [dict(s) for s in con.execute("SELECT id, name, reihenfolge FROM stufe WHERE bildungsgang_id = ? "
                                               "ORDER BY reihenfolge, name", (b["id"],))]
        lernfelder = []
        for lf in sorted(con.execute("SELECT * FROM lernfeld WHERE bildungsgang_id = ?", (b["id"],)), key=lambda z: natuerlich(z["nummer"])):
            anteile = {str(a["stufe_id"]): a["stunden"] for a in
                       con.execute("SELECT stufe_id, stunden FROM lernfeld_anteil WHERE lernfeld_id = ?", (lf["id"],))}
            lernfelder.append({"id": lf["id"], "nummer": lf["nummer"], "name": lf["name"], "stufe_id": lf["stufe_id"],
                               "stunden": lf["stunden"], "aktiv": bool(lf["aktiv"]), "anteile": anteile})
        bildungsgaenge.append({
            "id": b["id"], "name": b["name"], "kuerzel": b["kuerzel"], "einheit": b["einheit"], "aktiv": bool(b["aktiv"]),
            "stufen": stufen, "lernfelder": lernfelder, "zeitraster": zeitraster(con, b["id"], eigenes=True)})
    return {"bildungsgaenge": bildungsgaenge, "zeitraster_schule": zeitraster(con, None),
            "ferien": ferien(con), "klassen": klassen(con), "a_woche": db.einstellung(con, "a_woche", "ungerade"),
            "schuljahre": schuljahre(con)}


# --- Bildungsgaenge und Stufen ---

def bildungsgang_speichern(con, daten, bid=None):
    name = _text(daten.get("name"), "einen Namen")
    kuerzel = _text(daten.get("kuerzel"), "das Kürzel", 0, 12)
    einheit = daten.get("einheit") or "lernfeld"
    if einheit not in EINHEITEN:
        raise GrunddatenFehler("Unbekannte Einheit.")
    aktiv = 0 if daten.get("aktiv") is False else 1
    doppelt = con.execute("SELECT id FROM bildungsgang WHERE name = ? AND id != ?", (name, bid or -1)).fetchone()
    if doppelt:
        raise GrunddatenFehler("Den Bildungsgang %s gibt es schon." % name)
    if bid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM bildungsgang").fetchone()[0]
        cur = con.execute("INSERT INTO bildungsgang (name, kuerzel, einheit, aktiv, reihenfolge) VALUES (?, ?, ?, ?, ?)",
                          (name, kuerzel, einheit, aktiv, reihe))
        return cur.lastrowid
    _bildungsgang(con, bid)
    con.execute("UPDATE bildungsgang SET name = ?, kuerzel = ?, einheit = ?, aktiv = ? WHERE id = ?",
                (name, kuerzel, einheit, aktiv, bid))
    return bid


def bildungsgang_loeschen(con, bid):
    _bildungsgang(con, bid)
    if con.execute("SELECT 1 FROM klasse WHERE bildungsgang_id = ?", (bid,)).fetchone():
        raise GrunddatenFehler("Zu diesem Bildungsgang gibt es noch Klassen. Bitte stattdessen auf „nicht aktiv“ stellen.")
    con.execute("DELETE FROM bildungsgang WHERE id = ?", (bid,))


def stufe_speichern(con, daten, sid=None):
    name = _text(daten.get("name"), "einen Namen", max_len=40)
    if sid is None:
        bid = _id_oder_none(daten.get("bildungsgang_id"))
        _bildungsgang(con, bid)
    else:
        zeile = con.execute("SELECT bildungsgang_id FROM stufe WHERE id = ?", (sid,)).fetchone()
        if zeile is None:
            raise GrunddatenFehler("Diese Stufe gibt es nicht.")
        bid = zeile["bildungsgang_id"]
    if con.execute("SELECT 1 FROM stufe WHERE bildungsgang_id = ? AND name = ? AND id != ?", (bid, name, sid or -1)).fetchone():
        raise GrunddatenFehler("Die Stufe %s gibt es in diesem Bildungsgang schon." % name)
    if sid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM stufe WHERE bildungsgang_id = ?", (bid,)).fetchone()[0]
        return con.execute("INSERT INTO stufe (bildungsgang_id, name, reihenfolge) VALUES (?, ?, ?)", (bid, name, reihe)).lastrowid
    con.execute("UPDATE stufe SET name = ? WHERE id = ?", (name, sid))
    return sid


def stufe_loeschen(con, sid):
    if con.execute("SELECT 1 FROM klasse WHERE stufe_id = ?", (sid,)).fetchone():
        raise GrunddatenFehler("Klassen stehen noch auf dieser Stufe. Bitte die Klassen zuerst umstellen.")
    con.execute("DELETE FROM stufe WHERE id = ?", (sid,))


# --- Lernfelder bzw. Module ---

def lernfeld_speichern(con, daten, lid=None):
    if lid is None:
        bid = _id_oder_none(daten.get("bildungsgang_id"))
        b = _bildungsgang(con, bid)
    else:
        zeile = con.execute("SELECT bildungsgang_id FROM lernfeld WHERE id = ?", (lid,)).fetchone()
        if zeile is None:
            raise GrunddatenFehler("Dieses Lernfeld gibt es nicht.")
        b = _bildungsgang(con, zeile["bildungsgang_id"])
    nummer = _text(daten.get("nummer"), "die Nummer (z. B. LF 7)", max_len=12)
    name = _text(daten.get("name"), "einen Namen")
    stufe_id = _stufe_im_bildungsgang(con, _id_oder_none(daten.get("stufe_id")), b["id"])
    stunden = _zahl(daten.get("stunden") or 0, "Stundenansatz", 0, 2000)
    aktiv = 0 if daten.get("aktiv") is False else 1
    if con.execute("SELECT 1 FROM lernfeld WHERE bildungsgang_id = ? AND nummer = ? AND id != ?",
                   (b["id"], nummer, lid or -1)).fetchone():
        raise GrunddatenFehler("%s gibt es in diesem Bildungsgang schon." % nummer)
    if lid is None:
        lid = con.execute("INSERT INTO lernfeld (bildungsgang_id, stufe_id, nummer, name, stunden, aktiv) VALUES (?, ?, ?, ?, ?, ?)",
                          (b["id"], stufe_id, nummer, name, stunden, aktiv)).lastrowid
    else:
        con.execute("UPDATE lernfeld SET stufe_id = ?, nummer = ?, name = ?, stunden = ?, aktiv = ? WHERE id = ?",
                    (stufe_id, nummer, name, stunden, aktiv, lid))
    # Anteile je Stufe (Module ueber mehrere Semester): {stufe_id: stunden}; leer = keine Aufteilung
    anteile = daten.get("anteile") or {}
    if not isinstance(anteile, dict):
        raise GrunddatenFehler("Ungültige Anteile.")
    con.execute("DELETE FROM lernfeld_anteil WHERE lernfeld_id = ?", (lid,))
    for sid, std in anteile.items():
        if std in (None, "", 0, "0"):
            continue
        sid = _stufe_im_bildungsgang(con, _id_oder_none(sid), b["id"])
        con.execute("INSERT INTO lernfeld_anteil (lernfeld_id, stufe_id, stunden) VALUES (?, ?, ?)",
                    (lid, sid, _zahl(std, "Stunden je Stufe", 1, 2000)))
    return lid


def lernfeld_loeschen(con, lid):
    # Bibliothek haengt am Lernfeld (wird mitgeloescht); Planungen und Stundenplaene verlieren nur die Zuordnung
    con.execute("DELETE FROM lernfeld WHERE id = ?", (lid,))


# --- Zeitraster ---

def zeitraster(con, bildungsgang_id, eigenes=False):
    """Bloecke eines Bildungsgangs. Ohne eigene Bloecke gilt das Schulraster (ausser eigenes=True)."""
    if bildungsgang_id is None:
        zeilen = con.execute("SELECT * FROM zeitblock WHERE bildungsgang_id IS NULL ORDER BY beginn").fetchall()
    else:
        zeilen = con.execute("SELECT * FROM zeitblock WHERE bildungsgang_id = ? ORDER BY beginn", (bildungsgang_id,)).fetchall()
        if not zeilen and not eigenes:
            return zeitraster(con, None)
    return [{"id": z["id"], "bezeichnung": z["bezeichnung"], "beginn": z["beginn"], "ende": z["ende"]} for z in zeilen]


def zeitraster_speichern(con, bildungsgang_id, bloecke):
    """Ersetzt das ganze Raster (Schule bei bildungsgang_id None). Leere Liste beim Bildungsgang = Schulraster gilt."""
    if bildungsgang_id is not None:
        _bildungsgang(con, bildungsgang_id)
    if not isinstance(bloecke, list) or len(bloecke) > 16:
        raise GrunddatenFehler("Ungültiges Zeitraster.")
    saubere = []
    for i, b in enumerate(bloecke):
        if not isinstance(b, dict):
            raise GrunddatenFehler("Ungültiges Zeitraster.")
        bez = _text(b.get("bezeichnung"), "eine Bezeichnung für Block %d" % (i + 1), max_len=20)
        beginn, ende = (b.get("beginn") or "").strip(), (b.get("ende") or "").strip()
        if not UHRZEIT.fullmatch(beginn) or not UHRZEIT.fullmatch(ende):
            raise GrunddatenFehler("%s: Uhrzeiten bitte als HH:MM angeben." % bez)
        if beginn >= ende:
            raise GrunddatenFehler("%s: Das Ende muss nach dem Beginn liegen." % bez)
        saubere.append((bez, beginn, ende))
    saubere.sort(key=lambda t: t[1])
    for (b1, _, e1), (b2, s2, _) in zip(saubere, saubere[1:]):
        if s2 < e1:
            raise GrunddatenFehler("%s und %s überschneiden sich." % (b1, b2))
    if bildungsgang_id is None and not saubere:
        raise GrunddatenFehler("Das Schulraster braucht mindestens einen Block.")
    if bildungsgang_id is None:
        con.execute("DELETE FROM zeitblock WHERE bildungsgang_id IS NULL")
    else:
        con.execute("DELETE FROM zeitblock WHERE bildungsgang_id = ?", (bildungsgang_id,))
    for bez, beginn, ende in saubere:
        con.execute("INSERT INTO zeitblock (bildungsgang_id, bezeichnung, beginn, ende) VALUES (?, ?, ?, ?)",
                    (bildungsgang_id, bez, beginn, ende))


# --- Ferien ---

def ferien(con):
    return [dict(z) for z in con.execute("SELECT id, name, von, bis, quelle FROM ferien ORDER BY von")]


def ferien_anlegen(con, daten):
    name = _text(daten.get("name"), "einen Namen (z. B. Weihnachtsferien)")
    von, bis = _datum(daten.get("von"), "„von“"), _datum(daten.get("bis") or daten.get("von"), "„bis“")
    if bis < von:
        raise GrunddatenFehler("„Bis“ liegt vor „von“.")
    return con.execute("INSERT INTO ferien (name, von, bis, quelle) VALUES (?, ?, ?, 'hand')", (name, von, bis)).lastrowid


def ferien_loeschen(con, fid):
    con.execute("DELETE FROM ferien WHERE id = ?", (fid,))


# --- Schuljahre (erster und letzter Unterrichtstag; die Planung gilt je Schuljahr) ---

def schuljahre(con):
    return [dict(z) for z in con.execute("SELECT id, name, beginn, ende FROM schuljahr ORDER BY beginn")]


def schuljahr_speichern(con, daten, sid=None):
    name = _text(daten.get("name"), "einen Namen (z. B. 2026/27)", max_len=20)
    beginn, ende = _datum(daten.get("beginn"), "den ersten Unterrichtstag"), _datum(daten.get("ende"), "den letzten Unterrichtstag")
    if ende <= beginn:
        raise GrunddatenFehler("Der letzte Unterrichtstag muss nach dem ersten liegen.")
    if con.execute("SELECT 1 FROM schuljahr WHERE name = ? AND id != ?", (name, sid or -1)).fetchone():
        raise GrunddatenFehler("Das Schuljahr %s gibt es schon." % name)
    anderes = con.execute("SELECT name FROM schuljahr WHERE beginn <= ? AND ende >= ? AND id != ?", (ende, beginn, sid or -1)).fetchone()
    if anderes:
        raise GrunddatenFehler("Der Zeitraum überschneidet sich mit dem Schuljahr %s." % anderes["name"])
    if sid is None:
        return con.execute("INSERT INTO schuljahr (name, beginn, ende) VALUES (?, ?, ?)", (name, beginn, ende)).lastrowid
    if con.execute("SELECT 1 FROM schuljahr WHERE id = ?", (sid,)).fetchone() is None:
        raise GrunddatenFehler("Dieses Schuljahr gibt es nicht.")
    con.execute("UPDATE schuljahr SET name = ?, beginn = ?, ende = ? WHERE id = ?", (name, beginn, ende, sid))
    return sid


def schuljahr_loeschen(con, sid):
    if con.execute("SELECT 1 FROM plan_thema WHERE schuljahr_id = ?", (sid,)).fetchone():
        raise GrunddatenFehler("In diesem Schuljahr gibt es schon Planungen. Es lässt sich nicht mehr löschen.")
    con.execute("DELETE FROM schuljahr WHERE id = ?", (sid,))


def schuljahr_zum(con, datum):
    """Das Schuljahr, in dem datum (date oder ISO) liegt, oder None."""
    iso = datum if isinstance(datum, str) else datum.isoformat()
    zeile = con.execute("SELECT id, name, beginn, ende FROM schuljahr WHERE beginn <= ? AND ende >= ?", (iso, iso)).fetchone()
    return dict(zeile) if zeile else None


# --- Klassen ---

def klassen(con):
    zeilen = con.execute("SELECT k.*, b.name AS bildungsgang, s.name AS stufe FROM klasse k "
                         "JOIN bildungsgang b ON b.id = k.bildungsgang_id LEFT JOIN stufe s ON s.id = k.stufe_id "
                         "ORDER BY k.aktiv DESC, k.name")
    return [{"id": z["id"], "name": z["name"], "bildungsgang_id": z["bildungsgang_id"], "bildungsgang": z["bildungsgang"],
             "stufe_id": z["stufe_id"], "stufe": z["stufe"], "notenschluessel_id": z["notenschluessel_id"],
             "aktiv": bool(z["aktiv"])} for z in zeilen]


def klasse_speichern(con, daten, kid=None):
    name = _text(daten.get("name"), "einen Namen (z. B. BSMT 24a)", max_len=30)
    bid = _id_oder_none(daten.get("bildungsgang_id"))
    if bid is None:
        raise GrunddatenFehler("Bitte einen Bildungsgang wählen.")
    _bildungsgang(con, bid)
    stufe_id = _stufe_im_bildungsgang(con, _id_oder_none(daten.get("stufe_id")), bid)
    ns_id = _id_oder_none(daten.get("notenschluessel_id"))
    if ns_id is not None and not con.execute("SELECT 1 FROM notenschluessel WHERE id = ? AND art = 'konferenz'", (ns_id,)).fetchone():
        raise GrunddatenFehler("Als Schlüssel einer Klasse geht nur ein Konferenzschlüssel.")
    aktiv = 0 if daten.get("aktiv") is False else 1
    if con.execute("SELECT 1 FROM klasse WHERE name = ? AND id != ?", (name, kid or -1)).fetchone():
        raise GrunddatenFehler("Die Klasse %s gibt es schon." % name)
    if kid is None:
        return con.execute("INSERT INTO klasse (name, bildungsgang_id, stufe_id, notenschluessel_id, aktiv, erstellt) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (name, bid, stufe_id, ns_id, aktiv, db.jetzt())).lastrowid
    if con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
        raise GrunddatenFehler("Diese Klasse gibt es nicht.")
    con.execute("UPDATE klasse SET name = ?, bildungsgang_id = ?, stufe_id = ?, notenschluessel_id = ?, aktiv = ? WHERE id = ?",
                (name, bid, stufe_id, ns_id, aktiv, kid))
    return kid


def klasse_loeschen(con, kid):
    # an der Klasse haengen Stundenplaene und Aenderungen aller Lehrkraefte: dann nur noch "nicht aktiv"
    if con.execute("SELECT 1 FROM stundenplan_eintrag WHERE klasse_id = ? UNION SELECT 1 FROM aenderung WHERE klasse_id = ? "
                   "UNION SELECT 1 FROM plan_thema WHERE klasse_id = ?", (kid, kid, kid)).fetchone():
        raise GrunddatenFehler("Die Klasse steht in Stundenplänen. Bitte stattdessen auf „nicht aktiv“ stellen.")
    con.execute("DELETE FROM klasse WHERE id = ?", (kid,))
