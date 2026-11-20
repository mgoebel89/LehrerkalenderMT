"""Tests fuer 0.26.0: Beobachtungen je Schueler (app/beobachtungen.py): privat je Lehrkraft, mehrere Schueler aus einer
Stunde, Verlauf, Klassenuebersicht mit Filtern, PDFs, Aufraeumen, Zusammenfuehren und Loeschsperre.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import datetime
import http.client
import json
import threading

from app import beobachtungen, db, fotos, schuelerliste, server
from test_kollegium import MitKollegin
from test_fotos import DATA_URL


class Beobachtungen(MitKollegin):
    """gob und rei unterrichten BSMT 24a; gob zusaetzlich 25a."""

    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
            self.deniz = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Yılmaz", "vorname": "Deniz"})
            self.fritz = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k25, "nachname": "Fremd", "vorname": "Fritz"})

    def notiere(self, lid, ids, **mehr):
        with db.transaktion(self.con):
            return beobachtungen.anlegen(self.con, lid, dict({"schueler_ids": ids, "datum": "2026-11-20", "text": "arbeitet sauber",
                                                              "kategorie": "Arbeitsverhalten", "tendenz": "positiv"}, **mehr))

    def test_privat_je_lehrkraft(self):
        self.notiere(self.lid, [self.clara])
        self.notiere(self.rid, [self.clara], text="spricht kaum", kategorie="Sozialverhalten", tendenz="neutral")
        gob = beobachtungen.verlauf(self.con, self.lid, self.clara)["eintraege"]
        rei = beobachtungen.verlauf(self.con, self.rid, self.clara)["eintraege"]
        self.assertEqual(([e["text"] for e in gob], [e["text"] for e in rei]), (["arbeitet sauber"], ["spricht kaum"]))
        with self.assertRaises(beobachtungen.BeobachtungFehler):              # fremden Eintrag aendern/loeschen
            beobachtungen.loeschen(self.con, self.rid, gob[0]["id"])
        with self.assertRaises(beobachtungen.BeobachtungFehler):              # rei kennt 25a nicht
            self.notiere(self.rid, [self.fritz])
        self.assertEqual(beobachtungen.zusammenfassung(self.con, self.rid, self.k24)[self.clara]["anzahl"], 1)

    def test_eingaben_pruefen(self):
        for falsch in ({"text": ""}, {"kategorie": "Quatsch"}, {"tendenz": "super"}, {"datum": "gestern"}):
            with self.assertRaises(beobachtungen.BeobachtungFehler):
                self.notiere(self.lid, [self.clara], **falsch)
        with self.assertRaises(beobachtungen.BeobachtungFehler):              # zwei Klassen auf einmal
            self.notiere(self.lid, [self.clara, self.fritz])
        with self.assertRaises(beobachtungen.BeobachtungFehler):
            self.notiere(self.lid, [])
        ohne = self.notiere(self.lid, [self.clara], kategorie="", tendenz=None)
        e = beobachtungen.verlauf(self.con, self.lid, self.clara)["eintraege"][0]
        self.assertEqual((e["id"], e["kategorie"], e["tendenz"]), (ohne[0], "", "neutral"))

    def test_aus_der_stunde_fuer_mehrere(self):
        ids = self.notiere(self.lid, [self.clara, self.deniz, self.clara], stunde_datum="2026-11-20", stunde_beginn="07:45",
                           stunde_text="1. Block · Pneumatik")
        self.assertEqual(len(ids), 2)                                          # doppelte Auswahl zaehlt einmal
        st = beobachtungen.stunde(self.con, self.lid, "2026-11-20", "07:45")
        self.assertEqual(sorted(e["name"] for e in st), ["Weiß, Clara", "Yılmaz, Deniz"])
        self.assertEqual(st[0]["stunde_text"], "1. Block · Pneumatik")
        self.assertEqual(beobachtungen.stunde(self.con, self.rid, "2026-11-20", "07:45"), [])

    def test_aendern_und_verlauf_sortiert(self):
        alt, = self.notiere(self.lid, [self.clara], datum="2026-09-01", text="alt")
        self.notiere(self.lid, [self.clara], datum="2026-11-01", text="neu")
        with db.transaktion(self.con):
            beobachtungen.aendern(self.con, self.lid, alt, {"datum": "2026-10-01", "text": "geändert", "tendenz": "negativ", "kategorie": "Leistung"})
        v = beobachtungen.verlauf(self.con, self.lid, self.clara)
        self.assertEqual([(e["datum"], e["text"], e["tendenz"]) for e in v["eintraege"]],
                         [("2026-11-01", "neu", "positiv"), ("2026-10-01", "geändert", "negativ")])
        self.assertEqual((v["schueler"]["name"], v["schueler"]["klasse"]), ("Weiß, Clara", "BSMT 24a"))

    def test_klassenuebersicht_filter(self):
        self.notiere(self.lid, [self.clara], datum="2026-10-01", kategorie="Leistung", tendenz="negativ", text="Test verhauen")
        self.notiere(self.lid, [self.deniz], datum="2026-11-10")
        self.notiere(self.lid, [self.fritz], datum="2026-11-10")                  # andere Klasse
        k = beobachtungen.klasse(self.con, self.lid, self.k24)
        self.assertEqual(len(k["eintraege"]), 2)
        self.assertEqual({s["name"]: s["beobachtungen"]["anzahl"] for s in k["schueler"]}, {"Weiß, Clara": 1, "Yılmaz, Deniz": 1})
        self.assertEqual([e["text"] for e in beobachtungen.klasse(self.con, self.lid, self.k24, kategorie="Leistung")["eintraege"]], ["Test verhauen"])
        self.assertEqual(len(beobachtungen.klasse(self.con, self.lid, self.k24, tendenz="positiv")["eintraege"]), 1)
        self.assertEqual(len(beobachtungen.klasse(self.con, self.lid, self.k24, von="2026-11-01")["eintraege"]), 1)
        self.assertEqual(len(beobachtungen.klasse(self.con, self.lid, self.k24, suche="yılmaz")["eintraege"]), 1)
        self.assertEqual(len(beobachtungen.klasse(self.con, self.lid, self.k24, suche="verhauen")["eintraege"]), 1)

    def test_pdfs(self):
        with db.transaktion(self.con):
            fotos.setzen(self.con, self.lid, self.clara, DATA_URL)
        for i in range(30):                                                    # mehrere Seiten
            self.notiere(self.lid, [self.clara], datum="2026-10-%02d" % (i % 28 + 1), text="Eintrag %d " % i + "mit etwas mehr Text " * 6)
        self.notiere(self.lid, [self.deniz], stunde_datum="2026-11-20", stunde_beginn="07:45", stunde_text="1. Block", tendenz="negativ")
        inhalt, name = beobachtungen.schueler_pdf(self.con, self.lid, self.clara, "Matthias Göbel")
        self.assertTrue(inhalt.startswith(b"%PDF"))
        self.assertIn(b"/DCTDecode", inhalt)                                   # Foto
        self.assertGreater(inhalt.count(b"/Type /Page "), 1)
        self.assertTrue(name.startswith("Beobachtungen Weiß Clara"))
        inhalt, name = beobachtungen.klasse_pdf(self.con, self.lid, self.k24, "Matthias Göbel", tendenz="negativ")
        self.assertTrue(inhalt.startswith(b"%PDF") and name.startswith("Beobachtungen BSMT 24a"))
        with self.assertRaises(beobachtungen.BeobachtungFehler):              # rei hat keine
            beobachtungen.schueler_pdf(self.con, self.rid, self.clara)
        with self.assertRaises(beobachtungen.BeobachtungFehler):
            beobachtungen.klasse_pdf(self.con, self.lid, self.k24, kategorie="Sonstiges")

    def test_aufraeumen_nur_alte_zu_inaktiven(self):
        self.notiere(self.lid, [self.clara], datum="2025-06-01", text="alt, Schüler weg")
        self.notiere(self.lid, [self.clara], datum="2026-06-01", text="jünger")
        self.notiere(self.lid, [self.deniz], datum="2025-06-01", text="alt, Schüler noch da")
        self.notiere(self.rid, [self.clara], datum="2025-06-01", text="von rei")
        with db.transaktion(self.con):
            schuelerliste.speichern(self.con, self.lid, {"nachname": "Weiß", "vorname": "Clara", "aktiv": False}, self.clara)
        heute = datetime.date(2026, 11, 20)
        stand = beobachtungen.aufraeumen_stand(self.con, self.lid, heute)
        self.assertEqual((stand["anzahl"], stand["schueler"]), (1, [{"name": "Weiß, Clara", "klasse": "BSMT 24a", "anzahl": 1}]))
        with db.transaktion(self.con):
            self.assertEqual(beobachtungen.aufraeumen(self.con, self.lid, heute), 1)
        texte = sorted(z[0] for z in self.con.execute("SELECT text FROM beobachtung"))
        self.assertEqual(texte, ["alt, Schüler noch da", "jünger", "von rei"])

    def test_zusammenfuehren_und_loeschsperre(self):
        with db.transaktion(self.con):
            zweite = schuelerliste.speichern(self.con, self.rid, {"klasse_id": self.k24, "nachname": "Weiss", "vorname": "Clara"})
        self.notiere(self.rid, [zweite], text="von rei an der Doppelung")
        with db.transaktion(self.con):
            schuelerliste.zusammenfuehren(self.con, self.lid, self.clara, zweite)
        self.assertEqual([e["text"] for e in beobachtungen.verlauf(self.con, self.rid, self.clara)["eintraege"]], ["von rei an der Doppelung"])
        with self.assertRaises(schuelerliste.SchuelerFehler):                 # gob sieht rei's Eintrag nicht, darf trotzdem nicht loeschen
            schuelerliste.loeschen(self.con, self.lid, self.clara)


class BeobachtungenUeberDenServer(MitKollegin):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.clara = schuelerliste.speichern(self.con, self.lid, {"klasse_id": self.k24, "nachname": "Weiß", "vorname": "Clara"})
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
        status, a, _ = self.anfrage("POST", "/api/beobachtung", {"schueler_ids": [self.clara], "datum": "2026-11-20", "text": "gut mitgearbeitet",
                                                                 "tendenz": "positiv", "stunde_datum": "2026-11-20", "stunde_beginn": "07:45",
                                                                 "stunde_text": "1. Block"}, wer="rei")
        self.assertEqual(status, 200, a)
        bid = a["ids"][0]
        status, a, _ = self.anfrage("GET", "/api/beobachtungen?schueler=%d" % self.clara, wer="rei")
        self.assertEqual([e["text"] for e in a["eintraege"]], ["gut mitgearbeitet"])
        status, a, _ = self.anfrage("GET", "/api/beobachtungen?schueler=%d" % self.clara, wer="gob")
        self.assertEqual(a["eintraege"], [])                                   # privat
        status, a, _ = self.anfrage("GET", "/api/schueler?klasse=%d" % self.k24, wer="rei")
        self.assertEqual(a["beobachtungen"][str(self.clara)]["positiv"], 1)
        status, a, _ = self.anfrage("GET", "/api/beobachtungen/stunde?datum=2026-11-20&beginn=07:45", wer="rei")
        self.assertEqual(len(a["eintraege"]), 1)
        status, a, _ = self.anfrage("GET", "/api/beobachtungen?klasse=%d&tendenz=positiv" % self.k24, wer="rei")
        self.assertEqual(len(a["eintraege"]), 1)
        status, inhalt, _ = self.anfrage("GET", "/api/beobachtungen/schueler/%d.pdf" % self.clara, wer="rei", roh=True)
        self.assertEqual((status, inhalt[:4]), (200, b"%PDF"))
        status, inhalt, _ = self.anfrage("GET", "/api/beobachtungen/klasse.pdf?klasse=%d" % self.k24, wer="rei", roh=True)
        self.assertEqual((status, inhalt[:4]), (200, b"%PDF"))
        status, a, _ = self.anfrage("POST", "/api/beobachtung/%d" % bid, {"datum": "2026-11-19", "text": "x", "tendenz": "neutral"}, wer="gob")
        self.assertEqual(status, 400)                                          # nicht seins
        status, a, _ = self.anfrage("POST", "/api/beobachtung/%d/loeschen" % bid, {}, wer="rei")
        self.assertEqual(status, 200, a)
        status, a, _ = self.anfrage("GET", "/api/beobachtungen/aufraeumen", wer="rei")
        self.assertEqual(a["anzahl"], 0)
        status, a, _ = self.anfrage("POST", "/api/beobachtungen/aufraeumen", {}, wer="rei")
        self.assertEqual((status, a["geloescht"]), (200, 0))
