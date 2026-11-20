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
| C5 | Prüfungen unterbrechen den Unterricht: Termin belegt seinen Block vor allem anderen (auch vor festgesetzten Themen und in Blöcken eines anderen Lernfelds), das Thema läuft danach nahtlos weiter. Unterrichtsinhalt (Text fürs Klassenbuch, „In WebUntis kopieren“) und eigene Notizen je gehaltener Stunde; Vorstunde übernehmen, Text der anderen Gruppe übernehmen, bei Prüfungen „Prüfung: Titel“ als Vorschlag (Migration 17) | gebaut (0.17.0) |
| E | Teilen im Kollegium, vom Admin einschaltbar (Admin › System, Vorgabe aus, erst nach Freigabe durch Schulleitung und Datenschutz): Lehrkräfte derselben Klasse (laut Stundenplan) sehen gegenseitig die ganze Themenplanung der Klasse (nur lesen, Karte „Kollegium dieser Klasse“ in der Planung) mit den Unterrichtsinhalten der gehaltenen Stunden, Notizen einer Stunde nur mit Haken „auch fürs Kollegium sichtbar“ (0.22.0), und Termine, die ausdrücklich für die Klasse geteilt sind (Wochenplan, Stunde); ändern nur eigene. Schülerlisten, Noten, Merker und Privates bleiben privat. PDFs öffnen zum Drucken in einem neuen Tab (0.20.1) (Migrationen 20, 21) | gebaut (0.22.0) |
| F1 | Formularcenter mit Ablage und Stand (erstellt, abgegeben, genehmigt); Stundenplanänderung/Beurlaubung füllt das Schul-PDF aus Ausfällen und Vertretungen der Woche (Vorlage lädt der Admin hoch, nicht im Repo); Unterschrift und Paraphe mit Stift oder Finger zeichnen; Start auch nach Ausfall/Vertretung, aus der Woche und aus einem Termin (Migration 15; braucht python3-pypdf und python3-reportlab) | gebaut (0.13.0) |
| F2 | Unterrichtsbesuche aus dem alten Lehrerkalender übernommen, je Konto einschaltbar (Einstellungen › Konto) und nur für das eigene Konto sichtbar: Anwärter, Besuchs-Assistent, Handy-Erfassung mit Phasen, Kategorien, Beratungsschwerpunkten, Wertung, Foto und Skizze, Nachbereitung, Protokoll als PDF/ODT mit Schullogo (Migration 16; braucht python3-reportlab und python3-pil) | gebaut (0.14.0) |
| F3a | Dokumente: eigenes Paperless-ngx je Konto (Einstellungen › Konto, Token verschlüsselt, Schlüssel im Datenordner), Liste nach Anzeige-Tags mit Suche und Filter, Vorschau, Original, Metadaten und Notizen ändern, Hochladen mit Upload-Tag und Speicherpfad; VPN: „Weitere Ziele über das VPN“ (z. B. Paperless im Heimnetz) (Migration 18; braucht python3-cryptography) | gebaut (0.18.0) |
| F3b | In Paperless ablegen: Ergebnisliste, Rückmeldebögen (alle oder einzeln aus dem Rechenweg), Formulare und Protokoll eines Unterrichtsbesuchs; der Server erzeugt das PDF und legt es mit Titel, Datum, Typ, Korrespondent und Tags ab (Upload-Tag und Speicherpfad automatisch) | gebaut (0.19.0) |
| F3c | Dokumente aus Paperless an Prüfungen hängen (Export-Reiter, Suche, Vorschau, Lösen); über „In Paperless“ abgelegte Ergebnislisten und Rückmeldebögen hängen automatisch dran, sobald Paperless sie verarbeitet hat. Themen/LS bekommen keine Anhänge (Unterrichtsmaterial liegt in Moodle) (Migration 19) | gebaut (0.20.0) |
| G1 | VPN (aus TrackingDRS): Container als Teilnehmer im bestehenden WireGuard-VPN, Einrichtung unter Admin → System (Werte oder fertige Client-Datei) oder per Konsole; über das VPN nur HTTPS, für alle Teilnehmer, Antworten über das VPN zurück. Von zuhause unter einer festen Zugriffsadresse (vorbelegt: Schuladresse), Zertifikat bleibt; Kopiervorlagen für VPS, WireGuard-App und Heimnetz | gebaut (0.15.0) |
| G2 | Sicherung einspielen unter Admin → System (ZIP aus „Sicherung herunterladen“, z. B. Testinstanz → Produktivsystem): prüfen und Inhalt zeigen, mit Passwort bestätigen, vorher Sicherung des jetzigen Stands, Austausch durch den Dienstbenutzer, alle Anmeldungen enden; Konsole: `lehrerkalender-wiederherstellen <datei>` | gebaut (0.16.0) |
| H1 | Grunddaten für alle: ein neuer Bildungsgang mit Lernfeldern bekommt gleich die Stufen Grundstufe und Fachstufe 1–3; Lehrkräfte legen fehlende Lernfelder/Module selbst an (in Bildungsgängen ihrer Klassen laut Stundenplan) – in der Bibliothek, im Themen-Dialog der Planung, im Stundenplan-Block und unter Einstellungen › Lernfelder; alle sehen sie, ändern/löschen nur Ersteller und Admin, löschen nur unbenutzt (Migration 22) | gebaut (0.23.0) |
| H2 | Gemeinsame Schülerliste je Klasse: alle Lehrkräfte der Klasse (laut eigenem Stundenplan, auch vergangenem, oder mit eigenen Prüfungen in der Klasse; Admin alle) sehen und pflegen dieselbe Liste (Name, E-Mail, „in der Klasse“, Moodle-CSV); Gruppeneinteilung, Prüfungen und Noten bleiben privat. Beim Update werden die bisher privaten Listen zusammengeführt (gleiche E-Mail bzw. gleicher Name ohne widersprechende E-Mail); unklare Fälle zeigt die Liste als „Mögliche Doppelungen“ mit Zusammenführen bzw. „Sind verschiedene“. Änderungen stehen mit Kürzel im Protokoll (Migrationen 23, 24) | gebaut (0.24.0) |
| H3 | Fotos zu Schülern, gemeinsam für die Lehrkräfte der Klasse: aufnehmen mit der Kamera (Tablet/Handy) oder Datei, Ausschnitt im Browser wählen (Hochformat 4:5, JPEG 400 × 500); Vorschaubild bzw. Initialen in Schülerliste, Erfassung, Teams und Prüfungsmodus (dort groß), Ansicht „Fotos“ als Raster und Fotoliste der Klasse als PDF im DRS-Design (20 je Seite); Fotos bleiben, bis jemand sie löscht, und stehen in jeder Sicherung (Migration 25) | gebaut (0.25.0) |
| H3a | Bereich „Klassen“ in der Seitenleiste für alle Lehrkräfte mit der gemeinsamen Schülerliste und den Fotos (vorher Prüfungen › Schülerlisten; alte Adresse leitet um); Admin-Eintrag heißt jetzt „Klassenverwaltung“. Die Seiten der Unterrichtsbesuche (Übersicht, Besuch, Einstellungen) haben Kopf und Seitenleiste wie die App (web/rahmen.js); nur die Vollbild-Erfassung am Handy bleibt ohne | gebaut (0.25.1) |
| H4 | Beobachtungen je Schüler, immer privat je Lehrkraft: Verlauf mit Datum, optional Kategorie (Leistung, Arbeitsverhalten, Sozialverhalten, Sonstiges) und Tendenz (+ ○ −); Klick in der Schülerliste öffnet den Verlauf (Stammdaten über den Stift), Spalten mit Anzahl, Tendenz und letztem Eintrag; Klassen › Beobachtungen mit Filtern (Kategorie, Tendenz, Zeitraum, Suche); im Stunden-Fenster mehrere Schüler antippen und auf einmal notieren (mit Verweis auf die Stunde); PDF je Schüler (mit Foto) und je Klasse; Startseite bietet Beobachtungen zu Ehemaligen, älter als ein Jahr, zum Löschen an; Schüler mit Beobachtungen lassen sich nicht löschen (Migration 26) | gebaut (0.26.0) |
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
