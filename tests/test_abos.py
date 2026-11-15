"""Tests fuer Kalender-Abos (ICS): Auswerten, Ferien-Abo, Schultermine und eigene Termine im Wochenplan, Rechte.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import datetime
import shutil
import tempfile
import unittest

from app import abos, db, grunddaten, konten, stundenplan

D = datetime.date.fromisoformat
HEUTE = D("2026-11-15")

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//DE
BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:1
SUMMARY:Weihnachtsferien
DTSTART;VALUE=DATE:20261223
DTEND;VALUE=DATE:20270109
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Fachkonferenz Mechatronik
LOCATION:Raum 204
DTSTART;TZID=W. Europe Standard Time:20261117T150000
DTEND;TZID=W. Europe Standard Time:20261117T163000
END:VEVENT
BEGIN:VEVENT
UID:3
SUMMARY:Dienstbesprechung
DTSTART:20261116T130000Z
DTEND:20261116T140000Z
RRULE:FREQ=WEEKLY;COUNT=3
END:VEVENT
BEGIN:VEVENT
UID:4
SUMMARY:Uralt
DTSTART;VALUE=DATE:20200101
END:VEVENT
END:VCALENDAR
"""


class Auswerten(unittest.TestCase):
    def test_ganztags_zeitzone_wiederholung_fenster(self):
        t = abos.auswerten(ICS, HEUTE)
        namen = [(x["titel"], x["datum"], x["bis"], x["beginn"], x["ende"]) for x in t]
        self.assertIn(("Weihnachtsferien", "2026-12-23", "2027-01-08", None, None), namen)          # DTEND exklusiv
        self.assertIn(("Fachkonferenz Mechatronik", "2026-11-17", None, "15:00", "16:30"), namen)  # Windows-Zeitzone
        dienst = [x for x in namen if x[0] == "Dienstbesprechung"]
        self.assertEqual([x[1] for x in dienst], ["2026-11-16", "2026-11-23", "2026-11-30"])        # RRULE aufgeloest
        self.assertEqual(dienst[0][3], "14:00")                                                      # UTC -> Berlin
        self.assertNotIn("Uralt", [x[0] for x in namen])                                             # ausserhalb des Fensters
        self.assertEqual(next(x for x in t if x["titel"] == "Fachkonferenz Mechatronik")["ort"], "Raum 204")

    def test_kaputter_kalender_und_links(self):
        with self.assertRaises(abos.AboFehler):
            abos.auswerten(b"das ist kein Kalender", HEUTE)
        self.assertEqual(abos.url_pruefen("webcal://outlook.office365.com/x.ics"), "https://outlook.office365.com/x.ics")
        for falsch in ("ftp://x/y.ics", "file:///etc/passwd", "nix"):
            with self.subTest(url=falsch), self.assertRaises(abos.AboFehler):
                abos.url_pruefen(falsch)
        with self.assertRaises(abos.AboFehler):
            abos._ziel_erlaubt("127.0.0.1")


class MitAbos(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.admin = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.lk = konten.anlegen(self.con, "rei", "Kollege Reiter", "lehrkraft", "geheim123", vorlaeufig=False)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def anlegen(self, konto, **daten):
        with db.transaktion(self.con):
            return abos.speichern(self.con, konto, dict({"name": "Test", "url": "https://example.org/k.ics"}, **daten))

    def test_ferien_abo(self):
        a = self.anlegen(self.admin, schule=True, art="ferien", name="Ferien RLP")
        self.assertEqual(abos.abrufen(self.con, a, ICS, HEUTE), 1)        # nur ganztaegige im Fenster: Weihnachtsferien
        f = grunddaten.ferien(self.con)
        self.assertEqual([(x["name"], x["von"], x["bis"], x["abo"]) for x in f], [("Weihnachtsferien", "2026-12-23", "2027-01-08", "Ferien RLP")])
        frei = stundenplan.freie_tage(self.con, D("2026-12-28"), D("2026-12-28"))
        self.assertEqual(frei["2026-12-28"], "Weihnachtsferien")
        with self.assertRaises(grunddaten.GrunddatenFehler):           # einzeln loeschen geht nicht
            grunddaten.ferien_loeschen(self.con, f[0]["id"])
        abos.abrufen(self.con, a, ICS, HEUTE)                            # erneuter Abruf ersetzt, verdoppelt nicht
        self.assertEqual(len(grunddaten.ferien(self.con)), len(f))
        with db.transaktion(self.con):
            abos.loeschen(self.con, self.admin, a)
        self.assertEqual(grunddaten.ferien(self.con), [])

    def test_schultermine_und_eigene_im_wochenplan(self):
        schule = self.anlegen(self.admin, schule=True, art="termine", name="Schulkalender")
        eigen = self.anlegen(self.lk, name="Outlook")
        abos.abrufen(self.con, schule, ICS, HEUTE)
        abos.abrufen(self.con, eigen, ICS.replace(b"Fachkonferenz Mechatronik", b"Zahnarzt"), HEUTE)
        w = stundenplan.woche(self.con, self.lk["id"], D("2026-11-16"))
        titel = [(t["titel"], t["art"]) for t in w["termine"]]
        self.assertIn(("Fachkonferenz Mechatronik", "schule"), titel)
        self.assertIn(("Zahnarzt", "abo"), titel)
        # der Admin sieht die Schultermine, aber nicht das Outlook des Kollegen
        w = stundenplan.woche(self.con, self.admin["id"], D("2026-11-16"))
        self.assertNotIn("Zahnarzt", [t["titel"] for t in w["termine"]])
        self.assertIn("Fachkonferenz Mechatronik", [t["titel"] for t in w["termine"]])

    def test_rechte_und_fehler_am_abo(self):
        with self.assertRaises(abos.AboFehler):                             # Lehrkraft: kein Abo der Schule
            self.anlegen(self.lk, schule=True, art="ferien")
        eigen = self.anlegen(self.lk, name="Outlook")
        with self.assertRaises(abos.AboFehler):                             # fremdes Abo
            abos.loeschen(self.con, self.admin, eigen)
        with self.assertRaises(abos.AboFehler):
            abos.abrufen(self.con, eigen, b"kaputt", HEUTE)
        z = abos.liste(self.con, self.lk)[0]
        self.assertIn("gültigen Kalender", z["fehler"])


if __name__ == "__main__":
    unittest.main()
