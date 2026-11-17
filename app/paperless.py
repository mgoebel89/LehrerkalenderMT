"""Dokumente (Stufe F3): das eigene Paperless-ngx einer Lehrkraft, aus dem alten drs-lxc uebernommen.

Der Browser spricht nur mit /api/dokumente/...; Adresse und API-Token kennt allein der Server. Damit nur die schulischen
Dokumente erscheinen, zeigt die Liste Dokumente mit einem der Anzeige-Tags (ODER), und jeder Upload aus dem
Lehrerkalender bekommt den Upload-Tag und den Speicherpfad. Beides waehlt die Lehrkraft aus dem, was es in ihrem
Paperless gibt; der Lehrerkalender legt dort nichts an.

Konfiguration je Konto in lehrkraft.paperless: JSON, mit AES-GCM verschluesselt. Der Schluessel liegt als Datei im
Datenordner (paperless.key, nur fuer den Dienst lesbar), NICHT in der Datenbank: Eine heruntergeladene Sicherung
enthaelt den Token damit nicht lesbar. Nach "Sicherung einspielen" auf einer anderen Instanz muss jede Lehrkraft ihr
Paperless neu verbinden.

Erreichbarkeit: Steht Paperless im Heimnetz, laeuft die Verbindung ueber das VPN des Containers (Admin > System > VPN,
"Weitere Ziele ueber das VPN").
"""
import base64
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid

TIMEOUT = 20          # Sekunden; Uploads und Vorschauen dauern laenger als eine Liste
MAX_SEITEN = 20       # Deckel beim Durchblaettern der Stammlisten (je 100)
SEITE = 24
MAX_HOCHLADEN = 100 * 1024 * 1024
SCHLUESSEL_DATEI = "paperless.key"
SORTIERUNGEN = {"-created": "Neueste zuerst", "created": "Älteste zuerst", "title": "Titel A–Z", "-added": "Zuletzt hinzugefügt"}
ARTEN = {"preview": "preview", "thumb": "thumb", "download": "download"}


class PaperlessFehler(Exception):
    """Meldung fuer die Oberflaeche; status wird an den Browser weitergereicht (502 = Paperless nicht erreichbar)."""

    def __init__(self, meldung, status=400):
        super().__init__(meldung)
        self.status = status


# --- Konfiguration (verschluesselt) ---

def _aesgcm(daten_dir):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise PaperlessFehler("Im Container fehlt das Paket python3-cryptography (wird beim nächsten Update installiert).", 500)
    pfad = os.path.join(daten_dir, SCHLUESSEL_DATEI)
    try:
        with open(pfad, "rb") as f:
            schluessel = f.read()
    except FileNotFoundError:
        schluessel = secrets.token_bytes(32)
        try:
            fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:            # gleichzeitig angelegt: den anderen nehmen
            with open(pfad, "rb") as f:
                schluessel = f.read()
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(schluessel)
    if len(schluessel) != 32:
        raise PaperlessFehler("Der Schlüssel für die Paperless-Zugänge ist beschädigt (%s)." % pfad, 500)
    return AESGCM(schluessel)


def _verschluesseln(daten_dir, obj):
    nonce = secrets.token_bytes(12)
    return base64.b64encode(nonce + _aesgcm(daten_dir).encrypt(nonce, json.dumps(obj).encode("utf-8"), b"paperless")).decode("ascii")


def _entschluesseln(daten_dir, text):
    roh = base64.b64decode(text)
    return json.loads(_aesgcm(daten_dir).decrypt(roh[:12], roh[12:], b"paperless").decode("utf-8"))


def _zahlen(liste):
    aus = []
    for w in liste or []:
        try:
            n = int(w)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in aus:
            aus.append(n)
    return aus


def _zahl(w):
    try:
        return max(0, int(w or 0))
    except (TypeError, ValueError):
        return 0


