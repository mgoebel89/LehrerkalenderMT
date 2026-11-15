"""Angaben zur Schule fuer Kopf- und Fusszeilen: Schullogo (JPEG, vom Admin hochgeladen), Schulname, Webadresse.

Das Logo liegt als Base64 in der Tabelle einstellung (kommt so mit in die Sicherung) und gilt fuer alle. Der Browser
wandelt jedes hochgeladene Bild (PNG, JPEG, WebP ...) vorher in ein JPEG um; die PDFs betten es unveraendert ein.
"""
import base64
import re

from . import db, pdf

VORGABE_NAME = "David Roentgen Schule Neuwied"
VORGABE_WEB = "www.drsneuwied.de"
MAX_LOGO = 1024 * 1024          # 1 MB (nach der Umwandlung im Browser meist 30-150 KB)


class SchuleFehler(Exception):
    pass


def logo(con):
    """JPEG-Daten des Schullogos oder None."""
    wert = db.einstellung(con, "schullogo")
    if not wert:
        return None
    try:
        return base64.b64decode(wert)
    except (ValueError, TypeError):
        return None


def angaben(con):
    """{name, web, logo: bool, logo_masse: [breite, hoehe] oder None, logo_stand}"""
    daten = logo(con)
    masse = pdf.jpeg_masse(daten) if daten else None
    return {"name": db.einstellung(con, "schule_name", VORGABE_NAME), "web": db.einstellung(con, "schule_web", VORGABE_WEB),
            "logo": bool(masse), "logo_masse": list(masse[:2]) if masse else None, "logo_stand": db.einstellung(con, "schullogo_stand", "")}


def speichern(con, daten):
    """Schulname, Webadresse und Logo setzen. logo: 'data:image/jpeg;base64,...' (neu), '' (entfernen), fehlt (bleibt)."""
    if "name" in daten:
        name = (daten.get("name") or "").strip()
        if not name or len(name) > 120:
            raise SchuleFehler("Bitte den Schulnamen angeben (höchstens 120 Zeichen).")
        db.einstellung_setzen(con, "schule_name", name)
    if "web" in daten:
        web = (daten.get("web") or "").strip()
        if len(web) > 120:
            raise SchuleFehler("Die Webadresse ist zu lang.")
        db.einstellung_setzen(con, "schule_web", web)
    if "logo" in daten:
        wert = daten.get("logo") or ""
        if not wert:
            db.einstellung_setzen(con, "schullogo", "")
        else:
            m = re.fullmatch(r"data:image/jpeg;base64,([A-Za-z0-9+/=\s]+)", wert)
            if not m:
                raise SchuleFehler("Das Logo muss als JPEG ankommen. Bitte die Seite neu laden und noch einmal versuchen.")
            roh = base64.b64decode(m.group(1))
            if len(roh) > MAX_LOGO:
                raise SchuleFehler("Das Logo ist zu groß (höchstens 1 MB).")
            masse = pdf.jpeg_masse(roh)
            if not masse or masse[2] not in (1, 3):
                raise SchuleFehler("Das Bild lässt sich nicht lesen. Bitte ein anderes PNG oder JPEG wählen.")
            db.einstellung_setzen(con, "schullogo", base64.b64encode(roh).decode("ascii"))
        db.einstellung_setzen(con, "schullogo_stand", db.jetzt())
