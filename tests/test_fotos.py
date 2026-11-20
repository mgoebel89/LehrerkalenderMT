"""Tests fuer 0.25.0: Fotos zu Schuelern (app/fotos.py): speichern nur als JPEG, Zugriff wie die gemeinsame Liste,
Foto in Liste und Pruefung, Zusammenfuehren, Fotoliste als PDF.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import base64
import http.client
import json
import threading

from app import db, fotos, pruefungen, schuelerliste, server
from test_kollegium import MitKollegin
from test_schuelerliste import pruefung
from test_schule import JPEG

DATA_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


class Fotos(MitKollegin):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
            self.deniz = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Yılmaz", "vorname": "Deniz"})

    def test_setzen_holen_loeschen(self):
        self.assertIsNone(schuelerliste.liste(self.con, self.rid, self.k24)[0]["foto"])
        with db.transaktion(self.con):
            fotos.setzen(self.con, self.rid, self.clara, DATA_URL)          # rei unterrichtet 24a: darf
        self.assertEqual(fotos.holen(self.con, self.lid, self.clara), JPEG)   # gob sieht dasselbe Foto
        stand = next(s for s in schuelerliste.liste(self.con, self.lid, self.k24) if s["id"] == self.clara)["foto"]
        self.assertTrue(stand)
        with db.transaktion(self.con):
            fotos.loeschen(self.con, self.lid, self.clara)
        self.assertIsNone(fotos.holen(self.con, self.lid, self.clara))
        self.assertIsNone(next(s for s in schuelerliste.liste(self.con, self.lid, self.k24) if s["id"] == self.clara)["foto"])

    def test_nur_jpeg_und_nur_mit_zugriff(self):
        for falsch in ("", "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode(), "kein base64!",
                       base64.b64encode(b"x" * 100).decode(), "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8" + b"0" * (fotos.MAX_BYTES + 10)).decode()):
            with self.assertRaises(schuelerliste.SchuelerFehler):
                fotos.setzen(self.con, self.lid, self.clara, falsch)
        with self.assertRaises(schuelerliste.SchuelerFehler):              # 25a/24a: xyz hat keinen Zugriff
            fotos.setzen(self.con, 999, self.clara, DATA_URL)

    def test_foto_in_der_pruefung_und_beim_zusammenfuehren(self):
        with db.transaktion(self.con):
            fotos.setzen(self.con, self.lid, self.deniz, DATA_URL)
            pid = pruefung(self.con, self.lid, self.k24, self.sj)
        zeilen = {z["id"]: z for z in pruefungen.ergebnis(self.con, self.lid, pid)["schueler"]}
        self.assertTrue(zeilen[self.deniz]["foto"])
        self.assertIsNone(zeilen[self.clara]["foto"])
        # Zusammenfuehren: hat das Ziel (Clara) kein Foto, bekommt es das Foto des doppelten Eintrags
        with db.transaktion(self.con):
            zweite = schuelerliste.speichern(self.con, self.rid, {"klasse_id": self.k24, "nachname": "Weiss", "vorname": "Clara"})
            fotos.setzen(self.con, self.rid, zweite, DATA_URL)
            schuelerliste.zusammenfuehren(self.con, self.rid, self.clara, zweite)
        self.assertEqual(fotos.holen(self.con, self.lid, self.clara), JPEG)

    def test_fotoliste_pdf(self):
        with db.transaktion(self.con):
            fotos.setzen(self.con, self.lid, self.clara, DATA_URL)
            for i in range(25):                                             # mehr als eine Seite
                schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Schüler %02d" % i, "vorname": "Test"})
        inhalt, name = fotos.fotoliste_pdf(self.con, self.rid, self.k24, "Kollege Reiter")
        self.assertTrue(inhalt.startswith(b"%PDF"))
        self.assertTrue(name.startswith("Fotoliste BSMT 24a"))
        self.assertIn(b"/DCTDecode", inhalt)
        self.assertEqual(inhalt.count(b"/Type /Page "), 2)
        with self.assertRaises(schuelerliste.SchuelerFehler):              # leere Klasse
            fotos.fotoliste_pdf(self.con, self.lid, self.k25)


class FotosUeberDenServer(MitKollegin):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
            self.k25s = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k25, "nachname": "Fremd", "vorname": "Fritz"})
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

    def anfrage(self, methode, pfad, daten=None, wer=None, roh=False):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        k = {"X-Lehrerkalender": "1", "Content-Type": "application/json"}
        if wer:
            k["Cookie"] = self.keks[wer]
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=k)
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        return r.status, (inhalt if roh else json.loads(inhalt or b"{}")), dict(r.getheaders())

    def test_ablauf(self):
        status, a, _ = self.anfrage("GET", "/api/schueler/%d/foto" % self.clara, wer="rei", roh=True)
        self.assertEqual(status, 404)
        status, a, _ = self.anfrage("POST", "/api/schueler/%d/foto" % self.clara, {"bild": DATA_URL}, wer="rei")
        self.assertEqual(status, 200, a)
        status, inhalt, kopf = self.anfrage("GET", "/api/schueler/%d/foto?v=1" % self.clara, wer="gob", roh=True)
        self.assertEqual((status, inhalt, kopf["Content-Type"]), (200, JPEG, "image/jpeg"))
        status, a, _ = self.anfrage("POST", "/api/schueler/%d/foto" % self.k25s, {"bild": DATA_URL}, wer="rei")
        self.assertEqual(status, 400)                                        # 25a unterrichtet rei nicht
        status, a, _ = self.anfrage("GET", "/api/schueler/%d/foto" % self.k25s, wer="rei", roh=True)
        self.assertEqual(status, 400)
        status, inhalt, kopf = self.anfrage("GET", "/api/schueler/fotoliste.pdf?klasse=%d" % self.k24, wer="rei", roh=True)
        self.assertEqual((status, inhalt[:4]), (200, b"%PDF"))
        status, a, _ = self.anfrage("POST", "/api/schueler/%d/foto/loeschen" % self.clara, {}, wer="gob")
        self.assertEqual(status, 200, a)
        arten = [tuple(z) for z in self.con.execute("SELECT wer, art FROM protokoll WHERE art LIKE 'schueler_foto%' ORDER BY id")]
        self.assertEqual(arten, [("rei", "schueler_foto"), ("gob", "schueler_foto_geloescht")])
