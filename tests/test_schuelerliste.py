"""Tests fuer 0.24.0: gemeinsame Schuelerliste je Klasse (app/schuelerliste.py), Migration 23/24 (Zusammenfuehren der
frueheren privaten Listen), Zugriff, private Gruppen, Doppelungen.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import http.client
import json
import shutil
import tempfile
import threading
import unittest

from app import db, grunddaten, konten, pruefungen, schuelerliste, server, stundenplan
from test_kollegium import MitKollegin


def pruefung(con, lid, kid, sj, titel="Test"):
    return pruefungen.pruefung_speichern(con, lid, {"klasse_id": kid, "gruppe_id": None, "schuljahr_id": sj, "titel": titel,
                                                    "art": "schriftlich", "form": "fenster", "fenster_von": "2026-11-16",
                                                    "fenster_bis": "2026-11-20", "erfassung": "gesamt", "max_punkte": 50})


class MigrationZusammenfuehren(unittest.TestCase):
    """Datenbank im Stand 22 (private Listen) anlegen, dann auf den neuesten Stand bringen."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.verbinden(db.pfad(self.ordner))
        alle = db.MIGRATIONEN
        try:
            db.MIGRATIONEN = alle[:22]
            db.migrieren(self.con)
        finally:
            db.MIGRATIONEN = alle
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone()[0], 22)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def alt(self, lid, kid, nach, vor, mail="", gruppe=None, aktiv=1):
        return self.con.execute("INSERT INTO schueler (lehrkraft_id, klasse_id, gruppe_id, nachname, vorname, email, aktiv, erstellt) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, '2026-09-01T08:00:00')", (lid, kid, gruppe, nach, vor, mail, aktiv)).lastrowid

    def test_private_listen_werden_eine(self):
        c = self.con
        with db.transaktion(c):
            g = konten.anlegen(c, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)["id"]
            r = konten.anlegen(c, "rei", "Kollege Reiter", "lehrkraft", "geheim123", vorlaeufig=False)["id"]
            bs = grunddaten.bildungsgang_speichern(c, {"name": "Mechatroniker/in"})
            kid = grunddaten.klasse_speichern(c, {"name": "BSMT 24a", "bildungsgang_id": bs})
            sj = grunddaten.schuljahr_speichern(c, {"name": "2026/27", "beginn": "2026-08-10", "ende": "2027-06-25"})
            gr = c.execute("INSERT INTO gruppe (lehrkraft_id, klasse_id, name) VALUES (?, ?, 'Labor A')", (r, kid)).lastrowid
            g_weiss = self.alt(g, kid, "Weiß", "Clara", "clara@schule.de")
            g_yil = self.alt(g, kid, "Yılmaz", "Deniz")
            g_lea = self.alt(g, kid, "Schmitt", "Lea", "lea@schule.de")
            g_tom = self.alt(g, kid, "Müller", "Tom", "tom@schule.de", aktiv=0)
            g_j1, g_j2 = self.alt(g, kid, "Becker", "Jonas"), self.alt(g, kid, "Becker", "Jonas")   # gleiche Lehrkraft doppelt
            r_weiss = self.alt(r, kid, "Weiss", "Clara")                         # andere Schreibweise, ohne E-Mail
            r_yil = self.alt(r, kid, "Yilmaz", "Deniz", "deniz@schule.de")
            r_lea = self.alt(r, kid, "Schmitt", "Lea", "lea.schmitt@web.de")      # widerspricht: bleibt getrennt
            r_tom = self.alt(r, kid, "Müller", "Tom", "TOM@schule.de", gruppe=gr)
            pg, pr = pruefung(c, g, kid, sj, "KA gob"), pruefung(c, r, kid, sj, "KA rei")
            for pid, sid in ((pg, g_weiss), (pr, r_weiss), (pr, r_tom)):
                c.execute("INSERT INTO bewertung (pruefung_id, schueler_id, werte, geaendert) VALUES (?, ?, '{\"gesamt\": 40}', 'x')", (pid, sid))
        db.migrieren(c)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(db.MIGRATIONEN))
        self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        namen = sorted((z["nachname"], z["email"], z["aktiv"], z["erstellt_von"]) for z in c.execute("SELECT * FROM schueler"))
        self.assertEqual(namen, [("Becker", "", 1, g), ("Becker", "", 1, g), ("Müller", "tom@schule.de", 1, g),
                                 ("Schmitt", "lea.schmitt@web.de", 1, r), ("Schmitt", "lea@schule.de", 1, g),
                                 ("Weiß", "clara@schule.de", 1, g), ("Yılmaz", "deniz@schule.de", 1, g)])
        ids = {z["id"] for z in c.execute("SELECT id FROM schueler")}
        self.assertEqual(ids, {g_weiss, g_yil, g_lea, g_tom, g_j1, g_j2, r_lea})
        # Bewertungen haengen am gemeinsamen Schueler, die Gruppe von rei ebenso
        self.assertEqual(sorted(tuple(z) for z in c.execute("SELECT pruefung_id, schueler_id FROM bewertung")),
                         sorted([(pg, g_weiss), (pr, g_weiss), (pr, g_tom)]))
        self.assertEqual([tuple(z) for z in c.execute("SELECT lehrkraft_id, schueler_id, gruppe_id FROM schueler_gruppe")], [(r, g_tom, gr)])
        # beide sehen dieselbe Liste; offene Doppelungen: die beiden Becker (gleiche Lehrkraft) und Schmitt (E-Mails)
        self.assertEqual([s["id"] for s in schuelerliste.liste(c, g, kid)], [s["id"] for s in schuelerliste.liste(c, r, kid)])
        paare = {(p["a"]["id"], p["b"]["id"]) for p in schuelerliste.doppelungen(c, r, kid)}
        self.assertEqual(paare, {(g_j1, g_j2), tuple(sorted((g_lea, r_lea)))})
        tom = next(s for s in schuelerliste.liste(c, r, kid) if s["nachname"] == "Müller")
        self.assertEqual((tom["gruppe"], next(s for s in schuelerliste.liste(c, g, kid) if s["nachname"] == "Müller")["gruppe"]), ("Labor A", None))


