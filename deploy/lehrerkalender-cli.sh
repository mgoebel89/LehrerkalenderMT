#!/bin/sh
# Konsolenbefehle von Lehrerkalender MT (als /usr/local/bin/lehrerkalender installiert). Ohne Argument: Hilfe.
cd /opt/lehrerkalender || exit 1
exec runuser -u lehrerkalender -- env LEHRERKALENDER_DATEN=/var/lib/lehrerkalender python3 -m app.cli "$@"
