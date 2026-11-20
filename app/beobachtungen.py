"""Beobachtungen je Schueler (0.26.0).

Ein Verlauf mit einzelnen Eintraegen je Schueler: Datum, optional eine Kategorie (Leistung, Arbeitsverhalten,
Sozialverhalten, Sonstiges) und eine Tendenz (positiv, neutral, negativ), dazu der Text. Aus einer Stunde heraus
notiert, merkt sich der Eintrag die Stunde (Datum, Beginn und eine Beschriftung zum Anzeigen); dort kann eine
Beobachtung auch gleich fuer mehrere Schueler gelten (je Schueler ein Eintrag).

Beobachtungen sind IMMER privat je Lehrkraft: sie gehoeren zur Lehrkraft, die sie notiert hat, und werden nie
geteilt, auch nicht mit dem Kollegium der Klasse. Die Schueler selbst kommen aus der gemeinsamen Liste
(app/schuelerliste.py): notieren darf man nur zu Schuelern einer Klasse, deren Liste man nutzen darf.

Geloescht wird nur von Hand. Die Startseite bietet Beobachtungen zu Schuelern, die nicht mehr in der Klasse sind und
aelter als ein Jahr sind, zum Loeschen an (aufraeumen_stand / aufraeumen).

PDF je Schueler (mit Foto) und je Klasse im DRS-Design, vermerkt als persoenliche Aufzeichnung.
"""
import datetime

from . import db, exporte, fotos, pdf, schuelerliste
from .pdf import A4, MM, Seite, kuerzen, umbrechen

KATEGORIEN = ("Leistung", "Arbeitsverhalten", "Sozialverhalten", "Sonstiges")
TENDENZEN = {"positiv": "+ positiv", "neutral": "○ neutral", "negativ": "− negativ"}
PDF_TENDENZ = {"positiv": "+ positiv", "neutral": "o neutral", "negativ": "- negativ"}   # nur Zeichen der PDF-Grundschrift
AUFRAEUMEN_TAGE = 365


class BeobachtungFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _datum(wert, feld="das Datum"):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10]).isoformat()
    except ValueError:
        raise BeobachtungFehler("Bitte %s angeben." % feld)


def _zeile(z):
    return {"id": z["id"], "schueler_id": z["schueler_id"], "datum": z["datum"], "kategorie": z["kategorie"], "tendenz": z["tendenz"],
            "text": z["text"], "stunde_datum": z["stunde_datum"], "stunde_beginn": z["stunde_beginn"], "stunde_text": z["stunde_text"],
            "geaendert": z["geaendert"]}


def _schueler(con, lid, sid):
    try:
        return schuelerliste.zeile(con, lid, sid)
    except schuelerliste.SchuelerFehler as f:
        raise BeobachtungFehler(str(f))


def _eigene(con, lid, bid):
    z = con.execute("SELECT * FROM beobachtung WHERE id = ? AND lehrkraft_id = ?", (bid, lid)).fetchone()
    if z is None:
        raise BeobachtungFehler("Diese Beobachtung gibt es nicht.")
    return z


def _felder(daten):
    text = daten.get("text").strip() if isinstance(daten.get("text"), str) else ""
    if not text:
        raise BeobachtungFehler("Bitte die Beobachtung eintragen.")
    if len(text) > 4000:
        raise BeobachtungFehler("Die Beobachtung darf höchstens 4000 Zeichen haben.")
    kategorie = daten.get("kategorie") or ""
    if kategorie and kategorie not in KATEGORIEN:
        raise BeobachtungFehler("Unbekannte Kategorie.")
    tendenz = daten.get("tendenz") or "neutral"
    if tendenz not in TENDENZEN:
        raise BeobachtungFehler("Unbekannte Tendenz.")
    return {"datum": _datum(daten.get("datum")), "kategorie": kategorie, "tendenz": tendenz, "text": text}


# --- Anlegen, aendern, loeschen ---

def anlegen(con, lid, daten):
    """Beobachtung fuer einen oder mehrere Schueler (schueler_ids, alle aus derselben Klasse). Aus einer Stunde:
    stunde_datum, stunde_beginn, stunde_text. Rueckgabe: Liste der neuen Ids."""
    ids = daten.get("schueler_ids")
    if ids is None and daten.get("schueler_id") is not None:
        ids = [daten.get("schueler_id")]
    try:
        ids = list(dict.fromkeys(int(i) for i in (ids or [])))
    except (TypeError, ValueError):
        raise BeobachtungFehler("Ungültige Auswahl.")
    if not ids:
        raise BeobachtungFehler("Bitte mindestens einen Schüler wählen.")
    klassen = {_schueler(con, lid, sid)["klasse_id"] for sid in ids}
    if len(klassen) > 1:
        raise BeobachtungFehler("Eine Beobachtung gilt nur für Schüler derselben Klasse.")
    f = _felder(daten)
    stunde_datum = _datum(daten.get("stunde_datum"), "das Datum der Stunde") if daten.get("stunde_datum") else None
    stunde_beginn = str(daten.get("stunde_beginn") or "")[:5] or None if stunde_datum else None
    stunde_text = str(daten.get("stunde_text") or "")[:200] if stunde_datum else ""
    jetzt = db.jetzt()
    return [con.execute("INSERT INTO beobachtung (lehrkraft_id, schueler_id, datum, kategorie, tendenz, text, stunde_datum, stunde_beginn, "
                        "stunde_text, erstellt, geaendert) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (lid, sid, f["datum"], f["kategorie"], f["tendenz"], f["text"], stunde_datum, stunde_beginn, stunde_text,
                         jetzt, jetzt)).lastrowid for sid in ids]


