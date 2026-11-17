#!/bin/sh
# Konsolenbefehle von Lehrerkalender MT (als /usr/local/bin/lehrerkalender installiert). Ohne Argument: Hilfe.
cd /opt/lehrerkalender || exit 1
# WireGuard braucht root: lehrerkalender vpn ... (deploy/vpn.sh)
if [ "${1:-}" = vpn ]; then
  shift
  exec /usr/local/sbin/lehrerkalender-vpn "$@"
fi
exec runuser -u lehrerkalender -- env LEHRERKALENDER_DATEN=/var/lib/lehrerkalender python3 -m app.cli "$@"
