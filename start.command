#!/bin/bash
# Startet das Aktien-Tool im Browser. Einfach doppelklicken.
cd "$(dirname "$0")" || exit 1
PORT=8765
echo "Aktien-Tool wird gestartet ..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 fehlt. Bitte im Terminal 'xcode-select --install' ausfuehren."
  read -r -p "Enter zum Schliessen" _; exit 1
fi
if [ ! -f data/universe.json ]; then
  echo "Noch keine Daten gefunden - erzeuge Demodaten ..."
  python3 collector/demo_daten.py
fi
python3 -m http.server $PORT >/dev/null 2>&1 &
SRV=$!
sleep 1
open "http://localhost:$PORT/web/index.html"
echo ""
echo "Laeuft auf http://localhost:$PORT/web/index.html"
echo "Dieses Fenster offen lassen. Zum Beenden: Strg+C oder Fenster schliessen."
trap 'kill $SRV 2>/dev/null' EXIT
wait $SRV