def aendern(con, lid, bid, daten):
    _eigene(con, lid, bid)
    f = _felder(daten)
    con.execute("UPDATE beobachtung SET datum = ?, kategorie = ?, tendenz = ?, text = ?, geaendert = ? WHERE id = ?",
                (f["datum"], f["kategorie"], f["tendenz"], f["text"], db.jetzt(), bid))
    return bid


def loeschen(con, lid, bid):
    _eigene(con, lid, bid)
    con.execute("DELETE FROM beobachtung WHERE id = ?", (bid,))


# --- Lesen ---

def verlauf(con, lid, sid):
    """Eigene Beobachtungen zu einem Schueler, neueste zuerst, und der Schueler selbst."""
    s = _schueler(con, lid, sid)
    zeilen = con.execute("SELECT * FROM beobachtung WHERE lehrkraft_id = ? AND schueler_id = ? ORDER BY datum DESC, id DESC", (lid, sid))
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (s["klasse_id"],)).fetchone()["name"]
    return {"schueler": {"id": s["id"], "nachname": s["nachname"], "vorname": s["vorname"], "email": s["email"], "aktiv": bool(s["aktiv"]),
                         "name": s["nachname"] + (", " + s["vorname"] if s["vorname"] else ""), "klasse_id": s["klasse_id"], "klasse": klasse,
                         "foto": s["foto_geaendert"] if s["foto"] is not None else None, "entlassen_zum": s["entlassen_zum"]},
            "eintraege": [_zeile(z) for z in zeilen]}


def zusammenfassung(con, lid, kid):
    """Je Schueler der Klasse: Anzahl eigener Beobachtungen, Tendenzen, letzte. {schueler_id: {...}}"""
    erg = {}
    for z in con.execute("SELECT b.schueler_id, b.tendenz, MAX(b.datum) AS zuletzt, COUNT(*) AS n FROM beobachtung b "
                         "JOIN schueler s ON s.id = b.schueler_id WHERE b.lehrkraft_id = ? AND s.klasse_id = ? "
                         "GROUP BY b.schueler_id, b.tendenz", (lid, kid)):
        e = erg.setdefault(z["schueler_id"], {"anzahl": 0, "positiv": 0, "neutral": 0, "negativ": 0, "zuletzt": ""})
        e["anzahl"] += z["n"]
        e[z["tendenz"]] += z["n"]
        e["zuletzt"] = max(e["zuletzt"], z["zuletzt"])
    return erg


def klasse(con, lid, kid, kategorie=None, tendenz=None, von=None, bis=None, suche=None):
    """Klassenuebersicht: alle eigenen Beobachtungen der Klasse (gefiltert), dazu die Schueler mit Zaehlern."""
    try:
        schueler = schuelerliste.liste(con, lid, kid)
    except schuelerliste.SchuelerFehler as f:
        raise BeobachtungFehler(str(f))
    sql = ("SELECT b.* FROM beobachtung b JOIN schueler s ON s.id = b.schueler_id WHERE b.lehrkraft_id = ? AND s.klasse_id = ?")
    werte = [lid, kid]
    if kategorie:
        sql += " AND b.kategorie = ?"
        werte.append(kategorie)
    if tendenz:
        sql += " AND b.tendenz = ?"
        werte.append(tendenz)
    if von:
        sql += " AND b.datum >= ?"
        werte.append(_datum(von, "den Beginn des Zeitraums"))
    if bis:
        sql += " AND b.datum <= ?"
        werte.append(_datum(bis, "das Ende des Zeitraums"))
    eintraege = [_zeile(z) for z in con.execute(sql + " ORDER BY b.datum DESC, b.id DESC", werte)]
    if suche:
        q = suche.strip().lower()
        namen = {s["id"]: s["name"].lower() for s in schueler}
        eintraege = [e for e in eintraege if q in e["text"].lower() or q in namen.get(e["schueler_id"], "")]
    zusammen = zusammenfassung(con, lid, kid)
    for s in schueler:
        s["beobachtungen"] = zusammen.get(s["id"], {"anzahl": 0, "positiv": 0, "neutral": 0, "negativ": 0, "zuletzt": ""})
    name = con.execute("SELECT name FROM klasse WHERE id = ?", (kid,)).fetchone()["name"]
    return {"klasse": {"id": kid, "name": name}, "schueler": schueler, "eintraege": eintraege}


