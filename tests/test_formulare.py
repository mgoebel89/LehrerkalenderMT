"""Stufe F1: Formularcenter - Stundenplanaenderung aus den Ausfaellen der Woche, Unterschrift, Ablage mit Stand.

Braucht pypdf und reportlab (Paketquellen: python3-pypdf, python3-reportlab), sonst uebersprungen. Die echte
Schul-Vorlage liegt nicht im Repo; der Test baut eine Vorlage mit denselben Feldnamen und derselben Geometrie.
Mit LKMT_FORMULAR_VORLAGE=<pfad zur echten Vorlage> laeuft zusaetzlich ein Test gegen das Original.
"""
import base64
import io
import os
import shutil
import tempfile
import unittest

try:
    import pypdf
    from reportlab.pdfgen import canvas
except ImportError:
    pypdf = None

from app import db, formulare, grunddaten, konten, stundenplan



def png_bauen():
    """Kleine Unterschrift als PNG mit Transparenz (wie aus dem Zeichenfeld)."""
    from PIL import Image, ImageDraw
    bild = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    ImageDraw.Draw(bild).line([(5, 30), (60, 8), (115, 28)], fill=(26, 26, 26, 255), width=4)
    puffer = io.BytesIO()
    bild.save(puffer, "PNG")
    return puffer.getvalue()


def vorlage_bauen():
    """Vorlage wie das DRS-Formular: Kopf-, Begruendungs- und Tabellenfelder (6 Tage x Klasse/Vertretung x 14 Zeilen)."""
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=(595, 842))
    f = c.acroForm
    for name, x, y in (("Antragsteller1", 120, 760), ("am  von1", 120, 740), ("bis1", 300, 740), ("Datum1", 120, 100),
                       ("Fortbildung in1", 120, 600), ("Thema1", 300, 600), ("Antrag bei SL am1", 450, 600)):
        f.textfield(name=name, x=x, y=y, width=150, height=14)
    for i in range(1, 7):
        f.checkbox(name="Check Box%d" % i, x=40, y=700 - 15 * i, size=10)
    f.radio(name="Group1", value="0", x=40, y=340, size=10, selected=True)
    f.radio(name="Group1", value="1", x=80, y=340, size=10)
    n = 0
    for zeile in range(14):
        y = 310 - zeile * 11.5
        for spalte in range(12):
            n += 1
            f.textfield(name="M%d" % n, x=120 + spalte * 38, y=y, width=34, height=10)
    f.textfield(name="Unterschrift der Lehrperson1", x=250, y=120, width=341, height=18)
    c.showPage()
    c.save()
    return puffer.getvalue()


