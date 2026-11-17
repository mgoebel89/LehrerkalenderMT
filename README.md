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
| B | Stundenplan von Hand mit Versionen und A/B-Wochen, Feiertage RLP, Wochenplan nach Uhrzeit mit Ausfall, Vertretung (beide Richtungen), Verschieben, Zusatzstunde, eigene Termine und Merker, Startseite; eigene Gruppen je Klasse (0.2.1) | gebaut (0.2.1) |
| C1 | Schuljahr (Admin), Bibliothek je Lernfeld, Themenfolge je Klasse/Gruppe, Fließen auf die Blöcke (Stecknadel, Lernfeld-Spuren), Raster Doppelstunden und Schuljahr, Thema im Wochenplan | gebaut (0.3.0) |
| C2 | Stunden-Overlay mit Ist-Stand und Rückgängig, Lehrstoff kopieren, Merker für die nächste Stunde, Tagesansicht, Bilanz, „Ist offen“ auf der Startseite, Tage und Ferien im Raster deutlich abgehoben; Vertretung mit oder ohne eigenes Thema, Ausfall/Vertretung/Verschieben im Overlay (0.4.1); erster/letzter Unterrichtstag je Klasse, z. B. Ausschulung (0.4.2); Sonderstundenplan von–bis, z. B. Einführungswoche, und Knopf „Schuljahresbeginn“ (0.4.3); Kalender-Abos (ICS): Ferien und Schultermine (Admin), eigene z. B. Outlook (0.4.4) | gebaut (0.4.4) |
| D1 | Schülerlisten (Moodle-CSV, von Hand), Prüfungen (fester Termin in der Planung oder Fenster mit Frist), Erfassung je Aufgabe, Gesamtpunkte oder Feedbackbogen, Notenberechnung mit Rechenweg, Schlüsselwahl, Abschließen, Notenspiegel, eigene Notenschlüssel und Standard (0.5.0); Klassenwahl als Karteireiter in Planung und Prüfungen (0.5.1) | gebaut (0.5.1) |
| C3 | Thema als Ordner mit Umfang (Budget), darin Lernsituationen; Bibliothek Lernfeld → Thema → Lernsituationen; Raster mit aufklappbaren LS-Zeilen und „noch offen“; Schuljahr als Startansicht, aktuelle Woche in allen Rastern hinterlegt (Migration 11) | gebaut (0.6.0) |
| C4 | Gruppen ohne eigene Planung: eine Themenfolge je Klasse, Gruppenstunden am selben Tag bilden einen Schritt (gleicher Stoff), Ausfall nur einer Gruppe → „holt nach“; Prüfungen zusammen oder getrennt je Gruppe, Hinweis ohne passenden Unterricht (Migration 12) | gebaut (0.7.0) |
| D2a | Checkliste für Laborreihen (Versuche mit Haken und Punkten, je Versuch Team oder einzeln, nur Testat möglich), Teams je Prüfung (zufällig bilden, Team-Bereiche auch im Feedbackbogen), Matrix Schüler × Versuch; Prüfung aus dem Raster anlegen; Wochenplan zeigt Ausfall/Vertretung als farbiges Band (Migration 13) | gebaut (0.8.0) |
| D2b | Prüfungsmodus am Tablet (Vollbild): einzeln nacheinander mit Countdown je Schüler/Team (Vorwarnung gelb, Ende rot, Überziehung) oder alle parallel mit gemeinsamer Uhr; Dauer je Schüler protokolliert; Fragenpool je Prüfung, Fragen ziehen ohne Wiederholung, Spontanfragen notieren, Einschätzung 0–4 je Frage, optional als Bereich in der Note (Migration 14) | gebaut (0.9.0) |
| D2c | Exporte je Prüfung: Notenspalte für die Excel-Notenliste kopieren (alle Schüler alphabetisch, Dezimalnote mit Komma), PDF-Ergebnisliste mit Notenspiegel, Rückmeldebogen je Schüler zum Aushändigen, CSV fürs Moodle-Bewertungsbuch (E-Mail, Prozent, Note im Feedback); eigener PDF-Schreiber ohne Zusatzpakete | gebaut (0.10.0) |
| D2d | Moodle-Ergebnisse übernehmen (Bericht „Antworten“/„Bewertungen“ als JSON oder CSV): in eine Prüfung mit Gesamtpunkten (umgerechnet) oder als neue Prüfung (Titel aus dem Dateinamen, Termin am Prüfungstag im passenden Block); bester Versuch, Zuordnung mit Vorschlägen, Nachschreiber-Vermerk, Beginn/Dauer; Schülerlisten-Import aus Moodle wieder funktionsfähig | gebaut (0.11.0) |
| Schule | Schullogo (Admin, Grunddaten → Schule und Logo; Bild wird im Browser zu JPEG), Schulname und Webadresse; Logo auf der Anmeldeseite und in der Kopfzeile; Dokumente im DRS-Design: Logo oben links, Angaben rechts, feine Linie, Farbband Blau/Grün/Pink/Gelb (4:1:1:1) im Fuß | gebaut (0.12.0) |
| E | Teilen im Kollegium | offen |
| F1 | Formularcenter mit Ablage und Stand (erstellt, abgegeben, genehmigt); Stundenplanänderung/Beurlaubung füllt das Schul-PDF aus Ausfällen und Vertretungen der Woche (Vorlage lädt der Admin hoch, nicht im Repo); Unterschrift und Paraphe mit Stift oder Finger zeichnen; Start auch nach Ausfall/Vertretung, aus der Woche und aus einem Termin (Migration 15; braucht python3-pypdf und python3-reportlab) | gebaut (0.13.0) |
| F2 | Unterrichtsbesuche aus dem alten Lehrerkalender übernommen, je Konto einschaltbar (Einstellungen › Konto) und nur für das eigene Konto sichtbar: Anwärter, Besuchs-Assistent, Handy-Erfassung mit Phasen, Kategorien, Beratungsschwerpunkten, Wertung, Foto und Skizze, Nachbereitung, Protokoll als PDF/ODT mit Schullogo (Migration 16; braucht python3-reportlab und python3-pil) | gebaut (0.14.0) |
| F3 | Paperless | offen |
| G1 | VPN (aus TrackingDRS): Container als Teilnehmer im bestehenden WireGuard-VPN, Einrichtung unter Admin → System (Werte oder fertige Client-Datei) oder per Konsole; über das VPN nur HTTPS, für alle Teilnehmer, Antworten über das VPN zurück. Von zuhause unter einer festen Zugriffsadresse (vorbelegt: Schuladresse), Zertifikat bleibt; Kopiervorlagen für VPS, WireGuard-App und Heimnetz | gebaut (0.15.0) |
| G2 | Sicherung einspielen unter Admin → System (ZIP aus „Sicherung herunterladen“, z. B. Testinstanz → Produktivsystem): prüfen und Inhalt zeigen, mit Passwort bestätigen, vorher Sicherung des jetzigen Stands, Austausch durch den Dienstbenutzer, alle Anmeldungen enden; Konsole: `lehrerkalender-wiederherstellen <datei>` | gebaut (0.16.0) |
| G | Diktat, Feinschliff | offen |

## Installation (Proxmox)

Auf dem Proxmox-Host als root (das Repository muss dafür öffentlich sein):

    bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/LehrerkalenderMT/main/proxmox/lehrerkalender.sh)"

Danach im Browser `https://<container>/einrichtung` mit dem Einrichtungscode vom Ende des Skripts. Weitere Konten
entstehen über Einladungscodes (Admin → Konten).

Im Container: `lehrerkalender einrichtungscode`, `lehrerkalender konten`, `lehrerkalender passwort <kürzel>`
(Notfall), `lehrerkalender sicherung`, `lehrerkalender-update`, `lehrerkalender vpn einrichten|status|server|aus`.

## Entwickeln

    python tests/dev_server.py          # http://127.0.0.1:8472, Daten in .dev-daten
    python -m unittest discover -s tests

Der Code muss auch mit Python 3.11 laufen (Test `Python311`).
