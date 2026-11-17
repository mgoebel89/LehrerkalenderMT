"""WireGuard (Stufe G): Zugriff von zuhause ueber das bestehende VPN (aus TrackingDRS uebernommen).

Der Container wird Teilnehmer im WireGuard-VPN. Ueber das VPN nimmt er nur HTTPS (443) an und antwortet ueber das VPN
zurueck. Von zuhause erreichbar ist er unter seiner ZUGRIFFSADRESSE: vorbelegt mit der Schuladresse (z. B. 172.20.5.191),
aenderbar. Der Container haengt sie fest an wg0, sie gilt also auch dann weiter, wenn sich seine Adresse in der Schule
aendert; VPS und Geraete leiten diese eine Adresse ins VPN (Kopiervorlagen auf der Seite). Sie muss im /16-Netz der
Schuladresse liegen: dann reicht die bisherige Zertifizierungsstelle, und das Stammzertifikat auf den Geraeten bleibt.
Die VPN-Adresse kommt nur auf Wunsch ins Zertifikat (ausserhalb des bisherigen Netzes = neue Zertifizierungsstelle).

Aufruf aus deploy/vpn.sh (als root, im Programmordner):
  python3 -m app.vpn pruefen <server:port> <schluessel> <adresse> "<netze>" [<server-ip>]
    Ausgabe: adresse|netze|server-ip (bereinigt), sonst eine Fehlermeldung und Exit 1.
  python3 -m app.vpn anfrage-lesen <datei>
    Auftrag aus Admin > System lesen, loeschen, pruefen. Ausgabe: aktion|server|schluessel|adresse|netze|server-ip|
    server-if|psk|aus_datei|alle|zertifikat|zugriff (bei pruefen/aus nur die Aktion; zugriff leer = Schuladresse).
  python3 -m app.vpn zugriff <zugriffsadresse> <vpn-adresse> "<netze>" <server-ip>
    Zugriffsadresse pruefen. Ausgabe: die Adresse (leer = Schuladresse nehmen), sonst Fehlermeldung und Exit 1.
  python3 -m app.vpn conf-lesen <client-datei>
    Wie anfrage-lesen, aber aus einer WireGuard-Datei fuer den Container (lehrerkalender vpn einrichten --conf). Legt
    den privaten Schluessel (und PresharedKey) aus der Datei nach /etc/wireguard. Ausgabe wie oben.
  python3 -m app.vpn info-ablegen <oeffentlicher schluessel des containers> <aktiv 0|1> [<schnittstelle auf dem server>]
                                  [<aus datei 0|1>]
    Oeffentliche Angaben fuer die Seite nach <VPN_DIR>/einrichtung.json.
  python3 -m app.vpn verbindung [--leise]
    Steht die Verbindung (Handshake in den letzten 5 Minuten)? Ergebnis nach <VPN_DIR>/verbindung.json.
"""
import base64
import datetime
import ipaddress
import json
import os
import re
import socket
import stat
import subprocess
import sys

from . import db

KONF = "/etc/wireguard/wg0.conf"
SCHLUESSEL = "/etc/wireguard/lehrerkalender.key"   # privater Schluessel des Containers (nur root)
PSK = "/etc/wireguard/lehrerkalender.psk"          # PresharedKey, nur wenn die Client-Datei einen hat
TLS_IPS = "/etc/lehrerkalender/tls-ips"            # zusaetzliche Adressen im Zertifikat (deploy/tls.sh)
VPN_DIR = os.environ.get("LEHRERKALENDER_VPN_DIR", "/var/lib/lehrerkalender-vpn")
EINHEIT = os.environ.get("LEHRERKALENDER_VPN_EINHEIT", "/etc/systemd/system/lehrerkalender-vpn-anfrage.path")
HANDSHAKE_MAX = 300   # Sekunden; mit Keepalive 25 erneuert WireGuard den Handshake alle 2 Minuten
AKTIONEN = ("einrichten", "pruefen", "aus", "ziele")
MAX_ZIELE = 10
SCHNITTSTELLE = re.compile(r"[A-Za-z0-9_.=-]{1,15}")
LAUF_MAX = datetime.timedelta(minutes=10)   # haengt ein Auftrag laenger, darf ein neuer kommen


