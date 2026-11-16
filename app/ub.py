"""Stufe F2: Unterrichtsbesuche (Hospitationsprotokolle fuer Anwaerter), aus dem alten Lehrerkalender uebernommen.

Drei Ebenen wie dort: Einstellungen (Kategorien mit Piktogramm und Farbe, Phasen, Beratungsschwerpunkte = intern
"kriterien"), Anwaerter und Besuche mit Kopfdaten und Schwerpunkten, Eintraege im Verlauf (vom Handy erfasst, jeder
sofort gespeichert). Die Oberflaeche (web/ub-*.js) ist unveraendert uebernommen und spricht dieselben Adressen
(/unterrichtsbesuche..., /api/ub/..., /api/files/...). Fotos und Skizzen liegen als Blob in der Datenbank (ub_datei),
damit sie in der Sicherung stecken. Strikt privat: alles haengt an der Lehrkraft.

Die Piktogramme sind als Zeichenanweisungen hinterlegt (Pfade mit absoluten M/L/H/V/C/Q/Z-Befehlen, Kreise, Rechtecke):
dieselben Daten zeichnen das Icon im Browser (SVG) und im PDF/ODT. Boegen (A) und relative Befehle kann der
PDF-Zeichner nicht. 24x24-Raster, Strich 1,7.
"""
import base64
import io
import json
import re
import uuid
from datetime import date   # noqa: F401  (vom alten Modul)

from . import db

# ── Piktogramme ───────────────────────────────────────────────────────────
# (label, [teile]) — teil = ("path", d) | ("circle", cx, cy, r)
#                         | ("rect", x, y, w, h, rx)
ICONS: dict[str, tuple[str, list[tuple]]] = {
    "auge": ("Auge", [
        ("path", "M2 12 C5 6.5 8.5 5 12 5 C15.5 5 19 6.5 22 12 "
                 "C19 17.5 15.5 19 12 19 C8.5 19 5 17.5 2 12 Z"),
        ("circle", 12, 12, 3),
    ]),
    "gluehbirne": ("Glühbirne", [
        ("path", "M9 18 H15"),
        ("path", "M10 21 H14"),
        ("path", "M9 15 C9 13.5 8 12.8 7.2 11.8 C6.4 10.8 6 9.6 6 8.5 "
                 "C6 5.2 8.7 2.5 12 2.5 C15.3 2.5 18 5.2 18 8.5 "
                 "C18 9.6 17.6 10.8 16.8 11.8 C16 12.8 15 13.5 15 15 Z"),
    ]),
    "sprechblase": ("Sprechblase", [
        ("path", "M21 15 C21 16.1 20.1 17 19 17 H7 L3 21 V5 C3 3.9 3.9 3 5 3 "
                 "H19 C20.1 3 21 3.9 21 5 Z"),
    ]),
    "stern": ("Stern", [
        ("path", "M12 2.5 L14.9 8.4 L21.4 9.3 L16.7 13.9 L17.8 20.4 L12 17.3 "
                 "L6.2 20.4 L7.3 13.9 L2.6 9.3 L9.1 8.4 Z"),
    ]),
    "frage": ("Fragezeichen", [
        ("circle", 12, 12, 10),
        ("path", "M9.1 9 C9.1 7.3 10.4 6 12 6 C13.6 6 14.9 7.3 14.9 8.8 "
                 "C14.9 10.8 12 11.5 12 13.5"),
        ("path", "M12 17.2 L12 17.3"),
    ]),
    "achtung": ("Achtung", [
        ("path", "M10.3 3.9 L1.8 18 C1.2 19.3 2.1 21 3.5 21 H20.5 "
                 "C21.9 21 22.8 19.3 22.2 18 L13.7 3.9 C12.9 2.6 11.1 2.6 10.3 3.9 Z"),
        ("path", "M12 9 V13"),
        ("path", "M12 17 L12 17.1"),
    ]),
    "daumen": ("Daumen hoch", [
        ("path", "M7 10 V21"),
        ("path", "M7 10 L11 2.5 C12.7 2.5 14 3.8 14 5.5 V9 H19.5 "
                 "C20.8 9 21.7 10.2 21.4 11.4 L19.8 18.6 C19.5 19.9 18.4 21 17 21 "
                 "H4 C3.4 21 3 20.6 3 20 V11 C3 10.4 3.4 10 4 10 Z"),
    ]),
    "flagge": ("Flagge", [
        ("path", "M4 22 V3"),
        ("path", "M4 4 C8 1.5 12 6.5 16 4 C17.5 3.1 19 3 20 3 V14 "
                 "C19 14 17.5 14.1 16 15 C12 17.5 8 12.5 4 15"),
    ]),
    "uhr": ("Uhr", [
        ("circle", 12, 12, 10),
        ("path", "M12 6 V12 L16 14"),
    ]),
    "personen": ("Personen", [
        ("circle", 9, 7, 4),
        ("path", "M17 21 V19 C17 16.8 15.2 15 13 15 H5 C2.8 15 1 16.8 1 19 V21"),
        ("path", "M23 21 V19 C23 17.2 21.8 15.6 20 15.1"),
        ("path", "M16 3.1 C17.8 3.6 19 5.2 19 7 C19 8.8 17.8 10.4 16 10.9"),
    ]),
    "tafel": ("Tafel", [
        ("rect", 2, 3, 20, 14, 1.5),
        ("path", "M8 21 L12 17 L16 21"),
        ("path", "M6 8 H13"),
        ("path", "M6 12 H10"),
    ]),
    "lupe": ("Lupe", [
        ("circle", 11, 11, 7),
        ("path", "M21 21 L16 16"),
    ]),
    "stift": ("Stift", [
        ("path", "M16.5 3.5 C17.3 2.7 18.7 2.7 19.5 3.5 L20.5 4.5 "
                 "C21.3 5.3 21.3 6.7 20.5 7.5 L8 20 L3 21 L4 16 Z"),
        ("path", "M14.5 5.5 L18.5 9.5"),
    ]),
    "blitz": ("Blitz", [
        ("path", "M13 2 L3 14 H12 L11 22 L21 10 H12 Z"),
    ]),
    "haken": ("Haken", [
        ("circle", 12, 12, 10),
        ("path", "M8 12 L11 15 L16 9"),
    ]),
    "herz": ("Herz", [
        ("path", "M12 20.5 C12 20.5 3 15 3 8.8 C3 6 5.2 3.8 7.9 3.8 "
                 "C9.6 3.8 11.1 4.7 12 6 C12.9 4.7 14.4 3.8 16.1 3.8 "
                 "C18.8 3.8 21 6 21 8.8 C21 15 12 20.5 12 20.5 Z"),
    ]),
    "ziel": ("Zielscheibe", [
        ("circle", 12, 12, 10),
        ("circle", 12, 12, 6),
        ("circle", 12, 12, 2),
    ]),
    "trend": ("Aufwärtstrend", [
        ("path", "M3 17 L9 11 L13 15 L21 7"),
        ("path", "M15 7 H21 V13"),
    ]),
    "kamera": ("Kamera", [
        ("path", "M23 19 C23 20.1 22.1 21 21 21 H3 C1.9 21 1 20.1 1 19 V8 "
                 "C1 6.9 1.9 6 3 6 H7 L9 3 H15 L17 6 H21 C22.1 6 23 6.9 23 8 Z"),
        ("circle", 12, 13, 4),
    ]),
    "bild": ("Bild", [
        ("rect", 3, 3, 18, 18, 2),
        ("circle", 8.5, 8.5, 1.5),
        ("path", "M21 15 L16 10 L5 21"),
    ]),
    "plus": ("Plus", [
        ("path", "M12 5 V19"),
        ("path", "M5 12 H19"),
    ]),
}
STANDARD_ICON = "auge"

