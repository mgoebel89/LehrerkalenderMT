"""Fotos zu Schuelern (0.25.0).

Ein Foto je Schueler, gemeinsam fuer alle Lehrkraefte der Klasse (wie die Schuelerliste, app/schuelerliste.py). Der
Browser schneidet das Bild zu und verkleinert es (Hochformat 4:5, etwa 400 x 500 Pixel, JPEG); der Server prueft nur,
dass es ein lesbares JPEG in vernuenftiger Groesse ist. Fotos stehen in der Datenbank und sind damit in jeder
Sicherung. Sie bleiben, bis jemand sie loescht (auch bei "nicht mehr in der Klasse").

Fotoliste der Klasse als PDF im DRS-Design (Logo, feine Linie, Farbband im Fuss), mit dem eigenen PDF-Schreiber.
"""
import base64
import datetime

from . import db, exporte, pdf, schuelerliste
from .pdf import A4, MM, Seite, kuerzen, textbreite

MAX_BYTES = 600 * 1024
MAX_KANTE = 2000


def _jpeg(daten):
    """data:image/jpeg;base64,... oder reines Base64 -> Bytes; nur lesbare JPEGs in vernuenftiger Groesse."""
    if not isinstance(daten, str) or not daten:
        raise schuelerliste.SchuelerFehler("Kein Foto übertragen.")
    if daten.startswith("data:"):
        kopf, _, daten = daten.partition(",")
        if "image/jpeg" not in kopf:
            raise schuelerliste.SchuelerFehler("Das Foto muss ein JPEG sein.")
    try:
        roh = base64.b64decode(daten, validate=True)
    except (ValueError, TypeError):
        raise schuelerliste.SchuelerFehler("Das Foto ist beschädigt.")
    if len(roh) > MAX_BYTES:
        raise schuelerliste.SchuelerFehler("Das Foto ist zu groß (höchstens %d KB)." % (MAX_BYTES // 1024))
    masse = pdf.jpeg_masse(roh)
    if not masse or max(masse[0], masse[1]) > MAX_KANTE:
        raise schuelerliste.SchuelerFehler("Das Foto ist kein lesbares JPEG.")
    return roh


def setzen(con, lid, sid, daten):
    schuelerliste.zeile(con, lid, sid)
    con.execute("UPDATE schueler SET foto = ?, foto_geaendert = ? WHERE id = ?", (_jpeg(daten), db.jetzt(), sid))


def loeschen(con, lid, sid):
    schuelerliste.zeile(con, lid, sid)
    con.execute("UPDATE schueler SET foto = NULL, foto_geaendert = ? WHERE id = ?", (db.jetzt(), sid))


def holen(con, lid, sid):
    """JPEG-Bytes oder None."""
    return schuelerliste.zeile(con, lid, sid)["foto"]


# --- Fotoliste als PDF ---

SPALTEN, BILD_B = 5, 31 * MM
BILD_H = BILD_B * 5 / 4


def fotoliste_pdf(con, lid, kid, lehrkraft=""):
    """Alle Schueler der Klasse (in der Klasse) mit Foto und Namen, fuenf je Zeile (20 je Seite). Rueckgabe (pdf, dateiname)."""
    liste = schuelerliste.liste(con, lid, kid, nur_aktive=True)
    if not liste:
        raise schuelerliste.SchuelerFehler("In dieser Klasse gibt es noch keine Schüler.")
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (kid,)).fetchone()["name"]
    bilder = {z["id"]: z["foto"] for z in con.execute("SELECT id, foto FROM schueler WHERE klasse_id = ? AND foto IS NOT NULL", (kid,))}
    kd = exporte._kopfdaten(con)
    b, h = A4
    seiten = []
    luecke = (b - 30 * MM - SPALTEN * BILD_B) / (SPALTEN - 1)
    zeilen_hoehe = BILD_H + 12 * MM
    y = 0
    for i, s in enumerate(liste):
        if not seiten or y - zeilen_hoehe < 24 * MM and i % SPALTEN == 0:
            seite = Seite()
            seiten.append(seite)
            y = kopf(seite, kd, klasse, "Fotoliste " + klasse, "%d Schüler · %d mit Foto · nur für den Dienstgebrauch" % (len(liste), len(bilder)))
        spalte = i % SPALTEN
        x = 15 * MM + spalte * (BILD_B + luecke)
        oben = y
        foto = bilder.get(s["id"])
        if foto:
            seite.bild(foto, x, oben - BILD_H, BILD_B, BILD_H)
        else:
            seite.rechteck(x, oben - BILD_H, BILD_B, BILD_H, exporte.HELL)
            kuerzel = (s["vorname"][:1] + s["nachname"][:1]).upper() or "?"
            seite.text(x + (BILD_B - textbreite(kuerzel, 22, True)) / 2, oben - BILD_H / 2 - 3 * MM, kuerzel, 22, True, exporte.LEISE)
        seite.text(x, oben - BILD_H - 4.5 * MM, kuerzen(s["nachname"], 9, BILD_B, True), 9, True)
        seite.text(x, oben - BILD_H - 8.5 * MM, kuerzen(s["vorname"], 8.5, BILD_B), 8.5, farbe=exporte.LEISE)
        if spalte == SPALTEN - 1:
            y -= zeilen_hoehe
    for nr, seite in enumerate(seiten, 1):
        exporte._fuss(seite, nr, len(seiten), lehrkraft, kd)
    name = "Fotoliste %s %s.pdf" % (klasse, datetime.date.today().isoformat())
    return pdf.dokument(seiten, titel="Fotoliste " + klasse), name


def kopf(seite, kd, rechts_oben, titel, unterzeile):
    """DRS-Kopf wie bei den Ergebnislisten: Logo links, rechts oben Klasse und Stand, feine Linie, Titel und Unterzeile.
    Rueckgabe: y unter dem Kopf. Auch fuer die Beobachtungs-PDFs (app/beobachtungen.py)."""
    b, h = A4
    oben = h - 12 * MM
    hoehe = 7 * MM
    if kd["logo"] and kd["masse"]:
        bp, hp = kd["masse"]
        hoehe = 15 * MM
        breite = hoehe * bp / hp
        if breite > 75 * MM:
            breite = 75 * MM
            hoehe = breite * hp / bp
        seite.bild(kd["logo"], 15 * MM, oben - hoehe, breite, hoehe)
    else:
        seite.text(15 * MM, oben - 5 * MM, kuerzen(kd["name"], 12, 100 * MM, True), 12, True, exporte.BLAU)
    exporte._rechts(seite, b - 15 * MM, oben - 3.5 * MM, kuerzen(rechts_oben, 9.5, 90 * MM, True), 9.5, True)
    exporte._rechts(seite, b - 15 * MM, oben - 8.5 * MM, "Stand %s" % datetime.date.today().strftime("%d.%m.%Y"), 9, farbe=exporte.LEISE)
    linie = oben - max(hoehe, 15 * MM) - 4 * MM
    seite.linie(15 * MM, linie, b - 15 * MM, linie, (0.88, 0.88, 0.88), 0.5)
    seite.text(15 * MM, linie - 10 * MM, kuerzen(titel, 17, b - 30 * MM, True), 17, True)
    seite.text(15 * MM, linie - 16 * MM, kuerzen(unterzeile, 9, b - 30 * MM), 9, farbe=exporte.LEISE)
    return linie - 24 * MM