def stunde(con, lid, datum, beginn):
    """Eigene Beobachtungen, die aus dieser Stunde notiert wurden (mit Namen)."""
    zeilen = con.execute("SELECT b.*, s.nachname, s.vorname FROM beobachtung b JOIN schueler s ON s.id = b.schueler_id "
                         "WHERE b.lehrkraft_id = ? AND b.stunde_datum = ? AND b.stunde_beginn = ? ORDER BY b.id",
                         (lid, _datum(datum), str(beginn or "")[:5]))
    return [dict(_zeile(z), name=z["nachname"] + (", " + z["vorname"] if z["vorname"] else "")) for z in zeilen]


# --- Aufraeumen: alte Beobachtungen zu Schuelern, die nicht mehr in der Klasse sind ---

def _alt_sql(heute):
    grenze = (heute - datetime.timedelta(days=AUFRAEUMEN_TAGE)).isoformat()
    return ("FROM beobachtung b JOIN schueler s ON s.id = b.schueler_id WHERE b.lehrkraft_id = ? AND s.aktiv = 0 AND b.datum < ?", grenze)


def aufraeumen_stand(con, lid, heute=None):
    """{anzahl, schueler: [{name, klasse, anzahl}]} der eigenen Beobachtungen, die zum Loeschen angeboten werden."""
    wo, grenze = _alt_sql(heute or db.heute())
    zeilen = con.execute("SELECT s.nachname, s.vorname, k.name AS klasse, COUNT(*) AS n " + wo.replace("WHERE", "JOIN klasse k ON k.id = s.klasse_id WHERE", 1)
                         + " GROUP BY s.id ORDER BY k.name, s.nachname", (lid, grenze)).fetchall()
    return {"anzahl": sum(z["n"] for z in zeilen), "grenze": grenze,
            "schueler": [{"name": z["nachname"] + (", " + z["vorname"] if z["vorname"] else ""), "klasse": z["klasse"], "anzahl": z["n"]} for z in zeilen]}


def aufraeumen(con, lid, heute=None):
    wo, grenze = _alt_sql(heute or db.heute())
    n = con.execute("SELECT COUNT(*) " + wo, (lid, grenze)).fetchone()[0]
    con.execute("DELETE FROM beobachtung WHERE id IN (SELECT b.id " + wo + ")", (lid, grenze))
    return n


# --- PDF ---

def _tag(iso):
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[:4]) if iso else ""


SPALTEN = (("Datum", 15 * MM), ("Kategorie", 37 * MM), ("Tendenz", 66 * MM), ("Beobachtung", 86 * MM))
TEXT_BREITE = A4[0] - 15 * MM - 86 * MM - 1 * MM


class _Blatt:
    """Seiten mit Kopf (erste Seite) und Fuss; neue Seite, wenn der Platz nicht reicht."""

    def __init__(self, kd, rechts_oben, titel, unterzeile):
        self.kd, self.seiten = kd, []
        self.s = Seite()
        self.seiten.append(self.s)
        self.y = fotos.kopf(self.s, kd, rechts_oben, titel, unterzeile)

    def platz(self, hoehe):
        if self.y - hoehe < 24 * MM:
            self.s = Seite()
            self.seiten.append(self.s)
            self.y = A4[1] - 20 * MM

    def tabellenkopf(self):
        self.platz(14 * MM)
        self.s.rechteck(15 * MM, self.y - 2 * MM, A4[0] - 30 * MM, 6.5 * MM, exporte.HELL)
        for name, x in SPALTEN:
            self.s.text(x + 1 * MM, self.y, name, 8, True)
        self.y -= 7 * MM

    def eintrag(self, e):
        zeilen = umbrechen(e["text"], 9, TEXT_BREITE)
        unter = ("Stunde " + _tag(e["stunde_datum"]) + (" · " + e["stunde_text"] if e["stunde_text"] else "")) if e["stunde_datum"] else ""
        hoehe = len(zeilen) * 4.2 * MM + (3.8 * MM if unter else 0) + 3.5 * MM
        if self.y - hoehe < 24 * MM:
            self.platz(hoehe + 10 * MM)
            self.tabellenkopf()
        s, y = self.s, self.y
        s.text(16 * MM, y, _tag(e["datum"]), 9)
        s.text(38 * MM, y, e["kategorie"] or "–", 9, farbe=exporte.LEISE if not e["kategorie"] else exporte.TEXT)
        s.text(67 * MM, y, PDF_TENDENZ[e["tendenz"]], 9)
        for i, z in enumerate(zeilen):
            s.text(87 * MM, y - i * 4.2 * MM, z, 9)
        if unter:
            s.text(87 * MM, y - len(zeilen) * 4.2 * MM, kuerzen(unter, 7.5, TEXT_BREITE), 7.5, farbe=exporte.LEISE)
        letzte = y - (len(zeilen) - 1) * 4.2 * MM - (3.8 * MM if unter else 0)   # Grundlinie der letzten Zeile
        s.linie(15 * MM, letzte - 2 * MM, A4[0] - 15 * MM, letzte - 2 * MM, (0.9, 0.91, 0.93), 0.4)
        self.y = y - hoehe

    def fertig(self, lehrkraft, titel):
        for nr, seite in enumerate(self.seiten, 1):
            exporte._fuss(seite, nr, len(self.seiten), lehrkraft + " · persönliche Aufzeichnung, vertraulich", self.kd)
        return pdf.dokument(self.seiten, titel=titel)


