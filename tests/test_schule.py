"""Schullogo, Schulname und Webadresse; Dokumente im DRS-Design (Logo im Kopf, Farbband im Fuss)."""
import base64
import shutil
import tempfile
import unittest

from app import db, exporte, grunddaten, konten, notenschluessel, pdf, pruefungen, schule

# kleinstes JPEG-Geruest: SOI, APP0, SOF0 (64 x 32, 3 Kanaele), EOI - reicht fuer Masse und Einbettung im Test
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x11\x08\x00\x20\x00\x40\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9")
DATA_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


class Schule(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"}])
            self.kl = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": bs})
            self.sj = grunddaten.schuljahr_speichern(self.con, {"name": "2026/27", "beginn": "2026-11-16", "ende": "2026-12-11"})
            notenschluessel.speichern(self.con, self.k, {"name": "Konferenz BS", "art": "konferenz", "bildungsgang_id": bs, "system": "tendenz"})
            pruefungen.moodle_csv(self.con, self.k["id"], self.kl, "Vorname;Nachname\nClara;Weiß\nLea;Schmitt\n")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_angaben_und_logo(self):
        a = schule.angaben(self.con)
        self.assertEqual((a["name"], a["web"], a["logo"]), ("David Roentgen Schule Neuwied", "www.drsneuwied.de", False))
        self.assertEqual(pdf.jpeg_masse(JPEG), (64, 32, 3))
        schule.speichern(self.con, {"logo": DATA_URL, "web": "www.beispiel.de"})
        a = schule.angaben(self.con)
        self.assertEqual((a["logo"], a["logo_masse"], a["web"]), (True, [64, 32], "www.beispiel.de"))
        self.assertEqual(schule.logo(self.con), JPEG)
        for falsch in ("data:image/png;base64,iVBORw0KGgo=", "data:image/jpeg;base64," + base64.b64encode(b"kein bild").decode()):
            with self.assertRaises(schule.SchuleFehler):
                schule.speichern(self.con, {"logo": falsch})
        with self.assertRaises(schule.SchuleFehler):
            schule.speichern(self.con, {"name": ""})
        schule.speichern(self.con, {"logo": ""})
        self.assertFalse(schule.angaben(self.con)["logo"])

    def test_dokumente_mit_logo_und_farbband(self):
        lid = self.k["id"]
        pid = pruefungen.pruefung_speichern(self.con, lid, {"klasse_id": self.kl, "schuljahr_id": self.sj, "titel": "KA", "form": "termin",
                                                            "datum": "2026-11-20", "beginn": "07:45", "erfassung": "gesamt", "max_punkte": 50})
        for s in pruefungen.schueler(self.con, lid, self.kl):
            pruefungen.bewertung_setzen(self.con, lid, pid, s["id"], {"werte": {"gesamt": 40}})
        inhalt, _ = exporte.rueckmeldung_pdf(self.con, lid, pid)
        self.assertNotIn(b"/Subtype /Image", inhalt)                    # ohne Logo: Schulname als Text
        self.assertIn(b"(David Roentgen Schule Neuwied)", inhalt)
        self.assertIn(b"(www.drsneuwied.de)", inhalt)
        self.assertIn(b"0.694 0.784 0.000 rg", inhalt)                  # Gruen im Farbband
        schule.speichern(self.con, {"logo": DATA_URL})
        inhalt, _ = exporte.rueckmeldung_pdf(self.con, lid, pid)
        self.assertEqual(inhalt.count(b"/Type /Page "), 2)
        self.assertEqual(inhalt.count(b"/Subtype /Image"), 1)           # Logo einmal eingebettet, auf beiden Seiten benutzt
        self.assertEqual(inhalt.count(b" Do Q"), 2)
        self.assertIn(JPEG, inhalt)
        inhalt, _ = exporte.ergebnis_pdf(self.con, lid, pid)
        self.assertEqual(inhalt.count(b"/Subtype /Image"), 1)


if __name__ == "__main__":
    unittest.main()
