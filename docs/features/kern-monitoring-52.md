# kern-monitoring-52: „Mehr Log“ unter OPNsense liest das Systemlog

Roadmap: R-1630 (BUG).

## Problem / Motivation
„Mehr Log“ (Desktop, Monitoring-Dienstliste) führt unter FreeBSD und OPNsense
`grep -h -F -e '<name>' /var/log/messages | tail -n 200` aus (`build_journal_args`,
`apps/desktop/src-tauri/src/connection/ssh.rs`). OPNsense schreibt mit syslog-ng aber kein `/var/log/messages`: die
Zeilen, die keine Dienst-Datei aufnimmt, landen ab `notice` in `/var/log/system/system_YYYYMMDD.log`
(opnsense/core `src/opnsense/service/templates/OPNsense/Syslog/syslog-ng-local.conf`, Branch master, gelesen
2026-11-19; die Doku-Seite `docs.opnsense.org/manual/logging.html` lieferte 404). Der Tab bleibt dort leer.

## Ziel & Nicht-Ziele
- **Ziel:** Unter FreeBSD und OPNsense durchsucht derselbe feste Befehl `/var/log/messages` und
  `/var/log/system/system_*.log`; fehlt eine der Dateien, zeigt er die Zeilen der anderen. Der Befehl läuft in
  `sh -c '…'`, weil die Login-Shell unter FreeBSD csh/tcsh sein kann (dort bräche `2>/dev/null` und ein Glob ohne
  Treffer).
- **Nicht-Ziel:** die Dienst-eigenen Dateien von OPNsense (`/var/log/<dienst>/<dienst>_YYYYMMDD.log`); die
  Abbildung Dienstname → Datei ist nicht belegt.
- **Nicht-Ziel:** der UI-Hinweis in `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (nennt `/var/log/messages`):
  dieselbe Stelle plant klein-nachlese-15 T3 um; die Klein-Session nimmt den Pfad dort mit.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/connection/ssh.rs` (FreeBSD-Zweig von `build_journal_args` und sein Test),
`docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `changelog.d/kern-monitoring-52.md`.

## Datenmodell / API / Migrationen
Keine. Der Dienstname bleibt auf die FreeBSD-Klasse begrenzt (Buchstaben, Ziffern, `_ . -`), er steht in doppelten
Anführungszeichen innerhalb der einfachen von `sh -c`.

## Externe Integrationen
OPNsense syslog-ng-Vorlagen (Quelle oben); FreeBSD sh(1).

## Trade-offs & Alternativen
Alle Tagesdateien statt nur der neuesten: der Glob ist ohne Shell-Logik wie `ls | tail` in sh und csh gleich
lesbar; `tail -n 200` begrenzt die Ausgabe, die Dateinamen sortieren nach Datum.

## Risiken & Rollback
Bei langer Aufbewahrung liest grep mehr Daten (einmalig je Klick, nur lesend). Rollback: Revert.

## Doku-Impact
`docs/admin/monitoring.html` DE+EN (Abschnitt „Mehr Log“), CHANGELOG.

## Offene Fragen
Keine.
