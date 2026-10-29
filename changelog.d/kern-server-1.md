### Changed

- **Server: Warnung bei zu weiten Rechten der Schluesseldatei:** Duerfen Gruppe oder andere `data/.secret_key`
  lesen, warnt der Server beim Start (Pfad und Modus); der Schluessel wird weiter genutzt.
- **Server-Hooks: eigenes HOME fuer den Worker:** Hat der Server kein `HOME`, bekommt der Hook-Worker
  `DATA_DIR/hooks-home` (0700, beim ersten Lauf angelegt) statt `/tmp`.

### Fixed

- **Server: Mail-Betreff einzeilig wie im Monitoring:** Der Benachrichtigungs-Hub ersetzt Steuerzeichen und
  Zeilentrenner im Betreff durch Leerzeichen, wie es das Monitoring seit monitoring-hardening-2 tut; der Text der
  Mail bleibt unveraendert.
