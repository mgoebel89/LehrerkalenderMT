"""Tests fuer Stufe E: Teilen im Kollegium (app/kollegium.py). Geteilt wird nur zwischen Lehrkraeften derselben Klasse,
nur wenn der Admin es eingeschaltet hat; Termine nur ausdruecklich, die Planung nur zum Lesen.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import datetime
import json
import threading
import http.client

from app import db, grunddaten, kollegium, planung, server, stundenplan
from test_stufe_c import MitPlanung

MONTAG = datetime.date(2026, 11, 16)


class MitKollegin(MitPlanung):
    """gob unterrichtet BSMT 24a (Mo, Fr) und 25a (Di), Kollege Reiter (rei) nur 24a (Mi)."""

    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.k25 = grunddaten.klasse_speichern(self.con, {"name": "BSMT 25a", "bildungsgang_id": self.bs})
            stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 2, "beginn": "07:45", "ende": "09:15",
                                                                 "eintraege": [{"klasse_id": self.k25}]})
            self.vr = stundenplan.version_anlegen(self.con, self.rid, {"ab": "2026-08-01"})
            stundenplan.feld_setzen(self.con, self.rid, self.vr, {"wochentag": 3, "beginn": "07:45", "ende": "09:15",
                                                                  "eintraege": [{"klasse_id": self.k24}]})

    @property
    def rid(self):
        return self.r["id"]

    def termin(self, lid, **mehr):
        with db.transaktion(self.con):
            return stundenplan.termin_speichern(self.con, lid, dict({"art": "dienst", "titel": "Klassenfahrt", "datum": "2026-11-18"}, **mehr))

    def fremde_termine(self, lid):
        return [t for t in stundenplan.woche(self.con, lid, MONTAG)["termine"] if t.get("fremd")]


class Kollegium(MitKollegin):
    def test_wer_unterrichtet_was(self):
        self.assertEqual(kollegium.klassen_von(self.con, self.lid), {self.k24, self.k25})
        self.assertEqual(kollegium.klassen_von(self.con, self.rid), {self.k24})
        self.assertEqual([l["kuerzel"] for l in kollegium.lehrkraefte_der_klasse(self.con, self.k24)], ["rei", "gob"])
        # eine abgelaufene Version zaehlt nicht mehr
        self.assertEqual(kollegium.klassen_von(self.con, self.rid, heute=datetime.date(2025, 1, 1)), {self.k24})
        with db.transaktion(self.con):
            stundenplan.version_anlegen(self.con, self.rid, {"ab": "2026-09-01"})   # neue, leere Version
        self.assertEqual(kollegium.klassen_von(self.con, self.rid, heute=datetime.date(2026, 10, 1)), set())
        self.assertEqual(kollegium.klassen_von(self.con, self.rid, heute=datetime.date(2026, 8, 15)), {self.k24})

    def test_ohne_freigabe_sieht_niemand_etwas(self):
        self.termin(self.lid, klasse_id=self.k24, geteilt=True)
        self.assertEqual(self.fremde_termine(self.rid), [])
        self.assertEqual(stundenplan.woche(self.con, self.rid, MONTAG)["teilen_klassen"], [])
        self.assertIsNone(kollegium.klasse_uebersicht(self.con, self.rid, self.k24))
        with self.assertRaises(kollegium.KollegiumFehler):
            kollegium.kollege(self.con, self.rid, self.lid, self.k24)

    def test_geteilte_termine(self):
        with db.transaktion(self.con):
            kollegium.setzen(self.con, True)
        geteilt = self.termin(self.lid, klasse_id=self.k24, geteilt=True, notiz="Bus um 7 Uhr")
        self.termin(self.lid, titel="nur meins", klasse_id=self.k24)                          # nicht geteilt
        self.termin(self.lid, titel="andere Klasse", klasse_id=self.k25, geteilt=True)       # rei unterrichtet 25a nicht
        self.termin(self.lid, art="privat", titel="Zahnarzt", geteilt=True, klasse_id=self.k24)   # privat: nie geteilt
        fremd = self.fremde_termine(self.rid)
        self.assertEqual([(t["id"], t["titel"], t["klasse"], t["von_kuerzel"], t["notiz"]) for t in fremd],
                         [(geteilt, "Klassenfahrt", "BSMT 24a", "gob", "Bus um 7 Uhr")])
        self.assertEqual(self.fremde_termine(self.lid), [])                                  # eigene sind nicht "fremd"
        eigene = {t["titel"]: t for t in stundenplan.woche(self.con, self.lid, MONTAG)["termine"]}
        self.assertTrue(eigene["Klassenfahrt"]["geteilt"])
        self.assertFalse(eigene["nur meins"]["geteilt"])
        self.assertEqual((eigene["Zahnarzt"]["geteilt"], eigene["Zahnarzt"]["klasse_id"]), (False, None))
        # nur die Lehrkraft, die ihn eingetragen hat, kann ihn aendern oder loeschen
        with self.assertRaises(stundenplan.StundenplanFehler):
            stundenplan.termin_speichern(self.con, self.rid, {"art": "dienst", "titel": "x", "datum": "2026-11-18"}, geteilt)
        with self.assertRaises(stundenplan.StundenplanFehler):
            stundenplan.termin_loeschen(self.con, self.rid, geteilt)
        # teilen nur fuer eigene Klassen und nur mit Klasse
        with self.assertRaises(stundenplan.StundenplanFehler):
            self.termin(self.rid, klasse_id=self.k25, geteilt=True)
        with self.assertRaises(stundenplan.StundenplanFehler):
            self.termin(self.rid, geteilt=True)
        # die Kollegin sieht ihn auch in der Stunde (Termine des Tages)
        s = planung.stunde(self.con, self.rid, "2026-11-18", "07:45", jetzt="2026-11-18T08:00:00")
        self.assertEqual([t["titel"] for t in s["termine"]], ["Klassenfahrt"])
        # Admin schaltet wieder aus: weg
        with db.transaktion(self.con):
            kollegium.setzen(self.con, False)
        self.assertEqual(self.fremde_termine(self.rid), [])

    def test_klassenansicht_und_planung_lesen(self):
        with db.transaktion(self.con):
            kollegium.setzen(self.con, True)
            planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=3))
        self.termin(self.rid, klasse_id=self.k24, geteilt=True, titel="Elternabend", datum=db.heute().isoformat())
        u = kollegium.klasse_uebersicht(self.con, self.lid, self.k24)
        self.assertEqual([(l["kuerzel"], l["ich"]) for l in u["lehrkraefte"]], [("rei", False), ("gob", True)])
        self.assertEqual([(t["titel"], t["fremd"]) for t in u["termine"]], [("Elternabend", True)])
        self.assertIsNone(kollegium.klasse_uebersicht(self.con, self.rid, self.k25))     # rei hat 25a nicht
        self.assertEqual(kollegium.kollege(self.con, self.rid, self.lid, self.k24)["kuerzel"], "gob")
        for andere, kid in ((self.lid, self.k25), (self.rid, self.k24), (999, self.k24), (self.lid, None)):
            with self.assertRaises(kollegium.KollegiumFehler):
                kollegium.kollege(self.con, self.rid, andere, kid)
        self.assertEqual(kollegium.gemeinsame_klassen(self.con, self.rid, self.lid), {self.k24})
        stand = kollegium.admin_stand(self.con)
        self.assertEqual((stand["an"], stand["klassen"]), (True, [{"klasse": "BSMT 24a", "lehrkraefte": ["Kollege Reiter", "Matthias Göbel"]}]))


class KollegiumUeberDenServer(MitKollegin):
    """Planung lesen ueber /api/planung?lehrkraft=..: nur die gemeinsamen Klassen, sonst Fehler; Admin-Schalter."""

    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=3))
            planung.thema_speichern(self.con, self.lid, dict(self.strang(titel="Geheim 25a", bloecke=2), klasse_id=self.k25))
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

    def test_planung_lesen(self):
        url = "/api/planung?schuljahr=%d&klasse=%d&lehrkraft=%d" % (self.sj, self.k24, self.lid)
        status, a, _ = self.anfrage("GET", url, wer="rei")
        self.assertEqual(status, 400)                                       # noch nicht freigegeben
        status, a, _ = self.anfrage("POST", "/api/admin/kollegium", {"an": True}, wer="rei")
        self.assertEqual(status, 403)                                       # nur der Admin
        status, a, _ = self.anfrage("POST", "/api/admin/kollegium", {"an": True}, wer="gob")
        self.assertEqual((status, a["an"]), (200, True))
        status, a, _ = self.anfrage("GET", url, wer="rei")
        self.assertEqual(status, 200, a)
        self.assertEqual(a["lesend"]["kuerzel"], "gob")
        self.assertEqual([s["klasse"] for s in a["straenge"]], ["BSMT 24a"])   # 25a nicht, die hat rei nicht
        self.assertEqual([t["titel"] for t in a["plan"]["themen"]], ["SPS"])
        self.assertIsNone(a["kollegium"])
        status, a, _ = self.anfrage("GET", "/api/planung?schuljahr=%d&klasse=%d&lehrkraft=%d" % (self.sj, self.k25, self.lid), wer="rei")
        self.assertEqual(status, 400)
        # eigene Planung: die Klassenansicht nennt die Kollegin
        status, a, _ = self.anfrage("GET", "/api/planung?schuljahr=%d&klasse=%d" % (self.sj, self.k24), wer="rei")
        self.assertEqual([l["kuerzel"] for l in a["kollegium"]["lehrkraefte"]], ["rei", "gob"])
        self.assertIsNone(a["lesend"])
        # Termin teilen ueber die API
        status, a, _ = self.anfrage("POST", "/api/termin", {"art": "dienst", "titel": "Praktikum", "datum": "2026-11-17",
                                                            "klasse_id": self.k24, "geteilt": True}, wer="rei")
        self.assertEqual(status, 200, a)
        status, w, _ = self.anfrage("GET", "/api/woche?montag=2026-11-16", wer="gob")
        self.assertEqual([(t["titel"], t["von_kuerzel"]) for t in w["termine"] if t.get("fremd")], [("Praktikum", "rei")])
        self.assertEqual([k["name"] for k in w["teilen_klassen"]], ["BSMT 24a", "BSMT 25a"])
