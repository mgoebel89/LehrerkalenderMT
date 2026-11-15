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
        self.assertEqual(belegung[3], (2, 2, 3))

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

    def test_bibliothek_und_uebernehmen(self):
        ls = planung.baustein_speichern(self.con, self.k, {"art": "ls", "lernfeld_id": self.lf7, "titel": "Förderanlage automatisieren"})
        planung.baustein_speichern(self.con, self.k, {"art": "thema", "ls_id": ls, "titel": "Sensoren", "bloecke": 3})
        planung.baustein_speichern(self.con, self.k, {"art": "thema", "ls_id": ls, "titel": "SPS-Grundlagen", "bloecke": 4})
        leer = planung.baustein_speichern(self.con, self.k, {"art": "ls", "lernfeld_id": self.lf7, "titel": "Presse", "bloecke": 8})
        einzel = planung.baustein_speichern(self.con, self.k, {"art": "thema", "lernfeld_id": self.lf7, "titel": "Wiederholung", "bloecke": 1})
        bib = planung.bibliothek(self.con, self.bs)
        lf7 = next(lf for lf in bib if lf["id"] == self.lf7)
        self.assertEqual([(x["titel"], x["umfang"]) for x in lf7["lernsituationen"]], [("Förderanlage automatisieren", 7), ("Presse", 8)])
        self.assertEqual([t["titel"] for t in lf7["themen"]], ["Wiederholung"])
        with self.assertRaises(planung.PlanungFehler):                 # fremder Baustein
            planung.baustein_speichern(self.con, self.r, {"titel": "x", "bloecke": 1}, einzel)
        for b in (ls, leer, einzel):
            planung.aus_bibliothek(self.con, self.lid, self.strang(baustein_id=b))
        p = self.plan()
        self.assertEqual([(t["titel"], t["bloecke"], t["ls_titel"]) for t in p["themen"]],
                         [("Sensoren", 3, "Förderanlage automatisieren"), ("SPS-Grundlagen", 4, "Förderanlage automatisieren"),
                          ("Presse", 8, "Presse"), ("Wiederholung", 1, "")])
        self.assertIn("BSMT 24a", next(lf for lf in planung.bibliothek(self.con, self.bs) if lf["id"] == self.lf7)["lernsituationen"][0]["genutzt"])
        planung.baustein_loeschen(self.con, self.k, ls)                # Planung behaelt ihre Kopie
        self.assertEqual(len(self.plan()["themen"]), 4)

    def test_straenge_und_wochenplan_thema(self):
        g1 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 1"})
        stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 3, "beginn": "07:45", "ende": "09:15",
                                                             "eintraege": [{"klasse_id": self.k24, "gruppe_id": g1}]})
        namen = [s["name"] for s in planung.straenge(self.con, self.lid, self.sj)]
        self.assertEqual(namen, ["BSMT 24a · ganze Klasse", "BSMT 24a · Gr. 1"])
        planung.thema_speichern(self.con, self.lid, self.strang(titel="Theorie", bloecke=1))
        planung.thema_speichern(self.con, self.lid, self.strang(gruppe_id=g1, titel="Labor", bloecke=2))
        w = planung.themen_der_woche(self.con, self.lid, stundenplan.woche(self.con, self.lid, D("2026-11-16"), "2026-11-15T12:00:00"))
        self.assertEqual([(b["datum"], b["thema"]["titel"] if b["thema"] else None) for b in w["bloecke"]],
                         [("2026-11-16", "Theorie"), ("2026-11-18", "Labor"), ("2026-11-20", None)])
        with self.assertRaises(stundenplan.StundenplanFehler):        # Gruppe mit Planung
            stundenplan.gruppe_loeschen(self.con, self.lid, g1)
        with self.assertRaises(planung.PlanungFehler):                # fremdes Thema
            planung.thema_loeschen(self.con, self.r["id"], self.plan()["themen"][0]["id"])


if __name__ == "__main__":
    unittest.main()
