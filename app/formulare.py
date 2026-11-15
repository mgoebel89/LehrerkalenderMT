"""Stufe F1: Formularcenter mit Ablage und Status (erstellt, abgegeben, genehmigt) und die Unterschrift je Konto.

Erstes Formular: Stundenplanaenderung / Beurlaubung der DRS (aus dem alten Lehrerkalender uebernommen). Die
Schul-Vorlage ist ein echtes AcroForm mit 201 benannten Feldern; wir befuellen sie direkt, so sieht das Ergebnis 1:1
aus und der Schulleitungs-Block bleibt leer und im Reader ausfuellbar. Die Vorlage liegt NICHT im (oeffentlichen)
Repo, sondern wird vom Admin hochgeladen (Grunddaten -> Schule und Logo) und in der Datenbank gehalten.

Zwei Fallen (wie im alten Tool geloest):
1. Die Tabellen-Feldnamen sind chaotisch (Zeile 1 heisst M2/M1, die A-Zeilen M11A2 ...). Verlaesslich ist nur die
   Geometrie: die Zuordnung (Tag, Zeile, Klasse-/Vertretungs-Spalte) entsteht aus den Widget-Rechtecken.
2. Die Unterschrift ist ein Textfeld; das gezeichnete Bild (PNG, transparent) kommt per reportlab-Overlay auf die Linie.

Block -> Formularzeilen (Doppelstunden): Block 1 -> 1./2., 2 -> 3./4., 3 -> 5./6., 4 -> 7./8., 5 -> A1/A2, 6 -> A3/A4.
Die Blocknummer ist die Stelle des Blocks im Zeitraster der Klasse.

pypdf und reportlab kommen aus den Paketquellen (python3-pypdf, python3-reportlab); sie werden erst beim Erzeugen
geladen, damit der Rest der App auch ohne sie laeuft.
"""
import base64
import datetime
import hashlib
import io
import json
import re

from . import db, stundenplan

ARTEN = {"stundenplanaenderung": "Stundenplanänderung / Beurlaubung"}
STAENDE = ("erstellt", "abgegeben", "genehmigt")
WOCHENTAGE_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]
BLOCK_ZEILEN = [(0, 1), (2, 3), (4, 5), (6, 7), (10, 11), (12, 13)]
PFLICHTFELDER = ("Antragsteller1", "Unterschrift der Lehrperson1", "am  von1", "bis1")

# Begruendung: Checkbox + Textfelder (Schluessel = Namen im Dialog)
GRUENDE = {
    "pruefung": {"name": "Teilnahme an einer Prüfung", "checkbox": "Check Box2",
                 "felder": {"fuer": ("Teilnahme an Prüfung (für)", "Teilnahme an Pruefung"), "in": ("Prüfung in", "Pruefung in")}},
    "sitzung": {"name": "Sitzung / Konferenz", "checkbox": "Check Box1", "felder": {"bezeichnung": ("Sitzung in", "in1")}},
    "fortbildung": {"name": "Fortbildung", "checkbox": "Check Box4",
                    "felder": {"ort": ("Fortbildung in", "Fortbildung in1"), "thema": ("Thema", "Thema1"),
                               "antrag_am": ("Antrag bei der Schulleitung am", "Antrag bei SL am1")}},
    "beurlaubung": {"name": "Beurlaubung", "checkbox": "Check Box3", "felder": {}},
    "klassenfahrt": {"name": "Klassenfahrt / Unterrichtsgang", "checkbox": "Check Box6",
                     "felder": {"klasse": ("mit der Klasse", "Klassenfahrt  Klassenwanderung mit der Klasse1"), "nach": ("nach", "nach1"),
                                "befoerderung": ("Beförderungsmittel", "Beförderungsmittel1"), "von": ("Fahrt vom", "Die Fahrt findet vom1"),
                                "bis": ("bis", "Datum oder Unterrichtsstunden bis1")}},
    "sonstige": {"name": "Sonstiges", "checkbox": "Check Box5", "felder": {"text": ("Begründung", "Datum oder Unterrichtsstunden1")}},
}
_CHECKBOX_AN = "/Ja"
_RADIO_GRUPPE = "Group1"
_RADIO_ERFORDERLICH = "/1"
_RADIO_NICHT = "/0"
AUSFALL_TEXT = "entfällt, Klasse informiert"
MAX_UNTERSCHRIFT = 500 * 1024


class FormularFehler(Exception):
    pass


def _pypdf():
    try:
        import pypdf
        return pypdf
    except ImportError:
        raise FormularFehler("Für Formulare fehlt auf dem Server das Paket python3-pypdf (Admin: Update ausführen).")


