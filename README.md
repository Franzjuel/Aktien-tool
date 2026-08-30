# Aktien-Tool

Eigenes Analysewerkzeug fuer Aktien: Screener, Kennzahlen, Quartalszahlen ueber Jahre,
Insidergeschaefte und News. Laeuft lokal, kostet nichts, braucht keine Zusatzpakete.

## Schnellstart

1. Doppelklick auf `start.command` -> Browser oeffnet sich (zeigt zunaechst Demodaten)
2. Doppelklick auf `aktualisieren.command` -> holt echte Daten
3. Nochmal `start.command`

## Aufbau

    collector/config.json      Watchlist und SEC-Kontaktadresse  <- hier aenderst du Titel
    collector/fetch_data.py    Datensammler (nur Python-Standardbibliothek)
    collector/demo_daten.py    erzeugt Beispieldaten zum Ausprobieren
    collector/selbsttest.py    prueft die Rechenlogik ohne Internet
    data/                      erzeugte JSON-Dateien
    web/index.html             die Oberflaeche (eine einzige Datei)
    start.command              startet lokalen Server + Browser
    aktualisieren.command      holt frische Daten
    .github/workflows/         naechtliche Automatik, sobald das Projekt auf GitHub liegt

## Befehle

    python3 collector/fetch_data.py             alle Titel
    python3 collector/fetch_data.py AAPL NVDA   nur einzelne
    python3 collector/fetch_data.py --ohne-sec  schnell, nur Kurse
    python3 collector/selbsttest.py             Rechenlogik pruefen
    python3 collector/demo_daten.py             Demodaten neu erzeugen

## Datenquellen

- Kurse und Historie: Stooq (kein Schluessel noetig, weltweit)
- Bilanz-, Quartals- und Jahreszahlen: SEC EDGAR XBRL (US-Titel)
- Insidergeschaefte: SEC EDGAR Form 4
- Nachrichten: Yahoo Finance RSS und Google News RSS

Keine Anlageberatung. Alle Angaben ohne Gewaehr.
