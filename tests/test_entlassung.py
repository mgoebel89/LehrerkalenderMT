"""Tests fuer 0.27.0: Ausschulung mit dem Formular "Entlassung aus der Berufsschule" (app/formulare.py).

Braucht pypdf und reportlab (Paketquellen: python3-pypdf, python3-reportlab), sonst uebersprungen. Die echte
Schul-Vorlage liegt nicht im Repo; der Test baut eine Vorlage mit denselben Feldnamen. Mit
LKMT_ENTLASSUNG_VORLAGE=<pfad zur echten Vorlage> laeuft zusaetzlich ein Test gegen das Original.
"""
import base64
import datetime
import io
import os
import unittest

try:
    import pypdf
    from reportlab.pdfgen import canvas
except ImportError:
    pypdf = None

from app import beobachtungen, db, formulare, schuelerliste
from test_kollegium import MitKollegin

HEUTE = datetime.date(2026, 11, 20)


def vorlage_bauen():
    """Vorlage wie das DRS-Formular B2_6: Teil Klassenleitung (Texte, Radiogruppe, Datum) und Teil Abteilungsleitung."""
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=(595.56, 842.04))
    f = c.acroForm
    for name, x, y, b in (("TextField1", 199, 684, 179), ("TextField_2", 423, 684, 67), ("TextField_1", 199, 655, 179),
                          ("an die Schule durch1", 199, 620, 291), ("Schülerin / des  Schülers1", 199, 586, 291), ("Datum2", 71, 515, 128),
                          ("Frau / Herrn1", 145, 408, 234), ("Datum1", 72, 77, 139)):
        f.textfield(name=name, x=x, y=y, width=b, height=16)
    f.radio(name="Group1", value="0", x=199, y=562, size=11)
    f.radio(name="Group1", value="1", x=199, y=545, size=11)
    for i, y in enumerate((362, 315, 293, 258), 1):
        f.checkbox(name="Kontrollkästchen%d" % i, x=103, y=y, size=12)
    for i, y in enumerate((240, 222, 205, 174), 1):
        f.checkbox(name="Check Box%d" % i, x=132, y=y, size=8)
    c.showPage()
    c.save()
    return puffer.getvalue()


def png_bauen():
    from PIL import Image, ImageDraw
    bild = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    ImageDraw.Draw(bild).line([(5, 30), (60, 8), (115, 28)], fill=(26, 26, 26, 255), width=4)
    puffer = io.BytesIO()
    bild.save(puffer, "PNG")
    return puffer.getvalue()


def werte(pdf):
    felder = pypdf.PdfReader(io.BytesIO(pdf)).get_fields()
    return {k: v.get("/V") for k, v in felder.items()}


