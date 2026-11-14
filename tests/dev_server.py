"""Lokaler Testserver ohne TLS auf 127.0.0.1:<port> (Vorgabe 8472), Daten in .dev-daten im Repo-Ordner.

  python tests/dev_server.py [port]

Lehrerbereich und Schuelerseiten laufen dann auf demselben Port (http://127.0.0.1:8472/ bzw. /code und /s/<Code>).
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("LEHRERKALENDER_DATEN", os.path.join(REPO, ".dev-daten"))
os.environ["LEHRERKALENDER_OHNE_TLS"] = "1"
os.environ["LEHRERKALENDER_BIND"] = "127.0.0.1"
os.environ["LEHRERKALENDER_HTTP_PORT"] = sys.argv[1] if len(sys.argv) > 1 else "8472"
sys.path.insert(0, REPO)

from app import server  # noqa: E402  (erst nach den Umgebungsvariablen laden)

server.main()
