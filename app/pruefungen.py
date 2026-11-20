"""Pruefungen und Bewertung (Stufe D1).

Grundregeln (Konzept Abschnitt 5):
  - Die Schuelerliste ist die Wahrheit: ein Import legt nur neue Schueler an und aendert nie Namen.
  - Gespeichert werden Punkte bzw. gewaehlte Stufen; Prozent und Note entstehen erst ueber den Notenschluessel.
  - Jede Note hat einen sichtbaren Rechenweg.

Erfassung einer Pruefung:
  aufgaben  Punkte je Aufgabe (z. B. Klassenarbeit): Prozent = Summe erreicht / Summe maximal
  gesamt    nur Gesamtpunkte je Schueler: Prozent = erreicht / maximal
  bogen     Feedbackbogen (aus einer Vorlage kopiert): Bereiche mit Gewicht, Kriterien als Stufen (mit Punkten),
            Punkte, Abhaken (nur Information) oder Freitext. Kriterium -> Prozent, Bereich = gewichteter Schnitt der
            bewerteten Kriterien, gesamt = gewichteter Schnitt der bewerteten Bereiche. Unbewertetes zaehlt nicht,
            wird aber gemeldet.

Welcher Notenschluessel gilt: in der Pruefung gewaehlt -> Schluessel der Klasse -> persoenlicher Standard der
Lehrkraft -> Konferenzschluessel des Bildungsgangs. Beim Abschliessen wird der Schluessel eingefroren.

Zeitform: fester Termin (belegt als festgesetztes Thema der Planung seine Bloecke) oder Fenster mit Frist (belegt
keine Bloecke, laeuft nebenher).
"""
import datetime
import json
import random
import re

from . import db, grunddaten, notenschluessel, schuelerliste, stundenplan

ARTEN = {"schriftlich": "schriftlich", "muendlich": "mündlich", "praktisch": "praktisch", "portfolio": "Portfolio"}
ERFASSUNGEN = ("aufgaben", "gesamt", "bogen", "checkliste")
ERFASSUNG_NAMEN = {"aufgaben": "Punkte je Aufgabe", "gesamt": "Gesamtpunkte", "bogen": "Feedbackbogen", "checkliste": "Checkliste"}
TYPEN = ("stufen", "punkte", "haken", "text", "check")   # check = Haken mit Punkten (Checkliste)
STAENDE = ("geplant", "angekuendigt", "durchgefuehrt", "ausgewertet")
# Einschaetzung einer gezogenen oder spontanen Frage im Pruefungsmodus (Stufe 0-4)
FRAGE_STUFEN = ["nicht beantwortet", "ansatzweise mit Hilfe", "mit Hilfe beantwortet", "selbstständig beantwortet", "exzellent beantwortet"]
EINSTELLUNGEN = {"minuten": (15, 1, 240), "vorwarnung": (2, 0, 60), "gesamt_minuten": (90, 1, 600), "fragen_anzahl": (2, 1, 10),
                 "fragen_gewicht": (0, 0, 1000)}
STANDARD_STUFEN = [{"name": "nicht erkennbar", "punkte": 0}, {"name": "ansatzweise", "punkte": 1},
                   {"name": "überwiegend", "punkte": 2}, {"name": "vollständig", "punkte": 3}]


class PruefungFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _text(wert, feld, max_len=200, pflicht=True):
    wert = wert.strip() if isinstance(wert, str) else ""
    if pflicht and not wert:
        raise PruefungFehler("Bitte %s angeben." % feld)
    if len(wert) > max_len:
        raise PruefungFehler("%s darf höchstens %d Zeichen haben." % (feld[0].upper() + feld[1:], max_len))
    return wert


def _id(wert):
    if wert in (None, "", 0, "0"):
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise PruefungFehler("Ungültige Auswahl.")


def _zahl(wert, feld, minimum=0.0, maximum=10000.0):
    try:
        zahl = float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        raise PruefungFehler("Bitte bei %s eine Zahl angeben." % feld)
    if not minimum <= zahl <= maximum:
        raise PruefungFehler("%s muss zwischen %s und %s liegen." % (feld, _fmt(minimum), _fmt(maximum)))
    return zahl


def _fmt(zahl, stellen=1):
    """Zahl deutsch: 12 / 12,5 / 76,7."""
    if zahl is None:
        return "–"
    if abs(zahl - round(zahl)) < 1e-9:
        return str(int(round(zahl)))
    return ("%.*f" % (stellen, zahl)).replace(".", ",")


normalisiert = schuelerliste.normalisiert


# --- Schuelerlisten: gemeinsam je Klasse (app/schuelerliste.py); hier nur mit den Fehlern der Pruefungen ---

def _sl(funktion, *args):
    try:
        return funktion(*args)
    except schuelerliste.SchuelerFehler as f:
        raise PruefungFehler(str(f))


def _klasse(con, kid):
    if kid is None or con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
        raise PruefungFehler("Bitte eine Klasse wählen.")
    return kid


def schueler(con, lid, kid, nur_aktive=False):
    return _sl(schuelerliste.liste, con, lid, kid, nur_aktive)


def _schueler_zeile(con, lid, sid):
    return _sl(schuelerliste.zeile, con, lid, sid)


def schueler_speichern(con, lid, daten, sid=None):
    return _sl(schuelerliste.speichern, con, lid, daten, sid)


def schueler_loeschen(con, lid, sid):
    return _sl(schuelerliste.loeschen, con, lid, sid)


def moodle_csv(con, lid, kid, text):
    return _sl(schuelerliste.moodle_csv, con, lid, kid, text)


# --- Struktur (Feedbackbogen bzw. Aufgaben) ---

def struktur_pruefen(struktur):
    """Prueft und vervollstaendigt eine Struktur {bereiche: [{name, gewicht, kriterien: [{key, name, typ, max, gewicht,
    stufen}]}]}; vergibt fehlende Schluessel k1, k2 ..."""
    if not isinstance(struktur, dict) or not isinstance(struktur.get("bereiche"), list):
        raise PruefungFehler("Ungültiger Aufbau.")
    bereiche = struktur["bereiche"]
    if not 1 <= len(bereiche) <= 12:
        raise PruefungFehler("Ein Bogen braucht 1 bis 12 Bereiche.")
    vergeben = {k.get("key") for b in bereiche if isinstance(b, dict) for k in (b.get("kriterien") or []) if isinstance(k, dict)}
    naechster = 1
    sauber = []
    for b in bereiche:
        if not isinstance(b, dict):
            raise PruefungFehler("Ungültiger Bereich.")
        name = _text(b.get("name"), "einen Namen für jeden Bereich", 80)
        gewicht = _zahl(b.get("gewicht") if b.get("gewicht") not in (None, "") else 1, "Gewicht von „%s“" % name, 0.01, 1000)
        kriterien = b.get("kriterien") or []
        if not 1 <= len(kriterien) <= 60:
            raise PruefungFehler("Bereich „%s“ braucht 1 bis 60 Kriterien bzw. Aufgaben." % name)
        ks = []
        for k in kriterien:
            if not isinstance(k, dict):
                raise PruefungFehler("Ungültiges Kriterium.")
            kname = _text(k.get("name"), "einen Namen für jedes Kriterium", 120)
            typ = k.get("typ") or "punkte"
            if typ not in TYPEN:
                raise PruefungFehler("Unbekannte Art bei „%s“." % kname)
            key = k.get("key")
            if not key or not re.fullmatch(r"k\d{1,4}", str(key)):
                while "k%d" % naechster in vergeben:
                    naechster += 1
                key = "k%d" % naechster
                vergeben.add(key)
            neu = {"key": key, "name": kname, "typ": typ}
            if typ == "punkte":
                neu["max"] = _zahl(k.get("max"), "Höchstpunkte von „%s“" % kname, 0.5, 1000)
            if typ == "check":
                neu["max"] = _zahl(k.get("max") if k.get("max") not in (None, "") else 1, "Punkte von „%s“" % kname, 0.5, 1000)
            if typ == "stufen":
                stufen = k.get("stufen") or STANDARD_STUFEN
                if not isinstance(stufen, list) or not 2 <= len(stufen) <= 8:
                    raise PruefungFehler("„%s“ braucht 2 bis 8 Stufen." % kname)
                neu["stufen"] = [{"name": _text(st.get("name"), "einen Namen für jede Stufe", 60),
                                  "punkte": _zahl(st.get("punkte"), "Punkte einer Stufe von „%s“" % kname, 0, 100),
                                  "text": _text(st.get("text"), "die Beschreibung", 300, pflicht=False)} for st in stufen]
                if max(st["punkte"] for st in neu["stufen"]) <= 0:
                    raise PruefungFehler("Bei „%s“ muss mindestens eine Stufe Punkte bringen." % kname)
            if typ in ("stufen", "punkte") and k.get("gewicht") not in (None, ""):
                neu["gewicht"] = _zahl(k.get("gewicht"), "Gewicht von „%s“" % kname, 0.01, 100)
            ks.append(neu)
        sauber.append({"name": name, "gewicht": gewicht, "kriterien": ks, "team": bool(b.get("team"))})
    ergebnis_ = {"bereiche": sauber}
    if struktur.get("testat"):
        ergebnis_["testat"] = True
    return ergebnis_


