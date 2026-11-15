"""Stufe D2d: Moodle-Ergebnisse (Bericht "Antworten") in Pruefungen uebernehmen."""
import json
import shutil
import tempfile
import unittest

from app import db, grunddaten, konten, moodle, notenschluessel, planung, pruefungen, stundenplan

ZEILEN = [
    {"nachname": "Weiß", "vorname": "Clara", "abteilung": "BSMT 24 a", "institution": "DRS", "status": "Beendet",
     "begonnen": "20. November 2026  07:50", "beendet": "20. November 2026  08:40", "dauer": "50 Minuten 0 Sekunden", "bewertung5000": "37,93", "antwort1": "x"},
    {"nachname": "Weiss", "vorname": "Clara", "status": "Beendet", "begonnen": "20. November 2026  08:41", "beendet": "20. November 2026  08:59",
     "dauer": "18 Minuten 5 Sekunden", "bewertung5000": "40,00"},
    {"nachname": "Yilmaz", "vorname": "Deniz", "status": "Beendet", "begonnen": "20. November 2026  07:50", "beendet": "20. November 2026  08:50",
     "dauer": "1 Stunde", "bewertung5000": "25,00"},
    {"nachname": "Schmitt", "vorname": "Lea", "status": "Beendet", "begonnen": "27. November 2026  07:51", "beendet": "27. November 2026  08:30",
     "dauer": "39 Minuten", "bewertung5000": "-"},
    {"nachname": "Neu", "vorname": "Tom", "status": "Beendet", "begonnen": "20. November 2026  07:50", "beendet": "20. November 2026  08:30",
     "dauer": "40 Minuten", "bewertung5000": "50,00"},
    {"nachname": "Lea", "vorname": "Schmitt", "status": "In Bearbeitung", "begonnen": "20. November 2026  07:50", "beendet": "", "dauer": "", "bewertung5000": ""},
    {"nachname": "Gesamtdurchschnitt", "vorname": "", "status": "", "bewertung5000": "35,00"},
]
DATEI = json.dumps([ZEILEN], ensure_ascii=False)
CSV = ('Nachname,Vorname,Status,Begonnen,Beendet,Verbrauchte Zeit,"Bewertung/10,00"\n'
       'Weiß,Clara,Beendet,"20. November 2026  07:50","20. November 2026  08:00",10 Minuten,"7,50"\n')