class GemeinsameListe(MitKollegin):
    """gob unterrichtet 24a und 25a, rei nur 24a, xyz gar nichts."""

    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.x = konten.anlegen(self.con, "xyz", "Dritte Lehrkraft", "lehrkraft", "geheim123", vorlaeufig=False)["id"]
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})

    def test_zugriff(self):
        self.assertTrue(schuelerliste.darf_klasse(self.con, self.rid, self.k24))
        self.assertFalse(schuelerliste.darf_klasse(self.con, self.rid, self.k25))
        self.assertFalse(schuelerliste.darf_klasse(self.con, self.x, self.k24))
        self.assertTrue(schuelerliste.darf_klasse(self.con, self.lid, self.k25))      # Admin und Stundenplan
        with self.assertRaises(schuelerliste.SchuelerFehler):
            schuelerliste.liste(self.con, self.x, self.k24)
        with self.assertRaises(schuelerliste.SchuelerFehler):
            schuelerliste.speichern(self.con, self.x, {"nachname": "X"}, self.clara)
        self.assertEqual([k["name"] for k in schuelerliste.klassen(self.con, self.rid)], ["BSMT 24a"])
        self.assertTrue(schuelerliste.klassen(self.con, self.rid)[0]["meine"])
        self.assertEqual(schuelerliste.klassen(self.con, self.x), [])
        # auch eine vergangene Stundenplan-Version zaehlt
        with db.transaktion(self.con):
            stundenplan.version_anlegen(self.con, self.rid, {"ab": "2026-12-01"})
        self.assertTrue(schuelerliste.darf_klasse(self.con, self.rid, self.k24))

    def test_gemeinsam_aendern_gruppen_privat(self):
        with db.transaktion(self.con):
            g_rei = self.con.execute("INSERT INTO gruppe (lehrkraft_id, klasse_id, name) VALUES (?, ?, 'Labor A')", (self.rid, self.k24)).lastrowid
            neu = schuelerliste.speichern(self.con, self.rid, {"klasse_id": self.k24, "nachname": "Yılmaz", "vorname": "Deniz", "gruppe_id": g_rei})
            schuelerliste.speichern(self.con, self.rid, {"nachname": "Weiß", "vorname": "Clara", "email": "c@x.de", "aktiv": False}, self.clara)
        gob = {s["nachname"]: s for s in schuelerliste.liste(self.con, self.lid, self.k24)}
        rei = {s["nachname"]: s for s in schuelerliste.liste(self.con, self.rid, self.k24)}
        self.assertEqual(set(gob), {"Weiß", "Yılmaz"})
        self.assertEqual((gob["Weiß"]["email"], gob["Weiß"]["aktiv"]), ("c@x.de", False))        # rei hat es fuer alle geaendert
        self.assertEqual((rei["Yılmaz"]["gruppe"], gob["Yılmaz"]["gruppe"]), ("Labor A", None))   # Gruppe nur bei rei
        self.assertEqual(rei["Yılmaz"]["angelegt_von"], "Kollege Reiter")
        with self.assertRaises(schuelerliste.SchuelerFehler):       # fremde Gruppe geht nicht
            schuelerliste.speichern(self.con, self.lid, {"nachname": "Yılmaz", "gruppe_id": g_rei}, neu)
        # Aendern ohne gruppe_id laesst die eigene Gruppe stehen
        with db.transaktion(self.con):
            schuelerliste.speichern(self.con, self.rid, {"nachname": "Yılmaz", "vorname": "Deniz"}, neu)
        self.assertEqual(next(s for s in schuelerliste.liste(self.con, self.rid, self.k24) if s["id"] == neu)["gruppe"], "Labor A")

    def test_loeschen_nur_ohne_bewertungen_aller(self):
        with db.transaktion(self.con):
            pid = pruefung(self.con, self.rid, self.k24, self.sj)
            pruefungen.bewertung_setzen(self.con, self.rid, pid, self.clara, {"werte": {"gesamt": 30}})
        with self.assertRaises(schuelerliste.SchuelerFehler):       # rei hat bewertet, gob kann nicht loeschen
            schuelerliste.loeschen(self.con, self.lid, self.clara)

    def test_doppelung_zusammenfuehren_und_verschieden(self):
        with db.transaktion(self.con):
            zweite = schuelerliste.speichern(self.con, self.rid, {"klasse_id": self.k24, "nachname": "Weiss", "vorname": "Clara", "email": "c@x.de"})
            pg, pr = pruefung(self.con, self.lid, self.k24, self.sj, "A"), pruefung(self.con, self.rid, self.k24, self.sj, "B")
            pruefungen.bewertung_setzen(self.con, self.lid, pg, self.clara, {"werte": {"gesamt": 30}})
            pruefungen.bewertung_setzen(self.con, self.rid, pr, zweite, {"werte": {"gesamt": 40}})
        paare = schuelerliste.doppelungen(self.con, self.rid, self.k24)
        self.assertEqual([(p["a"]["id"], p["b"]["id"]) for p in paare], [(self.clara, zweite)])
        with db.transaktion(self.con):
            schuelerliste.zusammenfuehren(self.con, self.rid, self.clara, zweite)
        liste = schuelerliste.liste(self.con, self.lid, self.k24)
        self.assertEqual([(s["name"], s["email"]) for s in liste], [("Weiß, Clara", "c@x.de")])
        self.assertEqual(sorted(z[0] for z in self.con.execute("SELECT pruefung_id FROM bewertung WHERE schueler_id = ?", (self.clara,))), [pg, pr])
        # zwei in derselben Pruefung bewertet: kein Zusammenfuehren; "verschieden" blendet das Paar aus
        with db.transaktion(self.con):
            dritte = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
            pruefungen.bewertung_setzen(self.con, self.lid, pg, dritte, {"werte": {"gesamt": 10}})
        with self.assertRaises(schuelerliste.SchuelerFehler):
            schuelerliste.zusammenfuehren(self.con, self.lid, self.clara, dritte)
        with db.transaktion(self.con):
            schuelerliste.verschieden_markieren(self.con, self.lid, dritte, self.clara)
        self.assertEqual(schuelerliste.doppelungen(self.con, self.lid, self.k24), [])
        with self.assertRaises(schuelerliste.SchuelerFehler):       # rei kennt 25a nicht
            schuelerliste.zusammenfuehren(self.con, self.x, self.clara, dritte)

    def test_moodle_in_die_gemeinsame_liste(self):
        with db.transaktion(self.con):
            r = schuelerliste.moodle_csv(self.con, self.rid, self.k24, "Vorname;Nachname;E-Mail-Adresse\nClara;Weiss;c@x.de\nTom;Neu;\n")
        self.assertEqual((r["neu"], r["vorhanden"]), (["Neu, Tom"], ["Weiß, Clara"]))
        self.assertEqual(next(s for s in schuelerliste.liste(self.con, self.lid, self.k24) if s["vorname"] == "Clara")["email"], "c@x.de")