def _kriterien(struktur):
    return [k for b in struktur["bereiche"] for k in b["kriterien"]]


# --- Berechnung ---

def _kriterium_prozent(k, wert):
    """Anteil (0..1) eines bewerteten Kriteriums, sonst None; dazu Text fuer den Rechenweg."""
    if k["typ"] == "check":
        wert = bool(wert)
    elif wert in (None, ""):
        return None, None
    if k["typ"] == "punkte":
        p = float(wert)
        return p / k["max"], "%s %s/%s P" % (k["name"], _fmt(p), _fmt(k["max"]))
    if k["typ"] == "check":
        return (1.0 if wert else 0.0), "%s %s" % (k["name"], ("✓ " + _fmt(k["max"]) + " P") if wert else "–")
    if k["typ"] == "stufen":
        hoechst = max(st["punkte"] for st in k["stufen"])
        st = k["stufen"][int(wert)]
        return st["punkte"] / hoechst, "%s „%s“ %s/%s" % (k["name"], st["name"], _fmt(st["punkte"]), _fmt(hoechst))
    return None, None


def berechnen(erfassung, struktur, max_punkte, werte, fragen=None, fragen_gewicht=0):
    """Prozent (0..100) mit Rechenweg. Rueckgabe {prozent, rechenweg: [zeilen], fehlend: [namen], bereiche: [...]}"""
    werte = werte or {}
    if erfassung == "gesamt":
        if werte.get("gesamt") in (None, ""):
            return {"prozent": None, "rechenweg": [], "fehlend": ["Gesamtpunkte"], "bereiche": []}
        p = float(werte["gesamt"])
        prozent = 100.0 * p / max_punkte
        return {"prozent": prozent, "fehlend": [], "bereiche": [],
                "rechenweg": ["%s von %s Punkten = %s %%" % (_fmt(p), _fmt(max_punkte), _fmt(prozent))]}
    rechenweg, fehlend, bereiche = [], [], []
    summe_gewicht = summe = 0.0
    for b in struktur["bereiche"]:
        teile = []
        bg = bz = 0.0
        punkte_erreicht = punkte_max = 0.0
        for k in b["kriterien"]:
            if k["typ"] not in ("punkte", "stufen", "check"):
                continue
            anteil, text = _kriterium_prozent(k, werte.get(k["key"]))
            if anteil is None:
                fehlend.append(k["name"])
                continue
            # Punkte zaehlen standardmaessig mit ihren Hoechstpunkten (Klassenarbeit: Summe/Summe), Stufen mit 1
            g = k.get("gewicht", k["max"] if k["typ"] in ("punkte", "check") else 1.0)
            bg += g
            bz += g * anteil
            if k["typ"] == "punkte":
                punkte_erreicht += float(werte[k["key"]])
                punkte_max += k["max"]
            elif k["typ"] == "check":
                punkte_erreicht += k["max"] * anteil
                punkte_max += k["max"]
            teile.append(text + (" ×" + _fmt(k["gewicht"]) if "gewicht" in k else ""))
        if bg == 0:
            bereiche.append({"name": b["name"], "gewicht": b["gewicht"], "prozent": None})
            continue
        bp = 100.0 * bz / bg
        gewicht = punkte_max if erfassung == "checkliste" else b["gewicht"]   # Checkliste: Summe der Punkte / Summe
        bereiche.append({"name": b["name"], "gewicht": gewicht, "prozent": bp})
        summe_gewicht += gewicht
        summe += gewicht * bp
        if erfassung == "aufgaben":
            rechenweg.append("%s von %s Punkten = %s %%" % (_fmt(punkte_erreicht), _fmt(punkte_max), _fmt(bp)))
        elif erfassung == "checkliste":
            rechenweg.append("%s: %s von %s Punkten" % (b["name"], _fmt(punkte_erreicht), _fmt(punkte_max)))
        else:
            rechenweg.append("%s (Gewicht %s): %s → %s %%" % (b["name"], _fmt(b["gewicht"]), "; ".join(teile), _fmt(bp)))
    stufen = [f for f in (fragen or []) if f is not None]
    if erfassung == "bogen" and fragen_gewicht and stufen:
        fp = 100.0 * sum(stufen) / (4.0 * len(stufen))
        bereiche.append({"name": "Fragen", "gewicht": fragen_gewicht, "prozent": fp})
        summe_gewicht += fragen_gewicht
        summe += fragen_gewicht * fp
        rechenweg.append("Fragen (Gewicht %s): %s → %s %%" % (_fmt(fragen_gewicht), ", ".join("%d/4" % x for x in stufen), _fmt(fp)))
    if summe_gewicht == 0:
        return {"prozent": None, "rechenweg": rechenweg, "fehlend": fehlend, "bereiche": bereiche}
    if erfassung == "checkliste" and not any(werte.get(k["key"]) for k in _kriterien(struktur)):
        return {"prozent": None, "rechenweg": [], "fehlend": [], "bereiche": bereiche}   # noch nichts abgehakt: keine Note
    prozent = summe / summe_gewicht
    gewertet = [b for b in bereiche if b["prozent"] is not None]
    if erfassung == "checkliste":
        rechenweg.append("Gesamt: %s von %s Punkten = %s %%" % (_fmt(summe / 100.0), _fmt(summe_gewicht), _fmt(prozent)))
    elif len(gewertet) > 1:
        rechenweg.append("Gesamt: (" + " + ".join("%s × %s" % (_fmt(b["gewicht"]), _fmt(b["prozent"])) for b in gewertet)
                         + ") / %s = %s %%" % (_fmt(summe_gewicht), _fmt(prozent)))
    return {"prozent": prozent, "rechenweg": rechenweg, "fehlend": fehlend, "bereiche": bereiche}


# --- Vorlagen (Feedbackbogen) ---

