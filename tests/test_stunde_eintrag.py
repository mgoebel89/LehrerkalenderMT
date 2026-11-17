"""Tests fuer 0.17.0: Pruefungen unterbrechen den Unterricht (auch bei Stecknadel und fremdem Lernfeld am Block),
Unterrichtsinhalt und Notizen je gehaltener Stunde (Vorstunde, andere Gruppe, Vorschlag bei Pruefungen).
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import unittest

from app import db, planung, pruefungen, stundenplan
from test_stufe_c import MitPlanung


def bl(n, lf=None):
    return [{"datum": "2026-12-%02d" % (i + 1), "beginn": "07:45", "lernfeld_id": lf[i] if isinstance(lf, list) else lf} for i in range(n)]


def th(tid, n, lf=None, fest=None, pruefung=None):
    return {"id": tid, "bloecke": n, "lernfeld_id": lf, "ls": [], "fest_datum": fest, "fest_beginn": "07:45" if fest else None,
            "pruefung_id": pruefung}


def folge(belegung):
    return [b[0] if b else None for b in belegung]


class PruefungUnterbricht(unittest.TestCase):
    def test_thema_laeuft_nach_der_pruefung_weiter(self):
        belegung, info = planung.fliessen([th(1, 6), th(9, 1, fest="2026-12-04", pruefung=5)], bl(8))
        self.assertEqual(folge(belegung), [1, 1, 1, 9, 1, 1, 1, None])

    def test_festgesetztes_thema_verdraengt_die_pruefung_nicht(self):
        # vorher rutschte die Pruefung hinter das festgesetzte Thema (auf den 7. Block)
        belegung, info = planung.fliessen([th(1, 6, fest="2026-12-01"), th(9, 1, fest="2026-12-04", pruefung=5)], bl(8))
        self.assertEqual(folge(belegung), [1, 1, 1, 9, 1, 1, 1, None])
        self.assertEqual((info[9]["nadel"], info[1]["ueberlauf"]), ("ok", 0))
        # Stecknadel genau auf dem Pruefungsblock: das Thema beginnt danach
        belegung, _ = planung.fliessen([th(1, 2, fest="2026-12-04"), th(9, 1, fest="2026-12-04", pruefung=5)], bl(6))
        self.assertEqual(folge(belegung), [None, None, None, 9, 1, 1])

    def test_pruefung_im_block_eines_anderen_lernfelds(self):
        # LF 7 mo, LF 9 do im Wechsel; die LF-7-Arbeit liegt auf einem LF-9-Block: LF 9 laeuft danach weiter
        belegung, info = planung.fliessen([th(1, 4, lf=7), th(2, 4, lf=9), th(9, 1, lf=7, fest="2026-12-04", pruefung=5)],
                                          bl(8, [7, 9, 7, 9, 7, 9, 7, 9]))
        self.assertEqual(folge(belegung), [1, 2, 1, 9, 1, 2, 1, 2])
        self.assertEqual(info[2]["ueberlauf"], 1)

    def test_pruefung_ohne_unterricht_bleibt_leer(self):
        belegung, info = planung.fliessen([th(1, 3), th(9, 1, fest="2027-01-08", pruefung=5)], bl(4))
        self.assertEqual(folge(belegung), [1, 1, 1, None])
        self.assertEqual((info[9]["nadel"], info[9]["ueberlauf"]), ("fehlt", 0))

    def test_mehrere_bloecke_nur_am_pruefungstag(self):
        bloecke = [dict(b, beginn=z) for b in bl(2) for z in ("07:45", "09:30")]
        belegung, info = planung.fliessen([th(1, 3), th(9, 3, fest="2026-12-01", pruefung=5)], bloecke)
        self.assertEqual(folge(belegung), [9, 9, 1, 1])
        self.assertEqual(info[9]["ueberlauf"], 1)                  # am Tag gibt es nur 2 Bloecke


class PruefungInDerPlanung(MitPlanung):
    def test_festgesetztes_thema_und_klassenarbeit(self):
        tid = planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=4))
        planung.festsetzen(self.con, self.lid, tid, "2026-11-16", "07:45")
        pid = pruefungen.pruefung_speichern(self.con, self.lid, self.strang(
            titel="Klassenarbeit", form="termin", datum="2026-11-20", beginn="07:45", bloecke=1, erfassung="gesamt", max_punkte=50))
        p = self.plan()
        ka = next(t for t in p["themen"] if t["pruefung_id"] == pid)
        sps = next(t for t in p["themen"] if t["titel"] == "SPS")
        self.assertEqual((ka["von"], ka["nadel"]), ("2026-11-20", "ok"))
        self.assertEqual((sps["von"], sps["bis"], sps["ueberlauf"]), ("2026-11-16", "2026-12-04", 0))
        s = planung.stunde(self.con, self.lid, "2026-11-20", "07:45", jetzt="2026-11-25T12:00:00")
        self.assertEqual((s["thema"]["pruefung"], s["vorschlag"], s["eintrag"]["inhalt"]), (True, "Prüfung: Klassenarbeit", ""))
        s = planung.stunde(self.con, self.lid, "2026-11-23", "07:45", jetzt="2026-11-25T12:00:00")
        self.assertEqual((s["thema"]["titel"], s["thema"]["teil"], s["vorschlag"]), ("SPS", 2, ""))


class Eintrag(MitPlanung):
    def setUp(self):
        super().setUp()
        planung.thema_speichern(self.con, self.lid, self.strang(titel="SPS", bloecke=3))

    def stunde(self, datum, beginn="07:45"):
        return planung.stunde(self.con, self.lid, datum, beginn, jetzt="2026-11-25T12:00:00")

    def setzen(self, datum, beginn="07:45", **daten):
        with db.transaktion(self.con):
            planung.eintrag_setzen(self.con, self.lid, datum, beginn, daten)

    def test_inhalt_notizen_und_vorstunde(self):
        s = self.stunde("2026-11-16")
        self.assertEqual((s["eintrag"]["inhalt"], s["eintrag"]["notizen"], s["vorstunde"]), ("", "", None))
        self.setzen("2026-11-16", inhalt="  SPS: Grundlagen, Aufbau S7-1200 \r\n", notizen="Laptops mitbringen")
        e = self.stunde("2026-11-16")["eintrag"]
        self.assertEqual((e["inhalt"], e["notizen"]), ("SPS: Grundlagen, Aufbau S7-1200", "Laptops mitbringen"))
        v = self.stunde("2026-11-20")["vorstunde"]
        self.assertEqual((v["datum"], v["inhalt"], v["notizen"]), ("2026-11-16", "SPS: Grundlagen, Aufbau S7-1200", "Laptops mitbringen"))
        # nur ein Feld: das andere bleibt
        self.setzen("2026-11-16", notizen="")
        self.assertEqual(self.stunde("2026-11-16")["eintrag"]["inhalt"], "SPS: Grundlagen, Aufbau S7-1200")
        # die Vorstunde ist die letzte Stunde MIT Eintrag
        self.assertEqual(self.stunde("2026-11-23")["vorstunde"]["datum"], "2026-11-16")
        # beide leer: Eintrag weg
        self.setzen("2026-11-16", inhalt="")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM stunde_eintrag").fetchone()[0], 0)
        self.assertIsNone(self.stunde("2026-11-20")["vorstunde"])

    def test_fehler(self):
        with self.assertRaises(planung.PlanungFehler):              # keine Stunde
            self.setzen("2026-11-17", inhalt="x")
        with self.assertRaises(planung.PlanungFehler):              # zu lang
            self.setzen("2026-11-16", inhalt="x" * (planung.INHALT_MAX + 1))
        with self.assertRaises(planung.PlanungFehler):
            self.setzen("2026-11-16", notizen=["kein Text"])
        with self.assertRaises(planung.PlanungFehler):
            self.setzen("kein-datum", inhalt="x")
        # Inhalt auch ohne Schuljahr bzw. ohne Thema moeglich (Stunde ausserhalb des Schuljahrs)
        self.setzen("2026-12-14", inhalt="Wiederholung")
        self.assertEqual(self.stunde("2026-12-14")["eintrag"]["inhalt"], "Wiederholung")

    def test_gruppen(self):
        g1 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 1"})
        g2 = stundenplan.gruppe_speichern(self.con, self.lid, {"klasse_id": self.k24, "name": "Gr. 2"})
        for beginn, ende, g in (("07:45", "09:15", g1), ("09:30", "11:00", g2)):
            stundenplan.feld_setzen(self.con, self.lid, self.v, {"wochentag": 3, "beginn": beginn, "ende": ende,
                                                                 "eintraege": [{"klasse_id": self.k24, "gruppe_id": g}]})
        self.setzen("2026-11-16", inhalt="ganze Klasse")
        self.setzen("2026-11-18", "07:45", inhalt="G1: Verdrahtung", notizen="nur G1")
        s = self.stunde("2026-11-18", "09:30")
        self.assertEqual(s["andere_gruppe"], [{"gruppe": "Gr. 1", "beginn": "07:45", "inhalt": "G1: Verdrahtung"}])
        self.assertEqual((s["vorstunde"]["datum"], s["vorstunde"]["inhalt"]), ("2026-11-16", "ganze Klasse"))   # nicht G1
        self.setzen("2026-11-18", "09:30", inhalt="G2: Verdrahtung")
        self.assertEqual(self.stunde("2026-11-18", "09:30")["eintrag"]["inhalt"], "G2: Verdrahtung")
        self.assertEqual(self.stunde("2026-11-18")["eintrag"]["inhalt"], "G1: Verdrahtung")       # je Gruppe eigener Text
        # ganze Klasse danach: Vorstunde ist die letzte Gruppenstunde mit Eintrag
        self.assertEqual(self.stunde("2026-11-20")["vorstunde"]["beginn"], "09:30")
        self.assertEqual(self.stunde("2026-11-20")["andere_gruppe"], [])


if __name__ == "__main__":
    unittest.main()