@unittest.skipIf(pypdf is None, "pypdf/reportlab fehlen")
class Ausschulung(MitKollegin):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            formulare.vorlage_setzen(self.con, "entlassung", vorlage_bauen(), "entlassung.pdf")
            formulare.unterschrift_setzen(self.con, self.rid, "unterschrift", "data:image/png;base64," + base64.b64encode(png_bauen()).decode())
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
        self.rei = dict(self.con.execute("SELECT * FROM lehrkraft WHERE id = ?", (self.rid,)).fetchone())

    def ausschulen(self, **mehr):
        daten = dict({"schueler_id": self.clara, "klassenlehrer": "Kollege Reiter", "mitteilung": "Ausbildungsbetrieb",
                      "mitteilung_zusatz": "telefonisch am 18.11.", "letzter_tag": "2026-11-18", "leistung": "nicht_moeglich",
                      "datum": "2026-11-20", "grund": "Ausbildungsverhältnis gelöst"}, **mehr)
        with db.transaktion(self.con):
            return formulare.entlassung_erstellen(self.con, self.rei, daten, heute=HEUTE)

    def test_vorlage_braucht_die_felder(self):
        with self.assertRaises(formulare.FormularFehler):          # Stundenplan-Vorlage passt nicht als Entlassung
            from test_formulare import vorlage_bauen as falsche
            formulare.vorlage_setzen(self.con, "entlassung", falsche())
        self.assertIn("entlassung", formulare.vorlagen(self.con))

    def test_vorschlag(self):
        v = formulare.entlassung_vorschlag(self.con, self.rei, self.clara, heute=HEUTE)
        self.assertEqual((v["schueler"]["name"], v["schueler"]["klasse"], v["klassenlehrer"]), ("Weiß, Clara", "BSMT 24a", "Kollege Reiter"))
        self.assertEqual(v["letzter_tag"], "2026-11-18")           # rei hat 24a mittwochs
        self.assertTrue(v["vorlage"])

    def test_formular_gefuellt_rest_bleibt_ausfuellbar(self):
        fid = self.ausschulen()
        pdf, name = formulare.pdf_von(self.con, self.rid, fid)
        w = werte(pdf)
        self.assertEqual((w["TextField1"], w["TextField_2"], w["TextField_1"]), ("Weiß, Clara", "BSMT 24a", "Kollege Reiter"))
        self.assertEqual(w["an die Schule durch1"], "Ausbildungsbetrieb, telefonisch am 18.11.")
        self.assertEqual((w["Schülerin / des  Schülers1"], w["Datum2"]), ("18.11.2026", "20.11.2026"))
        self.assertEqual(w["Group1"], "/1")                         # nicht moeglich
        self.assertIn(w.get("Frau / Herrn1"), (None, ""))           # Teil Abteilungsleitung leer
        felder = pypdf.PdfReader(io.BytesIO(pdf)).get_fields()
        self.assertIn("Kontrollkästchen1", felder)                  # Formular bleibt ein Formular
        self.assertTrue(name.startswith("Entlassung Weiß Clara"))
        self.assertIn(b"/Image", pdf)                               # Unterschrift als Bild
        f = formulare.liste(self.con, self.rid)[0]
        self.assertEqual((f["artname"], f["betrifft"]), ("Entlassung aus der Berufsschule", "Weiß, Clara · BSMT 24a · letzter Tag 18.11.2026"))

    def test_schueler_ausgetragen_und_grund_privat(self):
        self.ausschulen()
        z = self.con.execute("SELECT aktiv, entlassen_zum, entlassen_von FROM schueler WHERE id = ?", (self.clara,)).fetchone()
        self.assertEqual(tuple(z), (0, "2026-11-18", self.rid))      # letzter Tag vorbei: sofort nicht mehr in der Klasse
        e = beobachtungen.verlauf(self.con, self.rid, self.clara)["eintraege"]
        self.assertEqual([(x["kategorie"], x["text"]) for x in e], [("Sonstiges", "Ausschulung zum 18.11.2026: Ausbildungsverhältnis gelöst")])
        self.assertEqual(beobachtungen.verlauf(self.con, self.lid, self.clara)["eintraege"], [])   # Grund nur bei rei
        with self.assertRaises(formulare.FormularFehler):          # nicht zweimal
            self.ausschulen()

    def test_letzter_tag_in_der_zukunft(self):
        self.ausschulen(letzter_tag="2026-11-27", grund="")
        self.assertEqual(self.con.execute("SELECT aktiv FROM schueler WHERE id = ?", (self.clara,)).fetchone()[0], 1)
        schuelerliste.entlassungen_nachziehen(self.con, datetime.date(2026, 11, 27))
        self.assertEqual(self.con.execute("SELECT aktiv FROM schueler WHERE id = ?", (self.clara,)).fetchone()[0], 1)   # bis einschl.
        schuelerliste.entlassungen_nachziehen(self.con, datetime.date(2026, 11, 28))
        self.assertEqual(self.con.execute("SELECT aktiv FROM schueler WHERE id = ?", (self.clara,)).fetchone()[0], 0)

    def test_hinweis_fuers_kollegium(self):
        self.ausschulen()
        h = schuelerliste.entlassungen_im_kollegium(self.con, self.lid, HEUTE)
        self.assertEqual(h, [{"name": "Weiß, Clara", "klasse": "BSMT 24a", "zum": "2026-11-18", "von": "Kollege Reiter"}])
        self.assertEqual(schuelerliste.entlassungen_im_kollegium(self.con, self.rid, HEUTE), [])          # nicht fuer mich selbst
        self.assertEqual(schuelerliste.entlassungen_im_kollegium(self.con, self.lid, datetime.date(2026, 12, 31)), [])   # nach 2 Wochen weg

    def test_loeschen_mit_und_ohne_reaktivieren(self):
        fid = self.ausschulen()
        with db.transaktion(self.con):
            formulare.loeschen(self.con, self.rid, fid)
        self.assertEqual(self.con.execute("SELECT aktiv FROM schueler WHERE id = ?", (self.clara,)).fetchone()[0], 0)
        with db.transaktion(self.con):                                  # von Hand wieder in die Klasse: Ausschulung entfaellt
            schuelerliste.speichern(self.con, self.rid, {"nachname": "Weiß", "vorname": "Clara", "aktiv": True}, self.clara)
        self.assertEqual(tuple(self.con.execute("SELECT aktiv, entlassen_zum FROM schueler WHERE id = ?", (self.clara,)).fetchone()), (1, None))
        fid = self.ausschulen()
        with db.transaktion(self.con):
            formulare.loeschen(self.con, self.rid, fid, reaktivieren=True)
        self.assertEqual(tuple(self.con.execute("SELECT aktiv, entlassen_zum FROM schueler WHERE id = ?", (self.clara,)).fetchone()), (1, None))

    def test_eingaben(self):
        for falsch in ({"mitteilung": "Wahrsagerin"}, {"leistung": "vielleicht"}, {"letzter_tag": ""}, {"klassenlehrer": " "},
                       {"schueler_id": 9999}):
            with self.assertRaises(formulare.FormularFehler):
                self.ausschulen(**falsch)
        fid = self.ausschulen(mitteilung="Sonstige", mitteilung_zusatz="Berufsberatung", grund="")
        self.assertEqual(werte(formulare.pdf_von(self.con, self.rid, fid)[0])["an die Schule durch1"], "Berufsberatung")

    @unittest.skipUnless(os.environ.get("LKMT_ENTLASSUNG_VORLAGE"), "LKMT_ENTLASSUNG_VORLAGE nicht gesetzt")
    def test_echte_vorlage(self):
        with open(os.environ["LKMT_ENTLASSUNG_VORLAGE"], "rb") as f:
            with db.transaktion(self.con):
                formulare.vorlage_setzen(self.con, "entlassung", f.read(), "Entlassung_Berufsschule.pdf")
        fid = self.ausschulen(leistung="moeglich")
        pdf, _ = formulare.pdf_von(self.con, self.rid, fid)
        w = werte(pdf)
        self.assertEqual((w["TextField1"], w["Group1"]), ("Weiß, Clara", "/0"))
        ziel = os.environ.get("LKMT_ENTLASSUNG_AUSGABE")
        if ziel:
            with open(ziel, "wb") as f:
                f.write(pdf)
