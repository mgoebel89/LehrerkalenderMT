"""Sicherung einspielen (Admin > System): z. B. die Daten der Testinstanz ins Produktivsystem uebernehmen.

Ablauf in drei Schritten, Bauweise wie das Update:
  1. hochladen   Der Webdienst nimmt eine Sicherung an (ZIP aus "Sicherung herunterladen" oder die .sqlite-Datei),
                 prueft sie (lesbar, unversehrt, nicht neuer als dieses Programm, mindestens ein Admin-Konto) und legt sie
                 als <daten>/wiederherstellung/hochgeladen.sqlite bereit. Die Seite zeigt, was darin steht.
  2. anfordern   Mit Passwort bestaetigt: <daten>/wiederherstellung/einspielen (enthaelt die Pruefsumme der Datei).
                 lehrerkalender-wiederherstellen.path startet daraufhin als root deploy/wiederherstellen.sh.
  3. ausfuehren  root stoppt den Dienst und ruft "lehrerkalender wiederherstellung-ausfuehren" auf - das laeuft wieder
                 als Dienstbenutzer, im eigenen Datenordner: Pruefsumme und Datei noch einmal pruefen, den bisherigen
                 Stand sichern (<daten>/sicherungen/vor-wiederherstellung-*.zip), die Datenbank austauschen, migrieren,
                 alle Anmeldungen beenden. Danach startet root den Dienst wieder. root selbst liest die hochgeladene
                 Datei nie: eine manipulierte Datei (z. B. ein Verweis auf eine Systemdatei) bringt ihm also nichts.
Ergebnisse von root in /var/lib/lehrerkalender-wiederherstellung (lauf.json, protokoll.txt), fuer den Webdienst lesbar.
Nicht in der Datenbank und deshalb nicht betroffen: Zertifikat (Stammzertifikat der Geraete bleibt), VPN.
"""
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import stat
import zipfile

from . import VERSION, db, updates

STAND_DIR = os.environ.get("LEHRERKALENDER_WIEDERHERSTELLUNG_DIR", "/var/lib/lehrerkalender-wiederherstellung")
EINHEIT = os.environ.get("LEHRERKALENDER_WIEDERHERSTELLUNG_EINHEIT", "/etc/systemd/system/lehrerkalender-wiederherstellen.path")
MAX_HOCHLADEN = 512 * 1024 * 1024     # Sicherung (ZIP oder .sqlite) beim Hochladen
MAX_ENTPACKT = 2 * 1024 * 1024 * 1024
HOCHGELADEN = "hochgeladen.sqlite"
INFO = "hochgeladen.json"
AUFTRAG = "einspielen"
LAUF_MAX = datetime.timedelta(minutes=15)
SQLITE_KOPF = b"SQLite format 3\x00"


class WiederherstellungFehler(Exception):
    pass


def ordner(daten_dir):
    return os.path.join(daten_dir, "wiederherstellung")


def eingerichtet():
    return os.path.exists(EINHEIT)