# Die zwei festen Wertungen — mit eigenem Piktogramm, damit sie im Protokoll
# ohne Legende lesbar sind.
# `pos` steht dabei, weil Jinjas `tojson` die Schlüssel alphabetisch sortiert —
# ohne sie stünde „Entwicklungsfeld" im Handy vor „Stärke".
WERTUNGEN: dict[str, dict] = {
    "staerke":     {"label": "Stärke", "icon": "daumen", "farbe": "#2E7D32", "pos": 0},
    "entwicklung": {"label": "Entwicklungsfeld", "icon": "trend", "farbe": "#C77700", "pos": 1},
}

# Feste Farbpalette statt Farbwähler: alle Töne sind auf Weiß lesbar und
# kräftig genug für ein Piktogramm im Ausdruck.
FARBEN: list[tuple[str, str]] = [
    ("#00639C", "DRS-Blau"),
    ("#00838F", "Petrol"),
    ("#2E7D32", "Grün"),
    ("#C77700", "Orange"),
    ("#C62828", "Rot"),
    ("#D4005E", "Magenta"),
    ("#6A3FA0", "Violett"),
    ("#5A6B7D", "Grau"),
]
_FARB_WERTE = {f for f, _ in FARBEN}

SPALTEN = {"verlauf": "Verlauf (links)", "kommentar": "Kommentar (rechts)"}
STATUS = {"geplant": "Geplant", "laufend": "Läuft", "abgeschlossen": "Abgeschlossen"}
ORDNUNGEN = {
    "chronologisch": "Chronologisch",
    "kategorie": "Nach Kategorie",
    "kriterium": "Nach Beratungsschwerpunkt",
    "zweispaltig": "Zweispaltig (Verlauf | Kommentar)",
}

# Vorgaben beim ersten Öffnen — danach gehört alles dem Lehrer.
VORGABE_KATEGORIEN = [
    ("Beobachtung", "auge", "#00639C", "verlauf"),
    ("Idee", "gluehbirne", "#C77700", "kommentar"),
    ("Anmerkung", "sprechblase", "#6A3FA0", "kommentar"),
]
VORGABE_PHASEN = ["Einstieg", "Erarbeitung", "Sicherung", "Übung / Transfer", "Abschluss"]
# Die „Kriterien" heißen in der Oberfläche **Beratungsschwerpunkte**: EIN Katalog
# für alle Anwärter (Liste des Seminars). Je Besuch wählt der Anwärter daraus
# aus (`ub_schwerpunkte`). Intern bleibt der Name `kriterien`/`kriterium_id`.
VORGABE_KRITERIEN = [
    "Klassenführung", "Strukturierung", "Aktivierung der Lernenden",
    "Lehrersprache & Impulse", "Medien & Material", "Lernatmosphäre",
    "Handlungsorientierung", "Ergebnissicherung",
]

_ZEIT_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── kleine Normalisierer ──────────────────────────────────────────────────

def zeit(wert: str | None) -> str:
    w = (wert or "").strip()[:5]
    return w if _ZEIT_RE.match(w) else ""


def datum(wert: str | None) -> str:
    w = (wert or "").strip()[:10]
    return w if _DATUM_RE.match(w) else ""


