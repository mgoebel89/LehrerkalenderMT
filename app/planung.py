"""Unterrichtsplanung (Stufe C1): Bibliothek, Themenfolge je Strang und das Fliessen der Themen auf die Bloecke.

Begriffe
  Bibliothek   Themen je Lernfeld bzw. Modul mit Umfang in Bloecken (Doppelstunden), darin Lernsituationen (LS). Fuer alle
               im Bildungsgang sichtbar; aendern darf, wer den Baustein angelegt hat (und der Admin).
  Strang       Was eine Lehrkraft in einer Klasse plant: Klasse + Gruppe (oder ganze Klasse) in einem Schuljahr. Eine
               geteilte Klasse hat so bis zu drei Straenge (ganze Klasse, Gr. 1, Gr. 2).
  Thema        Ein Eintrag der Themenfolge eines Strangs (meist aus der Bibliothek kopiert). Sein Umfang ist das Budget;
               die Lernsituationen darin fuellen es nach und nach, der Rest fliesst als "noch offen" mit. Brauchen die LS
               mehr, waechst das Thema.
  Spur         Bloecke im Stundenplan koennen optional einem Lernfeld zugeordnet sein (parallele Lernfelder, z. B.
               montags LF 7, donnerstags LF 9). Themen dieses Lernfelds fliessen nur in diese Bloecke; alle anderen
               Themen fliessen in Reihenfolge in die Bloecke ohne Lernfeld.

Fliessen: Die Bloecke eines Strangs sind die regulaeren Stunden laut Stundenplan im Schuljahr (ohne Ferien, Feiertage,
Ausfaelle, Stunden mit Vertretung und weggeschobene), dazu Zusatzstunden und hierher verschobene Stunden. Pruefungen mit
festem Termin belegen ihren Block als Erstes (gleich welches Lernfeld er hat) und unterbrechen damit den Unterricht.
Danach belegen festgesetzte Themen (Stecknadel) ihre Bloecke ab dem festgesetzten Block, die uebrigen fuellen in
Listenreihenfolge die freien Bloecke. Was nicht mehr passt, ist Ueberlauf (rot in der Planung).

Unterrichtsinhalt und Notizen: je gehaltener Stunde (Tabelle stunde_eintrag), nicht je Planungsblock. Der Inhalt ist der
Text fuer das Klassenbuch in WebUntis; Thema und Lernsituation dienen nur der Planung.
"""
import datetime

from . import db, grunddaten, stundenplan

natuerlich = grunddaten.natuerlich


class PlanungFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _text(wert, feld, max_len=200, pflicht=True):
    wert = wert.strip() if isinstance(wert, str) else ""
    if pflicht and not wert:
        raise PlanungFehler("Bitte %s angeben." % feld)
    if len(wert) > max_len:
        raise PlanungFehler("%s darf höchstens %d Zeichen haben." % (feld[0].upper() + feld[1:], max_len))
    return wert


def _id(wert):
    if wert in (None, "", 0, "0"):
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise PlanungFehler("Ungültige Auswahl.")


def _bloecke(wert, minimum=1):
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        raise PlanungFehler("Bitte den Umfang als ganze Zahl von Blöcken angeben.")
    if not minimum <= zahl <= 400:
        raise PlanungFehler("Der Umfang muss zwischen %d und 400 Blöcken liegen." % minimum)
    return zahl


# --- Bibliothek: Lernfeld -> Thema (Umfang als Budget) -> Lernsituationen ---

def _baustein(con, bid):
    zeile = con.execute("SELECT * FROM baustein WHERE id = ?", (bid,)).fetchone()
    if zeile is None:
        raise PlanungFehler("Diesen Baustein gibt es nicht.")
    return zeile


def _darf_aendern(konto, baustein):
    if konto["rolle"] != "admin" and baustein["besitzer_id"] != konto["id"]:
        raise PlanungFehler("Ändern darf nur, wer den Baustein angelegt hat.")


def bibliothek(con, bildungsgang_id):
    """Alle Bausteine eines Bildungsgangs je Lernfeld: lf["themen"] = [Thema mit lernsituationen] plus Nutzung."""
    lernfelder = [dict(z) for z in con.execute("SELECT id, nummer, name, stufe_id, stunden FROM lernfeld WHERE bildungsgang_id = ? "
                                               "AND aktiv = 1", (bildungsgang_id,))]
    lernfelder.sort(key=lambda lf: natuerlich(lf["nummer"]))
    namen = {z["id"]: z["name"] for z in con.execute("SELECT id, name FROM lehrkraft")}
    genutzt = {}
    for z in con.execute("SELECT DISTINCT p.baustein_id, k.name FROM plan_thema p JOIN klasse k ON k.id = p.klasse_id "
                         "WHERE p.baustein_id IS NOT NULL UNION SELECT DISTINCT l.baustein_id, k.name FROM plan_ls l "
                         "JOIN plan_thema p ON p.id = l.thema_id JOIN klasse k ON k.id = p.klasse_id WHERE l.baustein_id IS NOT NULL"):
        genutzt.setdefault(z[0], set()).add(z[1])
    for lf in lernfelder:
        alle = [dict(z) for z in con.execute("SELECT * FROM baustein WHERE lernfeld_id = ? ORDER BY reihenfolge, id", (lf["id"],))]
        for b in alle:
            b["besitzer"] = namen.get(b["besitzer_id"], "")
            b["genutzt"] = sorted(genutzt.get(b["id"], set()))
        kinder = {}
        for b in alle:
            if b["art"] == "ls" and b["eltern_id"]:
                kinder.setdefault(b["eltern_id"], []).append(b)
        lf["themen"] = []
        for b in alle:
            if b["art"] == "thema":
                b["lernsituationen"] = kinder.get(b["id"], [])
                b["verteilt"] = sum(x["bloecke"] for x in b["lernsituationen"])
                b["genutzt"] = sorted(set(b["genutzt"]).union(*[set(x["genutzt"]) for x in b["lernsituationen"]]))
                lf["themen"].append(b)
    return lernfelder


