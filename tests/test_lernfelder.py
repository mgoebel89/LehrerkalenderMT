"""Tests fuer 0.23.0: Stufen beim neuen Bildungsgang und Lernfelder durch Lehrkraefte.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import http.client
import json
import threading

from app import db, grunddaten, konten, planung, server
from test_kollegium import MitKollegin


class StufenBeimBildungsgang(MitKollegin):
    def test_lernfeld_bildungsgang_bekommt_vier_stufen(self):
        with db.transaktion(self.con):
            bid = grunddaten.bildungsgang_speichern(self.con, {"name": "Elektroniker/in", "einheit": "lernfeld"})
            mid = grunddaten.bildungsgang_speichern(self.con, {"name": "Fachschule Technik", "einheit": "modul"})
        gaenge = {b["id"]: b for b in grunddaten.alles(self.con)["bildungsgaenge"]}
        self.assertEqual([s["name"] for s in gaenge[bid]["stufen"]], ["Grundstufe", "Fachstufe 1", "Fachstufe 2", "Fachstufe 3"])
        self.assertEqual(gaenge[mid]["stufen"], [])                      # Module: keine Vorgabe
        # Stufen bleiben normal aenderbar; Aendern des Bildungsgangs legt nichts nach
        with db.transaktion(self.con):
            fs3 = gaenge[bid]["stufen"][3]["id"]
            grunddaten.stufe_loeschen(self.con, fs3)
            grunddaten.bildungsgang_speichern(self.con, {"name": "Elektroniker/in", "einheit": "lernfeld"}, bid)
        b = [x for x in grunddaten.alles(self.con)["bildungsgaenge"] if x["id"] == bid][0]
        self.assertEqual(len(b["stufen"]), 3)


class LernfelderDurchLehrkraefte(MitKollegin):
    """rei unterrichtet BSMT 24a (Bildungsgang BSMT), aber nichts in der Fachschule."""

    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.ft = grunddaten.bildungsgang_speichern(self.con, {"name": "Fachschule Technik", "einheit": "modul"})
            self.x = konten.anlegen(self.con, "xyz", "Dritte Lehrkraft", "lehrkraft", "geheim123", vorlaeufig=False)
        self.rei = konten.holen(self.con, self.rid)
        self.gob = konten.holen(self.con, self.lid)

    def anlegen(self, konto, **daten):
        with db.transaktion(self.con):
            return grunddaten.lernfeld_der_lehrkraft_speichern(self.con, konto, dict({"bildungsgang_id": self.bs, "nummer": "LF 12",
                                                                                      "name": "Instandhaltung", "stunden": 40}, **daten))

    def test_anlegen_nur_in_eigenen_bildungsgaengen(self):
        self.assertEqual(grunddaten.bildungsgaenge_der_lehrkraft(self.con, self.rid), {self.bs})
        lid = self.anlegen(self.rei)
        lf = [l for l in grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"] if l["id"] == lid][0]
        self.assertEqual((lf["besitzer_id"], lf["besitzer"]), (self.rid, "Kollege Reiter"))
        with self.assertRaises(grunddaten.GrunddatenFehler):          # keine Klasse in der Fachschule
            self.anlegen(self.rei, bildungsgang_id=self.ft, nummer="M 1")
        with self.assertRaises(grunddaten.GrunddatenFehler):          # ohne Stundenplan gar nicht
            self.anlegen(konten.holen(self.con, self.x["id"]), nummer="LF 13")
        self.anlegen(self.gob, bildungsgang_id=self.ft, nummer="M 1")  # der Admin darf ueberall
        with self.assertRaises(grunddaten.GrunddatenFehler):          # Nummer doppelt, wie beim Admin
            self.anlegen(self.rei)
        # Lernfelder des Admins haben keinen Besitzer
        alt = [l for l in grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"] if l["id"] == self.lf7][0]
        self.assertIsNone(alt["besitzer_id"])

    def test_aendern_nur_besitzer_und_admin(self):
        lid = self.anlegen(self.rei)
        with db.transaktion(self.con):
            grunddaten.lernfeld_der_lehrkraft_speichern(self.con, self.rei, {"nummer": "LF 12", "name": "Instandhaltung II", "stunden": 60}, lid)
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.lernfeld_der_lehrkraft_speichern(self.con, konten.holen(self.con, self.x["id"]), {"nummer": "LF 12", "name": "X"}, lid)
        with self.assertRaises(grunddaten.GrunddatenFehler):          # das LF des Admins darf rei nicht aendern
            grunddaten.lernfeld_der_lehrkraft_speichern(self.con, self.rei, {"nummer": "LF 7", "name": "X"}, self.lf7)
        with db.transaktion(self.con):
            grunddaten.lernfeld_der_lehrkraft_speichern(self.con, self.gob, {"nummer": "LF 12", "name": "Vom Admin", "stunden": 60}, lid)
        lf = [l for l in grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"] if l["id"] == lid][0]
        self.assertEqual((lf["name"], lf["stunden"], lf["besitzer_id"]), ("Vom Admin", 60, self.rid))   # Besitzer bleibt

    def test_loeschen_nur_unbenutzt(self):
        frei = self.anlegen(self.rei)
        benutzt = self.anlegen(self.rei, nummer="LF 13")
        with db.transaktion(self.con):
            planung.thema_speichern(self.con, self.rid, self.strang(titel="Wartung", bloecke=2, lernfeld_id=benutzt))
        with self.assertRaises(grunddaten.GrunddatenFehler) as f:
            grunddaten.lernfeld_der_lehrkraft_loeschen(self.con, self.rei, benutzt)
        self.assertIn("Planung", str(f.exception))
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.lernfeld_der_lehrkraft_loeschen(self.con, self.rei, self.lf7)   # nicht meins
        with db.transaktion(self.con):
            grunddaten.lernfeld_der_lehrkraft_loeschen(self.con, self.rei, frei)
        ids = {l["id"] for l in grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"]}
        self.assertEqual(ids, {self.lf7, self.lf9, benutzt})

    def test_konto_weg_lernfeld_bleibt(self):
        lid = self.anlegen(self.rei)
        with db.transaktion(self.con):
            self.con.execute("UPDATE lernfeld SET besitzer_id = NULL WHERE besitzer_id = ?", (self.rid,))
        lf = [l for l in grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"] if l["id"] == lid][0]
        self.assertEqual((lf["besitzer_id"], lf["besitzer"]), (None, ""))


class LernfelderUeberDenServer(MitKollegin):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.ft = grunddaten.bildungsgang_speichern(self.con, {"name": "Fachschule Technik", "einheit": "modul"})
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
        status, a, _ = self.anfrage("GET", "/api/lernfelder", wer="rei")
        self.assertEqual(status, 200)
        rechte = {b["name"]: b["darf_anlegen"] for b in a["bildungsgaenge"]}
        self.assertEqual(rechte, {"Mechatroniker/in": True, "Fachschule Technik": False})
        self.assertFalse(any(lf["darf_aendern"] for b in a["bildungsgaenge"] for lf in b["lernfelder"]))
        status, a, _ = self.anfrage("POST", "/api/lernfeld", {"bildungsgang_id": self.ft, "nummer": "M 1", "name": "X"}, wer="rei")
        self.assertEqual(status, 400, a)
        status, a, _ = self.anfrage("POST", "/api/lernfeld", {"bildungsgang_id": self.bs, "nummer": "LF 12", "name": "Instandhaltung",
                                                              "stunden": 40}, wer="rei")
        self.assertEqual(status, 200, a)
        neu = a["id"]
        lf = [l for b in a["bildungsgaenge"] for l in b["lernfelder"] if l["id"] == neu][0]
        self.assertEqual((lf["besitzer"], lf["darf_aendern"]), ("Kollege Reiter", True))
        status, a, _ = self.anfrage("POST", "/api/lernfeld/%d" % self.lf7, {"nummer": "LF 7", "name": "X"}, wer="rei")
        self.assertEqual(status, 400, a)
        status, a, _ = self.anfrage("GET", "/api/lernfelder", wer="gob")
        self.assertTrue(all(b["darf_anlegen"] for b in a["bildungsgaenge"]))
        self.assertTrue(all(lf["darf_aendern"] for b in a["bildungsgaenge"] for lf in b["lernfelder"]))
        status, a, _ = self.anfrage("POST", "/api/lernfeld/%d/loeschen" % neu, {}, wer="rei")
        self.assertEqual(status, 200, a)
        self.assertNotIn(neu, [l["id"] for b in a["bildungsgaenge"] for l in b["lernfelder"]])
        art = self.con.execute("SELECT wer, art FROM protokoll WHERE art LIKE 'lernfeld_%' ORDER BY id").fetchall()
        self.assertEqual([tuple(z) for z in art], [("rei", "lernfeld_angelegt"), ("rei", "lernfeld_geloescht")])