def adresse_pruefen(url):
    url = (url or "").strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    teile = urllib.parse.urlsplit(url)
    if teile.scheme not in ("http", "https") or not teile.hostname or teile.query or teile.fragment:
        raise PaperlessFehler("Adresse bitte wie im Browser, z. B. http://192.168.5.20:8000 oder https://paperless.example.de.")
    return url


def konfig(con, lid, daten_dir):
    """Die Konfiguration (mit Token) oder None. Nicht lesbar (z. B. nach dem Einspielen einer fremden Sicherung) -> Fehler."""
    z = con.execute("SELECT paperless FROM lehrkraft WHERE id = ?", (lid,)).fetchone()
    if not z or not z["paperless"]:
        return None
    try:
        k = _entschluesseln(daten_dir, z["paperless"])
    except PaperlessFehler:
        raise
    except Exception:
        raise PaperlessFehler("Die Paperless-Verbindung ist hier nicht lesbar (z. B. nach dem Einspielen einer Sicherung). "
                              "Bitte unter Einstellungen › Konto neu verbinden.")
    return {"url": k.get("url", ""), "token": k.get("token", ""), "tags": _zahlen(k.get("tags")),
            "upload_tag": _zahl(k.get("upload_tag")), "pfad": _zahl(k.get("pfad"))}


def konfig_oeffentlich(con, lid, daten_dir):
    """Fuer die Oberflaeche: alles ausser dem Token."""
    try:
        k = konfig(con, lid, daten_dir)
    except PaperlessFehler as f:
        return {"verbunden": False, "fehler": str(f)}
    if not k:
        return {"verbunden": False}
    return {"verbunden": True, "url": k["url"], "tags": k["tags"], "upload_tag": k["upload_tag"], "pfad": k["pfad"]}


def konfig_speichern(con, lid, daten_dir, daten, aufruf=None):
    """URL und Token (leer = bisheriger), Anzeige-Tags, Upload-Tag, Speicherpfad. Prueft die Verbindung vorher."""
    try:
        alt = konfig(con, lid, daten_dir) or {}
    except PaperlessFehler:
        alt = {}
    url = adresse_pruefen(daten.get("url"))
    token = (daten.get("token") or "").strip()
    if not token:
        if not alt.get("token") or alt.get("url") != url:
            raise PaperlessFehler("Bitte den API-Token aus Paperless eintragen (Paperless: Profil › API-Token).")
        token = alt["token"]
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,200}", token):
        raise PaperlessFehler("Der API-Token sieht nicht richtig aus (Buchstaben und Ziffern, aus Paperless kopieren).")
    k = {"url": url, "token": token, "tags": _zahlen(daten.get("tags")), "upload_tag": _zahl(daten.get("upload_tag")),
         "pfad": _zahl(daten.get("pfad"))}
    anzahl = testen(k, aufruf)
    con.execute("UPDATE lehrkraft SET paperless = ? WHERE id = ?", (_verschluesseln(daten_dir, k), lid))
    return anzahl


def konfig_loeschen(con, lid):
    con.execute("UPDATE lehrkraft SET paperless = NULL WHERE id = ?", (lid,))


def verbunden(con, lid):
    z = con.execute("SELECT paperless FROM lehrkraft WHERE id = ?", (lid,)).fetchone()
    return bool(z and z["paperless"])


# --- HTTP ---

