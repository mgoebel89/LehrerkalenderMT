"""Zweiter Faktor mit Einmalcodes aus einer Authenticator-App (TOTP nach RFC 6238: SHA-1, 6 Ziffern, 30 Sekunden),
ohne Zusatzpakete. Dazu Ersatzcodes zum Ausdrucken, falls das Handy fehlt (jeder nur einmal gueltig).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

SCHRITT = 30
STELLEN = 6
FENSTER = 1            # ein Schritt davor und danach gilt auch (Uhren gehen selten genau)
ERSATZ_ANZAHL = 10


def geheimnis_neu():
    """Zufaelliges Geheimnis (160 Bit) in Base32 ohne Fuellzeichen, wie Authenticator-Apps es erwarten."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _schluessel(geheimnis):
    text = geheimnis.strip().replace(" ", "").upper()
    return base64.b32decode(text + "=" * (-len(text) % 8))


def code(geheimnis, zaehler):
    digest = hmac.new(_schluessel(geheimnis), struct.pack(">Q", zaehler), hashlib.sha1).digest()
    versatz = digest[-1] & 0x0F
    zahl = struct.unpack(">I", digest[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return str(zahl % 10 ** STELLEN).zfill(STELLEN)


def zaehler_jetzt(uhr=None):
    return int((time.time() if uhr is None else uhr) // SCHRITT)


def pruefen(geheimnis, eingabe, zuletzt=0, uhr=None):
    """Zaehler des passenden Codes, sonst None. Ein Code, dessen Zaehler nicht neuer als `zuletzt` ist, gilt nicht
    (sonst liesse sich ein mitgelesener Code gleich noch einmal benutzen)."""
    eingabe = "".join(z for z in str(eingabe or "") if z.isdigit())
    if len(eingabe) != STELLEN or not geheimnis:
        return None
    jetzt = zaehler_jetzt(uhr)
    for z in range(jetzt - FENSTER, jetzt + FENSTER + 1):
        if z > zuletzt and hmac.compare_digest(code(geheimnis, z), eingabe):
            return z
    return None


def adresse(geheimnis, konto, aussteller="Lehrerkalender MT"):
    """otpauth-Adresse fuer den QR-Code der Authenticator-App."""
    etikett = urllib.parse.quote("%s:%s" % (aussteller, konto))
    return "otpauth://totp/%s?secret=%s&issuer=%s&digits=%d&period=%d" % (
        etikett, geheimnis, urllib.parse.quote(aussteller), STELLEN, SCHRITT)


def ersatzcodes_neu():
    """(Klartext-Liste zum Anzeigen, Liste der Pruefsummen zum Speichern)."""
    klar = ["%s-%s" % (secrets.token_hex(2).upper(), secrets.token_hex(2).upper()) for _ in range(ERSATZ_ANZAHL)]
    return klar, [_ersatz_summe(c) for c in klar]


def _ersatz_summe(text):
    return hashlib.sha256(text.strip().upper().replace(" ", "").encode("utf-8")).hexdigest()


def ersatzcode_einloesen(summen, eingabe):
    """Restliche Pruefsummen ohne den eingeloesten Code, oder None, wenn er nicht passt."""
    s = _ersatz_summe(eingabe or "")
    for i, vorhanden in enumerate(summen):
        if hmac.compare_digest(vorhanden, s):
            return summen[:i] + summen[i + 1:]
    return None