def farbe(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in _FARB_WERTE else FARBEN[0][0]


def icon_name(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in ICONS else STANDARD_ICON


def spalte(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in SPALTEN else "verlauf"


def wertung(wert: str | None) -> str:
    w = (wert or "").strip()
    return w if w in WERTUNGEN else ""


def text(wert, laenge: int | None = None) -> str:
    t = str(wert or "").strip()
    return t[:laenge] if laenge else t


def icon_svg(name: str) -> str:
    """Inneres SVG (ohne <svg>-Hülle) für Templates und JS."""
    _, teile = ICONS.get(name, ICONS[STANDARD_ICON])
    out = []
    for t in teile:
        if t[0] == "path":
            out.append(f'<path d="{t[1]}"/>')
        elif t[0] == "circle":
            out.append(f'<circle cx="{t[1]}" cy="{t[2]}" r="{t[3]}"/>')
        elif t[0] == "rect":
            out.append(f'<rect x="{t[1]}" y="{t[2]}" width="{t[3]}" '
                       f'height="{t[4]}" rx="{t[5]}"/>')
    return "".join(out)


def icon_katalog() -> dict[str, dict[str, str]]:
    return {k: {"label": v[0], "svg": icon_svg(k)} for k, v in ICONS.items()}




# ── Kontext: Verbindung und Lehrkraft (ersetzt Session + User des alten Tools) ──

class Kontext:
    """con + Lehrkraft-id. Wird an Stelle von (db, user) des alten Tools durchgereicht; die Protokoll-Module
    rufen ub.einstellung(db, user) usw. mit (k, k) auf."""

    def __init__(self, con, lid, name=""):
        self.con, self.lid, self.id = con, lid, lid
        self.full_name = self.username = name


class Zeile:
    """Zeile mit Attributzugriff (z.name), wie die SQLAlchemy-Objekte des alten Tools."""

    def __init__(self, **werte):
        self.__dict__.update(werte)


class UbFehler(Exception):
    def __init__(self, text, status=400):
        super().__init__(text)
        self.status = status


TABELLEN = {"kategorien": "ub_kategorie", "phasen": "ub_phase", "kriterien": "ub_kriterium"}
MODELLE = TABELLEN      # Name aus dem alten Tool (Pruefung "art in ub.MODELLE")
MAX_DATEI = 8 * 1024 * 1024
MAX_SKIZZE = 3 * 1024 * 1024


def _k(k):
    return k if isinstance(k, Kontext) else Kontext(*k)


# ── Einstellungen ─────────────────────────────────────────────────────────

def einstellung(k, _=None):
    """Einstellungszeile; beim allerersten Aufruf mit den Vorgaben (danach nie wieder)."""
    k = _k(k)
    z = k.con.execute("SELECT * FROM ub_einstellung WHERE lehrkraft_id = ?", (k.lid,)).fetchone()
    if z is None:
        k.con.execute("INSERT INTO ub_einstellung (lehrkraft_id, standard_ordnung) VALUES (?, 'chronologisch')", (k.lid,))
        for i, (name, ic, fa, sp) in enumerate(VORGABE_KATEGORIEN):
            k.con.execute("INSERT INTO ub_kategorie (lehrkraft_id, name, icon, farbe, spalte, position) VALUES (?, ?, ?, ?, ?, ?)",
                          (k.lid, name, ic, fa, sp, i))
        for i, name in enumerate(VORGABE_PHASEN):
            k.con.execute("INSERT INTO ub_phase (lehrkraft_id, name, position) VALUES (?, ?, ?)", (k.lid, name, i))
        for i, name in enumerate(VORGABE_KRITERIEN):
            k.con.execute("INSERT INTO ub_kriterium (lehrkraft_id, name, position) VALUES (?, ?, ?)", (k.lid, name, i))
        z = k.con.execute("SELECT * FROM ub_einstellung WHERE lehrkraft_id = ?", (k.lid,)).fetchone()
    return Zeile(standard_ordnung=z["standard_ordnung"])


def _obj(art, z):
    o = Zeile(id=z["id"], name=z["name"], position=z["position"], active=bool(z["aktiv"]))
    if art == "kategorien":
        o.icon, o.farbe, o.spalte = z["icon"], z["farbe"], z["spalte"]
    return o


def liste(k, _=None, art="kategorien", nur_aktive=False):
    k = _k(k)
    sql = "SELECT * FROM %s WHERE lehrkraft_id = ?" % TABELLEN[art] + (" AND aktiv = 1" if nur_aktive else "") + " ORDER BY position, id"
    return [_obj(art, z) for z in k.con.execute(sql, (k.lid,))]


def eintrag_spalte(art):
    return {"kategorien": "kategorie_id", "phasen": "phase_id", "kriterien": "kriterium_id"}[art]


def nutzung(k, art, oid):
    k = _k(k)
    n = k.con.execute("SELECT COUNT(*) FROM ub_eintrag WHERE %s = ?" % eintrag_spalte(art), (oid,)).fetchone()[0]
    if art == "kriterien":
        n += k.con.execute("SELECT COUNT(*) FROM ub_schwerpunkt WHERE kriterium_id = ?", (oid,)).fetchone()[0]
    return n


def einstellung_dict(art, o, nutzung_=None):
    d = {"id": o.id, "name": o.name, "position": o.position, "active": bool(o.active)}
    if art == "kategorien":
        d.update({"icon": o.icon, "farbe": o.farbe, "spalte": o.spalte})
    if nutzung_ is not None:
        d["nutzung"] = nutzung_
    return d


def katalog(k, _=None):
    einstellung(k)
    return {art: [einstellung_dict(art, o) for o in liste(k, None, art)] for art in TABELLEN}


def _art(art):
    if art not in TABELLEN:
        raise UbFehler("Nicht gefunden.", 404)
    return art


def _einstellungs_zeile(k, art, oid):
    z = k.con.execute("SELECT * FROM %s WHERE id = ? AND lehrkraft_id = ?" % TABELLEN[_art(art)], (oid, k.lid)).fetchone()
    if z is None:
        raise UbFehler("Nicht gefunden.", 404)
    return z


def _einstellung_werte(art, p, alt=None):
    w = {}
    if "name" in p:
        name = text(p.get("name"), 80)
        if not name:
            raise UbFehler("Der Name darf nicht leer sein.")
        w["name"] = name
    if "active" in p:
        w["aktiv"] = 1 if p.get("active") else 0
    if art == "kategorien":
        if "icon" in p:
            w["icon"] = icon_name(p.get("icon"))
        if "farbe" in p:
            w["farbe"] = farbe(p.get("farbe"))
        if "spalte" in p:
            w["spalte"] = spalte(p.get("spalte"))
    return w


def einstellung_anlegen(k, art, p):
    tab = TABELLEN[_art(art)]
    einstellung(k)
    pos = k.con.execute("SELECT MAX(position) FROM %s WHERE lehrkraft_id = ?" % tab, (k.lid,)).fetchone()[0]
    w = {"lehrkraft_id": k.lid, "position": (pos if pos is not None else -1) + 1}
    if art == "kategorien":
        w.update(icon=STANDARD_ICON, farbe=FARBEN[0][0], spalte="verlauf")
    w.update(_einstellung_werte(art, dict({"name": p.get("name")}, **p)))
    oid = k.con.execute("INSERT INTO %s (%s) VALUES (%s)" % (tab, ", ".join(w), ", ".join("?" * len(w))), list(w.values())).lastrowid
    return {"ok": True, "obj": einstellung_dict(art, _obj(art, _einstellungs_zeile(k, art, oid)), 0)}


def einstellung_reihenfolge(k, art, ids):
    tab = TABELLEN[_art(art)]
    eigene = {o.id for o in liste(k, None, art)}
    for i, oid in enumerate(ids or []):
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            continue
        if oid in eigene:
            k.con.execute("UPDATE %s SET position = ? WHERE id = ?" % tab, (i, oid))
    return {"ok": True}


def einstellung_speichern(k, art, oid, p):
    _einstellungs_zeile(k, art, oid)
    w = _einstellung_werte(art, p)
    if w:
        k.con.execute("UPDATE %s SET %s WHERE id = ?" % (TABELLEN[art], ", ".join("%s = ?" % x for x in w)), list(w.values()) + [oid])
    return {"ok": True, "obj": einstellung_dict(art, _obj(art, _einstellungs_zeile(k, art, oid)), nutzung(k, art, oid))}


def einstellung_loeschen(k, art, oid):
    _einstellungs_zeile(k, art, oid)
    n = nutzung(k, art, oid)
    if n:
        raise UbFehler("Wird in %d Einträgen verwendet — bitte stilllegen statt löschen." % n, 409)
    k.con.execute("DELETE FROM %s WHERE id = ?" % TABELLEN[art], (oid,))
    return {"ok": True}


def standard_ordnung_setzen(k, p):
    einstellung(k)
    if "standard_ordnung" in p:
        if p["standard_ordnung"] not in ORDNUNGEN:
            raise UbFehler("Unbekannte Ordnung.")
        k.con.execute("UPDATE ub_einstellung SET standard_ordnung = ? WHERE lehrkraft_id = ?", (p["standard_ordnung"], k.lid))
    return {"ok": True, "standard_ordnung": einstellung(k).standard_ordnung}


# ── Anwaerter ─────────────────────────────────────────────────────────────

def _anwaerter_zeile(k, aid):
    z = k.con.execute("SELECT * FROM ub_anwaerter WHERE id = ? AND lehrkraft_id = ?", (aid, k.lid)).fetchone()
    if z is None:
        raise UbFehler("Nicht gefunden.", 404)
    return z


def besuche_je_anwaerter(k, _=None):
    return {z[0]: z[1] for z in k.con.execute("SELECT anwaerter_id, COUNT(*) FROM ub_besuch WHERE lehrkraft_id = ? GROUP BY anwaerter_id", (k.lid,))}


def anwaerter_dict(z, besuche_=0):
    return {"id": z["id"], "name": z["name"], "faecher": z["faecher"], "seminar": z["seminar"], "notiz": z["notiz"],
            "active": bool(z["aktiv"]), "besuche": besuche_}


def anwaerter_liste(k):
    n = besuche_je_anwaerter(k)
    return [anwaerter_dict(z, n.get(z["id"], 0)) for z in
            k.con.execute("SELECT * FROM ub_anwaerter WHERE lehrkraft_id = ? ORDER BY aktiv DESC, name", (k.lid,))]


def _anwaerter_werte(p):
    w = {}
    if "name" in p:
        name = text(p.get("name"), 120)
        if not name:
            raise UbFehler("Der Anwärter braucht einen Namen.")
        w["name"] = name
    if "faecher" in p:
        w["faecher"] = text(p.get("faecher"), 200)
    if "seminar" in p:
        w["seminar"] = text(p.get("seminar"), 200)
    if "notiz" in p:
        w["notiz"] = text(p.get("notiz"))
    if "active" in p:
        w["aktiv"] = 1 if p.get("active") else 0
    return w


def anwaerter_anlegen(k, p):
    w = _anwaerter_werte(dict({"name": ""}, **p))
    w.update(lehrkraft_id=k.lid, erstellt=db.jetzt())
    aid = k.con.execute("INSERT INTO ub_anwaerter (%s) VALUES (%s)" % (", ".join(w), ", ".join("?" * len(w))), list(w.values())).lastrowid
    return aid


def anwaerter_speichern(k, aid, p):
    _anwaerter_zeile(k, aid)
    w = _anwaerter_werte(p)
    if w:
        k.con.execute("UPDATE ub_anwaerter SET %s WHERE id = ?" % ", ".join("%s = ?" % x for x in w), list(w.values()) + [aid])
    return {"ok": True, "anwaerter": anwaerter_dict(_anwaerter_zeile(k, aid), besuche_je_anwaerter(k).get(aid, 0))}


def anwaerter_besuche(k, aid):
    _anwaerter_zeile(k, aid)
    return {"ok": True, "besuche": [{"id": z["id"], "datum": z["datum"], "thema": z["thema"], "klasse": z["klasse"], "status": z["status"],
                                     "status_label": STATUS.get(z["status"], z["status"])}
                                    for z in k.con.execute("SELECT * FROM ub_besuch WHERE lehrkraft_id = ? AND anwaerter_id = ? "
                                                           "ORDER BY datum DESC, beginn DESC", (k.lid, aid))]}


def anwaerter_loeschen(k, aid):
    _anwaerter_zeile(k, aid)
    n = besuche_je_anwaerter(k).get(aid, 0)
    if n:
        raise UbFehler("An diesem Anwärter hängen %d Besuche — bitte stilllegen." % n, 409)
    k.con.execute("DELETE FROM ub_anwaerter WHERE id = ?", (aid,))
    return {"ok": True}


# ── Besuche ───────────────────────────────────────────────────────────────

def _besuch_zeile(k, bid):
    z = k.con.execute("SELECT b.*, a.name AS anwaerter_name, a.faecher AS anwaerter_faecher, a.seminar AS anwaerter_seminar FROM ub_besuch b JOIN ub_anwaerter a ON a.id = b.anwaerter_id "
                      "WHERE b.id = ? AND b.lehrkraft_id = ?", (bid, k.lid)).fetchone()
    if z is None:
        raise UbFehler("Nicht gefunden.", 404)
    return z


def besuch_obj(k, bid):
    """Besuch als Objekt mit Attributen wie im alten Tool (b.anwaerter.name, b.datum ...)."""
    z = _besuch_zeile(k, bid)
    return Zeile(id=z["id"], user_id=k.lid, anwaerter_id=z["anwaerter_id"], anwaerter=Zeile(id=z["anwaerter_id"], name=z["anwaerter_name"], faecher=z["anwaerter_faecher"],
                                                                                      seminar=z["anwaerter_seminar"]),
                 datum=z["datum"], beginn=z["beginn"], ende=z["ende"], klasse=z["klasse"], raum=z["raum"], thema=z["thema"],
                 lernziele=z["lernziele"], status=z["status"], reflexion=z["reflexion"], vereinbarungen=z["vereinbarungen"])


def besuche(k, _=None, anwaerter_id=None):
    sql = "SELECT id FROM ub_besuch WHERE lehrkraft_id = ?" + (" AND anwaerter_id = ?" if anwaerter_id else "") + " ORDER BY datum DESC, beginn DESC"
    return [besuch_obj(k, z[0]) for z in k.con.execute(sql, (k.lid, anwaerter_id) if anwaerter_id else (k.lid,))]


def schwerpunkte(k, besuch_id):
    k = _k(k)
    return [Zeile(id=z["id"], name=z["name"]) for z in k.con.execute(
        "SELECT kr.id, kr.name FROM ub_kriterium kr JOIN ub_schwerpunkt s ON s.kriterium_id = kr.id WHERE s.besuch_id = ? "
        "ORDER BY kr.position, kr.id", (besuch_id,))]


def setze_schwerpunkte(k, besuch_id, ids):
    gueltig = []
    for x in ids or []:
        try:
            kid = int(x)
        except (TypeError, ValueError):
            continue
        if kid not in gueltig and k.con.execute("SELECT 1 FROM ub_kriterium WHERE id = ? AND lehrkraft_id = ?", (kid, k.lid)).fetchone():
            gueltig.append(kid)
    k.con.execute("DELETE FROM ub_schwerpunkt WHERE besuch_id = ?", (besuch_id,))
    for pos, kid in enumerate(gueltig):
        k.con.execute("INSERT INTO ub_schwerpunkt (besuch_id, kriterium_id, position) VALUES (?, ?, ?)", (besuch_id, kid, pos))


def vorheriger_besuch(k, b):
    k = _k(k)
    kandidaten = [besuch_obj(k, z["id"]) for z in k.con.execute(
        "SELECT id, datum, beginn FROM ub_besuch WHERE lehrkraft_id = ? AND anwaerter_id = ? AND id != ?", (k.lid, b.anwaerter_id, b.id))
        if (z["datum"] or "", z["beginn"] or "", z["id"]) < (b.datum or "", b.beginn or "", b.id)]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda x: (x.datum or "", x.beginn or "", x.id))


def besuch_dict(k, b, mit_eintraegen=False):
    d = {"id": b.id, "anwaerter_id": b.anwaerter_id, "anwaerter": b.anwaerter.name, "datum": b.datum, "beginn": b.beginn, "ende": b.ende,
         "klasse": b.klasse, "raum": b.raum, "thema": b.thema, "lernziele": b.lernziele, "status": b.status,
         "status_label": STATUS.get(b.status, b.status), "reflexion": b.reflexion, "vereinbarungen": b.vereinbarungen,
         "schwerpunkte": [{"id": s.id, "text": s.name} for s in schwerpunkte(k, b.id)]}
    vor = vorheriger_besuch(k, b)
    d["vorige"] = ({"id": vor.id, "datum": vor.datum, "vereinbarungen": vor.vereinbarungen}
                   if vor and (vor.vereinbarungen or "").strip() else None)
    if mit_eintraegen:
        d["eintraege"] = [eintrag_dict(e) for e in eintraege(k, b.id)]
    return d


def ist_anstehend(b, heute):
    if b.status == "laufend":
        return True
    return b.status == "geplant" and (not b.datum or b.datum >= heute)


def _besuch_werte(p):
    w = {}
    if "datum" in p:
        w["datum"] = datum(p.get("datum"))
    if "beginn" in p:
        w["beginn"] = zeit(p.get("beginn"))
    if "ende" in p:
        w["ende"] = zeit(p.get("ende"))
    for feld, laenge in (("klasse", 80), ("raum", 40), ("thema", 300)):
        if feld in p:
            w[feld] = text(p.get(feld), laenge)
    for feld in ("lernziele", "reflexion", "vereinbarungen"):
        if feld in p:
            w[feld] = text(p.get(feld))
    if "status" in p and p.get("status") in STATUS:
        w["status"] = p["status"]
    return w


def besuch_anlegen(k, p):
    """Ein Aufruf am Ende des Assistenten, inklusive eines eventuell neuen Anwaerters."""
    neu = p.get("neuer_anwaerter")
    if neu:
        aid = anwaerter_anlegen(k, neu)
    else:
        try:
            aid = int(p.get("anwaerter_id") or 0)
        except (TypeError, ValueError):
            aid = 0
        _anwaerter_zeile(k, aid)
    w = {"status": "geplant"}
    w.update(_besuch_werte(p))
    if not w.get("datum"):
        raise UbFehler("Der Besuch braucht ein Datum.")
    jetzt = db.jetzt()
    w.update(lehrkraft_id=k.lid, anwaerter_id=aid, erstellt=jetzt, geaendert=jetzt)
    bid = k.con.execute("INSERT INTO ub_besuch (%s) VALUES (%s)" % (", ".join(w), ", ".join("?" * len(w))), list(w.values())).lastrowid
    setze_schwerpunkte(k, bid, p.get("schwerpunkte") or [])
    return {"ok": True, "id": bid}


def besuch_speichern(k, bid, p):
    _besuch_zeile(k, bid)
    w = _besuch_werte(p)
    if "anwaerter_id" in p:
        try:
            aid = int(p.get("anwaerter_id") or 0)
        except (TypeError, ValueError):
            aid = 0
        w["anwaerter_id"] = _anwaerter_zeile(k, aid)["id"]
    if "datum" in p and not w.get("datum"):
        raise UbFehler("Der Besuch braucht ein Datum.")
    if w:
        w["geaendert"] = db.jetzt()
        k.con.execute("UPDATE ub_besuch SET %s WHERE id = ?" % ", ".join("%s = ?" % x for x in w), list(w.values()) + [bid])
    if "schwerpunkte" in p:
        setze_schwerpunkte(k, bid, p.get("schwerpunkte") or [])
    return {"ok": True, "besuch": besuch_dict(k, besuch_obj(k, bid))}


def besuch_loeschen(k, bid):
    _besuch_zeile(k, bid)
    k.con.execute("DELETE FROM ub_datei WHERE uuid IN (SELECT foto_uuid FROM ub_eintrag WHERE besuch_id = ? UNION "
                  "SELECT skizze_uuid FROM ub_eintrag WHERE besuch_id = ?)", (bid, bid))
    k.con.execute("DELETE FROM ub_besuch WHERE id = ?", (bid,))   # Eintraege und Schwerpunkte gehen mit
    return {"ok": True}


# ── Eintraege ─────────────────────────────────────────────────────────────

def _eintrag_obj(z):
    return Zeile(id=z["id"], besuch_id=z["besuch_id"], art=z["art"], zeit=z["zeit"], position=z["position"], phase_id=z["phase_id"],
                 kategorie_id=z["kategorie_id"], text=z["text"], kriterium_id=z["kriterium_id"], wertung=z["wertung"], bezug_id=z["bezug_id"],
                 file_uuid=z["foto_uuid"], filename=z["foto_name"], skizze_json=z["skizze_json"], skizze_uuid=z["skizze_uuid"],
                 skizze_filename=z["skizze_name"])


def eintraege(k, besuch_id):
    """Chronologisch: nach Uhrzeit, bei gleicher Minute in Anlegereihenfolge; ohne Uhrzeit ans Ende."""
    k = _k(k)
    alle = [_eintrag_obj(z) for z in k.con.execute("SELECT * FROM ub_eintrag WHERE besuch_id = ?", (besuch_id,))]
    alle.sort(key=lambda e: (e.zeit or "99:99", e.position, e.id))
    return alle


def eintrag_dict(e):
    return {"id": e.id, "art": e.art, "zeit": e.zeit, "position": e.position, "phase_id": e.phase_id, "kategorie_id": e.kategorie_id,
            "text": e.text, "kriterium_id": e.kriterium_id, "wertung": e.wertung, "bezug_id": e.bezug_id,
            "foto": ("/api/files/%s/%s" % (e.file_uuid, e.filename) if e.file_uuid else ""),
            "skizze": ("/api/files/%s/%s" % (e.skizze_uuid, e.skizze_filename) if e.skizze_uuid else "")}


def mit_phasen(eintraege_):
    aktuell = None
    out = []
    for e in eintraege_:
        if e.art == "phase":
            aktuell = e.phase_id
        out.append((e, aktuell))
    return out


def _eintrag_zeile(k, eid):
    z = k.con.execute("SELECT e.* FROM ub_eintrag e JOIN ub_besuch b ON b.id = e.besuch_id WHERE e.id = ? AND b.lehrkraft_id = ?",
                      (eid, k.lid)).fetchone()
    if z is None:
        raise UbFehler("Nicht gefunden.", 404)
    return z


def _eigene_id(k, tab, wert):
    try:
        oid = int(wert)
    except (TypeError, ValueError):
        return None
    return oid if k.con.execute("SELECT 1 FROM %s WHERE id = ? AND lehrkraft_id = ?" % tab, (oid, k.lid)).fetchone() else None


def _eintrag_werte(k, besuch_id, art, eid, p):
    w = {}
    if "zeit" in p:
        w["zeit"] = zeit(p.get("zeit"))
    if art == "phase":
        if "phase_id" in p:
            pid = _eigene_id(k, "ub_phase", p.get("phase_id"))
            if not pid:
                raise UbFehler("Unbekannte Phase.")
            w["phase_id"] = pid
        return w
    if "kategorie_id" in p:
        kid = _eigene_id(k, "ub_kategorie", p.get("kategorie_id"))
        if not kid:
            raise UbFehler("Unbekannte Kategorie.")
        w["kategorie_id"] = kid
    if "text" in p:
        w["text"] = text(p.get("text"))
    if "kriterium_id" in p:
        w["kriterium_id"] = _eigene_id(k, "ub_kriterium", p.get("kriterium_id"))
    if "wertung" in p:
        w["wertung"] = wertung(p.get("wertung"))
    if "bezug_id" in p:
        w["bezug_id"] = None
        ref = p.get("bezug_id")
        if ref:
            try:
                ref = int(ref)
            except (TypeError, ValueError):
                ref = None
            r = k.con.execute("SELECT id FROM ub_eintrag WHERE id = ? AND besuch_id = ?", (ref, besuch_id)).fetchone() if ref else None
            if r and r["id"] != eid:
                w["bezug_id"] = r["id"]
    return w


def eintrag_anlegen(k, bid, p):
    b = _besuch_zeile(k, bid)
    art = "phase" if p.get("art") == "phase" else "eintrag"
    if art == "phase" and "phase_id" not in p:
        raise UbFehler("Unbekannte Phase.")
    if art == "eintrag" and "kategorie_id" not in p:
        raise UbFehler("Unbekannte Kategorie.")
    w = _eintrag_werte(k, bid, art, None, p)
    if art == "eintrag" and not w.get("text") and not p.get("foto_folgt"):
        raise UbFehler("Der Eintrag braucht einen Text.")
    pos = (k.con.execute("SELECT MAX(position) FROM ub_eintrag WHERE besuch_id = ?", (bid,)).fetchone()[0] or 0) + 10
    w.update(besuch_id=bid, art=art, position=pos, erstellt=db.jetzt())
    eid = k.con.execute("INSERT INTO ub_eintrag (%s) VALUES (%s)" % (", ".join(w), ", ".join("?" * len(w))), list(w.values())).lastrowid
    status = b["status"]
    if status == "geplant":     # der erste Eintrag setzt den Besuch auf „laeuft“
        status = "laufend"
        k.con.execute("UPDATE ub_besuch SET status = 'laufend' WHERE id = ?", (bid,))
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid))), "status": status}