def baustein_speichern(con, konto, daten, bid=None):
    """Thema (Ordner mit Umfang als Budget) oder Lernsituation in einem Thema (eltern_id) anlegen/aendern."""
    if bid is not None:
        alt = _baustein(con, bid)
        _darf_aendern(konto, alt)
        art, lfid, eltern = alt["art"], alt["lernfeld_id"], alt["eltern_id"]
    else:
        art = daten.get("art")
        if art not in ("ls", "thema"):
            raise PlanungFehler("Unbekannte Art.")
        eltern = None
        if art == "ls":
            eltern = _id(daten.get("eltern_id"))
            if eltern is None:
                raise PlanungFehler("Eine Lernsituation gehört in ein Thema.")
            t = _baustein(con, eltern)
            if t["art"] != "thema":
                raise PlanungFehler("Eine Lernsituation gehört in ein Thema.")
            lfid = t["lernfeld_id"]
        else:
            lfid = _id(daten.get("lernfeld_id"))
            if lfid is None or con.execute("SELECT 1 FROM lernfeld WHERE id = ?", (lfid,)).fetchone() is None:
                raise PlanungFehler("Bitte ein Lernfeld wählen.")
    titel = _text(daten.get("titel"), "einen Titel")
    bloecke = _bloecke(daten.get("bloecke") or 0)
    hinweis = _text(daten.get("hinweis"), "den Hinweis", 4000, pflicht=False)
    jetzt = db.jetzt()
    if bid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM baustein WHERE lernfeld_id = ? AND COALESCE(eltern_id, 0) = ?",
                            (lfid, eltern or 0)).fetchone()[0]
        return con.execute("INSERT INTO baustein (lernfeld_id, art, eltern_id, titel, bloecke, hinweis, reihenfolge, besitzer_id, erstellt, "
                           "geaendert) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (lfid, art, eltern, titel, bloecke, hinweis, reihe, konto["id"], jetzt, jetzt)).lastrowid
    con.execute("UPDATE baustein SET titel = ?, bloecke = ?, hinweis = ?, geaendert = ? WHERE id = ?", (titel, bloecke, hinweis, jetzt, bid))
    return bid


def baustein_loeschen(con, konto, bid):
    _darf_aendern(konto, _baustein(con, bid))
    con.execute("DELETE FROM baustein WHERE eltern_id = ?", (bid,))   # LS eines Themas gehen mit; Planungen behalten ihre Kopie
    con.execute("DELETE FROM baustein WHERE id = ?", (bid,))


def baustein_schieben(con, konto, bid, richtung):
    """Reihenfolge innerhalb von Thema bzw. Lernfeld: richtung -1 (nach oben) oder 1 (nach unten)."""
    b = _baustein(con, bid)
    _darf_aendern(konto, b)
    geschwister = [z["id"] for z in con.execute(
        "SELECT id FROM baustein WHERE lernfeld_id = ? AND art = ? AND COALESCE(eltern_id, 0) = ? ORDER BY reihenfolge, id",
        (b["lernfeld_id"], b["art"], b["eltern_id"] or 0))]
    _tauschen(con, "baustein", geschwister, bid, richtung)


def _tauschen(con, tabelle, ids, oid, richtung):
    i = ids.index(oid)
    j = i + (1 if richtung > 0 else -1)
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    for n, x in enumerate(ids):
        con.execute("UPDATE %s SET reihenfolge = ? WHERE id = ?" % tabelle, (n + 1, x))


# --- Straenge und Themenfolge ---

def _schuljahr(con, sid):
    zeile = con.execute("SELECT id, name, beginn, ende FROM schuljahr WHERE id = ?", (sid,)).fetchone()
    if zeile is None:
        raise PlanungFehler("Dieses Schuljahr gibt es nicht. Der Admin legt Schuljahre unter Grunddaten an.")
    return dict(zeile)


def straenge(con, lid, schuljahr_id):
    """Klassen der Lehrkraft im Schuljahr (je Klasse EINE Themenfolge, Gruppen gehoeren dazu): aus allen
    Stundenplan-Versionen, die im Schuljahr gelten, und aus vorhandenen Planungen.
    [{klasse_id, gruppe_id (immer None), name, klasse, gruppe (''), gruppen: [Namen], bildungsgang_id, themen}]"""
    sj = _schuljahr(con, schuljahr_id)
    liste = stundenplan.versionen(con, lid)
    klassen_ids = set()
    mit_gruppen = {}
    for v in liste:
        if v["ab"] <= sj["ende"] and (v["bis"] or "9999-12-31") >= sj["beginn"]:
            for e in v["eintraege"]:
                klassen_ids.add(e["klasse_id"])
                if e["gruppe_id"]:
                    mit_gruppen.setdefault(e["klasse_id"], set()).add(e["gruppe_id"])
    anzahl = {}
    for z in con.execute("SELECT klasse_id, COUNT(*) AS n FROM plan_thema WHERE lehrkraft_id = ? AND schuljahr_id = ? "
                         "GROUP BY klasse_id", (lid, schuljahr_id)):
        klassen_ids.add(z["klasse_id"])
        anzahl[z["klasse_id"]] = z["n"]
    klassen = {k["id"]: k for k in grunddaten.klassen(con)}
    gruppen = {g["id"]: g for g in stundenplan.gruppen(con, lid)}
    ergebnis = []
    for kid in klassen_ids:
        k = klassen.get(kid)
        if k is None:
            continue
        ergebnis.append({"klasse_id": kid, "gruppe_id": None, "klasse": k["name"], "gruppe": "", "name": k["name"],
                         "gruppen": sorted(gruppen[g]["name"] for g in mit_gruppen.get(kid, ()) if g in gruppen),
                         "bildungsgang_id": k["bildungsgang_id"], "stufe": k["stufe"], "themen": anzahl.get(kid, 0)})
    ergebnis.sort(key=lambda s: s["klasse"])
    return ergebnis


def _strang_aus(con, lid, daten):
    """Klasse und Schuljahr aus den Daten; die Planung gilt immer fuer die ganze Klasse (gruppe_id wird ignoriert)."""
    kid = _id(daten.get("klasse_id"))
    if kid is None or con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
        raise PlanungFehler("Bitte eine Klasse wählen.")
    sid = _id(daten.get("schuljahr_id"))
    _schuljahr(con, sid)
    return kid, None, sid


def _themen(con, lid, kid, gid, sid):
    """Themen eines Strangs in Reihenfolge, je mit ihren Lernsituationen (t["ls"])."""
    themen = [dict(z) for z in con.execute(
        "SELECT * FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ? "
        "ORDER BY reihenfolge, id", (lid, kid, gid or 0, sid))]
    if themen:
        ls = {}
        for z in con.execute("SELECT * FROM plan_ls WHERE thema_id IN (%s) ORDER BY reihenfolge, id" % ",".join("?" * len(themen)),
                             [t["id"] for t in themen]):
            ls.setdefault(z["thema_id"], []).append(dict(z))
        for t in themen:
            t["ls"] = ls.get(t["id"], [])
    return themen


def _thema(con, lid, tid):
    zeile = con.execute("SELECT * FROM plan_thema WHERE id = ? AND lehrkraft_id = ?", (tid, lid)).fetchone()
    if zeile is None:
        raise PlanungFehler("Dieses Thema gibt es nicht.")
    return zeile


def _lernfeld_der_klasse(con, kid, lfid):
    lfid = _id(lfid)
    if lfid is None:
        return None
    if con.execute("SELECT 1 FROM lernfeld l JOIN klasse k ON k.bildungsgang_id = l.bildungsgang_id WHERE l.id = ? AND k.id = ?",
                   (lfid, kid)).fetchone() is None:
        raise PlanungFehler("Das Lernfeld gehört nicht zum Bildungsgang der Klasse.")
    return lfid


def thema_speichern(con, lid, daten, tid=None):
    """Thema anlegen (am Ende der Folge des Strangs) oder aendern (Titel, Umfang als Budget, Lernfeld, Hinweis)."""
    if tid is None:
        kid, gid, sid = _strang_aus(con, lid, daten)
    else:
        alt = _thema(con, lid, tid)
        _keine_pruefung(alt)
        kid, gid, sid = alt["klasse_id"], alt["gruppe_id"], alt["schuljahr_id"]
    werte = (_text(daten.get("titel"), "einen Titel"), _bloecke(daten.get("bloecke") or 1),
             _lernfeld_der_klasse(con, kid, daten.get("lernfeld_id")), _text(daten.get("hinweis"), "den Hinweis", 4000, False))
    if tid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? "
                            "AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ?", (lid, kid, gid or 0, sid)).fetchone()[0]
        return con.execute("INSERT INTO plan_thema (lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, reihenfolge, titel, bloecke, "
                           "lernfeld_id, hinweis, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (lid, kid, gid, sid, reihe) + werte + (db.jetzt(),)).lastrowid
    con.execute("UPDATE plan_thema SET titel = ?, bloecke = ?, lernfeld_id = ?, hinweis = ? WHERE id = ?", werte + (tid,))
    return tid


def _keine_pruefung(t):
    if t["pruefung_id"]:
        raise PlanungFehler("Dieses Thema ist eine Prüfung. Termin und Umfang änderst du unter Prüfungen.")


def thema_loeschen(con, lid, tid):
    _keine_pruefung(_thema(con, lid, tid))
    con.execute("DELETE FROM plan_thema WHERE id = ?", (tid,))   # seine Lernsituationen gehen mit


def thema_schieben(con, lid, tid, richtung):
    t = _thema(con, lid, tid)
    ids = [x["id"] for x in _themen(con, lid, t["klasse_id"], t["gruppe_id"], t["schuljahr_id"])]
    _tauschen(con, "plan_thema", ids, tid, richtung)


def thema_an_stelle(con, lid, tid, stelle):
    """Thema an eine Position (0 = erste) der Folge setzen (Ziehen in der Liste)."""
    t = _thema(con, lid, tid)
    ids = [x["id"] for x in _themen(con, lid, t["klasse_id"], t["gruppe_id"], t["schuljahr_id"])]
    ids.remove(tid)
    try:
        stelle = max(0, min(int(stelle), len(ids)))
    except (TypeError, ValueError):
        raise PlanungFehler("Ungültige Position.")
    ids.insert(stelle, tid)
    for n, x in enumerate(ids):
        con.execute("UPDATE plan_thema SET reihenfolge = ? WHERE id = ?", (n + 1, x))


def festsetzen(con, lid, tid, datum, beginn):
    """Stecknadel: das Thema beginnt genau in diesem Block (datum + beginn). Ohne datum wird sie geloest."""
    _keine_pruefung(_thema(con, lid, tid))
    if not datum:
        con.execute("UPDATE plan_thema SET fest_datum = NULL, fest_beginn = NULL WHERE id = ?", (tid,))
        return
    try:
        datetime.date.fromisoformat(datum)
    except (TypeError, ValueError):
        raise PlanungFehler("Ungültiges Datum.")
    if not isinstance(beginn, str) or not stundenplan.UHRZEIT.fullmatch(beginn):
        raise PlanungFehler("Ungültiger Block.")
    con.execute("UPDATE plan_thema SET fest_datum = ?, fest_beginn = ? WHERE id = ?", (datum, beginn, tid))


# --- Lernsitutationen eines Themas der Planung ---

def _ls(con, lid, lsid):
    z = con.execute("SELECT l.* FROM plan_ls l JOIN plan_thema t ON t.id = l.thema_id WHERE l.id = ? AND t.lehrkraft_id = ?",
                    (lsid, lid)).fetchone()
    if z is None:
        raise PlanungFehler("Diese Lernsituation gibt es nicht.")
    return z


def ls_speichern(con, lid, daten, lsid=None):
    """Lernsituation in einem Thema anlegen (am Ende) bzw. aendern; mit thema_id auch in ein anderes Thema verschieben."""
    alt = _ls(con, lid, lsid) if lsid is not None else None
    tid = _id(daten.get("thema_id")) or (alt["thema_id"] if alt else None)
    if tid is None:
        raise PlanungFehler("Bitte ein Thema wählen.")
    t = _thema(con, lid, tid)
    _keine_pruefung(t)
    titel = _text(daten.get("titel"), "einen Titel")
    bloecke = _bloecke(daten.get("bloecke") or 1)
    hinweis = _text(daten.get("hinweis"), "den Hinweis", 4000, False)
    if alt is None or alt["thema_id"] != tid:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM plan_ls WHERE thema_id = ?", (tid,)).fetchone()[0]
    else:
        reihe = alt["reihenfolge"]
    if alt is None:
        return con.execute("INSERT INTO plan_ls (thema_id, reihenfolge, titel, bloecke, hinweis, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                           (tid, reihe, titel, bloecke, hinweis, db.jetzt())).lastrowid
    con.execute("UPDATE plan_ls SET thema_id = ?, reihenfolge = ?, titel = ?, bloecke = ?, hinweis = ? WHERE id = ?",
                (tid, reihe, titel, bloecke, hinweis, lsid))
    return lsid


def ls_loeschen(con, lid, lsid):
    _ls(con, lid, lsid)
    con.execute("DELETE FROM plan_ls WHERE id = ?", (lsid,))


def ls_schieben(con, lid, lsid, richtung):
    z = _ls(con, lid, lsid)
    ids = [x["id"] for x in con.execute("SELECT id FROM plan_ls WHERE thema_id = ? ORDER BY reihenfolge, id", (z["thema_id"],))]
    _tauschen(con, "plan_ls", ids, lsid, richtung)


def aus_bibliothek(con, lid, daten):
    """Baustein in die Planung kopieren. Thema -> neues Thema am Ende der Folge samt seinen Lernsituationen;
    Lernsituation -> in ein vorhandenes Thema der Planung (thema_id). Rueckgabe: Anzahl der Lernsituationen."""
    b = _baustein(con, _id(daten.get("baustein_id")))
    if b["art"] == "ls":
        tid = _id(daten.get("thema_id"))
        if tid is None:
            raise PlanungFehler("Bitte das Thema wählen, in das die Lernsituation kommt.")
        neu = ls_speichern(con, lid, {"thema_id": tid, "titel": b["titel"], "bloecke": b["bloecke"], "hinweis": b["hinweis"]})
        con.execute("UPDATE plan_ls SET baustein_id = ? WHERE id = ?", (b["id"], neu))
        return 1
    kid, gid, sid = _strang_aus(con, lid, daten)
    if con.execute("SELECT 1 FROM lernfeld l JOIN klasse k ON k.bildungsgang_id = l.bildungsgang_id WHERE l.id = ? AND k.id = ?",
                   (b["lernfeld_id"], kid)).fetchone() is None:
        raise PlanungFehler("Der Baustein gehört zu einem anderen Bildungsgang als die Klasse.")
    tid = thema_speichern(con, lid, {"klasse_id": kid, "gruppe_id": gid, "schuljahr_id": sid, "titel": b["titel"],
                                     "bloecke": max(b["bloecke"], 1), "lernfeld_id": b["lernfeld_id"], "hinweis": b["hinweis"]})
    con.execute("UPDATE plan_thema SET baustein_id = ? WHERE id = ?", (b["id"], tid))
    kinder = con.execute("SELECT * FROM baustein WHERE eltern_id = ? ORDER BY reihenfolge, id", (b["id"],)).fetchall()
    for n, k in enumerate(kinder):
        con.execute("INSERT INTO plan_ls (thema_id, reihenfolge, titel, bloecke, hinweis, baustein_id, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tid, n + 1, k["titel"], k["bloecke"], k["hinweis"], k["id"], db.jetzt()))
    return len(kinder)


# --- Bloecke eines Strangs ---

class Kalender:
    """Stundenplan, Aenderungen und freie Tage einer Lehrkraft fuer einen Zeitraum, einmal geladen."""

    def __init__(self, con, lid, von, bis):
        self.con, self.lid, self.von, self.bis = con, lid, von, bis
        self.versionen = stundenplan.versionen(con, lid)
        self.regel = stundenplan.a_woche_regel(con)
        self.frei = stundenplan.freie_tage(con, von, bis)
        self.aend = stundenplan._aenderungen(con, lid, von, bis)
        self.weg = {(a["datum"], a["beginn"]): a for a in self.aend if a["art"] in ("ausfall", "vertreten", "verschoben")}
        self.zeitraum = grunddaten.klassen_zeitraum(con)
        self._tage = {}

    def regulaer(self, datum):
        if datum not in self._tage:
            self._tage[datum] = stundenplan._regulaere_stunden(self.con, self.lid, datum, self.versionen, self.regel, self.frei,
                                                               self.zeitraum)
        return self._tage[datum]

    def bloecke(self, kid, gid=None):
        """Alle Bloecke der Klasse (ganze Klasse und ihre Gruppen) im Zeitraum, sortiert:
        [{datum, beginn, ende, lernfeld_id, art, gruppe_id}] und die ausgefallenen (nur zur Anzeige und fuer
        "holt nach"): [{datum, beginn, ende, zustand, grund, gruppe_id}]. gid wird nicht mehr beachtet."""
        nutzbar, weg = [], []
        tag = self.von
        while tag <= self.bis:
            iso = tag.isoformat()
            for e in self.regulaer(tag):
                if e["klasse_id"] != kid:
                    continue
                a = self.weg.get((iso, e["beginn"]))
                if a and a["art"] == "vertreten" and a["thema_weiter"]:   # Vertretung fuehrt das Thema weiter: zaehlt
                    nutzbar.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "lernfeld_id": e["lernfeld_id"],
                                    "art": "vertreten", "wer": a["wer"], "gruppe_id": e["gruppe_id"]})
                elif a:
                    weg.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "zustand": a["art"], "grund": a["grund"],
                                "gruppe_id": e["gruppe_id"]})
                else:
                    nutzbar.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "lernfeld_id": e["lernfeld_id"], "art": "regulaer",
                                    "gruppe_id": e["gruppe_id"]})
            tag += datetime.timedelta(days=1)
        for a in self.aend:
            if a["klasse_id"] != kid:
                continue
            if a["art"] == "zusatz" and self.von.isoformat() <= a["datum"] <= self.bis.isoformat():
                nutzbar.append({"datum": a["datum"], "beginn": a["beginn"], "ende": a["ende"], "lernfeld_id": None, "art": "zusatz",
                                "gruppe_id": a["gruppe_id"]})
            elif a["art"] == "verschoben" and a["ziel_datum"] and self.von.isoformat() <= a["ziel_datum"] <= self.bis.isoformat():
                ursprung = next((e for e in self.regulaer(datetime.date.fromisoformat(a["datum"])) if e["beginn"] == a["beginn"]), None)
                nutzbar.append({"datum": a["ziel_datum"], "beginn": a["ziel_beginn"], "ende": a["ziel_ende"],
                                "lernfeld_id": ursprung["lernfeld_id"] if ursprung else None, "art": "verschoben",
                                "gruppe_id": a["gruppe_id"]})
        nutzbar.sort(key=lambda b: (b["datum"], b["beginn"]))
        weg.sort(key=lambda b: (b["datum"], b["beginn"]))
        return nutzbar, weg


