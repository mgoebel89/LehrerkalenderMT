"""Notenschluessel: Prozent -> Note in drei Systemen (Tendenznoten, Zehntelnoten, MSS-Punkte).

Ein Schluessel speichert je Notenstufe die untere Prozentgrenze ("ab %"); die obere ergibt sich aus der naechsten Stufe.
Konferenzschluessel (je Bildungsgang einer) pflegt der Admin fuer alle, eigene Schluessel gehoeren einer Lehrkraft.
Neue Schluessel starten mit den Tabellen aus dem alten Lehrerkalender (app/services/grading.py), die man dann anpasst.

Zehntelnoten: Grenzen der ganzen Noten, dazwischen linear: Note g reicht von g-0,5 (an der oberen Grenze) bis g+0,4
(an der unteren); die 1 beginnt bei 1,0, die 6 endet bei 6,0. Gerechnet wird mit auf ganze Prozent gerundeten Werten.
"""
import json

from . import db

SYSTEME = ("tendenz", "zehntel", "punkte")
SYSTEMNAME = {"tendenz": "Tendenznoten", "zehntel": "Zehntelnoten", "punkte": "MSS-Punkte"}
STUFEN = {
    "tendenz": ["1", "1-", "2+", "2", "2-", "3+", "3", "3-", "4+", "4", "4-", "5+", "5", "5-", "6"],
    "zehntel": ["1", "2", "3", "4", "5", "6"],
    "punkte": [str(p) for p in range(15, -1, -1)],
}
VORGABE = {
    "tendenz": [92, 88, 84, 80, 76, 72, 68, 64, 60, 55, 50, 45, 40, 33, 0],
    "zehntel": [88, 76, 64, 50, 33, 0],
    "punkte": [95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 33, 27, 20, 0],
}


class SchluesselFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def vorgabe(system):
    if system not in SYSTEME:
        raise SchluesselFehler("Unbekanntes Notensystem.")
    return dict(zip(STUFEN[system], VORGABE[system]))


def grenzen_pruefen(system, grenzen):
    """{stufe: ab_prozent} -> dieselbe Zuordnung mit ganzen Zahlen, wenn lueckenlos und absteigend; sonst Fehler."""
    if system not in SYSTEME:
        raise SchluesselFehler("Unbekanntes Notensystem.")
    if not isinstance(grenzen, dict):
        raise SchluesselFehler("Ungültige Grenzen.")
    werte = []
    for stufe in STUFEN[system]:
        try:
            wert = int(grenzen.get(stufe))
        except (TypeError, ValueError):
            raise SchluesselFehler("Bei Note %s fehlt die Grenze „ab %%“." % stufe.replace("-", "−"))
        if not 0 <= wert <= 100:
            raise SchluesselFehler("Die Grenze bei Note %s muss zwischen 0 und 100 liegen." % stufe.replace("-", "−"))
        werte.append(wert)
    for (s1, w1), (s2, w2) in zip(zip(STUFEN[system], werte), zip(STUFEN[system][1:], werte[1:])):
        if w2 >= w1:
            raise SchluesselFehler("Note %s muss unter Note %s beginnen (%d %% ist nicht kleiner als %d %%)."
                                   % (s2.replace("-", "−"), s1.replace("-", "−"), w2, w1))
    if werte[-1] != 0:
        raise SchluesselFehler("Die schlechteste Note muss bei 0 % beginnen, sonst bleibt eine Lücke.")
    return dict(zip(STUFEN[system], werte))


def _dezimal_tendenz(stufe):
    return int(stufe[0]) + (-0.3 if stufe.endswith("+") else 0.3 if stufe.endswith("-") else 0.0)


def note(system, grenzen, prozent):
    """Note fuer einen Prozentwert: {"text": "2+", "dezimal": 1.7, "stufe": "2+"}."""
    q = round(max(0.0, min(100.0, float(prozent))))
    stufen = STUFEN[system]
    werte = [grenzen[s] for s in stufen]
    for i, (stufe, ab) in enumerate(zip(stufen, werte)):
        if q >= ab:
            break
    if system == "punkte":
        p = int(stufe)
        return {"text": "%d P" % p, "dezimal": round((17 - p) / 3, 1), "stufe": stufe}
    if system == "tendenz":
        return {"text": stufe.replace("-", "−"), "dezimal": round(_dezimal_tendenz(stufe), 1), "stufe": stufe}
    # Zehntel: linear innerhalb der ganzen Note
    g = int(stufe)
    oben_grenze = 100 if i == 0 else werte[i - 1] - 1
    oben, unten = (1.0 if g == 1 else g - 0.5), (6.0 if g == 6 else g + 0.4)
    anteil = 1.0 if oben_grenze == ab else (q - ab) / (oben_grenze - ab)
    wert = round(unten - anteil * (unten - oben), 1)
    return {"text": ("%.1f" % wert).replace(".", ","), "dezimal": wert, "stufe": stufe}


