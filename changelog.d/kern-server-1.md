### Changed

- **Server: Warnung bei zu weiten Rechten der Schluesseldatei:** Duerfen Gruppe oder andere `data/.secret_key`
  lesen, warnt der Server beim Start (Pfad und Modus); der Schluessel wird weiter genutzt.
- **Server-Hooks: eigenes HOME fuer den Worker:** Hat der Server kein `HOME`, bekommt der Hook-Worker
  `DATA_DIR/hooks-home` (0700, beim ersten Lauf angelegt) statt `/tmp`.

### Fixed

- **Server: Mail-Betreff einzeilig wie im Monitoring:** Der Benachrichtigungs-Hub ersetzt Steuerzeichen und
  Zeilentrenner im Betreff durch Leerzeichen, wie es das Monitoring seit monitoring-hardening-2 tut; der Text der
  Mail bleibt unveraendert.
- **Server-Hooks: NaN/Infinity im Webhook-Body ergibt 422:** Ein JSON-Body mit `NaN`, `Infinity` oder `-Infinity`
  fuehrte zu 500, sobald die Antwort ihn zurueckgab; der Trigger lehnt nicht-endliche Zahlen jetzt mit 422 an
  ihrer Stelle ab.
- **Server-CLI: Passwort ueber 128 Zeichen abgewiesen:** `create-admin` und `reset-admin` nahmen ein Passwort an,
  mit dem der Login (hoechstens 128 Zeichen) nie gelingen konnte; sie weisen es jetzt mit Exit 1 ab.