def vorlagen(con, lid):
    return [{"id": z["id"], "name": z["name"], "art": z["art"], "struktur": json.loads(z["struktur"]), "geaendert": z["geaendert"]}
            for z in con.execute("SELECT * FROM vorlage WHERE lehrkraft_id = ? ORDER BY name", (lid,))]


def vorlage_speichern(con, lid, daten, vid=None):
    name = _text(daten.get("name"), "einen Namen", 120)
    art = daten.get("art") if daten.get("art") in ARTEN else "muendlich"
    struktur = struktur_pruefen(daten.get("struktur"))
    jetzt = db.jetzt()
    if vid is None:
        return con.execute("INSERT INTO vorlage (lehrkraft_id, name, art, struktur, erstellt, geaendert) VALUES (?, ?, ?, ?, ?, ?)",
                           (lid, name, art, json.dumps(struktur, ensure_ascii=False), jetzt, jetzt)).lastrowid
    if con.execute("SELECT 1 FROM vorlage WHERE id = ? AND lehrkraft_id = ?", (vid, lid)).fetchone() is None:
        raise PruefungFehler("Diese Vorlage gibt es nicht.")
    con.execute("UPDATE vorlage SET name = ?, art = ?, struktur = ?, geaendert = ? WHERE id = ?",
                (name, art, json.dumps(struktur, ensure_ascii=False), jetzt, vid))
    return vid


def vorlage_loeschen(con, lid, vid):
    if con.execute("SELECT 1 FROM vorlage WHERE id = ? AND lehrkraft_id = ?", (vid, lid)).fetchone() is None:
        raise PruefungFehler("Diese Vorlage gibt es nicht.")
    con.execute("DELETE FROM vorlage WHERE id = ?", (vid,))   # Pruefungen behalten ihre Kopie


# --- Notenschluessel einer Pruefung ---

def standard_schluessel(con, lid):
    wert = db.einstellung(con, "standard_schluessel:%d" % lid)
    return int(wert) if wert else None


def standard_setzen(con, lid, sid):
    sid = _id(sid)
    if sid is not None:
        s = notenschluessel.holen(con, sid)
        if s is None or (s["art"] == "eigen" and s["besitzer_id"] != lid):
            raise PruefungFehler("Diesen Notenschlüssel gibt es nicht.")
    db.einstellung_setzen(con, "standard_schluessel:%d" % lid, str(sid) if sid else "")


def schluessel_fuer(con, lid, p):
    """(schluessel, herkunft) nach der Reihenfolge Pruefung -> Klasse -> Standard -> Konferenz; abgeschlossene
    Pruefungen nutzen den eingefrorenen Schluessel."""
    if p["schluessel_fest"]:
        return json.loads(p["schluessel_fest"]), "beim Abschließen festgehalten"
    if p["notenschluessel_id"]:
        s = notenschluessel.holen(con, p["notenschluessel_id"])
        if s:
            return s, "in der Prüfung gewählt"
    k = con.execute("SELECT notenschluessel_id, bildungsgang_id FROM klasse WHERE id = ?", (p["klasse_id"],)).fetchone()
    if k and k["notenschluessel_id"]:
        s = notenschluessel.holen(con, k["notenschluessel_id"])
        if s:
            return s, "Schlüssel der Klasse"
    std = standard_schluessel(con, lid)
    if std:
        s = notenschluessel.holen(con, std)
        if s:
            return s, "dein Standard"
    z = con.execute("SELECT id FROM notenschluessel WHERE art = 'konferenz' AND bildungsgang_id = ?",
                    (k["bildungsgang_id"] if k else None,)).fetchone()
    if z:
        return notenschluessel.holen(con, z["id"]), "Konferenzschlüssel des Bildungsgangs"
    return None, "kein Schlüssel – der Admin trägt den Konferenzschlüssel ein"


# --- Pruefungen ---

def _pruefung(con, lid, pid):
    z = con.execute("SELECT * FROM pruefung WHERE id = ? AND lehrkraft_id = ?", (pid, lid)).fetchone()
    if z is None:
        raise PruefungFehler("Diese Prüfung gibt es nicht.")
    return z


def _strang(con, lid, daten):
    """Klasse und Schuljahr; eine Pruefung gilt immer fuer die Klasse (getrennt schreiben = Termine je Gruppe)."""
    kid = _klasse(con, _id(daten.get("klasse_id")))
    gid = None
    sid = _id(daten.get("schuljahr_id"))
    if sid is None or con.execute("SELECT 1 FROM schuljahr WHERE id = ?", (sid,)).fetchone() is None:
        raise PruefungFehler("Bitte ein Schuljahr wählen.")
    return kid, gid, sid