def _anfrage(k, methode, pfad, parameter=None, json_inhalt=None, roh=None, typ=None):
    """Ein Aufruf gegen Paperless -> (Statuscode, Bytes, Kopfzeilen). Wirft PaperlessFehler bei Netz- und HTTP-Fehlern."""
    url = k["url"] + pfad
    if parameter:
        url += "?" + urllib.parse.urlencode(parameter, doseq=True)
    kopf = {"Authorization": "Token " + k["token"], "Accept": "application/json"}
    inhalt = None
    if json_inhalt is not None:
        inhalt = json.dumps(json_inhalt).encode("utf-8")
        kopf["Content-Type"] = "application/json"
    elif roh is not None:
        inhalt = roh
        kopf["Content-Type"] = typ
    req = urllib.request.Request(url, data=inhalt, method=methode, headers=kopf)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        text = e.read()[:300].decode("utf-8", "replace")
        if e.code in (401, 403):
            raise PaperlessFehler("Paperless lehnt den API-Token ab.", 401)
        if e.code == 404:
            raise PaperlessFehler("In Paperless nicht gefunden.", 404)
        raise PaperlessFehler("Paperless meldet %d: %s" % (e.code, text.strip() or e.reason), 502)
    except (urllib.error.URLError, OSError, ValueError) as e:
        grund = getattr(e, "reason", e)
        raise PaperlessFehler("Paperless ist nicht erreichbar (%s). Steht es im Heimnetz: läuft das VPN, und ist die "
                              "Adresse unter Admin › System › VPN als Ziel eingetragen?" % grund, 502)


def _json(k, methode, pfad, **mehr):
    _, inhalt, _ = _anfrage(k, methode, pfad, **mehr)
    if not inhalt:
        return {}
    try:
        aus = json.loads(inhalt)
    except ValueError:
        return {"roh": inhalt.decode("utf-8", "replace").strip().strip('"')}
    if isinstance(aus, dict):
        return aus
    if isinstance(aus, str):          # post_document antwortet mit der nackten Task-UUID (gueltiges JSON!)
        return {"roh": aus.strip()}
    return {"results": aus}


def _alle(k, pfad):
    aus, seite = [], 1
    while seite <= MAX_SEITEN:
        d = _json(k, "GET", pfad, parameter={"page": seite, "page_size": 100})
        aus.extend(d.get("results") or [])
        if not d.get("next"):
            break
        seite += 1
    return aus


def _noetig(con, lid, daten_dir):
    k = konfig(con, lid, daten_dir)
    if not k:
        raise PaperlessFehler("Paperless ist nicht verbunden: unter Einstellungen › Konto Adresse und API-Token eintragen.")
    return k


def testen(k, aufruf=None):
    """Verbindung pruefen: Anzahl der sichtbaren Dokumente."""
    d = (aufruf or _json)(k, "GET", "/api/documents/", parameter={"page_size": 1})
    if "count" not in d:
        raise PaperlessFehler("Unter dieser Adresse antwortet kein Paperless (keine Dokumentenliste).", 502)
    return d.get("count") or 0


# --- Stammlisten, Liste, Dokument ---

def _knapp(liste, felder):
    return [{f: x.get(f) for f in felder} for x in liste]


def stammlisten(con, lid, daten_dir):
    k = _noetig(con, lid, daten_dir)
    return {"tags": _knapp(_alle(k, "/api/tags/"), ["id", "name", "color"]),
            "pfade": _knapp(_alle(k, "/api/storage_paths/"), ["id", "name", "path"]),
            "korrespondenten": _knapp(_alle(k, "/api/correspondents/"), ["id", "name"]),
            "typen": _knapp(_alle(k, "/api/document_types/"), ["id", "name"]),
            "anzeige_tags": k["tags"], "upload_tag": k["upload_tag"], "pfad": k["pfad"]}


def _dokument_knapp(d):
    return {"id": d.get("id"), "titel": d.get("title") or "", "datum": (d.get("created_date") or d.get("created") or "")[:10],
            "hinzugefuegt": (d.get("added") or "")[:10], "korrespondent": d.get("correspondent"), "typ": d.get("document_type"),
            "pfad": d.get("storage_path"), "tags": d.get("tags") or [], "asn": d.get("archive_serial_number"),
            "notizen": [{"id": n.get("id"), "text": n.get("note") or "", "erstellt": (n.get("created") or "")[:16]}
                        for n in (d.get("notes") or []) if isinstance(n, dict)],
            "dateiname": d.get("original_file_name") or ""}


