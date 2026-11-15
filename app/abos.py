"""Kalender-Abos (ICS-Links), abgerufen vom Container.

  Schule (vom Admin, lehrkraft_id leer):
    art 'ferien'   ganztaegige Termine werden zu Ferien (ersetzen bei jedem Abruf die Ferien dieses Abos)
    art 'termine'  Schultermine (Konferenzen, paedagogische Tage ...), fuer alle Lehrkraefte im Wochenplan sichtbar
  Eigene (je Lehrkraft, z. B. der veroeffentlichte Outlook-Kalender): nur fuer die Lehrkraft sichtbar.

Abgerufen wird regelmaessig im Hintergrund (server.main) und auf Knopfdruck. Wiederkehrende Termine werden fuer ein
Fenster um heute aufgeloest (recurring_ical_events). Erlaubt sind nur http(s)- und webcal-Links, nicht auf den
Container selbst; Groesse und Wartezeit sind begrenzt.
"""
import datetime
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from . import db

try:
    import icalendar
    import recurring_ical_events
except ImportError:   # ohne Pakete: Abos lassen sich anlegen, der Abruf meldet den Fehler
    icalendar = recurring_ical_events = None

MAX_GROESSE = 5 * 1024 * 1024
WARTEZEIT = 20
FENSTER_ZURUECK = 120         # Tage vor heute
FENSTER_VOR = 450             # Tage nach heute
ARTEN = ("ferien", "termine")


class AboFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


# --- Abos verwalten ---

def _abo(con, aid):
    zeile = con.execute("SELECT * FROM kalender_abo WHERE id = ?", (aid,)).fetchone()
    if zeile is None:
        raise AboFehler("Dieses Abo gibt es nicht.")
    return zeile


def _darf(konto, abo):
    if abo["lehrkraft_id"] is None:
        if konto["rolle"] != "admin":
            raise AboFehler("Abos der Schule verwaltet der Admin.")
    elif abo["lehrkraft_id"] != konto["id"]:
        raise AboFehler("Dieses Abo gibt es nicht.")


def url_pruefen(url):
    """Normalisiert und prueft einen Abo-Link: webcal -> https, nur http(s), kein Zugriff auf den Container selbst."""
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    teile = urllib.parse.urlsplit(url)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        raise AboFehler("Bitte einen Abo-Link angeben, der mit https:// (oder webcal://) beginnt.")
    if len(url) > 2000:
        raise AboFehler("Der Link ist zu lang.")
    return url


def _ziel_erlaubt(host):
    """Kein Abruf von localhost/Link-local (Schutz vor Missbrauch des Containers als Sprungbrett)."""
    try:
        adressen = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except OSError:
        raise AboFehler("Der Server %s ist nicht erreichbar (Name unbekannt)." % host)
    for a in adressen:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise AboFehler("Dieser Link zeigt auf eine nicht erlaubte Adresse.")


def liste(con, konto, schule=False):
    """Eigene Abos bzw. (schule=True) die der Schule."""
    if schule:
        zeilen = con.execute("SELECT * FROM kalender_abo WHERE lehrkraft_id IS NULL ORDER BY art, name")
    else:
        zeilen = con.execute("SELECT * FROM kalender_abo WHERE lehrkraft_id = ? ORDER BY name", (konto["id"],))
    return [{"id": z["id"], "art": z["art"], "name": z["name"], "url": z["url"], "aktiv": bool(z["aktiv"]), "abgerufen": z["abgerufen"],
             "fehler": z["fehler"], "anzahl": z["anzahl"], "schule": z["lehrkraft_id"] is None} for z in zeilen]


