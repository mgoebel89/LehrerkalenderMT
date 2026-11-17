"""Paperless-Attrappe fuer Tests und zum Ausprobieren der Seite "Dokumente" ohne echtes Paperless.

  python tests/paperless_attrappe.py [port]      (Vorgabe 8473, Token: attrappe-token-1234)

Kann nur, was der Lehrerkalender braucht: Stammlisten, Dokumentenliste (Tags ODER, Suche, Seiten), Dokument lesen und
aendern, Notizen, Vorschau/Vorschaubild/Original, post_document (multipart) und tasks.
"""
import base64
import json
import re
import sys
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "attrappe-token-1234"
# kleinstes gueltiges PNG (1x1, blau) und ein winziges PDF
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgSPgPAAJoAZ8Y8a7fAAAAAElFTkSuQmCC")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def daten_neu():
    return {
        "tags": [{"id": 1, "name": "Schule", "color": "#00639c"}, {"id": 2, "name": "Privat", "color": "#d4005e"},
                 {"id": 3, "name": "Lehrerkalender", "color": "#f8b442"}, {"id": 4, "name": "LF 7", "color": "#b1c800"}],
        "storage_paths": [{"id": 1, "name": "Schule", "path": "schule/{title}"}, {"id": 2, "name": "Privat", "path": "privat/{title}"}],
        "correspondents": [{"id": 1, "name": "DRS Neuwied"}, {"id": 2, "name": "Festo"}],
        "document_types": [{"id": 1, "name": "Arbeitsblatt"}, {"id": 2, "name": "Klassenarbeit"}],
        "documents": {
            1: {"id": 1, "title": "Arbeitsblatt Pneumatik", "created": "2026-10-05", "added": "2026-10-05T10:00:00",
                "correspondent": 2, "document_type": 1, "storage_path": 1, "tags": [1, 4], "notes": [], "original_file_name": "ab-pneumatik.pdf"},
            2: {"id": 2, "title": "Steuerbescheid", "created": "2026-06-01", "added": "2026-06-02T08:00:00",
                "correspondent": None, "document_type": None, "storage_path": 2, "tags": [2], "notes": [], "original_file_name": "steuer.pdf"},
            3: {"id": 3, "title": "Klassenarbeit LF 7 Lösung", "created": "2026-11-01", "added": "2026-11-01T09:00:00",
                "correspondent": 1, "document_type": 2, "storage_path": 1, "tags": [1], "notes": [], "original_file_name": "ka-lf7.pdf"},
        },
        "tasks": {}, "naechste": 4, "uploads": [],
    }


