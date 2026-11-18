"""Webserver: alles ueber HTTPS (Port 443). HTTP (Port 80) liefert nur das Stammzertifikat (/ca.crt) und leitet sonst
nach HTTPS um (Bauweise wie TrackingDRS und Lernbuero MT).

Ohne Zertifikat (oder mit LEHRERKALENDER_OHNE_TLS=1 zum lokalen Testen) laeuft die ganze Seite ueber HTTP.
Umgebungsvariablen: LEHRERKALENDER_DATEN, LEHRERKALENDER_TLS_DIR, LEHRERKALENDER_HTTPS_PORT, LEHRERKALENDER_HTTP_PORT,
LEHRERKALENDER_BIND, LEHRERKALENDER_OHNE_TLS.

Alle Aenderungen laufen ueber POST mit JSON und dem Kopf X-Lehrerkalender: 1 (Schutz vor fremden Formularen).
"""
import datetime
import html
import json
import mimetypes
import os
import re
import socket
import ssl
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, abos, db, exporte, formulare, grunddaten, kollegium, konten, moodle, ub, notenschluessel, paperless, planung, pruefungen, qr, schule, stundenplan, totp, updates, vpn, wiederherstellung

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASIS, "web")
DATEN_DIR = os.environ.get("LEHRERKALENDER_DATEN", "/var/lib/lehrerkalender")
TLS_DIR = os.environ.get("LEHRERKALENDER_TLS_DIR", os.path.join(DATEN_DIR, "tls"))
HTTPS_PORT = int(os.environ.get("LEHRERKALENDER_HTTPS_PORT", "443"))
HTTP_PORT = int(os.environ.get("LEHRERKALENDER_HTTP_PORT", "80"))
BIND = os.environ.get("LEHRERKALENDER_BIND", "0.0.0.0")
OHNE_TLS = os.environ.get("LEHRERKALENDER_OHNE_TLS") == "1"

COOKIE = "lkmt"
KOPF = "X-Lehrerkalender"
MAX_BODY = 1024 * 1024
MAX_BODY_GROSS = 16 * 1024 * 1024        # Fotos und Skizzen der Unterrichtsbesuche (Base64)
GROSSE_ANFRAGEN = re.compile(r"/api/ub/eintraege/\d+/(foto|skizze)")
UB_SEITEN = {"": "ub-uebersicht.html", "/einstellungen": "ub-einstellungen.html", "/besuch": "ub-besuch.html", "/erfassen": "ub-erfassen.html"}
SEITEN = {"/anmelden": "anmelden.html", "/app": "app.html", "/einrichtung": "einrichtung.html", "/einladung": "einladung.html"}
STATISCH = re.compile(r"/static/([a-z0-9_-]+\.(css|js|svg|png|ico))")
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

SPERRE = konten.Sperre()            # Passwort-, Code- und Einladungs-Raten


class Fehler(Exception):
    def __init__(self, status, meldung):
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung


def _ganzzahl(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise Fehler(400, "Ungültige Angabe.")


class Handler(BaseHTTPRequestHandler):
    server_version = "LehrerkalenderMT"
    sys_version = ""
    timeout = 30
    protocol_version = "HTTP/1.1"
    nur_umleiten = False   # True: HTTP-Port neben HTTPS

    # --- Hilfen ---

    def _kopfzeilen(self, status, typ, laenge, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(laenge))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for name, wert in extra:
            self.send_header(name, wert)
        self.end_headers()

    def antwort(self, status, inhalt, typ="application/json; charset=utf-8", extra=(), cache=False):
        if not isinstance(inhalt, bytes):
            inhalt = json.dumps(inhalt, ensure_ascii=False).encode("utf-8")
        extra = list(extra) + ([] if cache else [("Cache-Control", "no-store")])
        self._kopfzeilen(status, typ, len(inhalt), extra)
        if self.command != "HEAD":
            self.wfile.write(inhalt)

    def umleiten(self, ziel):
        self._kopfzeilen(303, "text/plain; charset=utf-8", 0, [("Location", ziel), ("Cache-Control", "no-store")])

    def datei(self, pfad, typ=None):
        try:
            with open(pfad, "rb") as f:
                inhalt = f.read()
        except OSError:
            return self.antwort(404, {"fehler": "Nicht gefunden."})
        typ = typ or (mimetypes.guess_type(pfad)[0] or "application/octet-stream")
        if typ.startswith("text/") or typ in ("application/javascript", "image/svg+xml"):
            typ += "; charset=utf-8"
        self.antwort(200, inhalt, typ)

    def herunterladen(self, inhalt, typ, dateiname):
        """Datei ausliefern. PDFs mit ?ansehen=1 zeigt der Browser im Tab (zum Drucken), sonst Download."""
        name = urllib.parse.quote(dateiname)
        art = "inline" if typ == "application/pdf" and self.ansehen() else "attachment"
        self.antwort(200, inhalt, typ, extra=[("Content-Disposition", "%s; filename*=UTF-8''%s" % (art, name))])

    def ansehen(self):
        return self.command in ("GET", "HEAD") and self.abfrage("ansehen") == "1"

    def fehler(self, status, meldung, **mehr):
        """Fehlerantwort: JSON fuer die App; im PDF-Tab (?ansehen=1) eine kleine lesbare Seite statt rohem JSON."""
        if self.ansehen():
            seite = ("<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>Lehrerkalender MT</title>"
                     "<body style=\"font-family:system-ui,sans-serif;max-width:40em;margin:3em auto;padding:0 1em\">"
                     "<h1 style=\"font-size:1.3em\">Das PDF lässt sich nicht anzeigen</h1><p>%s</p>"
                     "<p style=\"color:#666\">Diesen Tab einfach schließen.</p></body></html>") % html.escape(meldung)
            return self.antwort(status, seite.encode("utf-8"), "text/html; charset=utf-8")
        self.antwort(status, dict({"fehler": meldung}, **mehr))

    def body(self):
        """JSON-Inhalt einer POST-Anfrage. Liest immer den ganzen Inhalt (sonst bricht die Verbindung ab)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        grenze = MAX_BODY_GROSS if GROSSE_ANFRAGEN.fullmatch(urllib.parse.urlsplit(self.path).path) else MAX_BODY
        if laenge > grenze:
            raise Fehler(413, "Die Anfrage ist zu groß.")
        roh = self.rfile.read(laenge) if laenge else b""
        if self.headers.get(KOPF) != "1":
            raise Fehler(403, "Anfrage abgelehnt.")
        if not roh:
            return {}
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Fehler(400, "Ungültige Daten.")
        if not isinstance(daten, dict):
            raise Fehler(400, "Ungültige Daten.")
        return daten

    def roh_speichern(self, ziel, grenze):
        """Inhalt einer POST-Anfrage ohne JSON (Datei-Upload) in Stuecken nach ziel schreiben. Bei einem Fehler davor
        bleibt der Inhalt ungelesen: dann die Verbindung schliessen, sonst laese der naechste Aufruf Dateireste."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if self.headers.get(KOPF) != "1":
            self.close_connection = True
            raise Fehler(403, "Anfrage abgelehnt.")
        if laenge <= 0:
            self.close_connection = True
            raise Fehler(400, "Keine Datei.")
        if laenge > grenze:
            self.close_connection = True
            raise Fehler(413, "Die Datei ist zu groß (höchstens %d MB)." % (grenze // (1024 * 1024)))
        rest = laenge
        with open(ziel, "wb") as f:
            while rest:
                teil = self.rfile.read(min(rest, 1024 * 1024))
                if not teil:
                    self.close_connection = True
                    raise Fehler(400, "Die Übertragung ist abgebrochen.")
                f.write(teil)
                rest -= len(teil)

    def abfrage(self, name, vorgabe=None):
        werte = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get(name)
        return werte[0] if werte else vorgabe

    def cookie(self):
        for teil in (self.headers.get("Cookie") or "").split(";"):
            name, _, wert = teil.strip().partition("=")
            if name == COOKIE:
                return wert
        return None

    def cookie_setzen(self, wert, max_age):
        sicher = "; Secure" if getattr(self.server, "ist_tls", False) else ""
        return ("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (COOKIE, wert, max_age, sicher))

    def adresse(self):
        return self.client_address[0]

    def host(self):
        host = (self.headers.get("Host") or "").strip()
        host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.split(":")[0]
        return host if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) else socket.gethostname()

    def konto(self, con, pflicht=True, vorlaeufig_ok=False):
        k = konten.sitzung_pruefen(con, self.cookie())
        if k is None:
            if pflicht:
                raise Fehler(401, "Bitte anmelden.")
            return None
        if k["pw_vorlaeufig"] and not vorlaeufig_ok:
            raise Fehler(403, "Bitte zuerst ein eigenes Passwort festlegen.")
        return k

    def gebremst(self):
        wartezeit = SPERRE.wartezeit(self.adresse())
        if wartezeit:
            raise Fehler(429, "Zu viele Fehlversuche. Bitte %d Sekunden warten." % wartezeit)

    # --- Verteilung ---

    def do_GET(self):
        self._verteilen("GET")

    def do_HEAD(self):
        self._verteilen("GET")

    def do_POST(self):
        self._verteilen("POST")

    def zu_https(self, methode):
        """HTTP-Port neben HTTPS: GET nach HTTPS umleiten, POST ablehnen (Passwoerter nie unverschluesselt)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if 0 < laenge <= MAX_BODY:
            self.rfile.read(laenge)
        if methode == "POST" or laenge > MAX_BODY:
            return self.antwort(403, {"fehler": "Bitte die Seite über https:// aufrufen."})
        port = "" if HTTPS_PORT == 443 else ":%d" % HTTPS_PORT
        self._kopfzeilen(301, "text/plain; charset=utf-8", 0,
                         [("Location", "https://%s%s%s" % (self.host(), port, self.path if self.path.startswith("/") else "/"))])

    def _verteilen(self, methode):
        pfad = urllib.parse.urlsplit(self.path).path
        if self.nur_umleiten and pfad != "/ca.crt":
            try:
                return self.zu_https(methode)
            except Fehler as f:
                return self.antwort(f.status, {"fehler": f.meldung})
        con = None
        try:
            con = db.verbinden(self.server.db_pfad)
            if methode == "GET" and not pfad.startswith("/api/") and not UB_PROTOKOLL.fullmatch(pfad):
                return self.seite(con, pfad)
            if methode == "POST" and pfad in ROH_ROUTEN:   # Datei als Inhalt (kein JSON), liest der Aufgerufene selbst
                return ROH_ROUTEN[pfad](self, con)
            for m, muster, funktion in ROUTEN:
                treffer = muster.fullmatch(pfad)
                if m == methode and treffer:
                    daten = self.body() if methode == "POST" else {}
                    return funktion(self, con, daten, *treffer.groups())
            if methode == "POST":
                self.body()
            raise Fehler(404, "Nicht gefunden.")
        except Fehler as f:
            self.fehler(f.status, f.meldung)
        except ub.UbFehler as f:
            self.fehler(f.status, str(f), detail=str(f))
        except paperless.PaperlessFehler as f:
            self.fehler(f.status, str(f))
        except (konten.KontoFehler, grunddaten.GrunddatenFehler, notenschluessel.SchluesselFehler, qr.QrFehler,
                stundenplan.StundenplanFehler, planung.PlanungFehler, abos.AboFehler, pruefungen.PruefungFehler,
                updates.UpdateFehler, schule.SchuleFehler, formulare.FormularFehler, vpn.VpnFehler, kollegium.KollegiumFehler,
                wiederherstellung.WiederherstellungFehler) as f:
            self.fehler(400, str(f))
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.timeout):
            pass
        except Exception as f:   # unerwartet: protokollieren, aber nichts Internes verraten
            print("FEHLER %s %s: %r" % (methode, pfad, f), file=sys.stderr, flush=True)
            try:
                self.fehler(500, "Interner Fehler. Bitte später noch einmal versuchen.")
            except OSError:
                pass
        finally:
            if con is not None:
                con.close()

    def seite(self, con, pfad):
        if pfad == "/":
            if konten.sitzung_pruefen(con, self.cookie()):
                return self.umleiten("/app")
            return self.umleiten("/einrichtung" if not konten.hat_konten(con) else "/anmelden")
        if pfad in SEITEN:
            return self.datei(os.path.join(WEB_DIR, SEITEN[pfad]), "text/html")
        ub_seite = re.fullmatch(r"/unterrichtsbesuche(/einstellungen|/\d+(/erfassen)?)?", pfad)
        if ub_seite:   # Unterrichtsbesuche: eigene Seiten wie im alten Lehrerkalender (Daten holt ub-laden.js)
            teil = ub_seite.group(1) or ""
            name = UB_SEITEN["/erfassen" if ub_seite.group(2) else ("/besuch" if teil and teil != "/einstellungen" else teil)]
            return self.datei(os.path.join(WEB_DIR, name), "text/html")
        treffer = STATISCH.fullmatch(pfad)
        if treffer:
            return self.datei(os.path.join(WEB_DIR, treffer.group(1)))
        if pfad == "/ca.crt":
            return self.datei(os.path.join(TLS_DIR, "ca.crt"), "application/x-x509-ca-cert")
        raise Fehler(404, "Nicht gefunden.")

    def log_message(self, fmt, *args):   # keine Zugriffsprotokolle
        pass


# --- Anmeldung und eigenes Konto ---

def api_status(h, con, daten):
    h.antwort(200, {"version": VERSION, "eingerichtet": konten.hat_konten(con)})


def api_einrichtung(h, con, daten):
    h.gebremst()
    with db.transaktion(con):
        try:
            konto = konten.einrichten(con, daten.get("code"), daten.get("kuerzel"), daten.get("name"), daten.get("passwort"))
        except konten.KontoFehler as f:
            if "Einrichtungscode" in str(f):
                SPERRE.fehlversuch(h.adresse())
            raise
    print("Einrichtung: erstes Admin-Konto %s angelegt" % konto["kuerzel"], flush=True)
    wert, _, _ = konten.anmelden(con, konto["kuerzel"], daten.get("passwort"))
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_anmelden(h, con, daten):
    h.gebremst()
    try:
        wert, konto, zwischen = konten.anmelden(con, daten.get("kuerzel"), daten.get("passwort"))
    except konten.KontoFehler:
        dauer = SPERRE.fehlversuch(h.adresse())
        print("Anmeldung fehlgeschlagen: %s von %s%s" % ((daten.get("kuerzel") or "")[:12], h.adresse(),
              ", gesperrt fuer %d s" % dauer if dauer else ""), flush=True)
        raise
    if zwischen:
        return h.antwort(200, {"zweiter_faktor": True, "zwischen": zwischen})
    SPERRE.erfolg(h.adresse())
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_anmelden_code(h, con, daten):
    h.gebremst()
    try:
        with db.transaktion(con):
            wert, konto = konten.zweiter_schritt(con, daten.get("zwischen"), daten.get("code"))
    except konten.KontoFehler:
        SPERRE.fehlversuch(h.adresse())
        raise
    SPERRE.erfolg(h.adresse())
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_abmelden(h, con, daten):
    konten.abmelden(con, h.cookie())
    h.antwort(200, {"ok": True}, extra=[h.cookie_setzen("", 0)])


def api_ich(h, con, daten):
    k = h.konto(con, vorlaeufig_ok=True)
    a = schule.angaben(con)
    h.antwort(200, {"konto": k, "version": VERSION, "update": updates.kurz() if k["rolle"] == "admin" else None,
                    "schule": {"name": a["name"], "logo": a["logo"], "stand": a["logo_stand"]}})


def api_passwort(h, con, daten):
    k = h.konto(con, vorlaeufig_ok=True)
    with db.transaktion(con):
        konten.passwort_aendern(con, k["id"], daten.get("alt"), daten.get("neu"))
    wert = konten.sitzung_erzeugen(con, k["id"])   # alte Anmeldungen sind jetzt ungueltig, diese bleibt
    h.antwort(200, {"konto": konten.holen(con, k["id"])}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_faktor_beginnen(h, con, daten):
    k = h.konto(con)
    geheimnis = totp.geheimnis_neu()
    adresse = totp.adresse(geheimnis, k["kuerzel"])
    h.antwort(200, {"geheimnis": geheimnis, "adresse": adresse, "qr": qr.svg(adresse)})


def api_faktor_einschalten(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        codes = konten.totp_einschalten(con, k["id"], daten.get("geheimnis"), daten.get("code"))
    h.antwort(200, {"ersatzcodes": codes, "konto": konten.holen(con, k["id"])})


def api_faktor_ausschalten(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        konten.totp_ausschalten(con, k["id"], daten.get("passwort"))
    h.antwort(200, {"konto": konten.holen(con, k["id"])})


def api_faktor_ersatzcodes(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        codes = konten.ersatzcodes_erneuern(con, k["id"])
    h.antwort(200, {"ersatzcodes": codes, "konto": konten.holen(con, k["id"])})


# --- Einladung einloesen (ohne Anmeldung) ---

def api_einladung_pruefen(h, con, daten):
    h.gebremst()
    try:
        zeile = konten.einladung_pruefen(con, daten.get("code"))
    except konten.KontoFehler:
        SPERRE.fehlversuch(h.adresse())
        raise
    h.antwort(200, {"rolle": zeile["rolle"], "gueltig_bis": zeile["gueltig_bis"]})


def api_einladung_einloesen(h, con, daten):
    h.gebremst()
    try:
        with db.transaktion(con):
            konto = konten.einladung_einloesen(con, daten.get("code"), daten.get("kuerzel"), daten.get("name"), daten.get("passwort"))
            db.protokoll(con, konto["kuerzel"], "konto_per_einladung", rolle=konto["rolle"])
    except konten.KontoFehler as f:
        if "Einladungscode" in str(f):
            SPERRE.fehlversuch(h.adresse())
        raise
    print("Konto %s per Einladung angelegt" % konto["kuerzel"], flush=True)
    wert, _, _ = konten.anmelden(con, konto["kuerzel"], daten.get("passwort"))
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


# --- Admin: Konten und Einladungen ---

def _admin(h, con):
    k = h.konto(con)
    if k["rolle"] != "admin":
        raise Fehler(403, "Nur für Admins.")
    return k


def api_konten(h, con, daten):
    _admin(h, con)
    h.antwort(200, {"konten": konten.liste(con), "einladungen": konten.einladungen(con)})


def api_konto_aendern(h, con, daten, lid):
    a = _admin(h, con)
    lid = _ganzzahl(lid)
    with db.transaktion(con):
        k = konten.aendern(con, lid, name=daten.get("name"), rolle=daten.get("rolle"), gesperrt=daten.get("gesperrt"))
        if daten.get("passwort"):
            konten.passwort_setzen(con, lid, daten["passwort"], vorlaeufig=True)
        if daten.get("zweiter_faktor_zuruecksetzen"):
            konten.totp_zuruecksetzen(con, lid)
        db.protokoll(con, a["kuerzel"], "konto_geaendert", konto=k["kuerzel"],
                     felder=sorted(f for f in ("name", "rolle", "gesperrt", "passwort", "zweiter_faktor_zuruecksetzen")
                                   if daten.get(f) not in (None, "", False) or f == "gesperrt" and daten.get(f) is False))
    h.antwort(200, {"konto": konten.holen(con, lid)})


def api_einladung_anlegen(h, con, daten):
    a = _admin(h, con)
    with db.transaktion(con):
        e = konten.einladung_anlegen(con, daten.get("rolle") or "lehrkraft", daten.get("tage") or 14, daten.get("notiz"), a["id"])
        db.protokoll(con, a["kuerzel"], "einladung_angelegt", rolle=e["rolle"], gueltig_bis=e["gueltig_bis"])
    h.antwort(200, {"einladung": e})


def api_einladung_zurueckziehen(h, con, daten, eid):
    a = _admin(h, con)
    with db.transaktion(con):
        konten.einladung_zurueckziehen(con, _ganzzahl(eid))
        db.protokoll(con, a["kuerzel"], "einladung_zurueckgezogen", id=int(eid))
    h.antwort(200, {"einladungen": konten.einladungen(con)})


# --- Grunddaten ---

def api_grunddaten(h, con, daten):
    k = h.konto(con)
    alles = grunddaten.alles(con)
    alles["notenschluessel"] = notenschluessel.liste(con, k)
    alles["schule"] = schule.angaben(con)
    alles["formularvorlagen"] = formulare.vorlagen(con)
    h.antwort(200, alles)


def api_logo(h, con, daten):
    """Schullogo (oeffentlich, auch fuer die Anmeldeseite)."""
    daten_ = schule.logo(con)
    if not daten_:
        raise Fehler(404, "Kein Schullogo.")
    h.antwort(200, daten_, "image/jpeg", extra=[("Cache-Control", "max-age=300")], cache=True)


def api_logo_da(h, con, daten):
    a = schule.angaben(con)
    h.antwort(200, {"logo": a["logo"], "stand": a["logo_stand"], "name": a["name"]})


def api_schule(h, con, daten):
    _admin(h, con)
    with db.transaktion(con):
        schule.speichern(con, daten)
    h.antwort(200, schule.angaben(con))


def _grunddaten_schritt(art, funktion, mit_id=False):
    """Admin-Aenderung an den Grunddaten mit Protokollzeile; Antwort ist immer der neue Gesamtstand."""
    def schritt(h, con, daten, oid=None):
        a = _admin(h, con)
        with db.transaktion(con):
            if mit_id:
                funktion(con, daten, _ganzzahl(oid))
            else:
                funktion(con, daten)
            db.protokoll(con, a["kuerzel"], art, id=int(oid) if oid else None,
                         **{k: v for k, v in daten.items() if k in ("name", "nummer", "bezeichnung", "von", "bis")})
        alles = grunddaten.alles(con)
        alles["notenschluessel"] = notenschluessel.liste(con, a)
        h.antwort(200, alles)
    return schritt


def _nur_id(funktion):
    return lambda con, daten, oid: funktion(con, oid)


def _zeitraster(con, daten):
    """Raster speichern und die Stundenplaene aller Lehrkraefte auf geaenderte Zeiten nachziehen (gleiche Bezeichnung)."""
    bid = daten.get("bildungsgang_id")
    vorher = stundenplan.raster_vorher(con)
    grunddaten.zeitraster_speichern(con, None if bid in (None, "", 0) else _ganzzahl(bid), daten.get("bloecke"))
    stundenplan.raster_nachziehen(con, vorher)


def _a_woche(con, daten):
    stundenplan.a_woche_setzen(con, daten.get("a_woche"))


def api_schluessel_vorgabe(h, con, daten):
    h.konto(con)
    system = h.abfrage("system", "tendenz")
    h.antwort(200, {"system": system, "stufen": notenschluessel.STUFEN.get(system, []), "grenzen": notenschluessel.vorgabe(system)})


def api_schluessel_probe(h, con, daten):
    """Rechnet Beispielwerte mit noch nicht gespeicherten Grenzen (fuer die Vorschau im Editor)."""
    h.konto(con)
    system = daten.get("system")
    grenzen = notenschluessel.grenzen_pruefen(system, daten.get("grenzen"))
    h.antwort(200, {"noten": {str(p): notenschluessel.note(system, grenzen, p)["text"] for p in range(0, 101)}})


def api_schluessel_anlegen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        sid = notenschluessel.speichern(con, k, daten)
        db.protokoll(con, k["kuerzel"], "schluessel_angelegt", id=sid, name=daten.get("name"), schluessel=daten.get("art"))
    h.antwort(200, {"schluessel": notenschluessel.holen(con, sid), "liste": notenschluessel.liste(con, k)})


def api_schluessel_aendern(h, con, daten, sid):
    k = h.konto(con)
    sid = _ganzzahl(sid)
    with db.transaktion(con):
        notenschluessel.speichern(con, k, daten, sid)
        db.protokoll(con, k["kuerzel"], "schluessel_geaendert", id=sid, name=daten.get("name"))
    h.antwort(200, {"schluessel": notenschluessel.holen(con, sid), "liste": notenschluessel.liste(con, k)})


def api_schluessel_kopieren(h, con, daten, sid):
    k = h.konto(con)
    with db.transaktion(con):
        neu = notenschluessel.kopieren(con, k, _ganzzahl(sid))
    h.antwort(200, {"schluessel": notenschluessel.holen(con, neu), "liste": notenschluessel.liste(con, k)})


def api_schluessel_loeschen(h, con, daten, sid):
    k = h.konto(con)
    with db.transaktion(con):
        notenschluessel.loeschen(con, k, _ganzzahl(sid))
        db.protokoll(con, k["kuerzel"], "schluessel_geloescht", id=int(sid))
    h.antwort(200, {"liste": notenschluessel.liste(con, k)})


def api_protokoll(h, con, daten):
    _admin(h, con)
    zeilen = con.execute("SELECT zeit, wer, art, daten FROM protokoll ORDER BY id DESC LIMIT 200")
    h.antwort(200, {"protokoll": [{"zeit": z["zeit"], "wer": z["wer"], "art": z["art"], "daten": json.loads(z["daten"])}
                                  for z in zeilen]})


# --- Stundenplan, Wochenplan, Aenderungen, Termine (Stufe B) ---

def api_stundenplan(h, con, daten):
    k = h.konto(con)
    h.antwort(200, stundenplan.editor(con, k["id"]))


def _stundenplan_schritt(funktion):
    """Aenderung am eigenen Stundenplan; Antwort ist der neue Stand des Editors."""
    def schritt(h, con, daten, vid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k["id"], daten, None if vid is None else _ganzzahl(vid))
        antwort = stundenplan.editor(con, k["id"])
        if isinstance(neu, int):
            antwort["neu"] = neu
        h.antwort(200, antwort)
    return schritt


def api_woche(h, con, daten):
    k = h.konto(con)
    try:
        montag = db.heute() if not h.abfrage("montag") else datetime.date.fromisoformat(h.abfrage("montag"))
    except ValueError:
        raise Fehler(400, "Ungültiges Datum.")
    if not h.abfrage("montag") and montag.isoweekday() > 5:   # am Wochenende schon die naechste Woche
        montag = montag + datetime.timedelta(days=8 - montag.isoweekday())
    h.antwort(200, planung.themen_der_woche(con, k["id"], stundenplan.woche(con, k["id"], montag)))


def _eigene_schritt(funktion):
    """Aenderung oder Termin der eigenen Woche; Antwort {ok, id}. Die Oberflaeche laedt die Woche danach neu."""
    def schritt(h, con, daten, oid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k["id"], daten, None if oid is None else _ganzzahl(oid))
        h.antwort(200, {"ok": True, "id": neu})
    return schritt


# --- Planung (Stufe C1): Bibliothek, Themenfolge, Fliessen ---

def api_bibliothek(h, con, daten):
    h.konto(con)
    alles = grunddaten.alles(con)
    gaenge = [{"id": b["id"], "name": b["name"], "kuerzel": b["kuerzel"], "einheit": b["einheit"], "stufen": b["stufen"]}
              for b in alles["bildungsgaenge"] if b["aktiv"]]
    bid = h.abfrage("bildungsgang")
    bid = _ganzzahl(bid) if bid else (gaenge[0]["id"] if gaenge else None)
    h.antwort(200, {"bildungsgaenge": gaenge, "bildungsgang_id": bid,
                    "lernfelder": planung.bibliothek(con, bid) if bid else []})


def _planung_schritt(funktion):
    """Aenderung an Bibliothek oder Planung; Antwort {ok, id}. Die Oberflaeche laedt danach neu."""
    def schritt(h, con, daten, oid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k, daten, None if oid is None else _ganzzahl(oid))
        h.antwort(200, {"ok": True, "id": neu})
    return schritt


def api_planung(h, con, daten):
    k = h.konto(con)
    jahre = grunddaten.schuljahre(con)
    sid = h.abfrage("schuljahr")
    if sid:
        sid = _ganzzahl(sid)
    else:
        jetzt = grunddaten.schuljahr_zum(con, db.heute())
        kuenftig = [j for j in jahre if j["beginn"] > db.heute().isoformat()]
        sid = jetzt["id"] if jetzt else (kuenftig[0]["id"] if kuenftig else (jahre[-1]["id"] if jahre else None))
    antwort = {"schuljahre": jahre, "schuljahr_id": sid, "straenge": [], "plan": None, "lesend": None, "kollegium": None,
               "unterricht": None}
    kid = _ganzzahl(h.abfrage("klasse")) if h.abfrage("klasse") else None
    lid = k["id"]
    if h.abfrage("lehrkraft"):   # Stufe E: Planung einer Kollegin/eines Kollegen derselben Klasse, nur lesen
        antwort["lesend"] = kollegium.kollege(con, k["id"], _ganzzahl(h.abfrage("lehrkraft")), kid)
        lid = antwort["lesend"]["id"]
    if sid:
        straenge = planung.straenge(con, lid, sid)
        if antwort["lesend"]:
            gemeinsam = kollegium.gemeinsame_klassen(con, k["id"], lid)
            straenge = [x for x in straenge if x["klasse_id"] in gemeinsam]
        antwort["straenge"] = straenge
        if kid:
            gid = h.abfrage("gruppe")
            antwort["plan"] = planung.plan(con, lid, kid, _ganzzahl(gid) if gid else None, sid)
            if antwort["lesend"]:
                p = antwort["plan"]
                antwort["unterricht"] = kollegium.unterricht(
                    con, lid, kid, _ganzzahl(gid) if gid else None, datetime.date.fromisoformat(p["schuljahr"]["beginn"]),
                    datetime.date.fromisoformat(p["schuljahr"]["ende"]), p["bloecke"], p["themen"])
            if not antwort["lesend"]:
                antwort["kollegium"] = kollegium.klasse_uebersicht(con, k["id"], kid)
    h.antwort(200, antwort)


def api_admin_kollegium(h, con, daten):
    _admin(h, con)
    h.antwort(200, kollegium.admin_stand(con))


def api_admin_kollegium_setzen(h, con, daten):
    a = _admin(h, con)
    an = daten.get("an") is True
    with db.transaktion(con):
        kollegium.setzen(con, an)
        db.protokoll(con, a["kuerzel"], "kollegium_teilen_" + ("an" if an else "aus"))
    h.antwort(200, kollegium.admin_stand(con))


def api_stunde(h, con, daten):
    k = h.konto(con)
    datum, beginn = h.abfrage("datum"), h.abfrage("beginn")
    try:
        datetime.date.fromisoformat(datum or "")
    except ValueError:
        raise Fehler(400, "Ungültiges Datum.")
    h.antwort(200, planung.stunde(con, k["id"], datum, beginn or ""))


def api_ist(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        planung.ist_setzen(con, k["id"], daten.get("datum"), daten.get("beginn"), daten.get("stand"))
    h.antwort(200, planung.stunde(con, k["id"], daten.get("datum"), daten.get("beginn")))


def api_stunde_eintrag(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        planung.eintrag_setzen(con, k["id"], daten.get("datum"), daten.get("beginn"), daten)
    h.antwort(200, planung.stunde(con, k["id"], daten.get("datum"), daten.get("beginn")))


# --- Dokumente (Stufe F3): eigenes Paperless je Konto, siehe app/paperless.py ---

def api_dokumente_konfig(h, con, daten):
    k = h.konto(con)
    h.antwort(200, paperless.konfig_oeffentlich(con, k["id"], DATEN_DIR))


def api_dokumente_konfig_speichern(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        anzahl = paperless.konfig_speichern(con, k["id"], DATEN_DIR, daten)
    antwort = paperless.konfig_oeffentlich(con, k["id"], DATEN_DIR)
    antwort["anzahl"] = anzahl
    h.antwort(200, antwort)


def api_dokumente_konfig_loeschen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        paperless.konfig_loeschen(con, k["id"])
    h.antwort(200, {"verbunden": False})


def api_dokumente_stammlisten(h, con, daten):
    k = h.konto(con)
    h.antwort(200, paperless.stammlisten(con, k["id"], DATEN_DIR))


def api_dokumente(h, con, daten):
    k = h.konto(con)
    h.antwort(200, paperless.suchen(con, k["id"], DATEN_DIR, h.abfrage("suche") or "",
                                    (h.abfrage("tags") or "").split(","), h.abfrage("sortierung") or "-created",
                                    h.abfrage("seite") or 1))


def api_dokument(h, con, daten, did):
    k = h.konto(con)
    h.antwort(200, paperless.dokument(con, k["id"], DATEN_DIR, did))


def api_dokument_aendern(h, con, daten, did):
    k = h.konto(con)
    h.antwort(200, paperless.aendern(con, k["id"], DATEN_DIR, did, daten))


def api_dokument_datei(h, con, daten, did, art):
    k = h.konto(con)
    inhalt, typ, name = paperless.datei(con, k["id"], DATEN_DIR, did, art)
    extra = [("Cache-Control", "private, max-age=300")]
    anzeigen = typ.startswith("application/pdf") or (typ.startswith("image/") and "svg" not in typ)
    if art == "download" or not anzeigen:   # fremde HTML-/SVG-Inhalte nie im eigenen Ursprung anzeigen
        extra.append(("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name or "dokument")))
    h.antwort(200, inhalt, typ, extra=extra, cache=True)


def api_dokument_notiz(h, con, daten, did):
    k = h.konto(con)
    h.antwort(200, paperless.notiz_neu(con, k["id"], DATEN_DIR, did, daten.get("text")))


def api_dokument_notiz_loeschen(h, con, daten, did, nid):
    k = h.konto(con)
    h.antwort(200, paperless.notiz_loeschen(con, k["id"], DATEN_DIR, did, nid))


def api_dokumente_hochladen(h, con):
    """Rohe POST-Anfrage: die Datei als Inhalt, Angaben als Abfrage-Parameter (name, titel, datum, korrespondent, typ, tags)."""
    try:
        k = h.konto(con)
    except Fehler:
        h.close_connection = True   # Inhalt ungelesen
        raise
    fd, tmp = tempfile.mkstemp(prefix="paperless-", dir=DATEN_DIR if os.path.isdir(DATEN_DIR) else None)
    os.close(fd)
    try:
        h.roh_speichern(tmp, paperless.MAX_HOCHLADEN)
        with open(tmp, "rb") as f:
            inhalt = f.read()
    finally:
        os.remove(tmp)
    task = paperless.hochladen(con, k["id"], DATEN_DIR, h.abfrage("name") or "", inhalt,
                               (h.headers.get("Content-Type") or "").split(";")[0].strip(), h.abfrage("titel") or "",
                               h.abfrage("datum") or "", h.abfrage("korrespondent") or 0, h.abfrage("typ") or 0,
                               (h.abfrage("tags") or "").split(","))
    h.antwort(200, {"task": task})


def _ablage_quelle(h, con, k, daten):
    """Erzeugt das PDF eines Exports wie beim Herunterladen: (Bytes, Dateiname, Datum fuer Paperless)."""
    quelle, oid = daten.get("quelle"), _ganzzahl(daten.get("id"))
    if quelle in ("ergebnis", "rueckmeldung"):
        p = pruefungen._pruefung(con, k["id"], oid)
        datum = p["datum"] or p["fenster_bis"] or ""
        if quelle == "ergebnis":
            inhalt, name = exporte.ergebnis_pdf(con, k["id"], oid, k["name"])
        else:
            sid = daten.get("schueler")
            inhalt, name = exporte.rueckmeldung_pdf(con, k["id"], oid, _ganzzahl(sid) if sid else None, k["name"])
        return inhalt, name, datum
    if quelle == "formular":
        inhalt, name = formulare.pdf_von(con, k["id"], oid)
        z = con.execute("SELECT von FROM formular WHERE id = ? AND lehrkraft_id = ?", (oid, k["id"])).fetchone()
        return inhalt, name, (z["von"] or "") if z else ""
    if quelle == "ub":
        from . import ub_protokoll_pdf
        kx = _ub(h, con)
        b = ub.besuch_obj(kx, oid)
        inhalt = ub_protokoll_pdf.erzeuge(kx, kx, b, mit_fotos=daten.get("fotos", True) not in (False, 0, "0"),
                                          ordnung=daten.get("ordnung") or None)
        name = "Unterrichtsbesuch_%s_%s.pdf" % (b.datum or "ohne-Datum", re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", b.anwaerter.name or ""))
        return inhalt, name, b.datum or ""
    raise Fehler(400, "Unbekannte Quelle.")


def api_dokumente_ablegen(h, con, daten):
    """Export (Ergebnisliste, Rueckmeldeboegen, Formular, Besuchsprotokoll) direkt im eigenen Paperless ablegen, mit
    Upload-Tag und Speicherpfad aus den Einstellungen. Der Browser laedt dafuer nichts herunter und wieder hoch."""
    k = h.konto(con)
    if not paperless.verbunden(con, k["id"]):
        raise Fehler(400, "Paperless ist nicht verbunden: unter Einstellungen › Konto Adresse und API-Token eintragen.")
    inhalt, name, datum = _ablage_quelle(h, con, k, daten)
    datum = daten.get("datum") or (datum[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", datum or "") else "")
    titel = (daten.get("titel") or "").strip() or os.path.splitext(name)[0].replace("_", " ")
    task = paperless.hochladen(con, k["id"], DATEN_DIR, name, inhalt, "application/pdf", titel, datum,
                               daten.get("korrespondent") or 0, daten.get("typ") or 0, daten.get("tags") or [])
    if daten.get("quelle") in ("ergebnis", "rueckmeldung"):   # haengt an der Pruefung, sobald Paperless es verarbeitet hat
        with db.transaktion(con):
            paperless.anhaengen_wartend(con, _ganzzahl(daten.get("id")), task, titel)
    h.antwort(200, {"task": task, "titel": titel})


# Anhaenge an Pruefungen (F3c): ohne umschliessende Transaktion, weil dabei Paperless gefragt wird (bis zu 20 s);
# die einzelnen Schreibzugriffe sind kurz und laufen im Autocommit.

def api_pruefung_dokumente(h, con, daten, pid):
    k = h.konto(con)
    pruefungen._pruefung(con, k["id"], _ganzzahl(pid))
    h.antwort(200, {"anhaenge": paperless.anhaenge(con, k["id"], DATEN_DIR, int(pid))})


def api_pruefung_dokument_anhaengen(h, con, daten, pid):
    k = h.konto(con)
    pruefungen._pruefung(con, k["id"], _ganzzahl(pid))
    paperless.anhaengen(con, k["id"], DATEN_DIR, int(pid), daten.get("dokument"))
    h.antwort(200, {"anhaenge": paperless.anhaenge(con, k["id"], DATEN_DIR, int(pid))})


def api_pruefung_dokument_loesen(h, con, daten, pid, aid):
    k = h.konto(con)
    pruefungen._pruefung(con, k["id"], _ganzzahl(pid))
    paperless.anhang_loesen(con, int(pid), int(aid))
    h.antwort(200, {"anhaenge": paperless.anhaenge(con, k["id"], DATEN_DIR, int(pid))})


def api_dokumente_aufgabe(h, con, daten):
    k = h.konto(con)
    h.antwort(200, paperless.aufgabe(con, k["id"], DATEN_DIR, h.abfrage("id") or ""))


def api_ist_offen(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"offen": planung.offene_ist(con, k["id"])})


def api_ist_alle(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        n = planung.ist_alle_bestaetigen(con, k["id"])
    h.antwort(200, {"bestaetigt": n})


# --- Kalender-Abos (ICS) ---

def api_abos(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"eigene": abos.liste(con, k), "schule": abos.liste(con, k, schule=True)})


def _abo_schritt(funktion, art):
    def schritt(h, con, daten, aid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k, daten, None if aid is None else _ganzzahl(aid))
            if daten.get("schule") or (aid and con.execute("SELECT 1 FROM kalender_abo WHERE id = ? AND lehrkraft_id IS NULL",
                                                           (int(aid),)).fetchone()):
                db.protokoll(con, k["kuerzel"], art, id=neu or (int(aid) if aid else None), name=daten.get("name"))
        h.antwort(200, {"eigene": abos.liste(con, k), "schule": abos.liste(con, k, schule=True), "id": neu})
    return schritt


def api_abo_abrufen(h, con, daten, aid):
    k = h.konto(con)
    aid = _ganzzahl(aid)
    abo = con.execute("SELECT * FROM kalender_abo WHERE id = ?", (aid,)).fetchone()
    if abo is None:
        raise Fehler(404, "Dieses Abo gibt es nicht.")
    abos._darf(k, abo)
    try:
        n = abos.abrufen(con, aid)
        meldung = None
    except abos.AboFehler as f:
        n, meldung = 0, str(f)
    h.antwort(200, {"anzahl": n, "fehler": meldung, "eigene": abos.liste(con, k), "schule": abos.liste(con, k, schule=True)})


ABO_TAKT = 3 * 3600   # alle drei Stunden


def abos_im_hintergrund(db_pfad):
    """Kalender-Abos regelmaessig abrufen (erster Lauf eine Minute nach dem Start)."""
    import time
    time.sleep(60)
    while True:
        try:
            abos.alle_abrufen(db_pfad)
        except Exception as f:   # der Thread darf nie sterben
            print("Abos: %r" % f, file=sys.stderr, flush=True)
        time.sleep(ABO_TAKT)


# --- Pruefungen und Bewertung (Stufe D1) ---

def _pr_schritt(funktion, antwort=None):
    """Aenderung; Antwort {ok, id} bzw. was antwort(con, k, daten, oid, neu) liefert."""
    def schritt(h, con, daten, oid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k, daten, None if oid is None else _ganzzahl(oid))
        h.antwort(200, antwort(con, k, daten, None if oid is None else int(oid), neu) if antwort else {"ok": True, "id": neu})
    return schritt


def api_schueler(h, con, daten):
    k = h.konto(con)
    kid = h.abfrage("klasse")
    h.antwort(200, {"schueler": pruefungen.schueler(con, k["id"], _ganzzahl(kid)) if kid else []})


def api_moodle_csv(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        r = pruefungen.moodle_csv(con, k["id"], _ganzzahl(daten.get("klasse_id")), daten.get("text"))
    h.antwort(200, r)


def api_pruefungen(h, con, daten):
    k = h.konto(con)
    kid, sid = h.abfrage("klasse"), h.abfrage("schuljahr")
    gid = h.abfrage("gruppe")
    liste = pruefungen.pruefungen(con, k["id"], _ganzzahl(kid), _ganzzahl(gid) if gid else None, _ganzzahl(sid)) if kid and sid else []
    h.antwort(200, {"pruefungen": liste, "vorlagen": pruefungen.vorlagen(con, k["id"]),
                    "schluessel": notenschluessel.liste(con, k), "standard": pruefungen.standard_schluessel(con, k["id"])})


def api_pruefung(h, con, daten, pid):
    k = h.konto(con)
    h.antwort(200, pruefungen.ergebnis(con, k["id"], _ganzzahl(pid)))


def api_bewertung(h, con, daten, pid, sid):
    k = h.konto(con)
    with db.transaktion(con):
        pruefungen.bewertung_setzen(con, k["id"], _ganzzahl(pid), _ganzzahl(sid), daten)
    h.antwort(200, pruefungen.ergebnis(con, k["id"], int(pid)))


def api_abschliessen(h, con, daten, pid):
    k = h.konto(con)
    with db.transaktion(con):
        warnungen = pruefungen.abschliessen(con, k["id"], _ganzzahl(pid))
    e = pruefungen.ergebnis(con, k["id"], int(pid))
    e["warnungen"] = warnungen
    h.antwort(200, e)


def api_team(h, con, daten, pid, tid=None, loeschen=False):
    k = h.konto(con)
    with db.transaktion(con):
        if loeschen:
            pruefungen.team_loeschen(con, k["id"], _ganzzahl(pid), _ganzzahl(tid))
        else:
            pruefungen.team_speichern(con, k["id"], _ganzzahl(pid), daten, None if tid is None else _ganzzahl(tid))
    h.antwort(200, pruefungen.ergebnis(con, k["id"], int(pid)))


def _pm_schritt(funktion):
    """Pruefungsmodus-Aenderung; Antwort: das ganze Ergebnis der Pruefung (plus "neu": Rueckgabe der Funktion)."""
    def schritt(h, con, daten, pid, oid=None):
        k = h.konto(con)
        with db.transaktion(con):
            neu = funktion(con, k["id"], _ganzzahl(pid), daten, None if oid is None else _ganzzahl(oid))
        e = pruefungen.ergebnis(con, k["id"], int(pid))
        e["neu"] = neu
        h.antwort(200, e)
    return schritt


def api_teams_bilden(h, con, daten, pid):
    k = h.konto(con)
    with db.transaktion(con):
        pruefungen.teams_bilden(con, k["id"], _ganzzahl(pid), daten.get("groesse"))
    h.antwort(200, pruefungen.ergebnis(con, k["id"], int(pid)))


def api_export(h, con, daten, pid):
    """Fuer die Export-Ansicht: Notenspalte (Excel) und wer fuer Moodle keine E-Mail-Adresse hat."""
    k = h.konto(con)
    _, ohne = exporte.moodle_csv(con, k["id"], _ganzzahl(pid))
    h.antwort(200, {"notenspalte": exporte.notenspalte(con, k["id"], int(pid)), "ohne_email": ohne})


def api_ergebnis_pdf(h, con, daten, pid):
    k = h.konto(con)
    inhalt, name = exporte.ergebnis_pdf(con, k["id"], _ganzzahl(pid), k["name"])
    h.herunterladen(inhalt, "application/pdf", name)


def api_rueckmeldung_pdf(h, con, daten, pid):
    k = h.konto(con)
    sid = h.abfrage("schueler")
    inhalt, name = exporte.rueckmeldung_pdf(con, k["id"], _ganzzahl(pid), _ganzzahl(sid) if sid else None, k["name"])
    h.herunterladen(inhalt, "application/pdf", name)


def api_moodle_export(h, con, daten, pid):
    k = h.konto(con)
    text, _ = exporte.moodle_csv(con, k["id"], _ganzzahl(pid))
    p = pruefungen.ergebnis(con, k["id"], int(pid))["pruefung"]
    h.herunterladen(text.encode("utf-8"), "text/csv; charset=utf-8", "Moodle %s.csv" % p["titel"])


# --- Formularcenter (Stufe F1) ---

def api_formulare(h, con, daten):
    k = h.konto(con)
    h.antwort(200, formulare.uebersicht(con, k["id"]))


def api_formular_vorschau(h, con, daten):
    k = h.konto(con)
    try:
        tag = datetime.date.fromisoformat(h.abfrage("woche") or db.heute().isoformat())
    except ValueError:
        raise Fehler(400, "Ungültiges Datum.")
    ae = formulare.woche_aenderungen(con, k["id"], tag)
    ae["vorhanden"] = formulare.woche_hat_formular(con, k["id"], tag.isoformat())
    h.antwort(200, ae)


def api_formular_erstellen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        fid = formulare.erstellen(con, k, daten)
    h.antwort(200, {"id": fid, "formulare": formulare.liste(con, k["id"])})


def api_formular_pdf(h, con, daten, fid):
    k = h.konto(con)
    inhalt, name = formulare.pdf_von(con, k["id"], _ganzzahl(fid))
    h.herunterladen(inhalt, "application/pdf", name)


def api_formular_stand(h, con, daten, fid):
    k = h.konto(con)
    with db.transaktion(con):
        formulare.stand_setzen(con, k["id"], _ganzzahl(fid), daten.get("stand"))
    h.antwort(200, {"formulare": formulare.liste(con, k["id"])})


def api_formular_loeschen(h, con, daten, fid):
    k = h.konto(con)
    with db.transaktion(con):
        formulare.loeschen(con, k["id"], _ganzzahl(fid))
    h.antwort(200, {"formulare": formulare.liste(con, k["id"])})


def api_unterschrift(h, con, daten, art):
    """Eigene Unterschrift bzw. Paraphe als PNG (nur fuer das eigene Konto)."""
    k = h.konto(con)
    bild = formulare.unterschrift(con, k["id"], art)
    if not bild:
        raise Fehler(404, "Noch nicht gezeichnet.")
    h.antwort(200, bild, "image/png")


def api_unterschrift_setzen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        formulare.unterschrift_setzen(con, k["id"], daten.get("art"), daten.get("bild") or "")
    h.antwort(200, {"unterschrift": bool(formulare.unterschrift(con, k["id"])), "paraphe": bool(formulare.unterschrift(con, k["id"], "paraphe"))})


def api_formularvorlage(h, con, daten):
    _admin(h, con)
    with db.transaktion(con):
        formulare.vorlage_setzen(con, daten.get("art") or "stundenplanaenderung", daten.get("pdf") or "", daten.get("name") or "")
    h.antwort(200, {"vorlagen": formulare.vorlagen(con)})


# --- Unterrichtsbesuche (Stufe F2, Adressen wie im alten Lehrerkalender) ---

def _ub(h, con):
    k = h.konto(con)
    if not k.get("ub_an"):
        raise Fehler(403, "Die Unterrichtsbesuche sind für dein Konto ausgeschaltet (Einstellungen › Konto).")
    return ub.Kontext(con, k["id"], k["name"])


def _ub_schritt(funktion, lesen=False):
    """Aufruf mit Kontext; Aenderungen in einer Transaktion. funktion(kontext, daten, *ids)."""
    def schritt(h, con, daten, *ids):
        kx = _ub(h, con)
        ids = [int(i) if i.isdigit() else i for i in ids]
        if lesen:
            return h.antwort(200, funktion(kx, daten, *ids))
        with db.transaktion(con):
            r = funktion(kx, daten, *ids)
        h.antwort(200, r)
    return schritt


def api_ub_seite(h, con, daten, seite, bid=None):
    kx = _ub(h, con)
    with db.transaktion(con):          # beim ersten Mal legt einstellung() die Vorgaben an
        if seite == "uebersicht":
            r = ub.seite_uebersicht(kx, db.heute().isoformat())
        elif seite == "einstellungen":
            r = ub.seite_einstellungen(kx)
        else:
            r = ub.seite_besuch(kx, int(bid))
    h.antwort(200, r)


def api_ub_modul(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        con.execute("UPDATE lehrkraft SET ub_an = ? WHERE id = ?", (1 if daten.get("an") else 0, k["id"]))
    h.antwort(200, {"an": bool(daten.get("an"))})


def api_ub_datei(h, con, daten, uuid_, name):
    kx = _ub(h, con)
    d = ub.datei(kx, uuid_)
    if d is None:
        raise Fehler(404, "Nicht gefunden.")
    h.antwort(200, d.read_bytes(), ub.datei_mime(kx, uuid_) or "application/octet-stream", extra=[("Cache-Control", "private, max-age=86400")], cache=True)


def api_ub_protokoll(h, con, daten, bid, fmt):
    from . import ub_protokoll_odt, ub_protokoll_pdf
    kx = _ub(h, con)
    b = ub.besuch_obj(kx, int(bid))
    modul, typ = (ub_protokoll_pdf, "application/pdf") if fmt == "pdf" else (ub_protokoll_odt, "application/vnd.oasis.opendocument.text")
    inhalt = modul.erzeuge(kx, kx, b, mit_fotos=h.abfrage("fotos") != "0", ordnung=h.abfrage("ordnung") or None)
    name = "Unterrichtsbesuch_%s_%s.%s" % (b.datum or "ohne-Datum", re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", b.anwaerter.name or ""), fmt)
    if fmt == "pdf":
        h.antwort(200, inhalt, typ, extra=[("Content-Disposition", "inline; filename*=UTF-8''%s" % urllib.parse.quote(name))])
    else:
        h.herunterladen(inhalt, typ, name)


def api_moodle_vorschau(h, con, daten):
    k = h.konto(con)
    h.antwort(200, moodle.vorschau(con, k["id"], daten))


def api_moodle_uebernehmen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        r = moodle.uebernehmen(con, k["id"], daten)
    h.antwort(200, r)


def api_wieder_oeffnen(h, con, daten, pid):
    k = h.konto(con)
    with db.transaktion(con):
        pruefungen.wieder_oeffnen(con, k["id"], _ganzzahl(pid))
    h.antwort(200, pruefungen.ergebnis(con, k["id"], int(pid)))


def api_unterricht(h, con, daten):
    """Fuer den Pruefungsdialog: Gruppen der Klasse, gehaltene Bloecke an einem Tag und Hinweise zu den Terminen
    (termine als JSON in der Abfrage: [{gruppe_id, datum, beginn}] bzw. datum + beginn fuer "zusammen")."""
    k = h.konto(con)
    kid = _ganzzahl(h.abfrage("klasse") or "")
    gruppen = [g for g in stundenplan.gruppen(con, k["id"]) if g["klasse_id"] == kid]
    datum = h.abfrage("datum")
    antwort = {"gruppen": gruppen, "bloecke": [], "hinweise": []}
    try:
        if datum:
            datetime.date.fromisoformat(datum)
            antwort["bloecke"] = planung.unterricht_am(con, k["id"], kid, datum)
        liste = json.loads(h.abfrage("termine") or "[]")
        namen = {g["id"]: g["name"] for g in gruppen}
        liste = [{"gruppe_id": t.get("gruppe_id"), "gruppe": namen.get(t.get("gruppe_id"), ""), "datum": t.get("datum"), "beginn": t.get("beginn")}
                 for t in liste if isinstance(t, dict) and t.get("datum")]
        for t in liste:
            datetime.date.fromisoformat(t["datum"])
        antwort["hinweise"] = pruefungen.termin_hinweise(con, k["id"], kid, liste)
    except (ValueError, TypeError, AttributeError):
        raise Fehler(400, "Ungültige Angaben.")
    h.antwort(200, antwort)


def api_pruefung_hinweise(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"hinweise": pruefungen.hinweise(con, k["id"])})


def api_standard_schluessel(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        pruefungen.standard_setzen(con, k["id"], daten.get("notenschluessel_id"))
    h.antwort(200, {"standard": pruefungen.standard_schluessel(con, k["id"])})


# --- System: Update und Sicherung ---

def api_sicherung(h, con, daten):
    _admin(h, con)
    pfad = updates.sicherung(con)
    try:
        with open(pfad, "rb") as f:
            inhalt = f.read()
    finally:
        os.remove(pfad)
    h.herunterladen(inhalt, "application/zip", "lehrerkalender-sicherung-%s.zip" % db.jetzt()[:10])


def api_update(h, con, daten):
    _admin(h, con)
    h.antwort(200, updates.stand(DATEN_DIR))


def api_update_anfordern(h, con, daten):
    a = _admin(h, con)
    updates.anfordern(DATEN_DIR, daten.get("art"))
    print("Update (%s) angefordert von %s" % (daten.get("art"), a["kuerzel"]), flush=True)
    h.antwort(200, updates.stand(DATEN_DIR))


def api_vpn(h, con, daten):
    _admin(h, con)
    h.antwort(200, vpn.web_stand(DATEN_DIR))


def api_vpn_anfordern(h, con, daten):
    # Einrichten und Ausschalten aendern, wer von aussen an den Container kommt: dafuer das eigene Passwort
    a = _admin(h, con)
    if daten.get("aktion") in ("einrichten", "aus"):
        pw = con.execute("SELECT pw FROM lehrkraft WHERE id = ?", (a["id"],)).fetchone()[0]
        if not konten.passwort_stimmt(pw, daten.get("passwort") or ""):
            raise vpn.VpnFehler("Das Passwort stimmt nicht.")
    angaben = vpn.anfordern(DATEN_DIR, {k: v for k, v in daten.items() if k != "passwort"})
    print("VPN: %s angefordert von %s%s" % (angaben["aktion"], a["kuerzel"], " (Client-Datei)" if daten.get("conf") else ""),
          flush=True)
    h.antwort(200, dict(vpn.web_stand(DATEN_DIR), hinweise=angaben.get("hinweise", [])))


# --- Sicherung einspielen (Admin > System) ---

def api_wiederherstellung(h, con, daten):
    _admin(h, con)
    h.antwort(200, wiederherstellung.stand(DATEN_DIR))


def api_wiederherstellung_hochladen(h, con):
    try:
        a = _admin(h, con)
    except Fehler:
        h.close_connection = True   # Inhalt ungelesen
        raise
    o = wiederherstellung.ordner(DATEN_DIR)
    os.makedirs(o, mode=0o750, exist_ok=True)
    tmp = os.path.join(o, "upload.tmp")
    try:
        h.roh_speichern(tmp, wiederherstellung.MAX_HOCHLADEN)
        angaben = wiederherstellung.bereitlegen(tmp, DATEN_DIR)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("Sicherung hochgeladen von %s (Stand %d, %s Konten)" % (a["kuerzel"], angaben["stand"], angaben["konten"]), flush=True)
    h.antwort(200, wiederherstellung.stand(DATEN_DIR))


def api_wiederherstellung_einspielen(h, con, daten):
    # ersetzt alle Daten: dafuer das eigene Passwort
    a = _admin(h, con)
    pw = con.execute("SELECT pw FROM lehrkraft WHERE id = ?", (a["id"],)).fetchone()[0]
    if not konten.passwort_stimmt(pw, daten.get("passwort") or ""):
        raise wiederherstellung.WiederherstellungFehler("Das Passwort stimmt nicht.")
    wiederherstellung.anfordern(DATEN_DIR, str(daten.get("pruefsumme") or ""))
    with db.transaktion(con):
        db.protokoll(con, a["kuerzel"], "sicherung_einspielen_angefordert")
    print("Sicherung einspielen angefordert von %s" % a["kuerzel"], flush=True)
    h.antwort(200, wiederherstellung.stand(DATEN_DIR))


def api_wiederherstellung_verwerfen(h, con, daten):
    _admin(h, con)
    if wiederherstellung.stand(DATEN_DIR)["wartet"]:
        raise wiederherstellung.WiederherstellungFehler("Das Einspielen ist schon beauftragt.")
    wiederherstellung.verwerfen(DATEN_DIR)
    h.antwort(200, wiederherstellung.stand(DATEN_DIR))


def api_update_sicherung(h, con, daten, name):
    _admin(h, con)
    with open(updates.sicherung_pfad(DATEN_DIR, name), "rb") as f:
        h.herunterladen(f.read(), "application/zip", name)


ID = r"(\d+)"
UB_PROTOKOLL = re.compile(r"/unterrichtsbesuche/\d+/protokoll\.(pdf|odt)")
ROUTEN = [(m, re.compile(p), f) for m, p, f in [
    ("GET", r"/api/status", api_status),
    ("POST", r"/api/einrichtung", api_einrichtung),
    ("POST", r"/api/anmelden", api_anmelden),
    ("POST", r"/api/anmelden/code", api_anmelden_code),
    ("POST", r"/api/abmelden", api_abmelden),
    ("GET", r"/api/ich", api_ich),
    ("POST", r"/api/passwort", api_passwort),
    ("POST", r"/api/zweiter-faktor/beginnen", api_faktor_beginnen),
    ("POST", r"/api/zweiter-faktor/einschalten", api_faktor_einschalten),
    ("POST", r"/api/zweiter-faktor/ausschalten", api_faktor_ausschalten),
    ("POST", r"/api/zweiter-faktor/ersatzcodes", api_faktor_ersatzcodes),
    ("POST", r"/api/einladung/pruefen", api_einladung_pruefen),
    ("POST", r"/api/einladung/einloesen", api_einladung_einloesen),
    ("GET", r"/api/admin/konten", api_konten),
    ("POST", r"/api/admin/konten/" + ID, api_konto_aendern),
    ("POST", r"/api/admin/einladungen", api_einladung_anlegen),
    ("POST", r"/api/admin/einladungen/" + ID + "/zurueckziehen", api_einladung_zurueckziehen),
    ("GET", r"/api/grunddaten", api_grunddaten),
    ("GET", r"/api/schule/logo", api_logo),
    ("GET", r"/api/schule/logo/da", api_logo_da),
    ("POST", r"/api/schule", api_schule),
    ("POST", r"/api/formularvorlage", api_formularvorlage),
    ("GET", r"/api/ub/seite/(uebersicht|einstellungen)", api_ub_seite),
    ("GET", r"/api/ub/seite/(besuch)/" + ID, api_ub_seite),
    ("POST", r"/api/ub/modul", api_ub_modul),
    ("GET", r"/api/files/([a-f0-9]{32})/([^/]+)", api_ub_datei),
    ("GET", r"/unterrichtsbesuche/" + ID + r"/protokoll\.(pdf|odt)", api_ub_protokoll),
    ("POST", r"/api/ub/einstellungen-allgemein", _ub_schritt(lambda k, d: ub.standard_ordnung_setzen(k, d))),
    ("GET", r"/api/ub/katalog", _ub_schritt(lambda k, d: ub.katalog(k), lesen=True)),
    ("POST", r"/api/ub/einstellungen/(kategorien|phasen|kriterien)", _ub_schritt(lambda k, d, art: ub.einstellung_anlegen(k, art, d))),
    ("POST", r"/api/ub/einstellungen/(kategorien|phasen|kriterien)/reihenfolge",
     _ub_schritt(lambda k, d, art: ub.einstellung_reihenfolge(k, art, d.get("ids")))),
    ("POST", r"/api/ub/einstellungen/(kategorien|phasen|kriterien)/" + ID + "/save", _ub_schritt(lambda k, d, art, oid: ub.einstellung_speichern(k, art, oid, d))),
    ("POST", r"/api/ub/einstellungen/(kategorien|phasen|kriterien)/" + ID + "/delete", _ub_schritt(lambda k, d, art, oid: ub.einstellung_loeschen(k, art, oid))),
    ("POST", r"/api/ub/anwaerter", _ub_schritt(lambda k, d: {"ok": True, "anwaerter": ub.anwaerter_dict(ub._anwaerter_zeile(k, ub.anwaerter_anlegen(k, d)))})),
    ("POST", r"/api/ub/anwaerter/" + ID + "/save", _ub_schritt(lambda k, d, aid: ub.anwaerter_speichern(k, aid, d))),
    ("GET", r"/api/ub/anwaerter/" + ID + "/besuche", _ub_schritt(lambda k, d, aid: ub.anwaerter_besuche(k, aid), lesen=True)),
    ("POST", r"/api/ub/anwaerter/" + ID + "/delete", _ub_schritt(lambda k, d, aid: ub.anwaerter_loeschen(k, aid))),
    ("POST", r"/api/ub/besuche", _ub_schritt(lambda k, d: ub.besuch_anlegen(k, d))),
    ("GET", r"/api/ub/besuche/" + ID, _ub_schritt(lambda k, d, bid: {"ok": True, "besuch": ub.besuch_dict(k, ub.besuch_obj(k, bid), True)}, lesen=True)),
    ("POST", r"/api/ub/besuche/" + ID + "/save", _ub_schritt(lambda k, d, bid: ub.besuch_speichern(k, bid, d))),
    ("POST", r"/api/ub/besuche/" + ID + "/delete", _ub_schritt(lambda k, d, bid: ub.besuch_loeschen(k, bid))),
    ("POST", r"/api/ub/besuche/" + ID + "/eintraege", _ub_schritt(lambda k, d, bid: ub.eintrag_anlegen(k, bid, d))),
    ("POST", r"/api/ub/eintraege/" + ID + "/save", _ub_schritt(lambda k, d, eid: ub.eintrag_speichern(k, eid, d))),
    ("POST", r"/api/ub/eintraege/" + ID + "/delete", _ub_schritt(lambda k, d, eid: ub.eintrag_loeschen(k, eid))),
    ("POST", r"/api/ub/eintraege/" + ID + "/foto", _ub_schritt(lambda k, d, eid: ub.foto_speichern(k, eid, d))),
    ("POST", r"/api/ub/eintraege/" + ID + "/foto/delete", _ub_schritt(lambda k, d, eid: ub.foto_loeschen(k, eid))),
    ("GET", r"/api/ub/eintraege/" + ID + "/skizze", _ub_schritt(lambda k, d, eid: ub.skizze_lesen(k, eid), lesen=True)),
    ("POST", r"/api/ub/eintraege/" + ID + "/skizze", _ub_schritt(lambda k, d, eid: ub.skizze_speichern(k, eid, d))),
    ("POST", r"/api/ub/eintraege/" + ID + "/skizze/delete", _ub_schritt(lambda k, d, eid: ub.skizze_loeschen(k, eid))),
    ("GET", r"/api/formulare", api_formulare),
    ("GET", r"/api/formulare/vorschau", api_formular_vorschau),
    ("POST", r"/api/formulare/stundenplanaenderung", api_formular_erstellen),
    ("GET", r"/api/formular/" + ID + r"\.pdf", api_formular_pdf),
    ("POST", r"/api/formular/" + ID + "/stand", api_formular_stand),
    ("POST", r"/api/formular/" + ID + "/loeschen", api_formular_loeschen),
    ("GET", r"/api/unterschrift/(unterschrift|paraphe)", api_unterschrift),
    ("POST", r"/api/unterschrift", api_unterschrift_setzen),
    ("POST", r"/api/admin/bildungsgang", _grunddaten_schritt("bildungsgang_angelegt", grunddaten.bildungsgang_speichern)),
    ("POST", r"/api/admin/bildungsgang/" + ID, _grunddaten_schritt("bildungsgang_geaendert",
                                                                   lambda con, d, i: grunddaten.bildungsgang_speichern(con, d, i), True)),
    ("POST", r"/api/admin/bildungsgang/" + ID + "/loeschen", _grunddaten_schritt("bildungsgang_geloescht",
                                                                                 _nur_id(grunddaten.bildungsgang_loeschen), True)),
    ("POST", r"/api/admin/stufe", _grunddaten_schritt("stufe_angelegt", grunddaten.stufe_speichern)),
    ("POST", r"/api/admin/stufe/" + ID, _grunddaten_schritt("stufe_geaendert",
                                                            lambda con, d, i: grunddaten.stufe_speichern(con, d, i), True)),
    ("POST", r"/api/admin/stufe/" + ID + "/loeschen", _grunddaten_schritt("stufe_geloescht", _nur_id(grunddaten.stufe_loeschen), True)),
    ("POST", r"/api/admin/lernfeld", _grunddaten_schritt("lernfeld_angelegt", grunddaten.lernfeld_speichern)),
    ("POST", r"/api/admin/lernfeld/" + ID, _grunddaten_schritt("lernfeld_geaendert",
                                                               lambda con, d, i: grunddaten.lernfeld_speichern(con, d, i), True)),
    ("POST", r"/api/admin/lernfeld/" + ID + "/loeschen", _grunddaten_schritt("lernfeld_geloescht",
                                                                             _nur_id(grunddaten.lernfeld_loeschen), True)),
    ("POST", r"/api/admin/zeitraster", _grunddaten_schritt("zeitraster_geaendert", _zeitraster)),
    ("POST", r"/api/admin/a-woche", _grunddaten_schritt("a_woche_geaendert", _a_woche)),
    ("POST", r"/api/admin/schuljahr", _grunddaten_schritt("schuljahr_angelegt", grunddaten.schuljahr_speichern)),
    ("POST", r"/api/admin/schuljahr/" + ID, _grunddaten_schritt("schuljahr_geaendert",
                                                                lambda con, d, i: grunddaten.schuljahr_speichern(con, d, i), True)),
    ("POST", r"/api/admin/schuljahr/" + ID + "/loeschen", _grunddaten_schritt("schuljahr_geloescht",
                                                                              _nur_id(grunddaten.schuljahr_loeschen), True)),
    ("POST", r"/api/admin/ferien", _grunddaten_schritt("ferien_angelegt", grunddaten.ferien_anlegen)),
    ("POST", r"/api/admin/ferien/" + ID + "/loeschen", _grunddaten_schritt("ferien_geloescht", _nur_id(grunddaten.ferien_loeschen), True)),
    ("POST", r"/api/admin/klasse", _grunddaten_schritt("klasse_angelegt", grunddaten.klasse_speichern)),
    ("POST", r"/api/admin/klasse/" + ID, _grunddaten_schritt("klasse_geaendert",
                                                             lambda con, d, i: grunddaten.klasse_speichern(con, d, i), True)),
    ("POST", r"/api/admin/klasse/" + ID + "/loeschen", _grunddaten_schritt("klasse_geloescht", _nur_id(grunddaten.klasse_loeschen), True)),
    ("GET", r"/api/notenschluessel/vorgabe", api_schluessel_vorgabe),
    ("POST", r"/api/notenschluessel/probe", api_schluessel_probe),
    ("POST", r"/api/notenschluessel", api_schluessel_anlegen),
    ("POST", r"/api/notenschluessel/" + ID, api_schluessel_aendern),
    ("POST", r"/api/notenschluessel/" + ID + "/kopieren", api_schluessel_kopieren),
    ("POST", r"/api/notenschluessel/" + ID + "/loeschen", api_schluessel_loeschen),
    ("GET", r"/api/admin/protokoll", api_protokoll),
    ("GET", r"/api/stundenplan", api_stundenplan),
    ("POST", r"/api/stundenplan/version", _stundenplan_schritt(lambda con, lid, d, _: stundenplan.version_anlegen(con, lid, d))),
    ("POST", r"/api/stundenplan/version/" + ID, _stundenplan_schritt(lambda con, lid, d, vid: stundenplan.version_aendern(con, lid, vid, d))),
    ("POST", r"/api/stundenplan/version/" + ID + "/loeschen",
     _stundenplan_schritt(lambda con, lid, d, vid: stundenplan.version_loeschen(con, lid, vid))),
    ("POST", r"/api/stundenplan/version/" + ID + "/feld",
     _stundenplan_schritt(lambda con, lid, d, vid: stundenplan.feld_setzen(con, lid, vid, d))),
    ("POST", r"/api/stundenplan/version/" + ID + "/tag-kopieren",
     _stundenplan_schritt(lambda con, lid, d, vid: stundenplan.tag_kopieren(con, lid, vid, d.get("von"), d.get("nach")))),
    ("POST", r"/api/gruppe", _stundenplan_schritt(lambda con, lid, d, _: stundenplan.gruppe_speichern(con, lid, d))),
    ("POST", r"/api/gruppe/" + ID, _stundenplan_schritt(lambda con, lid, d, gid: stundenplan.gruppe_speichern(con, lid, d, gid))),
    ("POST", r"/api/gruppe/" + ID + "/loeschen",
     _stundenplan_schritt(lambda con, lid, d, gid: stundenplan.gruppe_loeschen(con, lid, gid))),
    ("GET", r"/api/woche", api_woche),
    ("GET", r"/api/abos", api_abos),
    ("GET", r"/api/schueler", api_schueler),
    ("POST", r"/api/schueler", _pr_schritt(lambda con, k, d, _: pruefungen.schueler_speichern(con, k["id"], d))),
    ("POST", r"/api/schueler/" + ID, _pr_schritt(lambda con, k, d, i: pruefungen.schueler_speichern(con, k["id"], d, i))),
    ("POST", r"/api/schueler/" + ID + "/loeschen", _pr_schritt(lambda con, k, d, i: pruefungen.schueler_loeschen(con, k["id"], i))),
    ("POST", r"/api/schueler/moodle", api_moodle_csv),
    ("POST", r"/api/vorlage", _pr_schritt(lambda con, k, d, _: pruefungen.vorlage_speichern(con, k["id"], d))),
    ("POST", r"/api/vorlage/" + ID, _pr_schritt(lambda con, k, d, i: pruefungen.vorlage_speichern(con, k["id"], d, i))),
    ("POST", r"/api/vorlage/" + ID + "/loeschen", _pr_schritt(lambda con, k, d, i: pruefungen.vorlage_loeschen(con, k["id"], i))),
    ("GET", r"/api/pruefungen", api_pruefungen),
    ("GET", r"/api/pruefungen/hinweise", api_pruefung_hinweise),
    ("GET", r"/api/pruefungen/unterricht", api_unterricht),
    ("POST", r"/api/pruefung", _pr_schritt(lambda con, k, d, _: pruefungen.pruefung_speichern(con, k["id"], d))),
    ("GET", r"/api/pruefung/" + ID, api_pruefung),
    ("GET", r"/api/pruefung/" + ID + "/export", api_export),
    ("POST", r"/api/moodle/vorschau", api_moodle_vorschau),
    ("POST", r"/api/moodle/uebernehmen", api_moodle_uebernehmen),
    ("GET", r"/api/pruefung/" + ID + r"/ergebnis\.pdf", api_ergebnis_pdf),
    ("GET", r"/api/pruefung/" + ID + r"/rueckmeldung\.pdf", api_rueckmeldung_pdf),
    ("GET", r"/api/pruefung/" + ID + r"/moodle\.csv", api_moodle_export),
    ("POST", r"/api/pruefung/" + ID, _pr_schritt(lambda con, k, d, i: pruefungen.pruefung_speichern(con, k["id"], d, i))),
    ("POST", r"/api/pruefung/" + ID + "/loeschen", _pr_schritt(lambda con, k, d, i: pruefungen.pruefung_loeschen(con, k["id"], i))),
    ("POST", r"/api/pruefung/" + ID + "/bewertung/" + ID, api_bewertung),
    ("POST", r"/api/pruefung/" + ID + "/abschliessen", api_abschliessen),
    ("POST", r"/api/pruefung/" + ID + "/oeffnen", api_wieder_oeffnen),
    ("POST", r"/api/pruefung/" + ID + "/team", lambda h, con, d, pid: api_team(h, con, d, pid)),
    ("POST", r"/api/pruefung/" + ID + "/team/" + ID, lambda h, con, d, pid, tid: api_team(h, con, d, pid, tid)),
    ("POST", r"/api/pruefung/" + ID + "/team/" + ID + "/loeschen", lambda h, con, d, pid, tid: api_team(h, con, d, pid, tid, True)),
    ("POST", r"/api/pruefung/" + ID + "/teams/bilden", api_teams_bilden),
    ("POST", r"/api/pruefung/" + ID + "/einstellungen", _pm_schritt(lambda con, l, pid, d, _: pruefungen.einstellungen_setzen(con, l, pid, d))),
    ("POST", r"/api/pruefung/" + ID + "/frage", _pm_schritt(lambda con, l, pid, d, _: pruefungen.frage_speichern(con, l, pid, d))),
    ("POST", r"/api/pruefung/" + ID + "/frage/" + ID, _pm_schritt(lambda con, l, pid, d, fid: pruefungen.frage_speichern(con, l, pid, d, fid))),
    ("POST", r"/api/pruefung/" + ID + "/frage/" + ID + "/loeschen", _pm_schritt(lambda con, l, pid, d, fid: pruefungen.frage_loeschen(con, l, pid, fid))),
    ("POST", r"/api/pruefung/" + ID + "/fragen/einfuegen", _pm_schritt(lambda con, l, pid, d, _: pruefungen.fragen_einfuegen(con, l, pid, d.get("text")))),
    ("POST", r"/api/pruefung/" + ID + "/ziehen/" + ID, _pm_schritt(lambda con, l, pid, d, sid: pruefungen.frage_ziehen(con, l, pid, sid))),
    ("POST", r"/api/pruefung/" + ID + "/protokoll", _pm_schritt(lambda con, l, pid, d, _: pruefungen.protokoll_speichern(con, l, pid, d))),
    ("POST", r"/api/pruefung/" + ID + "/protokoll/" + ID, _pm_schritt(lambda con, l, pid, d, eid: pruefungen.protokoll_speichern(con, l, pid, d, eid))),
    ("POST", r"/api/pruefung/" + ID + "/protokoll/" + ID + "/loeschen", _pm_schritt(lambda con, l, pid, d, eid: pruefungen.protokoll_loeschen(con, l, pid, eid))),
    ("POST", r"/api/pruefung/" + ID + "/lauf/" + ID, _pm_schritt(lambda con, l, pid, d, sid: pruefungen.lauf_setzen(con, l, pid, sid, d.get("aktion")))),
    ("POST", r"/api/notenschluessel/standard", api_standard_schluessel),
    ("POST", r"/api/abo", _abo_schritt(lambda con, k, d, _: abos.speichern(con, k, d), "abo_angelegt")),
    ("POST", r"/api/abo/" + ID, _abo_schritt(lambda con, k, d, i: abos.speichern(con, k, d, i), "abo_geaendert")),
    ("POST", r"/api/abo/" + ID + "/loeschen", _abo_schritt(lambda con, k, d, i: abos.loeschen(con, k, i), "abo_geloescht")),
    ("POST", r"/api/abo/" + ID + "/abrufen", api_abo_abrufen),
    ("GET", r"/api/bibliothek", api_bibliothek),
    ("POST", r"/api/baustein", _planung_schritt(lambda con, k, d, _: planung.baustein_speichern(con, k, d))),
    ("POST", r"/api/baustein/" + ID, _planung_schritt(lambda con, k, d, i: planung.baustein_speichern(con, k, d, i))),
    ("POST", r"/api/baustein/" + ID + "/loeschen", _planung_schritt(lambda con, k, d, i: planung.baustein_loeschen(con, k, i))),
    ("POST", r"/api/baustein/" + ID + "/schieben",
     _planung_schritt(lambda con, k, d, i: planung.baustein_schieben(con, k, i, d.get("richtung") or 1))),
    ("GET", r"/api/planung", api_planung),
    ("GET", r"/api/stunde", api_stunde),
    ("POST", r"/api/ist", api_ist),
    ("POST", r"/api/stunde/eintrag", api_stunde_eintrag),
    ("GET", r"/api/dokumente/konfig", api_dokumente_konfig),
    ("POST", r"/api/dokumente/konfig", api_dokumente_konfig_speichern),
    ("POST", r"/api/dokumente/konfig/loeschen", api_dokumente_konfig_loeschen),
    ("GET", r"/api/dokumente/stammlisten", api_dokumente_stammlisten),
    ("GET", r"/api/dokumente/aufgabe", api_dokumente_aufgabe),
    ("POST", r"/api/dokumente/ablegen", api_dokumente_ablegen),
    ("GET", r"/api/pruefung/" + ID + r"/dokumente", api_pruefung_dokumente),
    ("POST", r"/api/pruefung/" + ID + r"/dokumente", api_pruefung_dokument_anhaengen),
    ("POST", r"/api/pruefung/" + ID + r"/dokumente/" + ID + r"/loesen", api_pruefung_dokument_loesen),
    ("GET", r"/api/dokumente", api_dokumente),
    ("GET", r"/api/dokumente/" + ID, api_dokument),
    ("POST", r"/api/dokumente/" + ID, api_dokument_aendern),
    ("GET", r"/api/dokumente/" + ID + r"/(preview|thumb|download)", api_dokument_datei),
    ("POST", r"/api/dokumente/" + ID + r"/notiz", api_dokument_notiz),
    ("POST", r"/api/dokumente/" + ID + r"/notiz/" + ID + r"/loeschen", api_dokument_notiz_loeschen),
    ("GET", r"/api/ist/offen", api_ist_offen),
    ("POST", r"/api/ist/alle", api_ist_alle),
    ("POST", r"/api/planung/uebernehmen", _planung_schritt(lambda con, k, d, _: planung.aus_bibliothek(con, k["id"], d))),
    ("POST", r"/api/thema", _planung_schritt(lambda con, k, d, _: planung.thema_speichern(con, k["id"], d))),
    ("POST", r"/api/thema/" + ID, _planung_schritt(lambda con, k, d, i: planung.thema_speichern(con, k["id"], d, i))),
    ("POST", r"/api/thema/" + ID + "/loeschen", _planung_schritt(lambda con, k, d, i: planung.thema_loeschen(con, k["id"], i))),
    ("POST", r"/api/thema/" + ID + "/schieben",
     _planung_schritt(lambda con, k, d, i: planung.thema_schieben(con, k["id"], i, d.get("richtung") or 1))),
    ("POST", r"/api/thema/" + ID + "/stelle",
     _planung_schritt(lambda con, k, d, i: planung.thema_an_stelle(con, k["id"], i, d.get("stelle")))),
    ("POST", r"/api/ls", _planung_schritt(lambda con, k, d, _: planung.ls_speichern(con, k["id"], d))),
    ("POST", r"/api/ls/" + ID, _planung_schritt(lambda con, k, d, i: planung.ls_speichern(con, k["id"], d, i))),
    ("POST", r"/api/ls/" + ID + "/loeschen", _planung_schritt(lambda con, k, d, i: planung.ls_loeschen(con, k["id"], i))),
    ("POST", r"/api/ls/" + ID + "/schieben",
     _planung_schritt(lambda con, k, d, i: planung.ls_schieben(con, k["id"], i, d.get("richtung") or 1))),
    ("POST", r"/api/thema/" + ID + "/festsetzen",
     _planung_schritt(lambda con, k, d, i: planung.festsetzen(con, k["id"], i, d.get("datum"), d.get("beginn")))),
    ("POST", r"/api/aenderung", _eigene_schritt(lambda con, lid, d, _: stundenplan.aenderung_anlegen(con, lid, d))),
    ("POST", r"/api/aenderung/" + ID + "/loeschen", _eigene_schritt(lambda con, lid, d, aid: stundenplan.aenderung_loeschen(con, lid, aid))),
    ("POST", r"/api/termin", _eigene_schritt(lambda con, lid, d, _: stundenplan.termin_speichern(con, lid, d))),
    ("POST", r"/api/termin/" + ID, _eigene_schritt(lambda con, lid, d, tid: stundenplan.termin_speichern(con, lid, d, tid))),
    ("POST", r"/api/termin/" + ID + "/loeschen", _eigene_schritt(lambda con, lid, d, tid: stundenplan.termin_loeschen(con, lid, tid))),
    ("GET", r"/api/admin/sicherung\.zip", api_sicherung),
    ("GET", r"/api/admin/update", api_update),
    ("POST", r"/api/admin/update", api_update_anfordern),
    ("GET", r"/api/admin/vpn", api_vpn),
    ("GET", r"/api/admin/kollegium", api_admin_kollegium),
    ("POST", r"/api/admin/kollegium", api_admin_kollegium_setzen),
    ("POST", r"/api/admin/vpn", api_vpn_anfordern),
    ("GET", r"/api/admin/update/sicherung/(vor-(?:update|wiederherstellung)-[0-9_-]+\.zip)", api_update_sicherung),
    ("GET", r"/api/admin/wiederherstellung", api_wiederherstellung),
    ("POST", r"/api/admin/wiederherstellung/einspielen", api_wiederherstellung_einspielen),
    ("POST", r"/api/admin/wiederherstellung/verwerfen", api_wiederherstellung_verwerfen),
]]

# Datei-Uploads ohne JSON (POST, Inhalt = Datei): eigener Weg in _verteilen, der Aufgerufene liest selbst
ROH_ROUTEN = {"/api/admin/wiederherstellung/hochladen": api_wiederherstellung_hochladen,
              "/api/dokumente/hochladen": api_dokumente_hochladen}


# --- HTTP neben HTTPS: nur Umleitung und /ca.crt ---

class UmleitHandler(Handler):
    nur_umleiten = True


class TLSServer(ThreadingHTTPServer):
    """HTTPS. Der TLS-Handschlag laeuft im Thread der Anfrage, nicht in der Annahmeschleife: ein Client, der die
    Verbindung oeffnet und dann nichts schickt, haelt so niemanden auf."""
    daemon_threads = True
    ist_tls = True

    def __init__(self, adresse, handler, kontext, db_pfad):
        super().__init__(adresse, handler)
        self.kontext = kontext
        self.db_pfad = db_pfad

    def finish_request(self, request, client_address):
        request.settimeout(Handler.timeout)
        try:
            tls = self.kontext.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):   # z.B. Browser lehnt das Zertifikat ab
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            # nur die Schreibrichtung schliessen und den Rest noch lesen: ein hartes Schliessen mit ungelesenen Daten
            # schickt ein RST, und der Browser verwirft dann womoeglich die schon gesendete Antwort
            try:
                tls.shutdown(socket.SHUT_WR)
                tls.settimeout(1.0)
                while tls.recv(4096):
                    pass
            except (OSError, ssl.SSLError):
                pass
            tls.close()


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    ist_tls = False

    def __init__(self, adresse, handler, db_pfad=None):
        super().__init__(adresse, handler)
        self.db_pfad = db_pfad


def tls_kontext():
    zert, schluessel = os.path.join(TLS_DIR, "server.crt"), os.path.join(TLS_DIR, "server.key")
    if not (os.path.exists(zert) and os.path.exists(schluessel)):
        return None
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    kontext.load_cert_chain(zert, schluessel)
    return kontext


def main():
    con = db.oeffnen(DATEN_DIR)
    code = konten.einrichtungscode(con)
    con.close()
    db_pfad = db.pfad(DATEN_DIR)
    kontext = None if OHNE_TLS else tls_kontext()
    if kontext is None:
        if not OHNE_TLS:
            print("HTTPS aus: kein Zertifikat in %s (lehrerkalender-tls). Alles laeuft ueber HTTP." % TLS_DIR, flush=True)
        server = HTTPServer((BIND, HTTP_PORT), Handler, db_pfad)
        print("Lehrerkalender MT %s auf http://%s:%d" % (VERSION, BIND, HTTP_PORT), flush=True)
    else:
        server = TLSServer((BIND, HTTPS_PORT), Handler, kontext, db_pfad)
        umleitung = HTTPServer((BIND, HTTP_PORT), UmleitHandler, db_pfad)
        threading.Thread(target=umleitung.serve_forever, daemon=True).start()
        print("Lehrerkalender MT %s auf https://%s:%d (http :%d leitet um)" % (VERSION, BIND, HTTPS_PORT, HTTP_PORT), flush=True)
    if code:
        print("Noch kein Konto: Einrichtung unter /einrichtung, Code mit  lehrerkalender einrichtungscode", flush=True)
    threading.Thread(target=abos_im_hintergrund, args=(db_pfad,), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
