"""Stufe D2c: Exporte einer Pruefung.

- Notenspalte fuer die Excel-Notenliste: alle Schueler der Schuelerliste alphabetisch nach Nachname (auch
  ausgetretene, damit die Zeilen zur Excel-Liste passen), Note als Dezimalzahl mit Komma; fehlt bzw. ohne Note = leer.
- PDF zum Abheften: Ergebnisliste mit Notenspiegel (fuer die Akte) und Rueckmeldebogen je Schueler zum Aushaendigen
  (eine Seite je Schueler, ohne Daten anderer, mit Unterschriftszeilen).
- Moodle-Bewertungsbuch: CSV mit E-Mail-Adresse, Bewertung (Prozent 0-100) und Feedback (Note und Prozent).
"""
import csv
import datetime
import io

from . import grunddaten, pdf, pruefungen
from .pdf import MM, A4, BLAU, LEISE, Seite, kuerzen, umbrechen

TEXT = (0.11, 0.14, 0.2)
LINIE = (0.8, 0.82, 0.86)
HELL = (0.93, 0.95, 0.97)


def _komma(zahl, stellen=1):
    if zahl is None:
        return ""
    s = ("%." + str(stellen) + "f") % zahl
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _klasse(con, kid):
    return next((k["name"] for k in grunddaten.klassen(con) if k["id"] == kid), "?")


def _wann(p):
    if p["form"] == "termin":
        if p["teilung"] == "getrennt" and p.get("termine"):
            return "getrennt: " + ", ".join("%s %s %s" % (t["gruppe"], _tag(t["datum"]), t["beginn"]) for t in p["termine"])
        return "%s, %s" % (_tag(p["datum"]), p["beginn"])
    return "Fenster %s bis %s" % (_tag(p["fenster_von"]), _tag(p["fenster_bis"]))


def _tag(iso):
    return datetime.date.fromisoformat(iso).strftime("%d.%m.%Y") if iso else ""


# --- Notenspalte (Excel) ---

def notenspalte(con, lid, pid):
    """[{name, note}] fuer alle Schueler der Klasse, alphabetisch nach Nachname, Vorname; note als '1,7' oder ''."""
    e = pruefungen.ergebnis(con, lid, pid)
    noten = {z["id"]: z for z in e["schueler"]}
    alle = pruefungen.schueler(con, lid, e["pruefung"]["klasse_id"])
    alle.sort(key=lambda s: (pruefungen.normalisiert(s["nachname"]), pruefungen.normalisiert(s["vorname"])))
    zeilen = []
    for s in alle:
        z = noten.get(s["id"])
        note = z["note"]["dezimal"] if z and z["note"] and not z["fehlt"] else None
        zeilen.append({"name": s["name"], "note": _komma(note, 1) if note is not None else "", "aktiv": s["aktiv"],
                       "fehlt": bool(z and z["fehlt"])})
    return zeilen


# --- Moodle-Bewertungsbuch ---

def moodle_csv(con, lid, pid):
    """CSV fuer den Import ins Moodle-Bewertungsbuch (Zuordnung ueber die E-Mail-Adresse).
    Rueckgabe: (Text, [Namen ohne E-Mail-Adresse, die eine Note haben])."""
    e = pruefungen.ergebnis(con, lid, pid)
    mails = {s["id"]: s["email"] for s in pruefungen.schueler(con, lid, e["pruefung"]["klasse_id"])}
    aus = io.StringIO()
    w = csv.writer(aus, lineterminator="\n")
    w.writerow(["E-Mail-Adresse", "Bewertung", "Feedback"])
    ohne = []
    for z in e["schueler"]:
        if z["fehlt"] or z["prozent"] is None:
            continue
        if not mails.get(z["id"]):
            ohne.append(z["name"])
            continue
        feedback = ("Note %s · %s %%" % (z["note"]["text"], _komma(z["prozent"], 1))) if z["note"] else "%s %%" % _komma(z["prozent"], 1)
        w.writerow([mails[z["id"]], "%.2f" % z["prozent"], feedback])
    return aus.getvalue(), ohne


# --- PDF: Ergebnisliste ---