class MoodleImport(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"}])
            self.kl = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs})
            self.sj = grunddaten.schuljahr_speichern(self.con, {"name": "2026/27", "beginn": "2026-11-16", "ende": "2026-12-11"})
            notenschluessel.speichern(self.con, self.k, {"name": "Konferenz BS", "art": "konferenz", "bildungsgang_id": self.bs, "system": "tendenz"})
            v = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2026-08-01"})
            for tag in (1, 5):
                stundenplan.feld_setzen(self.con, self.lid, v, {"wochentag": tag, "beginn": "07:45", "ende": "09:15", "eintraege": [{"klasse_id": self.kl}]})
            pruefungen.moodle_csv(self.con, self.lid, self.kl, "Vorname;Nachname;E-Mail-Adresse\nClara;Weiß;\nDeniz;Yılmaz;\nLea;Schmitt;\n")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @property
    def lid(self):
        return self.k["id"]

    def ids(self):
        return {s["nachname"]: s["id"] for s in pruefungen.schueler(self.con, self.lid, self.kl)}

    def gesamt(self, **mehr):
        return pruefungen.pruefung_speichern(self.con, self.lid, dict({"klasse_id": self.kl, "schuljahr_id": self.sj, "titel": "KA", "form": "termin",
                                                                       "datum": "2026-11-20", "beginn": "07:45", "erfassung": "gesamt", "max_punkte": 100}, **mehr))

    def test_lesen(self):
        g = moodle.lesen(DATEI)
        self.assertEqual((g["max"], len(g["versuche"]), g["uebersprungen"]), (50.0, 5, 1))
        v = g["versuche"][0]
        self.assertEqual((v["bewertung"], v["dauer"], v["beginn"].isoformat(), v["ende"].isoformat()),
                         (37.93, 3000, "2026-11-20T07:50:00", "2026-11-20T08:40:00"))
        self.assertEqual(moodle._sekunden("1 Stunde 2 Minuten"), 3720)
        g = moodle.lesen(CSV)
        self.assertEqual((g["max"], g["versuche"][0]["bewertung"], g["versuche"][0]["dauer"]), (10.0, 7.5, 600))
        with self.assertRaises(moodle.MoodleFehler):
            moodle.lesen('[{"name": "x"}]')

    def test_vorschau_zuordnung_bester_versuch_nachschreiber(self):
        v = moodle.vorschau(self.con, self.lid, {"text": DATEI, "dateiname": "BSMT24-1KA Softstarter und FU-Antworten.json", "klasse_id": self.kl})
        self.assertEqual((v["termin"], v["beginn"], v["titel"], v["max"]), ("2026-11-20", "07:50", "BSMT24-1KA Softstarter und FU", 50.0))
        z = {x["name"]: x for x in v["zeilen"]}
        s = self.ids()
        self.assertEqual((z["Weiss, Clara"]["anzahl"], z["Weiss, Clara"]["bewertung"]), (2, 40.0))          # bester von zwei Versuchen (Name aus diesem Versuch)
        self.assertEqual((z["Weiss, Clara"]["schueler_id"], z["Weiss, Clara"]["sicher"]), (s["Weiß"], True))
        self.assertEqual(z["Yilmaz, Deniz"]["schueler_id"], s["Yılmaz"])                                  # ı = i
        self.assertTrue(z["Schmitt, Lea"]["nachgeschrieben"])
        self.assertIsNone(z["Neu, Tom"]["schueler_id"])

    def test_neue_pruefung_aus_datei(self):
        s = self.ids()
        r = moodle.uebernehmen(self.con, self.lid, {"text": DATEI, "dateiname": "KA-Antworten.json", "klasse_id": self.kl})
        self.assertEqual((r["uebernommen"], r["ohne_zuordnung"]), (2, 2))          # Schmitt ohne Bewertung, Neu ohne Zuordnung
        e = pruefungen.ergebnis(self.con, self.lid, r["pruefung_id"])
        p = e["pruefung"]
        self.assertEqual((p["titel"], p["form"], p["datum"], p["beginn"], p["erfassung"], p["max_punkte"], p["stand"]),
                         ("KA", "termin", "2026-11-20", "07:45", "gesamt", 50.0, "durchgefuehrt"))
        z = {x["id"]: x for x in e["schueler"]}
        self.assertEqual((z[s["Weiß"]]["werte"]["gesamt"], z[s["Weiß"]]["dauer"]), (40.0, 1085))
        self.assertAlmostEqual(z[s["Yılmaz"]]["prozent"], 50.0)
        plan = planung.plan(self.con, self.lid, self.kl, None, self.sj, jetzt="2026-11-15T12:00:00")
        self.assertEqual(next(t for t in plan["themen"] if t["pruefung_id"] == p["id"])["von"], "2026-11-20")

    def test_in_vorhandene_pruefung_umgerechnet_mit_eigener_zuordnung(self):
        pid = self.gesamt()
        s = self.ids()
        v = moodle.vorschau(self.con, self.lid, {"text": DATEI, "pruefung_id": pid})
        neu = next(x for x in v["zeilen"] if x["name"] == "Neu, Tom")["schluessel"]
        schmitt = next(x for x in v["zeilen"] if x["name"] == "Schmitt, Lea")
        # Tom Neu ist in Wahrheit Lea Schmitt (anderer Moodle-Name); Schmitts eigener Eintrag hat keine Bewertung
        r = moodle.uebernehmen(self.con, self.lid, {"text": DATEI, "pruefung_id": pid, "zuordnung": {neu: s["Schmitt"], schmitt["schluessel"]: None}})
        self.assertEqual(r["uebernommen"], 3)
        z = {x["id"]: x for x in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"]}
        self.assertEqual((z[s["Weiß"]]["werte"]["gesamt"], z[s["Schmitt"]]["werte"]["gesamt"]), (80.0, 100.0))   # 40/50 -> 80/100
        with self.assertRaises(moodle.MoodleFehler):                        # doppelt zugeordnet
            moodle.uebernehmen(self.con, self.lid, {"text": DATEI, "pruefung_id": pid, "zuordnung": {neu: s["Weiß"]}})
        pid2 = self.gesamt(titel="Aufgaben", erfassung="aufgaben", aufgaben=[{"name": "A", "max": 5}])
        with self.assertRaises(moodle.MoodleFehler):                        # nur Gesamtpunkte
            moodle.vorschau(self.con, self.lid, {"text": DATEI, "pruefung_id": pid2})

    def test_nachschreiber_vermerk(self):
        pid = self.gesamt(max_punkte=50)
        zeilen = [dict(ZEILEN[3], bewertung5000="30,00")]
        moodle.uebernehmen(self.con, self.lid, {"text": json.dumps([zeilen]), "pruefung_id": pid})
        moodle.uebernehmen(self.con, self.lid, {"text": json.dumps([zeilen]), "pruefung_id": pid})   # zweimal: Vermerk nur einmal
        z = next(x for x in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"] if x["name"].startswith("Schmitt"))
        self.assertEqual(z["notiz"], "nachgeschrieben am 27.11.2026")


if __name__ == "__main__":
    unittest.main()
