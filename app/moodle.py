"""Stufe D2d: Ergebnisse eines Moodle-Tests uebernehmen.

Eingelesen wird der Moodle-Bericht "Antworten" (bzw. "Bewertungen") als JSON-Download ([[{nachname, vorname, status,
begonnen, beendet, dauer, bewertungNNNNN, antwort1 ...}]]) oder als CSV (Spalten Nachname, Vorname, Status, Begonnen,
Beendet, Verbrauchte Zeit, Bewertung/100,00). Der Hoechstwert steckt im Spaltennamen: bewertung10000 = 100,00.
Uebernommen werden nur Bewertung und Dauer (Beginn/Ende), keine Antworttexte. Bei mehreren Versuchen zaehlt der beste.
Ein Versuch an einem anderen Tag als dem Pruefungstermin gilt als nachgeschrieben (Vermerk in der Notiz).

Ablauf: vorschau() liest die Datei und ordnet die Namen der Schuelerliste zu (sicher bei gleichem Nach- und Vornamen,
sonst Vorschlag); uebernehmen() liest die Datei erneut und schreibt mit der bestaetigten Zuordnung in eine vorhandene
Pruefung (Gesamtpunkte, umgerechnet) oder legt eine neue an.
"""
import collections
import csv
import datetime
import io
import json
import re

from . import grunddaten, pruefungen, stundenplan

MONATE = {"januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
          "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
          "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12}
BEENDET = ("beendet", "abgeschlossen", "abgegeben", "finished")


class MoodleFehler(pruefungen.PruefungFehler):
    pass


def _zeitpunkt(text):
    """'24. September 2026  10:24' -> datetime (auch 'Donnerstag, 24. September 2026, 10:24')."""
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})\D+(\d{1,2}):(\d{2})", text or "")
    if not m or m.group(2).lower() not in MONATE:
        m2 = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\D+(\d{1,2}):(\d{2})", text or "")
        if not m2:
            return None
        t, mo, j, h, mi = (int(x) for x in m2.groups())
    else:
        t, mo, j, h, mi = int(m.group(1)), MONATE[m.group(2).lower()], int(m.group(3)), int(m.group(4)), int(m.group(5))
    try:
        return datetime.datetime(j, mo, t, h, mi)
    except ValueError:
        return None


def _sekunden(text):
    """'58 Minuten 28 Sekunden', '1 Stunde', '1 Stunde 2 Minuten' -> Sekunden (oder None)."""
    faktor = {"tag": 86400, "stunde": 3600, "minute": 60, "sekunde": 1, "day": 86400, "hour": 3600, "min": 60, "sec": 1}
    summe, treffer = 0, False
    for zahl, einheit in re.findall(r"(\d+)\s*([A-Za-zä]+)", text or ""):
        e = einheit.lower()
        f = next((v for k, v in faktor.items() if e.startswith(k)), None)
        if f:
            summe += int(zahl) * f
            treffer = True
    return summe if treffer else None


def _zahl(text):
    text = (text or "").strip().replace(" ", "")
    if not text or text in ("-", "–"):
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _zeilen_json(roh):
    daten = json.loads(roh)
    flach = []

    def sammeln(x):
        if isinstance(x, dict):
            flach.append(x)
        elif isinstance(x, list):
            for y in x:
                sammeln(y)
    sammeln(daten)
    return [{str(k).strip().lower(): ("" if v is None else str(v)) for k, v in z.items()} for z in flach]


def _zeilen_csv(roh):
    probe = roh[:2000]
    trenner = ";" if probe.count(";") > probe.count(",") else ("\t" if probe.count("\t") > probe.count(",") else ",")
    leser = csv.reader(io.StringIO(roh), delimiter=trenner)
    kopf = next(leser, None)
    if not kopf:
        return []
    namen = []
    for k in kopf:
        k = k.strip().lower()
        m = re.match(r"bewertung\s*/\s*([\d.,]+)", k)
        if m:
            k = "bewertung%d" % round(_zahl(m.group(1)) * 100)
        elif k.startswith("begonnen"):
            k = "begonnen"
        elif k.startswith("beendet") or k.startswith("abgeschlossen"):
            k = "beendet"
        elif k.startswith("verbrauchte zeit") or k.startswith("dauer"):
            k = "dauer"
        elif "mail" in k:
            k = "email"
        namen.append(k)
    return [dict(zip(namen, z)) for z in leser if any(x.strip() for x in z)]