def pruefung_speichern(con, lid, daten, pid=None):
    """Pruefung anlegen bzw. aendern. Fester Termin -> festgesetztes Thema in der Planung (belegt die Bloecke)."""
    if pid is None:
        kid, gid, sid = _strang(con, lid, daten)
        alt = None
    else:
        alt = _pruefung(con, lid, pid)
        kid, gid, sid = alt["klasse_id"], alt["gruppe_id"], alt["schuljahr_id"]
    titel = _text(daten.get("titel"), "einen Titel", 120)
    art = daten.get("art") if daten.get("art") in ARTEN else "schriftlich"
    form = daten.get("form") if daten.get("form") in ("termin", "fenster") else "termin"
    datum = beginn = von = bis = None
    bloecke = 1
    teilung = "zusammen"
    termine = []
    if form == "termin":
        bloecke = int(_zahl(daten.get("bloecke") or 1, "Blöcke", 1, 20))
        teilung = "getrennt" if daten.get("teilung") == "getrennt" else "zusammen"
        if teilung == "getrennt":
            termine = _termine_pruefen(con, lid, kid, daten.get("termine"))
            datum, beginn = termine[0]["datum"], termine[0]["beginn"]   # der erste Termin belegt die Planung
        else:
            datum = stundenplan._datum(daten.get("datum"), "den Tag der Prüfung").isoformat()
            beginn = stundenplan._uhrzeit(daten.get("beginn"), "den Block")
    else:
        von = stundenplan._datum(daten.get("fenster_von"), "den Beginn des Fensters").isoformat()
        bis = stundenplan._datum(daten.get("fenster_bis"), "die Frist").isoformat()
        if bis < von:
            raise PruefungFehler("Die Frist liegt vor dem Beginn des Fensters.")
    erfassung = daten.get("erfassung") if daten.get("erfassung") in ERFASSUNGEN else (alt["erfassung"] if alt else "aufgaben")
    max_punkte = None
    if erfassung == "gesamt":
        max_punkte = _zahl(daten.get("max_punkte"), "Höchstpunkte", 0.5, 10000)
        struktur = {"bereiche": []}
    elif erfassung == "aufgaben":
        aufgaben = daten.get("aufgaben")
        if aufgaben is None and alt is not None and alt["erfassung"] == "aufgaben":
            struktur = json.loads(alt["struktur"])
        else:
            if not isinstance(aufgaben, list) or not aufgaben:
                raise PruefungFehler("Bitte mindestens eine Aufgabe mit Höchstpunkten angeben.")
            struktur = struktur_pruefen({"bereiche": [{"name": "Aufgaben", "gewicht": 1, "kriterien": [
                {"key": a.get("key"), "name": a.get("name") or "Aufgabe %d" % (i + 1), "typ": "punkte", "max": a.get("max")}
                for i, a in enumerate(aufgaben) if isinstance(a, dict)]}]})
    elif erfassung == "checkliste":
        versuche = daten.get("versuche")
        if versuche is None and alt is not None and alt["erfassung"] == "checkliste":
            struktur = json.loads(alt["struktur"])
        else:
            if not isinstance(versuche, list) or not versuche:
                raise PruefungFehler("Bitte mindestens einen Versuch mit Haken anlegen.")
            struktur = {"bereiche": [{"name": v.get("name"), "gewicht": 1, "team": bool(v.get("team")), "kriterien": [
                {"key": h.get("key"), "name": h.get("name"), "typ": "check", "max": h.get("punkte")}
                for h in (v.get("haken") or []) if isinstance(h, dict)]} for v in versuche if isinstance(v, dict)]}
        if "testat" in daten:
            struktur["testat"] = bool(daten.get("testat"))
        struktur = struktur_pruefen(struktur)
    else:
        vid = _id(daten.get("vorlage_id"))
        if daten.get("struktur") is not None:
            struktur = struktur_pruefen(daten["struktur"])
        elif vid is not None:
            v = con.execute("SELECT struktur FROM vorlage WHERE id = ? AND lehrkraft_id = ?", (vid, lid)).fetchone()
            if v is None:
                raise PruefungFehler("Diese Vorlage gibt es nicht.")
            struktur = json.loads(v["struktur"])
        elif alt is not None and alt["erfassung"] == "bogen":
            struktur = json.loads(alt["struktur"])
        else:
            raise PruefungFehler("Bitte eine Feedbackbogen-Vorlage wählen.")
        team = daten.get("team_bereiche")
        if isinstance(team, list):                       # Bereiche, die fuers ganze Team gelten
            for i, b in enumerate(struktur["bereiche"]):
                b["team"] = i in team
    nsid = _id(daten.get("notenschluessel_id"))
    if nsid is not None:
        s = notenschluessel.holen(con, nsid)
        if s is None or (s["art"] == "eigen" and s["besitzer_id"] != lid):
            raise PruefungFehler("Diesen Notenschlüssel gibt es nicht.")
    lfid = _id(daten.get("lernfeld_id"))
    if lfid is not None and con.execute("SELECT 1 FROM lernfeld l JOIN klasse k ON k.bildungsgang_id = l.bildungsgang_id "
                                        "WHERE l.id = ? AND k.id = ?", (lfid, kid)).fetchone() is None:
        raise PruefungFehler("Das Lernfeld gehört nicht zum Bildungsgang der Klasse.")
    stand = daten.get("stand") if daten.get("stand") in STAENDE[:3] else (alt["stand"] if alt and alt["stand"] != "ausgewertet" else "geplant")
    werte = (titel, art, form, datum, beginn, bloecke, von, bis, erfassung, json.dumps(struktur, ensure_ascii=False), max_punkte,
             nsid, lfid, teilung, db.jetzt())
    if alt is None:
        pid = con.execute("INSERT INTO pruefung (titel, art, form, datum, beginn, bloecke, fenster_von, fenster_bis, erfassung, struktur, "
                          "max_punkte, notenschluessel_id, lernfeld_id, teilung, geaendert, lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, "
                          "stand, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          werte + (lid, kid, gid, sid, stand, db.jetzt())).lastrowid
    else:
        if alt["stand"] == "ausgewertet" and (erfassung != alt["erfassung"] or json.dumps(struktur, ensure_ascii=False) != alt["struktur"]):
            raise PruefungFehler("Die Prüfung ist abgeschlossen. Bitte zuerst wieder öffnen.")
        con.execute("UPDATE pruefung SET titel = ?, art = ?, form = ?, datum = ?, beginn = ?, bloecke = ?, fenster_von = ?, fenster_bis = ?, "
                    "erfassung = ?, struktur = ?, max_punkte = ?, notenschluessel_id = ?, lernfeld_id = ?, teilung = ?, geaendert = ?, stand = ? "
                    "WHERE id = ?", werte + (stand if alt["stand"] != "ausgewertet" else "ausgewertet", pid))
    con.execute("DELETE FROM pruefung_termin WHERE pruefung_id = ?", (pid,))
    for t in termine:
        con.execute("INSERT INTO pruefung_termin (pruefung_id, gruppe_id, datum, beginn) VALUES (?, ?, ?, ?)",
                    (pid, t["gruppe_id"], t["datum"], t["beginn"]))
    _planung_abgleichen(con, lid, pid)
    return pid


def _termine_pruefen(con, lid, kid, termine):
    """Termine je Gruppe beim getrennten Schreiben: [{gruppe_id, datum, beginn}], mindestens zwei Gruppen der Klasse,
    jede hoechstens einmal. Rueckgabe sortiert nach Datum und Beginn."""
    if not isinstance(termine, list) or len([t for t in termine if isinstance(t, dict)]) < 2:
        raise PruefungFehler("Getrennt schreiben braucht einen Termin je Gruppe (mindestens zwei).")
    ergebnis, gesehen = [], set()
    for t in termine:
        if not isinstance(t, dict):
            continue
        gid = _id(t.get("gruppe_id"))
        if gid is None:
            raise PruefungFehler("Bitte bei jedem Termin die Gruppe wählen.")
        stundenplan._gruppe_pruefen(con, lid, kid, gid)
        if gid in gesehen:
            raise PruefungFehler("Jede Gruppe hat nur einen Termin.")
        gesehen.add(gid)
        ergebnis.append({"gruppe_id": gid, "datum": stundenplan._datum(t.get("datum"), "den Tag der Prüfung").isoformat(),
                         "beginn": stundenplan._uhrzeit(t.get("beginn"), "den Block")})
    ergebnis.sort(key=lambda t: (t["datum"], t["beginn"]))
    return ergebnis


# --- Pruefungsmodus: Einstellungen, Fragenpool, Protokoll, Dauer ---

def einstellungen(p):
    """Einstellungen des Pruefungsmodus mit Vorgaben."""
    roh = json.loads(p["einstellungen"] or "{}") if isinstance(p["einstellungen"], str) else (p["einstellungen"] or {})
    return {k: roh.get(k, v[0]) for k, v in EINSTELLUNGEN.items()}


def einstellungen_setzen(con, lid, pid, daten):
    p = _pruefung(con, lid, pid)
    neu = einstellungen(p)
    for k, (_, lo, hi) in EINSTELLUNGEN.items():
        if k in daten and daten[k] not in (None, ""):
            wert = _zahl(daten[k], k, lo, hi)
            neu[k] = int(wert) if k != "fragen_gewicht" else wert
    con.execute("UPDATE pruefung SET einstellungen = ? WHERE id = ?", (json.dumps(neu), pid))


def fragen(con, pid):
    """Fragenpool mit Zahl der Ziehungen."""
    gezogen = {z[0]: z[1] for z in con.execute("SELECT frage_id, COUNT(*) FROM pruefung_protokoll WHERE pruefung_id = ? "
                                                 "AND frage_id IS NOT NULL GROUP BY frage_id", (pid,))}
    return [{"id": z["id"], "text": z["text"], "kategorie": z["kategorie"], "gezogen": gezogen.get(z["id"], 0)}
            for z in con.execute("SELECT * FROM pruefung_frage WHERE pruefung_id = ? ORDER BY reihenfolge, id", (pid,))]


def frage_speichern(con, lid, pid, daten, fid=None):
    _pruefung(con, lid, pid)
    text = _text(daten.get("text"), "die Frage", 1000)
    kategorie = _text(daten.get("kategorie"), "die Kategorie", 60, pflicht=False)
    if fid is None:
        n = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM pruefung_frage WHERE pruefung_id = ?", (pid,)).fetchone()[0]
        return con.execute("INSERT INTO pruefung_frage (pruefung_id, text, kategorie, reihenfolge) VALUES (?, ?, ?, ?)",
                           (pid, text, kategorie, n)).lastrowid
    if con.execute("SELECT 1 FROM pruefung_frage WHERE id = ? AND pruefung_id = ?", (fid, pid)).fetchone() is None:
        raise PruefungFehler("Diese Frage gibt es nicht.")
    con.execute("UPDATE pruefung_frage SET text = ?, kategorie = ? WHERE id = ?", (text, kategorie, fid))
    return fid


def fragen_einfuegen(con, lid, pid, text):
    """Mehrere Fragen auf einmal: eine je Zeile; "Kategorie: Frage" setzt die Kategorie. Rueckgabe: Anzahl."""
    n = 0
    for zeile in (text or "").splitlines():
        zeile = zeile.strip().lstrip("-•*").strip()
        if not zeile:
            continue
        kategorie = ""
        m = re.match(r"^([^:?]{1,40}):\s+(.+)$", zeile)
        if m:
            kategorie, zeile = m.group(1).strip(), m.group(2).strip()
        frage_speichern(con, lid, pid, {"text": zeile, "kategorie": kategorie})
        n += 1
    if not n:
        raise PruefungFehler("Bitte mindestens eine Frage eintragen (eine je Zeile).")
    return n


def frage_loeschen(con, lid, pid, fid):
    _pruefung(con, lid, pid)
    con.execute("DELETE FROM pruefung_frage WHERE id = ? AND pruefung_id = ?", (fid, pid))


def _schueler_der_pruefung(con, lid, p, sid):
    s = _schueler_zeile(con, lid, sid)
    if s["klasse_id"] != p["klasse_id"]:
        raise PruefungFehler("Der Schüler gehört nicht zur Klasse der Prüfung.")
    return s


def frage_ziehen(con, lid, pid, sid, zufall=None):
    """Zieht eine Frage fuer den Schueler: zuerst aus den in dieser Pruefung noch nie gezogenen; ist der Pool
    aufgebraucht, aus denen, die der Schueler selbst noch nicht hatte. Rueckgabe: id des Protokolleintrags."""
    p = _pruefung(con, lid, pid)
    _schueler_der_pruefung(con, lid, p, sid)
    pool = fragen(con, pid)
    if not pool:
        raise PruefungFehler("Der Fragenpool ist leer. Lege zuerst Fragen an (Reiter „Fragen“).")
    eigene = {z[0] for z in con.execute("SELECT frage_id FROM pruefung_protokoll WHERE pruefung_id = ? AND schueler_id = ? "
                                         "AND frage_id IS NOT NULL", (pid, sid))}
    kandidaten = [f for f in pool if not f["gezogen"]] or [f for f in pool if f["id"] not in eigene]
    if not kandidaten:
        raise PruefungFehler("Dieser Schüler hatte schon alle Fragen des Pools.")
    f = (zufall or random).choice(kandidaten)
    return con.execute("INSERT INTO pruefung_protokoll (pruefung_id, schueler_id, frage_id, text, zeit) VALUES (?, ?, ?, ?, ?)",
                       (pid, sid, f["id"], f["text"], db.jetzt())).lastrowid


def _stufe(wert):
    if wert in (None, ""):
        return None
    return int(_zahl(wert, "die Einschätzung", 0, len(FRAGE_STUFEN) - 1))


def protokoll_speichern(con, lid, pid, daten, eid=None):
    """Spontane Frage notieren (schueler_id, text, stufe) bzw. Eintrag aendern (stufe, text). Mit in_pool=True
    kommt eine spontane Frage zusaetzlich in den Fragenpool."""
    p = _pruefung(con, lid, pid)
    if p["stand"] == "ausgewertet":
        raise PruefungFehler("Die Prüfung ist abgeschlossen. Bitte zuerst wieder öffnen.")
    if eid is None:
        sid = _id(daten.get("schueler_id"))
        _schueler_der_pruefung(con, lid, p, sid)
        text = _text(daten.get("text"), "die Frage", 1000)
        eid = con.execute("INSERT INTO pruefung_protokoll (pruefung_id, schueler_id, text, stufe, zeit) VALUES (?, ?, ?, ?, ?)",
                          (pid, sid, text, _stufe(daten.get("stufe")), db.jetzt())).lastrowid
    else:
        alt = con.execute("SELECT * FROM pruefung_protokoll WHERE id = ? AND pruefung_id = ?", (eid, pid)).fetchone()
        if alt is None:
            raise PruefungFehler("Diesen Eintrag gibt es nicht.")
        text = _text(daten.get("text"), "die Frage", 1000) if "text" in daten else alt["text"]
        stufe = _stufe(daten.get("stufe")) if "stufe" in daten else alt["stufe"]
        con.execute("UPDATE pruefung_protokoll SET text = ?, stufe = ? WHERE id = ?", (text, stufe, eid))
    if daten.get("in_pool"):
        z = con.execute("SELECT * FROM pruefung_protokoll WHERE id = ?", (eid,)).fetchone()
        if z["frage_id"] is None:
            fid = frage_speichern(con, lid, pid, {"text": z["text"]})
            con.execute("UPDATE pruefung_protokoll SET frage_id = ? WHERE id = ?", (fid, eid))
    if p["stand"] in ("geplant", "angekuendigt"):
        con.execute("UPDATE pruefung SET stand = 'durchgefuehrt' WHERE id = ?", (pid,))
    return eid


def protokoll_loeschen(con, lid, pid, eid):
    _pruefung(con, lid, pid)
    con.execute("DELETE FROM pruefung_protokoll WHERE id = ? AND pruefung_id = ?", (eid, pid))


def lauf_setzen(con, lid, pid, sid, aktion):
    """Dauer protokollieren: 'start' setzt den Beginn (jetzt), 'ende' das Ende, 'zuruecksetzen' beides leer."""
    p = _pruefung(con, lid, pid)
    _schueler_der_pruefung(con, lid, p, sid)
    if aktion not in ("start", "ende", "zuruecksetzen"):
        raise PruefungFehler("Unbekannte Aktion.")
    jetzt = db.jetzt()
    con.execute("INSERT INTO bewertung (pruefung_id, schueler_id, werte, fehlt, notiz, geaendert) VALUES (?, ?, '{}', 0, '', ?) "
                "ON CONFLICT (pruefung_id, schueler_id) DO NOTHING", (pid, sid, jetzt))
    if aktion == "start":
        con.execute("UPDATE bewertung SET beginn = ?, ende = NULL WHERE pruefung_id = ? AND schueler_id = ?", (jetzt, pid, sid))
    elif aktion == "ende":
        con.execute("UPDATE bewertung SET ende = ?, beginn = COALESCE(beginn, ?) WHERE pruefung_id = ? AND schueler_id = ?",
                    (jetzt, jetzt, pid, sid))
    else:
        con.execute("UPDATE bewertung SET beginn = NULL, ende = NULL WHERE pruefung_id = ? AND schueler_id = ?", (pid, sid))
    if p["stand"] in ("geplant", "angekuendigt") and aktion != "zuruecksetzen":
        con.execute("UPDATE pruefung SET stand = 'durchgefuehrt' WHERE id = ?", (pid,))


def _dauer(beginn, ende):
    if not beginn or not ende:
        return None
    try:
        a = datetime.datetime.fromisoformat(beginn)
        b = datetime.datetime.fromisoformat(ende)
    except ValueError:
        return None
    return max(0, int((b - a).total_seconds()))


# --- Teams einer Pruefung ---

def _team_keys(struktur):
    """Schluessel der Kriterien in Team-Bereichen."""
    return {k["key"] for b in struktur["bereiche"] if b.get("team") for k in b["kriterien"]}


def teams(con, pid):
    """[{id, name, mitglieder: [schueler_id], werte}] in Reihenfolge."""
    mitglieder = {}
    for z in con.execute("SELECT team_id, schueler_id FROM pruefung_team_mitglied WHERE pruefung_id = ?", (pid,)):
        mitglieder.setdefault(z["team_id"], []).append(z["schueler_id"])
    return [{"id": z["id"], "name": z["name"], "mitglieder": mitglieder.get(z["id"], []), "werte": json.loads(z["werte"])}
            for z in con.execute("SELECT * FROM pruefung_team WHERE pruefung_id = ? ORDER BY reihenfolge, id", (pid,))]


def _team(con, pid, tid):
    z = con.execute("SELECT * FROM pruefung_team WHERE id = ? AND pruefung_id = ?", (tid, pid)).fetchone()
    if z is None:
        raise PruefungFehler("Dieses Team gibt es nicht.")
    return z


def _mitglieder_setzen(con, lid, p, tid, ids):
    if not isinstance(ids, list):
        raise PruefungFehler("Ungültige Mitglieder.")
    erlaubt = {s["id"] for s in schueler(con, lid, p["klasse_id"])}
    ids = [i for i in (_id(x) for x in ids) if i is not None]
    if any(i not in erlaubt for i in ids):
        raise PruefungFehler("Ein Schüler gehört nicht zur Klasse der Prüfung.")
    con.execute("DELETE FROM pruefung_team_mitglied WHERE team_id = ?", (tid,))
    for i in ids:   # wer schon in einem anderen Team ist, wechselt hierher
        con.execute("DELETE FROM pruefung_team_mitglied WHERE pruefung_id = ? AND schueler_id = ?", (p["id"], i))
        con.execute("INSERT INTO pruefung_team_mitglied (pruefung_id, team_id, schueler_id) VALUES (?, ?, ?)", (p["id"], tid, i))


def team_speichern(con, lid, pid, daten, tid=None):
    """Team anlegen bzw. aendern: name, schueler_ids (Schueler wechseln aus anderen Teams hierher)."""
    p = _pruefung(con, lid, pid)
    if p["stand"] == "ausgewertet":
        raise PruefungFehler("Die Prüfung ist abgeschlossen. Bitte zuerst wieder öffnen.")
    if tid is None:
        n = con.execute("SELECT COUNT(*) FROM pruefung_team WHERE pruefung_id = ?", (pid,)).fetchone()[0]
        name = _text(daten.get("name"), "einen Namen", 60, pflicht=False) or "Team %d" % (n + 1)
        tid = con.execute("INSERT INTO pruefung_team (pruefung_id, name, reihenfolge, geaendert) VALUES (?, ?, ?, ?)",
                          (pid, name, n + 1, db.jetzt())).lastrowid
    else:
        _team(con, pid, tid)
        if "name" in daten:
            con.execute("UPDATE pruefung_team SET name = ? WHERE id = ?", (_text(daten.get("name"), "einen Namen", 60), tid))
    if "schueler_ids" in daten:
        _mitglieder_setzen(con, lid, p, tid, daten.get("schueler_ids"))
    return tid


def team_loeschen(con, lid, pid, tid):
    _pruefung(con, lid, pid)
    _team(con, pid, tid)
    con.execute("DELETE FROM pruefung_team WHERE id = ?", (tid,))


def teams_bilden(con, lid, pid, groesse, zufall=None):
    """Alle Teams neu bilden: aktive Schueler zufaellig in Teams der Groesse 2-6; ein Rest von einem kommt ins letzte
    Team. Vorhandene Teams (samt ihren Teamwerten) werden ersetzt."""
    p = _pruefung(con, lid, pid)
    if p["stand"] == "ausgewertet":
        raise PruefungFehler("Die Prüfung ist abgeschlossen. Bitte zuerst wieder öffnen.")
    groesse = int(_zahl(groesse, "die Teamgröße", 2, 6))
    ids = [s["id"] for s in schueler(con, lid, p["klasse_id"], nur_aktive=True)]
    (zufall or random).shuffle(ids)
    gruppen_ = [ids[i:i + groesse] for i in range(0, len(ids), groesse)]
    if len(gruppen_) > 1 and len(gruppen_[-1]) == 1:
        gruppen_[-2].extend(gruppen_.pop())
    con.execute("DELETE FROM pruefung_team WHERE pruefung_id = ?", (pid,))
    for n, g in enumerate(gruppen_):
        tid = con.execute("INSERT INTO pruefung_team (pruefung_id, name, reihenfolge, geaendert) VALUES (?, ?, ?, ?)",
                          (pid, "Team %d" % (n + 1), n + 1, db.jetzt())).lastrowid
        for i in g:
            con.execute("INSERT INTO pruefung_team_mitglied (pruefung_id, team_id, schueler_id) VALUES (?, ?, ?)", (pid, tid, i))
    return len(gruppen_)


def termine(con, p):
    """Termine einer Pruefung: zusammen = einer fuer die Klasse, getrennt = je Gruppe. [{gruppe_id, gruppe, datum, beginn}]"""
    if p["form"] != "termin":
        return []
    if p["teilung"] != "getrennt":
        return [{"gruppe_id": None, "gruppe": "", "datum": p["datum"], "beginn": p["beginn"]}]
    return [dict(z) for z in con.execute("SELECT t.gruppe_id, g.name AS gruppe, t.datum, t.beginn FROM pruefung_termin t "
                                          "JOIN gruppe g ON g.id = t.gruppe_id WHERE t.pruefung_id = ? ORDER BY t.datum, t.beginn",
                                          (p["id"],))]


def termin_hinweise(con, lid, kid, liste):
    """Hinweise zu Terminen ohne passenden Unterricht: kein Unterricht der Klasse zu dieser Zeit, andere Gruppe als
    gewaehlt, bzw. nur eine Gruppe, obwohl die Klasse zusammen schreibt; getrennte Termine an verschiedenen Tagen."""
    from . import planung
    hinweise_ = []
    for t in liste:
        if not t.get("datum") or not t.get("beginn"):
            continue
        bl = planung.unterricht_am(con, lid, kid, t["datum"])
        treffer = next((b for b in bl if b["beginn"] == t["beginn"]), None)
        wer = t["gruppe"] + ": " if t.get("gruppe") else ""
        tag = stundenplan._tag_text(datetime.date.fromisoformat(t["datum"]))
        if treffer is None:
            hinweise_.append(wer + "Am %s um %s hast du keinen Unterricht in dieser Klasse." % (tag, t["beginn"]))
        elif t.get("gruppe_id") and treffer["gruppe_id"] and treffer["gruppe_id"] != t["gruppe_id"]:
            hinweise_.append(wer + "Am %s um %s hast du laut Stundenplan %s." % (tag, t["beginn"], treffer["gruppe"]))
        elif not t.get("gruppe_id") and treffer["gruppe_id"]:
            hinweise_.append("Am %s um %s hast du nur %s – schreibt die Klasse wirklich zusammen?" % (tag, t["beginn"], treffer["gruppe"]))
    if len({t.get("datum") for t in liste}) > 1:
        hinweise_.append("Die Gruppen schreiben an verschiedenen Tagen; in der Planung belegt die Prüfung den Tag des ersten Termins.")
    return hinweise_


def _planung_abgleichen(con, lid, pid):
    """Fester Termin: ein festgesetztes Thema mit den Bloecken der Pruefung in der Planung; Fenster: keins."""
    p = _pruefung(con, lid, pid)
    vorhanden = con.execute("SELECT id FROM plan_thema WHERE pruefung_id = ?", (pid,)).fetchone()
    if p["form"] != "termin":
        con.execute("DELETE FROM plan_thema WHERE pruefung_id = ?", (pid,))
        return
    if vorhanden:
        con.execute("UPDATE plan_thema SET titel = ?, bloecke = ?, lernfeld_id = ?, fest_datum = ?, fest_beginn = ?, klasse_id = ?, "
                    "gruppe_id = ?, schuljahr_id = ? WHERE id = ?",
                    (p["titel"], p["bloecke"], p["lernfeld_id"], p["datum"], p["beginn"], p["klasse_id"], p["gruppe_id"],
                     p["schuljahr_id"], vorhanden["id"]))
        return
    reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? "
                        "AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ?", (lid, p["klasse_id"], p["gruppe_id"] or 0, p["schuljahr_id"])).fetchone()[0]
    con.execute("INSERT INTO plan_thema (lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, reihenfolge, titel, bloecke, lernfeld_id, "
                "fest_datum, fest_beginn, pruefung_id, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (lid, p["klasse_id"], p["gruppe_id"], p["schuljahr_id"], reihe, p["titel"], p["bloecke"], p["lernfeld_id"],
                 p["datum"], p["beginn"], pid, db.jetzt()))