class VpnFehler(Exception):
    pass


def _schnittstellen():
    """[(name, ip_interface)] der Schnittstellen ausser wg0 (eth0 im Schulnetz)."""
    aus = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
    liste = []
    for zeile in aus.splitlines():
        teile = zeile.split()
        if len(teile) >= 4 and teile[2] == "inet" and teile[1] != "wg0":
            liste.append((teile[1], ipaddress.ip_interface(teile[3])))
    return liste


def eigene_netze():
    """Netze der anderen Schnittstellen (eth0 im Schulnetz): das VPN darf sie nicht ueberdecken."""
    return [(name, i.network) for name, i in _schnittstellen()]


def schuladressen():
    """Adressen des Containers im Schulnetz: ueber das VPN ebenfalls erreichbar, wenn der VPS sie dorthin leitet."""
    try:
        return [str(i.ip) for _, i in _schnittstellen()]
    except (OSError, ValueError):
        return []


def pruefen(server, schluessel, adresse, netze, server_ip="", lokal=()):
    """Gibt (adresse, [netze], server_ip) zurueck oder wirft VpnFehler mit einem Hinweis, wo die Angabe steht.
    netze sind die Ziele, die der Container ueber den Tunnel erreicht (Routen). Wer ihn ueber das VPN erreichen darf,
    regelt "alle Absender", nicht diese Liste."""
    server = (server or "").strip()
    m = re.fullmatch(r"([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):(\d{1,5})", server)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise VpnFehler("Server bitte als Adresse:Port, z. B. vpn.example.de:51820 (Port = ListenPort der Server-Config).")
    try:
        roh = base64.b64decode((schluessel or "").strip(), validate=True)
    except ValueError:
        roh = b""
    if len(roh) != 32:
        raise VpnFehler("Der öffentliche Schlüssel des Servers hat 44 Zeichen und endet auf „=“. "
                        "Auf dem Server: wg show wg0 public-key (nicht den PrivateKey aus der Config nehmen).")
    try:
        a = ipaddress.IPv4Address((adresse or "").strip().split("/")[0])
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Containers bitte als IPv4-Adresse, z. B. 10.8.0.20.") from None
    liste = []
    for n in (netze or "").replace(",", " ").split():
        try:
            liste.append(ipaddress.IPv4Network(n, strict=False))
        except ValueError:
            raise VpnFehler("Netz ungültig: %s (z. B. 10.8.0.0/24)" % n) from None
    if not liste:
        liste = [ipaddress.IPv4Network("%s/24" % a, strict=False)]
    if any(n.prefixlen < 8 for n in liste):
        raise VpnFehler("Nur das VPN-Netz soll über den Tunnel laufen, nicht alles (0.0.0.0/0). Damit dich alle Geräte "
                        "im VPN erreichen, „Alle Teilnehmer meines VPN“ einschalten.")
    if not any(a in n for n in liste):
        raise VpnFehler("Die VPN-Adresse %s liegt in keinem der Netze %s." % (a, " ".join(map(str, liste))))
    for name, netz in lokal:
        for n in liste:
            if n.overlaps(netz):
                raise VpnFehler("%s überschneidet sich mit dem Netz von %s (%s): dann wäre der Container dort nicht mehr "
                                "erreichbar. Geräte aus diesem Netz hinter dem VPN erreichen den Container trotzdem, "
                                "wenn „Alle Teilnehmer meines VPN“ an ist." % (n, name, netz))
    try:
        s = ipaddress.IPv4Address(server_ip.strip()) if server_ip and server_ip.strip() else next(liste[0].hosts())
    except ValueError:
        raise VpnFehler("Die VPN-Adresse des Servers bitte als IPv4-Adresse, z. B. 10.8.0.1.") from None
    if s == a:
        raise VpnFehler("Container und Server können nicht dieselbe VPN-Adresse haben.")
    return str(a), [str(n) for n in liste], str(s)


