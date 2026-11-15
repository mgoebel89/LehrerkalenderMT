"""Tests fuer Stufe D1: Schuelerlisten (Moodle-CSV), Notenberechnung mit Rechenweg, Pruefungen in der Planung,
Schluesselwahl, Abschliessen, Statistik.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import shutil
import tempfile
import unittest

from app import db, grunddaten, konten, notenschluessel, planung, pruefungen, stundenplan

MOODLE = """Vorname;Nachname;E-Mail-Adresse
Clara;Weiß;clara@schule.de
Deniz;Yılmaz;deniz@schule.de
Lea;Schmitt;
"""

BOGEN = {"bereiche": [
    {"name": "Präsentation", "gewicht": 40, "kriterien": [
        {"name": "Fachliche Richtigkeit", "typ": "stufen", "gewicht": 2},
        {"name": "Auftreten", "typ": "stufen"},
        {"name": "Handout abgegeben", "typ": "haken"}]},
    {"name": "Fachgespräch", "gewicht": 60, "kriterien": [
        {"name": "Fragen", "typ": "punkte", "max": 10},
        {"name": "Bemerkung", "typ": "text"}]}]}


class Berechnung(unittest.TestCase):
    def test_aufgaben_summe_durch_summe(self):
        st = pruefungen.struktur_pruefen({"bereiche": [{"name": "Aufgaben", "gewicht": 1, "kriterien": [
            {"name": "A1", "typ": "punkte", "max": 10}, {"name": "A2", "typ": "punkte", "max": 30}]}]})
        r = pruefungen.berechnen("aufgaben", st, None, {"k1": 10, "k2": 15})
        self.assertAlmostEqual(r["prozent"], 62.5)        # 25/40, nicht Mittel aus 100 % und 50 %
        self.assertEqual(r["rechenweg"], ["25 von 40 Punkten = 62,5 %"])
        r = pruefungen.berechnen("aufgaben", st, None, {"k1": 10})
        self.assertEqual((r["prozent"], r["fehlend"]), (100.0, ["A2"]))   # unbewertet zaehlt nicht, wird gemeldet

    def test_bogen_mit_gewichten(self):
        st = pruefungen.struktur_pruefen(BOGEN)
        # Stufen 0..3: Richtigkeit "ueberwiegend" (2/3, Gewicht 2), Auftreten "vollstaendig" (3/3) -> (2*2/3+1)/3 = 77,8 %
        r = pruefungen.berechnen("bogen", st, None, {"k1": 2, "k2": 3, "k3": True, "k4": 5, "k5": "gut"})
        self.assertAlmostEqual(r["bereiche"][0]["prozent"], 77.777, places=2)
        self.assertAlmostEqual(r["bereiche"][1]["prozent"], 50.0)
        self.assertAlmostEqual(r["prozent"], (40 * 77.7777 + 60 * 50) / 100, places=2)
        self.assertTrue(r["rechenweg"][-1].startswith("Gesamt: (40 × 77,8 + 60 × 50) / 100 = 61,1 %"))
        # nur ein Bereich bewertet: der andere zaehlt nicht mit
        r = pruefungen.berechnen("bogen", st, None, {"k4": 8})
        self.assertAlmostEqual(r["prozent"], 80.0)
        self.assertEqual(r["fehlend"], ["Fachliche Richtigkeit", "Auftreten"])

    def test_gesamtpunkte(self):
        r = pruefungen.berechnen("gesamt", {"bereiche": []}, 50, {"gesamt": 38})
        self.assertEqual((round(r["prozent"]), r["rechenweg"]), (76, ["38 von 50 Punkten = 76 %"]))

    def test_struktur_fehler(self):
        with self.assertRaises(pruefungen.PruefungFehler):
            pruefungen.struktur_pruefen({"bereiche": [{"name": "X", "kriterien": [{"name": "A", "typ": "punkte"}]}]})   # ohne Max
        with self.assertRaises(pruefungen.PruefungFehler):
            pruefungen.struktur_pruefen({"bereiche": []})


class MitPruefung(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.r = konten.anlegen(self.con, "rei", "Kollege Reiter", "lehrkraft", "geheim123", vorlaeufig=False)
            self.bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"}])
            self.kl = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs})
            self.sj = grunddaten.schuljahr_speichern(self.con, {"name": "2026/27", "beginn": "2026-11-16", "ende": "2026-12-11"})
            self.konf = notenschluessel.speichern(self.con, self.k, {"name": "Konferenz BS", "art": "konferenz", "bildungsgang_id": self.bs,
                                                                     "system": "tendenz"})
            v = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2026-08-01"})
            for tag in (1, 5):
                stundenplan.feld_setzen(self.con, self.lid, v, {"wochentag": tag, "beginn": "07:45", "ende": "09:15",
                                                                "eintraege": [{"klasse_id": self.kl}]})
            self.liste = pruefungen.moodle_csv(self.con, self.lid, self.kl, MOODLE)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @property
    def lid(self):
        return self.k["id"]

    def strang(self, **mehr):
        return dict({"klasse_id": self.kl, "gruppe_id": None, "schuljahr_id": self.sj}, **mehr)

    def ids(self):
        return {s["nachname"]: s["id"] for s in pruefungen.schueler(self.con, self.lid, self.kl)}


class Schuelerlisten(MitPruefung):
    def test_moodle_import_nie_umbenennen(self):
        self.assertEqual(sorted(self.liste["neu"]), ["Schmitt, Lea", "Weiß, Clara", "Yılmaz, Deniz"])
        sid = self.ids()["Weiß"]
        pruefungen.schueler_speichern(self.con, self.lid, {"nachname": "Weiss", "vorname": "Clara"}, sid)   # eigene Schreibweise
        r = pruefungen.moodle_csv(self.con, self.lid, self.kl, "Vorname,Nachname,E-Mail-Adresse\nClara,Weiß,clara@schule.de\nLea,Schmitt,lea@x.de\nTom,Neu,\n")
        self.assertEqual((r["neu"], len(r["vorhanden"])), (["Neu, Tom"], 2))
        self.assertEqual(next(x for x in pruefungen.schueler(self.con, self.lid, self.kl) if x["vorname"] == "Clara")["nachname"], "Weiss")
        self.assertEqual(next(s for s in pruefungen.schueler(self.con, self.lid, self.kl) if s["nachname"] == "Schmitt")["email"], "lea@x.de")
        self.assertEqual(pruefungen.schueler(self.con, self.r["id"], self.kl), [])                            # privat
        with self.assertRaises(pruefungen.PruefungFehler):
            pruefungen.moodle_csv(self.con, self.lid, self.kl, "Vorname;Mail\nA;b\n")


class Pruefungen(MitPruefung):
    def test_klassenarbeit_termin_planung_und_bewertung(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=3))
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Klassenarbeit LF 7", art="schriftlich", form="termin", datum="2026-11-20", beginn="07:45", bloecke=1,
            erfassung="aufgaben", aufgaben=[{"name": "A1", "max": 20}, {"name": "A2", "max": 30}]))
        p = planung.plan(self.con, self.lid, self.kl, None, self.sj, jetzt="2026-11-15T12:00:00")
        ka = next(t for t in p["themen"] if t["pruefung_id"] == pid)
        self.assertEqual((ka["von"], ka["nadel"]), ("2026-11-20", "ok"))
        self.assertEqual(next(t for t in p["themen"] if t["titel"] == "SPS")["bis"], "2026-11-27")    # fliesst um die Arbeit herum
        with self.assertRaises(planung.PlanungFehler):                                                # in der Planung fest
            planung.thema_loeschen(self.con, self.lid, ka["id"])
        s = self.ids()
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Weiß"], {"werte": {"k1": 20, "k2": 22}})
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Yılmaz"], {"werte": {"k1": 10, "k2": 10}})
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Schmitt"], {"fehlt": True})
        with self.assertRaises(pruefungen.PruefungFehler):                                            # ueber dem Hoechstwert
            pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Weiß"], {"werte": {"k1": 21}})
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        zeilen = {z["name"]: z for z in e["schueler"]}
        self.assertEqual(e["herkunft"], "Konferenzschlüssel des Bildungsgangs")
        self.assertEqual(zeilen["Weiß, Clara"]["note"]["text"], "2+")                                 # 42/50 = 84 %
        self.assertEqual(zeilen["Yılmaz, Deniz"]["note"]["text"], "5")                                # 20/50 = 40 %
        self.assertIn("42 von 50 Punkten = 84 %", zeilen["Weiß, Clara"]["rechenweg"])
        self.assertEqual(zeilen["Weiß, Clara"]["rechenweg"][-1], "Konferenz BS (Tendenznoten): 84 % → 2+")
        st = e["statistik"]
        self.assertEqual((st["bewertet"], st["fehlt"], st["schnitt"]), (2, 1, 3.35))                   # (1,7 + 5,0) / 2
        self.assertEqual(st["spiegel"]["2"], 1)
        self.assertEqual([round(a["prozent"]) for a in st["aufgaben"]], [75, 53])
        self.assertEqual(e["pruefung"]["stand"], "durchgefuehrt")
        # Abschliessen friert den Schluessel ein; spaetere Aenderung am Schluessel aendert die Note nicht
        self.assertEqual(pruefungen.abschliessen(self.con, self.lid, pid), [])
        notenschluessel.speichern(self.con, self.k, {"name": "Konferenz BS", "grenzen": dict(notenschluessel.vorgabe("tendenz"), **{"2+": 90, "1-": 95, "1": 98})},
                                  self.konf)
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        self.assertEqual(next(z for z in e["schueler"] if z["name"] == "Weiß, Clara")["note"]["text"], "2+")
        with self.assertRaises(pruefungen.PruefungFehler):
            pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Weiß"], {"werte": {"k1": 19}})
        pruefungen.wieder_oeffnen(self.con, self.lid, pid)
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        self.assertEqual(next(z for z in e["schueler"] if z["name"] == "Weiß, Clara")["note"]["text"], "2")   # neuer Schluessel
        pruefungen.pruefung_loeschen(self.con, self.lid, pid)
        self.assertFalse(any(t["pruefung_id"] for t in planung.plan(self.con, self.lid, self.kl, None, self.sj)["themen"]))

    def test_schluesselwahl_und_fenster(self):
        eigen = notenschluessel.speichern(self.con, self.k, {"name": "Mein strenger", "art": "eigen", "system": "punkte"})
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Fachgespräch LF 10", art="muendlich", form="fenster", fenster_von="2026-11-16", fenster_bis="2026-11-27",
            erfassung="gesamt", max_punkte=20))
        self.assertEqual(pruefungen.ergebnis(self.con, self.lid, pid)["herkunft"], "Konferenzschlüssel des Bildungsgangs")
        pruefungen.standard_setzen(self.con, self.lid, eigen)
        self.assertEqual(pruefungen.ergebnis(self.con, self.lid, pid)["herkunft"], "dein Standard")
        with db.transaktion(self.con):
            grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs, "notenschluessel_id": self.konf}, self.kl)
        self.assertEqual(pruefungen.ergebnis(self.con, self.lid, pid)["herkunft"], "Schlüssel der Klasse")
        pruefungen.pruefung_speichern(self.con, self.lid, {"titel": "Fachgespräch LF 10", "art": "muendlich", "form": "fenster",
                                                            "fenster_von": "2026-11-16", "fenster_bis": "2026-11-27", "erfassung": "gesamt",
                                                            "max_punkte": 20, "notenschluessel_id": eigen}, pid)
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        self.assertEqual((e["herkunft"], e["schluessel"]["system"]), ("in der Prüfung gewählt", "punkte"))
        pruefungen.bewertung_setzen(self.con, self.lid, pid, self.ids()["Weiß"], {"werte": {"gesamt": 17}})
        self.assertEqual(next(z for z in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"] if z["note"])["note"]["text"], "13 P")   # 85 % (MSS-Vorgabe)
        # Fenster belegt keine Bloecke; Hinweise fuer die Startseite
        self.assertFalse(any(t["pruefung_id"] for t in planung.plan(self.con, self.lid, self.kl, None, self.sj)["themen"]))
        import datetime
        h = pruefungen.hinweise(self.con, self.lid, heute=datetime.date(2026, 11, 20))
        self.assertEqual([(x["titel"], x["art"]) for x in h], [("Fachgespräch LF 10", "fenster")])
        with self.assertRaises(pruefungen.PruefungFehler):          # fremde Pruefung
            pruefungen.ergebnis(self.con, self.r["id"], pid)

    def test_bogen_aus_vorlage(self):
        vid = pruefungen.vorlage_speichern(self.con, self.lid, {"name": "Präsentation + Fachgespräch", "art": "muendlich", "struktur": BOGEN})
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Mündliche Prüfung LF 9", art="muendlich", form="termin", datum="2026-11-27", beginn="07:45", erfassung="bogen", vorlage_id=vid))
        pruefungen.vorlage_loeschen(self.con, self.lid, vid)                    # Pruefung behaelt ihre Kopie
        sid = self.ids()["Weiß"]
        pruefungen.bewertung_setzen(self.con, self.lid, pid, sid, {"werte": {"k1": 3, "k2": 3, "k4": 10}, "notiz": "souverän"})
        z = next(z for z in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"] if z["id"] == sid)
        self.assertEqual((round(z["prozent"]), z["note"]["text"], z["notiz"]), (100, "1", "souverän"))
        with self.assertRaises(pruefungen.PruefungFehler):                       # Stufe gibt es nicht
            pruefungen.bewertung_setzen(self.con, self.lid, pid, sid, {"werte": {"k1": 7}})


class GetrenntSchreiben(MitPruefung):
    def test_termine_je_gruppe_und_hinweise(self):
        grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"},
                                                         {"bezeichnung": "2. Block", "beginn": "09:30", "ende": "11:00"}])
        v = stundenplan.versionen(self.con, self.lid)[0]["id"]
        g1 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.kl, "name": "Gr. 1"})
        g2 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.kl, "name": "Gr. 2"})
        for beginn, ende, g in (("07:45", "09:15", g1), ("09:30", "11:00", g2)):
            stundenplan.feld_setzen(self.con, self.lid, v, {"wochentag": 3, "beginn": beginn, "ende": ende,
                                                            "eintraege": [{"klasse_id": self.kl, "gruppe_id": g}]})
        h = pruefungen.termin_hinweise(self.con, self.lid, self.kl, [{"gruppe_id": None, "datum": "2026-11-18", "beginn": "07:45"}])
        self.assertIn("nur Gr. 1", h[0])
        h = pruefungen.termin_hinweise(self.con, self.lid, self.kl, [{"gruppe_id": None, "datum": "2026-11-17", "beginn": "07:45"}])
        self.assertIn("keinen Unterricht", h[0])
        self.assertEqual(pruefungen.termin_hinweise(self.con, self.lid, self.kl, [{"datum": "2026-11-16", "beginn": "07:45"}]), [])
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Klassenarbeit", form="termin", teilung="getrennt", bloecke=1, erfassung="gesamt", max_punkte=50,
            termine=[{"gruppe_id": g2, "datum": "2026-11-18", "beginn": "09:30"}, {"gruppe_id": g1, "datum": "2026-11-18", "beginn": "07:45"}]))
        p = pruefungen.ergebnis(self.con, self.lid, pid)["pruefung"]
        self.assertEqual([(t["gruppe"], t["beginn"]) for t in p["termine"]], [("Gr. 1", "07:45"), ("Gr. 2", "09:30")])
        self.assertEqual((p["datum"], p["beginn"], p["teilung"], p["hinweise"]), ("2026-11-18", "07:45", "getrennt", []))
        plan = planung.plan(self.con, self.lid, self.kl, None, self.sj, jetzt="2026-11-15T12:00:00")
        ka = next(t for t in plan["themen"] if t["pruefung_id"] == pid)
        self.assertEqual((ka["von"], ka["nadel"], ka["zugeteilt"]), ("2026-11-18", "ok", 1))     # beide Gruppen = ein Schritt
        self.assertEqual([b["thema_id"] for b in plan["bloecke"] if b["datum"] == "2026-11-18"], [ka["id"], ka["id"]])
        # vertauschte Gruppen: Hinweis
        pruefungen.pruefung_speichern(self.con, self.lid, {"titel": "Klassenarbeit", "form": "termin", "teilung": "getrennt", "erfassung": "gesamt",
                                                           "max_punkte": 50, "termine": [{"gruppe_id": g2, "datum": "2026-11-18", "beginn": "07:45"},
                                                                                         {"gruppe_id": g1, "datum": "2026-11-18", "beginn": "09:30"}]}, pid)
        self.assertIn("laut Stundenplan Gr. 1", pruefungen.ergebnis(self.con, self.lid, pid)["pruefung"]["hinweise"][0])
        with self.assertRaises(pruefungen.PruefungFehler):                # ein Termin reicht nicht
            pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="X", form="termin", teilung="getrennt", erfassung="gesamt",
                                                                          max_punkte=10, termine=[{"gruppe_id": g1, "datum": "2026-11-18", "beginn": "07:45"}]))
        with self.assertRaises(stundenplan.StundenplanFehler):            # Gruppe mit Pruefungstermin
            stundenplan.gruppe_loeschen(self.con, self.lid, g1)

    def test_offene_ist_sieht_spaetere_pruefung(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=10))
        pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="KA", form="termin", datum="2026-12-04", beginn="07:45",
                                                                      erfassung="gesamt", max_punkte=10))
        offen = planung.offene_ist(self.con, self.lid, jetzt="2026-11-24T12:00:00")
        self.assertEqual({o["thema"] for o in offen}, {"SPS"})        # die Arbeit am 04.12. rutscht nicht nach vorn


if __name__ == "__main__":
    unittest.main()
