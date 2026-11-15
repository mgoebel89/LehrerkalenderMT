"""Tests fuer Stufe C1: Schuljahr, Bibliothek, Themenfolge, Fliessen (mit Spuren, Stecknadeln, Ausfall), Wochenplan-Thema.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import datetime
import shutil
import tempfile
import unittest

from app import db, grunddaten, konten, planung, stundenplan

D = datetime.date.fromisoformat
RASTER = [{"bezeichnung": "%d. Block" % (i + 1), "beginn": b, "ende": e} for i, (b, e) in
          enumerate([("07:45", "09:15"), ("09:30", "11:00"), ("11:30", "13:00")])]


class Fliessen(unittest.TestCase):
    """Die reine Verteilung, ohne Datenbank."""

    def bl(self, n, lf=None):
        return [{"datum": "2026-11-%02d" % (i + 1), "beginn": "07:45", "lernfeld_id": lf} for i in range(n)]

    def th(self, tid, n, lf=None, fest=None):
        return {"id": tid, "bloecke": n, "lernfeld_id": lf, "fest_datum": fest, "fest_beginn": "07:45" if fest else None}

    def test_reihenfolge_und_ueberlauf(self):
        belegung, info = planung.fliessen([self.th(1, 2), self.th(2, 3)], self.bl(4))
        self.assertEqual([b[0] if b else None for b in belegung], [1, 1, 2, 2])
        self.assertEqual((info[2]["zugeteilt"], info[2]["ueberlauf"]), (2, 1))
        self.assertEqual(belegung[3], (2, 2, 3, None))

    def test_stecknadel_bleibt_stehen_und_der_rest_fliesst_drumherum(self):
        belegung, info = planung.fliessen([self.th(1, 2), self.th(9, 2, fest="2026-11-03"), self.th(2, 3)], self.bl(8))
        self.assertEqual([b[0] if b else None for b in belegung], [1, 1, 9, 9, 2, 2, 2, None])
        self.assertEqual(info[9]["nadel"], "ok")
        belegung, info = planung.fliessen([self.th(9, 1, fest="2027-01-01")], self.bl(2))
        self.assertEqual(info[9]["nadel"], "fehlt")              # Block gibt es nicht: fliesst normal
        self.assertEqual(belegung[0][0], 9)

    def test_spuren_parallel(self):
        bloecke = self.bl(2, lf=7) + [dict(b, datum="2026-12-%02d" % (i + 1)) for i, b in enumerate(self.bl(2, lf=None))]
        belegung, info = planung.fliessen([self.th(1, 2, lf=9), self.th(2, 2, lf=7)], bloecke)
        # LF 7 hat eigene Bloecke; LF 9 hat keine und fliesst in die Bloecke ohne Lernfeld
        self.assertEqual([b[0] for b in belegung], [2, 2, 1, 1])


class MitPlanung(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.r = konten.anlegen(self.con, "rei", "Kollege Reiter", "lehrkraft", "geheim123", vorlaeufig=False)
            self.bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            self.lf7 = grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": self.bs, "nummer": "LF 7", "name": "Steuerungen", "stunden": 80})
            self.lf9 = grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": self.bs, "nummer": "LF 9", "name": "Antriebe", "stunden": 60})
            grunddaten.zeitraster_speichern(self.con, None, RASTER)
            self.k24 = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs})
            self.sj = grunddaten.schuljahr_speichern(self.con, {"name": "2026/27", "beginn": "2026-11-16", "ende": "2026-12-11"})
            grunddaten.ferien_anlegen(self.con, {"name": "Brückentag", "von": "2026-11-27", "bis": "2026-11-27"})
            self.v = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2026-08-01"})
            for tag in (1, 5):   # Mo und Fr je 1. Block
                stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": tag, "beginn": "07:45", "ende": "09:15",
                                                                     "eintraege": [{"klasse_id": self.k24}]})

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @property
    def lid(self):
        return self.k["id"]

    def strang(self, **mehr):
        return dict({"klasse_id": self.k24, "gruppe_id": None, "schuljahr_id": self.sj}, **mehr)

    def plan(self):
        return planung.plan(self.con, self.lid, self.k24, None, self.sj, jetzt="2026-11-15T12:00:00")


class Planung(MitPlanung):
    def test_schuljahr_regeln(self):
        with self.assertRaises(grunddaten.GrunddatenFehler):   # ueberschneidet sich
            grunddaten.schuljahr_speichern(self.con, {"name": "x", "beginn": "2026-12-01", "ende": "2027-01-31"})
        self.assertEqual(grunddaten.schuljahr_zum(self.con, "2026-11-20")["id"], self.sj)
        self.assertIsNone(grunddaten.schuljahr_zum(self.con, "2027-03-01"))

    def test_bloecke_ohne_ferien_und_ausfall(self):
        # Mo/Fr vom 16.11. bis 11.12. = 8 Bloecke, Fr 27.11. Brueckentag -> 7
        p = self.plan()
        self.assertEqual(p["summe"]["bloecke"], 7)
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-16", "beginn": "07:45"})
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "zusatz", "datum": "2026-11-18", "beginn": "09:30", "klasse_id": self.k24})
        p = self.plan()
        self.assertEqual(p["summe"]["bloecke"], 7)                       # -1 Ausfall, +1 Zusatzstunde
        self.assertEqual(p["bloecke"][0]["datum"], "2026-11-18")
        self.assertEqual(p["weg"][0]["zustand"], "ausfall")

    def test_themen_fliessen_und_rutschen_bei_ausfall(self):
        t1 = planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS-Grundlagen", bloecke=2, lernfeld_id=self.lf7))
        planung.thema_speichern(self.con, self.lid, self.strang(titel="GRAFCET", bloecke=3, lernfeld_id=self.lf7))
        p = self.plan()
        self.assertEqual([(t["titel"], t["von"], t["bis"]) for t in p["themen"]],
                         [("SPS-Grundlagen", "2026-11-16", "2026-11-20"), ("GRAFCET", "2026-11-23", "2026-12-04")])
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-20", "beginn": "07:45"})
        p = self.plan()
        self.assertEqual(p["themen"][0]["bis"], "2026-11-23")          # SPS braucht jetzt bis Montag
        self.assertEqual(p["themen"][1]["bis"], "2026-12-07")
        planung.thema_schieben(self.con, self.lid, t1, 1)              # Reihenfolge tauschen
        self.assertEqual(self.plan()["themen"][0]["titel"], "GRAFCET")

    def test_stecknadel_und_ueberlauf(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Lang", bloecke=5))
        ka = planung.thema_speichern(self.con, self.lid, self.strang(titel="Klassenarbeit", bloecke=1))
        planung.festsetzen(self.con, self.lid, ka, "2026-11-20", "07:45")
        p = self.plan()
        self.assertEqual(p["themen"][1]["von"], "2026-11-20")
        self.assertEqual(p["themen"][0]["von"], "2026-11-16")
        self.assertEqual(p["themen"][0]["bis"], "2026-12-07")          # fliesst um die Klassenarbeit herum (27.11. frei)
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Zu viel", bloecke=4))
        p = self.plan()
        self.assertEqual((p["themen"][2]["zugeteilt"], p["themen"][2]["ueberlauf"]), (1, 3))
        planung.festsetzen(self.con, self.lid, ka, None, None)
        self.assertEqual(self.plan()["themen"][1]["von"], "2026-12-07")

    def test_spur_lernfeld_am_block(self):
        stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 5, "beginn": "07:45", "ende": "09:15",
                                                             "eintraege": [{"klasse_id": self.k24, "lernfeld_id": self.lf9}]})
        planung.thema_speichern(self.con, self.lid, self.strang(titel="LF7 Thema", bloecke=2, lernfeld_id=self.lf7))
        planung.thema_speichern(self.con, self.lid, self.strang(titel="LF9 Thema", bloecke=2, lernfeld_id=self.lf9))
        p = self.plan()
        self.assertEqual([(t["titel"], t["von"], t["bis"]) for t in p["themen"]],
                         [("LF7 Thema", "2026-11-16", "2026-11-23"), ("LF9 Thema", "2026-11-20", "2026-12-04")])
        self.assertEqual([s["nummer"] for s in p["spuren"]], ["LF 9"])

    def test_ausschulung_und_spaeter_beginn(self):
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Lang", bloecke=6))
        with db.transaktion(self.con):
            grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs, "beginn": "2026-11-18",
                                                   "ende": "2026-11-30"}, self.k24)
        p = self.plan()
        self.assertEqual([b["datum"] for b in p["bloecke"]], ["2026-11-20", "2026-11-23", "2026-11-30"])
        self.assertEqual(p["themen"][0]["ueberlauf"], 3)
        self.assertEqual(p["klasse_zeitraum"], {"beginn": "2026-11-18", "ende": "2026-11-30"})
        w = stundenplan.woche(self.con, self.lid, D("2026-12-07"))           # nach der Ausschulung: keine Stunden
        self.assertEqual(w["bloecke"], [])
        with self.assertRaises(stundenplan.StundenplanFehler):               # Zusatzstunde nach der Ausschulung
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "zusatz", "datum": "2026-12-02", "beginn": "07:45", "klasse_id": self.k24})
        with self.assertRaises(stundenplan.StundenplanFehler):               # dorthin verschieben auch nicht
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "verschoben", "datum": "2026-11-30", "beginn": "07:45",
                                                               "ziel_datum": "2026-12-02", "ziel_beginn": "07:45"})
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs, "beginn": "2026-12-01",
                                                   "ende": "2026-11-30"}, self.k24)

    def test_bibliothek_und_uebernehmen(self):
        # Bibliothek: Lernfeld -> Thema (Budget) -> Lernsituationen
        th = planung.baustein_speichern(self.con, self.k, {"art": "thema", "lernfeld_id": self.lf7, "titel": "SPS-Programmierung", "bloecke": 10})
        planung.baustein_speichern(self.con, self.k, {"art": "ls", "eltern_id": th, "titel": "Förderanlage", "bloecke": 4})
        planung.baustein_speichern(self.con, self.k, {"art": "ls", "eltern_id": th, "titel": "Presse", "bloecke": 3})
        leer = planung.baustein_speichern(self.con, self.k, {"art": "thema", "lernfeld_id": self.lf7, "titel": "Wiederholung", "bloecke": 1})
        with self.assertRaises(planung.PlanungFehler):                 # LS ohne Thema
            planung.baustein_speichern(self.con, self.k, {"art": "ls", "lernfeld_id": self.lf7, "titel": "x", "bloecke": 1})
        lf7 = next(lf for lf in planung.bibliothek(self.con, self.bs) if lf["id"] == self.lf7)
        self.assertEqual([(t["titel"], t["bloecke"], t["verteilt"], [l["titel"] for l in t["lernsituationen"]]) for t in lf7["themen"]],
                         [("SPS-Programmierung", 10, 7, ["Förderanlage", "Presse"]), ("Wiederholung", 1, 0, [])])
        with self.assertRaises(planung.PlanungFehler):                 # fremder Baustein
            planung.baustein_speichern(self.con, self.r, {"titel": "x", "bloecke": 1}, leer)
        self.assertEqual(planung.aus_bibliothek(self.con, self.lid, self.strang(baustein_id=th)), 2)
        p = self.plan()
        t = p["themen"][0]
        self.assertEqual((t["titel"], t["bloecke"], t["verteilt"], [l["titel"] for l in t["ls"]]), ("SPS-Programmierung", 10, 7, ["Förderanlage", "Presse"]))
        # eine einzelne LS aus der Bibliothek in ein vorhandenes Thema der Planung
        einzel = planung.baustein_speichern(self.con, self.k, {"art": "ls", "eltern_id": leer, "titel": "Logik-Quiz", "bloecke": 1})
        planung.aus_bibliothek(self.con, self.lid, {"baustein_id": einzel, "thema_id": t["id"]})
        self.assertEqual([l["titel"] for l in self.plan()["themen"][0]["ls"]], ["Förderanlage", "Presse", "Logik-Quiz"])
        self.assertIn("BSMT 24a", next(x for x in planung.bibliothek(self.con, self.bs)[0]["themen"] if x["id"] == th)["genutzt"])
        planung.baustein_loeschen(self.con, self.k, th)                 # Planung behaelt ihre Kopie
        self.assertEqual(len(self.plan()["themen"][0]["ls"]), 3)

    def test_thema_als_budget_mit_lernsituationen(self):
        # Mo/Fr ab 16.11., 27.11. frei: Bloecke 16, 20, 23, 30, 4.12., 7.12., 11.12.
        t1 = planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=4))
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Danach", bloecke=1))
        a = planung.ls_speichern(self.con, self.lid, {"thema_id": t1, "titel": "LS A", "bloecke": 2})
        p = self.plan()
        t = p["themen"][0]
        self.assertEqual((t["bedarf"], t["offen"], t["ls"][0]["von"], t["ls"][0]["bis"]), (4, 2, "2026-11-16", "2026-11-20"))
        self.assertEqual([b["ls_id"] for b in p["bloecke"][:4]], [a, a, None, None])     # danach "noch offen"
        self.assertEqual(p["themen"][1]["von"], "2026-12-04")
        # LS brauchen mehr als das Budget: das Thema waechst
        planung.ls_speichern(self.con, self.lid, {"thema_id": t1, "titel": "LS B", "bloecke": 3})
        p = self.plan()
        self.assertEqual((p["themen"][0]["bedarf"], p["themen"][0]["offen"]), (5, 0))
        self.assertEqual(p["themen"][1]["von"], "2026-12-07")
        # Ist: LS A ist schon nach einem Block fertig -> LS B rueckt vor; Bedarf = max(Budget 4, 1 + 3) = 4
        planung.ist_setzen(self.con, self.lid, "2026-11-16", "07:45", "fertig")
        p = self.plan()
        self.assertEqual(p["themen"][0]["bedarf"], 4)                                      # max(Budget 4, 1 + 3)
        self.assertEqual([b["ls_id"] is not None for b in p["bloecke"][:4]], [True, True, True, True])
        with self.assertRaises(planung.PlanungFehler):                                     # fremde LS
            planung.ls_loeschen(self.con, self.r["id"], a)
        planung.ls_schieben(self.con, self.lid, a, 1)
        self.assertEqual([l["titel"] for l in self.plan()["themen"][0]["ls"]], ["LS B", "LS A"])

    def test_straenge_und_wochenplan_thema(self):
        """Eine Themenfolge je Klasse; G1 und G2 am selben Tag bilden einen Schritt (denselben Stoff)."""
        g1 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 1"})
        g2 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 2"})
        stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 3, "beginn": "07:45", "ende": "09:15",
                                                             "eintraege": [{"klasse_id": self.k24, "gruppe_id": g1}]})
        stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 3, "beginn": "09:30", "ende": "11:00",
                                                             "eintraege": [{"klasse_id": self.k24, "gruppe_id": g2}]})
        st = planung.straenge(self.con, self.lid, self.sj)
        self.assertEqual([(s["name"], s["gruppe_id"], s["gruppen"]) for s in st], [("BSMT 24a", None, ["Gr. 1", "Gr. 2"])])
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Theorie", bloecke=1))
        planung.thema_speichern(self.con, self.lid, self.strang(gruppe_id=g1, titel="Labor", bloecke=2))   # Gruppe wird ignoriert
        w = planung.themen_der_woche(self.con, self.lid, stundenplan.woche(self.con, self.lid, D("2026-11-16"), "2026-11-15T12:00:00"))
        self.assertEqual([(b["datum"], b["beginn"], b["thema"]["titel"] if b["thema"] else None, b["thema"]["teil"] if b["thema"] else None)
                          for b in w["bloecke"]],
                         [("2026-11-16", "07:45", "Theorie", 1), ("2026-11-18", "07:45", "Labor", 1), ("2026-11-18", "09:30", "Labor", 1),
                          ("2026-11-20", "07:45", "Labor", 2)])
        p = self.plan()
        # 4 Wochen je 3 Schritte (Mo, Mi gepaart, Fr), Brueckentag Fr 27.11. faellt weg
        self.assertEqual((p["summe"]["bloecke"], p["summe"]["geteilt"]), (11, 4))
        self.assertEqual([b["zweit"] for b in p["bloecke"][:4]], [False, False, True, False])
        s = planung.stunde(self.con, self.lid, "2026-11-18", "09:30", jetzt="2026-11-15T12:00:00")
        self.assertEqual((s["thema"]["titel"], s["geteilt"]), ("Labor", ["Gr. 1"]))
        self.assertEqual((s["vorige"]["datum"], s["naechste"]["datum"]), ("2026-11-16", "2026-11-20"))   # nicht die G1-Stunde davor
        with self.assertRaises(planung.PlanungFehler):                # fremdes Thema
            planung.thema_loeschen(self.con, self.r["id"], self.plan()["themen"][0]["id"])

    def test_ausfall_einer_gruppe_holt_nach(self):
        g1 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 1"})
        g2 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 2"})
        for beginn, ende, g in (("07:45", "09:15", g1), ("09:30", "11:00", g2)):
            stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 3, "beginn": beginn, "ende": ende,
                                                                 "eintraege": [{"klasse_id": self.k24, "gruppe_id": g}]})
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Theorie", bloecke=1))
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Labor", bloecke=3))
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-18", "beginn": "09:30", "grund": "krank"})
        p = self.plan()
        self.assertEqual(p["summe"]["bloecke"], 11)                   # G1 hatte den Schritt allein: der Plan laeuft weiter
        mi = [b for b in p["bloecke"] if b["datum"] == "2026-11-18"]
        self.assertEqual([(b["beginn"], b["thema_id"] is not None, b["zweit"]) for b in mi], [("07:45", True, False)])
        naechste_g2 = next(b for b in p["bloecke"] if b["datum"] == "2026-11-25" and b["beginn"] == "09:30")
        self.assertEqual([(n["datum"], n["gruppe"], n["thema"]) for n in naechste_g2["nachholen"]], [("2026-11-18", "Gr. 2", "Labor")])
        # Faellt G1 aus, wird G2 nicht mit dem 2. G1-Block gepaart (gibt es nicht) und haelt den Schritt allein
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-25", "beginn": "07:45", "grund": "Messe"})
        p = self.plan()
        mi = [b for b in p["bloecke"] if b["datum"] == "2026-11-25"]
        self.assertEqual([(b["beginn"], b["zweit"]) for b in mi], [("09:30", False)])

    def test_schritte_bilden(self):
        def b(datum, beginn, g=None):
            return {"datum": datum, "beginn": beginn, "gruppe_id": g}
        bl = [b("d1", "1"), b("d2", "1", 1), b("d2", "2", 1), b("d2", "3", 2), b("d2", "4", 2), b("d3", "1", 1)]
        self.assertEqual(planung.schritte_bilden(bl), [[0], [1, 3], [2, 4], [5]])
        # 1. G1-Block faellt aus: der 2. G1-Block gehoert zum 2. G2-Block
        bl = [b("d2", "2", 1), b("d2", "3", 2), b("d2", "4", 2)]
        self.assertEqual(planung.schritte_bilden(bl, [b("d2", "1", 1)]), [[0, 2], [1]])


class FliessenMitIst(Fliessen):
    def test_mehr_und_fertig(self):
        bl = self.bl(6)
        themen = [self.th(1, 2), self.th(2, 2)]
        # Block 2 (Thema 1, Teil 2): braucht einen mehr -> Thema 1 hat 3 Bloecke, Thema 2 rutscht
        belegung, info = planung.fliessen(themen, bl, {("2026-11-02", "07:45"): "mehr"})
        self.assertEqual([b[0] if b else None for b in belegung], [1, 1, 1, 2, 2, None])
        self.assertEqual(info[1]["bedarf"], 3)
        # Block 1: schon fertig -> Thema 2 rueckt vor
        belegung, info = planung.fliessen(themen, bl, {("2026-11-01", "07:45"): "fertig"})
        self.assertEqual([b[0] if b else None for b in belegung], [1, 2, 2, None, None, None])
        self.assertEqual(belegung[0], (1, 1, 1, None))

    def test_ferienabschnitte(self):
        frei = {"2026-10-12": "Herbstferien", "2026-10-13": "Herbstferien", "2026-10-16": "Herbstferien", "2026-10-19": "Herbstferien",
                "2026-11-01": "Allerheiligen"}
        a = planung.ferienabschnitte(frei, D("2026-10-01"), D("2026-11-30"))
        self.assertEqual([(x["name"], x["von"], x["bis"]) for x in a],
                         [("Herbstferien", "2026-10-12", "2026-10-13"), ("Herbstferien", "2026-10-16", "2026-10-19")])
        # Allerheiligen 2026 ist ein Sonntag: kein Werktag, kein Abschnitt
        frei = {"2026-12-23": "Weihnachtsferien", "2026-12-24": "Weihnachtsferien", "2026-12-25": "1. Weihnachtstag",
                "2026-12-28": "Weihnachtsferien", "2026-12-31": "Weihnachtsferien", "2027-01-01": "Neujahr"}
        frei.update({"2026-12-29": "Weihnachtsferien", "2026-12-30": "Weihnachtsferien"})
        a = planung.ferienabschnitte(frei, D("2026-12-01"), D("2027-01-31"))
        self.assertEqual([(x["name"], x["von"], x["bis"]) for x in a], [("Weihnachtsferien", "2026-12-23", "2027-01-01")])


class IstStand(MitPlanung):
    def setUp(self):
        super().setUp()
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=2, lernfeld_id=self.lf7))
        planung.thema_speichern(self.con, self.lid, self.strang(titel="GRAFCET", bloecke=2, lernfeld_id=self.lf7))

    def test_stunde_und_ist(self):
        s = planung.stunde(self.con, self.lid, "2026-11-20", "07:45", jetzt="2026-11-25T12:00:00")
        self.assertEqual((s["thema"]["titel"], s["thema"]["teil"], s["thema"]["von"]), ("SPS", 2, 2))
        self.assertEqual(s["naechste"]["datum"], "2026-11-23")
        self.assertEqual(s["vorige"]["datum"], "2026-11-16")
        planung.ist_setzen(self.con, self.lid, "2026-11-20", "07:45", "mehr")
        p = self.plan()
        self.assertEqual([(t["titel"], t["bedarf"], t["bis"]) for t in p["themen"]], [("SPS", 3, "2026-11-23"), ("GRAFCET", 2, "2026-12-04")])
        planung.ist_setzen(self.con, self.lid, "2026-11-20", "07:45", None)   # Rueckgaengig
        self.assertEqual(self.plan()["themen"][0]["bedarf"], 2)
        with self.assertRaises(planung.PlanungFehler):                        # dort keine Stunde
            planung.ist_setzen(self.con, self.lid, "2026-11-17", "07:45", "ok")

    def test_offene_ist_und_alle_bestaetigen(self):
        offen = planung.offene_ist(self.con, self.lid, jetzt="2026-11-24T08:00:00")
        self.assertEqual([o["datum"] for o in offen], ["2026-11-23", "2026-11-20", "2026-11-16"])
        planung.ist_setzen(self.con, self.lid, "2026-11-16", "07:45", "ok")
        self.assertEqual(len(planung.offene_ist(self.con, self.lid, jetzt="2026-11-24T08:00:00")), 2)
        self.assertEqual(planung.ist_alle_bestaetigen(self.con, self.lid, jetzt="2026-11-24T08:00:00"), 2)
        self.assertEqual(planung.offene_ist(self.con, self.lid, jetzt="2026-11-24T08:00:00"), [])

    def test_vertretung_mit_und_ohne_thema(self):
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "vertreten", "datum": "2026-11-20", "beginn": "07:45", "wer": "Kollege R.",
                                                           "thema_weiter": True})
        p = self.plan()
        self.assertEqual(p["themen"][0]["bis"], "2026-11-20")              # zaehlt als gehalten, nichts rutscht
        self.assertEqual(p["bloecke"][1]["art"], "vertreten")
        jetzt = "2026-11-24T08:00:00"
        self.assertEqual([o["datum"] for o in planung.offene_ist(self.con, self.lid, jetzt=jetzt)], ["2026-11-23", "2026-11-16"])
        s = planung.stunde(self.con, self.lid, "2026-11-20", "07:45", jetzt=jetzt)   # Ist darf, muss aber nicht
        self.assertEqual((s["vertreten"]["wer"], s["thema"]["titel"], s["aendern"]), ("Kollege R.", "SPS", False))
        planung.ist_setzen(self.con, self.lid, "2026-11-20", "07:45", "mehr")
        self.assertEqual(self.plan()["themen"][0]["bis"], "2026-11-23")
        w = planung.themen_der_woche(self.con, self.lid, stundenplan.woche(self.con, self.lid, D("2026-11-16"), jetzt))
        fr = next(b for b in w["bloecke"] if b["datum"] == "2026-11-20")
        self.assertEqual((fr["zustand"], fr["thema"]["titel"], fr["ist"]), ("vertreten", "SPS", "mehr"))
        # eigener Stoff: zaehlt nicht, das Thema wartet
        a = next(b for b in w["bloecke"] if b["datum"] == "2026-11-20")["aenderung_id"]
        stundenplan.aenderung_loeschen(self.con, self.lid, a)
        planung.ist_setzen(self.con, self.lid, "2026-11-16", "07:45", "ok")
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "vertreten", "datum": "2026-11-20", "beginn": "07:45", "thema_weiter": False})
        self.assertEqual(self.plan()["themen"][0]["bis"], "2026-11-23")
        with self.assertRaises(planung.PlanungFehler):
            planung.stunde(self.con, self.lid, "2026-11-20", "07:45", jetzt=jetzt)

    def test_bilanz_und_wochenplan(self):
        p = planung.plan(self.con, self.lid, self.k24, None, self.sj, jetzt="2026-11-21T12:00:00")
        lf7 = next(b for b in p["bilanz"] if b["lernfeld_id"] == self.lf7)
        self.assertEqual((lf7["ansatz"], lf7["verplant"], lf7["gehalten"]), (40, 4, 2))
        self.assertEqual(p["summe"]["ist_offen"], 2)
        self.assertEqual([f["name"] for f in p["ferien"]], ["Brückentag"])
        planung.ist_setzen(self.con, self.lid, "2026-11-16", "07:45", "fertig")
        w = planung.themen_der_woche(self.con, self.lid, stundenplan.woche(self.con, self.lid, D("2026-11-16"), "2026-11-21T12:00:00"))
        self.assertEqual([(b["thema"]["titel"], b["ist"]) for b in w["bloecke"]], [("SPS", "fertig"), ("GRAFCET", None)])


if __name__ == "__main__":
    unittest.main()