class Attrappe(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    D = daten_neu()
    sperre = threading.Lock()

    def log_message(self, *a):
        pass

    def _senden(self, status, inhalt, typ="application/json", kopf=()):
        roh = inhalt if isinstance(inhalt, bytes) else json.dumps(inhalt).encode()
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(roh)))
        for k, v in kopf:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(roh)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _verteilen(self, methode):
        teile = urllib.parse.urlsplit(self.path)
        pfad, q = teile.path, urllib.parse.parse_qs(teile.query)
        body = self._body() if methode in ("POST", "PATCH", "DELETE") else b""
        if self.headers.get("Authorization") != "Token " + TOKEN:
            return self._senden(401, {"detail": "Invalid token."})
        D = self.D
        with self.sperre:
            for liste in ("tags", "storage_paths", "correspondents", "document_types"):
                if pfad == "/api/%s/" % liste and methode == "GET":
                    return self._senden(200, {"count": len(D[liste]), "next": None, "results": D[liste]})
            if pfad == "/api/documents/" and methode == "GET":
                docs = list(D["documents"].values())
                if q.get("tags__id__in"):
                    ids = {int(x) for x in q["tags__id__in"][0].split(",")}
                    docs = [d for d in docs if ids & set(d["tags"])]
                if q.get("title_content"):
                    s = q["title_content"][0].lower()
                    docs = [d for d in docs if s in d["title"].lower()]
                o = (q.get("ordering") or ["-created"])[0]
                docs.sort(key=lambda d: d.get(o.lstrip("-")) or "", reverse=o.startswith("-"))
                gr, seite = int((q.get("page_size") or [25])[0]), int((q.get("page") or [1])[0])
                stueck = docs[(seite - 1) * gr: seite * gr]
                return self._senden(200, {"count": len(docs), "next": "x" if seite * gr < len(docs) else None, "results": stueck})
            if pfad == "/api/documents/post_document/" and methode == "POST":
                return self._hochladen(body)
            if pfad == "/api/tasks/" and methode == "GET":
                t = D["tasks"].get((q.get("task_id") or [""])[0])
                return self._senden(200, [t] if t else [])
            m = re.fullmatch(r"/api/documents/(\d+)/(?:(notes|preview|thumb|download)/)?", pfad)
            if not m or int(m.group(1)) not in D["documents"]:
                return self._senden(404, {"detail": "Not found."})
            d = D["documents"][int(m.group(1))]
            art = m.group(2)
            if art is None and methode == "GET":
                return self._senden(200, d)
            if art is None and methode == "PATCH":
                patch = json.loads(body)
                if "created" in patch and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(patch["created"])):
                    return self._senden(400, {"created": ["Datum ungültig"]})
                for k, v in patch.items():
                    d[k] = v
                return self._senden(200, d)
            if art == "notes":
                if methode == "POST":
                    d["notes"].append({"id": len(d["notes"]) + 100, "note": json.loads(body)["note"], "created": "2026-11-17T12:00:00"})
                elif methode == "DELETE":
                    nid = int(q["id"][0])
                    d["notes"] = [n for n in d["notes"] if n["id"] != nid]
                return self._senden(200, d["notes"])
            if art == "thumb":
                return self._senden(200, PNG, "image/png")
            if art == "preview":
                return self._senden(200, PDF, "application/pdf")
            return self._senden(200, PDF, "application/pdf",
                                [("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(d["original_file_name"]))])

    def _hochladen(self, body):
        typ = self.headers.get("Content-Type", "")
        grenze = re.search(r"boundary=(.+)$", typ).group(1).encode()
        felder, datei = {}, None
        for teil in body.split(b"--" + grenze)[1:-1]:
            kopf, _, inhalt = teil.strip(b"\r\n").partition(b"\r\n\r\n")
            name = re.search(rb'name="([^"]+)"', kopf).group(1).decode()
            fn = re.search(rb'filename="([^"]*)"', kopf)
            if fn:
                datei = (fn.group(1).decode(), inhalt)
            else:
                felder.setdefault(name, []).append(inhalt.decode())
        D = self.D
        nr = D["naechste"]
        D["naechste"] += 1
        D["documents"][nr] = {"id": nr, "title": (felder.get("title") or [datei[0]])[0], "created": (felder.get("created") or ["2026-11-17"])[0],
                              "added": "2026-11-17T12:00:00", "correspondent": int((felder.get("correspondent") or [0])[0]) or None,
                              "document_type": int((felder.get("document_type") or [0])[0]) or None,
                              "storage_path": int((felder.get("storage_path") or [0])[0]) or None,
                              "tags": [int(t) for t in felder.get("tags", [])], "notes": [], "original_file_name": datei[0]}
        D["uploads"].append({"felder": felder, "datei": datei[0], "groesse": len(datei[1])})
        task = str(uuid.uuid4())
        D["tasks"][task] = {"task_id": task, "status": "SUCCESS", "related_document": nr, "result": "ok"}
        return self._senden(200, json.dumps(task).encode())

    def do_GET(self):
        self._verteilen("GET")

    def do_POST(self):
        self._verteilen("POST")

    def do_PATCH(self):
        self._verteilen("PATCH")

    def do_DELETE(self):
        self._verteilen("DELETE")


def starten(port=0):
    """Startet die Attrappe im Hintergrund; Rueckgabe (server, url)."""
    Attrappe.D = daten_neu()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Attrappe)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


if __name__ == "__main__":
    srv, url = starten(int(sys.argv[1]) if len(sys.argv) > 1 else 8473)
    print("Paperless-Attrappe auf %s, Token %s" % (url, TOKEN), flush=True)
    threading.Event().wait()