class GemeinsameListeUeberDenServer(MitKollegin):
    def setUp(self):
        super().setUp()
        self.srv = server.HTTPServer(("127.0.0.1", 0), server.Handler)
        self.srv.db_pfad = db.pfad(self.ordner)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.keks = {}
        for kz in ("gob", "rei"):
            _, _, kopf = self.anfrage("POST", "/api/anmelden", {"kuerzel": kz, "passwort": "geheim123"})
            self.keks[kz] = kopf.get("Set-Cookie", "").split(";")[0]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def anfrage(self, methode, pfad, daten=None, wer=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        k = {"X-Lehrerkalender": "1", "Content-Type": "application/json"}
        if wer:
            k["Cookie"] = self.keks[wer]
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=k)
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        return r.status, json.loads(inhalt or b"{}"), dict(r.getheaders())

    def test_ablauf(self):
        status, a, _ = self.anfrage("GET", "/api/schueler/klassen", wer="rei")
        self.assertEqual([k["name"] for k in a["klassen"]], ["BSMT 24a"])
        status, a, _ = self.anfrage("POST", "/api/schueler", {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"}, wer="rei")
        self.assertEqual(status, 200, a)
        status, a, _ = self.anfrage("POST", "/api/schueler", {"klasse_id": self.k24, "nachname": "Weiss", "vorname": "Clara"}, wer="gob")
        status, a, _ = self.anfrage("GET", "/api/schueler?klasse=%d" % self.k24, wer="gob")
        self.assertEqual(status, 200, a)
        self.assertEqual(len(a["schueler"]), 2)
        self.assertEqual(len(a["doppelungen"]), 1)
        self.assertEqual(a["lehrkraefte"], ["Kollege Reiter"])                  # ohne mich selbst
        p = a["doppelungen"][0]
        status, a, _ = self.anfrage("POST", "/api/schueler/zusammenfuehren", {"ziel": p["a"]["id"], "quelle": p["b"]["id"]}, wer="rei")
        self.assertEqual(status, 200, a)
        status, a, _ = self.anfrage("GET", "/api/schueler?klasse=%d" % self.k25, wer="rei")
        self.assertEqual(status, 400)                                # 25a unterrichtet rei nicht
        arten = [tuple(z) for z in self.con.execute("SELECT wer, art FROM protokoll WHERE art LIKE 'schueler_%' ORDER BY id")]
        self.assertEqual(arten, [("rei", "schueler_angelegt"), ("gob", "schueler_angelegt"), ("rei", "schueler_zusammengefuehrt")])


if __name__ == "__main__":
    unittest.main()
