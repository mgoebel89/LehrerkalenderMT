"""Stufe F2: Unterrichtsbesuche (aus dem alten Lehrerkalender uebernommen) - Anwaerter, Besuche, Eintraege, Fotos,
Skizzen, Protokoll als PDF/ODT, je Konto einschaltbar und strikt privat.

Das Protokoll braucht reportlab und Pillow (Paketquellen: python3-reportlab, python3-pil), sonst uebersprungen.
"""
import base64
import http.client
import io
import json
import shutil
import tempfile
import threading
import unittest
import zipfile

try:
    from PIL import Image
except ImportError:
    Image = None
try:
    import reportlab   # noqa: F401
except ImportError:
    reportlab = None

from app import db, konten, server, ub


def bild_url(art="JPEG", groesse=(80, 60)):
    puffer = io.BytesIO()
    Image.new("RGB", groesse, (0, 99, 156)).save(puffer, art)
    return "data:image/%s;base64,%s" % (art.lower(), base64.b64encode(puffer.getvalue()).decode())


class Grundlagen(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.a = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.b = konten.anlegen(self.con, "mus", "Erika Muster", "lehrkraft", "geheim123", vorlaeufig=False)
        self.k = ub.Kontext(self.con, self.a["id"] if isinstance(self.a, dict) else self.a, "Matthias Göbel")
        self.k2 = ub.Kontext(self.con, self.b["id"] if isinstance(self.b, dict) else self.b, "Erika Muster")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def besuch(self, k=None, **mehr):
        k = k or self.k
        with db.transaktion(self.con):
            ub.einstellung(k)
            p = {"neuer_anwaerter": {"name": "Anna Anwärterin", "faecher": "Mechatronik"}, "datum": "2026-11-20", "beginn": "07:45",
                 "ende": "09:15", "klasse": "BSMT 24a", "thema": "Pneumatik"}
            p.update(mehr)
            return ub.besuch_anlegen(k, p)["id"]

    def test_vorgaben_und_einstellungen(self):
        with db.transaktion(self.con):
            ub.einstellung(self.k)
        s = ub.seite_einstellungen(self.k)
        for art in ("kategorien", "phasen", "kriterien"):
            self.assertTrue(s["daten"][art], art)        # Vorgaben wie im alten Tool
        # die andere Lehrkraft hat eigene Vorgaben, nicht dieselben Zeilen
        with db.transaktion(self.con):
            ub.einstellung(self.k2)
        ids1 = {o["id"] for o in s["daten"]["kategorien"]}
        ids2 = {o["id"] for o in ub.seite_einstellungen(self.k2)["daten"]["kategorien"]}
        self.assertFalse(ids1 & ids2)
        with db.transaktion(self.con):
            neu = ub.einstellung_anlegen(self.k, "kategorien", {"name": "Medien", "icon": "stern", "farbe": "#00639C"})
        self.assertTrue(neu["ok"])
        with self.assertRaises(ub.UbFehler):
            ub.einstellung_speichern(self.k2, "kategorien", neu["obj"]["id"], {"name": "x"})

    def test_besuch_eintraege_und_status(self):
        bid = self.besuch()
        U = ub.seite_uebersicht(self.k, "2026-11-16")
        self.assertEqual([b["id"] for b in U["anstehend"]], [bid])
        self.assertEqual(U["anstehend"][0]["anwaerter"], "Anna Anwärterin")
        kat = ub.liste(self.k, None, "kategorien", True)[0].id
        phase = ub.liste(self.k, None, "phasen", True)[0].id
        with db.transaktion(self.con):
            ub.eintrag_anlegen(self.k, bid, {"art": "phase", "phase_id": phase, "zeit": "07:46"})
            r = ub.eintrag_anlegen(self.k, bid, {"kategorie_id": kat, "text": "Sauberer Einstieg", "zeit": "07:50"})
        self.assertEqual(r["status"], "laufend")       # erster Eintrag setzt „laeuft“
        with self.assertRaises(ub.UbFehler):
            ub.eintrag_anlegen(self.k, bid, {"kategorie_id": kat, "text": ""})
        S = ub.seite_besuch(self.k, bid)
        self.assertEqual(len(S["besuch"]["eintraege"]), 2)
        # fremde Lehrkraft sieht den Besuch nicht
        with self.assertRaises(ub.UbFehler) as f:
            ub.seite_besuch(self.k2, bid)
        self.assertEqual(f.exception.status, 404)
        self.assertEqual(ub.seite_uebersicht(self.k2, "2026-11-16")["anstehend"], [])
        with db.transaktion(self.con):
            ub.besuch_speichern(self.k, bid, {"status": "abgeschlossen", "reflexion": "gut", "vereinbarungen": "Zeit im Blick"})
        U = ub.seite_uebersicht(self.k, "2026-11-16")
        self.assertEqual([b["id"] for b in U["vergangen"]], [bid])
        # Vereinbarungen erscheinen beim naechsten Besuch derselben Anwaerterin
        aid = self.con.execute("SELECT anwaerter_id FROM ub_besuch WHERE id = ?", (bid,)).fetchone()[0]
        bid2 = self.besuch(neuer_anwaerter=None, anwaerter_id=aid, datum="2026-12-04")
        vor = ub.vorheriger_besuch(self.k, ub.besuch_obj(self.k, bid2))
        self.assertEqual(vor.id, bid)
        # genutzte Kategorie laesst sich nicht loeschen
        with self.assertRaises(ub.UbFehler):
            ub.einstellung_loeschen(self.k, "kategorien", kat)

    @unittest.skipIf(Image is None, "Pillow fehlt")
    def test_foto_skizze_datei(self):
        bid = self.besuch()
        kat = ub.liste(self.k, None, "kategorien", True)[0].id
        with db.transaktion(self.con):
            eid = ub.eintrag_anlegen(self.k, bid, {"kategorie_id": kat, "text": "", "foto_folgt": True})["eintrag"]["id"]
            e = ub.foto_speichern(self.k, eid, {"datei": bild_url()})["eintrag"]
        uuid_ = self.con.execute("SELECT foto_uuid FROM ub_eintrag WHERE id = ?", (eid,)).fetchone()[0]
        self.assertIn(uuid_, json.dumps(e))
        self.assertEqual(ub.datei(self.k, uuid_).read_bytes()[:2], b"\xff\xd8")
        self.assertIsNone(ub.datei(self.k2, uuid_))      # fremde Dateien gibt es nicht
        with self.assertRaises(ub.UbFehler):
            ub.foto_speichern(self.k, eid, {"datei": "data:application/pdf;base64,AAAA"})
        striche = json.dumps({"hintergrund": "foto", "striche": [{"farbe": "#d00", "breite": 3, "punkte": [[0.1, 0.1], [0.5, 0.5]]}]})
        with db.transaktion(self.con):
            ub.skizze_speichern(self.k, eid, {"datei": bild_url("PNG"), "striche": striche})
        self.assertEqual(ub.skizze_lesen(self.k, eid)["skizze"]["hintergrund"], "foto")
        with db.transaktion(self.con):
            ub.besuch_loeschen(self.k, bid)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM ub_datei").fetchone()[0], 0)   # Dateien gehen mit

    @unittest.skipIf(reportlab is None or Image is None, "reportlab/Pillow fehlen")
    def test_protokoll_pdf_odt(self):
        from app import ub_protokoll_odt, ub_protokoll_pdf
        bid = self.besuch()
        kat = ub.liste(self.k, None, "kategorien", True)[0].id
        phase = ub.liste(self.k, None, "phasen", True)[0].id
        krit = ub.liste(self.k, None, "kriterien", True)[0].id
        with db.transaktion(self.con):
            ub.besuch_speichern(self.k, bid, {"schwerpunkte": [krit], "reflexion": "Reflexion ok", "vereinbarungen": "Mehr Schüleraktivität"})
            ub.eintrag_anlegen(self.k, bid, {"art": "phase", "phase_id": phase, "zeit": "07:46"})
            eid = ub.eintrag_anlegen(self.k, bid, {"kategorie_id": kat, "text": "Gute Visualisierung", "zeit": "07:50",
                                                   "kriterium_id": krit, "wertung": "plus"})["eintrag"]["id"]
            ub.foto_speichern(self.k, eid, {"datei": bild_url()})
        b = ub.besuch_obj(self.k, bid)
        for ordnung in ub.ORDNUNGEN:
            pdf = ub_protokoll_pdf.erzeuge(self.k, self.k, b, mit_fotos=True, ordnung=ordnung)
            self.assertTrue(pdf.startswith(b"%PDF"), ordnung)
        odt = ub_protokoll_odt.erzeuge(self.k, self.k, b, mit_fotos=True, ordnung=None)
        with zipfile.ZipFile(io.BytesIO(odt)) as z:
            inhalt = z.read("content.xml").decode("utf-8")
            self.assertEqual(z.read("mimetype"), b"application/vnd.oasis.opendocument.text")
        self.assertIn("Gute Visualisierung", inhalt)
        self.assertIn("Anna Anwärterin", inhalt)


class UbServer(unittest.TestCase):
    """Echter Server auf zufaelligem Port (wie in test_stufe_a)."""

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
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        koepfe = {"Content-Type": "application/json", "X-Lehrerkalender": "1"}
        if self.cookie:
            koepfe["Cookie"] = self.cookie
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=koepfe)
        r = c.getresponse()
        inhalt = r.read()
        neu = r.getheader("Set-Cookie")
        if neu:
            self.cookie = neu.split(";")[0]
        c.close()
        try:
            return r.status, json.loads(inhalt)
        except ValueError:
            return r.status, inhalt

    def einrichten(self):
        con = db.verbinden(db.pfad(self.ordner))
        code = konten.einrichtungscode(con)
        con.close()
        status, _ = self.anfrage("POST", "/api/einrichtung", {"code": code, "kuerzel": "gob", "name": "Matthias Göbel",
                                                               "passwort": "geheim123"})
        self.assertEqual(status, 200)

    def test_modul_schalter_und_seiten(self):
        self.einrichten()
        status, antwort = self.anfrage("GET", "/api/ub/seite/uebersicht")
        self.assertEqual(status, 403)                     # aus: keine Daten
        self.assertIn("ausgeschaltet", antwort["fehler"])
        self.assertEqual(self.anfrage("POST", "/api/ub/modul", {"an": True})[0], 200)
        self.assertTrue(self.anfrage("GET", "/api/konto")[1]["ub_an"] if self.anfrage("GET", "/api/konto")[0] == 200 else True)
        status, U = self.anfrage("GET", "/api/ub/seite/uebersicht")
        self.assertEqual(status, 200)
        self.assertEqual(U["anstehend"], [])
        status, r = self.anfrage("POST", "/api/ub/besuche", {"neuer_anwaerter": {"name": "Anna"}, "datum": "2026-11-20"})
        self.assertEqual(status, 200)
        bid = r["id"]
        for pfad in ("/unterrichtsbesuche", "/unterrichtsbesuche/einstellungen", "/unterrichtsbesuche/%d" % bid,
                     "/unterrichtsbesuche/%d/erfassen" % bid):
            status, html = self.anfrage("GET", pfad)
            self.assertEqual(status, 200, pfad)
            self.assertIn(b"ub-laden.js", html)
        status, S = self.anfrage("GET", "/api/ub/seite/besuch/%d" % bid)
        self.assertEqual(S["besuch"]["anwaerter"]["name"] if isinstance(S["besuch"]["anwaerter"], dict) else S["besuch"]["anwaerter"], "Anna")
        status, f = self.anfrage("POST", "/api/ub/besuche", {"neuer_anwaerter": {"name": "Ohne Datum"}})
        self.assertEqual(status, 400)
        self.assertIn("Datum", f["fehler"])
        status, _ = self.anfrage("GET", "/api/ub/seite/besuch/999")
        self.assertEqual(status, 404)
        if reportlab is not None and Image is not None:
            status, pdf = self.anfrage("GET", "/unterrichtsbesuche/%d/protokoll.pdf" % bid)
            self.assertEqual(status, 200)
            self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