def _kopf(seite, p, klasse, unterzeile):
    b, h = A4
    seite.rechteck(0, h - 8 * MM, b, 8 * MM, BLAU)
    seite.text(15 * MM, h - 5.5 * MM, "Lehrerkalender MT", 8, True, (1, 1, 1))
    seite.text(15 * MM, h - 20 * MM, kuerzen(p["titel"], 18, b - 30 * MM, True), 18, True)
    seite.text(15 * MM, h - 27 * MM, kuerzen(unterzeile, 9, b - 30 * MM), 9, farbe=LEISE)
    seite.text(15 * MM, h - 32 * MM, kuerzen("%s · %s · %s · %s" % (klasse, p["artname"], pruefungen.ERFASSUNG_NAMEN.get(p["erfassung"], p["erfassung"]),
                                                               _wann(p)), 9, b - 30 * MM), 9, farbe=LEISE)
    seite.linie(15 * MM, h - 35 * MM, b - 15 * MM, h - 35 * MM)
    return h - 43 * MM


def _fuss(seite, nr, gesamt, lehrkraft):
    b, _ = A4
    seite.linie(15 * MM, 14 * MM, b - 15 * MM, 14 * MM)
    seite.text(15 * MM, 9 * MM, "%s · erstellt %s" % (lehrkraft, datetime.date.today().strftime("%d.%m.%Y")), 7.5, farbe=LEISE)
    seite.text(b - 35 * MM, 9 * MM, "Seite %d von %d" % (nr, gesamt), 7.5, farbe=LEISE)


def ergebnis_pdf(con, lid, pid, lehrkraft=""):
    """Ergebnisliste fuer die Akte: Kopf, Kennzahlen, Notenspiegel, Tabelle aller Schueler (mit Team, Dauer)."""
    e = pruefungen.ergebnis(con, lid, pid)
    p, st = e["pruefung"], e["statistik"]
    klasse = _klasse(con, p["klasse_id"])
    schluessel = "Testat (ohne Note)" if p["struktur"].get("testat") else (
        "%s (%s)" % (e["schluessel"]["name"], e["schluessel"]["systemname"]) if e["schluessel"] else "kein Notenschlüssel")
    b, _ = A4
    seiten = [Seite()]
    y = _kopf(seiten[0], p, klasse, "Ergebnisliste · Notenschlüssel: " + schluessel)
    s = seiten[0]
    kennzahlen = [("bewertet", "%d von %d" % (st["bewertet"], st["schueler"])), ("gefehlt", str(st["fehlt"])),
                  ("Schnitt", _komma(st["schnitt"], 2) or "–"), ("Ø Prozent", (_komma(st["prozent"], 1) + " %") if st["prozent"] is not None else "–")]
    for i, (name, wert) in enumerate(kennzahlen):
        x = 15 * MM + i * 45 * MM
        s.rechteck(x, y - 12 * MM, 42 * MM, 13 * MM, HELL)
        s.text(x + 3 * MM, y - 4.5 * MM, name, 7.5, farbe=LEISE)
        s.text(x + 3 * MM, y - 10 * MM, wert, 12, True)
    y -= 20 * MM
    # Notenspiegel als liegende Balken
    if st["spiegel"]:
        s.text(15 * MM, y, "Notenspiegel", 10, True)
        y -= 6 * MM
        hoechst = max(1, max(st["spiegel"].values()))
        for stufe, n in st["spiegel"].items():
            s.text(15 * MM, y, str(stufe), 8.5)
            if n:
                s.rechteck(30 * MM, y - 0.8 * MM, max(1.5 * MM, 110 * MM * n / hoechst), 3.6 * MM, BLAU)
            s.text(30 * MM + 112 * MM, y, str(n), 8.5, farbe=LEISE)
            y -= 5 * MM
        y -= 4 * MM
    # Tabelle
    spalten = [("Nr", 15 * MM), ("Name", 24 * MM), ("Team / Gruppe", 92 * MM), ("Dauer", 127 * MM), ("Prozent", 145 * MM), ("Note", 168 * MM)]

    def tabellenkopf(seite, y):
        seite.rechteck(15 * MM, y - 2 * MM, b - 30 * MM, 6.5 * MM, HELL)
        for name, x in spalten:
            seite.text(x + 1 * MM, y, name, 8, True)
        return y - 7 * MM

    y = tabellenkopf(s, y)
    for nr, z in enumerate(e["schueler"], 1):
        if y < 22 * MM:
            s = Seite()
            seiten.append(s)
            y = tabellenkopf(s, A4[1] - 20 * MM)
        werte = [str(nr), kuerzen(z["name"], 9, 66 * MM), kuerzen(" · ".join(x for x in (z["team"], z["gruppe"] or "") if x), 8, 33 * MM),
                 "%d:%02d" % divmod(z["dauer"], 60) if z.get("dauer") is not None else "",
                 "" if z["fehlt"] else (_komma(z["prozent"], 1) + " %" if z["prozent"] is not None else "–"),
                 "fehlt" if z["fehlt"] else (z["note"]["text"] if z["note"] else "–")]
        for (name, x), wert in zip(spalten, werte):
            s.text(x + 1 * MM, y, wert, 9 if name in ("Name", "Note") else 8.5, name == "Note", TEXT if z["aktiv"] else LEISE)
        s.linie(15 * MM, y - 2 * MM, b - 15 * MM, y - 2 * MM)
        y -= 6 * MM
    if y < 40 * MM:
        s = Seite()
        seiten.append(s)
        y = A4[1] - 30 * MM
    y -= 14 * MM
    s.linie(15 * MM, y, 85 * MM, y, TEXT)
    s.text(15 * MM, y - 4 * MM, "Datum, Unterschrift Lehrkraft", 7.5, farbe=LEISE)
    for i, seite in enumerate(seiten, 1):
        _fuss(seite, i, len(seiten), lehrkraft)
    return pdf.dokument(seiten, "Ergebnis " + p["titel"]), "Ergebnis %s %s.pdf" % (klasse, p["titel"])


