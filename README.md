# Lehrerkalender MT

Version 2.0 des Lehrerkalenders der David-Roentgen-Schule Neuwied: Unterrichtsplanung mit Fließplanung, Stundenplan
und Wochenplan, Prüfungen und Bewertung, Formulare – für das Kollegium, im eigenen LXC-Container in der Schule.
Technik wie Lernbüro MT und TrackingDRS: Python ohne Framework, SQLite, Oberfläche ohne Build-Schritt, Pakete nur aus
den Paketquellen (Ubuntu 24.04).

Das Konzept (Fassung 2, freigegeben am 14.11.2026) liegt in `docs/KONZEPT.html`.

## Stand

| Stufe | Inhalt | Stand |
|---|---|---|
| A | Grundgerüst, Konten mit Einladungscode, Anmeldung mit optionalem zweitem Faktor, Admin-Grunddaten (Bildungsgänge, Stufen, Lernfelder/Module, Zeitraster, Ferien, Klassen, Konferenz-Notenschlüssel), Update, Sicherung | gebaut (0.1.0) |
| B | Stundenplan von Hand mit Versionen und A/B-Wochen, Feiertage RLP, Wochenplan nach Uhrzeit mit Ausfall, Vertretung (beide Richtungen), Verschieben, Zusatzstunde, eigene Termine und Merker, Startseite | gebaut (0.2.0) |
| C | Unterrichtsplanung: Bibliothek, Fließplanung, Raster, Bilanz, Stunden-Overlay | offen |
| D | Prüfungen und Bewertung | offen |
| E | Teilen im Kollegium | offen |
| F | Formularcenter, Unterrichtsbesuche, Paperless | offen |
| G | VPN, Diktat, Feinschliff | offen |

## Installation (Proxmox)

Auf dem Proxmox-Host als root (das Repository muss dafür öffentlich sein):

    bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/LehrerkalenderMT/main/proxmox/lehrerkalender.sh)"

Danach im Browser `https://<container>/einrichtung` mit dem Einrichtungscode vom Ende des Skripts. Weitere Konten
entstehen über Einladungscodes (Admin → Konten).

Im Container: `lehrerkalender einrichtungscode`, `lehrerkalender konten`, `lehrerkalender passwort <kürzel>`
(Notfall), `lehrerkalender sicherung`, `lehrerkalender-update`.

## Entwickeln

    python tests/dev_server.py          # http://127.0.0.1:8472, Daten in .dev-daten
    python -m unittest discover -s tests

Der Code muss auch mit Python 3.11 laufen (Test `Python311`).