def _zaehler(eintraege):
    n = {t: sum(1 for e in eintraege if e["tendenz"] == t) for t in TENDENZEN}
    return "%d %s · %d positiv, %d neutral, %d negativ" % (len(eintraege), "Eintrag" if len(eintraege) == 1 else "Einträge",
                                                          n["positiv"], n["neutral"], n["negativ"])


def schueler_pdf(con, lid, sid, lehrkraft=""):
    """Alle eigenen Beobachtungen zu einem Schueler, mit Foto. Rueckgabe (pdf, dateiname)."""
    v = verlauf(con, lid, sid)
    s, e = v["schueler"], v["eintraege"]
    if not e:
        raise BeobachtungFehler("Zu %s hast du noch keine Beobachtungen." % s["name"])
    kd = exporte._kopfdaten(con)
    zeitraum = _tag(e[-1]["datum"]) + " bis " + _tag(e[0]["datum"])
    blatt = _Blatt(kd, s["klasse"], "Beobachtungen – " + s["name"], _zaehler(e) + " · " + zeitraum)
    foto = con.execute("SELECT foto FROM schueler WHERE id = ?", (sid,)).fetchone()["foto"]
    if foto:   # Foto unter dem Kopf, die Tabelle beginnt darunter
        b = 22 * MM
        blatt.s.bild(foto, 15 * MM, blatt.y - b * 5 / 4, b, b * 5 / 4)
        blatt.y -= b * 5 / 4 + 6 * MM
    blatt.tabellenkopf()
    for x in e:
        blatt.eintrag(x)
    name = "Beobachtungen %s %s.pdf" % (s["name"].replace(",", ""), datetime.date.today().isoformat())
    return blatt.fertig(lehrkraft, "Beobachtungen " + s["name"]), name


def klasse_pdf(con, lid, kid, lehrkraft="", **filter_):
    """Eigene Beobachtungen der Klasse, nach Schuelern (mit den Filtern der Uebersicht). Rueckgabe (pdf, dateiname)."""
    k = klasse(con, lid, kid, **filter_)
    if not k["eintraege"]:
        raise BeobachtungFehler("Es gibt keine Beobachtungen, die zum Filter passen.")
    je = {}
    for e in k["eintraege"]:
        je.setdefault(e["schueler_id"], []).append(e)
    filter_text = " · ".join(x for x in (filter_.get("kategorie") or "", PDF_TENDENZ.get(filter_.get("tendenz") or "", ""),
                                         ("ab " + _tag(filter_["von"])) if filter_.get("von") else "",
                                         ("bis " + _tag(filter_["bis"])) if filter_.get("bis") else "") if x)
    kd = exporte._kopfdaten(con)
    blatt = _Blatt(kd, k["klasse"]["name"], "Beobachtungen " + k["klasse"]["name"],
                   _zaehler(k["eintraege"]) + " · " + str(len(je)) + " Schüler" + (" · " + filter_text if filter_text else ""))
    for s in k["schueler"]:
        if s["id"] not in je:
            continue
        blatt.platz(24 * MM)
        blatt.s.text(15 * MM, blatt.y, kuerzen(s["name"], 12, 120 * MM, True), 12, True, exporte.BLAU)
        blatt.s.text(140 * MM, blatt.y, _zaehler(je[s["id"]]), 8, farbe=exporte.LEISE)
        blatt.y -= 7 * MM
        blatt.tabellenkopf()
        for x in je[s["id"]]:
            blatt.eintrag(x)
        blatt.y -= 4 * MM
    name = "Beobachtungen %s %s.pdf" % (k["klasse"]["name"], datetime.date.today().isoformat())
    return blatt.fertig(lehrkraft, "Beobachtungen " + k["klasse"]["name"]), name