def schritte_bilden(bloecke, weg=(), fest=()):
    """Fasst Gruppenstunden zusammen: G1 und G2 bekommen nacheinander denselben Stoff und liegen am selben Tag,
    also bilden der n-te Block jeder Gruppe an einem Tag gemeinsam EINEN Schritt der Klasse. Bloecke der ganzen
    Klasse sind je ein Schritt. Die Zaehlung n beruecksichtigt ausgefallene Bloecke (weg), damit ein Ausfall von
    G1 die Paare nicht verschiebt. fest: Mengen von (datum, beginn), die vorab je einen Schritt bilden (Termine
    einer getrennt geschriebenen Pruefung); die uebrigen Gruppenstunden des Tages werden danach der Reihe nach
    gepaart. Rueckgabe: Liste von Schritten (je Liste von Indizes in bloecke), in zeitlicher Reihenfolge."""
    pos = {(b["datum"], b["beginn"]): i for i, b in enumerate(bloecke)}
    belegt, schritte = set(), []
    for menge in fest:
        idx = sorted(pos[k] for k in menge if k in pos and pos[k] not in belegt)
        if idx:
            schritte.append(idx)
            belegt.update(idx)
    frei = [b for i, b in enumerate(bloecke) if i not in belegt]
    rang = {}
    for b in sorted(frei + list(weg), key=lambda b: (b["datum"], b["beginn"])):
        if b.get("gruppe_id"):
            k = (b["datum"], b["gruppe_id"])
            rang[k] = rang.get(k, 0) + 1
            b["_rang"] = rang[k]
    platz = {}
    for i, b in enumerate(bloecke):
        if i in belegt:
            continue
        if not b.get("gruppe_id"):
            schritte.append([i])
            continue
        k = (b["datum"], b.pop("_rang"))
        n = platz.get(k)
        if n is not None and all(bloecke[j]["gruppe_id"] != b["gruppe_id"] for j in schritte[n]):
            schritte[n].append(i)
        else:
            platz[k] = len(schritte)
            schritte.append([i])
    for b in weg:
        b.pop("_rang", None)
    schritte.sort(key=lambda g: g[0])
    return schritte


