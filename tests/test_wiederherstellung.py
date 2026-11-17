"""Sicherung einspielen (Admin > System): z. B. die Testinstanz ins Produktivsystem uebernehmen.

Hochladen und pruefen (Webdienst), Auftrag mit Passwort, Austausch als Dienstbenutzer (sonst root ueber systemd).
"""
import http.client
import io
import json
import os
import pathlib
import shutil
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

from app import db, konten, server, updates, wiederherstellung
from app.server import COOKIE


def instanz(ordner, kuerzel="gob", name="Matthias Göbel", schule=None):
    """Daten-Ordner mit einem Admin-Konto (und ggf. Schulnamen); Rueckgabe: offene Verbindung."""
    con = db.oeffnen(ordner)
    with db.transaktion(con):
        konten.anlegen(con, kuerzel, name, "admin", "geheim123", vorlaeufig=False)
        if schule:
            db.einstellung_setzen(con, "schule_name", schule)
        db.protokoll(con, kuerzel, "test")
    return con


class Grundlagen(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        self.test = os.path.join(self.ordner, "test")       # Testinstanz (Quelle)
        self.prod = os.path.join(self.ordner, "prod")       # Produktivsystem (Ziel)
        for name, wert in (("STAND_DIR", os.path.join(self.ordner, "stand")), ("EINHEIT", os.path.join(self.ordner, "einheit.path"))):
            p = mock.patch.object(wiederherstellung, name, wert)
            p.start()
            self.addCleanup(p.stop)
        con = instanz(self.test, schule="David Roentgen Schule Neuwied")
        with db.transaktion(con):
            konten.anlegen(con, "mus", "Erika Muster", "lehrkraft", "geheim456", vorlaeufig=False)
        self.zip = updates.sicherung(con)   # wie "Sicherung herunterladen"
        con.close()
        self.addCleanup(lambda: os.path.exists(self.zip) and os.remove(self.zip))
        con = instanz(self.prod, kuerzel="adm", name="Produktiv Admin")
        con.close()

    def test_bereitlegen_zeigt_inhalt(self):
        a = wiederherstellung.bereitlegen(self.zip, self.prod)
        self.assertEqual((a["konten"], a["admins"], a["schule"], a["stand"]), (2, ["gob"], "David Roentgen Schule Neuwied", len(db.MIGRATIONEN)))
        self.assertEqual(len(a["pruefsumme"]), 64)
        self.assertEqual(wiederherstellung.hochgeladen(self.prod)["pruefsumme"], a["pruefsumme"])
        # die .sqlite-Datei geht genauso
        with zipfile.ZipFile(self.zip) as z:
            roh = z.read(db.DATEINAME)
        sqlite = os.path.join(self.ordner, "nur.sqlite")
        with open(sqlite, "wb") as f:
            f.write(roh)
        self.assertEqual(wiederherstellung.bereitlegen(sqlite, self.prod)["konten"], 2)

    def test_einspielen_ersetzt_alles(self):
        con = db.verbinden(db.pfad(self.prod))
        alt_geheimnis = konten._geheimnis(con)
        con.commit()
        con.close()
        a = wiederherstellung.bereitlegen(self.zip, self.prod)
        open(wiederherstellung.EINHEIT, "w").close()
        wiederherstellung.anfordern(self.prod, a["pruefsumme"])
        self.assertTrue(wiederherstellung.stand(self.prod)["wartet"])
        ausgabe = []
        wiederherstellung.ausfuehren(self.prod, ausgabe=ausgabe.append)
        con = db.verbinden(db.pfad(self.prod))
        try:
            self.assertEqual(sorted(z[0] for z in con.execute("SELECT kuerzel FROM lehrkraft")), ["gob", "mus"])   # Testinstanz
            self.assertIsNone(db.einstellung(con, "sitzung_geheimnis"))   # alle Anmeldungen beendet
            self.assertNotEqual(alt_geheimnis, konten._geheimnis(con))
            self.assertEqual(con.execute("SELECT art FROM protokoll ORDER BY id DESC LIMIT 1").fetchone()[0], "sicherung_eingespielt")
        finally:
            con.close()
        sicherungen = updates.sicherungen(self.prod)
        self.assertEqual(len(sicherungen), 1)
        self.assertTrue(sicherungen[0]["name"].startswith("vor-wiederherstellung-"))
        with zipfile.ZipFile(os.path.join(self.prod, "sicherungen", sicherungen[0]["name"])) as z:   # alter Stand ist drin
            pfad = os.path.join(self.ordner, "alt.sqlite")
            with open(pfad, "wb") as f:
                f.write(z.read(db.DATEINAME))
        self.assertEqual(wiederherstellung.pruefen(pfad)["admins"], ["adm"])
        self.assertIsNone(wiederherstellung.hochgeladen(self.prod))   # aufgeraeumt
        self.assertFalse(wiederherstellung.stand(self.prod)["wartet"])
        self.assertTrue(any("ausgetauscht" in z for z in ausgabe))

    def test_ohne_passenden_auftrag_nichts(self):
        a = wiederherstellung.bereitlegen(self.zip, self.prod)
        with self.assertRaises(wiederherstellung.WiederherstellungFehler):   # Units fehlen (nicht im Container)
            wiederherstellung.anfordern(self.prod, a["pruefsumme"])
        open(wiederherstellung.EINHEIT, "w").close()
        with self.assertRaises(wiederherstellung.WiederherstellungFehler):
            wiederherstellung.anfordern(self.prod, "0" * 64)
        with self.assertRaises(wiederherstellung.WiederherstellungFehler):   # kein Auftrag
            wiederherstellung.ausfuehren(self.prod, ausgabe=lambda t: None)
        wiederherstellung.anfordern(self.prod, a["pruefsumme"])
        with self.assertRaises(wiederherstellung.WiederherstellungFehler):   # zweimal geht nicht
            wiederherstellung.anfordern(self.prod, a["pruefsumme"])
        # Datei nach dem Bestaetigen ausgetauscht: nichts einspielen
        with open(os.path.join(wiederherstellung.ordner(self.prod), wiederherstellung.HOCHGELADEN), "ab") as f:
            f.write(b"\0" * 10)
        with self.assertRaises(wiederherstellung.WiederherstellungFehler) as f:
            wiederherstellung.ausfuehren(self.prod, ausgabe=lambda t: None)
        self.assertIn("geändert", str(f.exception))
        con = db.verbinden(db.pfad(self.prod))
        self.assertEqual([z[0] for z in con.execute("SELECT kuerzel FROM lehrkraft")], ["adm"])
        con.close()

    def test_abgelehnt(self):
        def datei(name, inhalt):
            p = os.path.join(self.ordner, name)
            with open(p, "wb") as f:
                f.write(inhalt)
            return p
        # neuere Version
        neuer = os.path.join(self.ordner, "neuer")
        con = instanz(neuer)
        con.execute("PRAGMA user_version = %d" % (len(db.MIGRATIONEN) + 1))
        con.commit()
        con.close()
        # ohne Admin
        ohne = os.path.join(self.ordner, "ohne")
        con = instanz(ohne)
        with db.transaktion(con):
            con.execute("UPDATE lehrkraft SET rolle = 'lehrkraft'")
        con.close()
        leer_zip = io.BytesIO()
        with zipfile.ZipFile(leer_zip, "w") as z:
            z.writestr("LIESMICH.txt", "nichts")
        faelle = [
            (db.pfad(neuer), "neueren Version"),
            (db.pfad(ohne), "kein (entsperrtes) Admin-Konto"),
            (datei("text.txt", b"hallo welt, keine datenbank"), "Bitte eine Sicherung"),
            (datei("leer.zip", leer_zip.getvalue()), "fehlt"),
            (datei("kaputt.zip", b"PK\x03\x04kaputt"), "beschädigt"),
            (datei("fremd.sqlite", wiederherstellung.SQLITE_KOPF + b"\0" * 100), "Datenbank"),
        ]
        for pfad, hinweis in faelle:
            with self.subTest(hinweis=hinweis), self.assertRaises(wiederherstellung.WiederherstellungFehler) as f:
                wiederherstellung.bereitlegen(pfad, self.prod)
            self.assertIn(hinweis, str(f.exception))
        self.assertIsNone(wiederherstellung.hochgeladen(self.prod))
        self.assertEqual(os.listdir(wiederherstellung.ordner(self.prod)), [])   # keine Reste

    def test_konsole(self):
        with mock.patch.dict(os.environ, {"LEHRERKALENDER_DATEN": self.prod}), mock.patch("sys.stdout", new_callable=io.StringIO) as aus:
            from app import cli
            self.assertEqual(cli.main(["wiederherstellung-pruefen", self.zip]), 0)
            self.assertEqual(cli.main(["wiederherstellung-ausfuehren", "--konsole"]), 0)
        self.assertIn("Admins: gob", aus.getvalue())
        con = db.verbinden(db.pfad(self.prod))
        self.assertIn("gob", [z[0] for z in con.execute("SELECT kuerzel FROM lehrkraft")])
        con.close()


class Api(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, True)
        einheit = os.path.join(self.ordner, "einheit.path")
        open(einheit, "w").close()
        for ziel, name, wert in ((wiederherstellung, "STAND_DIR", os.path.join(self.ordner, "stand")), (wiederherstellung, "EINHEIT", einheit),
                                 (server, "DATEN_DIR", self.ordner)):
            p = mock.patch.object(ziel, name, wert)
            p.start()
            self.addCleanup(p.stop)
        con = instanz(self.ordner)
        with db.transaktion(con):
            konten.anlegen(con, "abc", "A. Beispiel", "lehrkraft", "geheim456", vorlaeufig=False)
        self.cookies = {k: COOKIE + "=" + konten.anmelden(con, k, pw)[0] for k, pw in (("gob", "geheim123"), ("abc", "geheim456"))}
        con.commit()
        quelle = os.path.join(self.ordner, "quelle")
        c2 = instanz(quelle, kuerzel="neu")
        self.zip = updates.sicherung(c2)
        c2.close()
        self.addCleanup(os.remove, self.zip)
        con.close()
        self.srv = server.HTTPServer(("127.0.0.1", 0), server.Handler, db.pfad(self.ordner))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def anfrage(self, pfad, inhalt, wer="gob", typ="application/json", kopf=True):
        v = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=20)
        k = {"Content-Type": typ, "Cookie": self.cookies[wer]}
        if kopf:
            k["X-Lehrerkalender"] = "1"
        v.request("POST", pfad, body=inhalt, headers=k)
        a = v.getresponse()
        d = json.loads(a.read() or b"{}")
        v.close()
        return a.status, d

    def test_hochladen_und_einspielen(self):
        with open(self.zip, "rb") as f:
            roh = f.read()
        self.assertEqual(self.anfrage("/api/admin/wiederherstellung/hochladen", roh, "abc", "application/octet-stream")[0], 403)
        self.assertEqual(self.anfrage("/api/admin/wiederherstellung/hochladen", roh, typ="application/octet-stream", kopf=False)[0], 403)
        status, d = self.anfrage("/api/admin/wiederherstellung/hochladen", roh, typ="application/octet-stream")
        self.assertEqual(status, 200, d)
        h = d["hochgeladen"]
        self.assertEqual(h["admins"], ["neu"])
        status, d = self.anfrage("/api/admin/wiederherstellung/hochladen", b"keine sicherung", typ="application/octet-stream")
        self.assertEqual(status, 400)
        status, d = self.anfrage("/api/admin/wiederherstellung/einspielen", json.dumps({"passwort": "falsch", "pruefsumme": h["pruefsumme"]}))
        self.assertEqual((status, d["fehler"]), (400, "Das Passwort stimmt nicht."))
        status, d = self.anfrage("/api/admin/wiederherstellung/einspielen", json.dumps({"passwort": "geheim123", "pruefsumme": h["pruefsumme"]}))
        self.assertEqual(status, 200, d)
        self.assertTrue(d["wartet"])
        with open(os.path.join(self.ordner, "wiederherstellung", "einspielen"), encoding="utf-8") as f:
            self.assertNotIn("geheim", f.read())   # das Passwort landet nie im Auftrag
        status, d = self.anfrage("/api/admin/wiederherstellung/verwerfen", "{}")
        self.assertEqual(status, 400)   # schon beauftragt

    def test_verwerfen(self):
        with open(self.zip, "rb") as f:
            self.anfrage("/api/admin/wiederherstellung/hochladen", f.read(), typ="application/octet-stream")
        status, d = self.anfrage("/api/admin/wiederherstellung/verwerfen", "{}")
        self.assertEqual((status, d["hochgeladen"]), (200, None))


class Skripte(unittest.TestCase):
    def lies(self, name):
        return (pathlib.Path(__file__).resolve().parent.parent / "deploy" / name).read_text(encoding="utf-8")

    def test_installiert(self):
        inst = self.lies("install.sh")
        for teil in ("deploy/wiederherstellen.sh /usr/local/sbin/lehrerkalender-wiederherstellen", "lehrerkalender-wiederherstellen.path",
                     "lehrerkalender-wiederherstellen.service", '"$DATEN/wiederherstellung"', "/var/lib/lehrerkalender-wiederherstellung"):
            self.assertIn(teil, inst)

    def test_root_liest_die_datei_nie(self):
        sh = self.lies("wiederherstellen.sh")
        self.assertIn("/usr/local/bin/lehrerkalender wiederherstellung-ausfuehren", sh)   # als Dienstbenutzer
        self.assertIn('rm -f "$DATEN/wiederherstellung/einspielen"', sh)
        self.assertNotIn("hochgeladen.sqlite", sh)
        self.assertIn("PathExists=/var/lib/lehrerkalender/wiederherstellung/einspielen", self.lies("lehrerkalender-wiederherstellen.path"))


if __name__ == "__main__":
    unittest.main()
