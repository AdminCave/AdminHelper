### Changed

- **Backup und Diagnose:** `scripts/backup.sh` und `scripts/diagnostics.sh` legen Archiv und Bundle in einem eigenen,
  nur fuer den Aufrufer lesbaren Verzeichnis im Ausgabeordner an, bevor sie es an seinen Platz legen; Ort, Name und
  Inhalt der Ergebnisse bleiben gleich.
- **Entwickler-Werkzeuge:** `worktree-teardown.sh` prueft einen gemergten Branch gegen `origin/main` und raeumt
  fremd-eigene Reste ueber einen Wegwerf-Container; `nightly.sh` raeumt alte Berichte unter `.ah-out/weekly/` auf;
  `roadmap.py stats` liest den Verlauf in einem Durchgang und nennt keine Kevin-Minuten mehr; die Test-Venvs von
  `run.sh` installieren die Versionen aus dem Lock der Komponente.