def eintrag_speichern(k, eid, p):
    z = _eintrag_zeile(k, eid)
    w = _eintrag_werte(k, z["besuch_id"], z["art"], eid, p)
    if z["art"] == "eintrag" and "text" in p and not w.get("text") and not z["foto_uuid"] and not z["skizze_uuid"]:
        raise UbFehler("Der Eintrag braucht einen Text.")
    if w:
        k.con.execute("UPDATE ub_eintrag SET %s WHERE id = ?" % ", ".join("%s = ?" % x for x in w), list(w.values()) + [eid])
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid)))}


def _datei_weg(k, uuid_):
    if uuid_:
        k.con.execute("DELETE FROM ub_datei WHERE uuid = ? AND lehrkraft_id = ?", (uuid_, k.lid))


def _skizze_entfernen(k, z):
    _datei_weg(k, z["skizze_uuid"])
    k.con.execute("UPDATE ub_eintrag SET skizze_uuid = '', skizze_name = '', skizze_json = '' WHERE id = ?", (z["id"],))


def _skizze_auf_foto(z):
    try:
        return json.loads(z["skizze_json"] or "{}").get("hintergrund") == "foto"
    except ValueError:
        return False


def _foto_entfernen(k, z):
    """Entfernt das Foto und eine darauf gezeichnete Skizze gleich mit."""
    if _skizze_auf_foto(z):
        _skizze_entfernen(k, z)
    if z["foto_uuid"]:
        _datei_weg(k, z["foto_uuid"])
        k.con.execute("UPDATE ub_eintrag SET foto_uuid = '', foto_name = '' WHERE id = ?", (z["id"],))


