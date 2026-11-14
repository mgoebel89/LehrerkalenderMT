#!/bin/bash
# LehrerkalenderMT aktualisieren: neuesten Stand holen und install.sh erneut ausfuehren (Daten bleiben erhalten).
# Als /usr/local/sbin/lehrerkalender-update installiert.
set -euo pipefail
cd /opt/lehrerkalender
alt=$(git rev-parse --short HEAD)
git pull -q --ff-only
neu=$(git rev-parse --short HEAD)
echo "Stand $alt -> $neu"
exec bash deploy/install.sh
