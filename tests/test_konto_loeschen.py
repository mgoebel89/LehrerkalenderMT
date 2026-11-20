"""Tests fuer 0.28.0: Konten loeschen (app/konten.py loeschen_pruefen/loeschen, Server mit Sicherung vorher).
Die zu loeschende Lehrkraft hat ueberall Daten; danach muessen alle Verweise stimmen, Privates ist weg, was andere
nutzen (Bibliothek, Lernfelder, Schueler, Einladungen) bleibt ohne Besitzer stehen.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import base64
import http.client
import json
import os
import threading
import types

from app import beobachtungen, db, fotos, grunddaten, konten, notenschluessel, planung, pruefungen, schuelerliste, server, stundenplan, ub
from test_kollegium import MitKollegin
from test_fotos import DATA_URL
from test_schuelerliste import pruefung


class MitVollemKonto(MitKollegin):
    """rei (Lehrkraft, 24a) bekommt Daten in moeglichst allen Bereichen; gob ist Admin."""

    def setUp(self):
        super().setUp()
        rei = konten.holen(self.con, self.rid)
        c = self.con
        with db.transaktion(c):
            self.gruppe = stundenplan.gruppe_speichern(c, self.rid, {"klasse_id": self.k24, "name": "Gr. 1"})
            planung.thema_speichern(c, self.rid, self.strang(titel="Pneumatik", bloecke=2))
            planung.eintrag_setzen(c, self.rid, "2026-11-18", "07:45", {"inhalt": "Wendeschaltung", "notizen": "privat"})
            stundenplan.termin_speichern(c, self.rid, {"art": "dienst", "titel": "Konferenz", "datum": "2026-11-19"})
            stundenplan.aenderung_anlegen(c, self.rid, {"art": "ausfall", "datum": "2026-11-25", "beginn": "07:45", "grund": "krank"})
            self.lf = grunddaten.lernfeld_der_lehrkraft_speichern(c, rei, {"bildungsgang_id": self.bs, "nummer": "LF 12", "name": "Wartung"})
            self.baustein = planung.baustein_speichern(c, rei, {"art": "thema", "lernfeld_id": self.lf7, "titel": "SPS Grundlagen", "bloecke": 3})
            self.clara = schuelerliste.speichern(c, self.rid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara", "gruppe_id": self.gruppe})
            fotos.setzen(c, self.rid, self.clara, DATA_URL)
            self.pid = pruefung(c, self.rid, self.k24, self.sj)
            pruefungen.bewertung_setzen(c, self.rid, self.pid, self.clara, {"werte": {"gesamt": 30}})
            notenschluessel.speichern(c, rei, {"name": "Mein Schlüssel", "art": "eigen", "system": "tendenz"})
            beobachtungen.anlegen(c, self.rid, {"schueler_ids": [self.clara], "datum": "2026-11-18", "text": "privat notiert"})
            ub.anwaerter_anlegen(types.SimpleNamespace(lid=self.rid, con=c), {"name": "Anwärterin A"})
            e = konten.einladung_anlegen(c, "lehrkraft", 7, "für rei", self.lid)
            c.execute("UPDATE einladung SET eingeloest_von = ? WHERE id = ?", (self.rid, e["id"]))
            self.einladung = e["id"]
            # gob hat eigene Daten, die bleiben muessen
            self.gob_pid = pruefung(c, self.lid, self.k24, self.sj, "KA gob")
            pruefungen.bewertung_setzen(c, self.lid, self.gob_pid, self.clara, {"werte": {"gesamt": 45}})
            beobachtungen.anlegen(c, self.lid, {"schueler_ids": [self.clara], "datum": "2026-11-18", "text": "von gob"})


class KontoLoeschen(MitVollemKonto):
    def pruefen(self, lid=None, passwort="geheim123", kuerzel="rei"):
        return konten.loeschen_pruefen(self.con, self.lid, lid or self.rid, passwort, kuerzel)

    def test_bedingungen(self):
        with self.assertRaises(konten.KontoFehler) as f:                 # nicht gesperrt
            self.pruefen()
        self.assertIn("sperren", str(f.exception))
        with db.transaktion(self.con):
            konten.aendern(self.con, self.rid, gesperrt=True)
        with self.assertRaises(konten.KontoFehler):                      # falsches Passwort
            self.pruefen(passwort="falsch")
        with self.assertRaises(konten.KontoFehler):                      # falsches Kuerzel
            self.pruefen(kuerzel="gob")
        with self.assertRaises(konten.KontoFehler):                      # das eigene Konto
            konten.loeschen_pruefen(self.con, self.lid, self.lid, "geheim123", "gob")
        with self.assertRaises(konten.KontoFehler):
            self.pruefen(lid=9999)
        self.assertEqual(self.pruefen(kuerzel=" REI ")["kuerzel"], "rei")
        stand = konten.loeschen_stand(self.con, self.rid)
        self.assertEqual((stand["weg"]["Prüfungen mit Noten"], stand["weg"]["Beobachtungen"], stand["bleibt"]["selbst angelegte Lernfelder"]), (1, 1, 1))

    def test_gesperrter_zweiter_admin(self):
        """Ein (gesperrter) zweiter Admin laesst sich loeschen; seine Einladungen bleiben ohne Ersteller stehen.
        Den letzten aktiven Admin kann es dabei nicht treffen: wer loescht, ist selbst aktiver Admin."""
        with db.transaktion(self.con):
            zwei = konten.anlegen(self.con, "zwo", "Zweite Admin", "admin", "geheim123", vorlaeufig=False)["id"]
            e = konten.einladung_anlegen(self.con, "lehrkraft", 7, "von zwo", zwei)
            konten.aendern(self.con, zwei, gesperrt=True)
            konten.loeschen_pruefen(self.con, self.lid, zwei, "geheim123", "zwo")
            konten.loeschen(self.con, zwei)
        self.assertIsNone(self.con.execute("SELECT erstellt_von FROM einladung WHERE id = ?", (e["id"],)).fetchone()[0])
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_loeschen_alles_stimmig(self):
        with db.transaktion(self.con):
            konten.aendern(self.con, self.rid, gesperrt=True)
            self.pruefen()
            konten.loeschen(self.con, self.rid)
        c = self.con
        self.assertIsNone(konten.holen(c, self.rid))
        self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        weg = ("stundenplan_version", "plan_thema", "termin", "aenderung", "gruppe", "stunde_eintrag", "pruefung", "beobachtung",
               "schueler_gruppe", "ub_anwaerter")
        for t in weg:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM %s WHERE lehrkraft_id = ?" % t, (self.rid,)).fetchone()[0], 0, t)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM notenschluessel WHERE besitzer_id = ?", (self.rid,)).fetchone()[0], 0)
        # bleibt ohne Besitzer
        self.assertIsNone(c.execute("SELECT besitzer_id FROM baustein WHERE id = ?", (self.baustein,)).fetchone()[0])
        self.assertIsNone(c.execute("SELECT besitzer_id FROM lernfeld WHERE id = ?", (self.lf,)).fetchone()[0])
        s = c.execute("SELECT erstellt_von, foto IS NOT NULL FROM schueler WHERE id = ?", (self.clara,)).fetchone()
        self.assertEqual(tuple(s), (None, 1))                              # Schueler samt Foto bleibt
        self.assertEqual(tuple(c.execute("SELECT erstellt_von, eingeloest_von FROM einladung WHERE id = ?", (self.einladung,)).fetchone()),
                         (self.lid, None))
        # gob unberuehrt
        self.assertEqual(c.execute("SELECT COUNT(*) FROM bewertung WHERE pruefung_id = ?", (self.gob_pid,)).fetchone()[0], 1)
        self.assertEqual([e["text"] for e in beobachtungen.verlauf(c, self.lid, self.clara)["eintraege"]], ["von gob"])


class KontoLoeschenUeberDenServer(MitVollemKonto):
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
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=20)
        k = {"X-Lehrerkalender": "1", "Content-Type": "application/json"}
        if wer:
            k["Cookie"] = self.keks[wer]
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=k)
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        return r.status, json.loads(inhalt or b"{}"), dict(r.getheaders())

    def test_ablauf(self):
        url = "/api/admin/konten/%d/loeschen" % self.rid
        status, a, _ = self.anfrage("POST", url, {"kuerzel": "rei", "passwort": "geheim123"}, wer="rei")
        self.assertEqual(status, 403)                                      # nur der Admin
        status, a, _ = self.anfrage("POST", url, {"kuerzel": "rei", "passwort": "geheim123"}, wer="gob")
        self.assertEqual(status, 400)                                      # noch nicht gesperrt
        status, a, _ = self.anfrage("POST", "/api/admin/konten/%d" % self.rid, {"gesperrt": True}, wer="gob")
        self.assertEqual(status, 200, a)
        status, a, _ = self.anfrage("GET", url, wer="gob")
        self.assertEqual(a["weg"]["Beobachtungen"], 1)
        status, a, _ = self.anfrage("POST", url, {"kuerzel": "rei", "passwort": "geheim123"}, wer="gob")
        self.assertEqual(status, 200, a)
        self.assertTrue(a["sicherung"].startswith("vor-konto-loeschen-"))
        self.assertTrue(os.path.isfile(os.path.join(self.ordner, "sicherungen", a["sicherung"])))
        self.assertIsNone(konten.holen(self.con, self.rid))
        z = self.con.execute("SELECT wer, daten FROM protokoll WHERE art = 'konto_geloescht'").fetchone()
        self.assertEqual((z["wer"], json.loads(z["daten"])["konto"]), ("gob", "rei"))
        status, a, _ = self.anfrage("GET", "/api/ich", wer="rei")
        self.assertEqual(status, 401)                                      # Anmeldung von rei gilt nicht mehr
