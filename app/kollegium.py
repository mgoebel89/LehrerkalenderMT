"""Teilen im Kollegium (Stufe E).

Geteilt wird nur zwischen Lehrkraeften, die dieselbe Klasse laut ihrem Stundenplan unterrichten:
  - Termine der Klasse: ein dienstlicher Termin mit Klasse, ausdruecklich als "geteilt" markiert. Die anderen sehen
    ihn im Wochenplan und in der Stunde, aendern kann ihn nur, wer ihn eingetragen hat.
  - Planung: die ganze Themenplanung einer Klasse, nur zum Lesen, dazu der Unterrichtsinhalt der gehaltenen Stunden
    (Text fuers Klassenbuch) und Notizen einer Stunde, wenn dort der Haken "fuer das Kollegium sichtbar" gesetzt ist.
Noten, andere Notizen, Merker, private Termine und Besuchsprotokolle bleiben immer privat. Die Schuelerliste
ist seit 0.24.0 ohnehin je Klasse gemeinsam (app/schuelerliste.py, gilt auch ohne diesen Schalter).

Der Admin schaltet das Teilen unter Admin > System ein (Vorgabe: aus), sobald Schulleitung und Datenschutz zugestimmt
haben. Solange es aus ist, sieht niemand etwas von anderen.

"Unterrichtet" eine Klasse: sie steht in einer Stundenplan-Version, die heute oder spaeter gilt.
"""
import datetime

from . import db, grunddaten, stundenplan

SCHLUESSEL = "kollegium_teilen"
VORSCHAU_TAGE = 56          # Klassenansicht: geteilte Termine der naechsten acht Wochen


class KollegiumFehler(Exception):
    pass


def aktiv(con):
    return db.einstellung(con, SCHLUESSEL, "0") == "1"


def setzen(con, an):
    db.einstellung_setzen(con, SCHLUESSEL, "1" if an else "0")


def klassen_von(con, lid, heute=None):
    """Klassen, die die Lehrkraft unterrichtet (Stundenplan-Versionen, die heute oder spaeter gelten)."""
    heute = (heute or db.heute()).isoformat()
    ids = set()
    for v in stundenplan.versionen(con, lid):
        if (v["bis"] or "9999-12-31") >= heute:
            ids.update(e["klasse_id"] for e in v["eintraege"])
    return ids


def lehrkraefte_der_klasse(con, kid, heute=None):
    """Alle nicht gesperrten Lehrkraefte, die die Klasse unterrichten: [{id, kuerzel, name}] nach Name."""
    kandidaten = con.execute(
        "SELECT DISTINCT l.id, l.kuerzel, l.name FROM lehrkraft l JOIN stundenplan_version v ON v.lehrkraft_id = l.id "
        "JOIN stundenplan_eintrag e ON e.version_id = v.id WHERE e.klasse_id = ? AND l.gesperrt = 0 ORDER BY l.name", (kid,)).fetchall()
    return [dict(z) for z in kandidaten if kid in klassen_von(con, z["id"], heute)]


def meine_klassen(con, lid):
    """Fuer den Termin-Dialog: Klassen, fuer die ich Termine teilen kann. Leer, wenn das Teilen aus ist."""
    if not aktiv(con):
        return []
    ids = klassen_von(con, lid)
    return sorted(({"id": k["id"], "name": k["name"]} for k in grunddaten.klassen(con) if k["id"] in ids), key=lambda k: k["name"])


def teilen_pruefen(con, lid, kid):
    """Einen Termin teilen darf, wer die Klasse selbst unterrichtet."""
    if kid is None:
        raise KollegiumFehler("Zum Teilen bitte eine Klasse wählen.")
    if kid not in klassen_von(con, lid):
        raise KollegiumFehler("Teilen geht nur für Klassen, die du laut Stundenplan unterrichtest.")


def kollege(con, lid, andere, kid):
    """Planung einer anderen Lehrkraft fuer eine Klasse lesen: Teilen an, beide unterrichten die Klasse.
    Gibt {id, kuerzel, name} der anderen Lehrkraft zurueck."""
    if not aktiv(con):
        raise KollegiumFehler("Teilen im Kollegium ist nicht eingeschaltet.")
    z = con.execute("SELECT id, kuerzel, name FROM lehrkraft WHERE id = ? AND gesperrt = 0", (andere,)).fetchone()
    if z is None or andere == lid or kid is None or kid not in klassen_von(con, lid) or kid not in klassen_von(con, andere):
        raise KollegiumFehler("Diese Planung kannst du nicht sehen: Ihr müsst die Klasse beide laut Stundenplan unterrichten.")
    return dict(z)


def gemeinsame_klassen(con, lid, andere):
    return klassen_von(con, lid) & klassen_von(con, andere)


