### Added

- **Desktop: Kanaele im eingebetteten RDP (Backend):** Die eingebettete Sitzung liest jetzt die RDP-Optionen der
  Verbindung. Die Zwischenablage ist an (Text und Bilder, keine Dateien). Audio folgt `audio` (`local` oder ungesetzt
  lokal, `remote` auf dem Server, `off` aus; Mikrofon aus, unter Windows vorerst immer aus). `drives: true` gibt den
  Downloads-Ordner als Laufwerk frei; fehlt er, startet die Sitzung ohne Laufwerk und meldet das. Das Linux-Paket
  haengt an `libasound2` (deb) bzw. `alsa-lib` (rpm). Noch ruft keine Oberflaeche die Sitzung auf. Doku:
  Desktop-Entwicklerdoku (DE+EN), THIRD_PARTY_LICENSES.md.