def suchen(con, lid, daten_dir, suche="", tags=(), sortierung="-created", seite=1):
    """Dokumente mit einem der Anzeige-Tags (ODER). Zusaetzlich gewaehlte Tags schraenken innerhalb der Anzeige-Tags ein."""
    k = _noetig(con, lid, daten_dir)
    gewaehlt = _zahlen(tags)
    if k["tags"]:
        gewaehlt = [t for t in gewaehlt if t in k["tags"]] or k["tags"]
    p = {"page": max(1, _zahl(seite) or 1), "page_size": SEITE,
         "ordering": sortierung if sortierung in SORTIERUNGEN else "-created"}
    if gewaehlt:
        p["tags__id__in"] = ",".join(map(str, gewaehlt))
    if (suche or "").strip():
        p["title_content"] = suche.strip()[:200]
    d = _json(k, "GET", "/api/documents/", parameter=p)
    return {"anzahl": d.get("count") or 0, "weiter": bool(d.get("next")),
            "dokumente": [_dokument_knapp(x) for x in (d.get("results") or [])]}


def _id(w):
    n = _zahl(w)
    if not n:
        raise PaperlessFehler("Ungültige Dokumentnummer.")
    return n


def dokument(con, lid, daten_dir, did):
    k = _noetig(con, lid, daten_dir)
    return _dokument_knapp(_json(k, "GET", "/api/documents/%d/" % _id(did)))


def aendern(con, lid, daten_dir, did, daten):
    """Titel, Datum, Korrespondent, Typ und Tags aendern (nur diese Felder)."""
    k = _noetig(con, lid, daten_dir)
    patch = {}
    if "titel" in daten:
        titel = (daten.get("titel") or "").strip()
        if not titel or len(titel) > 128:
            raise PaperlessFehler("Bitte einen Titel angeben (höchstens 128 Zeichen).")
        patch["title"] = titel
    if "datum" in daten and daten.get("datum"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(daten["datum"])):
            raise PaperlessFehler("Ungültiges Datum.")
        patch["created"] = daten["datum"]
    if "korrespondent" in daten:
        patch["correspondent"] = _zahl(daten.get("korrespondent")) or None
    if "typ" in daten:
        patch["document_type"] = _zahl(daten.get("typ")) or None
    if "tags" in daten:
        patch["tags"] = _zahlen(daten.get("tags"))
    if not patch:
        return dokument(con, lid, daten_dir, did)
    try:
        return _dokument_knapp(_json(k, "PATCH", "/api/documents/%d/" % _id(did), json_inhalt=patch))
    except PaperlessFehler as f:
        if "created" not in patch or "meldet 400" not in str(f):
            raise
        patch["created_date"] = patch.pop("created")   # aeltere Paperless-Versionen: Datum nur ueber created_date
        return _dokument_knapp(_json(k, "PATCH", "/api/documents/%d/" % _id(did), json_inhalt=patch))


def _dateiname(kopf):
    """Dateiname aus Content-Disposition (filename*=UTF-8''... oder filename="...")."""
    m = re.search(r"filename\*=UTF-8''([^;]+)", kopf or "", re.I)
    if m:
        return urllib.parse.unquote(m.group(1).strip())
    m = re.search(r'filename="?([^";]+)"?', kopf or "", re.I)
    return m.group(1).strip() if m else ""


def datei(con, lid, daten_dir, did, art):
    """Vorschau, Vorschaubild oder Original: (Bytes, Content-Type, Dateiname oder '')."""
    if art not in ARTEN:
        raise PaperlessFehler("Unbekannte Art.")
    k = _noetig(con, lid, daten_dir)
    _, inhalt, kopf = _anfrage(k, "GET", "/api/documents/%d/%s/" % (_id(did), ARTEN[art]))
    name = os.path.basename(_dateiname(kopf.get("Content-Disposition")).replace("\\", "/"))
    return inhalt, kopf.get("Content-Type", "application/octet-stream"), name