def eintrag_loeschen(k, eid):
    z = _eintrag_zeile(k, eid)
    _skizze_entfernen(k, z)
    _foto_entfernen(k, _eintrag_zeile(k, eid))
    k.con.execute("UPDATE ub_eintrag SET bezug_id = NULL WHERE bezug_id = ?", (eid,))
    k.con.execute("DELETE FROM ub_eintrag WHERE id = ?", (eid,))
    return {"ok": True}


def _datei_aus(daten_url, erlaubt, standard_name):
    """'data:image/jpeg;base64,...' -> (bytes, mime, name)."""
    m = re.fullmatch(r"data:([a-z]+/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", daten_url or "")
    if not m or m.group(1) not in erlaubt:
        raise UbFehler("Nur %s." % ", ".join(sorted(set(x.split("/")[1].upper() for x in erlaubt))))
    roh = base64.b64decode(m.group(2))
    if not roh:
        raise UbFehler("Leere Datei.")
    if len(roh) > MAX_DATEI:
        raise UbFehler("Datei zu groß (max %d MB)." % (MAX_DATEI // (1024 * 1024)))
    endung = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[m.group(1)]
    return roh, m.group(1), "%s.%s" % (standard_name, endung)


def _datei_speichern(k, roh, mime, name):
    uuid_ = uuid.uuid4().hex
    k.con.execute("INSERT INTO ub_datei (uuid, lehrkraft_id, name, mime, daten, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                  (uuid_, k.lid, name, mime, roh, db.jetzt()))
    return uuid_


def foto_speichern(k, eid, p):
    z = _eintrag_zeile(k, eid)
    if z["art"] != "eintrag":
        raise UbFehler("Nur Einträge können ein Foto haben.")
    roh, mime, name = _datei_aus(p.get("datei"), ("image/jpeg", "image/png", "image/webp"), "foto")
    _foto_entfernen(k, z)          # ein Foto je Eintrag
    uuid_ = _datei_speichern(k, roh, mime, name)
    k.con.execute("UPDATE ub_eintrag SET foto_uuid = ?, foto_name = ? WHERE id = ?", (uuid_, name, eid))
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid)))}


