"""Unterrichtsplanung (Stufe C1): Bibliothek, Themenfolge je Strang und das Fliessen der Themen auf die Bloecke.

Begriffe
  Bibliothek   Lernsituationen (LS) und Themen je Lernfeld bzw. Modul, Umfang in Bloecken (Doppelstunden). Fuer alle im
               Bildungsgang sichtbar; aendern darf, wer den Baustein angelegt hat (und der Admin).
  Strang       Was eine Lehrkraft in einer Klasse plant: Klasse + Gruppe (oder ganze Klasse) in einem Schuljahr. Eine
               geteilte Klasse hat so bis zu drei Straenge (ganze Klasse, Gr. 1, Gr. 2).
  Thema        Ein Eintrag der Themenfolge eines Strangs, meist aus der Bibliothek kopiert ("In Klasse uebernehmen").
  Spur         Bloecke im Stundenplan koennen optional einem Lernfeld zugeordnet sein (parallele Lernfelder, z. B.
               montags LF 7, donnerstags LF 9). Themen dieses Lernfelds fliessen nur in diese Bloecke; alle anderen
               Themen fliessen in Reihenfolge in die Bloecke ohne Lernfeld.

Fliessen: Die Bloecke eines Strangs sind die regulaeren Stunden laut Stundenplan im Schuljahr (ohne Ferien, Feiertage,
Ausfaelle, Stunden mit Vertretung und weggeschobene), dazu Zusatzstunden und hierher verschobene Stunden. Festgesetzte
Themen (Stecknadel) belegen zuerst ihre Bloecke ab dem festgesetzten Block, die uebrigen fuellen in Listenreihenfolge
die freien Bloecke. Was nicht mehr passt, ist Ueberlauf (rot in der Planung).
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


# --- Bibliothek ---

def _baustein(con, bid):
    zeile = con.execute("SELECT * FROM baustein WHERE id = ?", (bid,)).fetchone()
    if zeile is None:
        raise PlanungFehler("Diesen Baustein gibt es nicht.")
    return zeile


def _darf_aendern(konto, baustein):
    if konto["rolle"] != "admin" and baustein["besitzer_id"] != konto["id"]:
        raise PlanungFehler("Ändern darf nur, wer den Baustein angelegt hat.")


def bibliothek(con, bildungsgang_id):
    """Alle Bausteine eines Bildungsgangs: {lernfeld_id: [LS mit themen, einzelne Themen]} plus Nutzung in Klassen."""
    lernfelder = [dict(z) for z in con.execute("SELECT id, nummer, name, stufe_id, stunden FROM lernfeld WHERE bildungsgang_id = ? "
                                               "AND aktiv = 1", (bildungsgang_id,))]
    lernfelder.sort(key=lambda lf: natuerlich(lf["nummer"]))
    namen = {z["id"]: z["name"] for z in con.execute("SELECT id, name FROM lehrkraft")}
    genutzt = {}
    for z in con.execute("SELECT DISTINCT p.baustein_id, k.name FROM plan_thema p JOIN klasse k ON k.id = p.klasse_id "
                         "WHERE p.baustein_id IS NOT NULL ORDER BY k.name"):
        genutzt.setdefault(z["baustein_id"], []).append(z["name"])
    for lf in lernfelder:
        alle = [dict(z) for z in con.execute("SELECT * FROM baustein WHERE lernfeld_id = ? ORDER BY reihenfolge, id", (lf["id"],))]
        for b in alle:
            b["besitzer"] = namen.get(b["besitzer_id"], "")
            b["genutzt"] = genutzt.get(b["id"], [])
        themen = {}
        for b in alle:
            if b["art"] == "thema" and b["ls_id"]:
                themen.setdefault(b["ls_id"], []).append(b)
        lf["lernsituationen"] = []
        for b in alle:
            if b["art"] == "ls":
                b["themen"] = themen.get(b["id"], [])
                b["umfang"] = sum(t["bloecke"] for t in b["themen"]) if b["themen"] else b["bloecke"]
                for t in b["themen"]:   # Genutzt-Angabe der LS umfasst ihre Themen
                    b["genutzt"] = sorted(set(b["genutzt"]) | set(t["genutzt"]))
                lf["lernsituationen"].append(b)
        lf["themen"] = [b for b in alle if b["art"] == "thema" and not b["ls_id"]]
    return lernfelder


def baustein_speichern(con, konto, daten, bid=None):
    """LS oder Thema anlegen/aendern. Thema in einer LS: ls_id. LS ohne Themen fliesst mit ihrem eigenen Umfang."""
    if bid is not None:
        alt = _baustein(con, bid)
        _darf_aendern(konto, alt)
        art, lfid, ls_id = alt["art"], alt["lernfeld_id"], alt["ls_id"]
    else:
        art = daten.get("art")
        if art not in ("ls", "thema"):
            raise PlanungFehler("Unbekannte Art.")
        ls_id = _id(daten.get("ls_id")) if art == "thema" else None
        if ls_id is not None:
            ls = _baustein(con, ls_id)
            if ls["art"] != "ls":
                raise PlanungFehler("Themen gehören in eine Lernsituation.")
            lfid = ls["lernfeld_id"]
        else:
            lfid = _id(daten.get("lernfeld_id"))
            if lfid is None or con.execute("SELECT 1 FROM lernfeld WHERE id = ?", (lfid,)).fetchone() is None:
                raise PlanungFehler("Bitte ein Lernfeld wählen.")
    titel = _text(daten.get("titel"), "einen Titel")
    bloecke = _bloecke(daten.get("bloecke") or 0, 0 if art == "ls" else 1)
    hinweis = _text(daten.get("hinweis"), "den Hinweis", 4000, pflicht=False)
    jetzt = db.jetzt()
    if bid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM baustein WHERE lernfeld_id = ? AND COALESCE(ls_id, 0) = ?",
                            (lfid, ls_id or 0)).fetchone()[0]
        return con.execute("INSERT INTO baustein (lernfeld_id, art, ls_id, titel, bloecke, hinweis, reihenfolge, besitzer_id, erstellt, "
                           "geaendert) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (lfid, art, ls_id, titel, bloecke, hinweis, reihe, konto["id"], jetzt, jetzt)).lastrowid
    con.execute("UPDATE baustein SET titel = ?, bloecke = ?, hinweis = ?, geaendert = ? WHERE id = ?", (titel, bloecke, hinweis, jetzt, bid))
    return bid


def baustein_loeschen(con, konto, bid):
    _darf_aendern(konto, _baustein(con, bid))
    con.execute("DELETE FROM baustein WHERE id = ?", (bid,))   # Themen einer LS gehen mit; Planungen behalten ihre Kopie


def baustein_schieben(con, konto, bid, richtung):
    """Reihenfolge innerhalb von LS bzw. Lernfeld: richtung -1 (nach oben) oder 1 (nach unten)."""
    b = _baustein(con, bid)
    _darf_aendern(konto, b)
    geschwister = [z["id"] for z in con.execute(
        "SELECT id FROM baustein WHERE lernfeld_id = ? AND art = ? AND COALESCE(ls_id, 0) = ? ORDER BY reihenfolge, id",
        (b["lernfeld_id"], b["art"], b["ls_id"] or 0))]
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
    """Straenge der Lehrkraft im Schuljahr: aus allen Stundenplan-Versionen, die im Schuljahr gelten, und aus
    vorhandenen Planungen. [{klasse_id, gruppe_id, name, klasse, gruppe, bildungsgang_id, themen}]"""
    sj = _schuljahr(con, schuljahr_id)
    liste = stundenplan.versionen(con, lid)
    paare = set()
    for v in liste:
        if v["ab"] <= sj["ende"] and (v["bis"] or "9999-12-31") >= sj["beginn"]:
            paare |= {(e["klasse_id"], e["gruppe_id"]) for e in v["eintraege"]}
    anzahl = {}
    for z in con.execute("SELECT klasse_id, gruppe_id, COUNT(*) AS n FROM plan_thema WHERE lehrkraft_id = ? AND schuljahr_id = ? "
                         "GROUP BY klasse_id, gruppe_id", (lid, schuljahr_id)):
        paare.add((z["klasse_id"], z["gruppe_id"]))
        anzahl[(z["klasse_id"], z["gruppe_id"])] = z["n"]
    klassen = {k["id"]: k for k in grunddaten.klassen(con)}
    gruppen = {g["id"]: g for g in stundenplan.gruppen(con, lid)}
    geteilt = {k for k, g in paare if g}
    ergebnis = []
    for kid, gid in paare:
        k = klassen.get(kid)
        if k is None:
            continue
        gname = gruppen[gid]["name"] if gid in gruppen else ("ganze Klasse" if kid in geteilt else "")
        ergebnis.append({"klasse_id": kid, "gruppe_id": gid, "klasse": k["name"], "gruppe": gname,
                         "name": k["name"] + (" · " + gname if gname else ""), "bildungsgang_id": k["bildungsgang_id"],
                         "stufe": k["stufe"], "themen": anzahl.get((kid, gid), 0)})
    ergebnis.sort(key=lambda s: (s["klasse"], s["gruppe_id"] is not None, s["gruppe"]))
    return ergebnis


def _strang_aus(con, lid, daten):
    kid = _id(daten.get("klasse_id"))
    if kid is None or con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
        raise PlanungFehler("Bitte eine Klasse wählen.")
    gid = _id(daten.get("gruppe_id"))
    if gid is not None and con.execute("SELECT 1 FROM gruppe WHERE id = ? AND lehrkraft_id = ? AND klasse_id = ?",
                                       (gid, lid, kid)).fetchone() is None:
        raise PlanungFehler("Diese Gruppe gehört nicht zur Klasse.")
    sid = _id(daten.get("schuljahr_id"))
    _schuljahr(con, sid)
    return kid, gid, sid


def _themen(con, lid, kid, gid, sid):
    return [dict(z) for z in con.execute(
        "SELECT * FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ? "
        "ORDER BY reihenfolge, id", (lid, kid, gid or 0, sid))]


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
    """Thema anlegen (am Ende der Folge des Strangs) oder aendern (Titel, Umfang, Lernfeld, Lernsituation, Hinweis)."""
    if tid is None:
        kid, gid, sid = _strang_aus(con, lid, daten)
    else:
        alt = _thema(con, lid, tid)
        _keine_pruefung(alt)
        kid, gid, sid = alt["klasse_id"], alt["gruppe_id"], alt["schuljahr_id"]
    werte = (_text(daten.get("titel"), "einen Titel"), _bloecke(daten.get("bloecke") or 1),
             _lernfeld_der_klasse(con, kid, daten.get("lernfeld_id")), _text(daten.get("ls_titel"), "die Lernsituation", 200, False),
             _text(daten.get("hinweis"), "den Hinweis", 4000, False))
    if tid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? "
                            "AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ?", (lid, kid, gid or 0, sid)).fetchone()[0]
        return con.execute("INSERT INTO plan_thema (lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, reihenfolge, titel, bloecke, "
                           "lernfeld_id, ls_titel, hinweis, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (lid, kid, gid, sid, reihe) + werte + (db.jetzt(),)).lastrowid
    con.execute("UPDATE plan_thema SET titel = ?, bloecke = ?, lernfeld_id = ?, ls_titel = ?, hinweis = ? WHERE id = ?", werte + (tid,))
    return tid


def _keine_pruefung(t):
    if t["pruefung_id"]:
        raise PlanungFehler("Dieses Thema ist eine Prüfung. Termin und Umfang änderst du unter Prüfungen.")


def thema_loeschen(con, lid, tid):
    _keine_pruefung(_thema(con, lid, tid))
    con.execute("DELETE FROM plan_thema WHERE id = ?", (tid,))


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


def aus_bibliothek(con, lid, daten):
    """Baustein in die Folge eines Strangs kopieren: LS mit Themen -> je Thema ein Eintrag (mit Name der LS),
    LS ohne Themen -> ein Eintrag mit ihrem Umfang, einzelnes Thema -> ein Eintrag. Rueckgabe: Anzahl."""
    kid, gid, sid = _strang_aus(con, lid, daten)
    b = _baustein(con, _id(daten.get("baustein_id")))
    if con.execute("SELECT 1 FROM lernfeld l JOIN klasse k ON k.bildungsgang_id = l.bildungsgang_id WHERE l.id = ? AND k.id = ?",
                   (b["lernfeld_id"], kid)).fetchone() is None:
        raise PlanungFehler("Der Baustein gehört zu einem anderen Bildungsgang als die Klasse.")
    if b["art"] == "ls":
        themen = con.execute("SELECT * FROM baustein WHERE ls_id = ? ORDER BY reihenfolge, id", (b["id"],)).fetchall()
        stuecke = [(t["titel"], t["bloecke"], b["titel"], t["id"], t["hinweis"]) for t in themen] or \
                  [(b["titel"], max(b["bloecke"], 1), b["titel"], b["id"], b["hinweis"])]
    else:
        ls = con.execute("SELECT titel FROM baustein WHERE id = ?", (b["ls_id"],)).fetchone() if b["ls_id"] else None
        stuecke = [(b["titel"], b["bloecke"], ls["titel"] if ls else "", b["id"], b["hinweis"])]
    reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) FROM plan_thema WHERE lehrkraft_id = ? AND klasse_id = ? "
                        "AND COALESCE(gruppe_id, 0) = ? AND schuljahr_id = ?", (lid, kid, gid or 0, sid)).fetchone()[0]
    for n, (titel, bloecke, ls_titel, bid, hinweis) in enumerate(stuecke):
        con.execute("INSERT INTO plan_thema (lehrkraft_id, klasse_id, gruppe_id, schuljahr_id, reihenfolge, titel, bloecke, lernfeld_id, "
                    "ls_titel, baustein_id, hinweis, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (lid, kid, gid, sid, reihe + n + 1, titel, max(bloecke, 1), b["lernfeld_id"], ls_titel, bid, hinweis, db.jetzt()))
    return len(stuecke)


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

    def bloecke(self, kid, gid):
        """Alle Bloecke des Strangs im Zeitraum, sortiert: [{datum, beginn, ende, lernfeld_id, art}] und die ausgefallenen
        (nur zur Anzeige): [{datum, beginn, ende, zustand, grund}]."""
        nutzbar, weg = [], []
        tag = self.von
        while tag <= self.bis:
            iso = tag.isoformat()
            for e in self.regulaer(tag):
                if e["klasse_id"] != kid or e["gruppe_id"] != gid:
                    continue
                a = self.weg.get((iso, e["beginn"]))
                if a and a["art"] == "vertreten" and a["thema_weiter"]:   # Vertretung fuehrt das Thema weiter: zaehlt
                    nutzbar.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "lernfeld_id": e["lernfeld_id"],
                                    "art": "vertreten", "wer": a["wer"]})
                elif a:
                    weg.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "zustand": a["art"], "grund": a["grund"]})
                else:
                    nutzbar.append({"datum": iso, "beginn": e["beginn"], "ende": e["ende"], "lernfeld_id": e["lernfeld_id"], "art": "regulaer"})
            tag += datetime.timedelta(days=1)
        for a in self.aend:
            if a["klasse_id"] != kid or a["gruppe_id"] != gid:
                continue
            if a["art"] == "zusatz" and self.von.isoformat() <= a["datum"] <= self.bis.isoformat():
                nutzbar.append({"datum": a["datum"], "beginn": a["beginn"], "ende": a["ende"], "lernfeld_id": None, "art": "zusatz"})
            elif a["art"] == "verschoben" and a["ziel_datum"] and self.von.isoformat() <= a["ziel_datum"] <= self.bis.isoformat():
                ursprung = next((e for e in self.regulaer(datetime.date.fromisoformat(a["datum"])) if e["beginn"] == a["beginn"]), None)
                nutzbar.append({"datum": a["ziel_datum"], "beginn": a["ziel_beginn"], "ende": a["ziel_ende"],
                                "lernfeld_id": ursprung["lernfeld_id"] if ursprung else None, "art": "verschoben"})
        nutzbar.sort(key=lambda b: (b["datum"], b["beginn"]))
        weg.sort(key=lambda b: (b["datum"], b["beginn"]))
        return nutzbar, weg


# --- Fliessen ---

IST_STAENDE = ("ok", "mehr", "fertig")


def fliessen(themen, bloecke, ist=None):
    """Verteilt die Themen (in Reihenfolge, mit bloecke, lernfeld_id, fest_datum/fest_beginn) auf die Bloecke.
    ist: {(datum, beginn): 'ok'|'mehr'|'fertig'} veraendert den Bedarf des Themas, das gerade in diesem Block liegt:
    'mehr' = es braucht einen Block mehr, 'fertig' = es endet mit diesem Block. Der Rest rueckt nach bzw. vor.
    Rueckgabe: (belegung, info) mit belegung[i] = (thema_id, teil, bedarf) fuer Block i oder None und
    info[thema_id] = {zugeteilt, bedarf, ueberlauf, bloecke, nadel: ok|fehlt|None}."""
    ist = ist or {}
    spuren = {b["lernfeld_id"] for b in bloecke if b["lernfeld_id"]}
    spur_bloecke = {}
    for i, b in enumerate(bloecke):
        spur_bloecke.setdefault(b["lernfeld_id"] if b["lernfeld_id"] in spuren else None, []).append(i)
    belegung = [None] * len(bloecke)
    info = {t["id"]: {"bedarf": t["bloecke"], "nadel": None, "bloecke": []} for t in themen}
    spur_themen = {}
    for t in themen:
        spur_themen.setdefault(t["lernfeld_id"] if t["lernfeld_id"] in spuren else None, []).append(t)

    for spur, liste in spur_themen.items():
        idx = spur_bloecke.get(spur, [])
        frei = [True] * len(idx)

        def fuellen(t, n):
            """Belegt ab Position n freie Bloecke fuer t, bis der (durch Ist veraenderliche) Bedarf gedeckt ist.
            Rueckgabe: Position nach dem letzten geprueften Block."""
            x = info[t["id"]]
            while n < len(idx) and len(x["bloecke"]) < x["bedarf"]:
                if frei[n]:
                    frei[n] = False
                    x["bloecke"].append(idx[n])
                    b = bloecke[idx[n]]
                    stand = ist.get((b["datum"], b["beginn"]))
                    if stand == "mehr":
                        x["bedarf"] += 1
                    elif stand == "fertig":
                        x["bedarf"] = len(x["bloecke"])
                n += 1
            return n

        # 1. festgesetzte Themen ab ihrem Block
        for t in liste:
            if not t.get("fest_datum"):
                continue
            start = next((n for n, i in enumerate(idx) if bloecke[i]["datum"] == t["fest_datum"] and bloecke[i]["beginn"] == t["fest_beginn"]), None)
            if start is None:
                info[t["id"]]["nadel"] = "fehlt"
                continue
            info[t["id"]]["nadel"] = "ok"
            fuellen(t, start)
        # 2. die uebrigen in Reihenfolge in die freien Bloecke
        zeiger = 0
        for t in liste:
            if info[t["id"]]["nadel"] != "ok":
                zeiger = fuellen(t, zeiger)
    for t in themen:
        x = info[t["id"]]
        x["bloecke"].sort()
        x["zugeteilt"] = len(x["bloecke"])
        x["ueberlauf"] = max(0, x["bedarf"] - x["zugeteilt"])
        for teil, i in enumerate(x["bloecke"]):
            belegung[i] = (t["id"], teil + 1, x["bedarf"])
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
    """Bloecke, ausgefallene Bloecke, Themen und Fluss eines Strangs im Schuljahr."""
    von, bis = _schuljahr_grenzen(sj)
    kal = kal or Kalender(con, lid, von, bis)
    ist = _ist(con, lid, von, bis) if ist is None else ist
    bloecke, weg = kal.bloecke(kid, gid)
    themen = _themen(con, lid, kid, gid, sj["id"])
    belegung, info = fliessen(themen, bloecke, ist)
    for i, b in enumerate(bloecke):
        b["thema_id"], b["teil"], b["von"] = belegung[i] if belegung[i] else (None, None, None)
        b["ist"] = ist.get((b["datum"], b["beginn"]))
    return kal, bloecke, weg, themen, info


def plan(con, lid, kid, gid, sid, jetzt=None):
    """Alles fuer die Planungsansicht eines Strangs: Themen mit Fluss-Info, Bloecke mit Belegung und Ist, ausgefallene
    Bloecke, Ferienabschnitte, Kalenderwochen, Lernfelder der Klasse und die Bilanz."""
    sj = _schuljahr(con, sid)
    von, bis = _schuljahr_grenzen(sj)
    jetzt = jetzt or db.jetzt()
    kal, bloecke, weg, themen, info = _strang_rechnen(con, lid, kid, gid, sj)
    for b in bloecke:
        b["vergangen"] = (b["datum"], b["ende"]) <= (jetzt[:10], jetzt[11:16])
    lf = {z["id"]: dict(z) for z in sorted(con.execute("SELECT l.id, l.nummer, l.name, l.stunden FROM lernfeld l JOIN klasse k "
                                                       "ON k.bildungsgang_id = l.bildungsgang_id WHERE k.id = ?", (kid,)),
                                           key=lambda z: natuerlich(z["nummer"]))}
    for t in themen:
        x = info[t["id"]]
        t.update(zugeteilt=x["zugeteilt"], bedarf=x["bedarf"], ueberlauf=x["ueberlauf"], nadel=x["nadel"],
                 von=bloecke[x["bloecke"][0]]["datum"] if x["bloecke"] else None,
                 bis=bloecke[x["bloecke"][-1]]["datum"] if x["bloecke"] else None,
                 gehalten=sum(1 for i in x["bloecke"] if bloecke[i]["vergangen"]),
                 lernfeld=lf.get(t["lernfeld_id"], {}).get("nummer", ""))
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
    spuren = sorted({b["lernfeld_id"] for b in bloecke if b["lernfeld_id"]})
    kl = con.execute("SELECT beginn, ende FROM klasse WHERE id = ?", (kid,)).fetchone()
    klasse_zeitraum = {"beginn": kl["beginn"] if kl["beginn"] and kl["beginn"] > sj["beginn"] else None,
                       "ende": kl["ende"] if kl["ende"] and kl["ende"] < sj["ende"] else None}
    return {"schuljahr": sj, "klasse_zeitraum": klasse_zeitraum, "themen": themen, "bloecke": bloecke, "weg": weg, "wochen": wochen,
            "ferien": ferienabschnitte(kal.frei, von, bis),
            "lernfelder": list(lf.values()), "spuren": [lf.get(s, {"id": s, "nummer": "?"}) for s in spuren], "bilanz": bilanz,
            "summe": {"bloecke": len(bloecke), "verplant": sum(t["zugeteilt"] for t in themen),
                      "bedarf": sum(t["bedarf"] for t in themen), "ueberlauf": sum(t["ueberlauf"] for t in themen),
                      "frei": sum(1 for b in bloecke if b["thema_id"] is None),
                      "rest": sum(1 for b in bloecke if not b["vergangen"]), "ist_offen": len(offen)},
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
    straenge_ = {(b["klasse"]["id"], b["gruppe"]["id"] if b["gruppe"] else None) for b in woche["bloecke"]
                 if b["klasse"] and b["art"] in ("regulaer", "zusatz", "verschoben")}
    zuordnung = {}
    for kid, gid in straenge_:
        _, bloecke, _, themen, _ = _strang_rechnen(con, lid, kid, gid, sj, kal, ist)
        nach_id = {t["id"]: t for t in themen}
        for b in bloecke:
            if b["thema_id"]:
                t = nach_id[b["thema_id"]]
                zuordnung[(b["datum"], b["beginn"], kid)] = {"id": t["id"], "titel": t["titel"], "teil": b["teil"], "von": b["von"],
                                                           "lernfeld": nummern.get(t["lernfeld_id"], ""), "ls": t["ls_titel"],
                                                           "pruefung_id": t["pruefung_id"]}
    for b in woche["bloecke"]:
        if _gehalten_oder_weiter(b):
            b["thema"] = zuordnung.get((b["datum"], b["beginn"], b["klasse"]["id"]))
            b["ist"] = ist.get((b["datum"], b["beginn"]))
    return woche


def _stunden_des_strangs(con, lid, kid, gid, sj, kal, ist):
    _, bloecke, _, themen, _ = _strang_rechnen(con, lid, kid, gid, sj, kal, ist)
    return bloecke, {t["id"]: t for t in themen}


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
                "termine": [t for t in woche["termine"] if t["datum"] <= datum <= (t["bis"] or t["datum"])],
                "vergangen": (datum, b["ende"]) <= (jetzt[:10], jetzt[11:16]), "jetzt": b["jetzt"], "schuljahr": None,
                "aendern": b["art"] == "regulaer" and not b["zustand"],
                "vertreten": {"wer": b["wer"], "grund": b["grund"], "aenderung_id": b["aenderung_id"]} if b["zustand"] == "vertreten" else None,
                "raster": [dict(r) for r in stundenplan.raster_der_klasse(con, kid)]}
    sj = grunddaten.schuljahr_zum(con, datum)
    zeile = con.execute("SELECT stand FROM ist WHERE lehrkraft_id = ? AND datum = ? AND beginn = ?", (lid, datum, beginn)).fetchone()
    ergebnis["ist"] = zeile["stand"] if zeile else None
    if sj is None:
        return ergebnis
    ergebnis["schuljahr"] = sj["name"]
    von, bis = _schuljahr_grenzen(sj)
    kal = Kalender(con, lid, von, bis)
    bloecke, themen = _stunden_des_strangs(con, lid, kid, gid, sj, kal, _ist(con, lid, von, bis))
    pos = next((i for i, x in enumerate(bloecke) if x["datum"] == datum and x["beginn"] == beginn), None)
    if pos is None:
        return ergebnis
    x = bloecke[pos]
    if x["thema_id"]:
        t = themen[x["thema_id"]]
        lf = con.execute("SELECT nummer, name FROM lernfeld WHERE id = ?", (t["lernfeld_id"],)).fetchone() if t["lernfeld_id"] else None
        ergebnis["thema"] = {"id": t["id"], "titel": t["titel"], "teil": x["teil"], "von": x["von"], "ls": t["ls_titel"],
                             "hinweis": t["hinweis"], "lernfeld": lf["nummer"] if lf else "", "lernfeld_name": lf["name"] if lf else ""}
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
    bis = min(bis, datetime.date.fromisoformat(jetzt[:10]))
    if bis < von:
        return []
    kal = Kalender(con, lid, von, bis)
    ist = _ist(con, lid, von, bis)
    offen = []
    for s in straenge(con, lid, sj["id"]):
        bloecke, themen = _stunden_des_strangs(con, lid, s["klasse_id"], s["gruppe_id"], sj, kal, ist)
        for b in bloecke:
            if b["thema_id"] and not b["ist"] and b["art"] != "vertreten" and (b["datum"], b["ende"]) <= (jetzt[:10], jetzt[11:16]):
                offen.append({"datum": b["datum"], "beginn": b["beginn"], "strang": s["name"], "thema": themen[b["thema_id"]]["titel"],
                              "klasse_id": s["klasse_id"], "gruppe_id": s["gruppe_id"], "thema_id": b["thema_id"]})
    offen.sort(key=lambda x: (x["datum"], x["beginn"]), reverse=True)
    return offen[:grenze]


def ist_alle_bestaetigen(con, lid, jetzt=None):
    """Alle offenen Stunden als 'wie geplant' bestaetigen. Rueckgabe: Anzahl."""
    offen = offene_ist(con, lid, jetzt, grenze=100000)
    for o in offen:   # "wie geplant" aendert den Fluss nicht, deshalb direkt eintragen
        con.execute("INSERT OR IGNORE INTO ist (lehrkraft_id, datum, beginn, klasse_id, gruppe_id, thema_id, stand, geaendert) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'ok', ?)", (lid, o["datum"], o["beginn"], o["klasse_id"], o["gruppe_id"], o["thema_id"], db.jetzt()))
    return len(offen)