def speichern(con, konto, daten, aid=None):
    name = (daten.get("name") or "").strip()[:60]
    if not name:
        raise AboFehler("Bitte einen Namen angeben (z. B. Outlook dienstlich).")
    url = url_pruefen(daten.get("url"))
    aktiv = 0 if daten.get("aktiv") is False else 1
    if aid is not None:
        abo = _abo(con, aid)
        _darf(konto, abo)
        con.execute("UPDATE kalender_abo SET name = ?, url = ?, aktiv = ? WHERE id = ?", (name, url, aktiv, aid))
        return aid
    schule = bool(daten.get("schule"))
    if schule and konto["rolle"] != "admin":
        raise AboFehler("Abos der Schule legt der Admin an.")
    art = daten.get("art") if schule else "termine"
    if art not in ARTEN:
        raise AboFehler("Bitte wählen: Ferien oder Termine.")
    return con.execute("INSERT INTO kalender_abo (lehrkraft_id, art, name, url, aktiv, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                       (None if schule else konto["id"], art, name, url, aktiv, db.jetzt())).lastrowid


def loeschen(con, konto, aid):
    abo = _abo(con, aid)
    _darf(konto, abo)
    con.execute("DELETE FROM kalender_abo WHERE id = ?", (aid,))   # Termine und Ferien des Abos gehen mit


# --- Abrufen und Auswerten ---

def laden(url):
    """Holt den Inhalt eines Abo-Links (Bytes)."""
    teile = urllib.parse.urlsplit(url)
    _ziel_erlaubt(teile.hostname)
    anfrage = urllib.request.Request(url, headers={"User-Agent": "LehrerkalenderMT (Kalender-Abo)", "Accept": "text/calendar, */*"})
    try:
        with urllib.request.urlopen(anfrage, timeout=WARTEZEIT) as antwort:
            inhalt = antwort.read(MAX_GROESSE + 1)
    except urllib.error.HTTPError as f:
        raise AboFehler("Der Server antwortet mit Fehler %d." % f.code)
    except (urllib.error.URLError, OSError) as f:
        grund = getattr(f, "reason", f)
        if isinstance(grund, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(grund):
            raise AboFehler("Das Zertifikat des Kalender-Servers lässt sich nicht prüfen. Bitte den Link kontrollieren.")
        if isinstance(grund, (socket.timeout, TimeoutError)) or "timed out" in str(grund):
            raise AboFehler("Der Kalender-Server antwortet nicht (Zeitüberschreitung).")
        if isinstance(grund, socket.gaierror):
            raise AboFehler("Den Kalender-Server gibt es nicht (Name unbekannt).")
        raise AboFehler("Abruf nicht möglich: %s" % grund)
    if len(inhalt) > MAX_GROESSE:
        raise AboFehler("Der Kalender ist zu groß (mehr als 5 MB).")
    return inhalt


def _ortszeit(wert):
    """datetime (mit oder ohne Zeitzone) -> naive Ortszeit Berlin."""
    if wert.tzinfo is not None and db.ZONE is not None:
        return wert.astimezone(db.ZONE).replace(tzinfo=None)
    return wert.replace(tzinfo=None)


def auswerten(inhalt, heute=None):
    """ICS-Inhalt -> Termine [{titel, datum, bis, beginn, ende, ort, ganztags}] im Fenster um heute (Wiederholungen
    aufgeloest). Ganztaegige: bis = letzter Tag (DTEND ist im ICS exklusiv)."""
    if icalendar is None:
        raise AboFehler("Auf dem Server fehlen die Pakete python3-icalendar und python3-recurring-ical-events.")
    try:
        kal = icalendar.Calendar.from_ical(inhalt)
    except Exception:
        raise AboFehler("Der Link liefert keinen gültigen Kalender (ICS).")
    heute = heute or db.heute()
    von = heute - datetime.timedelta(days=FENSTER_ZURUECK)
    bis = heute + datetime.timedelta(days=FENSTER_VOR)
    try:
        ereignisse = recurring_ical_events.of(kal).between(von, bis)
    except Exception:
        raise AboFehler("Die Termine des Kalenders lassen sich nicht auswerten.")
    termine = []
    for e in ereignisse:
        start = e.get("DTSTART")
        if start is None:
            continue
        s = start.dt
        ende = e.get("DTEND").dt if e.get("DTEND") is not None else None
        titel = str(e.get("SUMMARY") or "(ohne Titel)").strip()[:200]
        ort = str(e.get("LOCATION") or "").strip()[:200]
        if isinstance(s, datetime.datetime):
            s = _ortszeit(s)
            en = _ortszeit(ende) if isinstance(ende, datetime.datetime) else s
            gleich = en.date() == s.date() or (en.date() == s.date() + datetime.timedelta(days=1) and en.time() == datetime.time(0, 0))
            termine.append({"titel": titel, "ort": ort, "ganztags": False, "datum": s.date().isoformat(),
                            "bis": None if gleich else en.date().isoformat(),
                            "beginn": s.strftime("%H:%M"), "ende": en.strftime("%H:%M") if gleich and en > s else None})
        else:   # ganztaegig
            letzter = (ende - datetime.timedelta(days=1)) if isinstance(ende, datetime.date) and ende > s else s
            termine.append({"titel": titel, "ort": ort, "ganztags": True, "datum": s.isoformat(),
                            "bis": letzter.isoformat() if letzter != s else None, "beginn": None, "ende": None})
    termine.sort(key=lambda t: (t["datum"], t["beginn"] or ""))
    return termine


def abrufen(con, aid, inhalt=None, heute=None):
    """Ein Abo abrufen (oder mit inhalt auswerten) und Termine bzw. Ferien ersetzen. Fehler landen am Abo.
    Rueckgabe: Anzahl der Termine; wirft AboFehler mit der Meldung."""
    abo = _abo(con, aid)
    try:
        termine = auswerten(inhalt if inhalt is not None else laden(abo["url"]), heute)
    except AboFehler as f:
        with db.transaktion(con):
            con.execute("UPDATE kalender_abo SET abgerufen = ?, fehler = ? WHERE id = ?", (db.jetzt(), str(f), aid))
        raise
    with db.transaktion(con):
        con.execute("DELETE FROM abo_termin WHERE abo_id = ?", (aid,))
        con.execute("DELETE FROM ferien WHERE abo_id = ?", (aid,))
        if abo["art"] == "ferien":
            # nur ganztaegige Eintraege sind Ferien (z. B. "Herbstferien 12.10.-23.10.")
            termine = [t for t in termine if t["ganztags"]]
            for t in termine:
                con.execute("INSERT INTO ferien (name, von, bis, quelle, abo_id) VALUES (?, ?, ?, 'abo', ?)",
                            (t["titel"][:80], t["datum"], t["bis"] or t["datum"], aid))
        else:
            for t in termine:
                con.execute("INSERT INTO abo_termin (abo_id, titel, datum, bis, beginn, ende, ort) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (aid, t["titel"], t["datum"], t["bis"], t["beginn"], t["ende"], t["ort"]))
        con.execute("UPDATE kalender_abo SET abgerufen = ?, fehler = '', anzahl = ? WHERE id = ?", (db.jetzt(), len(termine), aid))
    return len(termine)


def alle_abrufen(db_pfad):
    """Alle aktiven Abos abrufen (Hintergrund). Fehler je Abo stehen danach am Abo."""
    con = db.verbinden(db_pfad)
    try:
        for z in con.execute("SELECT id FROM kalender_abo WHERE aktiv = 1").fetchall():
            try:
                abrufen(con, z["id"])
            except AboFehler:
                pass
            except Exception as f:   # nie den Hintergrund-Thread beenden
                print("Abo %d: %r" % (z["id"], f), flush=True)
    finally:
        con.close()


def termine(con, lid, von, bis):
    """Abo-Termine fuer den Wochenplan: Schultermine (alle) und eigene Abos, die den Zeitraum beruehren."""
    return [dict(z) for z in con.execute(
        "SELECT t.id, t.titel, t.datum, t.bis, t.beginn, t.ende, t.ort, a.name AS quelle, "
        "CASE WHEN a.lehrkraft_id IS NULL THEN 'schule' ELSE 'abo' END AS art "
        "FROM abo_termin t JOIN kalender_abo a ON a.id = t.abo_id "
        "WHERE a.aktiv = 1 AND a.art = 'termine' AND (a.lehrkraft_id IS NULL OR a.lehrkraft_id = ?) "
        "AND t.datum <= ? AND COALESCE(t.bis, t.datum) >= ? ORDER BY t.datum, COALESCE(t.beginn, ''), t.titel",
        (lid, bis.isoformat(), von.isoformat()))]