def lesen(roh):
    """Datei-Inhalt -> {max, versuche: [{nachname, vorname, email, beginn, ende, dauer, bewertung}], uebersprungen}."""
    roh = (roh or "").lstrip("﻿").strip()
    if not roh:
        raise MoodleFehler("Die Datei ist leer.")
    try:
        zeilen = _zeilen_json(roh) if roh[0] in "[{" else _zeilen_csv(roh)
    except (ValueError, csv.Error):
        raise MoodleFehler("Die Datei lässt sich nicht lesen. Bitte den Moodle-Bericht als JSON oder CSV herunterladen.")
    hoechst = None
    for z in zeilen:
        for k in z:
            m = re.fullmatch(r"bewertung(\d+)", k)
            if m:
                hoechst = int(m.group(1)) / 100.0
    if not zeilen or "nachname" not in zeilen[0]:
        raise MoodleFehler("In der Datei fehlen die Spalten Nachname/Vorname. Bitte den Bericht „Antworten“ oder „Bewertungen“ des Tests verwenden.")
    if not hoechst:
        raise MoodleFehler("In der Datei fehlt die Spalte „Bewertung“ (z. B. Bewertung/100,00).")
    schluessel = "bewertung%d" % round(hoechst * 100)
    versuche, uebersprungen = [], 0
    for z in zeilen:
        name = (z.get("nachname") or "").strip()
        status = (z.get("status") or "beendet").strip().lower()
        if not name or name.lower().startswith(("gesamtdurchschnitt", "overall average", "durchschnitt")):
            continue
        if not status.startswith(BEENDET):
            uebersprungen += 1
            continue
        beginn, ende = _zeitpunkt(z.get("begonnen")), _zeitpunkt(z.get("beendet"))
        dauer = _sekunden(z.get("dauer"))
        if beginn and dauer is not None:
            ende = beginn + datetime.timedelta(seconds=dauer)   # genauer als die gerundete Endzeit
        versuche.append({"nachname": name, "vorname": (z.get("vorname") or "").strip(), "email": (z.get("email") or z.get("e-mail-adresse") or "").strip(),
                         "beginn": beginn, "ende": ende, "dauer": dauer, "bewertung": _zahl(z.get(schluessel))})
    if not versuche:
        raise MoodleFehler("Die Datei enthält keine beendeten Versuche.")
    return {"max": hoechst, "versuche": versuche, "uebersprungen": uebersprungen}


def _beste(versuche):
    """Je Person (Nach- und Vorname) der beste Versuch; ohne Bewertung zaehlt der erste."""
    je = collections.OrderedDict()
    for v in versuche:
        je.setdefault((pruefungen.normalisiert(v["nachname"]), pruefungen.normalisiert(v["vorname"])), []).append(v)
    ergebnis = []
    for k, liste in je.items():
        bewertet = [v for v in liste if v["bewertung"] is not None]
        beste = max(bewertet, key=lambda v: v["bewertung"]) if bewertet else liste[0]
        ergebnis.append(dict(beste, schluessel="%s|%s" % k, anzahl=len(liste)))
    return ergebnis


