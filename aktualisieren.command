#!/bin/bash
# Holt frische Daten von Stooq, SEC und den News-Feeds.
cd "$(dirname "$0")" || exit 1
python3 collector/fetch_data.py "$@"
echo ""
read -r -p "Fertig. Enter zum Schliessen " _