# --- Speichern ---

def _aus_zeile(z):
    return {"id": z["id"], "name": z["name"], "system": z["system"], "systemname": SYSTEMNAME[z["system"]], "art": z["art"],
            "bildungsgang_id": z["bildungsgang_id"], "besitzer_id": z["besitzer_id"], "grenzen": json.loads(z["grenzen"]),
            "stufen": STUFEN[z["system"]], "geaendert": z["geaendert"]}


def liste(con, konto):
    """Konferenzschluessel (alle) und die eigenen der Lehrkraft."""
    zeilen = con.execute("SELECT * FROM notenschluessel WHERE art = 'konferenz' OR besitzer_id = ? "
                         "ORDER BY art, name", (konto["id"],))
    return [_aus_zeile(z) for z in zeilen]


def holen(con, sid):
    z = con.execute("SELECT * FROM notenschluessel WHERE id = ?", (sid,)).fetchone()
    return _aus_zeile(z) if z else None


def _darf_aendern(konto, s):
    if s["art"] == "konferenz":
        if konto["rolle"] != "admin":
            raise SchluesselFehler("Konferenzschlüssel ändert nur der Admin. Du kannst ihn als eigenen kopieren.")
    elif s["besitzer_id"] != konto["id"]:
        raise SchluesselFehler("Diesen Schlüssel gibt es nicht.")


def speichern(con, konto, daten, sid=None):
    name = (daten.get("name") or "").strip()
    if not 2 <= len(name) <= 60:
        raise SchluesselFehler("Bitte einen Namen mit 2 bis 60 Zeichen angeben.")
    if sid is not None:
        alt = holen(con, sid)
        if alt is None:
            raise SchluesselFehler("Diesen Schlüssel gibt es nicht.")
        _darf_aendern(konto, alt)
        art, bid, system = alt["art"], alt["bildungsgang_id"], alt["system"]
    else:
        art = daten.get("art") or "eigen"
        system = daten.get("system")
        if art not in ("konferenz", "eigen"):
            raise SchluesselFehler("Unbekannte Art.")
        bid = None
        if art == "konferenz":
            if konto["rolle"] != "admin":
                raise SchluesselFehler("Konferenzschlüssel legt nur der Admin an.")
            try:
                bid = int(daten.get("bildungsgang_id"))
            except (TypeError, ValueError):
                raise SchluesselFehler("Bitte den Bildungsgang wählen.")
            if con.execute("SELECT 1 FROM bildungsgang WHERE id = ?", (bid,)).fetchone() is None:
                raise SchluesselFehler("Diesen Bildungsgang gibt es nicht.")
            if con.execute("SELECT 1 FROM notenschluessel WHERE art = 'konferenz' AND bildungsgang_id = ?", (bid,)).fetchone():
                raise SchluesselFehler("Für diesen Bildungsgang gibt es schon einen Konferenzschlüssel.")
    system = daten.get("system") or system
    grenzen = grenzen_pruefen(system, daten.get("grenzen") if daten.get("grenzen") is not None else vorgabe(system))
    if sid is None:
        jetzt = db.jetzt()
        return con.execute("INSERT INTO notenschluessel (name, system, art, bildungsgang_id, besitzer_id, grenzen, erstellt, geaendert) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (name, system, art, bid, konto["id"] if art == "eigen" else None,
                            json.dumps(grenzen), jetzt, jetzt)).lastrowid
    con.execute("UPDATE notenschluessel SET name = ?, system = ?, grenzen = ?, geaendert = ? WHERE id = ?",
                (name, system, json.dumps(grenzen), db.jetzt(), sid))
    return sid


def kopieren(con, konto, sid):
    s = holen(con, sid)
    if s is None or (s["art"] == "eigen" and s["besitzer_id"] != konto["id"]):
        raise SchluesselFehler("Diesen Schlüssel gibt es nicht.")
    return speichern(con, konto, {"name": ("Kopie von " + s["name"])[:60], "art": "eigen", "system": s["system"],
                                  "grenzen": s["grenzen"]})


def loeschen(con, konto, sid):
    s = holen(con, sid)
    if s is None:
        raise SchluesselFehler("Diesen Schlüssel gibt es nicht.")
    _darf_aendern(konto, s)
    con.execute("DELETE FROM notenschluessel WHERE id = ?", (sid,))
