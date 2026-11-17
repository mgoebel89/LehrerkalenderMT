#!/bin/bash
# Sicherung einspielen (z. B. die Daten der Testinstanz ins Produktivsystem). Als /usr/local/sbin/lehrerkalender-wiederherstellen
# installiert (root).
#
#   lehrerkalender-wiederherstellen anfrage   Auftrag aus Admin > System (gestartet von lehrerkalender-wiederherstellen.path)
#   lehrerkalender-wiederherstellen <datei>   von der Konsole: Sicherung (ZIP oder .sqlite) pruefen, nachfragen, einspielen
#
# root stoppt und startet nur den Dienst. Pruefen, den bisherigen Stand sichern und die Datenbank austauschen macht
# "lehrerkalender wiederherstellung-..." als Dienstbenutzer in dessen Datenordner (app/wiederherstellung.py). Ergebnisse
# fuer die Seite in /var/lib/lehrerkalender-wiederherstellung (lauf.json, protokoll.txt).
set -uo pipefail
DATEN=/var/lib/lehrerkalender
STAND=/var/lib/lehrerkalender-wiederherstellung
umask 022
export TZ=Europe/Berlin   # Zeiten wie in der Datenbank
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }
install -d -o root -g root -m 755 "$STAND"

jetzt() { date '+%Y-%m-%dT%H:%M:%S'; }

lauf() {   # lauf <beginn> <ende|""> <ergebnis|"">
  local ende=null erg=null tmp
  [ -n "$2" ] && ende="\"$2\""
  [ -n "$3" ] && erg="\"$3\""
  tmp=$(mktemp "$STAND/.neu.XXXXXX")
  printf '{"beginn": "%s", "ende": %s, "ergebnis": %s}\n' "$1" "$ende" "$erg" > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$STAND/lauf.json"
}

austauschen() {   # austauschen <Option fuer wiederherstellung-ausfuehren>: Dienst stoppen, tauschen, Dienst starten
  local ergebnis=ok
  echo "== $(jetzt) Dienst stoppen"
  systemctl stop lehrerkalender.service
  echo "== $(jetzt) Sicherung einspielen"
  /usr/local/bin/lehrerkalender wiederherstellung-ausfuehren "$@" || ergebnis=fehler
  echo "== $(jetzt) Dienst starten"
  systemctl start lehrerkalender.service || ergebnis=fehler
  echo "== $(jetzt) Ende: $ergebnis"
  [ "$ergebnis" = ok ]
}

anfrage() {
  local beginn ergebnis=ok
  beginn=$(jetzt)
  lauf "$beginn" "" ""
  austauschen > "$STAND/protokoll.neu" 2>&1 || ergebnis=fehler
  rm -f "$DATEN/wiederherstellung/einspielen"   # nie zweimal (die .path-Einheit startet sonst erneut)
  chmod 644 "$STAND/protokoll.neu"
  mv -f "$STAND/protokoll.neu" "$STAND/protokoll.txt"
  lauf "$beginn" "$(jetzt)" "$ergebnis"
}

konsole() {
  local datei=$1 ziel="$DATEN/wiederherstellung/upload.tmp" antwort
  [ -f "$datei" ] || { echo "Datei nicht gefunden: $datei"; exit 1; }
  install -d -o lehrerkalender -g lehrerkalender -m 750 "$DATEN/wiederherstellung"
  install -o lehrerkalender -g lehrerkalender -m 640 "$datei" "$ziel"
  if ! /usr/local/bin/lehrerkalender wiederherstellung-pruefen "$ziel"; then rm -f "$ziel"; exit 1; fi
  rm -f "$ziel"
  echo
  echo "ACHTUNG: Alle Daten dieses Lehrerkalenders werden durch die Sicherung ersetzt (vorher wird eine Sicherung"
  echo "angelegt). Alle Anmeldungen enden."
  read -r -p "Einspielen? Zum Bestaetigen 'ja' tippen: " antwort
  [ "$antwort" = ja ] || { echo "Nichts eingespielt."; exit 1; }
  austauschen --konsole
}

case "${1:-}" in
  anfrage) anfrage ;;
  "") sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
  *) konsole "$1" ;;
esac
