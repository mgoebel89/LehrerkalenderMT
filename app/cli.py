"""Befehle fuer die Konsole des Containers (Aufruf ueber /usr/local/bin/lehrerkalender):

  lehrerkalender einrichtungscode            Code fuer /einrichtung zeigen (nur solange es kein Konto gibt)
  lehrerkalender konten                      alle Lehrkraft-Konten auflisten
  lehrerkalender admin <kuerzel> <name...>   Admin-Konto mit vorlaeufigem Passwort anlegen (Notfall)
  lehrerkalender passwort <kuerzel>          vorlaeufiges Passwort setzen und Konto entsperren (Notfall)
  lehrerkalender sicherung                   Sicherung (ZIP) nach /var/lib/lehrerkalender/sicherungen (vor jedem Update)
  lehrerkalender wiederherstellung-pruefen <datei>
                                             Sicherung (ZIP oder .sqlite) pruefen und zum Einspielen bereitlegen
  lehrerkalender wiederherstellung-ausfuehren [--konsole]
                                             bereitliegende Sicherung einspielen (nur bei gestopptem Dienst; das macht
                                             lehrerkalender-wiederherstellen als root)
"""
import os
import secrets
import sys

from . import db, konten, updates, wiederherstellung


def _vorlaeufig():
    return secrets.token_urlsafe(9)


def _angaben_zeigen(a):
    print("Sicherung: Datenbankstand %d (hier %d), %s Konten, Admins: %s" % (a["stand"], a["aktueller_stand"], a["konten"],
                                                                         ", ".join(a["admins"])))
    print("  Klassen: %s, Prüfungen: %s, Unterrichtsbesuche: %s, letzte Änderung: %s" % (
        a["klassen"], a["pruefungen"], a["besuche"], a["letzte_aenderung"] or "–"))


def main(argv):
    daten_dir = os.environ.get("LEHRERKALENDER_DATEN", "/var/lib/lehrerkalender")
    befehl = argv[0] if argv else ""
    # Einspielen: die bisherige Datenbank erst gar nicht oeffnen (sie wird ausgetauscht)
    if befehl == "wiederherstellung-pruefen" and len(argv) == 2:
        _angaben_zeigen(wiederherstellung.bereitlegen(argv[1], daten_dir))
        return 0
    if befehl == "wiederherstellung-ausfuehren":
        wiederherstellung.ausfuehren(daten_dir, mit_auftrag="--konsole" not in argv)
        return 0
    con = db.oeffnen(daten_dir)
    if befehl == "einrichtungscode":
        code = konten.einrichtungscode(con)
        print(code if code else "Die Einrichtung ist abgeschlossen (es gibt schon ein Konto).")
    elif befehl == "konten":
        for k in konten.liste(con):
            print("%-8s %-10s %s%s" % (k["kuerzel"], k["rolle"], k["name"], "  (gesperrt)" if k["gesperrt"] else ""))
    elif befehl == "admin" and len(argv) >= 3:
        pw = _vorlaeufig()
        with db.transaktion(con):
            k = konten.anlegen(con, argv[1], " ".join(argv[2:]), "admin", pw, vorlaeufig=True)
        print("Admin %s angelegt. Vorläufiges Passwort: %s (muss bei der ersten Anmeldung geändert werden)" % (k["kuerzel"], pw))
    elif befehl == "passwort" and len(argv) == 2:
        zeile = con.execute("SELECT id FROM lehrkraft WHERE kuerzel = ?", (argv[1].lower(),)).fetchone()
        if zeile is None:
            print("Kein Konto mit dem Kürzel %s." % argv[1])
            return 1
        pw = _vorlaeufig()
        with db.transaktion(con):
            konten.passwort_setzen(con, zeile[0], pw, vorlaeufig=True)
            con.execute("UPDATE lehrkraft SET gesperrt = 0 WHERE id = ?", (zeile[0],))
        print("Vorläufiges Passwort für %s: %s (muss bei der nächsten Anmeldung geändert werden)" % (argv[1].lower(), pw))
    elif befehl == "sicherung":
        print("Sicherung angelegt: %s" % updates.sicherung_ablegen(con, daten_dir))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (konten.KontoFehler, wiederherstellung.WiederherstellungFehler) as f:
        print(f)
        sys.exit(1)