def _pruefsumme(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for teil in iter(lambda: f.read(1024 * 1024), b""):
            h.update(teil)
    return h.hexdigest()


def _zahl(con, sql):
    try:
        zeile = con.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    return zeile[0] if zeile else None


def pruefen(pfad):
    """Sicherung (.sqlite) nur lesend pruefen. Rueckgabe: was die Seite vor dem Einspielen zeigt, sonst Fehler."""
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(16)
    except OSError:
        raise WiederherstellungFehler("Die Sicherung lässt sich nicht lesen.") from None
    if kopf != SQLITE_KOPF:
        raise WiederherstellungFehler("Das ist keine Datenbank des Lehrerkalenders.")
    try:
        # immutable: nur lesen, ohne Sperren und ohne -wal/-shm daneben anzulegen (die Datei gehoert uns, niemand schreibt)
        con = sqlite3.connect(pathlib.Path(os.path.abspath(pfad)).as_uri() + "?mode=ro&immutable=1", uri=True)
    except sqlite3.Error:
        raise WiederherstellungFehler("Die Datenbank lässt sich nicht öffnen.") from None
    try:
        try:
            ergebnis = con.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error:
            ergebnis = "Fehler"
        if ergebnis != "ok":
            raise WiederherstellungFehler("Die Datenbank in der Sicherung ist beschädigt (%s)." % str(ergebnis)[:80])
        stand = con.execute("PRAGMA user_version").fetchone()[0]
        tabellen = {z[0] for z in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if stand < 1 or not {"lehrkraft", "einstellung", "protokoll"} <= tabellen:
            raise WiederherstellungFehler("Das ist keine Datenbank des Lehrerkalenders.")
        if stand > len(db.MIGRATIONEN):
            raise WiederherstellungFehler(
                "Die Sicherung stammt aus einer neueren Version (Datenbankstand %d, hier %d). Bitte diesen Lehrerkalender "
                "zuerst aktualisieren (Version und Update), dann die Sicherung einspielen." % (stand, len(db.MIGRATIONEN)))
        admins = [z[0] for z in con.execute("SELECT kuerzel FROM lehrkraft WHERE rolle = 'admin' AND gesperrt = 0 ORDER BY kuerzel")]
        if not admins:
            raise WiederherstellungFehler("In der Sicherung gibt es kein (entsperrtes) Admin-Konto. Danach käme niemand mehr an die "
                                          "Verwaltung, deshalb wird sie nicht eingespielt.")
        letzte = _zahl(con, "SELECT MAX(zeit) FROM protokoll")
        schule = _zahl(con, "SELECT wert FROM einstellung WHERE schluessel = 'schule_name'")
        return {
            "stand": stand, "aktueller_stand": len(db.MIGRATIONEN), "version": VERSION,
            "konten": _zahl(con, "SELECT COUNT(*) FROM lehrkraft"), "admins": admins,
            "klassen": _zahl(con, "SELECT COUNT(*) FROM klasse") if "klasse" in tabellen else None,
            "pruefungen": _zahl(con, "SELECT COUNT(*) FROM pruefung") if "pruefung" in tabellen else None,
            "besuche": _zahl(con, "SELECT COUNT(*) FROM ub_besuch") if "ub_besuch" in tabellen else None,
            "letzte_aenderung": letzte, "schule": schule,
            "groesse": os.path.getsize(pfad),
        }
    finally:
        con.close()


def _entpacken(quelle, ziel):
    """ZIP der Sicherung: genau die Datenbankdatei herausholen, mit Groessengrenze (gepackte Riesendateien)."""
    try:
        z = zipfile.ZipFile(quelle)
    except (zipfile.BadZipFile, OSError):
        raise WiederherstellungFehler("Die ZIP-Datei ist beschädigt.") from None
    with z:
        eintraege = [e for e in z.infolist() if not e.is_dir() and os.path.basename(e.filename) == db.DATEINAME]
        if len(eintraege) != 1:
            raise WiederherstellungFehler("In der ZIP-Datei fehlt %s. Bitte eine Sicherung aus „Sicherung herunterladen“ "
                                          "nehmen." % db.DATEINAME)
        e = eintraege[0]
        if e.file_size > MAX_ENTPACKT:
            raise WiederherstellungFehler("Die Datenbank in der ZIP-Datei ist zu groß.")
        geschrieben = 0
        with z.open(e) as rein, open(ziel, "wb") as raus:
            for teil in iter(lambda: rein.read(1024 * 1024), b""):
                geschrieben += len(teil)
                if geschrieben > MAX_ENTPACKT:
                    raise WiederherstellungFehler("Die Datenbank in der ZIP-Datei ist zu groß.")
                raus.write(teil)


def bereitlegen(quelle, daten_dir):
    """Hochgeladene Datei (ZIP oder .sqlite) pruefen und als hochgeladen.sqlite bereitlegen. Rueckgabe: Angaben."""
    o = ordner(daten_dir)
    os.makedirs(o, mode=0o750, exist_ok=True)
    neu = os.path.join(o, HOCHGELADEN + ".neu")
    try:
        with open(quelle, "rb") as f:
            kopf = f.read(16)
        if kopf.startswith(b"PK"):
            _entpacken(quelle, neu)
        elif kopf == SQLITE_KOPF:
            shutil.copyfile(quelle, neu)
        else:
            raise WiederherstellungFehler("Bitte eine Sicherung als ZIP (aus „Sicherung herunterladen“) oder die Datei %s "
                                          "wählen." % db.DATEINAME)
        angaben = pruefen(neu)
        angaben.update(pruefsumme=_pruefsumme(neu), hochgeladen=db.jetzt())
        os.replace(neu, os.path.join(o, HOCHGELADEN))
    finally:
        if os.path.exists(neu):
            os.remove(neu)
    _schreiben_json(os.path.join(o, INFO), angaben)
    return angaben


def _schreiben_json(pfad, daten):
    with open(pfad + ".neu", "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False)
    os.replace(pfad + ".neu", pfad)


def _lesen_json(pfad):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def hochgeladen(daten_dir):
    info = _lesen_json(os.path.join(ordner(daten_dir), INFO))
    return info if info and os.path.exists(os.path.join(ordner(daten_dir), HOCHGELADEN)) else None


def verwerfen(daten_dir):
    for name in (HOCHGELADEN, INFO, AUFTRAG):
        try:
            os.remove(os.path.join(ordner(daten_dir), name))
        except OSError:
            pass


def _protokoll():
    try:
        with open(os.path.join(STAND_DIR, "protokoll.txt"), encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-200:])
    except OSError:
        return ""


def _laeuft(lauf):
    if not lauf or not lauf.get("beginn") or lauf.get("ende"):
        return False
    try:
        return datetime.datetime.fromisoformat(db.jetzt()) - datetime.datetime.fromisoformat(lauf["beginn"]) < LAUF_MAX
    except ValueError:
        return False


def stand(daten_dir):
    lauf = _lesen_json(os.path.join(STAND_DIR, "lauf.json"))
    return {"eingerichtet": eingerichtet(), "hochgeladen": hochgeladen(daten_dir), "lauf": lauf, "laeuft": _laeuft(lauf),
            "wartet": os.path.exists(os.path.join(ordner(daten_dir), AUFTRAG)), "protokoll": _protokoll()}


def anfordern(daten_dir, pruefsumme):
    """Einspielen beauftragen (das Passwort prueft der Server vorher)."""
    if not eingerichtet():
        raise WiederherstellungFehler("Das Einspielen über die Seite geht nur im Container (nach dem nächsten Update).")
    s = stand(daten_dir)
    if s["laeuft"] or s["wartet"]:
        raise WiederherstellungFehler("Es läuft schon ein Einspielen. Bitte kurz warten.")
    info = s["hochgeladen"]
    if not info:
        raise WiederherstellungFehler("Es liegt keine Sicherung bereit. Bitte zuerst hochladen.")
    if not pruefsumme or pruefsumme != info.get("pruefsumme"):
        raise WiederherstellungFehler("Die bereitliegende Sicherung hat sich geändert. Bitte noch einmal hochladen.")
    _schreiben_json(os.path.join(ordner(daten_dir), AUFTRAG), {"pruefsumme": pruefsumme, "zeit": db.jetzt()})


def _auftrag_lesen(pfad):
    """Auftrag lesen und loeschen; kein Verweis, nur eine kleine regulaere Datei."""
    try:
        fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        roh = os.read(fd, 4096) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    finally:
        os.close(fd)
        try:
            os.unlink(pfad)
        except OSError:
            pass
    try:
        d = json.loads(roh.decode("utf-8"))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def ausfuehren(daten_dir, mit_auftrag=True, ausgabe=print):
    """Als Dienstbenutzer bei gestopptem Dienst: Datenbank gegen die bereitliegende Sicherung tauschen.
    mit_auftrag: nur mit Auftrag aus der Seite (Pruefsumme muss passen); False = von der Konsole."""
    o = ordner(daten_dir)
    quelle = os.path.join(o, HOCHGELADEN)
    if mit_auftrag:
        auftrag = _auftrag_lesen(os.path.join(o, AUFTRAG))
        if not auftrag:
            raise WiederherstellungFehler("Kein Auftrag gefunden.")
    info = hochgeladen(daten_dir)
    if not info:
        raise WiederherstellungFehler("Es liegt keine Sicherung bereit.")
    if os.path.islink(quelle) or not os.path.isfile(quelle):
        raise WiederherstellungFehler("Die bereitliegende Sicherung ist keine normale Datei.")
    summe = _pruefsumme(quelle)
    if summe != info.get("pruefsumme") or (mit_auftrag and summe != auftrag.get("pruefsumme")):
        raise WiederherstellungFehler("Die bereitliegende Sicherung hat sich geändert. Nichts eingespielt.")
    angaben = pruefen(quelle)
    ausgabe("Sicherung geprüft: Datenbankstand %d, %s Konten (Admins: %s), letzte Änderung %s" % (
        angaben["stand"], angaben["konten"], ", ".join(angaben["admins"]), angaben["letzte_aenderung"] or "–"))

    ziel = db.pfad(daten_dir)
    if os.path.exists(ziel):
        con = db.verbinden(ziel)
        try:
            ausgabe("Bisheriger Stand gesichert: %s" % updates.sicherung_ablegen(con, daten_dir, art="wiederherstellung"))
        finally:
            con.close()
    neu = ziel + ".neu"
    shutil.copyfile(quelle, neu)
    os.chmod(neu, 0o640)
    for rest in (ziel + "-wal", ziel + "-shm"):   # zum alten Stand: darf nie auf die neue Datei angewandt werden
        if os.path.exists(rest):
            os.remove(rest)
    os.replace(neu, ziel)
    con = db.oeffnen(daten_dir)   # migriert auf den Stand dieses Programms
    try:
        with db.transaktion(con):
            con.execute("DELETE FROM einstellung WHERE schluessel = 'sitzung_geheimnis'")   # alle Anmeldungen enden
            db.protokoll(con, "system", "sicherung_eingespielt", stand=angaben["stand"], konten=angaben["konten"],
                         letzte_aenderung=angaben["letzte_aenderung"])
        ausgabe("Datenbank ausgetauscht und auf Stand %d gebracht. Alle Anmeldungen sind beendet." %
                con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()
    verwerfen(daten_dir)
    return angaben