def pruefung_loeschen(con, lid, pid):
    _pruefung(con, lid, pid)
    con.execute("DELETE FROM pruefung WHERE id = ?", (pid,))   # Bewertungen und Planungs-Thema gehen mit


def _aus_zeile(z, con=None, lid=None):
    p = dict(z)
    p["struktur"] = json.loads(p["struktur"])
    p["artname"] = ARTEN.get(p["art"], p["art"])
    if con is not None:
        p["termine"] = termine(con, p)
        p["hinweise"] = termin_hinweise(con, lid, p["klasse_id"], p["termine"]) if p["stand"] in ("geplant", "angekuendigt") else []
    return p


def pruefungen(con, lid, kid, gid, sid):
    """Pruefungen eines Strangs mit kurzer Statistik (bewertet/Schnitt), nach Termin sortiert."""
    liste = []
    for z in con.execute("SELECT * FROM pruefung WHERE lehrkraft_id = ? AND klasse_id = ? AND schuljahr_id = ?",
                         (lid, kid, sid)).fetchall():
        e = ergebnis(con, lid, z["id"])
        p = e["pruefung"]
        p["statistik"] = e["statistik"]
        p["schluessel"] = e["schluessel"]["name"] if e["schluessel"] else None
        liste.append(p)
    liste.sort(key=lambda p: (p["datum"] or p["fenster_bis"] or "", p["titel"]))
    return liste


