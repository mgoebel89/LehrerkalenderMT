"""Webserver: alles ueber HTTPS (Port 443). HTTP (Port 80) liefert nur das Stammzertifikat (/ca.crt) und leitet sonst
nach HTTPS um (Bauweise wie TrackingDRS und Lernbuero MT).

Ohne Zertifikat (oder mit LEHRERKALENDER_OHNE_TLS=1 zum lokalen Testen) laeuft die ganze Seite ueber HTTP.
Umgebungsvariablen: LEHRERKALENDER_DATEN, LEHRERKALENDER_TLS_DIR, LEHRERKALENDER_HTTPS_PORT, LEHRERKALENDER_HTTP_PORT,
LEHRERKALENDER_BIND, LEHRERKALENDER_OHNE_TLS.

Alle Aenderungen laufen ueber POST mit JSON und dem Kopf X-Lehrerkalender: 1 (Schutz vor fremden Formularen).
"""
import datetime
import json
import mimetypes
import os
import re
import socket
import ssl
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, abos, db, grunddaten, konten, notenschluessel, planung, qr, stundenplan, totp, updates

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
        name = urllib.parse.quote(dateiname)
        self.antwort(200, inhalt, typ, extra=[("Content-Disposition", "attachment; filename*=UTF-8''%s" % name)])

    def body(self):
        """JSON-Inhalt einer POST-Anfrage. Liest immer den ganzen Inhalt (sonst bricht die Verbindung ab)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if laenge > MAX_BODY:
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
            if methode == "GET" and not pfad.startswith("/api/"):
                return self.seite(con, pfad)
            for m, muster, funktion in ROUTEN:
                treffer = muster.fullmatch(pfad)
                if m == methode and treffer:
                    daten = self.body() if methode == "POST" else {}
                    return funktion(self, con, daten, *treffer.groups())
            if methode == "POST":
                self.body()
            raise Fehler(404, "Nicht gefunden.")
        except Fehler as f:
            self.antwort(f.status, {"fehler": f.meldung})
        except (konten.KontoFehler, grunddaten.GrunddatenFehler, notenschluessel.SchluesselFehler, qr.QrFehler,
                stundenplan.StundenplanFehler, planung.PlanungFehler, abos.AboFehler, updates.UpdateFehler) as f:
            self.antwort(400, {"fehler": str(f)})
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.timeout):
            pass
        except Exception as f:   # unerwartet: protokollieren, aber nichts Internes verraten
            print("FEHLER %s %s: %r" % (methode, pfad, f), file=sys.stderr, flush=True)
            try:
                self.antwort(500, {"fehler": "Interner Fehler. Bitte später noch einmal versuchen."})
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
    h.antwort(200, {"konto": k, "version": VERSION, "update": updates.kurz() if k["rolle"] == "admin" else None})


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
    h.antwort(200, alles)


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
    antwort = {"schuljahre": jahre, "schuljahr_id": sid, "straenge": [], "plan": None}
    if sid:
        antwort["straenge"] = planung.straenge(con, k["id"], sid)
        kid = h.abfrage("klasse")
        if kid:
            gid = h.abfrage("gruppe")
            antwort["plan"] = planung.plan(con, k["id"], _ganzzahl(kid), _ganzzahl(gid) if gid else None, sid)
    h.antwort(200, antwort)


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


def api_update_sicherung(h, con, daten, name):
    _admin(h, con)
    with open(updates.sicherung_pfad(DATEN_DIR, name), "rb") as f:
        h.herunterladen(f.read(), "application/zip", name)


ID = r"(\d+)"
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
    ("GET", r"/api/admin/update/sicherung/(vor-update-[0-9_-]+\.zip)", api_update_sicherung),
]]


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