def _zuordnen(liste, schueler):
    """Vorschlag je Moodle-Person: gleiche E-Mail oder gleicher Nach- und Vorname = sicher; nur gleicher Nachname
    (eindeutig) bzw. Vorname vertauscht = Vorschlag."""
    for v in liste:
        n, vn = pruefungen.normalisiert(v["nachname"]), pruefungen.normalisiert(v["vorname"])
        treffer = [s for s in schueler if v["email"] and s["email"] and s["email"].lower() == v["email"].lower()]
        sicher = bool(treffer)
        if not treffer:
            treffer = [s for s in schueler if pruefungen.normalisiert(s["nachname"]) == n and pruefungen.normalisiert(s["vorname"]) == vn]
            sicher = bool(treffer)
        if not treffer:
            treffer = [s for s in schueler if pruefungen.normalisiert(s["nachname"]) == vn and pruefungen.normalisiert(s["vorname"]) == n] or \
                      [s for s in schueler if pruefungen.normalisiert(s["nachname"]) == n]
        v["schueler_id"] = treffer[0]["id"] if len(treffer) == 1 else None
        v["sicher"] = sicher and len(treffer) == 1


def _termin(p, liste):
    """Tag der Pruefung: Termin der Pruefung, sonst der Tag mit den meisten Versuchen."""
    if p is not None and p["form"] == "termin" and p["datum"]:
        return p["datum"]
    tage = collections.Counter(v["beginn"].date().isoformat() for v in liste if v["beginn"])
    return tage.most_common(1)[0][0] if tage else None


def _titel_aus(dateiname):
    t = re.sub(r"\.(json|csv|txt)$", "", (dateiname or "").strip(), flags=re.I)
    t = re.sub(r"[-_ ]*(antworten|bewertungen|ergebnisse|responses|grades)$", "", t, flags=re.I)
    return t.strip(" -_")[:120] or "Moodle-Test"


def vorschau(con, lid, daten):
    """Datei lesen und zuordnen. daten: {text, dateiname, pruefung_id | klasse_id}."""
    p = None
    if daten.get("pruefung_id"):
        p = pruefungen._aus_zeile(pruefungen._pruefung(con, lid, pruefungen._id(daten.get("pruefung_id"))))
        if p["erfassung"] != "gesamt":
            raise MoodleFehler("Moodle liefert nur die Gesamtbewertung. Übernehmen geht in Prüfungen mit „Gesamtpunkte“ – oder lege eine neue Prüfung aus der Datei an.")
        kid = p["klasse_id"]
    else:
        kid = pruefungen._klasse(con, pruefungen._id(daten.get("klasse_id")))
    g = lesen(daten.get("text"))
    liste = _beste(g["versuche"])
    schueler = pruefungen.schueler(con, lid, kid)
    if not schueler:
        raise MoodleFehler("Für diese Klasse gibt es noch keine Schülerliste. Lege sie zuerst an (Prüfungen → Schülerlisten).")
    _zuordnen(liste, schueler)
    tag = _termin(p, liste)
    zeilen = []
    for v in liste:
        datum = v["beginn"].date().isoformat() if v["beginn"] else None
        zeilen.append({"schluessel": v["schluessel"], "name": v["nachname"] + (", " + v["vorname"] if v["vorname"] else ""),
                       "anzahl": v["anzahl"], "bewertung": v["bewertung"], "prozent": None if v["bewertung"] is None else 100.0 * v["bewertung"] / g["max"],
                       "datum": datum, "dauer": v["dauer"], "nachgeschrieben": bool(tag and datum and datum != tag),
                       "schueler_id": v["schueler_id"], "sicher": v["sicher"]})
    beginn = collections.Counter(v["beginn"].strftime("%H:%M") for v in liste if v["beginn"] and v["beginn"].date().isoformat() == tag)
    return {"max": g["max"], "zeilen": zeilen, "uebersprungen": g["uebersprungen"], "termin": tag,
            "beginn": beginn.most_common(1)[0][0] if beginn else None, "titel": _titel_aus(daten.get("dateiname")),
            "klasse_id": kid, "pruefung": {"id": p["id"], "titel": p["titel"], "max_punkte": p["max_punkte"]} if p else None,
            "schueler": [{"id": s["id"], "name": s["name"], "aktiv": s["aktiv"]} for s in schueler]}