@unittest.skipIf(pypdf is None, "pypdf/reportlab fehlen")
class Formularcenter(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"},
                                                             {"bezeichnung": "2. Block", "beginn": "09:30", "ende": "11:00"}])
            self.kl = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": bs})
            v = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2026-08-01"})
            for tag, beginn, ende in ((1, "07:45", "09:15"), (4, "09:30", "11:00")):
                stundenplan.feld_setzen(self.con, self.lid, v, {"wochentag": tag, "beginn": beginn, "ende": ende, "eintraege": [{"klasse_id": self.kl}]})
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-16", "beginn": "07:45", "grund": "Fortbildung"})
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "vertreten", "datum": "2026-11-19", "beginn": "09:30", "wer": "Kollege R.",
                                                               "thema_weiter": True})

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @property
    def lid(self):
        return self.k["id"]

    def felder(self, pdf):
        r = pypdf.PdfReader(io.BytesIO(pdf))
        return {k: v.get("/V") for k, v in (r.get_fields() or {}).items()}

    def test_woche_aenderungen(self):
        ae = formulare.woche_aenderungen(self.con, self.lid, "2026-11-18")
        self.assertEqual((ae["montag"], ae["von"], ae["bis"]), ("2026-11-16", "2026-11-16", "2026-11-19"))
        self.assertEqual([(e["tag"], e["block"], e["klasse"], e["vertretung"]) for e in ae["eintraege"]],
                         [(0, 0, "BSMT 24a", "entfällt, Klasse informiert"), (3, 1, "BSMT 24a", "Kollege R.")])

    def test_ohne_vorlage_und_vorlage_pruefen(self):
        with self.assertRaises(formulare.FormularFehler):
            formulare.erstellen(self.con, self.k, {"woche": "2026-11-16", "grund": "fortbildung"})
        with self.assertRaises(formulare.FormularFehler):          # kein PDF
            formulare.vorlage_setzen(self.con, "stundenplanaenderung", "data:application/pdf;base64," + base64.b64encode(b"nein").decode())
        puffer = io.BytesIO()
        c = canvas.Canvas(puffer)
        c.drawString(100, 100, "falsches Formular")
        c.save()
        with self.assertRaises(formulare.FormularFehler):          # PDF ohne die Felder
            formulare.vorlage_setzen(self.con, "stundenplanaenderung", puffer.getvalue())

    def test_erstellen_ablage_stand(self):
        formulare.vorlage_setzen(self.con, "stundenplanaenderung", vorlage_bauen(), "Vorlage.pdf")
        formulare.unterschrift_setzen(self.con, self.lid, "unterschrift", "data:image/png;base64," + base64.b64encode(png_bauen()).decode())
        fid = formulare.erstellen(self.con, self.k, {"woche": "2026-11-18", "grund": "fortbildung",
                                                     "felder": {"ort": "Koblenz", "thema": "SPS S7-1500"}})
        f = formulare.liste(self.con, self.lid)[0]
        self.assertEqual((f["id"], f["stand"], f["von"], f["bis"]), (fid, "erstellt", "2026-11-16", "2026-11-19"))
        self.assertEqual(f["betrifft"], "Mo 16.11. – Do 19.11. · Fortbildung SPS S7-1500 · 2 Blöcke")
        pdf, name = formulare.pdf_von(self.con, self.lid, fid)
        werte = self.felder(pdf)
        self.assertEqual((werte["Antragsteller1"], werte["am  von1"], werte["bis1"], werte["Fortbildung in1"]),
                         ("Matthias Göbel", "Mo, 16.11.2026", "Do, 19.11.2026", "Koblenz"))
        tabelle = {v for k, v in werte.items() if k.startswith("M") and v}
        self.assertEqual(tabelle, {"BSMT 24a", "entfällt, Klasse informiert", "Kollege R."})
        self.assertEqual((werte["Check Box4"], werte["Group1"]), ("/Ja", "/1"))
        self.assertIn(b"/XObject", pdf)                               # Unterschrift als Bild aufgelegt
        formulare.stand_setzen(self.con, self.lid, fid, "abgegeben")
        self.assertEqual(formulare.liste(self.con, self.lid)[0]["stand"], "abgegeben")
        with self.assertRaises(formulare.FormularFehler):
            formulare.stand_setzen(self.con, self.lid, fid, "irgendwas")
        self.assertTrue(formulare.woche_hat_formular(self.con, self.lid, "2026-11-20"))
        formulare.loeschen(self.con, self.lid, fid)
        self.assertEqual(formulare.liste(self.con, self.lid), [])

    def test_ohne_stunden_mit_eigenem_zeitraum(self):
        formulare.vorlage_setzen(self.con, "stundenplanaenderung", vorlage_bauen())
        fid = formulare.erstellen(self.con, self.k, {"woche": "2026-11-23", "grund": "beurlaubung", "von": "2026-11-24", "bis": "2026-11-24"})
        werte = self.felder(formulare.pdf_von(self.con, self.lid, fid)[0])
        self.assertEqual((werte["am  von1"], werte["Group1"]), ("Di, 24.11.2026", "/0"))   # keine Stunden: „nicht erforderlich“

    def test_nur_stunden_im_gewaehlten_zeitraum(self):
        """Gewaehlt Mo-Mi: die Vertretung am Donnerstag gehoert nicht ins Formular (so im Test-CT gemeldet)."""
        formulare.vorlage_setzen(self.con, "stundenplanaenderung", vorlage_bauen())
        fid = formulare.erstellen(self.con, self.k, {"woche": "2026-11-16", "grund": "sonstige", "von": "2026-11-16", "bis": "2026-11-18"})
        werte = self.felder(formulare.pdf_von(self.con, self.lid, fid)[0])
        tabelle = {v for k, v in werte.items() if k.startswith("M") and v}
        self.assertEqual(tabelle, {"BSMT 24a", "entfällt, Klasse informiert"})       # nur der Ausfall am Montag
        f = formulare.liste(self.con, self.lid)[0]
        self.assertEqual((f["von"], f["bis"], f["betrifft"].endswith("1 Block")), ("2026-11-16", "2026-11-18", True))

    @unittest.skipUnless(os.environ.get("LKMT_FORMULAR_VORLAGE"), "echte Vorlage nicht angegeben")
    def test_echte_vorlage(self):
        formulare.vorlage_setzen(self.con, "stundenplanaenderung", open(os.environ["LKMT_FORMULAR_VORLAGE"], "rb").read())
        karte = formulare._karte(formulare.vorlage(self.con))
        self.assertEqual(len(karte["tage"]["Mo"]), 14)
        fid = formulare.erstellen(self.con, self.k, {"woche": "2026-11-16", "grund": "sonstige", "felder": {"text": "Exkursion"}})
        werte = self.felder(formulare.pdf_von(self.con, self.lid, fid)[0])
        self.assertEqual(sum(1 for v in werte.values() if v == "entfällt, Klasse informiert"), 2)   # Block 1 = Zeilen 1./2.


if __name__ == "__main__":
    unittest.main()
