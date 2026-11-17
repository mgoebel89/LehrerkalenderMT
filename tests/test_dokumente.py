"""Stufe F3a: Dokumente (eigenes Paperless je Konto) gegen die Paperless-Attrappe, dazu die weiteren Ziele ueber das VPN.
Braucht das Paket cryptography (Debian: python3-cryptography), sonst uebersprungen.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import http.client
import ipaddress
import json
import os
import shutil
import tempfile
import threading
import unittest

try:
    import cryptography   # noqa: F401
except ImportError:
    cryptography = None

from app import db, konten, paperless, server, vpn
import paperless_attrappe as attrappe


@unittest.skipIf(cryptography is None, "cryptography fehlt (python3-cryptography)")
class Dokumente(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.url = attrappe.starten()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        attrappe.Attrappe.D = attrappe.daten_neu()
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.a = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.b = konten.anlegen(self.con, "mus", "Erika Muster", "lehrkraft", "geheim123", vorlaeufig=False)
        self.lid = self.a["id"]

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def verbinden(self, **mehr):
        with db.transaktion(self.con):
            return paperless.konfig_speichern(self.con, self.lid, self.ordner, dict({"url": self.url + "/", "token": attrappe.TOKEN}, **mehr))

    def test_verbinden_verschluesselt_und_ohne_token_nach_aussen(self):
        with self.assertRaises(paperless.PaperlessFehler) as f:           # falscher Token
            self.verbinden(token="falscher-token-123")
        self.assertEqual(f.exception.status, 401)
        with self.assertRaises(paperless.PaperlessFehler):               # Unsinn als Adresse
            self.verbinden(url="ftp://x")
        self.assertEqual(self.verbinden(), 3)
        roh = self.con.execute("SELECT paperless FROM lehrkraft WHERE id = ?", (self.lid,)).fetchone()[0]
        self.assertNotIn(attrappe.TOKEN, roh)                              # Token nicht im Klartext in der Datenbank
        o = paperless.konfig_oeffentlich(self.con, self.lid, self.ordner)
        self.assertEqual((o["verbunden"], o["url"]), (True, self.url))
        self.assertNotIn("token", o)
        self.assertTrue(konten.oeffentlich(self.con.execute("SELECT * FROM lehrkraft WHERE id = ?", (self.lid,)).fetchone())["paperless"])
        # Token leer = bisheriger bleibt (Tags aendern), aber nicht bei neuer Adresse
        with db.transaktion(self.con):
            paperless.konfig_speichern(self.con, self.lid, self.ordner, {"url": self.url, "token": "", "tags": [1, 3], "upload_tag": 3, "pfad": 1})
        self.assertEqual(paperless.konfig(self.con, self.lid, self.ordner)["token"], attrappe.TOKEN)
        with self.assertRaises(paperless.PaperlessFehler):
            paperless.konfig_speichern(self.con, self.lid, self.ordner, {"url": "http://127.0.0.1:1", "token": ""})
        # anderer Schluessel (z. B. Sicherung auf einer anderen Instanz eingespielt): verstaendliche Meldung
        andere = tempfile.mkdtemp()
        try:
            o = paperless.konfig_oeffentlich(self.con, self.lid, andere)
            self.assertFalse(o["verbunden"])
            self.assertIn("neu verbinden", o["fehler"])
        finally:
            shutil.rmtree(andere, ignore_errors=True)
        self.assertFalse(paperless.verbunden(self.con, self.b["id"]))
        with self.assertRaises(paperless.PaperlessFehler):               # die Kollegin hat keins
            paperless.suchen(self.con, self.b["id"], self.ordner)

    def test_liste_nur_mit_anzeige_tags(self):
        self.verbinden(tags=[1, 3])
        d = paperless.suchen(self.con, self.lid, self.ordner)
        self.assertEqual({x["titel"] for x in d["dokumente"]}, {"Arbeitsblatt Pneumatik", "Klassenarbeit LF 7 Lösung"})   # nicht Privat
        self.assertEqual(paperless.suchen(self.con, self.lid, self.ordner, tags=["2"])["anzahl"], 2)   # Privat ist kein Anzeige-Tag
        self.assertEqual([x["titel"] for x in paperless.suchen(self.con, self.lid, self.ordner, suche="pneu")["dokumente"]], ["Arbeitsblatt Pneumatik"])
        st = paperless.stammlisten(self.con, self.lid, self.ordner)
        self.assertEqual((len(st["tags"]), st["anzeige_tags"]), (4, [1, 3]))

    def test_dokument_aendern_notizen_dateien(self):
        self.verbinden()
        d = paperless.aendern(self.con, self.lid, self.ordner, 1, {"titel": "AB Pneumatik 1", "datum": "2026-10-06", "tags": [1, 4, 3], "typ": 0})
        self.assertEqual((d["titel"], d["datum"], d["tags"], d["typ"]), ("AB Pneumatik 1", "2026-10-06", [1, 4, 3], None))
        with self.assertRaises(paperless.PaperlessFehler):
            paperless.aendern(self.con, self.lid, self.ordner, 1, {"titel": ""})
        d = paperless.notiz_neu(self.con, self.lid, self.ordner, 1, "Lösung liegt in KA-Ordner")
        self.assertEqual([n["text"] for n in d["notizen"]], ["Lösung liegt in KA-Ordner"])
        d = paperless.notiz_loeschen(self.con, self.lid, self.ordner, 1, d["notizen"][0]["id"])
        self.assertEqual(d["notizen"], [])
        inhalt, typ, name = paperless.datei(self.con, self.lid, self.ordner, 1, "download")
        self.assertEqual((typ, name), ("application/pdf", "ab-pneumatik.pdf"))
        self.assertTrue(inhalt.startswith(b"%PDF"))
        self.assertEqual(paperless.datei(self.con, self.lid, self.ordner, 1, "thumb")[1], "image/png")
        with self.assertRaises(paperless.PaperlessFehler) as f:
            paperless.dokument(self.con, self.lid, self.ordner, 99)
        self.assertEqual(f.exception.status, 404)

    def test_hochladen_mit_upload_tag_und_pfad(self):
        self.verbinden(tags=[1], upload_tag=3, pfad=1)
        task = paperless.hochladen(self.con, self.lid, self.ordner, "C:\\fakepath\\Ergebnis \"KA\".pdf", b"%PDF-1.4 test", "application/pdf",
                                   "Ergebnisliste KA", "2026-11-17", 1, 2, ["4"])
        up = attrappe.Attrappe.D["uploads"][-1]
        self.assertEqual(up["datei"], "Ergebnis _KA_.pdf")
        self.assertEqual((up["felder"]["title"], up["felder"]["storage_path"], sorted(up["felder"]["tags"])),
                         (["Ergebnisliste KA"], ["1"], ["3", "4"]))
        a = paperless.aufgabe(self.con, self.lid, self.ordner, task)
        self.assertEqual((a["stand"], a["dokument"]), ("SUCCESS", 4))
        self.assertEqual(paperless.aufgabe(self.con, self.lid, self.ordner, "00000000-0000-0000-0000-000000000000")["stand"], "PENDING")
        with self.assertRaises(paperless.PaperlessFehler):
            paperless.aufgabe(self.con, self.lid, self.ordner, "../etc")
        with self.assertRaises(paperless.PaperlessFehler):
            paperless.hochladen(self.con, self.lid, self.ordner, "x.pdf", b"")


@unittest.skipIf(cryptography is None, "cryptography fehlt (python3-cryptography)")
class DokumenteUeberDenServer(unittest.TestCase):
    """Rohes Hochladen, Dateiantworten (Content-Disposition) und dass niemand ohne Anmeldung an Dokumente kommt."""

    @classmethod
    def setUpClass(cls):
        cls.p_srv, cls.p_url = attrappe.starten()
        cls.ordner = tempfile.mkdtemp()
        cls.alt_daten = server.DATEN_DIR
        server.DATEN_DIR = cls.ordner
        con = db.oeffnen(cls.ordner)
        with db.transaktion(con):
            a = konten.anlegen(con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            paperless.konfig_speichern(con, a["id"], cls.ordner, {"url": cls.p_url, "token": attrappe.TOKEN, "upload_tag": 3})
        con.close()
        cls.srv = server.HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.srv.db_pfad = db.pfad(cls.ordner)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]
        status, _, kopf = cls.anfrage("POST", "/api/anmelden", json.dumps({"kuerzel": "gob", "passwort": "geheim123"}).encode(),
                                      {"Content-Type": "application/json"})
        cls.keks = kopf.get("Set-Cookie", "").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.p_srv.shutdown()
        cls.p_srv.server_close()
        server.DATEN_DIR = cls.alt_daten
        shutil.rmtree(cls.ordner, ignore_errors=True)

    @classmethod
    def anfrage(cls, methode, pfad, body=None, kopf=None, keks=True):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        k = {"X-Lehrerkalender": "1"}
        if keks and getattr(cls, "keks", None):
            k["Cookie"] = cls.keks
        k.update(kopf or {})
        c.request(methode, pfad, body=body, headers=k)
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        return r.status, inhalt, dict(r.getheaders())

    def test_ablauf(self):
        status, inhalt, _ = self.anfrage("GET", "/api/dokumente/konfig")
        self.assertEqual(status, 200)
        self.assertNotIn(attrappe.TOKEN, inhalt.decode())
        status, inhalt, _ = self.anfrage("GET", "/api/dokumente?tags=&suche=Klassen")
        self.assertEqual((status, json.loads(inhalt)["anzahl"]), (200, 1))
        status, inhalt, kopf = self.anfrage("GET", "/api/dokumente/1/download")
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''ab-pneumatik.pdf", kopf["Content-Disposition"])
        status, _, kopf = self.anfrage("GET", "/api/dokumente/1/preview")
        self.assertEqual((status, kopf.get("Content-Disposition")), (200, None))      # PDF darf im Browser aufgehen
        status, inhalt, _ = self.anfrage("POST", "/api/dokumente/hochladen?name=Liste.pdf&titel=Liste&tags=1", b"%PDF-1.4 x",
                                         {"Content-Type": "application/pdf"})
        self.assertEqual(status, 200, inhalt)
        self.assertTrue(json.loads(inhalt)["task"])
        self.assertEqual(sorted(attrappe.Attrappe.D["uploads"][-1]["felder"]["tags"]), ["1", "3"])
        status, _, _ = self.anfrage("GET", "/api/dokumente", keks=False)
        self.assertEqual(status, 401)
        status, _, _ = self.anfrage("POST", "/api/dokumente/hochladen?name=a.pdf", b"x", {"Content-Type": "application/pdf"}, keks=False)
        self.assertIn(status, (401, 403))


class VpnZiele(unittest.TestCase):
    SCHULE = [("eth0", ipaddress.IPv4Network("172.20.0.0/16"))]

    def test_ziele_pruefen(self):
        self.assertEqual(vpn.ziele_pruefen("192.168.5.20, 192.168.5.0/24 192.168.5.20", self.SCHULE), ["192.168.5.20/32", "192.168.5.0/24"])
        self.assertEqual(vpn.ziele_pruefen("", self.SCHULE), [])
        for falsch in ("8.8.8.8", "10.0.0.0/8", "172.20.5.10", "keine-adresse"):
            with self.assertRaises(vpn.VpnFehler, msg=falsch):
                vpn.ziele_pruefen(falsch, self.SCHULE)
        with self.assertRaises(vpn.VpnFehler):
            vpn.ziele_pruefen(" ".join("192.168.9.%d" % i for i in range(1, 12)), self.SCHULE)

    def test_auftrag_und_konf(self):
        a = vpn.angaben_pruefen({"aktion": "ziele", "ziele": "192.168.5.20"}, self.SCHULE)
        self.assertEqual(a, {"aktion": "ziele", "netze": "192.168.5.20/32"})
        self.assertEqual(vpn.ziele_lesen("# Zugriff = 172.20.5.191\n# Ziele = 192.168.5.20/32 192.168.7.0/24\n[Interface]"),
                         ["192.168.5.20/32", "192.168.7.0/24"])
        self.assertEqual(vpn.ziele_lesen("# Ziele = \n[Interface]"), [])
        self.assertEqual(vpn.ziele_lesen("[Interface]"), [])

    def test_weg_von_der_seite_bis_root(self):
        """Webdienst legt den Auftrag ab, root liest und prueft ihn erneut: die Ziele muessen dabei ankommen
        (0.18.0 verlor sie, weil der Auftrag sie unter "netze" ablegte, root aber "ziele" las)."""
        ordner = tempfile.mkdtemp()
        alt = (vpn.EINHEIT, vpn.VPN_DIR, vpn.eigene_netze)
        try:
            vpn.EINHEIT = os.path.join(ordner, "einheit")
            open(vpn.EINHEIT, "w").close()
            vpn.VPN_DIR = os.path.join(ordner, "stand")
            os.makedirs(vpn.VPN_DIR)
            with open(os.path.join(vpn.VPN_DIR, "einrichtung.json"), "w", encoding="utf-8") as f:
                json.dump({"aktiv": True, "adresse": "10.0.0.9"}, f)
            vpn.eigene_netze = lambda: self.SCHULE
            vpn.anfordern(ordner, {"aktion": "ziele", "ziele": "192.168.6.20"})
            a = vpn.anfrage_lesen(os.path.join(ordner, "vpn", "anfrage.json"))
            self.assertEqual((a["aktion"], a["netze"]), ("ziele", "192.168.6.20/32"))
            with self.assertRaises(vpn.VpnFehler):                 # Schulnetz wird auch auf dem Weg abgewiesen
                vpn.anfordern(ordner, {"aktion": "ziele", "ziele": "172.20.5.10"})
        finally:
            vpn.EINHEIT, vpn.VPN_DIR, vpn.eigene_netze = alt
            shutil.rmtree(ordner, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