def foto_loeschen(k, eid):
    _foto_entfernen(k, _eintrag_zeile(k, eid))
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid)))}


def skizze_lesen(k, eid):
    z = _eintrag_zeile(k, eid)
    return {"ok": True, "skizze": json.loads(z["skizze_json"]) if z["skizze_json"] else None}


def skizze_speichern(k, eid, p):
    """Striche (JSON) und das im Browser gerenderte Bild; das Bild zeigen Verlauf und Protokoll."""
    z = _eintrag_zeile(k, eid)
    if z["art"] != "eintrag":
        raise UbFehler("Nur Einträge können eine Skizze haben.")
    striche = p.get("striche") or ""
    if len(striche.encode("utf-8")) > MAX_SKIZZE:
        raise UbFehler("Die Skizze ist zu groß.")
    try:
        d = json.loads(striche)
    except ValueError:
        raise UbFehler("Ungültige Skizze.")
    if not isinstance(d, dict) or not isinstance(d.get("striche"), list) or d.get("hintergrund") not in ("leer", "foto"):
        raise UbFehler("Ungültige Skizze.")
    if d["hintergrund"] == "foto" and not z["foto_uuid"]:
        raise UbFehler("Die Skizze gehört zu einem Foto, der Eintrag hat aber keins.")
    roh, mime, name = _datei_aus(p.get("datei"), ("image/jpeg", "image/png"), "skizze")
    _skizze_entfernen(k, z)
    uuid_ = _datei_speichern(k, roh, mime, name)
    k.con.execute("UPDATE ub_eintrag SET skizze_uuid = ?, skizze_name = ?, skizze_json = ? WHERE id = ?", (uuid_, name, striche, eid))
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid)))}


