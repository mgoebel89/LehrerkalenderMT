"""Lehrkraft-Konten (aus TrackingDRS und Lernbuero MT uebernommen): Passwoerter (PBKDF2), Anmeldung per signiertem
Cookie, Sperre gegen Passwort-Raten, Einrichtungscode fuer das erste Admin-Konto. Neu im Lehrerkalender: Konten
entstehen ueber Einladungscodes, und jede Lehrkraft kann einen zweiten Faktor (Authenticator-App) einschalten.

Cookie-Inhalt: <id>.<ablauf>.<stand>.<signatur>. `stand` steigt bei Passwortwechsel und Sperre, damit alle
bestehenden Anmeldungen ungueltig werden. Abmelden merkt sich die Signatur bis zum Ablauf.
Mit zweitem Faktor gibt die Passwortpruefung nur einen kurzlebigen Zwischenschein (<id>.<ablauf>.<stand>.2f.<signatur>)
zurueck; erst der Code aus der App macht daraus eine Anmeldung.
"""
import datetime
import hashlib
import hmac
import json
import re
import secrets
import time

from . import db, totp

SITZUNG_S = 10 * 3600
ITERATIONEN = 200_000
MIN_PASSWORT = 8
ROLLEN = ("admin", "lehrkraft")
KUERZEL = re.compile(r"[a-z0-9]{2,8}")
FEHLVERSUCHE = 5          # danach ist die Anmeldung von diesem Rechner eine Weile gesperrt
SPERRE_S = 60             # jede weitere Sperre doppelt so lang ...
SPERRE_MAX_S = 15 * 60    # ... aber hoechstens so lang


class KontoFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


def _hash(passwort, salz, iterationen=ITERATIONEN):
    return hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), bytes.fromhex(salz), iterationen).hex()


def passwort_hash(passwort):
    if len(passwort or "") < MIN_PASSWORT:
        raise KontoFehler("Das Passwort braucht mindestens %d Zeichen." % MIN_PASSWORT)
    if len(passwort) > 100:
        raise KontoFehler("Das Passwort ist zu lang.")
    salz = secrets.token_hex(16)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONEN, salz, _hash(passwort, salz))


def passwort_stimmt(gespeichert, passwort):
    try:
        _verfahren, iterationen, salz, soll = gespeichert.split("$")
        return hmac.compare_digest(_hash(passwort or "", salz, int(iterationen)), soll)
    except ValueError:
        return False


def _geheimnis(con):
    wert = db.einstellung(con, "sitzung_geheimnis")
    if wert is None:
        wert = secrets.token_hex(32)
        db.einstellung_setzen(con, "sitzung_geheimnis", wert)
    return wert


def oeffentlich(zeile):
    return {"id": zeile["id"], "kuerzel": zeile["kuerzel"], "name": zeile["name"], "rolle": zeile["rolle"],
            "pw_vorlaeufig": bool(zeile["pw_vorlaeufig"]), "gesperrt": bool(zeile["gesperrt"]),
            "zweiter_faktor": bool(zeile["totp"]), "ersatzcodes_uebrig": len(json.loads(zeile["ersatzcodes"] or "[]"))}


def _kuerzel_pruefen(kuerzel):
    kuerzel = (kuerzel or "").strip().lower()
    if not KUERZEL.fullmatch(kuerzel):
        raise KontoFehler("Das Kürzel braucht 2 bis 8 Kleinbuchstaben oder Ziffern, z. B. gob.")
    return kuerzel


def _name_pruefen(name):
    name = (name or "").strip()
    if not 2 <= len(name) <= 80:
        raise KontoFehler("Bitte einen Namen mit 2 bis 80 Zeichen angeben.")
    return name


def hat_konten(con):
    return con.execute("SELECT 1 FROM lehrkraft LIMIT 1").fetchone() is not None


def liste(con):
    return [oeffentlich(z) for z in con.execute("SELECT * FROM lehrkraft ORDER BY name")]


