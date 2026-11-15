"""Stundenplan und Wochenplan (Stufe B).

Jede Lehrkraft pflegt ihren Grundstundenplan von Hand: je Wochentag und Block eine Klasse aus den gemeinsamen Klassen,
fuer jede Woche oder nur in A- bzw. B-Wochen. Ein Plan hat Versionen, die ab einem Datum gelten (2. Halbjahr = neue
Version); vergangene Wochen zeigen den damals gueltigen Plan. Die Uhrzeiten kommen aus dem Zeitraster des Bildungsgangs
der Klasse und stehen im Eintrag mit drin, damit alte Versionen ihre Zeiten behalten.

Einmalige Aenderungen gelten fuer ein Datum:
  ausfall     die Stunde faellt aus (zaehlt in der Planung als Ausfall)
  vertreten   die Stunde findet statt, aber jemand anderes haelt sie (ich bin z. B. auf Fortbildung)
  verschoben  die Stunde findet an einem anderen Tag oder in einem anderen Block statt
  vertretung  ich vertrete jemanden (zusaetzlicher Block, auch in einer fremden Klasse)
  zusatz      zusaetzliche Stunde in einer Klasse

Dazu eigene Termine (Dienst, privat) und Merker an einer Stunde. A/B-Wochen richten sich nach der Kalenderwoche; der
Admin legt fest, ob die ungeraden oder die geraden KW A-Wochen sind. Ferien kommen aus den Grunddaten, die gesetzlichen
Feiertage in Rheinland-Pfalz werden berechnet.
"""
import datetime
import re
import sqlite3

from . import db, grunddaten

UHRZEIT = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa")
SCHULTAGE = 5                      # Mo bis Fr (die Datenbank erlaubt den Samstag schon fuer spaeter)
WOCHEN = ("alle", "A", "B")
AENDERUNGEN = ("ausfall", "vertreten", "verschoben", "vertretung", "zusatz")
TERMINARTEN = ("dienst", "privat", "merker")
# Klassenfarben (gut unterscheidbar, auf weissem Grund kraeftig genug fuer den Rand der Karte)
FARBEN = ("#00639C", "#7b4fa8", "#8a9c00", "#d99000", "#0f8a8a", "#D4005E", "#5d6b7a", "#c2571a")


class StundenplanFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


# --- kleine Pruefhilfen ---

def _datum(wert, feld="das Datum"):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10])
    except ValueError:
        raise StundenplanFehler("Bitte %s angeben." % feld)


def _uhrzeit(wert, feld="eine Uhrzeit"):
    wert = (wert or "").strip() if isinstance(wert, str) else ""
    if not UHRZEIT.fullmatch(wert):
        raise StundenplanFehler("Bitte %s als HH:MM angeben." % feld)
    return wert


def _text(wert, max_len=200):
    wert = wert.strip() if isinstance(wert, str) else ""
    if len(wert) > max_len:
        raise StundenplanFehler("Der Text darf höchstens %d Zeichen haben." % max_len)
    return wert


def _id(wert):
    if wert in (None, "", 0, "0"):
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise StundenplanFehler("Ungültige Auswahl.")


def _wochentag(wert):
    try:
        tag = int(wert)
    except (TypeError, ValueError):
        tag = 0
    if not 1 <= tag <= SCHULTAGE:
        raise StundenplanFehler("Ungültiger Wochentag.")
    return tag


def montag_von(datum):
    return datum - datetime.timedelta(days=datum.weekday())


# --- Feiertage, Ferien, A/B-Wochen ---

def ostersonntag(jahr):
    """Gregorianischer Ostersonntag (Algorithmus nach Meeus/Jones/Butcher)."""
    a, b, c = jahr % 19, jahr // 100, jahr % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    monat = (h + l_ - 7 * m + 114) // 31
    tag = (h + l_ - 7 * m + 114) % 31 + 1
    return datetime.date(jahr, monat, tag)


def feiertage_rlp(jahr):
    """Gesetzliche Feiertage in Rheinland-Pfalz: {iso-datum: name}."""
    ostern = ostersonntag(jahr)
    tage = lambda n: (ostern + datetime.timedelta(days=n)).isoformat()   # noqa: E731
    return {
        "%d-01-01" % jahr: "Neujahr", tage(-2): "Karfreitag", tage(1): "Ostermontag", "%d-05-01" % jahr: "Tag der Arbeit",
        tage(39): "Christi Himmelfahrt", tage(50): "Pfingstmontag", tage(60): "Fronleichnam",
        "%d-10-03" % jahr: "Tag der Deutschen Einheit", "%d-11-01" % jahr: "Allerheiligen",
        "%d-12-25" % jahr: "1. Weihnachtstag", "%d-12-26" % jahr: "2. Weihnachtstag",
    }


def freie_tage(con, von, bis):
    """Unterrichtsfreie Tage zwischen von und bis (je einschliesslich): {iso-datum: name}. Feiertage gehen vor Ferien."""
    frei = {}
    for f in con.execute("SELECT name, von, bis FROM ferien WHERE von <= ? AND bis >= ? ORDER BY von",
                         (bis.isoformat(), von.isoformat())):
        tag = max(von, datetime.date.fromisoformat(f["von"]))
        ende = min(bis, datetime.date.fromisoformat(f["bis"]))
        while tag <= ende:
            frei.setdefault(tag.isoformat(), f["name"])
            tag += datetime.timedelta(days=1)
    for jahr in range(von.year, bis.year + 1):
        for iso, name in feiertage_rlp(jahr).items():
            if von.isoformat() <= iso <= bis.isoformat():
                frei[iso] = name
    return frei