# --- Unterschrift und Paraphe je Konto ---

def unterschrift(con, lid, art="unterschrift"):
    spalte = "paraphe" if art == "paraphe" else "unterschrift"
    z = con.execute("SELECT %s FROM lehrkraft WHERE id = ?" % spalte, (lid,)).fetchone()
    return bytes(z[0]) if z and z[0] else None


def unterschrift_setzen(con, lid, art, bild):
    """bild: 'data:image/png;base64,...' (neu) oder '' (entfernen)."""
    if art not in ("unterschrift", "paraphe"):
        raise FormularFehler("Unbekannte Art.")
    roh = None
    if bild:
        m = re.fullmatch(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)", bild)
        if not m:
            raise FormularFehler("Die Zeichnung kam nicht als PNG an.")
        roh = base64.b64decode(m.group(1))
        if not roh.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FormularFehler("Die Zeichnung kam nicht als PNG an.")
        if len(roh) > MAX_UNTERSCHRIFT:
            raise FormularFehler("Die Zeichnung ist zu groß.")
    con.execute("UPDATE lehrkraft SET %s = ? WHERE id = ?" % art, (roh, lid))


# --- Vorlage ---

def vorlage(con, art="stundenplanaenderung"):
    z = con.execute("SELECT pdf FROM formularvorlage WHERE art = ?", (art,)).fetchone()
    return bytes(z[0]) if z else None


def vorlagen(con):
    return {z["art"]: {"name": z["name"], "hochgeladen": z["hochgeladen"]}
            for z in con.execute("SELECT art, name, hochgeladen FROM formularvorlage")}


def vorlage_setzen(con, art, inhalt, name=""):
    """Schul-Vorlage pruefen und speichern. inhalt: 'data:application/pdf;base64,...' oder Bytes; '' entfernt sie."""
    if art not in ARTEN:
        raise FormularFehler("Unbekanntes Formular.")
    if not inhalt:
        con.execute("DELETE FROM formularvorlage WHERE art = ?", (art,))
        return
    if isinstance(inhalt, str):
        m = re.fullmatch(r"data:[a-z/+-]*;base64,([A-Za-z0-9+/=\s]+)", inhalt)
        if not m:
            raise FormularFehler("Die Vorlage muss ein PDF sein.")
        inhalt = base64.b64decode(m.group(1))
    if not inhalt.startswith(b"%PDF"):
        raise FormularFehler("Die Vorlage muss ein PDF sein.")
    pypdf = _pypdf()
    try:
        felder = pypdf.PdfReader(io.BytesIO(inhalt)).get_fields() or {}
    except Exception:
        raise FormularFehler("Das PDF lässt sich nicht lesen.")
    fehlen = [f for f in PFLICHTFELDER if f not in felder]
    if fehlen:
        raise FormularFehler("Das ist nicht das erwartete DRS-Formular (es fehlen Felder wie „%s“)." % fehlen[0])
    con.execute("INSERT INTO formularvorlage (art, pdf, name, hochgeladen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (art) DO UPDATE SET pdf = excluded.pdf, name = excluded.name, hochgeladen = excluded.hochgeladen",
                (art, inhalt, (name or "")[:200], db.jetzt()))
    _karte.cache.clear()