def zugriff_pruefen(zugriff, adresse, netze, server_ip, lokal=()):
    """Zugriffsadresse von zuhause: leer = die Schuladresse (setzt vpn.sh ein). Sonst eine IPv4-Adresse ausserhalb des
    VPN-Netzes, die im /16-Netz der Schuladresse liegt (sonst reicht die Zertifizierungsstelle nicht)."""
    zugriff = (zugriff or "").strip()
    if not zugriff:
        return ""
    try:
        z = ipaddress.IPv4Address(zugriff.split("/")[0])
    except ValueError:
        raise VpnFehler("Die Zugriffsadresse bitte als IPv4-Adresse, z. B. 172.20.5.191.") from None
    if not z.is_private or z.is_loopback or z.is_link_local:
        raise VpnFehler("Die Zugriffsadresse muss eine private Adresse sein (wie die Schuladresse).")
    if str(z) in (str(adresse), str(server_ip)):
        raise VpnFehler("Die Zugriffsadresse darf nicht die VPN-Adresse des Containers oder des Servers sein.")
    for n in netze or []:
        if z in ipaddress.IPv4Network(str(n), strict=False):
            raise VpnFehler("Die Zugriffsadresse %s liegt im VPN-Netz %s. Nimm dafür die VPN-Adresse oder eine Adresse aus "
                            "dem Schulnetz." % (z, n))
    bereich = ipaddress.IPv4Network("%s/16" % z, strict=False)
    if lokal and not any(bereich.overlaps(netz) for _, netz in lokal):
        raise VpnFehler("Die Zugriffsadresse %s liegt nicht im Bereich der Schuladresse (%s). Dafür bräuchten alle Geräte ein "
                        "neues Stammzertifikat; nimm eine Adresse aus %s." % (
                            z, ", ".join(str(netz) for _, netz in lokal),
                            ", ".join(str(ipaddress.IPv4Network("%s/16" % netz.network_address, strict=False)) for _, netz in lokal)))
    return str(z)


def ziele_pruefen(text, lokal=()):
    """Weitere Ziele ueber das VPN (z. B. Paperless im Heimnetz): einzelne Adressen oder kleine private Netze, die der
    Container ueber den Tunnel erreicht. Nicht das Schulnetz (dann waere der Container dort weg) und nichts Oeffentliches."""
    aus = []
    for teil in (text or "").replace(",", " ").split():
        try:
            n = ipaddress.IPv4Network(teil, strict=False)
        except ValueError:
            raise VpnFehler("Ziel ungültig: %s (z. B. 192.168.5.20 oder 192.168.5.0/24)" % teil) from None
        if n.prefixlen < 16:
            raise VpnFehler("%s ist zu groß: höchstens ein /16-Netz, besser einzelne Adressen." % n)
        if not n.is_private:
            raise VpnFehler("%s ist keine Adresse aus einem Heim- oder Firmennetz (privater Bereich)." % n)
        for name, netz in lokal:
            if n.overlaps(netz):
                raise VpnFehler("%s liegt im Netz von %s (%s), also im Schulnetz: dorthin geht es nicht über das VPN." % (n, name, netz))
        if str(n) not in aus:
            aus.append(str(n))
    if len(aus) > MAX_ZIELE:
        raise VpnFehler("Höchstens %d Ziele." % MAX_ZIELE)
    return aus


def ziele_lesen(text):
    """Weitere Ziele aus wg0.conf (Kommentar von vpn.sh)."""
    m = re.search(r"^[ \t]*#[ \t]*Ziele[ \t]*=[ \t]*(.*?)[ \t]*$", text, re.M)
    return m.group(1).split() if m else []


def konf_lesen(text):
    """Aus wg0.conf: eigene Adresse, Netze ueber den Tunnel und die Server-IP (Kommentare von vpn.sh)."""
    werte = {}
    for zeile in text.splitlines():
        m = re.match(r"\s*(#\s*Server-IP|#\s*Netze|Address|AllowedIPs)\s*=\s*(.+?)\s*$", zeile)
        if m:
            werte.setdefault(m.group(1).lstrip("# ").strip(), m.group(2))
    adresse = ipaddress.IPv4Address(werte["Address"].split("/")[0])
    netze = [ipaddress.IPv4Network(n, strict=False) for n in werte.get("Netze", werte.get("AllowedIPs", "")).replace(",", " ").split()]
    netze = [n for n in netze if n.prefixlen >= 8]
    server = werte.get("Server-IP")
    return adresse, netze, ipaddress.IPv4Address(server) if server else None