def _feste_paare(con, lid, kid, bloecke):
    """Getrennt geschriebene Pruefungen der Klasse: die Bloecke ihrer Termine an einem Tag bilden zusammen je einen
    Schritt (bei mehreren Bloecken der k-te Block jeder Gruppe ab ihrem Termin)."""
    termine = {}
    for z in con.execute("SELECT t.pruefung_id, t.gruppe_id, t.datum, t.beginn, p.bloecke FROM pruefung_termin t "
                         "JOIN pruefung p ON p.id = t.pruefung_id WHERE p.lehrkraft_id = ? AND p.klasse_id = ? "
                         "AND p.form = 'termin' AND p.teilung = 'getrennt'", (lid, kid)):
        termine.setdefault((z["pruefung_id"], z["datum"]), []).append(z)
    fest = []
    for (_, datum), liste in termine.items():
        reihen = []
        for z in liste:
            eigene = [b for b in bloecke if b["datum"] == datum and b["gruppe_id"] == z["gruppe_id"] and b["beginn"] >= z["beginn"]]
            reihen.append([(b["datum"], b["beginn"]) for b in eigene[:max(1, z["bloecke"])]])
        for k in range(max(len(r) for r in reihen)):
            menge = {r[k] for r in reihen if k < len(r)}
            if len(menge) > 1:
                fest.append(menge)
    return fest


def _ist_zusammen(staende):
    """Ist eines Schritts aus den Ist-Staenden seiner Bloecke: fertig vor mehr vor ok."""
    staende = [x for x in staende if x]
    for x in ("fertig", "mehr", "ok"):
        if x in staende:
            return x
    return None


# --- Fliessen ---

IST_STAENDE = ("ok", "mehr", "fertig")


