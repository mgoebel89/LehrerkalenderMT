"""Tests fuer Stufe D1: Schuelerlisten (Moodle-CSV), Notenberechnung mit Rechenweg, Pruefungen in der Planung,
Schluesselwahl, Abschliessen, Statistik.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import shutil
import tempfile
import unittest

from app import db, exporte, grunddaten, pdf, konten, notenschluessel, planung, pruefungen, stundenplan

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

    def test_getauschte_bloecke_bilden_das_paar(self):
        """B hat Block 1+2, A Block 3+4; B schreibt im 2., A im 3. Block: diese beiden sind EIN Schritt, 1. und 4. der andere."""
        grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "%d. Block" % (n + 1), "beginn": b, "ende": e} for n, (b, e) in
                                                         enumerate([("07:45", "09:15"), ("09:30", "11:00"), ("11:30", "13:00"), ("13:15", "14:45")])])
        v = stundenplan.versionen(self.con, self.lid)[0]["id"]
        ga = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.kl, "name": "Klasse A"})
        gb = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.kl, "name": "Klasse B"})
        for beginn, ende, g in (("07:45", "09:15", gb), ("09:30", "11:00", gb), ("11:30", "13:00", ga), ("13:15", "14:45", ga)):
            stundenplan.feld_setzen(self.con, self.lid, v, {"wochentag": 4, "beginn": beginn, "ende": ende,
                                                            "eintraege": [{"klasse_id": self.kl, "gruppe_id": g}]})
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Robotik-Labor", bloecke=20))
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Robotik", form="termin", teilung="getrennt", bloecke=1, erfassung="gesamt", max_punkte=50,
            termine=[{"gruppe_id": gb, "datum": "2026-11-19", "beginn": "09:30"}, {"gruppe_id": ga, "datum": "2026-11-19", "beginn": "11:30"}]))
        p = planung.plan(self.con, self.lid, self.kl, None, self.sj, jetzt="2026-11-15T12:00:00")
        ka = next(t for t in p["themen"] if t["pruefung_id"] == pid)
        do = {b["beginn"]: b["thema_id"] == ka["id"] for b in p["bloecke"] if b["datum"] == "2026-11-19"}
        self.assertEqual(do, {"07:45": False, "09:30": True, "11:30": True, "13:15": False})
        self.assertEqual(ka["zugeteilt"], 1)
        andere = [(b["beginn"], b["zweit"]) for b in p["bloecke"] if b["datum"] == "2026-11-19" and b["thema_id"] != ka["id"]]
        self.assertEqual(andere, [("07:45", False), ("13:15", True)])   # 1. von B und 2. von A: derselbe Stoff

    def test_pruefung_ohne_unterricht_fliesst_nicht(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=2))
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="KA", form="termin", datum="2026-11-17", beginn="07:45",
                                                                            erfassung="gesamt", max_punkte=10))   # Dienstag: kein Unterricht
        p = planung.plan(self.con, self.lid, self.kl, None, self.sj, jetzt="2026-11-15T12:00:00")
        ka = next(t for t in p["themen"] if t["pruefung_id"] == pid)
        self.assertEqual((ka["nadel"], ka["zugeteilt"], ka["ueberlauf"]), ("fehlt", 0, 0))
        self.assertFalse(any(b["thema_id"] == ka["id"] for b in p["bloecke"]))
        self.assertIn("keinen Unterricht", pruefungen.ergebnis(self.con, self.lid, pid)["pruefung"]["hinweise"][0])

    def test_offene_ist_sieht_spaetere_pruefung(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=10))
        pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="KA", form="termin", datum="2026-12-04", beginn="07:45",
                                                                      erfassung="gesamt", max_punkte=10))
        offen = planung.offene_ist(self.con, self.lid, jetzt="2026-11-24T12:00:00")
        self.assertEqual({o["thema"] for o in offen}, {"SPS"})        # die Arbeit am 04.12. rutscht nicht nach vorn


class LaborUndTeams(MitPruefung):
    def reihe(self, **mehr):
        return pruefungen.pruefung_speichern(self.con, self.lid, self.strang(**dict(
            titel="Laborreihe Pneumatik", art="praktisch", form="fenster", fenster_von="2026-11-16", fenster_bis="2026-12-11",
            erfassung="checkliste", versuche=[
                {"name": "V1 Zylinder", "team": True, "haken": [{"name": "Aufbau", "punkte": 2}, {"name": "Messung", "punkte": 2}]},
                {"name": "V2 Ventile", "team": False, "haken": [{"name": "Protokoll", "punkte": 4}]}]), **mehr))

    def test_checkliste_mit_team_und_einzel(self):
        pid = self.reihe()
        s = self.ids()
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        v1, v2 = e["pruefung"]["struktur"]["bereiche"]
        self.assertEqual((v1["team"], v2["team"], v1["kriterien"][0]["typ"]), (True, False, "check"))
        t = pruefungen.team_speichern(self.con, self.lid, pid, {"schueler_ids": [s["Weiß"], s["Schmitt"]]})
        # Haken im Team-Versuch bei Weiß gilt auch fuer Schmitt; V2 ist einzeln
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Weiß"], {"werte": {v1["kriterien"][0]["key"]: True, v2["kriterien"][0]["key"]: True}})
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        z = {x["name"].split(",")[0]: x for x in e["schueler"]}
        self.assertEqual([v["erledigt"] for v in z["Weiß"]["versuche"]], [1, 1])
        self.assertEqual([v["erledigt"] for v in z["Schmitt"]["versuche"]], [1, 0])
        self.assertEqual((z["Weiß"]["team"], z["Yılmaz"]["team"]), ("Team 1", ""))
        self.assertAlmostEqual(z["Weiß"]["prozent"], 75.0)       # 2 + 4 von 8 Punkten
        self.assertAlmostEqual(z["Schmitt"]["prozent"], 25.0)    # 2 von 8
        self.assertIsNone(z["Yılmaz"]["prozent"])               # noch nichts abgehakt: (noch) keine Note
        self.assertEqual(z["Weiß"]["rechenweg"][-2:], ["Gesamt: 6 von 8 Punkten = 75 %", "Konferenz BS (Tendenznoten): 75 % → 3+"])
        self.assertEqual(e["statistik"]["fortschritt"], [0, 1])  # V1 bei niemandem ganz fertig, V2 bei einem
        # Team aufloesen: Schmitt verliert den Teamhaken
        pruefungen.team_loeschen(self.con, self.lid, pid, t)
        z = {x["name"].split(",")[0]: x for x in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"]}
        self.assertEqual([v["erledigt"] for v in z["Schmitt"]["versuche"]], [0, 0])

    def test_testat_ohne_note_und_teams_bilden(self):
        pid = self.reihe(testat=True)
        e = pruefungen.ergebnis(self.con, self.lid, pid)
        self.assertTrue(e["pruefung"]["struktur"]["testat"])
        self.assertIsNone(e["schluessel"])
        self.assertTrue(all(z["note"] is None for z in e["schueler"]))
        self.assertEqual(pruefungen.abschliessen(self.con, self.lid, pid), ["3 ohne Bewertung"])   # ohne Schluessel moeglich
        pruefungen.wieder_oeffnen(self.con, self.lid, pid)
        n = pruefungen.teams_bilden(self.con, self.lid, pid, 2)
        teams = pruefungen.teams(self.con, pid)
        self.assertEqual((n, sorted(len(t["mitglieder"]) for t in teams)), (1, [3]))   # 3 Schueler, Rest von 1 kommt dazu
        # Aenderung ohne neue Versuche behaelt die Struktur
        pruefungen.pruefung_speichern(self.con, self.lid, {"titel": "Laborreihe", "form": "fenster", "fenster_von": "2026-11-16",
                                                           "fenster_bis": "2026-12-11", "erfassung": "checkliste", "testat": False}, pid)
        st = pruefungen.ergebnis(self.con, self.lid, pid)["pruefung"]["struktur"]
        self.assertEqual((len(st["bereiche"]), st.get("testat")), (2, None))

    def test_bogen_mit_teambereich(self):
        vid = pruefungen.vorlage_speichern(self.con, self.lid, {"name": "Präsentation", "art": "bogen", "struktur": {"bereiche": [
            {"name": "Präsentation", "gewicht": 1, "kriterien": [{"name": "Gestaltung", "typ": "punkte", "max": 10}]},
            {"name": "Fachgespräch", "gewicht": 1, "kriterien": [{"name": "Fachwissen", "typ": "punkte", "max": 10}]}]}})
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="Projekt", art="muendlich", form="termin", datum="2026-11-20",
                                                                            beginn="07:45", erfassung="bogen", vorlage_id=vid, team_bereiche=[0]))
        s = self.ids()
        pruefungen.team_speichern(self.con, self.lid, pid, {"name": "Roboter", "schueler_ids": [s["Weiß"], s["Yılmaz"]]})
        st = pruefungen.ergebnis(self.con, self.lid, pid)["pruefung"]["struktur"]
        g, f = st["bereiche"][0]["kriterien"][0]["key"], st["bereiche"][1]["kriterien"][0]["key"]
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Yılmaz"], {"werte": {g: 8, f: 4}})
        pruefungen.bewertung_setzen(self.con, self.lid, pid, s["Weiß"], {"werte": {f: 10}})
        z = {x["name"].split(",")[0]: x for x in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"]}
        self.assertEqual((z["Weiß"]["werte"], z["Yılmaz"]["werte"]), ({g: 8, f: 10}, {g: 8, f: 4}))
        self.assertAlmostEqual(z["Weiß"]["prozent"], 90.0)
        self.assertEqual(z["Weiß"]["team"], "Roboter")


class Pruefungsmodus(MitPruefung):
    def setUp(self):
        super().setUp()
        vid = pruefungen.vorlage_speichern(self.con, self.lid, {"name": "Fachgespräch", "art": "muendlich", "struktur": {"bereiche": [
            {"name": "Fachwissen", "gewicht": 3, "kriterien": [{"name": "Grundlagen", "typ": "punkte", "max": 10}]}]}})
        self.pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(titel="Fachgespräch", art="muendlich", form="termin",
                                                                                 datum="2026-11-20", beginn="07:45", erfassung="bogen", vorlage_id=vid))

    def test_fragen_ziehen_ohne_wiederholung(self):
        n = pruefungen.fragen_einfuegen(self.con, self.lid, self.pid, "Pneumatik: Was ist ein 5/2-Wegeventil?\n- Was macht ein Drosselrückschlagventil?\n\n")
        self.assertEqual(n, 2)
        pool = pruefungen.fragen(self.con, self.pid)
        self.assertEqual([(f["kategorie"], f["text"][:8]) for f in pool], [("Pneumatik", "Was ist "), ("", "Was mach")])
        s = self.ids()
        e1 = pruefungen.frage_ziehen(self.con, self.lid, self.pid, s["Weiß"])
        e2 = pruefungen.frage_ziehen(self.con, self.lid, self.pid, s["Schmitt"])
        texte = [z[0] for z in self.con.execute("SELECT text FROM pruefung_protokoll WHERE id IN (?, ?)", (e1, e2))]
        self.assertEqual(len(set(texte)), 2)                           # zweite Ziehung nimmt die andere Frage
        e3 = pruefungen.frage_ziehen(self.con, self.lid, self.pid, s["Weiß"])   # Pool aufgebraucht: die, die Weiß noch nicht hatte
        self.assertNotEqual(self.con.execute("SELECT frage_id FROM pruefung_protokoll WHERE id = ?", (e3,)).fetchone()[0],
                            self.con.execute("SELECT frage_id FROM pruefung_protokoll WHERE id = ?", (e1,)).fetchone()[0])
        with self.assertRaises(pruefungen.PruefungFehler):             # Weiß hatte jetzt alle
            pruefungen.frage_ziehen(self.con, self.lid, self.pid, s["Weiß"])

    def test_spontanfragen_stufen_in_der_note_und_dauer(self):
        s = self.ids()
        k = pruefungen.ergebnis(self.con, self.lid, self.pid)["pruefung"]["struktur"]["bereiche"][0]["kriterien"][0]["key"]
        pruefungen.bewertung_setzen(self.con, self.lid, self.pid, s["Weiß"], {"werte": {k: 8}})
        eid = pruefungen.protokoll_speichern(self.con, self.lid, self.pid, {"schueler_id": s["Weiß"], "text": "Wozu dient ein Rückschlagventil?", "stufe": 2})
        pruefungen.protokoll_speichern(self.con, self.lid, self.pid, {"schueler_id": s["Weiß"], "text": "Symbol eines Zylinders?", "stufe": 4})
        z = next(x for x in pruefungen.ergebnis(self.con, self.lid, self.pid)["schueler"] if x["name"].startswith("Weiß"))
        self.assertAlmostEqual(z["prozent"], 80.0)                     # ohne Gewicht: Fragen nur im Protokoll
        self.assertEqual([(e["stufe"], e["spontan"]) for e in z["protokoll"]], [(2, True), (4, True)])
        pruefungen.einstellungen_setzen(self.con, self.lid, self.pid, {"fragen_gewicht": 1, "minuten": 20})
        e = pruefungen.ergebnis(self.con, self.lid, self.pid)
        z = next(x for x in e["schueler"] if x["name"].startswith("Weiß"))
        self.assertEqual((e["pruefung"]["einstellungen"]["minuten"], e["pruefung"]["einstellungen"]["vorwarnung"]), (20, 2))
        self.assertAlmostEqual(z["prozent"], (3 * 80 + 1 * 75) / 4)     # Fragen (2+4)/8 = 75 % mit Gewicht 1
        self.assertIn("Fragen (Gewicht 1): 2/4, 4/4 → 75 %", z["rechenweg"])
        pruefungen.protokoll_speichern(self.con, self.lid, self.pid, {"in_pool": True}, eid)
        self.assertEqual([f["text"] for f in pruefungen.fragen(self.con, self.pid)], ["Wozu dient ein Rückschlagventil?"])
        with self.assertRaises(pruefungen.PruefungFehler):
            pruefungen.protokoll_speichern(self.con, self.lid, self.pid, {"stufe": 7}, eid)
        pruefungen.lauf_setzen(self.con, self.lid, self.pid, s["Schmitt"], "start")
        self.con.execute("UPDATE bewertung SET beginn = '2020-01-01T07:50:00' WHERE schueler_id = ?", (s["Schmitt"],))
        pruefungen.lauf_setzen(self.con, self.lid, self.pid, s["Schmitt"], "ende")
        z = next(x for x in pruefungen.ergebnis(self.con, self.lid, self.pid)["schueler"] if x["name"].startswith("Schmitt"))
        self.assertTrue(z["beginn"].startswith("2020-01-01T07:50") and z["dauer"] > 0)
        self.assertIsNone(z["prozent"])                                # Dauer allein ist keine Bewertung


class Exporte(MitPruefung):
    def setUp(self):
        super().setUp()
        self.pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Klassenarbeit LF 7", form="termin", datum="2026-11-20", beginn="07:45", erfassung="aufgaben",
            aufgaben=[{"name": "A1", "max": 20}, {"name": "A2", "max": 30}]))
        s = self.ids()
        pruefungen.bewertung_setzen(self.con, self.lid, self.pid, s["Weiß"], {"werte": {"k1": 20, "k2": 22}, "notiz": "Gute Herleitung."})
        pruefungen.bewertung_setzen(self.con, self.lid, self.pid, s["Schmitt"], {"fehlt": True})
        pruefungen.schueler_speichern(self.con, self.lid, {"nachname": "Yılmaz", "vorname": "Deniz", "aktiv": False}, s["Yılmaz"])
        pruefungen.schueler_speichern(self.con, self.lid, {"klasse_id": self.kl, "nachname": "Adler", "vorname": "Ben"})

    def test_notenspalte_alle_alphabetisch_mit_komma(self):
        z = exporte.notenspalte(self.con, self.lid, self.pid)
        self.assertEqual([x["name"] for x in z], ["Adler, Ben", "Schmitt, Lea", "Weiß, Clara", "Yılmaz, Deniz"])   # auch ausgetretene
        self.assertEqual([x["note"] for x in z], ["", "", "1,7", ""])                                                # 84 % = 2+ = 1,7
        self.assertEqual([x["fehlt"] for x in z], [False, True, False, False])

    def test_moodle_csv(self):
        text, ohne = exporte.moodle_csv(self.con, self.lid, self.pid)
        self.assertEqual(text.strip().splitlines(), ["E-Mail-Adresse,Bewertung,Feedback", "clara@schule.de,84.00,Note 2+ · 84 %"])
        self.assertEqual(ohne, [])
        adler = next(x for x in pruefungen.schueler(self.con, self.lid, self.kl) if x["nachname"] == "Adler")
        pruefungen.bewertung_setzen(self.con, self.lid, self.pid, adler["id"], {"werte": {"k1": 10, "k2": 10}})
        self.assertEqual(exporte.moodle_csv(self.con, self.lid, self.pid)[1], ["Adler, Ben"])   # ohne E-Mail: nicht zuordenbar

    def test_pdfs(self):
        inhalt, name = exporte.ergebnis_pdf(self.con, self.lid, self.pid, "Matthias Göbel")
        self.assertTrue(inhalt.startswith(b"%PDF-1.4") and inhalt.rstrip().endswith(b"%%EOF"))
        self.assertEqual(name, "Ergebnis BSMT 24a Klassenarbeit LF 7.pdf")
        self.assertIn("Weiß, Clara".encode("cp1252"), inhalt)
        self.assertEqual(pdf._ersetzen("Yılmaz, Şahin, Łukasz, Dvořák, Müller"), "Yilmaz, Sahin, Lukasz, Dvorák, Müller")   # á kennt cp1252
        inhalt, name = exporte.rueckmeldung_pdf(self.con, self.lid, self.pid)
        self.assertEqual(inhalt.count(b"/Type /Page "), 1)                 # nur Weiß ist bewertet (Schmitt fehlt)
        self.assertIn("Gute Herleitung.".encode("cp1252"), inhalt)
        self.assertNotIn("Schmitt".encode("cp1252"), inhalt)               # keine Daten anderer
        with self.assertRaises(pruefungen.PruefungFehler):
            exporte.rueckmeldung_pdf(self.con, self.lid, self.pid, self.ids()["Schmitt"])

if __name__ == "__main__":
    unittest.main()