# --- Notizen ---

def notiz_neu(con, lid, daten_dir, did, text):
    text = (text or "").strip()
    if not text or len(text) > 5000:
        raise PaperlessFehler("Bitte eine Notiz eingeben (höchstens 5000 Zeichen).")
    k = _noetig(con, lid, daten_dir)
    _json(k, "POST", "/api/documents/%d/notes/" % _id(did), json_inhalt={"note": text})
    return dokument(con, lid, daten_dir, did)


def notiz_loeschen(con, lid, daten_dir, did, nid):
    k = _noetig(con, lid, daten_dir)
    _json(k, "DELETE", "/api/documents/%d/notes/" % _id(did), parameter={"id": _id(nid)})   # Notiz-ID als Parameter
    return dokument(con, lid, daten_dir, did)


# --- Hochladen ---

def _multipart(felder, dateiname, inhalt, typ):
    grenze = "----lehrerkalender" + uuid.uuid4().hex
    teile = []
    for name, wert in felder:
        teile.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (grenze, name, wert)).encode("utf-8"))
    sicher = re.sub(r'["\r\n\\]', "_", dateiname) or "dokument"
    teile.append(("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                  % (grenze, sicher, typ)).encode("utf-8"))
    teile.append(inhalt)
    teile.append(("\r\n--%s--\r\n" % grenze).encode("utf-8"))
    return b"".join(teile), "multipart/form-data; boundary=" + grenze


def hochladen(con, lid, daten_dir, dateiname, inhalt, typ="application/pdf", titel="", datum="", korrespondent=0, dok_typ=0, tags=()):
    """Legt ein Dokument ab (immer mit Upload-Tag und Speicherpfad) und liefert die Task-ID. Paperless verarbeitet
    asynchron (OCR); die Dokumentnummer gibt es erst ueber aufgabe()."""
    k = _noetig(con, lid, daten_dir)
    if not inhalt:
        raise PaperlessFehler("Die Datei ist leer.")
    dateiname = os.path.basename((dateiname or "").replace("\\", "/")).strip() or "dokument.pdf"
    felder = []
    if (titel or "").strip():
        felder.append(("title", titel.strip()[:128]))
    if datum:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", datum):
            raise PaperlessFehler("Ungültiges Datum.")
        felder.append(("created", datum))
    if _zahl(korrespondent):
        felder.append(("correspondent", str(_zahl(korrespondent))))
    if _zahl(dok_typ):
        felder.append(("document_type", str(_zahl(dok_typ))))
    if k["pfad"]:
        felder.append(("storage_path", str(k["pfad"])))
    alle_tags = _zahlen(tags)
    if k["upload_tag"] and k["upload_tag"] not in alle_tags:
        alle_tags.append(k["upload_tag"])
    felder += [("tags", str(t)) for t in alle_tags]
    if not re.fullmatch(r"[\w.+-]+/[\w.+-]+", typ or ""):
        typ = "application/octet-stream"
    roh, ctyp = _multipart(felder, dateiname, inhalt, typ)
    d = _json(k, "POST", "/api/documents/post_document/", roh=roh, typ=ctyp)
    return str(d.get("roh") or d.get("task_id") or "")


def aufgabe(con, lid, daten_dir, task_id):
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", task_id or ""):
        raise PaperlessFehler("Ungültige Aufgabe.")
    k = _noetig(con, lid, daten_dir)
    d = _json(k, "GET", "/api/tasks/", parameter={"task_id": task_id})
    liste = d.get("results") if isinstance(d.get("results"), list) else []
    if not liste:
        return {"stand": "PENDING", "dokument": None, "fehler": ""}
    t = liste[0]
    return {"stand": t.get("status") or "PENDING", "dokument": t.get("related_document"),
            "fehler": (t.get("result") or "") if t.get("status") == "FAILURE" else ""}