def skizze_loeschen(k, eid):
    _skizze_entfernen(k, _eintrag_zeile(k, eid))
    return {"ok": True, "eintrag": eintrag_dict(_eintrag_obj(_eintrag_zeile(k, eid)))}


class Datei:
    """Bild aus der Datenbank, wo das alte Tool einen Dateipfad hatte (read_bytes() wie pathlib.Path)."""

    def __init__(self, daten, name):
        self._daten, self.name = daten, name

    def read_bytes(self):
        return self._daten

    def oeffnen(self):
        return io.BytesIO(self._daten)


def datei(k, uuid_, _name=None):
    """Datei einer Lehrkraft (Foto, Skizze) oder None."""
    k = _k(k)
    if not re.fullmatch(r"[a-f0-9]{32}", uuid_ or ""):
        return None
    z = k.con.execute("SELECT name, mime, daten FROM ub_datei WHERE uuid = ? AND lehrkraft_id = ?", (uuid_, k.lid)).fetchone()
    return Datei(bytes(z["daten"]), z["name"]) if z else None


def datei_mime(k, uuid_):
    z = k.con.execute("SELECT mime FROM ub_datei WHERE uuid = ? AND lehrkraft_id = ?", (uuid_, k.lid)).fetchone()
    return z["mime"] if z else None