def holen(con, lehrkraft_id):
    zeile = con.execute("SELECT * FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    return oeffentlich(zeile) if zeile else None


def anlegen(con, kuerzel, name, rolle, passwort, vorlaeufig=True):
    kuerzel = _kuerzel_pruefen(kuerzel)
    name = _name_pruefen(name)
    if rolle not in ROLLEN:
        raise KontoFehler("Unbekannte Rolle.")
    pw = passwort_hash(passwort)
    if con.execute("SELECT 1 FROM lehrkraft WHERE kuerzel = ?", (kuerzel,)).fetchone():
        raise KontoFehler("Das Kürzel %s ist schon vergeben." % kuerzel)
    cur = con.execute("INSERT INTO lehrkraft (kuerzel, name, rolle, pw, pw_vorlaeufig, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                      (kuerzel, name, rolle, pw, 1 if vorlaeufig else 0, db.jetzt()))
    return holen(con, cur.lastrowid)


def _aktive_admins(con, ohne=None):
    return con.execute("SELECT COUNT(*) FROM lehrkraft WHERE rolle = 'admin' AND gesperrt = 0 AND id != ?",
                       (ohne or -1,)).fetchone()[0]


def aendern(con, lehrkraft_id, name=None, rolle=None, gesperrt=None):
    k = holen(con, lehrkraft_id)
    if k is None:
        raise KontoFehler("Dieses Konto gibt es nicht.")
    if rolle is not None and rolle not in ROLLEN:
        raise KontoFehler("Unbekannte Rolle.")
    wird_admin_los = (rolle == "lehrkraft" or gesperrt) and k["rolle"] == "admin"
    if wird_admin_los and _aktive_admins(con, ohne=lehrkraft_id) == 0:
        raise KontoFehler("Das ist der letzte aktive Admin. Lege zuerst einen weiteren Admin an.")
    if name is not None:
        con.execute("UPDATE lehrkraft SET name = ? WHERE id = ?", (_name_pruefen(name), lehrkraft_id))
    if rolle is not None:
        con.execute("UPDATE lehrkraft SET rolle = ? WHERE id = ?", (rolle, lehrkraft_id))
    if gesperrt is not None:
        # sperren beendet alle Anmeldungen (stand + 1)
        con.execute("UPDATE lehrkraft SET gesperrt = ?, stand = stand + ? WHERE id = ?",
                    (1 if gesperrt else 0, 1 if gesperrt else 0, lehrkraft_id))
    return holen(con, lehrkraft_id)


def passwort_setzen(con, lehrkraft_id, passwort, vorlaeufig):
    pw = passwort_hash(passwort)
    con.execute("UPDATE lehrkraft SET pw = ?, pw_vorlaeufig = ?, stand = stand + 1 WHERE id = ?",
                (pw, 1 if vorlaeufig else 0, lehrkraft_id))


def passwort_aendern(con, lehrkraft_id, alt, neu):
    zeile = con.execute("SELECT pw FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    if zeile is None or not passwort_stimmt(zeile["pw"], alt):
        raise KontoFehler("Das bisherige Passwort stimmt nicht.")
    if alt == neu:
        raise KontoFehler("Das neue Passwort muss sich vom bisherigen unterscheiden.")
    passwort_setzen(con, lehrkraft_id, neu, vorlaeufig=False)


# --- Anmeldung ---

def _signatur(con, text):
    return hmac.new(bytes.fromhex(_geheimnis(con)), text.encode(), hashlib.sha256).hexdigest()


def sitzung_erzeugen(con, lehrkraft_id, uhr=None):
    stand = con.execute("SELECT stand FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()[0]
    ablauf = int((time.time() if uhr is None else uhr) + SITZUNG_S)
    text = "%d.%d.%d" % (lehrkraft_id, ablauf, stand)
    return "%s.%s" % (text, _signatur(con, text))


ZWISCHEN_S = 5 * 60   # so lange gilt der Zwischenschein fuer den zweiten Faktor


def _passwort_pruefen(con, kuerzel, passwort):
    zeile = con.execute("SELECT * FROM lehrkraft WHERE kuerzel = ?", ((kuerzel or "").strip().lower(),)).fetchone()
    # auch bei unbekanntem Kuerzel rechnen, damit die Antwortzeit nichts verraet
    stimmt = passwort_stimmt(zeile["pw"] if zeile else "pbkdf2_sha256$%d$00$00" % ITERATIONEN, passwort)
    if zeile is None or not stimmt:
        raise KontoFehler("Kürzel oder Passwort stimmt nicht.")
    if zeile["gesperrt"]:
        raise KontoFehler("Dieses Konto ist gesperrt.")
    return zeile


def anmelden(con, kuerzel, passwort, uhr=None):
    """Prueft Kuerzel und Passwort. Rueckgabe: (Cookie-Wert, Kontoangaben, None) oder, wenn der zweite Faktor an ist,
    (None, Kontoangaben, Zwischenschein)."""
    zeile = _passwort_pruefen(con, kuerzel, passwort)
    if zeile["totp"]:
        ablauf = int((time.time() if uhr is None else uhr) + ZWISCHEN_S)
        text = "%d.%d.%d.2f" % (zeile["id"], ablauf, zeile["stand"])
        return None, oeffentlich(zeile), "%s.%s" % (text, _signatur(con, text))
    return sitzung_erzeugen(con, zeile["id"], uhr), oeffentlich(zeile), None


def zweiter_schritt(con, zwischenschein, eingabe, uhr=None):
    """Zwischenschein + Code aus der App (oder ein Ersatzcode). Rueckgabe: (Cookie-Wert, Kontoangaben)."""
    try:
        lid, ablauf, stand, marke, signatur = (zwischenschein or "").split(".")
        if marke != "2f" or not hmac.compare_digest(signatur, _signatur(con, "%s.%s.%s.2f" % (lid, ablauf, stand))):
            raise ValueError
        zeile = con.execute("SELECT * FROM lehrkraft WHERE id = ?", (int(lid),)).fetchone()
        if zeile is None or zeile["gesperrt"] or int(stand) != zeile["stand"]:
            raise ValueError
        if int(ablauf) < (time.time() if uhr is None else uhr):
            raise KontoFehler("Die Anmeldung hat zu lange gedauert. Bitte noch einmal mit Passwort beginnen.")
    except ValueError:
        raise KontoFehler("Bitte noch einmal mit Passwort beginnen.")
    zaehler = totp.pruefen(zeile["totp"], eingabe, zeile["totp_zuletzt"], uhr)
    if zaehler is not None:
        con.execute("UPDATE lehrkraft SET totp_zuletzt = ? WHERE id = ?", (zaehler, zeile["id"]))
    else:
        rest = totp.ersatzcode_einloesen(json.loads(zeile["ersatzcodes"] or "[]"), eingabe)
        if rest is None:
            raise KontoFehler("Der Code stimmt nicht.")
        con.execute("UPDATE lehrkraft SET ersatzcodes = ? WHERE id = ?", (json.dumps(rest), zeile["id"]))
    return sitzung_erzeugen(con, zeile["id"], uhr), holen(con, zeile["id"])


# --- Zweiter Faktor einrichten ---

def totp_einschalten(con, lehrkraft_id, geheimnis, eingabe, uhr=None):
    """Speichert das Geheimnis, wenn der erste Code aus der App passt. Rueckgabe: Ersatzcodes im Klartext (nur jetzt
    sichtbar)."""
    zeile = con.execute("SELECT * FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    if zeile["totp"]:
        raise KontoFehler("Der zweite Faktor ist schon eingeschaltet.")
    try:
        zaehler = totp.pruefen(geheimnis, eingabe, 0, uhr)
    except (ValueError, TypeError):
        zaehler = None
    if zaehler is None:
        raise KontoFehler("Der Code passt nicht. Bitte den aktuellen Code aus der App eingeben.")
    klar, summen = totp.ersatzcodes_neu()
    con.execute("UPDATE lehrkraft SET totp = ?, totp_zuletzt = ?, ersatzcodes = ? WHERE id = ?",
                (geheimnis, zaehler, json.dumps(summen), lehrkraft_id))
    return klar


def totp_ausschalten(con, lehrkraft_id, passwort):
    zeile = con.execute("SELECT pw FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    if not passwort_stimmt(zeile["pw"], passwort):
        raise KontoFehler("Das Passwort stimmt nicht.")
    con.execute("UPDATE lehrkraft SET totp = '', totp_zuletzt = 0, ersatzcodes = '[]' WHERE id = ?", (lehrkraft_id,))


def totp_zuruecksetzen(con, lehrkraft_id):
    """Fuer den Admin, wenn jemand sein Handy verloren hat."""
    if holen(con, lehrkraft_id) is None:
        raise KontoFehler("Dieses Konto gibt es nicht.")
    con.execute("UPDATE lehrkraft SET totp = '', totp_zuletzt = 0, ersatzcodes = '[]' WHERE id = ?", (lehrkraft_id,))


def ersatzcodes_erneuern(con, lehrkraft_id):
    zeile = con.execute("SELECT totp FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    if not zeile["totp"]:
        raise KontoFehler("Der zweite Faktor ist nicht eingeschaltet.")
    klar, summen = totp.ersatzcodes_neu()
    con.execute("UPDATE lehrkraft SET ersatzcodes = ? WHERE id = ?", (json.dumps(summen), lehrkraft_id))
    return klar


def sitzung_pruefen(con, token, uhr=None):
    """Kontoangaben zur Anmeldung im Cookie, oder None."""
    try:
        lid, ablauf, stand, signatur = (token or "").split(".")
        zeile = con.execute("SELECT * FROM lehrkraft WHERE id = ?", (int(lid),)).fetchone()
        if zeile is None or zeile["gesperrt"]:
            return None
        if int(ablauf) < (time.time() if uhr is None else uhr) or int(stand) != zeile["stand"]:
            return None
        if not hmac.compare_digest(signatur, _signatur(con, "%s.%s.%s" % (lid, ablauf, stand))):
            return None
        if con.execute("SELECT 1 FROM abgemeldet WHERE signatur = ?", (signatur,)).fetchone():
            return None
    except ValueError:
        return None
    return oeffentlich(zeile)


def abmelden(con, token, uhr=None):
    """Beendet diese Anmeldung, auch wenn jemand das Cookie kopiert hat."""
    if sitzung_pruefen(con, token, uhr) is None:
        return
    _lid, ablauf, _stand, signatur = token.split(".")
    con.execute("DELETE FROM abgemeldet WHERE ablauf < ?", (int(time.time() if uhr is None else uhr),))
    con.execute("INSERT OR IGNORE INTO abgemeldet (signatur, ablauf) VALUES (?, ?)", (signatur, int(ablauf)))


# --- Einrichtung: erstes Admin-Konto ---

def einrichtungscode(con):
    """Code fuer /einrichtung, solange es noch kein Konto gibt (sonst None). Wird beim ersten Aufruf erzeugt."""
    if hat_konten(con):
        return None
    code = db.einstellung(con, "einrichtungscode")
    if code is None:
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        db.einstellung_setzen(con, "einrichtungscode", code)
    return code


def einrichten(con, code, kuerzel, name, passwort):
    soll = einrichtungscode(con)
    if soll is None:
        raise KontoFehler("Die Einrichtung ist schon abgeschlossen. Bitte anmelden.")
    if not hmac.compare_digest((code or "").strip().upper(), soll):
        raise KontoFehler("Der Einrichtungscode stimmt nicht.")
    konto = anlegen(con, kuerzel, name, "admin", passwort, vorlaeufig=False)
    con.execute("DELETE FROM einstellung WHERE schluessel = 'einrichtungscode'")
    return konto


# --- Einladungen: so entstehen alle weiteren Konten ---

EINLADUNG_TAGE = (1, 60)   # erlaubte Gueltigkeit in Tagen


def _einladung(zeile, heute):
    return {"id": zeile["id"], "code": zeile["code"], "rolle": zeile["rolle"], "gueltig_bis": zeile["gueltig_bis"],
            "notiz": zeile["notiz"], "erstellt": zeile["erstellt"], "eingeloest": zeile["eingeloest"],
            "eingeloest_von": zeile["eingeloest_name"],
            "stand": "eingeloest" if zeile["eingeloest"] else ("abgelaufen" if zeile["gueltig_bis"] < heute else "offen")}


def einladungen(con):
    heute = db.heute().isoformat()
    zeilen = con.execute("SELECT e.*, l.name AS eingeloest_name FROM einladung e "
                         "LEFT JOIN lehrkraft l ON l.id = e.eingeloest_von ORDER BY e.erstellt DESC, e.id DESC LIMIT 50")
    return [_einladung(z, heute) for z in zeilen]


def einladung_anlegen(con, rolle, tage, notiz, von_id):
    if rolle not in ROLLEN:
        raise KontoFehler("Unbekannte Rolle.")
    try:
        tage = int(tage)
    except (TypeError, ValueError):
        raise KontoFehler("Bitte die Gültigkeit in Tagen angeben.")
    if not EINLADUNG_TAGE[0] <= tage <= EINLADUNG_TAGE[1]:
        raise KontoFehler("Eine Einladung gilt %d bis %d Tage." % EINLADUNG_TAGE)
    notiz = (notiz or "").strip()[:80]
    while True:
        code = "KAL-%s-%s" % (secrets.token_hex(2).upper(), secrets.token_hex(2).upper())
        if not con.execute("SELECT 1 FROM einladung WHERE code = ?", (code,)).fetchone():
            break
    bis = (db.heute() + datetime.timedelta(days=tage)).isoformat()
    cur = con.execute("INSERT INTO einladung (code, rolle, gueltig_bis, notiz, erstellt, erstellt_von) VALUES (?, ?, ?, ?, ?, ?)",
                      (code, rolle, bis, notiz, db.jetzt(), von_id))
    return [e for e in einladungen(con) if e["id"] == cur.lastrowid][0]


def einladung_zurueckziehen(con, einladung_id):
    zeile = con.execute("SELECT eingeloest FROM einladung WHERE id = ?", (einladung_id,)).fetchone()
    if zeile is None:
        raise KontoFehler("Diese Einladung gibt es nicht.")
    if zeile["eingeloest"]:
        raise KontoFehler("Die Einladung wurde schon eingelöst.")
    con.execute("DELETE FROM einladung WHERE id = ?", (einladung_id,))


def einladung_pruefen(con, code):
    """Offene, gueltige Einladung zum Code, sonst KontoFehler."""
    code = (code or "").strip().upper()
    if not code.startswith("KAL-"):
        code = "KAL-" + code
    zeile = con.execute("SELECT * FROM einladung WHERE code = ?", (code,)).fetchone()
    if zeile is None:
        raise KontoFehler("Den Einladungscode gibt es nicht.")
    if zeile["eingeloest"]:
        raise KontoFehler("Dieser Einladungscode wurde schon benutzt.")
    if zeile["gueltig_bis"] < db.heute().isoformat():
        raise KontoFehler("Dieser Einladungscode ist abgelaufen. Bitte beim Admin einen neuen holen.")
    return zeile


def einladung_einloesen(con, code, kuerzel, name, passwort):
    zeile = einladung_pruefen(con, code)
    konto = anlegen(con, kuerzel, name, zeile["rolle"], passwort, vorlaeufig=False)
    con.execute("UPDATE einladung SET eingeloest = ?, eingeloest_von = ? WHERE id = ?", (db.jetzt(), konto["id"], zeile["id"]))
    return konto


class Sperre:
    """Bremst Passwort-Raten: nach FEHLVERSUCHE Fehlern von einem Rechner SPERRE_S Pause, jede weitere Sperre doppelt
    so lang (hoechstens SPERRE_MAX_S), bis eine Anmeldung von dort klappt."""

    def __init__(self, uhr=time.time):
        self.uhr = uhr
        self.rechner = {}   # Adresse -> (Fehlversuche, gesperrt bis, Anzahl Sperren bisher)

    def wartezeit(self, adresse):
        return max(0.0, self.rechner.get(adresse, (0, 0.0, 0))[1] - self.uhr())

    def fehlversuch(self, adresse):
        """Zaehlt einen Fehlversuch. Rueckgabe: Dauer der jetzt beginnenden Sperre in s, sonst 0."""
        fehler, _bis, stufe = self.rechner.get(adresse, (0, 0.0, 0))
        fehler += 1
        if len(self.rechner) > 1000:   # alte Eintraege vergessen
            grenze = self.uhr() - SPERRE_MAX_S
            self.rechner = {a: e for a, e in self.rechner.items() if e[1] > grenze}
        if fehler < FEHLVERSUCHE:
            self.rechner[adresse] = (fehler, 0.0, stufe)
            return 0
        dauer = min(SPERRE_MAX_S, SPERRE_S * 2 ** stufe)
        self.rechner[adresse] = (0, self.uhr() + dauer, stufe + 1)
        return dauer

    def erfolg(self, adresse):
        self.rechner.pop(adresse, None)
