# kern-monitoring-21 — Monitoring: tag-gebundene Checks ohne Fund-Churn

Roadmap: R-1446

## Problem / Motivation
- **Churn nach dem Update (R-1446, Teil 1):** Seit R-1397 trägt die Zusammenfassung einer Instanz eines Moduls mit
  tag-gebundenen Checks den Schlüssel `tag_checks`. Eine vor dem Update gespeicherte Zusammenfassung hat ihn nicht;
  `_seen_again` (`apps/monitoring/app/discovery.py:575`) vergleicht beide und hält sie für verschieden. Jede
  übernommene Wiki.js-Instanz wird so nach dem Update einmal `changed`/`open`, auch auf Tag 3 oder `latest`, und ein
  verworfener Fund geht wieder auf. Die Doku nennt nur den Versionssprung als Grund: „Wechselt das Image auf 3, wird
  der Fund `changed`“ (`docs/admin/monitoring.html`, Zeile `wikijs`).
- **Rückkehr (R-1446, Teil 2):** `_adopt` (`apps/monitoring/app/module_sync.py:424`) schaltet einen tag-gebundenen
  Check aus, wenn das Image auf einen Tag wechselt, den er nicht trägt. Kehrt das Image zurück (3 → 2), bleibt er aus:
  ein `changed`-Fund lässt beim Übernehmen jeden ausgeschalteten Check aus, denn er könnte vom Admin stammen.

## Ziel & Nicht-Ziele
- Fehlt `tag_checks` in einer der beiden Zusammenfassungen, zählt der Schlüssel nicht für den Vergleich (wie
  `containers` vor R-1397, `test_an_adopted_finding_with_a_summary_from_before_containers_stays_adopted`); der Scan
  schreibt ihn still nach.
- Teil 2: Variante A (Kevin 2026-11-17): ein nicht mehr passender Check wird beim Übernehmen gelöscht, bei der
  Rückkehr neu angelegt.
- Nicht: andere Schlüssel der Zusammenfassung, der Katalog-Sync beim Start (`sync_catalog`, er beachtet Tags schon
  über `probe_config`).

## Betroffene Komponenten & Dateien
monitoring: `apps/monitoring/app/discovery.py`, `apps/monitoring/app/module_sync.py`, Tests
`apps/monitoring/tests/test_discovery_match.py`, `apps/monitoring/tests/test_module_sync.py`;
`changelog.d/kern-monitoring-21.md`; bei Teil 2 `docs/admin/monitoring.html` DE+EN.

## Datenmodell / API / Migrationen
Teil 1: keine. Teil 2: je nach Antwort keine (Variante A) oder eine Spalte an `monitor_checks` (Variante B).

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Teil 1: die alten Zusammenfassungen per Migration nachrechnen braucht das Inventar je Server in der Migration; der
  Vergleich ohne fehlenden Schlüssel ist der bestehende Weg (`containers`).
- Teil 2: siehe Offene Fragen.

## Risiken & Rollback
Ein Versionssprung genau im ersten Scan nach dem Update fällt nicht als `changed` auf; erst der nächste Sprung. Der
Katalog-Sync beim Start bindet die neuen Checks dann schon passend zum Tag. Rollback: Revert.

## Doku-Impact
Teil 1 keine (die Doku beschreibt das gewollte Verhalten). Teil 2: Zeile `wikijs` in `docs/admin/monitoring.html`
DE+EN. CHANGELOG-Fragment.

## Offene Fragen
Keine. Teil 2 hat Kevin am 2026-11-17 entschieden: Variante A (ein nicht mehr passender Check wird beim Übernehmen
gelöscht, ohne Grabstein, und bei der Rückkehr neu angelegt; keine Migration; Intervall, Timeout, Name und Verlauf
dieses Checks gehen verloren). Verworfen: B, eine Spalte `tag_off` per Migration.
