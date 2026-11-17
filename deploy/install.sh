#!/bin/bash
# Lehrerkalender MT im Container installieren oder aktualisieren (Ubuntu 24.04 / Debian 12). Als root aus dem Repo-Ordner:
#
#   git clone https://github.com/mgoebel89/LehrerkalenderMT /opt/lehrerkalender && bash /opt/lehrerkalender/deploy/install.sh
#
# Legt den Systembenutzer lehrerkalender an, Daten in /var/lib/lehrerkalender (Datenbank, Zertifikate, Sicherungen).
# Dienste: lehrerkalender (Webseite 80/443), lehrerkalender-tls.timer (Zertifikat), lehrerkalender-firewall (nur 22/80/443),
# lehrerkalender-update-pruefen.timer/.path und lehrerkalender-update-ausfuehren.path (Update aus dem Lehrerbereich),
# lehrerkalender-vpn-anfrage.path (VPN aus Admin > System), lehrerkalender-wiederherstellen.path (Sicherung einspielen).
# Befehle danach: lehrerkalender (Konsole, z.B. lehrerkalender einrichtungscode, lehrerkalender vpn status),
# lehrerkalender-update.
set -euo pipefail
ZIEL=/opt/lehrerkalender
DATEN=/var/lib/lehrerkalender

cd "$(dirname "$(readlink -f "$0")")/.."
[ "$(pwd)" = "$ZIEL" ] || { echo "Bitte aus $ZIEL aufrufen (git clone ... $ZIEL)."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }

echo "==> Pakete"
fehlt=""
for befehl in python3 openssl nft git; do command -v "$befehl" >/dev/null || fehlt=1; done
[ -e /usr/share/zoneinfo/Europe/Berlin ] || fehlt=1
python3 -c 'import icalendar, recurring_ical_events' 2>/dev/null || fehlt=1   # Schulkalender-Abo (ICS)
python3 -c 'import reportlab, pypdf, PIL' 2>/dev/null || fehlt=1   # PDF (Formulare, Feedbackboegen, Protokolle)
if [ -n "$fehlt" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  apt-get install -y -q python3 openssl nftables git ca-certificates tzdata python3-icalendar \
    python3-recurring-ical-events python3-reportlab python3-pypdf python3-pil >/dev/null
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Lehrerkalender MT braucht Python 3.11 oder neuer."; exit 1; }

echo "==> Benutzer und Ordner"
id lehrerkalender >/dev/null 2>&1 || useradd --system --home-dir "$DATEN" --shell /usr/sbin/nologin lehrerkalender
install -d -o lehrerkalender -g lehrerkalender -m 750 "$DATEN" "$DATEN/update" "$DATEN/sicherungen" "$DATEN/vpn" "$DATEN/wiederherstellung"
install -d -o root -g root -m 755 /var/lib/lehrerkalender-update /var/lib/lehrerkalender-vpn /var/lib/lehrerkalender-wiederherstellung   # Ergebnisse von root, fuer den Webdienst nur lesbar
find "$DATEN" -maxdepth 1 -name 'lehrerkalender.sqlite*' -exec chmod 640 {} +
install -d -o root -g root -m 755 /etc/lehrerkalender
# der Code gehoert root: der Webdienst kann ihn nicht veraendern
chown -R root:root "$ZIEL"
chmod -R go-w "$ZIEL"

echo "==> Befehle, Dienste, Firewall"
install -o root -g root -m 755 deploy/tls.sh /usr/local/sbin/lehrerkalender-tls
install -o root -g root -m 755 deploy/update.sh /usr/local/sbin/lehrerkalender-update
install -o root -g root -m 755 deploy/selbstupdate.sh /usr/local/sbin/lehrerkalender-selbstupdate
install -o root -g root -m 755 deploy/vpn.sh /usr/local/sbin/lehrerkalender-vpn
install -o root -g root -m 755 deploy/wiederherstellen.sh /usr/local/sbin/lehrerkalender-wiederherstellen
install -o root -g root -m 755 deploy/lehrerkalender-cli.sh /usr/local/bin/lehrerkalender
install -o root -g root -m 644 deploy/firewall.nft /etc/lehrerkalender/firewall.nft
UPDATE_EINHEITEN="lehrerkalender-update-pruefen.path lehrerkalender-update-pruefen.timer lehrerkalender-update-ausfuehren.path lehrerkalender-vpn-anfrage.path lehrerkalender-wiederherstellen.path"
for einheit in lehrerkalender.service lehrerkalender-tls.service lehrerkalender-tls.timer lehrerkalender-firewall.service \
    lehrerkalender-update-pruefen.service lehrerkalender-update-ausfuehren.service lehrerkalender-vpn-anfrage.service \
    lehrerkalender-wiederherstellen.service $UPDATE_EINHEITEN; do
  install -o root -g root -m 644 "deploy/$einheit" "/etc/systemd/system/$einheit"
done
systemctl daemon-reload
/usr/local/sbin/lehrerkalender-tls
systemctl enable -q lehrerkalender-firewall.service lehrerkalender-tls.timer lehrerkalender.service $UPDATE_EINHEITEN
systemctl restart lehrerkalender-firewall.service   # Regeln neu laden (auch nach einem Update)
systemctl start lehrerkalender-tls.timer $UPDATE_EINHEITEN
systemctl restart lehrerkalender.service

for _ in $(seq 1 20); do
  systemctl is-active --quiet lehrerkalender.service && python3 - 2>/dev/null <<'PRUEFEN' && break
import ssl, urllib.request
kontext = ssl.create_default_context(cafile="/var/lib/lehrerkalender/tls/ca.crt")
kontext.check_hostname = False
urllib.request.urlopen("https://127.0.0.1/api/status", context=kontext, timeout=3).read()
PRUEFEN
  sleep 1
done
if ! systemctl is-active --quiet lehrerkalender.service; then
  journalctl -u lehrerkalender.service -n 30 --no-pager
  echo "Der Dienst lehrerkalender laeuft nicht (siehe oben)."
  exit 1
fi

# einmal nach einer neueren Version suchen (im Hintergrund, damit die Einstellungen gleich den Stand zeigen)
systemctl start --no-block lehrerkalender-update-pruefen.service

ip=$(hostname -I | awk '{print $1}')
code=$(/usr/local/bin/lehrerkalender einrichtungscode 2>/dev/null || true)
echo
echo "Lehrerkalender MT laeuft: https://$ip"
echo "  Stammzertifikat fuer die Lehrer-Geraete: http://$ip/ca.crt"
if [ -n "$code" ] && [ "${code#Die Einrichtung}" = "$code" ]; then
  echo "  Erstes Admin-Konto anlegen: https://$ip/einrichtung   Einrichtungscode: $code"
fi