def fliessen(themen, bloecke, ist=None):
    """Verteilt die Themen (in Reihenfolge, mit bloecke = Budget, ls = Lernsituationen, lernfeld_id,
    fest_datum/fest_beginn) auf die Bloecke.

    Ein Thema laeuft zuerst durch seine Lernsituationen (je mit eigenem Umfang), danach durch den noch offenen Rest
    seines Budgets. Bedarf des Themas = max(Budget, Summe der LS). ist: {(datum, beginn): 'ok'|'mehr'|'fertig'} wirkt
    auf das, was gerade dran ist: 'mehr' = die LS (bzw. der offene Rest) braucht einen Block mehr, 'fertig' = die LS
    endet mit diesem Block (ein offener Rest fuellt das Budget weiter auf); im offenen Rest beendet 'fertig' das Thema.
    Rueckgabe: (belegung, info) mit belegung[i] = (thema_id, teil, bedarf, ls_id oder None) fuer Block i oder None und
    info[thema_id] = {zugeteilt, bedarf, ueberlauf, bloecke, nadel, ls: {ls_id: [bloecke]}, offen: [bloecke]}."""
    ist = ist or {}
    spuren = {b["lernfeld_id"] for b in bloecke if b["lernfeld_id"]}
    spur_bloecke = {}
    for i, b in enumerate(bloecke):
        spur_bloecke.setdefault(b["lernfeld_id"] if b["lernfeld_id"] in spuren else None, []).append(i)
    belegung = [None] * len(bloecke)
    info = {}
    for t in themen:
        info[t["id"]] = {"nadel": None, "bloecke": [], "zuordnung": [], "slots": [[ls["id"], ls["bloecke"]] for ls in t.get("ls", [])],
                         "slot": 0, "im_slot": 0, "budget": t["bloecke"], "extra": 0, "ende": False}

    def bedarf(x):
        if x["ende"]:
            return len(x["bloecke"])
        return max(x["budget"] + x["extra"], sum(s[1] for s in x["slots"]))

    spur_themen = {}
    for t in themen:
        spur_themen.setdefault(t["lernfeld_id"] if t["lernfeld_id"] in spuren else None, []).append(t)

    # 0. Pruefungen unterbrechen den Unterricht: sie belegen ihren Termin vor allem anderen, gleich welches Lernfeld
    #    der Block hat und ob dort ein festgesetztes Thema liegt (bei mehreren Bloecken die folgenden desselben Tages).
    #    Alles andere fliesst drumherum und laeuft danach nahtlos weiter.
    frei_alle = [True] * len(bloecke)
    for t in themen:
        if not (t.get("pruefung_id") and t.get("fest_datum")):
            continue
        x = info[t["id"]]
        start = next((i for i, b in enumerate(bloecke) if (t["fest_datum"], t["fest_beginn"]) in
                      b.get("keys", {(b["datum"], b["beginn"])})), None)
        if start is None:
            x["nadel"] = "fehlt"
            x["ende"] = True                    # ohne Unterricht zum Termin bleibt sie leer
            continue
        x["nadel"] = "ok"
        i = start
        while i < len(bloecke) and bloecke[i]["datum"] == bloecke[start]["datum"] and len(x["bloecke"]) < t["bloecke"]:
            if frei_alle[i]:
                frei_alle[i] = False
                x["bloecke"].append(i)
                x["zuordnung"].append(None)
            i += 1

    for spur, liste in spur_themen.items():
        idx = spur_bloecke.get(spur, [])
        frei = [frei_alle[i] for i in idx]

        def fuellen(t, n):
            """Belegt ab Position n freie Bloecke fuer t, bis der (veraenderliche) Bedarf gedeckt ist."""
            x = info[t["id"]]
            while n < len(idx) and len(x["bloecke"]) < bedarf(x):
                if frei[n]:
                    frei[n] = False
                    b = bloecke[idx[n]]
                    stand = ist.get((b["datum"], b["beginn"]))
                    x["bloecke"].append(idx[n])
                    if x["slot"] < len(x["slots"]):             # in einer Lernsituation
                        slot = x["slots"][x["slot"]]
                        x["zuordnung"].append(slot[0])
                        x["im_slot"] += 1
                        if stand == "mehr":
                            slot[1] += 1
                        elif stand == "fertig":
                            slot[1] = x["im_slot"]
                        if x["im_slot"] >= slot[1]:
                            x["slot"] += 1
                            x["im_slot"] = 0
                    else:                                        # noch offener Rest des Budgets
                        x["zuordnung"].append(None)
                        if stand == "mehr":
                            x["extra"] += 1
                        elif stand == "fertig":
                            x["ende"] = True
                n += 1
            return n

        # 1. festgesetzte Themen ab ihrem Block
        for t in liste:
            if not t.get("fest_datum") or t.get("pruefung_id"):   # Pruefungen liegen schon (Schritt 0)
                continue
            start = next((n for n, i in enumerate(idx) if (t["fest_datum"], t["fest_beginn"]) in
                          bloecke[i].get("keys", {(bloecke[i]["datum"], bloecke[i]["beginn"])})), None)
            if start is None:
                info[t["id"]]["nadel"] = "fehlt"
                continue
            info[t["id"]]["nadel"] = "ok"
            fuellen(t, start)
        # 2. die uebrigen in Reihenfolge in die freien Bloecke
        zeiger = 0
        for t in liste:
            if info[t["id"]]["nadel"] != "ok" and not t.get("pruefung_id"):
                zeiger = fuellen(t, zeiger)
    for t in themen:
        x = info[t["id"]]
        x["bedarf"] = bedarf(x)
        paare = sorted(zip(x["bloecke"], x["zuordnung"]))
        x["bloecke"] = [i for i, _ in paare]
        x["zugeteilt"] = len(x["bloecke"])
        x["ueberlauf"] = max(0, x["bedarf"] - x["zugeteilt"])
        x["ls"] = {}
        x["offen"] = []
        for teil, (i, ls_id) in enumerate(paare):
            belegung[i] = (t["id"], teil + 1, x["bedarf"], ls_id)
            (x["ls"].setdefault(ls_id, []) if ls_id else x["offen"]).append(i)
        x["ls_laenge"] = {s[0]: s[1] for s in x["slots"]}
    return belegung, info


def _schuljahr_grenzen(sj):
    return datetime.date.fromisoformat(sj["beginn"]), datetime.date.fromisoformat(sj["ende"])


def _ist(con, lid, von, bis):
    return {(z["datum"], z["beginn"]): z["stand"] for z in con.execute(
        "SELECT datum, beginn, stand FROM ist WHERE lehrkraft_id = ? AND datum BETWEEN ? AND ?", (lid, von.isoformat(), bis.isoformat()))}


def ferienabschnitte(frei, von, bis):
    """Zusammenhaengende unterrichtsfreie Werktage (Ferien, Feiertage) im Zeitraum: [{von, bis, name, tage}].
    Ein Wochenende dazwischen trennt einen Abschnitt nicht; Feiertage in den Ferien (Neujahr) gehoeren dazu.
    Name ist der haeufigste Name im Abschnitt (also der der Ferien)."""
    abschnitte = []
    tag = von
    while tag <= bis:
        name = frei.get(tag.isoformat())
        if name and tag.isoweekday() <= 5:
            letzter = abschnitte[-1] if abschnitte else None
            zwischen = []
            if letzter:
                d = datetime.date.fromisoformat(letzter["bis"]) + datetime.timedelta(days=1)
                while d < tag:
                    zwischen.append(d)
                    d += datetime.timedelta(days=1)
            if letzter and all(d.isoweekday() > 5 for d in zwischen):
                letzter["bis"] = tag.isoformat()
                letzter["tage"] += 1
                letzter["namen"].append(name)
            else:
                abschnitte.append({"von": tag.isoformat(), "bis": tag.isoformat(), "tage": 1, "namen": [name]})
        tag += datetime.timedelta(days=1)
    for a in abschnitte:
        namen = a.pop("namen")
        a["name"] = max(namen, key=namen.count)
    return abschnitte


def _strang_rechnen(con, lid, kid, gid, sj, kal=None, ist=None):
    """Bloecke, ausgefallene Bloecke, Themen, Fluss und Schritte einer Klasse im Schuljahr. Die Themen fliessen auf
    die Schritte (gepaarte Gruppenstunden = ein Schritt); jeder Block bekommt das Thema seines Schritts
    (thema_id, teil, von, ls_id, ls_teil, schritt, zweit = nicht der erste Block des Schritts) und "nachholen"
    (Stoff, den seine Gruppe durch einen Ausfall verpasst hat). info[...]["bloecke"] sind Schritt-Indizes."""
    von, bis = _schuljahr_grenzen(sj)
    kal = kal or Kalender(con, lid, von, bis)
    ist = _ist(con, lid, von, bis) if ist is None else ist
    bloecke, weg = kal.bloecke(kid)
    gnamen = {g["id"]: g["name"] for g in stundenplan.gruppen(con, lid)}
    for b in bloecke + weg:
        b["gruppe"] = gnamen.get(b["gruppe_id"], "") if b["gruppe_id"] else ""
    gruppen_ = schritte_bilden(bloecke, weg, _feste_paare(con, lid, kid, bloecke))
    schritte = []
    for g in gruppen_:
        erster = bloecke[g[0]]
        schritte.append({"datum": erster["datum"], "beginn": erster["beginn"], "ende": erster["ende"], "lernfeld_id": erster["lernfeld_id"],
                         "keys": {(bloecke[j]["datum"], bloecke[j]["beginn"]) for j in g}, "bloecke": g})
    ist_schritte = {(x["datum"], x["beginn"]): _ist_zusammen(ist.get(k) for k in x["keys"]) for x in schritte}
    themen = _themen(con, lid, kid, None, sj["id"])
    belegung, info = fliessen(themen, schritte, ist_schritte)
    ls_zaehler = {}
    for n, x in enumerate(schritte):
        thema_id, teil, von_, ls_id = belegung[n] if belegung[n] else (None, None, None, None)
        ls_teil = None
        if ls_id:
            ls_zaehler[ls_id] = ls_teil = ls_zaehler.get(ls_id, 0) + 1
        x.update(thema_id=thema_id, teil=teil, von=von_, ls_id=ls_id, ls_teil=ls_teil)
        for m, i in enumerate(x["bloecke"]):
            b = bloecke[i]
            b.update(thema_id=thema_id, teil=teil, von=von_, ls_id=ls_id, ls_teil=ls_teil, schritt=n, zweit=m > 0,
                     ist=ist.get((b["datum"], b["beginn"])), nachholen=[])
    # Ausfall nur einer Gruppe: der Plan laeuft weiter (die andere Gruppe hatte den Schritt allein); die naechste
    # Stunde der ausgefallenen Gruppe bekommt den Hinweis "holt nach"
    nach_tag = {}
    for i, b in enumerate(bloecke):
        nach_tag.setdefault(b["datum"], []).append(i)
    nach_id = {t["id"]: t for t in themen}
    for w in weg:
        if not w["gruppe_id"] or w["zustand"] == "verschoben":
            continue
        rang = sum(1 for x in bloecke + weg if x["datum"] == w["datum"] and x["gruppe_id"] == w["gruppe_id"] and x["beginn"] <= w["beginn"])
        partner = None
        for gid_ in {bloecke[i]["gruppe_id"] for i in nach_tag.get(w["datum"], [])} - {None, w["gruppe_id"]}:
            eigene = sorted([x for x in bloecke + weg if x["datum"] == w["datum"] and x["gruppe_id"] == gid_], key=lambda x: x["beginn"])
            if len(eigene) >= rang and any(eigene[rang - 1] is y for y in bloecke):
                partner = eigene[rang - 1]
                break
        if not partner or not partner["thema_id"] or len(schritte[partner["schritt"]]["bloecke"]) > 1:
            continue
        t = nach_id[partner["thema_id"]]
        ls = next((y for y in t["ls"] if y["id"] == partner["ls_id"]), None)
        folgende = next((b for b in bloecke if b["gruppe_id"] == w["gruppe_id"] and (b["datum"], b["beginn"]) > (w["datum"], w["beginn"])), None)
        if folgende is not None:
            folgende["nachholen"].append({"datum": w["datum"], "gruppe": w["gruppe"], "thema": t["titel"], "ls": ls["titel"] if ls else ""})
    return kal, bloecke, weg, themen, info, schritte