def _werte_pruefen(p, werte):
    """Neue Werte einer Bewertung gegen die Struktur pruefen; None/'' loescht einen Wert."""
    if not isinstance(werte, dict):
        raise PruefungFehler("Ungültige Werte.")
    sauber = {}
    if p["erfassung"] == "gesamt":
        for key, wert in werte.items():
            if key != "gesamt":
                raise PruefungFehler("Unbekanntes Feld.")
            sauber[key] = None if wert in (None, "") else _zahl(wert, "Punkte", 0, p["max_punkte"])
        return sauber
    kriterien = {k["key"]: k for k in _kriterien(p["struktur"])}
    for key, wert in werte.items():
        k = kriterien.get(key)
        if k is None:
            raise PruefungFehler("Unbekanntes Kriterium.")
        if wert in (None, ""):
            sauber[key] = None
        elif k["typ"] == "punkte":
            sauber[key] = _zahl(wert, k["name"], 0, k["max"])
        elif k["typ"] == "stufen":
            i = int(_zahl(wert, k["name"], 0, len(k["stufen"]) - 1))
            sauber[key] = i
        elif k["typ"] in ("haken", "check"):
            sauber[key] = bool(wert)
        else:
            sauber[key] = _text(wert, k["name"], 2000, pflicht=False)
    return sauber


