"""Tests fuer Stufe B: Feiertage, A/B-Wochen, Stundenplan mit Versionen, Wochenplan mit Aenderungen, Termine, Raster-Umzug.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import datetime
import http.client
import json
import shutil
import tempfile
import threading
import unittest

from app import db, grunddaten, konten, server, stundenplan

D = datetime.date.fromisoformat
SCHULRASTER = [{"bezeichnung": "%d. Block" % (i + 1), "beginn": b, "ende": e} for i, (b, e) in
               enumerate([("07:45", "09:15"), ("09:30", "11:00"), ("11:30", "13:00"), ("13:15", "14:45")])]
FS_RASTER = [{"bezeichnung": "FS 1", "beginn": "17:15", "ende": "18:45"}, {"bezeichnung": "FS 2", "beginn": "19:00", "ende": "20:30"}]


class Kalenderrechnung(unittest.TestCase):
    def test_ostern_und_feiertage_rlp(self):
        self.assertEqual(stundenplan.ostersonntag(2027), D("2027-03-28"))
        self.assertEqual(stundenplan.ostersonntag(2026), D("2026-04-05"))
        f = stundenplan.feiertage_rlp(2027)
        self.assertEqual(f["2027-03-26"], "Karfreitag")
        self.assertEqual(f["2027-05-06"], "Christi Himmelfahrt")
        self.assertEqual(f["2027-05-17"], "Pfingstmontag")
        self.assertEqual(f["2027-05-27"], "Fronleichnam")
        self.assertEqual(f["2027-11-01"], "Allerheiligen")
        self.assertEqual(len(f), 11)

    def test_ab_woche(self):
        self.assertEqual(stundenplan.ab_woche(D("2026-11-23"), "ungerade"), "B")   # KW 48
        self.assertEqual(stundenplan.ab_woche(D("2026-11-16"), "ungerade"), "A")   # KW 47
        self.assertEqual(stundenplan.ab_woche(D("2026-11-16"), "gerade"), "B")


class MitStundenplan(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.k = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.bs = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
            self.fs = grunddaten.bildungsgang_speichern(self.con, {"name": "Fachschule Technik", "kuerzel": "FT"})
            grunddaten.zeitraster_speichern(self.con, None, SCHULRASTER)
            grunddaten.zeitraster_speichern(self.con, self.fs, FS_RASTER)
            self.k24 = grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": self.bs})
            self.k22 = grunddaten.klasse_speichern(self.con, {"name": "BSMT 22b", "bildungsgang_id": self.bs})
            self.ft = grunddaten.klasse_speichern(self.con, {"name": "FT 25", "bildungsgang_id": self.fs})
            self.v1 = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2026-08-01", "name": "1. Halbjahr"})
            # Mo 1+2 BSMT 24a, Mi 3 A: 24a / B: 22b, Di FS 1 FT 25
            self.feld(self.v1, 1, "07:45", "09:15", [{"klasse_id": self.k24}])
            self.feld(self.v1, 1, "09:30", "11:00", [{"klasse_id": self.k24}])
            self.feld(self.v1, 3, "11:30", "13:00", [{"klasse_id": self.k24, "woche": "A"}, {"klasse_id": self.k22, "woche": "B"}])
            self.feld(self.v1, 2, "17:15", "18:45", [{"klasse_id": self.ft}])

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    @property
    def lid(self):
        return self.k["id"]

    def feld(self, vid, tag, beginn, ende, eintraege):
        stundenplan.feld_setzen(self.con, self.lid, vid, {"wochentag": tag, "beginn": beginn, "ende": ende, "eintraege": eintraege})

    def woche(self, montag, jetzt="2026-11-18T12:00:00"):
        return stundenplan.woche(self.con, self.lid, D(montag), jetzt)

    def namen(self, w, datum):
        return [(b["beginn"], b["klasse"]["name"] if b["klasse"] else b.get("klasse_text"), b["art"], b["zustand"])
                for b in w["bloecke"] if b["datum"] == datum]


class Stundenplan(MitStundenplan):
    def test_ab_wochen_und_zeilen_nach_uhrzeit(self):
        a = self.woche("2026-11-16")   # KW 47 = A
        b = self.woche("2026-11-23")   # KW 48 = B
        self.assertEqual(a["ab"], "A")
        self.assertEqual(self.namen(a, "2026-11-18"), [("11:30", "BSMT 24a", "regulaer", None)])
        self.assertEqual(self.namen(b, "2026-11-25"), [("11:30", "BSMT 22b", "regulaer", None)])
        self.assertEqual([z["beginn"] for z in a["zeilen"]], ["07:45", "09:30", "11:30", "13:15", "17:15", "19:00"])
        self.assertEqual(a["zeilen"][4]["raster"], "FT")
        self.assertTrue(a["bloecke"][0]["klasse"]["name"])
        self.assertEqual(len(set(a["farben"].values())), 3)

    def test_jetzt(self):
        w = self.woche("2026-11-16", jetzt="2026-11-18T12:10:00")
        self.assertTrue(next(b for b in w["bloecke"] if b["datum"] == "2026-11-18")["jetzt"])

    def test_regeln_im_feld(self):
        with self.assertRaises(stundenplan.StundenplanFehler):   # FT 25 hat keinen Block 07:45
            self.feld(self.v1, 4, "07:45", "09:15", [{"klasse_id": self.ft}])
        with self.assertRaises(stundenplan.StundenplanFehler):   # zwei Klassen nur als A und B
            self.feld(self.v1, 4, "07:45", "09:15", [{"klasse_id": self.k24}, {"klasse_id": self.k22}])
        self.feld(self.v1, 1, "07:45", "09:15", [])               # leeren
        self.assertEqual(self.namen(self.woche("2026-11-16"), "2026-11-16"), [("09:30", "BSMT 24a", "regulaer", None)])

    def test_versionen_gelten_ab_datum_und_tag_kopieren(self):
        v2 = stundenplan.version_anlegen(self.con, self.lid, {"ab": "2027-02-01", "name": "2. Halbjahr", "kopie_von": self.v1})
        stundenplan.tag_kopieren(self.con, self.lid, v2, 1, 5)    # Montag auch am Freitag
        self.feld(v2, 1, "07:45", "09:15", [{"klasse_id": self.k22}])
        alt = self.woche("2027-01-25")
        neu = self.woche("2027-02-01")
        self.assertEqual(self.namen(alt, "2027-01-25")[0][1], "BSMT 24a")
        self.assertEqual(self.namen(neu, "2027-02-01")[0][1], "BSMT 22b")
        self.assertEqual(len(self.namen(neu, "2027-02-05")), 2)
        self.assertEqual(len(self.namen(alt, "2027-01-29")), 0)
        vs = stundenplan.versionen(self.con, self.lid)
        self.assertEqual(vs[0]["bis"], "2027-01-31")
        with self.assertRaises(stundenplan.StundenplanFehler):
            stundenplan.version_anlegen(self.con, self.lid, {"ab": "2027-02-01"})

    def test_ferien_und_feiertage_sind_frei(self):
        with db.transaktion(self.con):
            grunddaten.ferien_anlegen(self.con, {"name": "Herbstferien", "von": "2026-10-12", "bis": "2026-10-23"})
        w = self.woche("2026-10-12")
        self.assertEqual(w["bloecke"], [])
        self.assertEqual(w["tage"][0]["frei"], "Herbstferien")
        w = self.woche("2027-05-17")   # Pfingstmontag
        self.assertEqual(w["tage"][0]["frei"], "Pfingstmontag")
        self.assertEqual(self.namen(w, "2027-05-17"), [])

    def test_fremder_stundenplan_ist_tabu(self):
        with db.transaktion(self.con):
            ander = konten.anlegen(self.con, "rei", "Kollege Reiter", "lehrkraft", "geheim123", vorlaeufig=False)
        with self.assertRaises(stundenplan.StundenplanFehler):
            stundenplan.feld_setzen(self.con, ander["id"], self.v1, {"wochentag": 1, "beginn": "07:45", "ende": "09:15", "eintraege": []})
        self.assertEqual(stundenplan.woche(self.con, ander["id"], D("2026-11-16"))["bloecke"], [])


class Aenderungen(MitStundenplan):
    def test_ausfall_vertreten_und_zuruecknehmen(self):
        aid = stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-16", "beginn": "07:45", "grund": "Exkursion"})
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "vertreten", "datum": "2026-11-16", "beginn": "09:30", "wer": "Kollege R."})
        w = self.woche("2026-11-16")
        self.assertEqual([b["zustand"] for b in w["bloecke"] if b["datum"] == "2026-11-16"], ["ausfall", "vertreten"])
        with self.assertRaises(stundenplan.StundenplanFehler):   # doppelt
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-16", "beginn": "07:45"})
        with self.assertRaises(stundenplan.StundenplanFehler):   # dort ist kein Unterricht
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "ausfall", "datum": "2026-11-17", "beginn": "07:45"})
        stundenplan.aenderung_loeschen(self.con, self.lid, aid)
        self.assertIsNone(self.woche("2026-11-16")["bloecke"][0]["zustand"])

    def test_verschieben_auch_in_die_naechste_woche(self):
        with self.assertRaises(stundenplan.StundenplanFehler):   # Fr 20.11. hat noch keinen Unterricht
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "verschoben", "datum": "2026-11-20", "beginn": "07:45",
                                                               "ziel_datum": "2026-11-24", "ziel_beginn": "09:30"})
        self.feld(self.v1, 5, "07:45", "09:15", [{"klasse_id": self.k22}])
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "verschoben", "datum": "2026-11-20", "beginn": "07:45",
                                                           "ziel_datum": "2026-11-24", "ziel_beginn": "09:30", "grund": "Messe"})
        w1, w2 = self.woche("2026-11-16"), self.woche("2026-11-23")
        weg = next(b for b in w1["bloecke"] if b["datum"] == "2026-11-20")
        self.assertEqual((weg["zustand"], weg["ziel"]["datum"]), ("verschoben", "2026-11-24"))
        hin = next(b for b in w2["bloecke"] if b["datum"] == "2026-11-24")
        self.assertEqual((hin["art"], hin["klasse"]["name"], hin["herkunft"]["datum"]), ("verschoben", "BSMT 22b", "2026-11-20"))
        with self.assertRaises(stundenplan.StundenplanFehler):   # Ziel belegt (Mo 1. Block BSMT 24a)
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "verschoben", "datum": "2026-11-16", "beginn": "09:30",
                                                               "ziel_datum": "2026-11-23", "ziel_beginn": "07:45"})

    def test_vertretung_und_zusatz(self):
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "vertretung", "datum": "2026-11-17", "beginn": "07:45",
                                                           "klasse_text": "IT 23", "wer": "Kollegin M."})
        stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "zusatz", "datum": "2026-11-17", "beginn": "09:30", "klasse_id": self.k22})
        self.assertEqual(self.namen(self.woche("2026-11-16"), "2026-11-17"),
                         [("07:45", "IT 23", "vertretung", None), ("09:30", "BSMT 22b", "zusatz", None), ("17:15", "FT 25", "regulaer", None)])
        with self.assertRaises(stundenplan.StundenplanFehler):   # Zusatz auf belegten Block
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "zusatz", "datum": "2026-11-16", "beginn": "07:45", "klasse_id": self.k22})
        with self.assertRaises(stundenplan.StundenplanFehler):   # FT 25 hat keinen Block 07:45
            stundenplan.aenderung_anlegen(self.con, self.lid, {"art": "zusatz", "datum": "2026-11-18", "beginn": "07:45", "klasse_id": self.ft})


class Termine(MitStundenplan):
    def test_termine_und_merker(self):
        stundenplan.termin_speichern(self.con, self.lid, {"art": "dienst", "titel": "Fachkonferenz", "datum": "2026-11-17", "beginn": "15:00"})
        stundenplan.termin_speichern(self.con, self.lid, {"art": "privat", "titel": "Klassenfahrt", "datum": "2026-11-13", "bis": "2026-11-16"})
        stundenplan.termin_speichern(self.con, self.lid, {"art": "merker", "titel": "Aufgabe 4 besprechen", "datum": "2026-11-16",
                                                          "beginn": "07:45", "klasse_id": self.k24})
        w = self.woche("2026-11-16")
        self.assertEqual([t["titel"] for t in w["termine"]], ["Klassenfahrt", "Fachkonferenz"])
        self.assertEqual(w["bloecke"][0]["merker"][0]["text"], "Aufgabe 4 besprechen")
        with self.assertRaises(stundenplan.StundenplanFehler):
            stundenplan.termin_speichern(self.con, self.lid, {"art": "dienst", "titel": "x", "datum": "2026-11-17", "beginn": "15:00", "ende": "14:00"})


class RasterUmzug(MitStundenplan):
    def test_geaenderte_zeiten_ziehen_den_stundenplan_mit(self):
        neu =[dict(b) for b in SCHULRASTER]
        neu[0].update(beginn="08:00", ende="09:30")
        neu[1].update(beginn="09:45", ende="11:15")
        with db.transaktion(self.con):
            vorher = stundenplan.raster_vorher(self.con)
            grunddaten.zeitraster_speichern(self.con, None, neu)
            stundenplan.raster_nachziehen(self.con, vorher)
        self.assertEqual(self.namen(self.woche("2026-11-16"), "2026-11-16"),
                         [("08:00", "BSMT 24a", "regulaer", None), ("09:45", "BSMT 24a", "regulaer", None)])
        self.assertEqual(self.namen(self.woche("2026-11-16"), "2026-11-17"), [("17:15", "FT 25", "regulaer", None)])   # FS unberuehrt

    def test_klasse_im_stundenplan_nicht_loeschbar(self):
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.klasse_loeschen(self.con, self.k24)


class WebserverB(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        db.oeffnen(self.ordner).close()
        self.server = server.HTTPServer(("127.0.0.1", 0), server.Handler, db.pfad(self.ordner))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.cookie = None
        server.SPERRE.rechner.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def anfrage(self, methode, pfad, daten=None):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        koepfe = {"Content-Type": "application/json", "X-Lehrerkalender": "1"}
        if self.cookie:
            koepfe["Cookie"] = self.cookie
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=koepfe)
        r = c.getresponse()
        inhalt = r.read()
        if r.getheader("Set-Cookie"):
            self.cookie = r.getheader("Set-Cookie").split(";")[0]
        c.close()
        return r.status, json.loads(inhalt)

    def test_ablauf(self):
        con = db.verbinden(db.pfad(self.ordner))
        code = konten.einrichtungscode(con)
        con.close()
        self.anfrage("POST", "/api/einrichtung", {"code": code, "kuerzel": "gob", "name": "Matthias Göbel", "passwort": "geheim123"})
        _, g = self.anfrage("POST", "/api/admin/bildungsgang", {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
        bid = g["bildungsgaenge"][0]["id"]
        self.anfrage("POST", "/api/admin/zeitraster", {"bildungsgang_id": None, "bloecke": SCHULRASTER})
        _, g = self.anfrage("POST", "/api/admin/klasse", {"name": "BSMT 24a", "bildungsgang_id": bid})
        kid = g["klassen"][0]["id"]
        _, g = self.anfrage("POST", "/api/admin/a-woche", {"a_woche": "gerade"})
        self.assertEqual(g["a_woche"], "gerade")
        status, e = self.anfrage("POST", "/api/stundenplan/version", {"ab": "2026-08-01", "name": "1. Halbjahr"})
        self.assertEqual(status, 200)
        vid = e["neu"]
        status, e = self.anfrage("POST", "/api/stundenplan/version/%d/feld" % vid,
                                 {"wochentag": 1, "beginn": "07:45", "ende": "09:15", "eintraege": [{"klasse_id": kid}]})
        self.assertEqual(e["versionen"][0]["eintraege"][0]["klasse_id"], kid)
        status, e = self.anfrage("POST", "/api/stundenplan/version/%d/feld" % vid,
                                 {"wochentag": 1, "beginn": "17:00", "ende": "18:00", "eintraege": [{"klasse_id": kid}]})
        self.assertEqual(status, 400)
        status, w = self.anfrage("GET", "/api/woche?montag=2026-11-16")
        self.assertEqual((w["kw"], w["ab"], len(w["bloecke"])), (47, "B", 1))
        status, r = self.anfrage("POST", "/api/aenderung", {"art": "ausfall", "datum": "2026-11-16", "beginn": "07:45"})
        self.assertEqual(status, 200)
        status, r = self.anfrage("POST", "/api/termin", {"art": "dienst", "titel": "Konferenz", "datum": "2026-11-18"})
        tid = r["id"]
        self.assertEqual(self.anfrage("POST", "/api/termin/%d/loeschen" % tid, {})[0], 200)
        status, w = self.anfrage("GET", "/api/woche?montag=2026-11-16")
        self.assertEqual((w["bloecke"][0]["zustand"], w["termine"]), ("ausfall", []))
        self.assertEqual(self.anfrage("GET", "/api/woche?montag=quatsch")[0], 400)
        self.assertEqual(self.anfrage("POST", "/api/admin/klasse/%d/loeschen" % kid, {})[0], 400)


if __name__ == "__main__":
    unittest.main()