def plan(con, lid, kid, gid, sid, jetzt=None):
    """Alles fuer die Planungsansicht eines Strangs: Themen mit Fluss-Info, Bloecke mit Belegung und Ist, ausgefallene
    Bloecke, Ferienabschnitte, Kalenderwochen, Lernfelder der Klasse und die Bilanz."""
    sj = _schuljahr(con, sid)
    von, bis = _schuljahr_grenzen(sj)
    jetzt = jetzt or db.jetzt()
    kal, bloecke, weg, themen, info, schritte = _strang_rechnen(con, lid, kid, gid, sj)
    for b in bloecke:
        b["vergangen"] = (b["datum"], b["ende"]) <= (jetzt[:10], jetzt[11:16])
    for x in schritte:
        x["vergangen"] = all(bloecke[i]["vergangen"] for i in x["bloecke"])
    lf = {z["id"]: dict(z) for z in sorted(con.execute("SELECT l.id, l.nummer, l.name, l.stunden FROM lernfeld l JOIN klasse k "
                                                       "ON k.bildungsgang_id = l.bildungsgang_id WHERE k.id = ?", (kid,)),
                                           key=lambda z: natuerlich(z["nummer"]))}
    for t in themen:
        x = info[t["id"]]
        t.update(zugeteilt=x["zugeteilt"], bedarf=x["bedarf"], ueberlauf=x["ueberlauf"], nadel=x["nadel"],
                 von=schritte[x["bloecke"][0]]["datum"] if x["bloecke"] else None,
                 bis=schritte[x["bloecke"][-1]]["datum"] if x["bloecke"] else None,
                 gehalten=sum(1 for i in x["bloecke"] if schritte[i]["vergangen"]),
                 lernfeld=lf.get(t["lernfeld_id"], {}).get("nummer", ""),
                 verteilt=sum(ls["bloecke"] for ls in t["ls"]), offen=len(x["offen"]),
                 offen_rest=max(0, x["bedarf"] - sum(x["ls_laenge"].values())) if t["ls"] else x["bedarf"])
        for ls in t["ls"]:
            mein = x["ls"].get(ls["id"], [])
            ls.update(zugeteilt=len(mein), bedarf=x["ls_laenge"].get(ls["id"], ls["bloecke"]),
                      von=schritte[mein[0]]["datum"] if mein else None, bis=schritte[mein[-1]]["datum"] if mein else None)
    # Kalenderwochen des Schuljahres (fuer die Ansicht "Schuljahr")
    wochen = []
    montag = stundenplan.montag_von(von)
    while montag <= bis:
        tage = [(montag + datetime.timedelta(days=n)).isoformat() for n in range(5)]
        frei = [kal.frei[t] for t in tage if t in kal.frei]
        wochen.append({"montag": montag.isoformat(), "kw": montag.isocalendar()[1], "frei": len(frei) >= 5,
                       "ferien": frei[0] if frei else None, "freie_tage": len(frei),
                       "heute": tage[0] <= jetzt[:10] <= tage[-1]})
        montag += datetime.timedelta(days=7)
    # Bilanz je Lernfeld: Stundenansatz (in Bloecken) gegen Verplantes und Gehaltenes
    bilanz = []
    for lfid in [x for x in lf if any(t["lernfeld_id"] == x for t in themen)] + ([None] if any(not t["lernfeld_id"] for t in themen) else []):
        ts = [t for t in themen if t["lernfeld_id"] == lfid]
        l = lf.get(lfid)
        bilanz.append({"lernfeld_id": lfid, "nummer": l["nummer"] if l else "ohne Lernfeld", "name": l["name"] if l else "",
                       "ansatz": round(l["stunden"] / 2) if l and l["stunden"] else None,
                       "verplant": sum(t["bedarf"] for t in ts), "gehalten": sum(t["gehalten"] for t in ts),
                       "ueberlauf": sum(t["ueberlauf"] for t in ts)})
    offen = [b for b in bloecke if b["vergangen"] and b["thema_id"] and not b["ist"] and b["art"] != "vertreten"]
    geteilt = sum(1 for x in schritte if len(x["bloecke"]) > 1)
    spuren = sorted({b["lernfeld_id"] for b in bloecke if b["lernfeld_id"]})
    kl = con.execute("SELECT beginn, ende FROM klasse WHERE id = ?", (kid,)).fetchone()
    klasse_zeitraum = {"beginn": kl["beginn"] if kl["beginn"] and kl["beginn"] > sj["beginn"] else None,
                       "ende": kl["ende"] if kl["ende"] and kl["ende"] < sj["ende"] else None}
    return {"schuljahr": sj, "klasse_zeitraum": klasse_zeitraum, "themen": themen, "bloecke": bloecke, "weg": weg, "wochen": wochen,
            "ferien": ferienabschnitte(kal.frei, von, bis),
            "lernfelder": list(lf.values()), "spuren": [lf.get(s, {"id": s, "nummer": "?"}) for s in spuren], "bilanz": bilanz,
            "summe": {"bloecke": len(schritte), "verplant": sum(t["zugeteilt"] for t in themen),
                      "bedarf": sum(t["bedarf"] for t in themen), "ueberlauf": sum(t["ueberlauf"] for t in themen),
                      "frei": sum(1 for x in schritte if x["thema_id"] is None), "geteilt": geteilt,
                      "rest": sum(1 for x in schritte if not x["vergangen"]), "ist_offen": len(offen)},
            "heute": jetzt[:10]}


# --- Wochenplan, Stunde und Ist-Stand ---

def _schuljahr_der_woche(con, woche):
    return grunddaten.schuljahr_zum(con, woche["montag"]) or grunddaten.schuljahr_zum(con, woche["tage"][-1]["datum"])


def _gehalten_oder_weiter(b):
    """Stunde, die in der Planung zaehlt: von mir gehalten oder vertreten mit meinem Thema."""
    return bool(b["klasse"]) and b["art"] in ("regulaer", "zusatz", "verschoben") and \
        (not b["zustand"] or (b["zustand"] == "vertreten" and b.get("thema_weiter")))