def bewertung_setzen(con, lid, pid, sid, daten):
    """Werte (einzeln oder mehrere) einer Bewertung setzen; fehlt/notiz optional. Rueckgabe: Zeile wie in ergebnis()."""
    p = _aus_zeile(_pruefung(con, lid, pid))
    if p["stand"] == "ausgewertet":
        raise PruefungFehler("Die Prüfung ist abgeschlossen. Bitte zuerst wieder öffnen.")
    s = _schueler_zeile(con, lid, sid)
    if s["klasse_id"] != p["klasse_id"]:
        raise PruefungFehler("Der Schüler gehört nicht zur Klasse der Prüfung.")
    alt = con.execute("SELECT * FROM bewertung WHERE pruefung_id = ? AND schueler_id = ?", (pid, sid)).fetchone()
    werte = json.loads(alt["werte"]) if alt else {}
    team = con.execute("SELECT t.* FROM pruefung_team_mitglied m JOIN pruefung_team t ON t.id = m.team_id "
                       "WHERE m.pruefung_id = ? AND m.schueler_id = ?", (pid, sid)).fetchone()
    team_keys = _team_keys(p["struktur"]) if team else set()
    team_werte = json.loads(team["werte"]) if team else {}
    for key, wert in _werte_pruefen(p, daten.get("werte") or {}).items():
        ziel = team_werte if key in team_keys else werte      # Team-Kriterium: gilt fuer alle Mitglieder
        if wert is None:
            ziel.pop(key, None)
        else:
            ziel[key] = wert
    if team:
        con.execute("UPDATE pruefung_team SET werte = ?, geaendert = ? WHERE id = ?",
                    (json.dumps(team_werte, ensure_ascii=False), db.jetzt(), team["id"]))
    fehlt = (1 if daten["fehlt"] else 0) if "fehlt" in daten else (alt["fehlt"] if alt else 0)
    notiz = _text(daten["notiz"], "die Notiz", 4000, pflicht=False) if "notiz" in daten else (alt["notiz"] if alt else "")
    con.execute("INSERT INTO bewertung (pruefung_id, schueler_id, werte, fehlt, notiz, geaendert) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (pruefung_id, schueler_id) DO UPDATE SET werte = excluded.werte, fehlt = excluded.fehlt, "
                "notiz = excluded.notiz, geaendert = excluded.geaendert",
                (pid, sid, json.dumps(werte, ensure_ascii=False), fehlt, notiz, db.jetzt()))
    if p["stand"] in ("geplant", "angekuendigt") and (werte or team_werte):
        con.execute("UPDATE pruefung SET stand = 'durchgefuehrt' WHERE id = ?", (pid,))


def _ganze_note(system, n):
    """Stufe der ganzen Note fuer den Notenspiegel."""
    if system == "punkte":
        return n["stufe"]
    return n["stufe"][0]