# ── Seiten (an Stelle der Jinja-Vorlagen): was window.UB je Seite enthaelt ──

def seite_uebersicht(k, heute):
    einstellung(k)
    alle = besuche(k)
    anstehend = sorted([b for b in alle if ist_anstehend(b, heute)], key=lambda b: (b.datum or "9999", b.beginn or ""))
    vergangen = [b for b in alle if not ist_anstehend(b, heute)]
    zahl = {z[0]: z[1] for z in k.con.execute("SELECT e.besuch_id, COUNT(*) FROM ub_eintrag e JOIN ub_besuch b ON b.id = e.besuch_id "
                                              "WHERE b.lehrkraft_id = ? AND e.art = 'eintrag' GROUP BY e.besuch_id", (k.lid,))}
    kurz = lambda b: {"id": b.id, "datum": b.datum, "beginn": b.beginn, "ende": b.ende, "status": b.status, "anwaerter": b.anwaerter.name,
                      "thema": b.thema, "klasse": b.klasse, "raum": b.raum, "eintraege": zahl.get(b.id, 0)}
    return {"anwaerter": anwaerter_liste(k), "schwerpunktKatalog": [{"id": o.id, "name": o.name} for o in liste(k, None, "kriterien", True)],
            "heute": heute, "anstehend": [kurz(b) for b in anstehend], "vergangen": [kurz(b) for b in vergangen]}


def seite_besuch(k, bid):
    b = besuch_obj(k, bid)
    return {"besuch": besuch_dict(k, b, mit_eintraegen=True), "katalog": katalog(k), "icons": icon_katalog(), "wertungen": WERTUNGEN,
            "status": STATUS, "ordnungen": ORDNUNGEN, "standardOrdnung": einstellung(k).standard_ordnung}


def seite_einstellungen(k):
    einstellung(k)
    daten = {art: [einstellung_dict(art, o, nutzung(k, art, o.id)) for o in liste(k, None, art)] for art in TABELLEN}
    return {"daten": daten, "icons": icon_katalog(), "farben": FARBEN, "spalten": SPALTEN, "ordnungen": ORDNUNGEN,
            "standardOrdnung": einstellung(k).standard_ordnung}