def themen_der_woche(con, lid, woche):
    """Ergaenzt die Bloecke eines Wochenplans (stundenplan.woche) um Thema und Ist-Stand:
    block["thema"] = {id, titel, teil, von, lernfeld, ls} oder None, block["ist"] = Stand oder None."""
    for b in woche["bloecke"]:
        b["thema"], b["ist"] = None, None
    sj = _schuljahr_der_woche(con, woche) if woche["bloecke"] else None
    if sj is None:
        return woche
    von, bis = _schuljahr_grenzen(sj)
    kal = Kalender(con, lid, von, bis)
    ist = _ist(con, lid, von, bis)
    nummern = {z["id"]: z["nummer"] for z in con.execute("SELECT id, nummer FROM lernfeld")}
    klassen_ = {b["klasse"]["id"] for b in woche["bloecke"] if b["klasse"] and b["art"] in ("regulaer", "zusatz", "verschoben")}
    zuordnung = {}
    for kid in klassen_:
        _, bloecke, _, themen, _, _ = _strang_rechnen(con, lid, kid, None, sj, kal, ist)
        nach_id = {t["id"]: t for t in themen}
        for b in bloecke:
            if b["thema_id"]:
                t = nach_id[b["thema_id"]]
                ls = next((x for x in t["ls"] if x["id"] == b["ls_id"]), None)
                zuordnung[(b["datum"], b["beginn"], kid)] = {"id": t["id"], "titel": t["titel"], "teil": b["teil"], "von": b["von"],
                                                           "lernfeld": nummern.get(t["lernfeld_id"], ""), "ls": ls["titel"] if ls else "",
                                                           "pruefung_id": t["pruefung_id"], "nachholen": b["nachholen"]}
    for b in woche["bloecke"]:
        if _gehalten_oder_weiter(b):
            b["thema"] = zuordnung.get((b["datum"], b["beginn"], b["klasse"]["id"]))
            b["ist"] = ist.get((b["datum"], b["beginn"]))
    return woche


def _stunden_des_strangs(con, lid, kid, gid, sj, kal, ist):
    _, bloecke, _, themen, info, _ = _strang_rechnen(con, lid, kid, gid, sj, kal, ist)
    return bloecke, {t["id"]: t for t in themen}, info


def stunde(con, lid, datum, beginn, jetzt=None):
    """Alles fuer das Stunden-Overlay einer gehaltenen Stunde (regulaer, Zusatzstunde oder hierher verschoben):
    Klasse/Gruppe, Thema mit Teil und Hinweis, Ist-Stand, Merker dieser und der naechsten Stunde, vorige und
    naechste Stunde des Strangs, Termine des Tages."""
    jetzt = jetzt or db.jetzt()
    tag = datetime.date.fromisoformat(datum)
    woche = stundenplan.woche(con, lid, tag, jetzt)
    b = next((x for x in woche["bloecke"] if x["datum"] == datum and x["beginn"] == beginn and _gehalten_oder_weiter(x)), None)
    if b is None:
        raise PlanungFehler("Zu dieser Zeit hältst du keine Stunde.")
    kid, gid = b["klasse"]["id"], b["gruppe"]["id"] if b["gruppe"] else None
    ergebnis = {"datum": datum, "beginn": b["beginn"], "ende": b["ende"], "klasse": b["klasse"], "gruppe": b["gruppe"], "art": b["art"],
                "zeile": next((z for z in woche["zeilen"] if z["beginn"] == b["beginn"]), None),
                "thema": None, "ist": None, "merker": b["merker"], "naechste": None, "vorige": None, "naechste_merker": [],
                "nachholen": [], "geteilt": [],
                "termine": [t for t in woche["termine"] if t["datum"] <= datum <= (t["bis"] or t["datum"])],
                "vergangen": (datum, b["ende"]) <= (jetzt[:10], jetzt[11:16]), "jetzt": b["jetzt"], "schuljahr": None,
                "aendern": b["art"] == "regulaer" and not b["zustand"],
                "vertreten": {"wer": b["wer"], "grund": b["grund"], "aenderung_id": b["aenderung_id"]} if b["zustand"] == "vertreten" else None,
                "raster": [dict(r) for r in stundenplan.raster_der_klasse(con, kid)]}
    sj = grunddaten.schuljahr_zum(con, datum)
    zeile = con.execute("SELECT stand FROM ist WHERE lehrkraft_id = ? AND datum = ? AND beginn = ?", (lid, datum, beginn)).fetchone()
    ergebnis["ist"] = zeile["stand"] if zeile else None
    ergebnis.update(_eintraege(con, lid, datum, b["beginn"], kid, gid))
    if sj is None:
        return ergebnis
    ergebnis["schuljahr"] = sj["name"]
    von, bis = _schuljahr_grenzen(sj)
    kal = Kalender(con, lid, von, bis)
    alle, themen, info = _stunden_des_strangs(con, lid, kid, gid, sj, kal, _ist(con, lid, von, bis))
    x = next((y for y in alle if y["datum"] == datum and y["beginn"] == beginn), None)
    if x is None:
        return ergebnis
    ergebnis["nachholen"] = x["nachholen"]
    ergebnis["geteilt"] = [y["gruppe"] for y in alle if y["schritt"] == x["schritt"] and y is not x]
    # vorige/naechste Stunde aus Sicht dieser Stunde: bei einer Gruppe deren Stunden und die der ganzen Klasse,
    # bei der ganzen Klasse je Schritt die erste Stunde
    bloecke = [y for y in alle if (y["gruppe_id"] in (None, x["gruppe_id"]) if x["gruppe_id"] else (not y["zweit"] or y is x))]
    pos = bloecke.index(x)
    if x["thema_id"]:
        t = themen[x["thema_id"]]
        lf = con.execute("SELECT nummer, name FROM lernfeld WHERE id = ?", (t["lernfeld_id"],)).fetchone() if t["lernfeld_id"] else None
        ls = next((y for y in t["ls"] if y["id"] == x["ls_id"]), None)
        ls_teil = x["ls_teil"] if ls else None
        ls_von = info[t["id"]]["ls_laenge"].get(ls["id"]) if ls else None
        if t["pruefung_id"]:
            ergebnis["vorschlag"] = "Prüfung: " + t["titel"]
        ergebnis["thema"] = {"id": t["id"], "titel": t["titel"], "teil": x["teil"], "von": x["von"], "ls": ls["titel"] if ls else "",
                             "pruefung": bool(t["pruefung_id"]),
                             "ls_teil": ls_teil, "ls_von": ls_von,
                             "hinweis": (ls["hinweis"] if ls and ls["hinweis"] else t["hinweis"]),
                             "lernfeld": lf["nummer"] if lf else "", "lernfeld_name": lf["name"] if lf else ""}
    if pos > 0:
        ergebnis["vorige"] = {"datum": bloecke[pos - 1]["datum"], "beginn": bloecke[pos - 1]["beginn"]}
    if pos + 1 < len(bloecke):
        n = bloecke[pos + 1]
        ergebnis["naechste"] = {"datum": n["datum"], "beginn": n["beginn"],
                                "thema": themen[n["thema_id"]]["titel"] if n["thema_id"] else None}
        ergebnis["naechste_merker"] = [{"id": m["id"], "text": m["titel"]} for m in con.execute(
            "SELECT id, titel FROM termin WHERE lehrkraft_id = ? AND art = 'merker' AND datum = ? AND beginn = ? AND klasse_id = ?",
            (lid, n["datum"], n["beginn"], kid))]
    return ergebnis


INHALT_MAX, NOTIZEN_MAX = 2000, 10000