def ergebnis(con, lid, pid):
    """Alles zur Bewertung einer Pruefung: Pruefung, Schluessel, Schueler mit Werten, Prozent, Note, Rechenweg, Statistik."""
    p = _aus_zeile(_pruefung(con, lid, pid), con, lid)
    schluessel, herkunft = schluessel_fuer(con, lid, p)
    bew = {z["schueler_id"]: z for z in con.execute("SELECT * FROM bewertung WHERE pruefung_id = ?", (pid,))}
    p["teams"] = teams(con, pid)
    p["einstellungen"] = einstellungen(p)
    p["fragen"] = fragen(con, pid)
    p["fragen_stufen"] = FRAGE_STUFEN
    protokoll = {}
    for z in con.execute("SELECT * FROM pruefung_protokoll WHERE pruefung_id = ? ORDER BY zeit, id", (pid,)):
        protokoll.setdefault(z["schueler_id"], []).append({"id": z["id"], "frage_id": z["frage_id"], "text": z["text"], "stufe": z["stufe"],
                                                            "zeit": z["zeit"], "spontan": z["frage_id"] is None})
    team_von = {sid: t for t in p["teams"] for sid in t["mitglieder"]}
    team_keys = _team_keys(p["struktur"]) if p["erfassung"] in ("bogen", "checkliste") else set()
    testat = bool(p["struktur"].get("testat"))
    if testat:
        schluessel, herkunft = None, "Nur Testat: ohne Note"
    zeilen = []
    for s in schueler(con, lid, p["klasse_id"]):
        b = bew.get(s["id"])
        team = team_von.get(s["id"])
        if not s["aktiv"] and not b and not team:
            continue
        werte = json.loads(b["werte"]) if b else {}
        if team:
            werte = {k: v for k, v in werte.items() if k not in team_keys}
            werte.update({k: v for k, v in team["werte"].items() if k in team_keys})
        fehlt = bool(b["fehlt"]) if b else False
        eintraege = protokoll.get(s["id"], [])
        r = berechnen(p["erfassung"], p["struktur"], p["max_punkte"], werte, [e["stufe"] for e in eintraege],
                      p["einstellungen"]["fragen_gewicht"]) if not fehlt else \
            {"prozent": None, "rechenweg": [], "fehlend": [], "bereiche": []}
        note = None
        if r["prozent"] is not None and schluessel:
            note = notenschluessel.note(schluessel["system"], schluessel["grenzen"], r["prozent"])
            r["rechenweg"].append("%s (%s): %s %% → %s" % (schluessel["name"], notenschluessel.SYSTEMNAME[schluessel["system"]],
                                                       _fmt(round(r["prozent"]), 0), note["text"]))
        versuche = []
        if p["erfassung"] == "checkliste":
            for bereich in p["struktur"]["bereiche"]:
                ks = [k for k in bereich["kriterien"] if k["typ"] == "check"]
                versuche.append({"erledigt": sum(1 for k in ks if werte.get(k["key"])), "gesamt": len(ks)})
        zeilen.append({"id": s["id"], "name": s["name"], "gruppe": s["gruppe"], "aktiv": s["aktiv"], "werte": werte, "fehlt": fehlt,
                       "team_id": team["id"] if team else None, "team": team["name"] if team else "", "versuche": versuche,
                       "protokoll": eintraege, "beginn": b["beginn"] if b else None, "ende": b["ende"] if b else None,
                       "dauer": _dauer(b["beginn"], b["ende"]) if b else None,
                       "notiz": b["notiz"] if b else "", "prozent": r["prozent"], "note": note, "rechenweg": r["rechenweg"],
                       "fehlend": r["fehlend"], "bereiche": r["bereiche"]})
    # Statistik
    noten = [z for z in zeilen if z["note"]]
    spiegel = {}
    if schluessel:
        reihe = notenschluessel.STUFEN[schluessel["system"]]
        stufen = reihe if schluessel["system"] == "punkte" else sorted({st[0] for st in reihe})
        spiegel = {st: 0 for st in stufen}
        for z in noten:
            spiegel[_ganze_note(schluessel["system"], z["note"])] += 1
    aufgaben = []
    for k in _kriterien(p["struktur"]):
        if k["typ"] not in ("punkte", "stufen"):
            continue
        anteile = [a for a in (_kriterium_prozent(k, z["werte"].get(k["key"]))[0] for z in zeilen if not z["fehlt"]) if a is not None]
        aufgaben.append({"key": k["key"], "name": k["name"], "max": k.get("max"), "anzahl": len(anteile),
                         "prozent": 100.0 * sum(anteile) / len(anteile) if anteile else None})
    if p["erfassung"] == "checkliste":
        aktiv = [z for z in zeilen if z["aktiv"] and not z["fehlt"]]
        fortschritt = [sum(1 for z in aktiv if z["versuche"][i]["erledigt"] == z["versuche"][i]["gesamt"]) for i in range(len(p["struktur"]["bereiche"]))]
    else:
        fortschritt = []
    statistik = {"schueler": len([z for z in zeilen if z["aktiv"]]), "bewertet": len(noten), "fortschritt": fortschritt,
                 "fehlt": len([z for z in zeilen if z["fehlt"]]),
                 "offen": len([z for z in zeilen if z["aktiv"] and not z["fehlt"] and z["prozent"] is None]),
                 "unvollstaendig": len([z for z in zeilen if z["prozent"] is not None and z["fehlend"]]),
                 "schnitt": round(sum(z["note"]["dezimal"] for z in noten) / len(noten), 2) if noten else None,
                 "prozent": round(sum(z["prozent"] for z in noten) / len(noten), 1) if noten else None,
                 "spiegel": spiegel, "aufgaben": aufgaben}
    return {"pruefung": p, "schluessel": schluessel, "herkunft": herkunft, "schueler": zeilen, "statistik": statistik}


def abschliessen(con, lid, pid):
    """Pruefung abschliessen: Schluessel einfrieren, Stand 'ausgewertet'. Rueckgabe: Warnungen (offene/unvollstaendige)."""
    e = ergebnis(con, lid, pid)
    if e["schluessel"] is None and not e["pruefung"]["struktur"].get("testat"):
        raise PruefungFehler("Ohne Notenschlüssel lässt sich nicht abschließen. Der Admin trägt den Konferenzschlüssel ein.")
    con.execute("UPDATE pruefung SET stand = 'ausgewertet', schluessel_fest = ?, geaendert = ? WHERE id = ?",
                (json.dumps(e["schluessel"], ensure_ascii=False), db.jetzt(), pid))
    st = e["statistik"]
    warnungen = []
    if st["offen"]:
        warnungen.append("%d ohne Bewertung" % st["offen"])
    if st["unvollstaendig"]:
        warnungen.append("%d mit unbewerteten Kriterien (nicht mitgerechnet)" % st["unvollstaendig"])
    return warnungen


def wieder_oeffnen(con, lid, pid):
    _pruefung(con, lid, pid)
    con.execute("UPDATE pruefung SET stand = 'durchgefuehrt', schluessel_fest = NULL, geaendert = ? WHERE id = ?", (db.jetzt(), pid))


def hinweise(con, lid, heute=None, tage=21):
    """Fuer die Startseite: anstehende Pruefungen (naechste drei Wochen), laufende Fenster, nicht abgeschlossene."""
    heute = (heute or db.heute()).isoformat()
    bis = (datetime.date.fromisoformat(heute) + datetime.timedelta(days=tage)).isoformat()
    namen = {k["id"]: k["name"] for k in grunddaten.klassen(con)}
    ergebnis_ = []
    for z in con.execute("SELECT * FROM pruefung WHERE lehrkraft_id = ? AND stand != 'ausgewertet' ORDER BY COALESCE(datum, fenster_bis)", (lid,)):
        if z["form"] == "termin":
            if heute <= z["datum"] <= bis:
                art = "bald"
            elif z["datum"] < heute:
                art = "offen"
            else:
                continue
            wann = z["datum"]
        else:
            if z["fenster_von"] <= heute <= z["fenster_bis"]:
                art = "fenster"
            elif z["fenster_bis"] < heute:
                art = "offen"
            elif z["fenster_von"] <= bis:
                art = "bald"
            else:
                continue
            wann = z["fenster_bis"]
        ergebnis_.append({"id": z["id"], "titel": z["titel"], "klasse": namen.get(z["klasse_id"], "?"), "art": art, "wann": wann,
                          "form": z["form"]})
    return ergebnis_
