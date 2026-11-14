"""Tests fuer Stufe A: Datenbank, Konten mit Einladung und zweitem Faktor, Grunddaten, Notenschluessel, Webserver.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import ast
import http.client
import json
import pathlib
import shutil
import tempfile
import threading
import unittest

from app import db, grunddaten, konten, notenschluessel, server, totp

REPO = pathlib.Path(__file__).resolve().parent.parent


class Python311(unittest.TestCase):
    """Der Container hat Python 3.12, das Repo soll aber auch mit 3.11 laufen (Debian 12)."""

    def test_syntax(self):
        for datei in REPO.rglob("*.py"):
            if ".dev-daten" in datei.parts:
                continue
            with self.subTest(datei=str(datei.relative_to(REPO))):
                ast.parse(datei.read_text(encoding="utf-8"), feature_version=(3, 11))


class MitDatenbank(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def konto(self, kuerzel="gob", rolle="admin"):
        with db.transaktion(self.con):
            return konten.anlegen(self.con, kuerzel, "Konto " + kuerzel.upper(), rolle, "geheim123", vorlaeufig=False)


class Totp(unittest.TestCase):
    # Pruefwert aus RFC 6238, Anhang B (SHA-1, Zeit 59 s): 94287082 -> die letzten 6 Stellen
    GEHEIM = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # base32("12345678901234567890")

    def test_rfc_pruefwert(self):
        self.assertEqual(totp.code(self.GEHEIM, 59 // 30), "287082")
        self.assertEqual(totp.code(self.GEHEIM, 1111111109 // 30), "081804")

    def test_fenster_und_keine_wiederholung(self):
        z = totp.pruefen(self.GEHEIM, "287082", 0, uhr=59)
        self.assertEqual(z, 1)
        self.assertEqual(totp.pruefen(self.GEHEIM, "287082", 0, uhr=59 + 30), 1)   # ein Schritt spaeter gilt noch
        self.assertIsNone(totp.pruefen(self.GEHEIM, "287082", 1, uhr=59))           # schon benutzt
        self.assertIsNone(totp.pruefen(self.GEHEIM, "000000", 0, uhr=59))

    def test_ersatzcodes_nur_einmal(self):
        klar, summen = totp.ersatzcodes_neu()
        self.assertEqual(len(klar), 10)
        rest = totp.ersatzcode_einloesen(summen, klar[3].lower())
        self.assertEqual(len(rest), 9)
        self.assertIsNone(totp.ersatzcode_einloesen(rest, klar[3]))


class Konten(MitDatenbank):
    def test_anmelden_ohne_zweiten_faktor(self):
        k = self.konto()
        wert, konto, zwischen = konten.anmelden(self.con, "GOB", "geheim123")
        self.assertIsNone(zwischen)
        self.assertEqual(konten.sitzung_pruefen(self.con, wert)["id"], k["id"])
        with self.assertRaises(konten.KontoFehler):
            konten.anmelden(self.con, "gob", "falsch123")

    def test_zweiter_faktor_ablauf(self):
        k = self.konto()
        geheim = Totp.GEHEIM
        with db.transaktion(self.con):
            codes = konten.totp_einschalten(self.con, k["id"], geheim, totp.code(geheim, 100), uhr=100 * 30)
        self.assertEqual(len(codes), 10)
        wert, _konto, zwischen = konten.anmelden(self.con, "gob", "geheim123", uhr=101 * 30)
        self.assertIsNone(wert)
        self.assertIsNone(konten.sitzung_pruefen(self.con, zwischen))   # der Zwischenschein ist keine Anmeldung
        with self.assertRaises(konten.KontoFehler):
            konten.zweiter_schritt(self.con, zwischen, "000000", uhr=101 * 30)
        with self.assertRaises(konten.KontoFehler):   # der Code vom Einschalten gilt nicht noch einmal
            konten.zweiter_schritt(self.con, zwischen, totp.code(geheim, 100), uhr=101 * 30)
        wert, konto = konten.zweiter_schritt(self.con, zwischen, totp.code(geheim, 101), uhr=101 * 30)
        self.assertTrue(konto["zweiter_faktor"])
        self.assertIsNotNone(konten.sitzung_pruefen(self.con, wert, uhr=101 * 30))
        # Ersatzcode statt App, nur einmal
        _w, _k, zwischen = konten.anmelden(self.con, "gob", "geheim123", uhr=102 * 30)
        _w, konto = konten.zweiter_schritt(self.con, zwischen, codes[0], uhr=102 * 30)
        self.assertEqual(konto["ersatzcodes_uebrig"], 9)
        with self.assertRaises(konten.KontoFehler):
            konten.zweiter_schritt(self.con, zwischen, codes[0], uhr=102 * 30)

    def test_zwischenschein_laeuft_ab(self):
        k = self.konto()
        with db.transaktion(self.con):
            konten.totp_einschalten(self.con, k["id"], Totp.GEHEIM, totp.code(Totp.GEHEIM, 10), uhr=300)
        _w, _k, zwischen = konten.anmelden(self.con, "gob", "geheim123", uhr=400)
        later = 400 + konten.ZWISCHEN_S + 1
        with self.assertRaises(konten.KontoFehler):
            konten.zweiter_schritt(self.con, zwischen, totp.code(Totp.GEHEIM, later // 30), uhr=later)

    def test_einladung(self):
        adm = self.konto("adm", "admin")
        with db.transaktion(self.con):
            e = konten.einladung_anlegen(self.con, "lehrkraft", 14, "Kollege R.", adm["id"])
        self.assertRegex(e["code"], r"KAL-[0-9A-F]{4}-[0-9A-F]{4}")
        self.assertEqual(e["stand"], "offen")
        with db.transaktion(self.con):
            neu = konten.einladung_einloesen(self.con, e["code"][4:].lower(), "rei", "Kollege Reiter", "geheim123")
        self.assertEqual(neu["rolle"], "lehrkraft")
        self.assertFalse(neu["pw_vorlaeufig"])
        with self.assertRaises(konten.KontoFehler):
            konten.einladung_einloesen(self.con, e["code"], "rei2", "Noch einer", "geheim123")
        self.assertEqual(konten.einladungen(self.con)[0]["stand"], "eingeloest")
        with self.assertRaises(konten.KontoFehler):
            konten.einladung_anlegen(self.con, "lehrkraft", 99, "", adm["id"])

    def test_einladung_abgelaufen(self):
        adm = self.konto("adm", "admin")
        with db.transaktion(self.con):
            e = konten.einladung_anlegen(self.con, "lehrkraft", 1, "", adm["id"])
            self.con.execute("UPDATE einladung SET gueltig_bis = '2020-01-01' WHERE id = ?", (e["id"],))
        with self.assertRaises(konten.KontoFehler):
            konten.einladung_einloesen(self.con, e["code"], "neu", "Neu Konto", "geheim123")


class Grunddaten(MitDatenbank):
    def bildungsgang(self, name="Mechatroniker/in", einheit="lernfeld"):
        with db.transaktion(self.con):
            return grunddaten.bildungsgang_speichern(self.con, {"name": name, "kuerzel": "BSMT", "einheit": einheit})

    def test_bildungsgang_stufen_lernfelder(self):
        bid = self.bildungsgang()
        with db.transaktion(self.con):
            fs1 = grunddaten.stufe_speichern(self.con, {"bildungsgang_id": bid, "name": "Fachstufe I"})
            grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": bid, "nummer": "LF 7", "name": "Steuerungen",
                                                     "stufe_id": fs1, "stunden": 80})
        with self.assertRaises(grunddaten.GrunddatenFehler):   # doppelte Nummer
            grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": bid, "nummer": "LF 7", "name": "Nochmal"})
        b = grunddaten.alles(self.con)["bildungsgaenge"][0]
        self.assertEqual([s["name"] for s in b["stufen"]], ["Fachstufe I"])
        self.assertEqual(b["lernfelder"][0]["stunden"], 80)

    def test_modul_mit_anteilen(self):
        bid = self.bildungsgang("Fachschule Technik", "modul")
        with db.transaktion(self.con):
            s1 = grunddaten.stufe_speichern(self.con, {"bildungsgang_id": bid, "name": "1. Semester"})
            s2 = grunddaten.stufe_speichern(self.con, {"bildungsgang_id": bid, "name": "2. Semester"})
            grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": bid, "nummer": "M 4", "name": "Automatisierung",
                                                     "stufe_id": s1, "stunden": 120, "anteile": {str(s1): 80, str(s2): 40}})
        lf = grunddaten.alles(self.con)["bildungsgaenge"][0]["lernfelder"][0]
        self.assertEqual(lf["anteile"], {str(s1): 80, str(s2): 40})

    def test_stufe_aus_anderem_bildungsgang_abgelehnt(self):
        a, b = self.bildungsgang("A"), self.bildungsgang("B")
        with db.transaktion(self.con):
            fremd = grunddaten.stufe_speichern(self.con, {"bildungsgang_id": b, "name": "X"})
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.lernfeld_speichern(self.con, {"bildungsgang_id": a, "nummer": "LF 1", "name": "Y", "stufe_id": fremd})

    def test_zeitraster_schule_und_eigenes(self):
        bid = self.bildungsgang("Fachschule Technik", "modul")
        with db.transaktion(self.con):
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "2. Block", "beginn": "09:30", "ende": "11:00"},
                                                             {"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"}])
        self.assertEqual([z["bezeichnung"] for z in grunddaten.zeitraster(self.con, bid)], ["1. Block", "2. Block"])  # erbt Schule
        with db.transaktion(self.con):
            grunddaten.zeitraster_speichern(self.con, bid, [{"bezeichnung": "FS 1", "beginn": "17:15", "ende": "18:45"}])
        self.assertEqual([z["bezeichnung"] for z in grunddaten.zeitraster(self.con, bid)], ["FS 1"])
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "A", "beginn": "08:00", "ende": "09:30"},
                                                             {"bezeichnung": "B", "beginn": "09:00", "ende": "10:00"}])
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.zeitraster_speichern(self.con, None, [{"bezeichnung": "A", "beginn": "9:00", "ende": "10:00"}])

    def test_klasse_und_loeschschutz(self):
        bid = self.bildungsgang()
        with db.transaktion(self.con):
            grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": bid})
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.klasse_speichern(self.con, {"name": "BSMT 24a", "bildungsgang_id": bid})
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.bildungsgang_loeschen(self.con, bid)

    def test_ferien(self):
        with db.transaktion(self.con):
            grunddaten.ferien_anlegen(self.con, {"name": "Weihnachtsferien", "von": "2026-12-23", "bis": "2027-01-08"})
        with self.assertRaises(grunddaten.GrunddatenFehler):
            grunddaten.ferien_anlegen(self.con, {"name": "Falsch", "von": "2026-12-23", "bis": "2026-12-01"})
        self.assertEqual(len(grunddaten.ferien(self.con)), 1)


class Notenschluessel(MitDatenbank):
    def test_vorgabe_ist_gueltig_und_rechnet_wie_die_voransicht(self):
        for system in notenschluessel.SYSTEME:
            notenschluessel.grenzen_pruefen(system, notenschluessel.vorgabe(system))
        t, z, p = (notenschluessel.vorgabe(s) for s in ("tendenz", "zehntel", "punkte"))
        self.assertEqual(notenschluessel.note("tendenz", t, 87)["text"], "2+")
        self.assertEqual(notenschluessel.note("tendenz", t, 87)["dezimal"], 1.7)
        self.assertEqual(notenschluessel.note("tendenz", t, 69)["text"], "3")
        self.assertEqual(notenschluessel.note("tendenz", t, 66.1)["text"], "3−")
        self.assertEqual(notenschluessel.note("zehntel", z, 87)["text"], "1,5")
        self.assertEqual(notenschluessel.note("zehntel", z, 76)["text"], "2,4")
        self.assertEqual(notenschluessel.note("zehntel", z, 69)["text"], "3,0")
        self.assertEqual(notenschluessel.note("zehntel", z, 100)["text"], "1,0")
        self.assertEqual(notenschluessel.note("zehntel", z, 0)["text"], "6,0")
        self.assertEqual(notenschluessel.note("punkte", p, 87)["text"], "13 P")
        self.assertEqual(notenschluessel.note("punkte", p, 69)["text"], "9 P")

    def test_grenzen_pruefen(self):
        g = notenschluessel.vorgabe("zehntel")
        g["3"] = 80   # nicht mehr absteigend
        with self.assertRaises(notenschluessel.SchluesselFehler):
            notenschluessel.grenzen_pruefen("zehntel", g)
        g = notenschluessel.vorgabe("zehntel")
        g["6"] = 5    # Luecke unten
        with self.assertRaises(notenschluessel.SchluesselFehler):
            notenschluessel.grenzen_pruefen("zehntel", g)

    def test_konferenzschluessel_nur_admin_und_einer_je_bildungsgang(self):
        adm, lk = self.konto("adm", "admin"), self.konto("lk", "lehrkraft")
        with db.transaktion(self.con):
            bid = grunddaten.bildungsgang_speichern(self.con, {"name": "Mechatroniker/in"})
            sid = notenschluessel.speichern(self.con, adm, {"name": "Konferenz BS", "art": "konferenz", "bildungsgang_id": bid,
                                                            "system": "tendenz"})
        with self.assertRaises(notenschluessel.SchluesselFehler):
            notenschluessel.speichern(self.con, adm, {"name": "Zweiter", "art": "konferenz", "bildungsgang_id": bid, "system": "zehntel"})
        with self.assertRaises(notenschluessel.SchluesselFehler):
            notenschluessel.speichern(self.con, lk, {"name": "Geaendert"}, sid)
        with db.transaktion(self.con):
            kopie = notenschluessel.kopieren(self.con, lk, sid)
        self.assertEqual(notenschluessel.holen(self.con, kopie)["art"], "eigen")
        self.assertEqual({s["id"] for s in notenschluessel.liste(self.con, lk)}, {sid, kopie})
        self.assertEqual({s["id"] for s in notenschluessel.liste(self.con, adm)}, {sid})   # eigene sieht nur der Besitzer


class Webserver(unittest.TestCase):
    """Echter Server auf zufaelligem Port (wie HTTPS, hier ohne TLS) und der Umleit-Port."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        db.oeffnen(self.ordner).close()
        pfad = db.pfad(self.ordner)
        self.server = server.HTTPServer(("127.0.0.1", 0), server.Handler, pfad)
        self.umleitung = server.HTTPServer(("127.0.0.1", 0), server.UmleitHandler, pfad)
        for s in (self.server, self.umleitung):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.cookie = None
        server.SPERRE.rechner.clear()

    def tearDown(self):
        for s in (self.server, self.umleitung):
            s.shutdown()
            s.server_close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def anfrage(self, methode, pfad, daten=None, port=None, kopf=True):
        c = http.client.HTTPConnection("127.0.0.1", port or self.server.server_address[1], timeout=10)
        koepfe = {"Content-Type": "application/json"}
        if kopf:
            koepfe["X-Lehrerkalender"] = "1"
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

    def test_ablauf_admin(self):
        self.assertEqual(self.anfrage("GET", "/api/status")[1]["eingerichtet"], False)
        self.einrichten()
        self.assertEqual(self.anfrage("POST", "/api/admin/bildungsgang", {"name": "X"}, kopf=False)[0], 403)   # ohne Schutzkopf
        status, g = self.anfrage("POST", "/api/admin/bildungsgang", {"name": "Mechatroniker/in", "kuerzel": "BSMT"})
        self.assertEqual(status, 200)
        bid = g["bildungsgaenge"][0]["id"]
        status, g = self.anfrage("POST", "/api/admin/zeitraster", {"bildungsgang_id": None,
                                                                   "bloecke": [{"bezeichnung": "1. Block", "beginn": "07:45", "ende": "09:15"}]})
        self.assertEqual(g["zeitraster_schule"][0]["beginn"], "07:45")
        status, g = self.anfrage("POST", "/api/admin/klasse", {"name": "BSMT 24a", "bildungsgang_id": bid})
        self.assertEqual(g["klassen"][0]["name"], "BSMT 24a")
        status, r = self.anfrage("POST", "/api/notenschluessel", {"name": "Konferenz BS", "art": "konferenz", "bildungsgang_id": bid,
                                                                  "system": "tendenz", "grenzen": notenschluessel.vorgabe("tendenz")})
        self.assertEqual(status, 200)
        status, r = self.anfrage("POST", "/api/notenschluessel/probe", {"system": "tendenz", "grenzen": notenschluessel.vorgabe("tendenz")})
        self.assertEqual(r["noten"]["87"], "2+")
        status, p = self.anfrage("GET", "/api/admin/protokoll")
        self.assertIn("klasse_angelegt", [z["art"] for z in p["protokoll"]])

    def test_einladung_und_rechte(self):
        self.einrichten()
        status, r = self.anfrage("POST", "/api/admin/einladungen", {"rolle": "lehrkraft", "tage": 7, "notiz": "Kollege"})
        code = r["einladung"]["code"]
        self.cookie = None
        self.assertEqual(self.anfrage("POST", "/api/einladung/pruefen", {"code": code})[0], 200)
        status, r = self.anfrage("POST", "/api/einladung/einloesen", {"code": code, "kuerzel": "rei", "name": "Kollege Reiter",
                                                                       "passwort": "geheim123"})
        self.assertEqual(status, 200)
        self.assertEqual(self.anfrage("GET", "/api/ich")[1]["konto"]["kuerzel"], "rei")
        self.assertEqual(self.anfrage("GET", "/api/grunddaten")[0], 200)              # lesen darf jede Lehrkraft
        self.assertEqual(self.anfrage("GET", "/api/admin/konten")[0], 403)            # Admin-Bereich nicht
        self.assertEqual(self.anfrage("POST", "/api/admin/bildungsgang", {"name": "Y"})[0], 403)

    def test_zweiter_faktor_ueber_server(self):
        self.einrichten()
        status, start = self.anfrage("POST", "/api/zweiter-faktor/beginnen", {})
        self.assertTrue(start["qr"].startswith("<svg"))
        code = totp.code(start["geheimnis"], totp.zaehler_jetzt())
        status, r = self.anfrage("POST", "/api/zweiter-faktor/einschalten", {"geheimnis": start["geheimnis"], "code": code})
        self.assertEqual(status, 200)
        self.anfrage("POST", "/api/abmelden", {})
        self.cookie = None
        status, r = self.anfrage("POST", "/api/anmelden", {"kuerzel": "gob", "passwort": "geheim123"})
        self.assertTrue(r["zweiter_faktor"])
        self.assertIsNone(self.cookie)
        self.assertEqual(self.anfrage("GET", "/api/ich")[0], 401)
        status, r = self.anfrage("POST", "/api/anmelden/code", {"zwischen": r["zwischen"], "code": r and "12345"})
        self.assertEqual(status, 400)

    def test_umleitung_und_seiten(self):
        status, _ = self.anfrage("GET", "/app", port=self.umleitung.server_address[1])
        self.assertEqual(status, 301)
        self.assertEqual(self.anfrage("POST", "/api/anmelden", {}, port=self.umleitung.server_address[1])[0], 403)
        for seite in ("/anmelden", "/einladung", "/einrichtung", "/app", "/static/app.js", "/static/admin.js", "/static/kalender.css"):
            with self.subTest(seite=seite):
                self.assertEqual(self.anfrage("GET", seite)[0], 200)


if __name__ == "__main__":
    unittest.main()