def _eintraege(con, lid, datum, beginn, kid, gid):
    """Unterrichtsinhalt und Notizen dieser Stunde, die letzte Stunde der Klasse mit Eintrag davor (bei einer Gruppe:
    deren Stunden und die der ganzen Klasse) und die Inhalte der anderen Gruppen am selben Tag."""
    z = con.execute("SELECT inhalt, notizen, geaendert FROM stunde_eintrag WHERE lehrkraft_id = ? AND datum = ? AND beginn = ?",
                    (lid, datum, beginn)).fetchone()
    gnamen = {g["id"]: g["name"] for g in stundenplan.gruppen(con, lid)}
    v = con.execute("SELECT datum, beginn, gruppe_id, inhalt, notizen FROM stunde_eintrag WHERE lehrkraft_id = ? AND klasse_id = ? "
                    "AND (datum < ? OR (datum = ? AND beginn < ?)) AND (inhalt != '' OR notizen != '') "
                    + ("AND COALESCE(gruppe_id, 0) IN (0, ?) " if gid else "") + "ORDER BY datum DESC, beginn DESC LIMIT 1",
                    (lid, kid, datum, datum, beginn) + ((gid,) if gid else ())).fetchone()
    andere = [] if not gid else [
        {"gruppe": gnamen.get(y["gruppe_id"], ""), "beginn": y["beginn"], "inhalt": y["inhalt"]} for y in con.execute(
            "SELECT beginn, gruppe_id, inhalt FROM stunde_eintrag WHERE lehrkraft_id = ? AND klasse_id = ? AND datum = ? "
            "AND gruppe_id IS NOT NULL AND gruppe_id != ? AND inhalt != '' ORDER BY beginn", (lid, kid, datum, gid))]
    return {"eintrag": {"inhalt": z["inhalt"] if z else "", "notizen": z["notizen"] if z else "", "geaendert": z["geaendert"] if z else None},
            "vorstunde": {"datum": v["datum"], "beginn": v["beginn"], "gruppe": gnamen.get(v["gruppe_id"], "") if v["gruppe_id"] else "",
                          "inhalt": v["inhalt"], "notizen": v["notizen"]} if v else None,
            "andere_gruppe": andere, "vorschlag": ""}


def eintrag_setzen(con, lid, datum, beginn, daten):
    """Unterrichtsinhalt und/oder Notizen einer gehaltenen Stunde speichern (fehlende Felder bleiben, wie sie sind).
    Sind danach beide leer, verschwindet der Eintrag."""
    try:
        datetime.date.fromisoformat(datum)
    except (TypeError, ValueError):
        raise PlanungFehler("Ungültiges Datum.")
    s = stunde(con, lid, datum, beginn)
    alt = s["eintrag"]
    neu = {}
    for feld, grenze, name in (("inhalt", INHALT_MAX, "Der Unterrichtsinhalt"), ("notizen", NOTIZEN_MAX, "Die Notizen")):
        wert = daten.get(feld)
        if wert is None:
            neu[feld] = alt[feld]
            continue
        if not isinstance(wert, str):
            raise PlanungFehler("Ungültige Eingabe.")
        wert = wert.replace("\r\n", "\n").strip()
        if len(wert) > grenze:
            raise PlanungFehler("%s darf höchstens %d Zeichen haben." % (name, grenze))
        neu[feld] = wert
    if not neu["inhalt"] and not neu["notizen"]:
        con.execute("DELETE FROM stunde_eintrag WHERE lehrkraft_id = ? AND datum = ? AND beginn = ?", (lid, datum, s["beginn"]))
        return
    con.execute("INSERT INTO stunde_eintrag (lehrkraft_id, datum, beginn, klasse_id, gruppe_id, inhalt, notizen, geaendert) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (lehrkraft_id, datum, beginn) DO UPDATE SET inhalt = excluded.inhalt, "
                "notizen = excluded.notizen, klasse_id = excluded.klasse_id, gruppe_id = excluded.gruppe_id, geaendert = excluded.geaendert",
                (lid, datum, s["beginn"], s["klasse"]["id"], s["gruppe"]["id"] if s["gruppe"] else None, neu["inhalt"], neu["notizen"], db.jetzt()))


def ist_setzen(con, lid, datum, beginn, stand):
    """Ist-Stand einer gehaltenen Stunde setzen ('ok', 'mehr', 'fertig') oder mit stand=None zuruecknehmen."""
    if stand not in IST_STAENDE + (None,):
        raise PlanungFehler("Unbekannter Ist-Stand.")
    s = stunde(con, lid, datum, beginn)
    if stand is None:
        con.execute("DELETE FROM ist WHERE lehrkraft_id = ? AND datum = ? AND beginn = ?", (lid, datum, beginn))
        return
    if stand != "ok" and not s["thema"]:
        raise PlanungFehler("In dieser Stunde liegt kein Thema aus der Planung.")
    con.execute("INSERT INTO ist (lehrkraft_id, datum, beginn, klasse_id, gruppe_id, thema_id, stand, geaendert) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (lehrkraft_id, datum, beginn) DO UPDATE SET stand = excluded.stand, thema_id = excluded.thema_id, "
                "geaendert = excluded.geaendert",
                (lid, datum, s["beginn"], s["klasse"]["id"], s["gruppe"]["id"] if s["gruppe"] else None,
                 s["thema"]["id"] if s["thema"] else None, stand, db.jetzt()))


def offene_ist(con, lid, jetzt=None, grenze=30):
    """Vergangene Stunden des laufenden Schuljahres mit Thema, aber ohne Ist-Bestaetigung (neueste zuerst)."""
    jetzt = jetzt or db.jetzt()
    sj = grunddaten.schuljahr_zum(con, jetzt[:10])
    if sj is None:
        return []
    von, bis = _schuljahr_grenzen(sj)
    if datetime.date.fromisoformat(jetzt[:10]) < von:
        return []
    kal = Kalender(con, lid, von, bis)   # ganzes Schuljahr: spaetere Stecknadeln (Pruefungen) praegen den Fluss mit
    ist = _ist(con, lid, von, bis)
    offen = []
    for s in straenge(con, lid, sj["id"]):
        bloecke, themen, _ = _stunden_des_strangs(con, lid, s["klasse_id"], None, sj, kal, ist)
        for b in bloecke:
            if b["thema_id"] and not b["ist"] and b["art"] != "vertreten" and (b["datum"], b["ende"]) <= (jetzt[:10], jetzt[11:16]):
                offen.append({"datum": b["datum"], "beginn": b["beginn"], "strang": s["name"] + (" · " + b["gruppe"] if b["gruppe"] else ""),
                              "thema": themen[b["thema_id"]]["titel"], "klasse_id": s["klasse_id"], "gruppe_id": b["gruppe_id"],
                              "thema_id": b["thema_id"]})
    offen.sort(key=lambda x: (x["datum"], x["beginn"]), reverse=True)
    return offen[:grenze]


def ist_alle_bestaetigen(con, lid, jetzt=None):
    """Alle offenen Stunden als 'wie geplant' bestaetigen. Rueckgabe: Anzahl."""
    offen = offene_ist(con, lid, jetzt, grenze=100000)
    for o in offen:   # "wie geplant" aendert den Fluss nicht, deshalb direkt eintragen
        con.execute("INSERT OR IGNORE INTO ist (lehrkraft_id, datum, beginn, klasse_id, gruppe_id, thema_id, stand, geaendert) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'ok', ?)", (lid, o["datum"], o["beginn"], o["klasse_id"], o["gruppe_id"], o["thema_id"], db.jetzt()))
    return len(offen)


def unterricht_am(con, lid, kid, datum):
    """Gehaltene Bloecke der Klasse an einem Tag (ganze Klasse und Gruppen): [{beginn, ende, gruppe_id, gruppe}]."""
    tag = datetime.date.fromisoformat(datum)
    kal = Kalender(con, lid, tag, tag)
    bloecke, _ = kal.bloecke(kid)
    gnamen = {g["id"]: g["name"] for g in stundenplan.gruppen(con, lid)}
    return [{"beginn": b["beginn"], "ende": b["ende"], "gruppe_id": b["gruppe_id"], "gruppe": gnamen.get(b["gruppe_id"], "")}
            for b in bloecke]