def zugriff_lesen(text):
    """Zugriffsadresse aus wg0.conf (Kommentar von vpn.sh), None bei alten Dateien."""
    m = re.search(r"^\s*#\s*Zugriff\s*=\s*(\S+)\s*$", text, re.M)
    return m.group(1) if m else None


def alle_absender(text):
    """wg0.conf von vpn.sh mit "alle Absender": AllowedIPs 0.0.0.0/0, Antworten gehen ueber den Tunnel zurueck."""
    return bool(re.search(r"^\s*#\s*Alle-Absender\s*=\s*ja\s*$", text, re.M))


# --- Verbindung pruefen (statt des Sperrtests in TrackingDRS) ---

def _handshake_alter():
    r = subprocess.run(["wg", "show", "wg0", "latest-handshakes"], capture_output=True, text=True)
    if r.returncode != 0:
        return None, False
    zeiten = [int(t.split()[1]) for t in r.stdout.splitlines() if len(t.split()) == 2 and t.split()[1].isdigit()]
    letzte = max(zeiten, default=0)
    return (int(datetime.datetime.now().timestamp()) - letzte if letzte else None), True


def verbindung(handshake=None):
    """verbunden | keine_verbindung (kein Handshake in den letzten 5 Minuten) | aus (wg0 nicht aktiv)."""
    alter, aktiv = (handshake or _handshake_alter)()
    if not aktiv:
        ergebnis = "aus"
    elif alter is None or alter > HANDSHAKE_MAX:
        ergebnis = "keine_verbindung"
    else:
        ergebnis = "verbunden"
    return {"zeit": db.jetzt(), "ergebnis": ergebnis, "handshake_vor": alter}


TEXTE = {
    "verbunden": "Verbindung zum Server steht.",
    "keine_verbindung": "Keine Verbindung zum Server (kein Handshake in den letzten 5 Minuten). Steht der Container in der "
                        "Server-Config? Ist ausgehendes UDP zum Port des Servers frei?",
    "aus": "VPN ist aus (wg0 nicht aktiv).",
}


