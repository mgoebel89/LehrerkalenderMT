"""Stufe F1: Formularcenter mit Ablage und Status (erstellt, abgegeben, genehmigt) und die Unterschrift je Konto.
Zweites Formular (0.27.0): Entlassung aus der Berufsschule (Ausschulung), siehe unten.

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

ARTEN = {"stundenplanaenderung": "Stundenplanänderung / Beurlaubung", "entlassung": "Entlassung aus der Berufsschule"}
STAENDE = ("erstellt", "abgegeben", "genehmigt")
WOCHENTAGE_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]
BLOCK_ZEILEN = [(0, 1), (2, 3), (4, 5), (6, 7), (10, 11), (12, 13)]
PFLICHTFELDER = {"stundenplanaenderung": ("Antragsteller1", "Unterschrift der Lehrperson1", "am  von1", "bis1"),
                 "entlassung": ("TextField1", "TextField_2", "TextField_1", "an die Schule durch1", "Schülerin / des  Schülers1",
                                "Group1", "Datum2")}

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
    fehlen = [f for f in PFLICHTFELDER[art] if f not in felder]
    if fehlen:
        raise FormularFehler("Das ist nicht das erwartete DRS-Formular (es fehlen Felder wie „%s“)." % fehlen[0])
    con.execute("INSERT INTO formularvorlage (art, pdf, name, hochgeladen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (art) DO UPDATE SET pdf = excluded.pdf, name = excluded.name, hochgeladen = excluded.hochgeladen",
                (art, inhalt, (name or "")[:200], db.jetzt()))
    _karte.cache.clear()


def _wert(x):
    """Indirekte PDF-Objekte aufloesen (aeltere pypdf-Versionen liefern /Annots, /Fields, /Kids als Verweis)."""
    return x.get_object() if hasattr(x, "get_object") else x


def _liste(x):
    x = _wert(x)
    return list(x) if x else []


def _widgets(reader):
    aus = []
    for a in _liste(reader.pages[0].get("/Annots")):
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
    for f in _liste(_wert(acro).get("/Fields")):
        obj = f.get_object()
        name = obj.get("/T")
        if name is None or str(name) not in staende:
            continue
        ziel = staende[str(name)]
        obj[NameObject("/V")] = NameObject(ziel)
        kinder = _liste(obj.get("/Kids"))
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
    for a in _liste(writer.pages[0].get("/Annots")):
        o = a.get_object()
        eltern = o.get("/Parent")
        nm = o.get("/T") or (eltern.get_object().get("/T") if eltern else None)
        if nm is None or str(nm) not in namen:
            continue
        da = o.get("/DA") or (eltern.get_object().get("/DA") if eltern else None)
        neu = re.sub(r"(/\S+)\s+[\d.]+\s+Tf", r"\1 0 Tf", str(da), count=1) if da else "/Cali 0 Tf 0 0.388235 0.611765 rg"
        o[NameObject("/DA")] = TextStringObject(neu)


def _unterschrift_overlay(bild, karte, hoehe_max=None):
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
    hoehe_max = hoehe_max or min(20.0, max(10.0, 146.0 - unten))
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


def im_zeitraum(ae, von=None, bis=None):
    """Nur die Stunden zwischen von und bis (je einschliesslich); ohne Angabe gilt die ganze Woche."""
    eintraege = [e for e in ae["eintraege"] if (not von or e["datum"] >= von) and (not bis or e["datum"] <= bis)]
    tage = sorted({e["datum"] for e in eintraege})
    return dict(ae, eintraege=eintraege, von=tage[0] if tage else None, bis=tage[-1] if tage else None)


def ausfuellen(con, konto, montag, grund, felder, von=None, bis=None, aenderungen=None, heute=None):
    """Befuellte Stundenplanaenderung als PDF-Bytes."""
    pdf_vorlage = vorlage(con)
    if not pdf_vorlage:
        raise FormularFehler("Die Schul-Vorlage für die Stundenplanänderung fehlt noch. Der Admin lädt sie unter Grunddaten → Schule und Logo hoch.")
    if grund not in GRUENDE:
        raise FormularFehler("Bitte eine Begründung wählen.")
    pypdf = _pypdf()
    ae = im_zeitraum(aenderungen or woche_aenderungen(con, konto["id"], montag), von, bis)
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
    ae = im_zeitraum(woche_aenderungen(con, konto["id"], montag), von, bis)
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
    if z["art"] == "entlassung":
        return bytes(z["pdf"]), "Entlassung %s.pdf" % z["betrifft"].split(" · ")[0].replace(",", "")
    return bytes(z["pdf"]), "%s %s.pdf" % ("Stundenplanaenderung", z["von"] or "")


def stand_setzen(con, lid, fid, stand):
    _formular(con, lid, fid)
    if stand not in STAENDE:
        raise FormularFehler("Unbekannter Stand.")
    con.execute("UPDATE formular SET stand = ?, geaendert = ? WHERE id = ?", (stand, db.jetzt(), fid))


def loeschen(con, lid, fid, reaktivieren=False):
    """Formular loeschen. Bei einer Entlassung mit reaktivieren=True ist der Schueler danach wieder in der Klasse."""
    z = _formular(con, lid, fid)
    if z["art"] == "entlassung" and reaktivieren:
        sid = json.loads(z["daten"] or "{}").get("schueler_id")
        if sid and con.execute("SELECT 1 FROM schueler WHERE id = ?", (sid,)).fetchone():
            con.execute("UPDATE schueler SET aktiv = 1, entlassen_zum = NULL, entlassen_von = NULL WHERE id = ?", (sid,))
    con.execute("DELETE FROM formular WHERE id = ?", (fid,))


def uebersicht(con, lid):
    """Fuer das Formularcenter: Ablage, ob Vorlage und Unterschrift da sind, Gruende mit ihren Feldern."""
    return {"formulare": liste(con, lid), "vorlagen": vorlagen(con), "unterschrift": bool(unterschrift(con, lid)),
            "mitteilung_durch": MITTEILUNG_DURCH,
            "paraphe": bool(unterschrift(con, lid, "paraphe")),
            "gruende": [{"key": k, "name": g["name"], "felder": [{"key": fk, "name": fv[0]} for fk, fv in g["felder"].items()]}
                        for k, g in GRUENDE.items()]}


def woche_hat_formular(con, lid, datum):
    """Gibt es fuer die Woche von datum schon eine Stundenplanaenderung? (fuer die Frage „jetzt erstellen?“)"""
    montag = stundenplan.montag_von(datetime.date.fromisoformat(datum)).isoformat()
    return con.execute("SELECT 1 FROM formular WHERE lehrkraft_id = ? AND art = 'stundenplanaenderung' AND json_extract(daten, '$.woche') = ?",
                       (lid, montag)).fetchone() is not None


# --- Entlassung aus der Berufsschule (0.27.0) ---
# Die Schul-Vorlage (AcroForm, 17 Felder) laedt der Admin hoch. Gefuellt wird nur der Teil Klassenleitung; der Teil
# Abteilungsleitung (Frau/Herrn, Kaestchen 1-1.2, Termin) bleibt leer und im PDF-Reader ausfuellbar. Die Unterschrift
# kommt als Bild auf die Linie "Unterschrift der Lehrperson" (Koordinaten aus der Vorlage, Stand 06/01/2024 B2_6).

MITTEILUNG_DURCH = ["Ausbildungsbetrieb", "Schüler/in selbst", "Eltern", "Kammer (IHK/HWK)", "Agentur für Arbeit", "Sonstige"]
ENTLASSUNG_FELDER = {"name": "TextField1", "klasse": "TextField_2", "klassenlehrer": "TextField_1",
                     "mitteilung": "an die Schule durch1", "letzter_tag": "Schülerin / des  Schülers1", "datum": "Datum2"}
_LEISTUNG = {"moeglich": "/0", "nicht_moeglich": "/1"}
_ENTLASSUNG_UNTERSCHRIFT = {"seite": (595.56, 842.04), "unterschrift": (292.0, 519.0, 486.0, 548.0)}


def _datum_de(iso):
    return datetime.date.fromisoformat(iso).strftime("%d.%m.%Y")


def letzte_stunde(con, lid, kid, heute=None):
    """Letzter Tag bis heute, an dem die Lehrkraft die Klasse laut Wochenplan hatte (gehalten oder vertreten); sonst heute."""
    heute = heute or db.heute()
    tag = heute
    for _ in range(10):
        w = stundenplan.woche(con, lid, tag)
        tage = [b["datum"] for b in w["bloecke"] if b["klasse"] and b["klasse"]["id"] == kid and b["datum"] <= heute.isoformat()
                and b["zustand"] in (None, "vertreten")]
        if tage:
            return max(tage)
        tag -= datetime.timedelta(days=7)
    return heute.isoformat()


def entlassung_vorschlag(con, konto, sid, heute=None):
    """Vorbelegung des Dialogs: Schueler, Klasse, Klassenlehrer(in) = ich, letzter Unterrichtstag, Datum heute."""
    from . import schuelerliste
    try:
        s = schuelerliste.zeile(con, konto["id"], sid)
    except schuelerliste.SchuelerFehler as f:
        raise FormularFehler(str(f))
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (s["klasse_id"],)).fetchone()["name"]
    return {"schueler": {"id": s["id"], "name": s["nachname"] + (", " + s["vorname"] if s["vorname"] else ""), "klasse": klasse,
                         "aktiv": bool(s["aktiv"]), "entlassen_zum": s["entlassen_zum"]},
            "klassenlehrer": konto["name"], "letzter_tag": letzte_stunde(con, konto["id"], s["klasse_id"], heute),
            "datum": (heute or db.heute()).isoformat(), "mitteilung_durch": MITTEILUNG_DURCH, "vorlage": bool(vorlage(con, "entlassung"))}


def entlassung_ausfuellen(con, konto, werte_):
    """Befuellte Entlassung als PDF-Bytes. werte_: name, klasse, klassenlehrer, mitteilung, letzter_tag, datum (Texte),
    leistung ('moeglich'/'nicht_moeglich')."""
    pdf_vorlage = vorlage(con, "entlassung")
    if not pdf_vorlage:
        raise FormularFehler("Die Schul-Vorlage „Entlassung aus der Berufsschule“ fehlt noch. Der Admin lädt sie unter Grunddaten → Schule und Logo hoch.")
    pypdf = _pypdf()
    reader = pypdf.PdfReader(io.BytesIO(pdf_vorlage))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    seite = writer.pages[0]
    writer.update_page_form_field_values(seite, {ENTLASSUNG_FELDER[k]: v for k, v in werte_.items() if k in ENTLASSUNG_FELDER},
                                         auto_regenerate=False)
    _knopf_staende(writer, {"Group1": _LEISTUNG[werte_["leistung"]]})
    # Ohne NeedAppearances: pypdf hat die Texte schon gezeichnet, die Auswahlkreise behalten das Aussehen der Vorlage.
    # Die leeren Felder der Abteilungsleitung zeichnet der PDF-Reader beim Ausfuellen selbst.
    bild = unterschrift(con, konto["id"])
    if bild:
        overlay = _unterschrift_overlay(bild, _ENTLASSUNG_UNTERSCHRIFT, hoehe_max=26.0)
        if overlay is not None:
            seite.merge_page(overlay)
    puffer = io.BytesIO()
    writer.write(puffer)
    return puffer.getvalue()


def entlassung_erstellen(con, konto, daten, heute=None):
    """Entlassung erzeugen und ablegen, Schueler austragen (ab dem Tag nach dem letzten Unterrichtstag nicht mehr in der
    Klasse), optional den Grund als private Beobachtung festhalten. daten: schueler_id, klassenlehrer, mitteilung (Art),
    mitteilung_zusatz, letzter_tag, leistung, datum, grund. Rueckgabe: id des Formulars."""
    from . import beobachtungen, schuelerliste
    heute = heute or db.heute()
    try:
        sid = int(daten.get("schueler_id"))
        s = schuelerliste.zeile(con, konto["id"], sid)
    except (TypeError, ValueError, schuelerliste.SchuelerFehler):
        raise FormularFehler("Bitte einen Schüler wählen.")
    if s["entlassen_zum"]:
        raise FormularFehler("Für diesen Schüler gibt es schon eine Ausschulung zum %s." % _datum_de(s["entlassen_zum"]))
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (s["klasse_id"],)).fetchone()["name"]
    name = s["nachname"] + (", " + s["vorname"] if s["vorname"] else "")
    lehrer = str(daten.get("klassenlehrer") or "").strip()[:80]
    if not lehrer:
        raise FormularFehler("Bitte die Klassenleitung angeben.")
    art = daten.get("mitteilung")
    if art not in MITTEILUNG_DURCH:
        raise FormularFehler("Bitte wählen, wer den Grund mitgeteilt hat.")
    zusatz = str(daten.get("mitteilung_zusatz") or "").strip()[:120]
    mitteilung = art + (", " + zusatz if zusatz else "") if art != "Sonstige" else (zusatz or "Sonstige")
    leistung = daten.get("leistung")
    if leistung not in _LEISTUNG:
        raise FormularFehler("Bitte wählen, ob eine Leistungsbeurteilung möglich ist.")
    try:
        letzter = datetime.date.fromisoformat(str(daten.get("letzter_tag") or ""))
        datum = datetime.date.fromisoformat(str(daten.get("datum") or heute.isoformat()))
    except ValueError:
        raise FormularFehler("Bitte den letzten Unterrichtstag und das Datum angeben.")
    pdf = entlassung_ausfuellen(con, konto, {"name": name, "klasse": klasse, "klassenlehrer": lehrer, "mitteilung": mitteilung,
                                             "letzter_tag": letzter.strftime("%d.%m.%Y"), "datum": datum.strftime("%d.%m.%Y"),
                                             "leistung": leistung})
    con.execute("UPDATE schueler SET entlassen_zum = ?, entlassen_von = ?, aktiv = CASE WHEN ? < ? THEN 0 ELSE aktiv END WHERE id = ?",
                (letzter.isoformat(), konto["id"], letzter.isoformat(), heute.isoformat(), sid))
    grund = str(daten.get("grund") or "").strip()
    if grund:
        beobachtungen.anlegen(con, konto["id"], {"schueler_ids": [sid], "datum": datum.isoformat(), "kategorie": "Sonstiges",
                                                 "tendenz": "neutral", "text": "Ausschulung zum %s: %s" % (letzter.strftime("%d.%m.%Y"), grund)})
    jetzt = db.jetzt()
    betrifft = "%s · %s · letzter Tag %s" % (name, klasse, letzter.strftime("%d.%m.%Y"))
    return con.execute("INSERT INTO formular (lehrkraft_id, art, betrifft, von, bis, daten, pdf, stand, erstellt, geaendert) "
                       "VALUES (?, 'entlassung', ?, ?, ?, ?, ?, 'erstellt', ?, ?)",
                       (konto["id"], betrifft, letzter.isoformat(), letzter.isoformat(),
                        json.dumps({"schueler_id": sid, "klassenlehrer": lehrer, "mitteilung": mitteilung, "leistung": leistung,
                                    "datum": datum.isoformat()}, ensure_ascii=False), pdf, jetzt, jetzt)).lastrowid