def _widgets(reader):
    aus = []
    for a in reader.pages[0].get("/Annots") or []:
        o = a.get_object()
        if o.get("/Subtype") != "/Widget":
            continue
        eltern = o.get("/Parent")
        name = o.get("/T") or (eltern.get_object().get("/T") if eltern else None)
        typ = o.get("/FT") or (eltern.get_object().get("/FT") if eltern else None)
        rect = o.get("/Rect")
        if not name or not rect:
            continue
        x0, y0, x1, y1 = (float(v) for v in rect)
        aus.append({"name": str(name), "ft": str(typ), "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return aus


def _zentren(werte, toleranz):
    zentren = []
    for v in sorted(werte):
        if zentren and abs(v - zentren[-1]) <= toleranz:
            continue
        zentren.append(v)
    return zentren


def _karte(pdf_bytes):
    """{tag: [(klasse_feld, vertretung_feld)] je Zeile oben -> unten} und das Rechteck der Unterschrift, aus der Geometrie."""
    schluessel = hashlib.sha1(pdf_bytes).hexdigest()
    if schluessel in _karte.cache:
        return _karte.cache[schluessel]
    reader = _pypdf().PdfReader(io.BytesIO(pdf_bytes))
    alle = _widgets(reader)
    ws = [w for w in alle if w["ft"] == "/Tx" and 145 <= w["y0"] <= 320 and w["x0"] >= 115]
    zeilen = sorted(_zentren([w["y0"] for w in ws], 6), reverse=True)
    spalten = sorted(_zentren([w["x0"] for w in ws], 8))

    def naechster(zentren, v):
        return min(range(len(zentren)), key=lambda i: abs(zentren[i] - v))
    raster = {}
    for w in ws:
        raster[(naechster(zeilen, w["y0"]), naechster(spalten, w["x0"]))] = w["name"]
    tage = {}
    for d, tag in enumerate(_TAGE):
        tage[tag] = [(raster.get((r, 2 * d), ""), raster.get((r, 2 * d + 1), "")) for r in range(len(zeilen))]
    sig = next(((w["x0"], w["y0"], w["x1"], w["y1"]) for w in alle if w["name"] == "Unterschrift der Lehrperson1"), (250.0, 120.0, 591.0, 138.0))
    mb = reader.pages[0].mediabox
    _karte.cache[schluessel] = {"tage": tage, "unterschrift": sig, "seite": (float(mb.width), float(mb.height))}
    return _karte.cache[schluessel]


_karte.cache = {}


# --- Aenderungen einer Woche ---

def woche_aenderungen(con, lid, montag):
    """Ausfall und Vertretung eigener Stunden der Woche (wie im Wochenplan); verschobene und Zusatzstunden zaehlen nicht.
    {von, bis, eintraege: [{datum, tag, block, klasse, vertretung, grund}]}"""
    if isinstance(montag, str):
        montag = datetime.date.fromisoformat(montag)
    montag = stundenplan.montag_von(montag)
    w = stundenplan.woche(con, lid, montag)
    cache, eintraege = {}, []
    for b in w["bloecke"]:
        if b["art"] != "regulaer" or b["zustand"] not in ("ausfall", "vertreten") or not b["klasse"]:
            continue
        raster = stundenplan.raster_der_klasse(con, b["klasse"]["id"], cache)
        nr = next((i for i, r in enumerate(raster) if r["beginn"] == b["beginn"]), None)
        if nr is None or nr >= len(BLOCK_ZEILEN):
            continue
        tag = datetime.date.fromisoformat(b["datum"])
        klasse = b["klasse"]["name"] + (" " + b["gruppe"]["name"] if b["gruppe"] else "")
        eintraege.append({"datum": b["datum"], "tag": tag.weekday(), "block": nr, "beginn": b["beginn"], "klasse": klasse,
                          "vertretung": AUSFALL_TEXT if b["zustand"] == "ausfall" else (b.get("wer") or "").strip(),
                          "grund": b.get("grund") or ""})
    eintraege.sort(key=lambda e: (e["datum"], e["block"]))
    tage = sorted({e["datum"] for e in eintraege})
    return {"montag": montag.isoformat(), "von": tage[0] if tage else None, "bis": tage[-1] if tage else None, "eintraege": eintraege}


def _tag_text(iso):
    if not iso:
        return ""
    try:
        d = datetime.date.fromisoformat(iso.strip())
    except ValueError:
        return iso.strip()
    return "%s, %s" % (WOCHENTAGE_LANG[d.weekday()][:2], d.strftime("%d.%m.%Y"))


# --- Ausfuellen ---

def _knopf_staende(writer, staende):
    acro = writer._root_object.get("/AcroForm")
    if acro is None:
        return
    from pypdf.generic import NameObject
    for f in acro.get_object().get("/Fields") or []:
        obj = f.get_object()
        name = obj.get("/T")
        if name is None or str(name) not in staende:
            continue
        ziel = staende[str(name)]
        obj[NameObject("/V")] = NameObject(ziel)
        kinder = obj.get("/Kids")
        if kinder:
            for kid in kinder:
                k = kid.get_object()
                ap = k.get("/AP")
                hier = [str(x) for x in ap.get_object()["/N"].get_object().keys()] if ap and ap.get_object().get("/N") else []
                k[NameObject("/AS")] = NameObject(ziel if ziel in hier else "/Off")
        else:
            obj[NameObject("/AS")] = NameObject(ziel)


def _automatische_groesse(writer, namen):
    """Schmale Tabellenspalten: Schriftgroesse 0 (= automatisch), damit langer Text schrumpft statt abgeschnitten zu werden."""
    if not namen:
        return
    from pypdf.generic import NameObject, TextStringObject
    for a in writer.pages[0].get("/Annots") or []:
        o = a.get_object()
        eltern = o.get("/Parent")
        nm = o.get("/T") or (eltern.get_object().get("/T") if eltern else None)
        if nm is None or str(nm) not in namen:
            continue
        da = o.get("/DA") or (eltern.get_object().get("/DA") if eltern else None)
        neu = re.sub(r"(/\S+)\s+[\d.]+\s+Tf", r"\1 0 Tf", str(da), count=1) if da else "/Cali 0 Tf 0 0.388235 0.611765 rg"
        o[NameObject("/DA")] = TextStringObject(neu)


def _unterschrift_overlay(bild, karte):
    """Eine Seite mit dem Unterschriftsbild auf der Linie (sitzt auf, ragt nicht in die Tabelle)."""
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError:
        return None
    try:
        img = ImageReader(io.BytesIO(bild))
        iw, ih = img.getSize()
    except Exception:
        return None
    if not iw or not ih:
        return None
    pw, ph = karte["seite"]
    x0, y0, x1, _ = karte["unterschrift"]
    unten = y0 - 1.0
    hoehe_max = min(20.0, max(10.0, 146.0 - unten))
    breite_max = min((x1 - x0) - 6, 220.0)
    f = min(breite_max / iw, hoehe_max / ih)
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=(pw, ph))
    try:
        c.drawImage(img, x0 + 4, unten, width=iw * f, height=ih * f, mask="auto", preserveAspectRatio=True)
        c.save()
    except Exception:          # unlesbares Bild: Formular lieber ohne Unterschrift als gar nicht
        return None
    puffer.seek(0)
    return _pypdf().PdfReader(puffer).pages[0]


def ausfuellen(con, konto, montag, grund, felder, von=None, bis=None, aenderungen=None, heute=None):
    """Befuellte Stundenplanaenderung als PDF-Bytes."""
    pdf_vorlage = vorlage(con)
    if not pdf_vorlage:
        raise FormularFehler("Die Schul-Vorlage für die Stundenplanänderung fehlt noch. Der Admin lädt sie unter Grunddaten → Schule und Logo hoch.")
    if grund not in GRUENDE:
        raise FormularFehler("Bitte eine Begründung wählen.")
    pypdf = _pypdf()
    ae = aenderungen or woche_aenderungen(con, konto["id"], montag)
    karte = _karte(pdf_vorlage)
    werte = {"Antragsteller1": konto["name"], "Datum1": (heute or datetime.date.today()).strftime("%d.%m.%Y")}
    von_text = _tag_text(von) if von else _tag_text(ae["von"])
    bis_text = _tag_text(bis) if bis else _tag_text(ae["bis"])
    if von_text:
        werte["am  von1"] = von_text
    if bis_text:
        werte["bis1"] = bis_text
    tabelle = set()
    for e in ae["eintraege"]:
        if e["tag"] > 5:
            continue
        for zeile in BLOCK_ZEILEN[e["block"]]:
            kf, vf = karte["tage"][_TAGE[e["tag"]]][zeile] if zeile < len(karte["tage"][_TAGE[e["tag"]]]) else ("", "")
            if kf:
                werte[kf] = e["klasse"]
                tabelle.add(kf)
            if vf:
                werte[vf] = e["vertretung"]
                tabelle.add(vf)
    g = GRUENDE[grund]
    for schluessel, (_, feld) in g["felder"].items():
        wert = str((felder or {}).get(schluessel) or "").strip()
        if wert:
            werte[feld] = wert[:200]
    reader = pypdf.PdfReader(io.BytesIO(pdf_vorlage))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    seite = writer.pages[0]
    writer.update_page_form_field_values(seite, werte, auto_regenerate=False)
    _automatische_groesse(writer, tabelle)
    _knopf_staende(writer, {_RADIO_GRUPPE: _RADIO_ERFORDERLICH if ae["eintraege"] else _RADIO_NICHT, g["checkbox"]: _CHECKBOX_AN})
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass
    bild = unterschrift(con, konto["id"])
    if bild:
        overlay = _unterschrift_overlay(bild, karte)
        if overlay is not None:
            seite.merge_page(overlay)
    puffer = io.BytesIO()
    writer.write(puffer)
    return puffer.getvalue()


# --- Ablage ---

def _formular(con, lid, fid):
    z = con.execute("SELECT * FROM formular WHERE id = ? AND lehrkraft_id = ?", (fid, lid)).fetchone()
    if z is None:
        raise FormularFehler("Dieses Formular gibt es nicht.")
    return z


def _betrifft(von, bis, grund, ae, felder):
    zeit = _tag_text(von)[:2] + " " + datetime.date.fromisoformat(von).strftime("%d.%m.") if von else ""
    if bis and bis != von:
        zeit += " – " + _tag_text(bis)[:2] + " " + datetime.date.fromisoformat(bis).strftime("%d.%m.")
    was = GRUENDE[grund]["name"].split(" / ")[0]
    if grund == "fortbildung" and (felder or {}).get("thema"):
        was = "Fortbildung " + str(felder["thema"]).strip()[:40]
    if grund == "klassenfahrt" and (felder or {}).get("klasse"):
        was = "Fahrt " + str(felder["klasse"]).strip()[:30]
    n = len(ae["eintraege"])
    return " · ".join(x for x in (zeit, was, ("%d %s" % (n, "Block" if n == 1 else "Blöcke")) if n else "") if x)


def erstellen(con, konto, daten):
    """Stundenplanaenderung erzeugen und ablegen. daten: {woche, grund, felder, von, bis}. Rueckgabe: id."""
    try:
        montag = stundenplan.montag_von(datetime.date.fromisoformat(daten.get("woche") or daten.get("von") or ""))
    except (TypeError, ValueError):
        raise FormularFehler("Bitte die Woche wählen.")
    von = (daten.get("von") or "").strip() or None
    bis = (daten.get("bis") or "").strip() or None
    for x in (von, bis):
        if x:
            try:
                datetime.date.fromisoformat(x)
            except ValueError:
                raise FormularFehler("Ungültiges Datum.")
    if von and bis and bis < von:
        raise FormularFehler("„bis“ liegt vor „von“.")
    grund = daten.get("grund")
    felder = {k: str(v)[:200] for k, v in (daten.get("felder") or {}).items() if isinstance(k, str)}
    ae = woche_aenderungen(con, konto["id"], montag)
    pdf = ausfuellen(con, konto, montag, grund, felder, von, bis, ae)
    von = von or ae["von"] or montag.isoformat()
    bis = bis or ae["bis"] or von
    jetzt = db.jetzt()
    return con.execute("INSERT INTO formular (lehrkraft_id, art, betrifft, von, bis, daten, pdf, stand, erstellt, geaendert) "
                       "VALUES (?, 'stundenplanaenderung', ?, ?, ?, ?, ?, 'erstellt', ?, ?)",
                       (konto["id"], _betrifft(von, bis, grund, ae, felder), von, bis,
                        json.dumps({"woche": montag.isoformat(), "grund": grund, "felder": felder}, ensure_ascii=False), pdf, jetzt, jetzt)).lastrowid


def liste(con, lid):
    return [{"id": z["id"], "art": z["art"], "artname": ARTEN.get(z["art"], z["art"]), "betrifft": z["betrifft"], "von": z["von"],
             "bis": z["bis"], "stand": z["stand"], "erstellt": z["erstellt"], "geaendert": z["geaendert"], "daten": json.loads(z["daten"] or "{}")}
            for z in con.execute("SELECT id, art, betrifft, von, bis, stand, erstellt, geaendert, daten FROM formular WHERE lehrkraft_id = ? "
                                 "ORDER BY von DESC, id DESC", (lid,))]


def pdf_von(con, lid, fid):
    z = _formular(con, lid, fid)
    return bytes(z["pdf"]), "%s %s.pdf" % ("Stundenplanaenderung", z["von"] or "")


def stand_setzen(con, lid, fid, stand):
    _formular(con, lid, fid)
    if stand not in STAENDE:
        raise FormularFehler("Unbekannter Stand.")
    con.execute("UPDATE formular SET stand = ?, geaendert = ? WHERE id = ?", (stand, db.jetzt(), fid))


def loeschen(con, lid, fid):
    _formular(con, lid, fid)
    con.execute("DELETE FROM formular WHERE id = ?", (fid,))


def uebersicht(con, lid):
    """Fuer das Formularcenter: Ablage, ob Vorlage und Unterschrift da sind, Gruende mit ihren Feldern."""
    return {"formulare": liste(con, lid), "vorlagen": vorlagen(con), "unterschrift": bool(unterschrift(con, lid)),
            "paraphe": bool(unterschrift(con, lid, "paraphe")),
            "gruende": [{"key": k, "name": g["name"], "felder": [{"key": fk, "name": fv[0]} for fk, fv in g["felder"].items()]}
                        for k, g in GRUENDE.items()]}


def woche_hat_formular(con, lid, datum):
    """Gibt es fuer die Woche von datum schon eine Stundenplanaenderung? (fuer die Frage „jetzt erstellen?“)"""
    montag = stundenplan.montag_von(datetime.date.fromisoformat(datum)).isoformat()
    return con.execute("SELECT 1 FROM formular WHERE lehrkraft_id = ? AND art = 'stundenplanaenderung' AND json_extract(daten, '$.woche') = ?",
                       (lid, montag)).fetchone() is not None
