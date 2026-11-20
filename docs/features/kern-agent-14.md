# kern-agent-14 — Agent: gescheiterte Abfrage der fehlgeschlagenen Units melden

Roadmap: R-1644.

## Problem

`collectServiceHealth` (`apps/agent/internal/monitor/services_linux.go:49`) fragt die fehlgeschlagenen Units mit `systemctl list-units --state=failed` ab. Scheitert dieser Aufruf (Exit-Status, Timeout, systemctl startet nicht), wertet der Code den Fehler nur als `if err == nil` aus: `failed` bleibt leer, und `health["error"]` fehlt. Der Monitoring-Dienst meldet dann `service_process` im Modus `auto` als „All services OK“. Außerdem setzt er über `others_ok` alle Dienst-Objekte auf ok, obwohl gerade fehlgeschlagene Units unbekannt sind.

## Ziel & Nicht-Ziele

- Scheitert die Abfrage der fehlgeschlagenen Units, trägt der Bericht `error` mit kurzem Grund (`commandFailure`, wie bei `list-units`). Der Check steht dann auf `unknown` mit dem Grund. Das ist dieselbe Semantik wie bei einem gescheiterten `list-units` (Semantik: `docs/admin/monitoring.html`, „Kann der Agent die Dienste nicht abfragen (<code>systemctl list-units</code> scheitert), ist der Check <code>unknown</code> mit dem Grund statt <code>ok</code>.“).
- Gelingt `list-units --all`, bleiben `counts` und die Fakten erhalten. Scheitern beide Aufrufe, gilt der Grund von `list-units`.
- Nicht-Ziel: Änderungen am Monitoring-Dienst. Er wertet `error` schon so aus (`checkers/agent.py`, `ServiceProcessChecker`).

## Betroffene Komponenten & Dateien

`apps/agent/internal/monitor/services_linux.go` und `services_linux_test.go`. Doku: `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `docs/developer/agent.html`, `docs/en/developer/agent.html`.

## Datenmodell / API / Migrationen

Keine. Das Feld `error` im Dienste-Bericht gibt es schon.

## Trade-offs & Alternativen

Man könnte einen eigenen Schlüssel (`failed_error`) einführen und damit den Rest des Berichts als gültig kennzeichnen. Der Server müsste ihn dann neu auswerten, und das wäre ein Vertragswechsel. Empfehlung: `error`, also dieselbe Wirkung wie bei `list-units`.

## Risiken & Rollback

Ein Host, auf dem nur die Abfrage der fehlgeschlagenen Units scheitert, zeigt jetzt `unknown` statt ok. Das ist gewollt. Rollback per Revert.

## Doku-Impact

Der Satz in der Admin-Doku (DE+EN) nennt auch die Abfrage der fehlgeschlagenen Units, ebenso die Agent-Tabelle der Entwickler-Doku (DE+EN). Dazu das Fragment `changelog.d/kern-agent-14.md`.

## Offene Fragen

Keine.