_SPALTEN = ("SELECT t.id, t.art, t.datum, t.bis, t.beginn, t.ende, t.klasse_id, t.titel, t.notiz, t.lehrkraft_id, "
            "l.name AS von_name, l.kuerzel AS von_kuerzel FROM termin t JOIN lehrkraft l ON l.id = t.lehrkraft_id "
            "WHERE t.geteilt = 1 AND t.art = 'dienst' ")


def _mit_klasse(con, zeilen, lid):
    namen = {k["id"]: k["name"] for k in grunddaten.klassen(con)}
    return [dict(z, klasse=namen.get(z["klasse_id"], ""), geteilt=True, fremd=z["lehrkraft_id"] != lid) for z in zeilen]


def geteilte_termine(con, lid, von, bis):
    """Geteilte Klassentermine ANDERER Lehrkraefte fuer meine Klassen im Zeitraum (nur lesen)."""
    if not aktiv(con):
        return []
    klassen = sorted(klassen_von(con, lid))
    if not klassen:
        return []
    zeilen = con.execute(_SPALTEN + "AND t.lehrkraft_id != ? AND t.klasse_id IN (%s) AND t.datum <= ? AND COALESCE(t.bis, t.datum) >= ? "
                         "ORDER BY t.datum, COALESCE(t.beginn, ''), t.id" % ",".join("?" * len(klassen)),
                         [lid] + klassen + [bis.isoformat(), von.isoformat()]).fetchall()
    return _mit_klasse(con, zeilen, lid)


def klasse_uebersicht(con, lid, kid, heute=None):
    """Klassenansicht in der Planung: wer die Klasse unterrichtet und die geteilten Termine der naechsten Wochen
    (von allen, auch meine). None, wenn das Teilen aus ist oder ich die Klasse nicht unterrichte."""
    heute = heute or db.heute()
    if not aktiv(con) or kid not in klassen_von(con, lid, heute):
        return None
    leute = [dict(l, ich=l["id"] == lid) for l in lehrkraefte_der_klasse(con, kid, heute)]
    bis = heute + datetime.timedelta(days=VORSCHAU_TAGE)
    zeilen = con.execute(_SPALTEN + "AND t.klasse_id = ? AND t.datum <= ? AND COALESCE(t.bis, t.datum) >= ? "
                         "ORDER BY t.datum, COALESCE(t.beginn, ''), t.id", (kid, bis.isoformat(), heute.isoformat())).fetchall()
    return {"lehrkraefte": leute, "termine": _mit_klasse(con, zeilen, lid), "tage": VORSCHAU_TAGE}


def unterricht(con, andere, kid, gid, von, bis, bloecke=(), themen=()):
    """Fuer die lesende Planung: Unterrichtsinhalte der gehaltenen Stunden der anderen Lehrkraft in dieser Klasse (bei
    einer Gruppe: deren Stunden und die der ganzen Klasse), neueste zuerst. Notizen nur, wenn sie geteilt sind."""
    gnamen = {g["id"]: g["name"] for g in stundenplan.gruppen(con, andere)}
    titel = {t["id"]: t["titel"] for t in themen}
    thema = {(b["datum"], b["beginn"]): titel.get(b.get("thema_id")) for b in bloecke}
    zeilen = con.execute(
        "SELECT datum, beginn, gruppe_id, inhalt, CASE WHEN notizen_geteilt = 1 THEN notizen ELSE '' END AS notizen "
        "FROM stunde_eintrag WHERE lehrkraft_id = ? AND klasse_id = ? AND datum BETWEEN ? AND ? "
        "AND (inhalt != '' OR (notizen_geteilt = 1 AND notizen != '')) "
        + ("AND COALESCE(gruppe_id, 0) IN (0, ?) " if gid else "") + "ORDER BY datum DESC, beginn DESC",
        (andere, kid, von.isoformat(), bis.isoformat()) + ((gid,) if gid else ())).fetchall()
    return [{"datum": z["datum"], "beginn": z["beginn"], "gruppe": gnamen.get(z["gruppe_id"], "") if z["gruppe_id"] else "",
             "thema": thema.get((z["datum"], z["beginn"])) or "", "inhalt": z["inhalt"], "notizen": z["notizen"]} for z in zeilen]


def admin_stand(con):
    """Fuer Admin > System: Schalter und welche Klassen mehrere Lehrkraefte haben."""
    klassen = []
    for k in grunddaten.klassen(con):
        if not k["aktiv"]:
            continue
        leute = lehrkraefte_der_klasse(con, k["id"])
        if len(leute) > 1:
            klassen.append({"klasse": k["name"], "lehrkraefte": [l["name"] for l in leute]})
    return {"an": aktiv(con), "klassen": sorted(klassen, key=lambda x: x["klasse"])}