def _block(con, kid, uhrzeit):
    """Block des Zeitrasters der Klasse, in dem die Uhrzeit liegt (bzw. der naechste danach)."""
    raster = stundenplan.raster_der_klasse(con, kid)
    for b in raster:
        if b["beginn"] <= uhrzeit < b["ende"]:
            return b["beginn"]
    spaeter = [b for b in raster if b["beginn"] >= uhrzeit]
    return spaeter[0]["beginn"] if spaeter else None


def uebernehmen(con, lid, daten):
    """Mit bestaetigter Zuordnung {schluessel: schueler_id} in die Pruefung schreiben bzw. eine neue anlegen.
    Rueckgabe: {pruefung_id, uebernommen, ohne_zuordnung}."""
    v = vorschau(con, lid, daten)
    zuordnung = daten.get("zuordnung") or {}
    erlaubt = {s["id"] for s in v["schueler"]}
    if v["pruefung"]:
        pid = v["pruefung"]["id"]
        p = pruefungen._pruefung(con, lid, pid)
    else:
        if not v["termin"]:
            raise MoodleFehler("Die Datei enthält kein Datum. Bitte die Prüfung selbst anlegen und dann übernehmen.")
        sj = grunddaten.schuljahr_zum(con, v["termin"])
        if sj is None:
            raise MoodleFehler("Der Tag der Prüfung (%s) liegt in keinem Schuljahr." % v["termin"])
        block = _block(con, v["klasse_id"], v["beginn"] or "00:00")
        basis = {"klasse_id": v["klasse_id"], "schuljahr_id": sj["id"], "titel": (daten.get("titel") or v["titel"]), "art": "schriftlich",
                 "erfassung": "gesamt", "max_punkte": v["max"], "stand": "durchgefuehrt"}
        if block:
            basis.update(form="termin", datum=v["termin"], beginn=block)
        else:
            basis.update(form="fenster", fenster_von=v["termin"], fenster_bis=v["termin"])
        pid = pruefungen.pruefung_speichern(con, lid, basis)
        p = pruefungen._pruefung(con, lid, pid)
    faktor = p["max_punkte"] / v["max"]
    uebernommen, ohne = 0, 0
    benutzt = set()
    beste = {x["schluessel"]: x for x in _beste(lesen(daten.get("text"))["versuche"])}
    for z in v["zeilen"]:
        sid = pruefungen._id(zuordnung.get(z["schluessel"], z["schueler_id"]))
        if sid is None or sid not in erlaubt:
            ohne += 1
            continue
        if sid in benutzt:
            raise MoodleFehler("Ein Schüler ist mehreren Moodle-Namen zugeordnet. Bitte die Zuordnung prüfen.")
        benutzt.add(sid)
        if z["bewertung"] is None:
            ohne += 1
            continue
        pruefungen.bewertung_setzen(con, lid, pid, sid, {"werte": {"gesamt": round(z["bewertung"] * faktor, 2)}, "fehlt": False})
        versuch = beste[z["schluessel"]]
        if versuch["beginn"]:
            con.execute("UPDATE bewertung SET beginn = ?, ende = ? WHERE pruefung_id = ? AND schueler_id = ?",
                        (versuch["beginn"].isoformat(timespec="seconds"), versuch["ende"].isoformat(timespec="seconds") if versuch["ende"] else None, pid, sid))
        if z["nachgeschrieben"]:
            vermerk = "nachgeschrieben am %s" % datetime.date.fromisoformat(z["datum"]).strftime("%d.%m.%Y")
            alt = con.execute("SELECT notiz FROM bewertung WHERE pruefung_id = ? AND schueler_id = ?", (pid, sid)).fetchone()["notiz"]
            if vermerk not in alt:
                con.execute("UPDATE bewertung SET notiz = ? WHERE pruefung_id = ? AND schueler_id = ?",
                            ((alt + "\n" if alt else "") + vermerk, pid, sid))
        uebernommen += 1
    return {"pruefung_id": pid, "uebernommen": uebernommen, "ohne_zuordnung": ohne}