def _schreiben(name, daten, ordner=None):
    ordner = ordner or VPN_DIR
    os.makedirs(ordner, mode=0o755, exist_ok=True)
    pfad = os.path.join(ordner, name)
    with open(pfad + ".neu", "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    os.chmod(pfad + ".neu", 0o644)
    os.replace(pfad + ".neu", pfad)


def _lesen(name):
    try:
        with open(os.path.join(VPN_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# --- Einrichten aus Admin > System ---
# Der Webdienst darf nichts einrichten (eigener Benutzer). Er prueft die Angaben und legt <daten>/vpn/anfrage.json ab;
# lehrerkalender-vpn-anfrage.path startet daraufhin als root "lehrerkalender-vpn anfrage". Das liest die Datei (ohne
# einem Symlink zu folgen), loescht sie, prueft die Angaben noch einmal und fuehrt den Auftrag aus. Ergebnisse in
# VPN_DIR: lauf.json, protokoll.txt, verbindung.json und einrichtung.json (nur Oeffentliches: Adressen, oeffentliche
# Schluessel, wg0.conf ohne Schluessel). Den privaten Schluessel des Containers sieht die Seite nie.

def _anfrage_pfad(daten_dir):
    return os.path.join(daten_dir, "vpn", "anfrage.json")


def server_text(host, port):
    """Adresse und Port aus dem Formular -> host:port ([v6]:port)."""
    host = str(host or "").strip()
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "%s:%s" % (host, str(port or "").strip() or "51820")


def _schluessel(text, wofuer):
    text = (text or "").strip()
    try:
        if len(base64.b64decode(text, validate=True)) == 32:
            return text
    except ValueError:
        pass
    raise VpnFehler("%s ist kein WireGuard-Schlüssel (44 Zeichen, endet auf „=“)." % wofuer)


def conf_einlesen(text, lokal=()):
    """Client-Datei fuer den Container (wie man sie fuer ein Handy schreibt) -> Angaben, privater Schluessel, PSK.

    Uebernommen werden [Interface] PrivateKey + Address und [Peer] PublicKey, PresharedKey, Endpoint, AllowedIPs.
    0.0.0.0/0 (oder ein Netz, das sich mit dem Schulnetz ueberschneidet) heisst: alle Absender aus dem VPN zulassen.
    Der Container leitet deshalb nichts um, Routen gibt es nur fuers VPN-Netz. DNS/MTU/IPv6 bleiben weg.
    Rueckgabe: ({server, schluessel, adresse, netze, server_ip, alle}, privat, psk oder None, [hinweise])."""
    if len(text or "") > 4000:
        raise VpnFehler("Die Datei ist zu groß für eine WireGuard-Config.")
    werte, abschnitt, peers, hinweise = {"interface": {}, "peer": {}}, None, 0, []
    for zeile in (text or "").splitlines():
        z = zeile.split("#", 1)[0].strip()
        if not z:
            continue
        m = re.fullmatch(r"\[(\w+)\]", z)
        if m:
            abschnitt = m.group(1).lower()
            peers += abschnitt == "peer"
            continue
        if "=" in z and abschnitt in werte:
            k, v = z.split("=", 1)
            werte[abschnitt].setdefault(k.strip().lower(), v.strip())
    i, pe = werte["interface"], werte["peer"]
    if not i or not pe:
        raise VpnFehler("Das ist keine WireGuard-Config: Es fehlt [Interface] oder [Peer].")
    if peers > 1:
        raise VpnFehler("Die Datei hat mehrere [Peer]. Für den Container gehört nur der Server hinein.")
    privat = _schluessel(i.get("privatekey"), "PrivateKey unter [Interface]")
    psk = _schluessel(pe["presharedkey"], "PresharedKey") if pe.get("presharedkey") else None
    if not pe.get("endpoint"):
        raise VpnFehler("Unter [Peer] fehlt Endpoint (Adresse:Port des Servers).")
    adressen = [a.strip() for a in i.get("address", "").split(",") if a.strip()]
    v4 = [a for a in adressen if ":" not in a]
    if not v4:
        raise VpnFehler("Unter [Interface] fehlt eine IPv4-Adresse (Address = 10.8.0.20/24).")
    if len(adressen) > 1:
        hinweise.append("Nur die IPv4-Adresse %s wird verwendet." % v4[0].split("/")[0])
    try:
        eigen = ipaddress.IPv4Interface(v4[0] if "/" in v4[0] and not v4[0].endswith("/32") else v4[0].split("/")[0] + "/24")
    except ValueError:
        raise VpnFehler("Address unter [Interface] ist keine IPv4-Adresse.") from None
    netze, alle = [], False
    for n in pe.get("allowedips", "").split(","):
        n = n.strip()
        if not n or ":" in n:
            continue
        try:
            netz = ipaddress.IPv4Network(n, strict=False)
        except ValueError:
            raise VpnFehler("AllowedIPs: %s ist kein Netz." % n) from None
        if netz.prefixlen < 8:
            alle = True
            hinweise.append("AllowedIPs %s: Alle Teilnehmer deines VPN erreichen den Container (nur HTTPS). Sein eigener "
                            "Verkehr (Updates, Kalender) bleibt im Schulnetz." % n)
            continue
        ueberschneidung = [name for name, lnetz in lokal if netz.overlaps(lnetz)]
        if ueberschneidung:
            alle = True
            hinweise.append("%s überschneidet sich mit dem Netz von %s: Geräte dort erreichen den Container über das VPN "
                            "trotzdem („Alle Teilnehmer meines VPN“ ist dafür an), der Container selbst bleibt aber im "
                            "Schulnetz." % (n, ueberschneidung[0]))
            continue
        netze.append(netz)
    if not any(eigen.ip in n for n in netze):
        netze.insert(0, eigen.network)
    if i.get("dns"):
        hinweise.append("DNS wird nicht übernommen, der Container nutzt sein eigenes.")
    adresse, netze, server_ip = pruefen(pe["endpoint"], pe.get("publickey"), str(eigen.ip), " ".join(map(str, netze)), "", lokal)
    return ({"server": pe["endpoint"].strip(), "schluessel": pe["publickey"].strip(), "adresse": adresse,
             "netze": " ".join(netze), "server_ip": server_ip, "alle": alle}, privat, psk, hinweise)


def _ja(wert):
    return wert in (True, 1, "1", "ja", "true")


def angaben_pruefen(d, lokal=()):
    """Auftrag aus dem Formular oder der Anfrage-Datei -> bereinigtes dict, sonst VpnFehler.
    Mit einer Client-Datei (conf) kommen privat, psk und hinweise dazu; die gehen nie an die Seite zurueck.
    zertifikat: die VPN-Adresse kommt ins Zertifikat (sonst nur die Schuladresse, Zertifikat bleibt unveraendert)."""
    aktion = d.get("aktion")
    if aktion not in AKTIONEN:
        raise VpnFehler("Unbekannte Aktion.")
    if aktion == "ziele":   # nur die weiteren Ziele aendern, alles andere bleibt (vpn.sh ziele)
        return {"aktion": aktion, "netze": " ".join(ziele_pruefen(str(d.get("ziele") or ""), lokal))}
    if aktion != "einrichten":
        return {"aktion": aktion}
    schnitt = str(d.get("server_if") or "").strip() or "wg0"
    if not SCHNITTSTELLE.fullmatch(schnitt):
        raise VpnFehler("Name der WireGuard-Schnittstelle auf dem Server bitte wie in /etc/wireguard, z. B. wg0.")
    if d.get("conf"):
        angaben, privat, psk, hinweise = conf_einlesen(str(d["conf"]), lokal)
        zugriff = zugriff_pruefen(str(d.get("zugriff") or ""), angaben["adresse"], angaben["netze"].split(), angaben["server_ip"], lokal)
        return dict(angaben, aktion=aktion, server_if=schnitt, privat=privat, psk=psk, hinweise=hinweise,
                    alle=angaben["alle"] or _ja(d.get("alle")), zertifikat=_ja(d.get("zertifikat")), zugriff=zugriff)
    server = str(d.get("server") or "").strip()
    schluessel = str(d.get("schluessel") or "").strip()
    adresse, netze, server_ip = pruefen(server, schluessel, str(d.get("adresse") or ""), str(d.get("netze") or ""),
                                        str(d.get("server_ip") or ""), lokal)
    zugriff = zugriff_pruefen(str(d.get("zugriff") or ""), adresse, netze, server_ip, lokal)
    return {"aktion": aktion, "server": server, "schluessel": schluessel, "adresse": adresse, "netze": " ".join(netze),
            "server_ip": server_ip, "server_if": schnitt, "alle": _ja(d.get("alle")), "zertifikat": _ja(d.get("zertifikat")),
            "zugriff": zugriff}


def schluessel_ablegen(privat, psk):
    """Als root: Schluessel aus der Client-Datei nach /etc/wireguard (nur root lesbar), PSK oder keinen."""
    os.makedirs(os.path.dirname(SCHLUESSEL), mode=0o700, exist_ok=True)
    for pfad, inhalt in ((SCHLUESSEL, privat), (PSK, psk)):
        if inhalt is None:
            if os.path.exists(pfad):
                os.remove(pfad)
            continue
        fd = os.open(pfad + ".neu", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(inhalt + "\n")
        os.replace(pfad + ".neu", pfad)


def eingerichtet():
    return os.path.exists(EINHEIT)


def _protokoll():
    try:
        with open(os.path.join(VPN_DIR, "protokoll.txt"), encoding="utf-8", errors="replace") as f:
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


def web_stand(daten_dir):
    lauf = _lesen("lauf.json")
    return {"eingerichtet": eingerichtet(), "einrichtung": _lesen("einrichtung.json"), "verbindung": _lesen("verbindung.json"),
            "lauf": lauf, "laeuft": _laeuft(lauf), "wartet": os.path.exists(_anfrage_pfad(daten_dir)),
            "protokoll": _protokoll(), "schuladressen": schuladressen()}


def anfordern(daten_dir, daten):
    if not eingerichtet():
        raise VpnFehler("Das VPN lässt sich über die Seite nur im Container einrichten (nach dem nächsten Update über "
                        "die Konsole).")
    s = web_stand(daten_dir)
    if s["laeuft"] or s["wartet"]:
        raise VpnFehler("Es läuft schon ein Auftrag. Bitte kurz warten.")
    if daten.get("aktion") == "ziele" and not s["einrichtung"]:
        raise VpnFehler("Bitte zuerst das VPN einrichten.")
    d = dict(daten)
    if d.get("aktion") == "einrichten" and not d.get("conf"):
        d["server"] = server_text(d.get("server"), d.get("port"))
    try:
        lokal = eigene_netze()
    except (OSError, ValueError):
        lokal = []   # root prueft ohnehin noch einmal
    angaben = angaben_pruefen(d, lokal)
    # Mit Client-Datei geht die Datei selbst an root (sie enthaelt den privaten Schluessel des Containers): nur fuer den
    # Webdienst lesbar und nur, bis root sie abholt.
    auftrag = {"aktion": angaben["aktion"], "conf": d["conf"], "server_if": angaben["server_if"],
               "alle": angaben["alle"], "zertifikat": angaben["zertifikat"], "zugriff": angaben["zugriff"]} if "privat" in angaben \
        else {k: v for k, v in angaben.items() if k != "hinweise"}
    if angaben["aktion"] == "ziele":   # root prueft erneut und liest dafuer "ziele" (nicht das Ergebnis "netze")
        auftrag = {"aktion": "ziele", "ziele": angaben["netze"]}
    pfad = _anfrage_pfad(daten_dir)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    fd = os.open(pfad + ".neu", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dict(auftrag, zeit=db.jetzt()), f)
    os.replace(pfad + ".neu", pfad)
    return {k: v for k, v in angaben.items() if k not in ("privat", "psk")}


def anfrage_lesen(pfad):
    """Als root: Anfrage-Datei lesen und loeschen. Kein Symlink, nur eine kleine regulaere Datei."""
    try:
        fd = os.open(pfad, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise VpnFehler("Keine Anfrage gefunden.") from None
    try:
        roh = os.read(fd, 8192) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    finally:
        os.close(fd)
        try:
            os.unlink(pfad)
        except OSError:
            pass
    try:
        d = json.loads(roh.decode("utf-8"))
    except ValueError:
        raise VpnFehler("Die Anfrage ist unlesbar.") from None
    if not isinstance(d, dict):
        raise VpnFehler("Die Anfrage ist unlesbar.")
    return angaben_pruefen(d, eigene_netze())


def _conf_angaben(text):
    angaben, privat, psk, hinweise = conf_einlesen(text, eigene_netze())
    return dict(angaben, privat=privat, psk=psk, hinweise=hinweise)


def _oeffentlicher_schluessel(text):
    try:
        if len(base64.b64decode((text or "").strip(), validate=True)) == 32:
            return text.strip()
    except ValueError:
        pass
    raise VpnFehler("Öffentlicher Schlüssel des Containers ungültig.")


def _im_zertifikat(adresse):
    try:
        with open(TLS_IPS, encoding="utf-8") as f:
            return adresse in [z.strip() for z in f if not z.startswith("#")]
    except OSError:
        return False


def info_ablegen(container_schluessel, aktiv, server_if=None, aus_datei=None):
    """Als root nach dem Einrichten/Ausschalten: was die Seite fuer Peer-Block und Kopiervorlagen braucht.
    aus_datei: eingerichtet mit einer Client-Datei (der Server kennt den Container dann meist schon)."""
    with open(KONF, encoding="utf-8") as f:
        text = f.read()
    adresse, netze, server_ip = konf_lesen(text)
    werte = dict(re.findall(r"^\s*(Endpoint|PublicKey)\s*=\s*(\S+)", text, re.M))
    alt = _lesen("einrichtung.json") or {}
    konf = "\n".join(z for z in text.splitlines() if not z.strip().lower().startswith(("privatekey", "presharedkey"))) + "\n"
    info = {"zeit": db.jetzt(), "aktiv": bool(aktiv), "name": socket.gethostname().split(".")[0],
            "adresse": str(adresse), "netze": [str(n) for n in netze], "server_ip": str(server_ip) if server_ip else None,
            "server": werte.get("Endpoint"), "server_schluessel": werte.get("PublicKey"),
            "container_schluessel": _oeffentlicher_schluessel(container_schluessel),
            "server_if": server_if or alt.get("server_if") or "wg0", "konf": konf,
            "aus_datei": alt.get("aus_datei", False) if aus_datei is None else aus_datei, "psk": os.path.exists(PSK),
            "alle": alle_absender(text), "schuladressen": schuladressen(), "zertifikat": _im_zertifikat(str(adresse)),
            "zugriff": zugriff_lesen(text), "ziele": ziele_lesen(text)}
    _schreiben("einrichtung.json", info)
    return info


def _verbindung_main(leise):
    if not os.path.exists(KONF):
        print("VPN nicht eingerichtet (lehrerkalender vpn einrichten).", file=sys.stderr)
        return 1
    erg = verbindung()
    _schreiben("verbindung.json", erg)
    if not leise:
        print(TEXTE[erg["ergebnis"]] + ("" if erg["handshake_vor"] is None else " (letzter Handshake vor %d s)" % erg["handshake_vor"]))
    return 0 if erg["ergebnis"] == "verbunden" else 2


def main(argv):
    if argv[:1] == ["verbindung"]:
        return _verbindung_main("--leise" in argv)
    try:
        if argv[:1] in (["anfrage-lesen"], ["conf-lesen"]) and len(argv) == 2:
            if argv[0] == "anfrage-lesen":
                a = anfrage_lesen(argv[1])
            else:   # lehrerkalender vpn einrichten --conf <datei>
                with open(argv[1], encoding="utf-8") as f:
                    a = dict(aktion="einrichten", server_if="", **_conf_angaben(f.read()))
            if a.get("privat"):
                schluessel_ablegen(a["privat"], a["psk"])
            for h in a.get("hinweise", []):
                print("Hinweis: %s" % h, file=sys.stderr)
            print("|".join([*(a.get(k, "") for k in ("aktion", "server", "schluessel", "adresse", "netze", "server_ip",
                                                     "server_if")), "1" if a.get("psk") else "", "1" if a.get("privat") else "",
                            "1" if a.get("alle") else "", "1" if a.get("zertifikat") else "", a.get("zugriff") or ""]))
            return 0
        if argv[:1] == ["ziele"] and len(argv) == 2:
            print(" ".join(ziele_pruefen(argv[1], eigene_netze())))
            return 0
        if argv[:1] == ["zugriff"] and len(argv) == 5:
            print(zugriff_pruefen(argv[1], argv[2], argv[3].split(), argv[4], eigene_netze()))
            return 0
        if argv[:1] == ["info-ablegen"] and len(argv) in (3, 4, 5):
            info_ablegen(argv[1], argv[2] == "1", argv[3] if len(argv) >= 4 and argv[3] else None,
                         (argv[4] == "1") if len(argv) == 5 and argv[4] else None)
            return 0
    except (VpnFehler, OSError, KeyError, ValueError) as f:
        print("Fehler: %s" % f, file=sys.stderr)
        return 1
    if len(argv) < 5 or argv[0] != "pruefen":
        print(__doc__)
        return 1
    try:
        a, netze, s = pruefen(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else "", eigene_netze())
    except VpnFehler as f:
        print("Fehler: %s" % f, file=sys.stderr)
        return 1
    print("%s|%s|%s" % (a, " ".join(netze), s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