def a_woche_regel(con):
    return db.einstellung(con, "a_woche", "ungerade")


def a_woche_setzen(con, regel):
    if regel not in ("ungerade", "gerade"):
        raise StundenplanFehler("Bitte „ungerade“ oder „gerade“ wählen.")
    db.einstellung_setzen(con, "a_woche", regel)


def ab_woche(datum, regel):
    """'A' oder 'B' fuer die Kalenderwoche von datum."""
    ungerade = datum.isocalendar()[1] % 2 == 1
    return "A" if ungerade == (regel == "ungerade") else "B"


# --- Zeitraster und Klassen ---

def _klassen(con):
    return {k["id"]: k for k in grunddaten.klassen(con)}


def raster_der_klasse(con, klasse_id, _cache=None):
    """Bloecke, die fuer die Klasse gelten (Raster ihres Bildungsgangs, sonst das der Schule)."""
    zeile = con.execute("SELECT bildungsgang_id FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    if zeile is None:
        raise StundenplanFehler("Diese Klasse gibt es nicht.")
    if _cache is not None:
        if zeile["bildungsgang_id"] not in _cache:
            _cache[zeile["bildungsgang_id"]] = grunddaten.zeitraster(con, zeile["bildungsgang_id"])
        return _cache[zeile["bildungsgang_id"]]
    return grunddaten.zeitraster(con, zeile["bildungsgang_id"])


def _block_der_klasse(con, klasse_id, beginn, ende=None):
    """Der Block der Klasse, der um beginn anfaengt (und, wenn angegeben, um ende endet)."""
    for b in raster_der_klasse(con, klasse_id):
        if b["beginn"] == beginn and (ende is None or b["ende"] == ende):
            return b
    raise StundenplanFehler("Diesen Block gibt es im Zeitraster dieser Klasse nicht.")


def zeitraster_zeilen(con, zusaetzlich=()):
    """Zeilen fuer Stundenplan und Wochenplan nach Uhrzeit: Schulraster, eigene Raster der Bildungsgaenge mit aktiven
    Klassen und zusaetzliche Zeiten [(beginn, ende)], die in keinem Raster (mehr) stehen."""
    zeilen = {}
    for b in grunddaten.zeitraster(con, None):
        zeilen[(b["beginn"], b["ende"])] = {"beginn": b["beginn"], "ende": b["ende"], "bezeichnung": b["bezeichnung"], "raster": ""}
    for bg in con.execute("SELECT DISTINCT b.id, b.kuerzel, b.name FROM bildungsgang b JOIN klasse k ON k.bildungsgang_id = b.id "
                          "WHERE k.aktiv = 1 ORDER BY b.reihenfolge, b.name"):
        for b in grunddaten.zeitraster(con, bg["id"], eigenes=True):
            zeilen.setdefault((b["beginn"], b["ende"]), {"beginn": b["beginn"], "ende": b["ende"], "bezeichnung": b["bezeichnung"],
                                                         "raster": bg["kuerzel"] or bg["name"]})
    for beginn, ende in zusaetzlich:
        zeilen.setdefault((beginn, ende), {"beginn": beginn, "ende": ende, "bezeichnung": "", "raster": "", "fremd": True})
    return sorted(zeilen.values(), key=lambda z: (z["beginn"], z["ende"]))


def farben(klassen_ids, klassen):
    """Feste Farbe je Klasse: nach Namen sortiert der Reihe nach aus FARBEN."""
    namen = sorted({k for k in klassen_ids if k in klassen}, key=lambda k: klassen[k]["name"])
    return {k: FARBEN[i % len(FARBEN)] for i, k in enumerate(namen)}


# --- Versionen und Eintraege ---

def _version(con, lid, vid):
    zeile = con.execute("SELECT * FROM stundenplan_version WHERE id = ? AND lehrkraft_id = ?", (vid, lid)).fetchone()
    if zeile is None:
        raise StundenplanFehler("Diese Version gibt es nicht.")
    return zeile


def versionen(con, lid):
    """Alle Versionen der Lehrkraft (aelteste zuerst) mit ihren Eintraegen."""
    liste = []
    for v in con.execute("SELECT * FROM stundenplan_version WHERE lehrkraft_id = ? ORDER BY ab", (lid,)).fetchall():
        eintraege = [{"id": e["id"], "wochentag": e["wochentag"], "beginn": e["beginn"], "ende": e["ende"],
                      "klasse_id": e["klasse_id"], "gruppe_id": e["gruppe_id"], "lernfeld_id": e["lernfeld_id"], "woche": e["woche"]}
                     for e in con.execute("SELECT * FROM stundenplan_eintrag WHERE version_id = ? ORDER BY wochentag, beginn, woche",
                                          (v["id"],))]
        liste.append({"id": v["id"], "ab": v["ab"], "name": v["name"], "eintraege": eintraege})
    for i, v in enumerate(liste):
        nach = liste[i + 1]["ab"] if i + 1 < len(liste) else None
        v["bis"] = (datetime.date.fromisoformat(nach) - datetime.timedelta(days=1)).isoformat() if nach else None
    return liste


def gueltige_version(liste, datum):
    """Die Version, die am Datum gilt (liste aufsteigend nach ab), oder None."""
    gefunden = None
    for v in liste:
        if v["ab"] <= datum.isoformat():
            gefunden = v
    return gefunden


def version_anlegen(con, lid, daten):
    """Neue Version ab einem Datum, leer oder als Kopie einer eigenen Version (kopie_von)."""
    ab = _datum(daten.get("ab"), "das Datum, ab dem die Version gilt").isoformat()
    name = _text(daten.get("name"), 60)
    if con.execute("SELECT 1 FROM stundenplan_version WHERE lehrkraft_id = ? AND ab = ?", (lid, ab)).fetchone():
        raise StundenplanFehler("Ab diesem Datum gibt es schon eine Version.")
    quelle = _id(daten.get("kopie_von"))
    if quelle is not None:
        _version(con, lid, quelle)
    vid = con.execute("INSERT INTO stundenplan_version (lehrkraft_id, ab, name, erstellt) VALUES (?, ?, ?, ?)",
                      (lid, ab, name, db.jetzt())).lastrowid
    if quelle is not None:
        con.execute("INSERT INTO stundenplan_eintrag (version_id, wochentag, beginn, ende, klasse_id, gruppe_id, lernfeld_id, woche) "
                    "SELECT ?, wochentag, beginn, ende, klasse_id, gruppe_id, lernfeld_id, woche FROM stundenplan_eintrag "
                    "WHERE version_id = ?", (vid, quelle))
    return vid


def version_aendern(con, lid, vid, daten):
    _version(con, lid, vid)
    ab = _datum(daten.get("ab"), "das Datum, ab dem die Version gilt").isoformat()
    if con.execute("SELECT 1 FROM stundenplan_version WHERE lehrkraft_id = ? AND ab = ? AND id != ?", (lid, ab, vid)).fetchone():
        raise StundenplanFehler("Ab diesem Datum gibt es schon eine Version.")
    con.execute("UPDATE stundenplan_version SET ab = ?, name = ? WHERE id = ?", (ab, _text(daten.get("name"), 60), vid))


def version_loeschen(con, lid, vid):
    _version(con, lid, vid)
    con.execute("DELETE FROM stundenplan_version WHERE id = ?", (vid,))


def _ueberschneidet(b1, e1, b2, e2):
    return b1 < e2 and b2 < e1


def feld_setzen(con, lid, vid, daten):
    """Setzt einen Block eines Wochentags: eintraege = [] (frei), [{klasse_id, gruppe_id, woche: 'alle'}] oder je eine Klasse
    fuer A und/oder B. gruppe_id leer = ganze Klasse. Die Uhrzeiten muessen im Zeitraster jeder gewaehlten Klasse stehen."""
    _version(con, lid, vid)
    tag = _wochentag(daten.get("wochentag"))
    beginn, ende = _uhrzeit(daten.get("beginn"), "den Beginn"), _uhrzeit(daten.get("ende"), "das Ende")
    eintraege = daten.get("eintraege") or []
    if not isinstance(eintraege, list) or len(eintraege) > 2:
        raise StundenplanFehler("Ungültige Einträge.")
    saubere = []
    for e in eintraege:
        if not isinstance(e, dict):
            raise StundenplanFehler("Ungültige Einträge.")
        kid, woche = _id(e.get("klasse_id")), e.get("woche") or "alle"
        if kid is None:
            continue
        if woche not in WOCHEN:
            raise StundenplanFehler("Ungültige Woche.")
        k = con.execute("SELECT name, aktiv FROM klasse WHERE id = ?", (kid,)).fetchone()
        if k is None:
            raise StundenplanFehler("Diese Klasse gibt es nicht.")
        try:
            _block_der_klasse(con, kid, beginn, ende)
        except StundenplanFehler:
            raise StundenplanFehler("%s hat laut Zeitraster keinen Block %s–%s." % (k["name"], beginn, ende))
        saubere.append((kid, woche, _gruppe_pruefen(con, lid, kid, e.get("gruppe_id")), _lernfeld_pruefen(con, kid, e.get("lernfeld_id"))))
    wochen = [x[1] for x in saubere]
    if len(saubere) == 2 and sorted(wochen) != ["A", "B"]:
        raise StundenplanFehler("Zwei Klassen in einem Block gehen nur als A- und B-Woche.")
    # andere Bloecke desselben Tages, die sich zeitlich ueberschneiden (z. B. anderes Raster), sind nicht erlaubt
    for alt in con.execute("SELECT e.beginn, e.ende, e.woche, k.name FROM stundenplan_eintrag e JOIN klasse k ON k.id = e.klasse_id "
                           "WHERE e.version_id = ? AND e.wochentag = ? AND e.beginn != ?", (vid, tag, beginn)):
        for _, w, _, _ in saubere:
            if _ueberschneidet(beginn, ende, alt["beginn"], alt["ende"]) and ("alle" in (w, alt["woche"]) or w == alt["woche"]):
                raise StundenplanFehler("Der Block überschneidet sich mit %s (%s–%s)." % (alt["name"], alt["beginn"], alt["ende"]))
    con.execute("DELETE FROM stundenplan_eintrag WHERE version_id = ? AND wochentag = ? AND beginn = ?", (vid, tag, beginn))
    for kid, woche, gid, lfid in saubere:
        con.execute("INSERT INTO stundenplan_eintrag (version_id, wochentag, beginn, ende, klasse_id, gruppe_id, lernfeld_id, woche) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (vid, tag, beginn, ende, kid, gid, lfid, woche))


def tag_kopieren(con, lid, vid, von, nach):
    """Ersetzt alle Bloecke des Tages nach durch die des Tages von (innerhalb einer Version)."""
    _version(con, lid, vid)
    von, nach = _wochentag(von), _wochentag(nach)
    if von == nach:
        raise StundenplanFehler("Bitte zwei verschiedene Tage wählen.")
    con.execute("DELETE FROM stundenplan_eintrag WHERE version_id = ? AND wochentag = ?", (vid, nach))
    con.execute("INSERT INTO stundenplan_eintrag (version_id, wochentag, beginn, ende, klasse_id, gruppe_id, lernfeld_id, woche) "
                "SELECT version_id, ?, beginn, ende, klasse_id, gruppe_id, lernfeld_id, woche FROM stundenplan_eintrag "
                "WHERE version_id = ? AND wochentag = ?",
                (nach, vid, von))


# --- Gruppen einer Klasse (je Lehrkraft) ---

def gruppen(con, lid):
    """Eigene Gruppen: [{id, klasse_id, name}], je Klasse in Reihenfolge."""
    return [dict(g) for g in con.execute("SELECT id, klasse_id, name FROM gruppe WHERE lehrkraft_id = ? "
                                         "ORDER BY klasse_id, reihenfolge, name", (lid,))]


def _gruppe_pruefen(con, lid, kid, gid):
    """gid leer = ganze Klasse; sonst muss die Gruppe der Lehrkraft gehoeren und zur Klasse passen."""
    gid = _id(gid)
    if gid is None:
        return None
    if con.execute("SELECT 1 FROM gruppe WHERE id = ? AND lehrkraft_id = ? AND klasse_id = ?", (gid, lid, kid)).fetchone() is None:
        raise StundenplanFehler("Diese Gruppe gehört nicht zur Klasse.")
    return gid


def _lernfeld_pruefen(con, kid, lfid):
    """Optionales Lernfeld eines Blocks (Spur in der Planung): muss zum Bildungsgang der Klasse gehoeren."""
    lfid = _id(lfid)
    if lfid is None:
        return None
    if con.execute("SELECT 1 FROM lernfeld l JOIN klasse k ON k.bildungsgang_id = l.bildungsgang_id WHERE l.id = ? AND k.id = ?",
                   (lfid, kid)).fetchone() is None:
        raise StundenplanFehler("Das Lernfeld gehört nicht zum Bildungsgang der Klasse.")
    return lfid


def gruppe_speichern(con, lid, daten, gid=None):
    name = _text(daten.get("name"), 20)
    if not name:
        raise StundenplanFehler("Bitte einen Namen angeben (z. B. Gr. 1).")
    if gid is None:
        kid = _id(daten.get("klasse_id"))
        if kid is None or con.execute("SELECT 1 FROM klasse WHERE id = ?", (kid,)).fetchone() is None:
            raise StundenplanFehler("Bitte eine Klasse wählen.")
    else:
        zeile = con.execute("SELECT klasse_id FROM gruppe WHERE id = ? AND lehrkraft_id = ?", (gid, lid)).fetchone()
        if zeile is None:
            raise StundenplanFehler("Diese Gruppe gibt es nicht.")
        kid = zeile["klasse_id"]
    if con.execute("SELECT 1 FROM gruppe WHERE lehrkraft_id = ? AND klasse_id = ? AND name = ? AND id != ?",
                   (lid, kid, name, gid or -1)).fetchone():
        raise StundenplanFehler("Die Gruppe %s gibt es in dieser Klasse schon." % name)
    if gid is None:
        reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM gruppe WHERE lehrkraft_id = ? AND klasse_id = ?",
                            (lid, kid)).fetchone()[0]
        return con.execute("INSERT INTO gruppe (lehrkraft_id, klasse_id, name, reihenfolge) VALUES (?, ?, ?, ?)",
                           (lid, kid, name, reihe)).lastrowid
    con.execute("UPDATE gruppe SET name = ? WHERE id = ?", (name, gid))
    return gid


def gruppe_loeschen(con, lid, gid):
    if con.execute("SELECT 1 FROM gruppe WHERE id = ? AND lehrkraft_id = ?", (gid, lid)).fetchone() is None:
        raise StundenplanFehler("Diese Gruppe gibt es nicht.")
    if con.execute("SELECT 1 FROM stundenplan_eintrag WHERE gruppe_id = ? UNION SELECT 1 FROM aenderung WHERE gruppe_id = ? "
                   "UNION SELECT 1 FROM plan_thema WHERE gruppe_id = ? UNION SELECT 1 FROM ist WHERE gruppe_id = ?",
                   (gid, gid, gid, gid)).fetchone():
        raise StundenplanFehler("Die Gruppe steht noch im Stundenplan, in einer Änderung oder in der Planung. Bitte dort zuerst entfernen.")
    con.execute("DELETE FROM gruppe WHERE id = ?", (gid,))


# --- Was an einem Tag stattfindet ---

def _regulaere_stunden(con, lid, datum, liste=None, regel=None, frei=None):
    """Regulaere Stunden laut Grundstundenplan an einem Datum (ohne Aenderungen): [eintrag, ...]."""
    liste = versionen(con, lid) if liste is None else liste
    if datum.isoweekday() > SCHULTAGE:
        return []
    frei = freie_tage(con, datum, datum) if frei is None else frei
    if datum.isoformat() in frei:
        return []
    v = gueltige_version(liste, datum)
    if v is None:
        return []
    ab = ab_woche(datum, regel or a_woche_regel(con))
    return [e for e in v["eintraege"] if e["wochentag"] == datum.isoweekday() and e["woche"] in ("alle", ab)]


def _aenderungen(con, lid, von, bis):
    return [dict(a) for a in con.execute(
        "SELECT * FROM aenderung WHERE lehrkraft_id = ? AND ((datum BETWEEN ? AND ?) OR (ziel_datum BETWEEN ? AND ?)) ORDER BY datum, beginn",
        (lid, von.isoformat(), bis.isoformat(), von.isoformat(), bis.isoformat()))]


def _belegung(con, lid, datum):
    """Was ich an einem Datum tatsaechlich halte: [(beginn, ende, klassenname, aenderung_id oder None)]."""
    belegt = []
    aend = _aenderungen(con, lid, datum, datum)
    weg = {a["beginn"] for a in aend if a["datum"] == datum.isoformat() and a["art"] in ("ausfall", "vertreten", "verschoben")}
    namen = {k["id"]: k["name"] for k in grunddaten.klassen(con)}
    for e in _regulaere_stunden(con, lid, datum):
        if e["beginn"] not in weg:
            belegt.append((e["beginn"], e["ende"], namen.get(e["klasse_id"], "?"), None))
    for a in aend:
        if a["art"] in ("vertretung", "zusatz") and a["datum"] == datum.isoformat():
            belegt.append((a["beginn"], a["ende"], namen.get(a["klasse_id"]) or a["klasse_text"] or "Vertretung", a["id"]))
        elif a["art"] == "verschoben" and a["ziel_datum"] == datum.isoformat():
            belegt.append((a["ziel_beginn"], a["ziel_ende"], namen.get(a["klasse_id"], "?"), a["id"]))
    return belegt


def _frei_pruefen(con, lid, datum, beginn, ende):
    for b, e, name, _ in _belegung(con, lid, datum):
        if _ueberschneidet(beginn, ende, b, e):
            raise StundenplanFehler("Am %s um %s hast du schon Unterricht (%s)." % (_tag_text(datum), b, name))


def _tag_text(datum):
    return "%s %s" % (WOCHENTAGE[datum.weekday()] if datum.weekday() < 6 else "So", datum.strftime("%d.%m."))


# --- Einmalige Aenderungen ---

def aenderung_anlegen(con, lid, daten):
    art = daten.get("art")
    if art not in AENDERUNGEN:
        raise StundenplanFehler("Unbekannte Änderung.")
    datum = _datum(daten.get("datum"))
    beginn = _uhrzeit(daten.get("beginn"), "den Block")
    grund, wer = _text(daten.get("grund")), _text(daten.get("wer"), 80)
    werte = {"art": art, "datum": datum.isoformat(), "beginn": beginn, "klasse_id": None, "gruppe_id": None, "klasse_text": "",
             "ziel_datum": None,
             "ziel_beginn": None, "ziel_ende": None, "wer": wer, "grund": grund}

    if art in ("ausfall", "vertreten", "verschoben"):
        stunde = next((e for e in _regulaere_stunden(con, lid, datum) if e["beginn"] == beginn), None)
        if stunde is None:
            raise StundenplanFehler("Laut Stundenplan hast du am %s um %s keinen Unterricht." % (_tag_text(datum), beginn))
        if con.execute("SELECT 1 FROM aenderung WHERE lehrkraft_id = ? AND datum = ? AND beginn = ? AND art IN "
                       "('ausfall', 'vertreten', 'verschoben')", (lid, datum.isoformat(), beginn)).fetchone():
            raise StundenplanFehler("Für diese Stunde ist schon eine Änderung eingetragen. Bitte zuerst zurücknehmen.")
        werte.update(ende=stunde["ende"], klasse_id=stunde["klasse_id"], gruppe_id=stunde["gruppe_id"])
        if art == "vertreten":   # keine Vorauswahl: die Lehrkraft entscheidet jedes Mal
            weiter = daten.get("thema_weiter")
            if weiter not in (True, False):
                raise StundenplanFehler("Bitte wählen: Übernimmt die Vertretung dein Thema oder macht sie eigenen Stoff?")
            werte["thema_weiter"] = 1 if weiter else 0
        if art == "verschoben":
            ziel = _datum(daten.get("ziel_datum"), "den neuen Tag")
            ziel_beginn = _uhrzeit(daten.get("ziel_beginn"), "den neuen Block")
            block = _block_der_klasse(con, stunde["klasse_id"], ziel_beginn)
            if ziel == datum and ziel_beginn == beginn:
                raise StundenplanFehler("Der neue Termin ist derselbe wie der alte.")
            if ziel.isoweekday() > SCHULTAGE:
                raise StundenplanFehler("Bitte einen Tag von Montag bis Freitag wählen.")
            frei = freie_tage(con, ziel, ziel).get(ziel.isoformat())
            if frei:
                raise StundenplanFehler("Am %s ist unterrichtsfrei (%s)." % (_tag_text(ziel), frei))
            _frei_pruefen(con, lid, ziel, block["beginn"], block["ende"])
            werte.update(ziel_datum=ziel.isoformat(), ziel_beginn=block["beginn"], ziel_ende=block["ende"])
    else:   # vertretung, zusatz: ein zusaetzlicher Block
        kid = _id(daten.get("klasse_id"))
        if kid is not None:
            block = _block_der_klasse(con, kid, beginn)
            werte["klasse_id"] = kid
            werte["gruppe_id"] = _gruppe_pruefen(con, lid, kid, daten.get("gruppe_id"))
        elif art == "vertretung":
            werte["klasse_text"] = _text(daten.get("klasse_text"), 40)
            if not werte["klasse_text"]:
                raise StundenplanFehler("Bitte die Klasse wählen oder eintragen.")
            block = next((b for b in grunddaten.zeitraster(con, None) if b["beginn"] == beginn), None)
            if block is None:
                block = {"beginn": beginn, "ende": _uhrzeit(daten.get("ende"), "das Ende")}
        else:
            raise StundenplanFehler("Bitte eine Klasse wählen.")
        if datum.isoweekday() > SCHULTAGE:
            raise StundenplanFehler("Bitte einen Tag von Montag bis Freitag wählen.")
        _frei_pruefen(con, lid, datum, block["beginn"], block["ende"])
        werte["ende"] = block["ende"]
    felder = ["lehrkraft_id"] + list(werte) + ["erstellt"]
    return con.execute("INSERT INTO aenderung (%s) VALUES (%s)" % (", ".join(felder), ", ".join("?" * len(felder))),
                       [lid] + list(werte.values()) + [db.jetzt()]).lastrowid


def aenderung_loeschen(con, lid, aid):
    if con.execute("SELECT 1 FROM aenderung WHERE id = ? AND lehrkraft_id = ?", (aid, lid)).fetchone() is None:
        raise StundenplanFehler("Diese Änderung gibt es nicht.")
    con.execute("DELETE FROM aenderung WHERE id = ?", (aid,))


# --- Termine und Merker ---

def termin_speichern(con, lid, daten, tid=None):
    if tid is not None and con.execute("SELECT 1 FROM termin WHERE id = ? AND lehrkraft_id = ?", (tid, lid)).fetchone() is None:
        raise StundenplanFehler("Diesen Termin gibt es nicht.")
    art = daten.get("art") or "dienst"
    if art not in TERMINARTEN:
        raise StundenplanFehler("Unbekannte Terminart.")
    titel = _text(daten.get("titel"), 200)
    if not titel:
        raise StundenplanFehler("Bitte einen Text eingeben." if art == "merker" else "Bitte einen Titel eingeben.")
    datum = _datum(daten.get("datum")).isoformat()
    bis, beginn, ende, kid = None, None, None, None
    if art == "merker":
        beginn = _uhrzeit(daten.get("beginn"), "den Block")
        kid = _id(daten.get("klasse_id"))
        if kid is None:
            raise StundenplanFehler("Ein Merker gehört zu einer Stunde einer Klasse.")
    else:
        if daten.get("bis"):
            bis = _datum(daten.get("bis"), "„bis“").isoformat()
            if bis < datum:
                raise StundenplanFehler("„Bis“ liegt vor dem Beginn.")
            bis = None if bis == datum else bis
        if daten.get("beginn"):
            beginn = _uhrzeit(daten.get("beginn"), "die Uhrzeit")
            if daten.get("ende"):
                ende = _uhrzeit(daten.get("ende"), "das Ende")
                if ende <= beginn:
                    raise StundenplanFehler("Das Ende muss nach dem Beginn liegen.")
    werte = (art, datum, bis, beginn, ende, kid, titel, _text(daten.get("notiz"), 2000))
    if tid is None:
        return con.execute("INSERT INTO termin (lehrkraft_id, art, datum, bis, beginn, ende, klasse_id, titel, notiz, erstellt) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (lid,) + werte + (db.jetzt(),)).lastrowid
    con.execute("UPDATE termin SET art = ?, datum = ?, bis = ?, beginn = ?, ende = ?, klasse_id = ?, titel = ?, notiz = ? WHERE id = ?",
                werte + (tid,))
    return tid


def termin_loeschen(con, lid, tid):
    if con.execute("SELECT 1 FROM termin WHERE id = ? AND lehrkraft_id = ?", (tid, lid)).fetchone() is None:
        raise StundenplanFehler("Diesen Termin gibt es nicht.")
    con.execute("DELETE FROM termin WHERE id = ?", (tid,))


def _termine(con, lid, von, bis):
    return [dict(t) for t in con.execute(
        "SELECT id, art, datum, bis, beginn, ende, klasse_id, titel, notiz FROM termin WHERE lehrkraft_id = ? "
        "AND datum <= ? AND COALESCE(bis, datum) >= ? ORDER BY datum, COALESCE(beginn, ''), id",
        (lid, bis.isoformat(), von.isoformat()))]


# --- Wochenplan ---

def woche(con, lid, montag, jetzt=None):
    """Alles fuer den Wochenplan einer Lehrkraft: Tage (mit frei/heute), Zeilen nach Uhrzeit, Bloecke mit Zustand,
    Termine und Merker. jetzt: ISO-Zeit (Vorgabe: db.jetzt())."""
    montag = montag_von(montag)
    freitag = montag + datetime.timedelta(days=SCHULTAGE - 1)
    jetzt = jetzt or db.jetzt()
    heute, uhr = jetzt[:10], jetzt[11:16]
    liste = versionen(con, lid)
    regel = a_woche_regel(con)
    frei = freie_tage(con, montag, freitag)
    klassen = _klassen(con)
    aend = _aenderungen(con, lid, montag, freitag)
    termine = _termine(con, lid, montag, freitag)
    merker = [t for t in termine if t["art"] == "merker"]
    weg = {(a["datum"], a["beginn"]): a for a in aend if a["art"] in ("ausfall", "vertreten", "verschoben")}
    eigene_gruppen = gruppen(con, lid)
    gruppennamen = {g["id"]: g["name"] for g in eigene_gruppen}

    def klasse(kid):
        k = klassen.get(kid)
        return {"id": k["id"], "name": k["name"], "bildungsgang": k["bildungsgang"], "stufe": k["stufe"]} if k else None

    def block(datum, beginn, ende, kid, art, gid=None, **mehr):
        b = {"datum": datum, "beginn": beginn, "ende": ende, "klasse": klasse(kid), "art": art, "zustand": None,
             "gruppe": {"id": gid, "name": gruppennamen.get(gid, "?")} if gid else None,
             "merker": [{"id": m["id"], "text": m["titel"]} for m in merker
                        if m["datum"] == datum and m["beginn"] == beginn and (kid is None or m["klasse_id"] == kid)]}
        b.update(mehr)
        return b

    bloecke, tage = [], []
    for i in range(SCHULTAGE):
        d = montag + datetime.timedelta(days=i)
        iso = d.isoformat()
        tage.append({"datum": iso, "tag": WOCHENTAGE[i], "frei": frei.get(iso), "heute": iso == heute})
        for e in _regulaere_stunden(con, lid, d, liste, regel, frei):
            b = block(iso, e["beginn"], e["ende"], e["klasse_id"], "regulaer", e["gruppe_id"], woche=e["woche"])
            a = weg.get((iso, e["beginn"]))
            if a:
                b.update(zustand=a["art"], aenderung_id=a["id"], grund=a["grund"], wer=a["wer"], thema_weiter=bool(a["thema_weiter"]),
                         ziel={"datum": a["ziel_datum"], "beginn": a["ziel_beginn"]} if a["art"] == "verschoben" else None)
            bloecke.append(b)
    for a in aend:
        if a["art"] in ("vertretung", "zusatz") and montag.isoformat() <= a["datum"] <= freitag.isoformat():
            bloecke.append(block(a["datum"], a["beginn"], a["ende"], a["klasse_id"], a["art"], a["gruppe_id"], aenderung_id=a["id"],
                                 grund=a["grund"], wer=a["wer"], klasse_text=a["klasse_text"]))
        elif a["art"] == "verschoben" and a["ziel_datum"] and montag.isoformat() <= a["ziel_datum"] <= freitag.isoformat():
            bloecke.append(block(a["ziel_datum"], a["ziel_beginn"], a["ziel_ende"], a["klasse_id"], "verschoben", a["gruppe_id"],
                                 aenderung_id=a["id"],
                                 grund=a["grund"], herkunft={"datum": a["datum"], "beginn": a["beginn"]}))
    for b in bloecke:
        b["jetzt"] = b["datum"] == heute and b["beginn"] <= uhr < b["ende"] and b["zustand"] is None
    bloecke.sort(key=lambda b: (b["datum"], b["beginn"]))

    # Zeilen: Schulraster, Raster der Klassen dieser Woche bzw. der gueltigen Version, und Zeiten ausserhalb jedes Rasters
    zeiten = {(b["beginn"], b["ende"]) for b in bloecke}
    v = gueltige_version(liste, montag) or (liste[-1] if liste else None)
    benutzt = {e["klasse_id"] for e in (v["eintraege"] if v else [])} | {b["klasse"]["id"] for b in bloecke if b["klasse"]}
    rasterzeiten = set()
    cache = {}
    for kid in benutzt:
        if kid in klassen:
            rasterzeiten |= {(r["beginn"], r["ende"]) for r in raster_der_klasse(con, kid, cache)}
    schule = {(r["beginn"], r["ende"]) for r in grunddaten.zeitraster(con, None)}
    zeilen = [z for z in zeitraster_zeilen(con, zeiten)
              if (z["beginn"], z["ende"]) in schule | rasterzeiten | zeiten]
    alle_klassen = {e["klasse_id"] for v in liste for e in v["eintraege"]} | benutzt
    return {
        "montag": montag.isoformat(), "kw": montag.isocalendar()[1], "ab": ab_woche(montag, regel), "heute": heute,
        "tage": tage, "zeilen": zeilen, "bloecke": bloecke,
        "termine": [t for t in termine if t["art"] != "merker"], "merker": merker,
        "farben": {str(k): f for k, f in farben(alle_klassen, klassen).items()},
        "hat_stundenplan": bool(liste),
        "klassen": [{"id": k["id"], "name": k["name"],
                     "bloecke": [r["beginn"] + "-" + r["ende"] for r in raster_der_klasse(con, k["id"], cache)]}
                    for k in klassen.values() if k["aktiv"]],
        "gruppen": eigene_gruppen,
    }


# --- Stundenplan-Editor ---

def editor(con, lid, heute=None):
    """Alles fuer den Editor: Versionen, Klassen mit ihren Blockzeiten, Zeilen, A/B dieser Woche."""
    heute = heute or db.heute()
    liste = versionen(con, lid)
    klassen = _klassen(con)
    cache = {}
    # am Wochenende zaehlt schon die kommende Woche (wie im Wochenplan)
    woche_von = heute + datetime.timedelta(days=8 - heute.isoweekday()) if heute.isoweekday() > SCHULTAGE else heute
    klassen_liste = [{"id": k["id"], "name": k["name"], "bildungsgang": k["bildungsgang"], "bildungsgang_id": k["bildungsgang_id"],
                      "stufe": k["stufe"], "aktiv": k["aktiv"],
                      "bloecke": [r["beginn"] + "-" + r["ende"] for r in raster_der_klasse(con, k["id"], cache)]}
                     for k in klassen.values()]
    zeiten = {(e["beginn"], e["ende"]) for v in liste for e in v["eintraege"]}
    jetzt_gueltig = gueltige_version(liste, heute)
    lernfelder = sorted((dict(z) for z in con.execute("SELECT id, bildungsgang_id, nummer, name FROM lernfeld WHERE aktiv = 1")),
                        key=lambda l: (l["bildungsgang_id"], grunddaten.natuerlich(l["nummer"])))
    return {"versionen": liste, "klassen": klassen_liste, "gruppen": gruppen(con, lid), "lernfelder": lernfelder,
            "zeilen": zeitraster_zeilen(con, zeiten),
            "farben": {str(k): f for k, f in farben({e["klasse_id"] for v in liste for e in v["eintraege"]}, klassen).items()},
            "ab": ab_woche(woche_von, a_woche_regel(con)), "ab_naechste": woche_von != heute, "a_woche": a_woche_regel(con),
            "heute": heute.isoformat(),
            "gilt_jetzt": jetzt_gueltig["id"] if jetzt_gueltig else None}


# --- Zeitraster geaendert: Eintraege nachziehen ---

def raster_vorher(con):
    """Merkt sich je Klasse ihr wirksames Raster (vor einer Aenderung durch den Admin)."""
    cache = {}
    return {kid: list(raster_der_klasse(con, kid, cache)) for kid in _klassen(con)}


def raster_nachziehen(con, vorher):
    """Nach einer Raster-Aenderung: Bloecke, die gleich heissen, aber andere Zeiten haben, in Stundenplaenen (alle
    Versionen) sowie in heutigen und kuenftigen Aenderungen und Merkern auf die neuen Zeiten setzen."""
    nachher = raster_vorher(con)
    heute = db.heute().isoformat()
    for kid, alt in vorher.items():
        neu = {b["bezeichnung"]: b for b in nachher.get(kid, [])}
        umzug = [(a, neu[a["bezeichnung"]]) for a in alt
                 if a["bezeichnung"] in neu and (a["beginn"], a["ende"]) != (neu[a["bezeichnung"]]["beginn"], neu[a["bezeichnung"]]["ende"])]
        if not umzug:
            continue
        fall_b = "CASE beginn " + " ".join("WHEN '%s' THEN '%s'" % (a["beginn"], n["beginn"]) for a, n in umzug) + " ELSE beginn END"
        fall_e = "CASE beginn " + " ".join("WHEN '%s' THEN '%s'" % (a["beginn"], n["ende"]) for a, n in umzug) + " ELSE ende END"
        alte = "(%s)" % ", ".join("'%s'" % a["beginn"] for a, _ in umzug)   # nur HH:MM aus der Pruefung, kein Fremdtext
        try:
            con.execute("UPDATE stundenplan_eintrag SET ende = %s, beginn = %s WHERE klasse_id = ? AND beginn IN %s"
                        % (fall_e, fall_b, alte), (kid,))
            con.execute("UPDATE aenderung SET ende = %s, beginn = %s WHERE klasse_id = ? AND datum >= ? AND beginn IN %s"
                        % (fall_e, fall_b, alte), (kid, heute))
            con.execute("UPDATE aenderung SET ziel_ende = %s, ziel_beginn = %s WHERE klasse_id = ? AND ziel_datum >= ? AND ziel_beginn IN %s"
                        % (fall_e.replace("beginn", "ziel_beginn").replace("ende", "ziel_ende"),
                           fall_b.replace("beginn", "ziel_beginn"), alte), (kid, heute))
            con.execute("UPDATE termin SET beginn = %s WHERE art = 'merker' AND klasse_id = ? AND datum >= ? AND beginn IN %s"
                        % (fall_b, alte), (kid, heute))
        except sqlite3.IntegrityError:
            raise grunddaten.GrunddatenFehler("Die neuen Zeiten passen nicht zu bestehenden Stundenplänen (zwei Blöcke würden "
                                              "zusammenfallen). Bitte die Zeiten in kleineren Schritten ändern.")


def klasse_benutzt(con, kid):
    return bool(con.execute("SELECT 1 FROM stundenplan_eintrag WHERE klasse_id = ? UNION SELECT 1 FROM aenderung WHERE klasse_id = ?",
                            (kid, kid)).fetchone())