# --- PDF: Rueckmeldebogen je Schueler ---

def _wert_text(k, wert):
    if k["typ"] == "stufen":
        if wert in (None, ""):
            return "nicht bewertet"
        st = k["stufen"][int(wert)]
        return "%s (%s von %s P)" % (st["name"], _komma(st["punkte"]), _komma(max(x["punkte"] for x in k["stufen"])))
    if k["typ"] == "punkte":
        return "nicht bewertet" if wert in (None, "") else "%s von %s P" % (_komma(float(wert), 2), _komma(k["max"]))
    if k["typ"] == "check":
        return ("✓ erledigt (%s P)" % _komma(k["max"])) if wert else "– offen (%s P)" % _komma(k["max"])
    if k["typ"] == "haken":
        return "✓ erledigt" if wert else "–"
    return str(wert or "")


class _Schreiber:
    """Fliesstext von oben nach unten mit Seitenumbruch."""

    def __init__(self, seiten, kopf):
        self.seiten, self.kopf = seiten, kopf
        self.neu()

    def neu(self):
        self.s = Seite()
        self.seiten.append(self.s)
        self.y = self.kopf(self.s)

    def platz(self, hoehe):
        if self.y - hoehe < 30 * MM:
            self.neu()

    def zeile(self, text, groesse=9.5, fett=False, farbe=TEXT, einzug=0, abstand=1.45):
        breite = A4[0] - 30 * MM - einzug
        for z in umbrechen(text, groesse, breite, fett) or [""]:
            self.platz(groesse * abstand)
            self.s.text(15 * MM + einzug, self.y, z, groesse, fett, farbe)
            self.y -= groesse * abstand

    def paar(self, links, rechts, einzug=4 * MM):
        """Kriterium links, Bewertung rechts (rechte Spalte ab 115 mm)."""
        zeilen = umbrechen(links, 9.5, 95 * MM - einzug)
        rz = umbrechen(rechts, 9.5, 78 * MM)
        n = max(len(zeilen), len(rz))
        self.platz(n * 13.5)
        for i in range(n):
            if i < len(zeilen):
                self.s.text(15 * MM + einzug, self.y, zeilen[i], 9.5)
            if i < len(rz):
                self.s.text(117 * MM, self.y, rz[i], 9.5, i == 0)
            self.y -= 13.5
        self.s.linie(15 * MM + einzug, self.y + 9, A4[0] - 15 * MM, self.y + 9, HELL)
        self.y -= 2


def rueckmeldung_pdf(con, lid, pid, sid=None, lehrkraft=""):
    """Rueckmeldebogen: je Schueler (oder nur sid) eigene Seite(n) zum Aushaendigen."""
    e = pruefungen.ergebnis(con, lid, pid)
    p = e["pruefung"]
    klasse = _klasse(con, p["klasse_id"])
    testat = bool(p["struktur"].get("testat"))
    auswahl = [z for z in e["schueler"] if (sid is None or z["id"] == sid) and not z["fehlt"]
               and (z["prozent"] is not None or z["protokoll"] or any(v["erledigt"] for v in z["versuche"]))]
    if not auswahl:
        raise pruefungen.PruefungFehler("Es gibt noch keine Bewertung für einen Rückmeldebogen.")
    alle_seiten = []
    for z in auswahl:
        seiten = []
        w = _Schreiber(seiten, lambda s: _kopf(s, p, klasse, "Rückmeldung für " + z["name"]))
        w.zeile(z["name"], 14, True)
        w.y -= 2
        if p["erfassung"] == "gesamt":
            w.paar("Gesamtpunkte", _wert_text({"typ": "punkte", "max": p["max_punkte"]}, z["werte"].get("gesamt")), 0)
        else:
            for b in p["struktur"]["bereiche"]:
                w.y -= 3
                titel = b["name"] + (" (Team)" if b.get("team") else "")
                if p["erfassung"] == "bogen":
                    titel += "  ·  Gewicht %s" % _komma(b["gewicht"])
                w.zeile(titel, 10.5, True, BLAU)
                for k in b["kriterien"]:
                    w.paar(k["name"], _wert_text(k, z["werte"].get(k["key"])))
        if z["protokoll"]:
            w.y -= 3
            w.zeile("Fragen im Gespräch", 10.5, True, BLAU)
            for x in z["protokoll"]:
                w.paar(("(spontan) " if x["spontan"] else "") + x["text"],
                       p["fragen_stufen"][x["stufe"]] if x["stufe"] is not None else "ohne Einschätzung")
        if z["notiz"]:
            w.y -= 3
            w.zeile("Bemerkung", 10.5, True, BLAU)
            w.zeile(z["notiz"], 9.5)
        # Ergebnis
        w.y -= 6
        w.platz(30 * MM)
        w.s.rechteck(15 * MM, w.y - 9 * MM, A4[0] - 30 * MM, 13 * MM, HELL)
        if testat:
            fertig = sum(1 for v in z["versuche"] if v["erledigt"] == v["gesamt"])
            ergebnis = "Testat: %d von %d Versuchen vollständig" % (fertig, len(z["versuche"]))
        elif z["note"]:
            ergebnis = "Ergebnis: %s %%  ·  Note %s" % (_komma(z["prozent"], 1), z["note"]["text"])
        else:
            ergebnis = "Ergebnis: %s %%" % _komma(z["prozent"], 1) if z["prozent"] is not None else "Noch nicht vollständig bewertet"
        w.s.text(19 * MM, w.y - 4.5 * MM, ergebnis, 13, True)
        w.y -= 14 * MM
        if z["rechenweg"]:
            for r in z["rechenweg"]:
                w.zeile(r, 7.5, farbe=LEISE)
        # Unterschriften
        w.platz(26 * MM)
        w.y -= 16 * MM
        for x, text in ((15 * MM, "Datum, Unterschrift Lehrkraft"), (110 * MM, "Kenntnis genommen: Schüler/in")):
            w.s.linie(x, w.y, x + 80 * MM, w.y, TEXT)
            w.s.text(x, w.y - 4 * MM, text, 7.5, farbe=LEISE)
        for i, seite in enumerate(seiten, 1):
            _fuss(seite, i, len(seiten), lehrkraft)
        alle_seiten.extend(seiten)
    name = "Rückmeldung %s %s%s.pdf" % (klasse, p["titel"], (" " + auswahl[0]["name"]) if sid else "")
    return pdf.dokument(alle_seiten, "Rückmeldung " + p["titel"]), name
